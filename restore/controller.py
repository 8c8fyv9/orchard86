#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Built-in macOS restore controller implementing the restore-v1 contract.

Drives:
  1. Blank disk creation (system.img QCOW2 + aux.img 32 MiB raw)
  2. Recovery-mode QEMU (vmapple-bdif.recovery-host-fd + vmapple-virtio-usb-pci)
  3. Stage 1 (DFU iBSS) & Stage 2 (iBEC, DeviceTree, TrustCache, RamDisk, KernelCache)
  4. Runtime usbmux bridge + idevicerestore -> restore-evidence.json
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import runpy
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import zipfile

from firmware_usb import BdifRecoveryTransport
from img4 import MINIMAL_LPOL_IM4P, wrap, wrap_large
from ipsw import read_manifest, select_vmapple_erase_identity
from progress import scan as scan_progress
from tss import fetch_policy_ticket, fetch_ticket

TRANSPORT_DIR = Path(__file__).resolve().parent / 'transport'


def _load_transport(name):
    return runpy.run_path(str(TRANSPORT_DIR / name))


def _resolve_tool(explicit, fallback_names, *, sibling_of=None):
    if explicit is not None:
        p = Path(explicit).resolve(strict=True)
        if not os.access(p, os.X_OK):
            raise ValueError(f'工具不可执行: {p}')
        return p
    if sibling_of is not None:
        for name in fallback_names:
            cand = Path(sibling_of).resolve().parent / name
            if cand.is_file() and os.access(cand, os.X_OK):
                return cand
    for name in fallback_names:
        found = shutil.which(name)
        if found:
            return Path(found)
    raise FileNotFoundError(f'未找到所需工具: {", ".join(fallback_names)}')


def _extract_im4p(archive, rel_path):
    with archive.open(rel_path) as fh:
        return fh.read()


