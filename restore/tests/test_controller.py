# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

RESTORE_DIR = Path(__file__).resolve().parents[1]
if str(RESTORE_DIR) not in sys.path:
    sys.path.insert(0, str(RESTORE_DIR))

import firmware_usb
import img4
import tss


class ControllerUnitTests(unittest.TestCase):
    def test_img4_wrap_and_large(self):
        payload = img4.tlv(0x30, img4.tlv(0x16, b'IM4P') + img4.tlv(0x16, b'ibss'))
        ticket = img4.tlv(0x30, img4.tlv(0x16, b'IM4M'))
        gen = b'\x01\x02\x03\x04\x05\x06\x07\x08'
        wrapped = img4.wrap(payload, ticket, gen)
        self.assertTrue(wrapped.startswith(b'\x30'))
        self.assertIn(b'IMG4', wrapped)
        self.assertIn(b'IM4R', wrapped)
        self.assertEqual(wrapped, img4.wrap_large(payload, ticket, gen))

    def test_tss_request_and_response(self):
        manifest = {
            'BuildIdentities': [{
                'Info': {'DeviceClass': 'vma2macosap', 'Variant': 'Customer Erase Install (IPSW)', 'RestoreBehavior': 'Erase'},
                'ApChipID': '0xfe00',
                'ApBoardID': '0x20',
                'ApSecurityDomain': '0x01',
                'Manifest': {'iBSS': {'Trusted': True, 'Digest': b'\xaa' * 48, 'Info': {}}},
            }]
        }
        ident = tss.select_identity(manifest)
        req = tss.build_request(ident, 1, b'\xbb' * 32)
        self.assertEqual(req['ApECID'], 1)
        self.assertEqual(req['ApChipID'], 0xFE00)
        body = b'STATUS=0&MESSAGE=SUCCESS\n' + plistlib.dumps({'ApImg4Ticket': b'\x30\x00'})
        self.assertEqual(tss.parse_response(body), b'\x30\x00')
        pol_req = tss.build_policy_request(ident, 1, b'\xbb' * 32, img4.MINIMAL_LPOL_IM4P, b'\x30\x00')
        self.assertFalse(pol_req['Ap,LocalBoot'])
        self.assertIn('Ap,LocalPolicy', pol_req)
        self.assertIn('Ap,NextStageIM4MHash', pol_req)

    def test_bdif_dfu_and_stage2_socketpair(self):
        host, dev = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        seen = []

        def fake_device():
            while True:
                try:
                    pkt = dev.recv(4096)
                except OSError:
                    break
                if not pkt:
                    break
                seen.append(pkt)
                # Reply with valid EP0/ACK frame
                if len(pkt) >= 6 and pkt[5] == 1 and pkt[4] == 4:
                    dev.send(bytes([1, 4]))
                elif len(pkt) >= 7 and pkt[5] == 1 and pkt[4] == 0 and pkt[6] == 0xA1:
                    # DFU GETSTATUS: kind1/channel0 + 6-byte status
                    dev.send(bytes([1, 0, 0, 0, 0, 0, 5, 0]))
                elif len(pkt) >= 7 and pkt[5] == 1 and pkt[4] == 0 and pkt[6] == 0xC0:
                    # getenv filesize response
                    dev.send(bytes([1, 0]) + hex(len(b'FAKE_IBEC_DATA')).encode('ascii') + b'\x00')
                else:
                    dev.send(bytes([1, 0]))

        t = threading.Thread(target=fake_device, daemon=True)
        t.start()
        try:
            tr = firmware_usb.BdifRecoveryTransport(host, timeout=2.0)
            tr.upload_dfu(b'FAKE_IBSS_DATA')
            tr.stage2_select()
            tr.upload_bulk(b'FAKE_IBEC_DATA')
            tr.send_command('bootx')
        finally:
            host.close()
            dev.close()
            t.join(timeout=2.0)
        self.assertTrue(any(b'getenv filesize' in p for p in seen))
        self.assertTrue(any(b'bootx\x00' in p for p in seen))

    def test_controller_dry_run_and_cli_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('qemu', 'qemu-img', 'idevicerestore'):
                f = root / name
                f.write_text('#!/bin/sh\nexit 0\n')
                f.chmod(0o700)
            (root / 'fw.bin').write_bytes(b'fw')
            manifest = {
                'ProductVersion': '13.6',
                'ProductBuildVersion': '22G120',
                'BuildIdentities': [{
                    'Info': {'DeviceClass': 'vma2macosap', 'Variant': 'Customer Erase Install (IPSW)', 'RestoreBehavior': 'Erase'},
                    'ApChipID': '0xfe00', 'ApBoardID': '0x20', 'ApSecurityDomain': '0x01',
                    'Manifest': {},
                }]
            }
            with zipfile.ZipFile(root / 'test.ipsw', 'w') as zf:
                zf.writestr('BuildManifest.plist', plistlib.dumps(manifest))

            res = subprocess.run([
                sys.executable, '-B', str(RESTORE_DIR / 'controller.py'),
                '--ipsw', str(root / 'test.ipsw'),
                '--qemu', str(root / 'qemu'),
                '--qemu-img', str(root / 'qemu-img'),
                '--idevicerestore', str(root / 'idevicerestore'),
                '--firmware', str(root / 'fw.bin'),
                '--output', str(root / 'out'),
                '--dry-run',
            ], capture_output=True, text=True, check=False)
            self.assertEqual(res.returncode, 0, res.stderr)
            info = json.loads(res.stdout)
            self.assertTrue(info['dry_run'])
            self.assertEqual(info['product_build'], '22G120')


if __name__ == '__main__':
    unittest.main()
