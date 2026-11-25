#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""mac27 独立启动入口（run-installer=off）：支持参数预览、计划写出与显式启动。"""
import argparse
import json
import os
from pathlib import Path
import subprocess

from preflight import input_file


def safe_path(path):
    if any(c in str(path) for c in (',', '\n', '\r')):
        raise ValueError('QEMU 路径包含不支持的字符')
    return str(path)


def build(args):
    qemu, system, aux, firmware = map(
        input_file, (args.qemu, args.system, args.aux, args.firmware)
    )
    if len({(s.st_dev, s.st_ino) for s in (p.stat() for p in (qemu, system, aux, firmware))}) != 4:
        raise ValueError('QEMU、系统盘、AUX 与固件必须是 4 个不同的文件')
    with system.open('rb') as stream:
        if stream.read(4) != bytes([81, 70, 73, 251]):
            raise ValueError('系统盘必须是 QCOW2 格式')
    if not 0 < args.ecid < 2**64 or args.cpus < 1 or args.memory_gib < 1:
        raise ValueError('无效的 ECID、vCPU 数量或内存大小')

    output = args.output.parent.resolve(strict=True) / args.output.name
    if output.exists() or output.is_symlink():
        raise ValueError('运行目录必须尚不存在')
    q, root, aux_p, fw, o = map(safe_path, (qemu, system, aux, firmware, output))
    if len(os.fsencode(o + '/console.sock')) >= 108:
        raise ValueError('运行目录路径过长，超出 Unix socket 长度限制')

    display_args = ['-display', 'none']
    if args.display == 'vnc':
        display_args = ['-display', f'vnc=127.0.0.1:{args.vnc_display}']

    net_args = []
    if args.ssh_port is not None:
        if not 1 <= args.ssh_port <= 65535:
            raise ValueError('SSH 转发端口必须在 1..65535 之间')
        net_args = [
            '-netdev', f'user,id=net0,restrict=on,hostfwd=tcp:127.0.0.1:{args.ssh_port}-:22',
            '-device', 'virtio-net-pci,netdev=net0,romfile=',
        ]

    machine_opts = (
        f'vmapple,uuid={args.ecid},accel=tcg,run-installer=off,'
        'recovery-protection=on,recovery-rtc-selector=on,recovery-shared-page=on'
    )
    mem_args = []
    if args.display == 'vnc':
        machine_opts += ',gfx-reims=1,memory-backend=ram0'
        mem_args = ['-object', f'memory-backend-memfd,id=ram0,size={args.memory_gib}G']

    argv = [
        q,
        '-machine',
        machine_opts,
        '-cpu', 'max,experimental-pac-init=on',
        '-smp', str(args.cpus),
        '-m', f'{args.memory_gib}G',
        *mem_args,
        '-nodefaults',
        *display_args,
        '-monitor', 'none',
        '-no-reboot',
        '-bios', fw,
        '-global', 'virtio-pci.x-ascending-capabilities=on',
        '-qmp', f'unix:{o}/qmp.sock,server=on,wait=off',
        '-chardev', f'socket,id=console,path={o}/console.sock,server=on,wait=off,logfile={o}/serial.log',
        '-serial', 'chardev:console',
        '-drive', f'file={aux_p},if=pflash,id=pflash0,node-name=shared-aux,format=raw',
        '-drive', f'file={root},if=pflash,id=pflash1,node-name=shared-root,format=qcow2',
        '-device', 'vmapple-virtio-blk-pci,id=runtimeaux,drive=shared-aux,variant=aux,share-rw=on',
        '-device', 'vmapple-virtio-blk-pci,id=installedroot,drive=shared-root,variant=root,share-rw=on',
        *net_args,
    ]
    if not args.run_immediately:
        argv.insert(argv.index('-no-reboot'), '-S')
    return output, argv


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('qemu', 'system', 'aux', 'firmware', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--ecid', type=lambda x: int(x, 0), required=True)
    p.add_argument('--cpus', type=int, default=4)
    p.add_argument('--memory-gib', type=int, default=8)
    p.add_argument('--display', choices=('none', 'vnc'), default='none')
    p.add_argument('--vnc-display', type=int, default=9, help='回环 VNC 显示编号（默认 9 -> 5909）')
    p.add_argument('--ssh-port', type=int, default=None, help='可选：将客体 22 端口映射到 127.0.0.1:PORT')
    p.add_argument('--confirm-offline-pair', action='store_true', help='确认所传 system/aux 已停机且配对')
    p.add_argument('--write-plan', type=Path, default=None, help='将启动计划写入新目录（不启动 VM）')
    p.add_argument('--launch-paused', action='store_true', help='以暂停态(-S)启动 QEMU')
    p.add_argument('--run-immediately', action='store_true', help='配合 --launch-paused 不加 -S 直接运行')
    args = p.parse_args()

    try:
        output, argv = build(args)
        plan = {
            'stage': 'boot',
            'output_dir': str(output),
            'display': args.display,
            'ssh_port': args.ssh_port,
            'qemu_argv': argv,
        }
        if args.write_plan is not None:
            if args.launch_paused:
                raise ValueError('--write-plan 与 --launch-paused 互斥')
            plan_dir = args.write_plan.parent.resolve(strict=True) / args.write_plan.name
            if plan_dir.exists() or plan_dir.is_symlink():
                raise ValueError('计划目录必须尚不存在')
            os.umask(0o077)
            plan_dir.mkdir(mode=0o700)
            plan_file = plan_dir / 'plan.json'
            fd = os.open(plan_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
            print(str(plan_file))
            return 0

        if not args.launch_paused:
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            return 0

        if not args.confirm_offline_pair:
            raise ValueError('实际启动必须传入 --confirm-offline-pair')
        if os.geteuid() == 0:
            raise ValueError('禁止以 root 身份启动 QEMU')
        if not os.access(argv[0], os.X_OK):
            raise ValueError('QEMU 不可执行')
        os.umask(0o077)
        output.mkdir(mode=0o700)
        return subprocess.call(argv)
    except (OSError, ValueError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