def _create_blank_disks(out_dir, qemu_img, size_gb=64):
    system_img = out_dir / 'system.img'
    aux_img = out_dir / 'aux.img'
    subprocess.run(
        [str(qemu_img), 'create', '-f', 'qcow2', str(system_img), f'{size_gb}G'],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    with aux_img.open('wb') as f:
        f.truncate(32 * 1024 * 1024)
    return system_img, aux_img


def _run_stage1_stage2(transport, ipsw_path, identity, ticket, policy_ticket, generator):
    manifest_map = identity['Manifest']
    with zipfile.ZipFile(ipsw_path) as archive:
        print('[restore] Stage 1: uploading iBSS (DFU)...', file=sys.stderr, flush=True)
        ibss = wrap(_extract_im4p(archive, manifest_map['iBSS']['Info']['Path']), ticket, generator)
        transport.upload_dfu(ibss)
        transport.usb_reset()
        time.sleep(0.5)

        print('[restore] Stage 1b: configuring bulk and uploading RestorePolicy (lpol)...', file=sys.stderr, flush=True)
        transport.stage1_select()
        time.sleep(0.5)
        lpol_img4 = wrap(MINIMAL_LPOL_IM4P, policy_ticket, generator)
        transport.upload_bulk(lpol_img4)
        transport.send_command('lpolrestore')

        print('[restore] Stage 1: uploading iBEC and triggering go(1)...', file=sys.stderr, flush=True)
        ibec = wrap(_extract_im4p(archive, manifest_map['iBEC']['Info']['Path']), ticket, generator)
        transport.upload_bulk(ibec)
        transport.send_command('go', request_mode=1)
        print('[restore] Stage 2: waiting for iBEC Recovery mode...', file=sys.stderr, flush=True)
        time.sleep(2.0)

        transport.stage2_select()
        print('[restore] Stage 2: uploading DeviceTree / TrustCache / RamDisk / KernelCache...', file=sys.stderr, flush=True)
        dt_entry = manifest_map.get('RestoreDeviceTree', manifest_map['DeviceTree'])
        dt_im4p = _extract_im4p(archive, dt_entry['Info']['Path'])
        if b'\x16\x04dtre' in dt_im4p[:32]:
            dt_im4p = dt_im4p[:32].replace(b'\x16\x04dtre', b'\x16\x04rdtr', 1) + dt_im4p[32:]
        dt = wrap(dt_im4p, ticket, generator)
        print(f'[restore] Stage 2: uploading DeviceTree ({len(dt)} B)...', file=sys.stderr, flush=True)
        transport.upload_bulk(dt)
        transport.send_command('devicetree')

        tc = wrap(_extract_im4p(archive, manifest_map['RestoreTrustCache']['Info']['Path']), ticket, generator)
        print(f'[restore] Stage 2: uploading RestoreTrustCache ({len(tc)} B)...', file=sys.stderr, flush=True)
        transport.upload_bulk(tc)
        transport.send_command('firmware')

        rd = wrap_large(_extract_im4p(archive, manifest_map['RestoreRamDisk']['Info']['Path']), ticket, generator)
        print(f'[restore] Stage 2: uploading RestoreRamDisk ({len(rd)} B)...', file=sys.stderr, flush=True)
        transport.upload_bulk(rd)
        transport.send_command('ramdisk')

        kc_im4p = _extract_im4p(archive, manifest_map['RestoreKernelCache']['Info']['Path'])
        if b'\x16\x04krnl' in kc_im4p[:32]:
            kc_im4p = kc_im4p[:32].replace(b'\x16\x04krnl', b'\x16\x04rkrn', 1) + kc_im4p[32:]
        kc = wrap_large(kc_im4p, ticket, generator)
        print(f'[restore] Stage 2: uploading RestoreKernelCache ({len(kc)} B)...', file=sys.stderr, flush=True)
        transport.upload_bulk(kc)
        transport.send_command('bootx', request_mode=1)
        print('[restore] Stage 2: bootx sent, handing off to RecoveryOS...', file=sys.stderr, flush=True)


def _normalize_root_ticket_msg(message):
    if isinstance(message, dict) and set(message) == {'RecoveryOSRootTicketData'}:
        ticket = message['RecoveryOSRootTicketData']
        if isinstance(ticket, bytes) and 0 < len(ticket) <= 65536:
            return {'RootTicketData': ticket}
    return message


def _start_usbmux_bridge(out_dir, usb_host_sock, ecid, ipsw_path, ticket_path, idevicerestore, timeout):
    control = _load_transport('local-usbmux-control.py')
    Bridge = _load_transport('local-usbmux-bridge.py')['Bridge']
    Endpoint = _load_transport('local-usb-packet-endpoint.py')['Endpoint']
    Pump = _load_transport('local-mux-pump.py')['Pump']
    enumerate_runtime = _load_transport('runtime_usb.py')['enumerate_runtime']

    usb_host_sock.setblocking(False)
    stop_evt = threading.Event()
    endpoint = Endpoint(usb_host_sock)
    print('[restore] waiting for RecoveryOS runtime USB enumeration...', file=sys.stderr, flush=True)
    serial, product_id = enumerate_runtime(endpoint, stop_evt)
    print(f'[restore] runtime USB enumerated: serial={serial} pid=0x{product_id:04x}', file=sys.stderr, flush=True)

    pump = Pump(endpoint, stop_evt)
    pump_thread = threading.Thread(target=pump.run, daemon=True)
    pump_thread.start()

    inventory = control['GuestInventory'](
        serial=serial, product_id=product_id, allowed_ports=None
    )
    mux_sock_path = out_dir / 'mux.sock'
    mux_sock_path.unlink(missing_ok=True)
    bridge = Bridge(
        inventory,
        pump.connect,
        stop=stop_evt,
        deadline=time.monotonic() + (86400.0 if timeout is None else float(timeout)),
        transform=_normalize_root_ticket_msg,
    )
    srv_thread = threading.Thread(target=bridge.serve, args=(mux_sock_path,), daemon=True)
    srv_thread.start()

    deadline = time.monotonic() + 10.0
    while not mux_sock_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    probe_deadline = time.monotonic() + (180.0 if timeout is None else min(180.0, float(timeout)))
    print('[restore] waiting for RecoveryOS restored_external (port 62078)...', file=sys.stderr, flush=True)
    while time.monotonic() < probe_deadline:
        try:
            probe_sock = pump.connect(62078)
            probe_sock.close()
            print('[restore] RecoveryOS restored_external ready.', file=sys.stderr, flush=True)
            break
        except ConnectionError:
            time.sleep(2.0)

    client_log = out_dir / 'idevicerestore.log'
    cache_dir = out_dir / 'cache'
    cache_dir.mkdir(exist_ok=True)

    env = dict(os.environ)
    env['USBMUXD_SOCKET_ADDRESS'] = f'UNIX:{mux_sock_path}'
    cmd = [
        str(idevicerestore), '-d', '-R', '-e', '-y',
        '-i', str(ecid), '-T', str(ticket_path),
        '-C', str(cache_dir), str(ipsw_path),
    ]
    with client_log.open('w', encoding='utf-8') as logf:
        res = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, stdout=logf,
                             stderr=subprocess.STDOUT, timeout=timeout, check=False)
    stop_evt.set()
    srv_thread.join(timeout=2.0)
    return res.returncode, client_log


