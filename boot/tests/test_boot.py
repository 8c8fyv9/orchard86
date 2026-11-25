# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

BOOT_CLI = Path(__file__).resolve().parents[1] / 'cli.py'


@unittest.skipIf(os.geteuid() == 0, 'run fixture tests as non-root')
class BootCliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        qemu = self.root / 'qemu'
        qemu.write_text('#!/bin/sh\nexit 0\n')
        qemu.chmod(0o700)
        (self.root / 'firmware').write_bytes(b'fw')
        (self.root / 'aux').write_bytes(b'aux')
        (self.root / 'system').write_bytes(b'QFI\xfb')

    def run_cli(self, *extra):
        args = [
            sys.executable, '-B', str(BOOT_CLI),
            '--qemu', str(self.root / 'qemu'),
            '--firmware', str(self.root / 'firmware'),
            '--system', str(self.root / 'system'),
            '--aux', str(self.root / 'aux'),
            '--output', str(self.root / 'runtime'),
            '--ecid', '0x12',
            *extra,
        ]
        return subprocess.run(args, capture_output=True, text=True, check=False)

    def test_dry_run_preview_and_ssh_vnc(self):
        res = self.run_cli('--display', 'vnc', '--vnc-display', '9', '--ssh-port', '2229')
        self.assertEqual(res.returncode, 0, res.stderr)
        plan = json.loads(res.stdout)
        self.assertEqual(plan['stage'], 'boot')
        self.assertIn('-S', plan['qemu_argv'])
        self.assertIn('vnc=127.0.0.1:9', plan['qemu_argv'])
        self.assertIn('user,id=net0,restrict=on,hostfwd=tcp:127.0.0.1:2229-:22', plan['qemu_argv'])
        self.assertFalse((self.root / 'runtime').exists())

    def test_write_plan_permissions(self):
        plan_dir = self.root / 'plan'
        res = self.run_cli('--write-plan', str(plan_dir))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(stat.S_IMODE(plan_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((plan_dir / 'plan.json').stat().st_mode), 0o600)

    def test_reject_non_qcow2_and_missing_confirm(self):
        (self.root / 'system').write_bytes(b'raw!')
        res = self.run_cli()
        self.assertNotEqual(res.returncode, 0)
        (self.root / 'system').write_bytes(b'QFI\xfb')
        res2 = self.run_cli('--launch-paused')
        self.assertNotEqual(res2.returncode, 0)


if __name__ == '__main__':
    unittest.main()