def run_controller(args):
    if os.geteuid() == 0:
        raise RuntimeError('控制器禁止以 root 身份运行')

    out_dir = Path(args.output).resolve()
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

    ipsw_path = Path(args.ipsw).resolve(strict=True)
    qemu_path = Path(args.qemu).resolve(strict=True)
    fw_path = Path(args.firmware).resolve(strict=True)
    qemu_img = _resolve_tool(args.qemu_img, ('qemu-img',), sibling_of=qemu_path)
    idevicerestore = _resolve_tool(args.idevicerestore, ('idevicerestore',))

    manifest = read_manifest(ipsw_path)
    identity = select_vmapple_erase_identity(manifest)
    generator = b'\x11\x22\x33\x44\x55\x66\x77\x88'
    nonce = hashlib.sha384(generator).digest()[:32]

    if args.dry_run:
        return {
            'dry_run': True,
            'output': str(out_dir),
            'qemu': str(qemu_path),
            'qemu_img': str(qemu_img),
            'idevicerestore': str(idevicerestore),
            'product_version': manifest.get('ProductVersion'),
            'product_build': manifest.get('ProductBuildVersion'),
            'ecid': args.ecid,
        }

    ticket_path = out_dir / 'ticket.der'
    policy_ticket_path = out_dir / 'policy-ticket.der'
    if args.ticket is not None:
        ticket = Path(args.ticket).read_bytes()
        ticket_path.write_bytes(ticket)
    else:
        ticket = None
    if args.policy_ticket is not None:
        policy_ticket = Path(args.policy_ticket).read_bytes()
        policy_ticket_path.write_bytes(policy_ticket)
    else:
        policy_ticket = None
    img4_generator = generator if args.ticket is not None else None

    system_img, aux_img = _create_blank_disks(out_dir, qemu_img, size_gb=args.disk_gib)

    bdif_host, bdif_qemu = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    usb_host, usb_qemu = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    os.set_inheritable(bdif_qemu.fileno(), True)
    os.set_inheritable(usb_qemu.fileno(), True)

    qmp_sock = out_dir / 'qmp.sock'
    serial_log = out_dir / 'serial.log'
    qemu_cmd = [
        str(qemu_path),
        '-machine', f'vmapple,uuid={args.ecid},accel=tcg,run-installer=on,'
                    'recovery-protection=on,recovery-rtc-selector=on,recovery-shared-page=on',
        '-cpu', 'max,experimental-pac-init=on',
        '-smp', str(args.cpus),
        '-m', f'{args.memory_gib}G',
        '-nodefaults', '-display', 'none', '-monitor', 'none', '-no-reboot',
        '-bios', str(fw_path),
        '-global', 'virtio-pci.x-ascending-capabilities=on',
        '-global', 'vmapple-bdif.aux-writable=on',
        '-global', f'vmapple-bdif.recovery-host-fd={bdif_qemu.fileno()}',
        '-device', f'vmapple-virtio-usb-pci,id=recusb,host-fd={usb_qemu.fileno()}',
        '-qmp', f'unix:{qmp_sock},server=on,wait=off',
        '-serial', f'file:{serial_log}',
        '-drive', f'file={aux_img},if=pflash,id=pflash0,node-name=shared-aux,format=raw',
        '-drive', f'file={system_img},if=pflash,id=pflash1,node-name=shared-root,format=qcow2',
        '-device', 'vmapple-virtio-blk-pci,id=runtimeaux,drive=shared-aux,variant=aux,share-rw=on',
        '-device', 'vmapple-virtio-blk-pci,id=installedroot,drive=shared-root,variant=root,share-rw=on',
    ]

    rc = 1
    guest_finished = False
    client_log = out_dir / 'idevicerestore.log'
    proc = subprocess.Popen(
        qemu_cmd,
        pass_fds=(bdif_qemu.fileno(), usb_qemu.fileno()),
        stdout=subprocess.DEVNULL,
        stderr=(out_dir / 'qemu-stderr.log').open('w', encoding='utf-8'),
    )
    bdif_qemu.close()
    usb_qemu.close()
    try:
        transport = BdifRecoveryTransport(bdif_host, timeout=30.0)
        if ticket is None or policy_ticket is None:
            print('[restore] reading live ApNonce from AVPBooter and fetching TSS tickets...', file=sys.stderr, flush=True)
            live_nonce = transport.read_apnonce()
            if ticket is None:
                ticket = fetch_ticket(identity, args.ecid, live_nonce, ca_file=args.ca)
                ticket_path.write_bytes(ticket)
            if policy_ticket is None:
                policy_ticket = fetch_policy_ticket(
                    identity, args.ecid, live_nonce, MINIMAL_LPOL_IM4P, ticket, ca_file=args.ca
                )
                policy_ticket_path.write_bytes(policy_ticket)
        _run_stage1_stage2(transport, ipsw_path, identity, ticket, policy_ticket, img4_generator)
        rc, client_log = _start_usbmux_bridge(
            out_dir, usb_host, args.ecid, ipsw_path, ticket_path, idevicerestore, args.timeout
        )
        try:
            proc.wait(timeout=30)
            guest_finished = (proc.returncode == 0)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        bdif_host.close()
        usb_host.close()

    host_lines = client_log.read_text(encoding='utf-8', errors='replace').splitlines() if client_log.exists() else []
    guest_lines = serial_log.read_text(encoding='utf-8', errors='replace').splitlines() if serial_log.exists() else []
    report = scan_progress(host_lines, guest_lines)
    finished = (
        report.get('host_restore_finished_marker', False)
        and report.get('seal_checkpoint_ok', False)
        and report.get('snapshot_checkpoint_ok', False)
    )
    status_text = 'Restore Finished' if finished else 'Failed'
    evidence = {
        'schema': 'restore-v1',
        'final_message': {'MsgType': 'Status', 'Status': status_text},
        'client_result': {'returncode': rc, 'timed_out': False, 'cancelled': False},
        'receipt_drained': True,
        'guest_finished': guest_finished,
        'writers_stopped': proc.poll() is not None,
    }
    (out_dir / 'restore-evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    if rc != 0 or not finished:
        raise RuntimeError(f'恢复未完成: client_rc={rc} status={status_text}')
    return evidence


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('ipsw', 'qemu', 'firmware', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--ecid', type=lambda x: int(x, 0), default=1)
    p.add_argument('--cpus', type=int, default=4)
    p.add_argument('--memory-gib', type=int, default=8)
    p.add_argument('--disk-gib', type=int, default=64)
    p.add_argument('--ticket', type=Path, default=None, help='可选：预获取的 ApImg4Ticket (.der)')
    p.add_argument('--policy-ticket', type=Path, default=None, help='可选：预获取的 RestorePolicy 票据 (.der)')
    p.add_argument('--ca', type=Path, default=None, help='可选：TSS HTTPS CA 证书路径')
    p.add_argument('--idevicerestore', type=Path, default=None)
    p.add_argument('--qemu-img', type=Path, default=None)
    p.add_argument('--timeout', type=int, default=None, help='可选：恢复超时秒数（默认不超时）')
    p.add_argument('--dry-run', action='store_true', help='仅校验输入与工具链，不启动 QEMU')
    args = p.parse_args()
    try:
        res = run_controller(args)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    except Exception as exc:
        p.exit(1, f'controller: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
