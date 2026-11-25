# SPDX-License-Identifier: GPL-3.0-or-later
import argparse
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import run_restore


STUB = '''
import argparse, json, os
from pathlib import Path
p = argparse.ArgumentParser()
for role in ('ipsw', 'qemu', 'firmware', 'output'):
    p.add_argument('--' + role, type=Path, required=True)
a = p.parse_args()
assert all(x.is_absolute() for x in vars(a).values())
assert a.output == Path.cwd() == Path(os.environ['HOME'])
assert 'RESTORE_TEST_SECRET' not in os.environ
mode = a.firmware.read_text()
if mode == 'failed':
    raise SystemExit(23)
if mode == 'empty':
    raise SystemExit(0)
msg = dict(MsgType='StatusMsg', Status=False if mode == 'bool' else 0)
result = dict(returncode=0, timed_out=False, cancelled=False)
doc = dict(schema='restore-v1', final_message=msg, client_result=result,
           receipt_drained=mode != 'pending', guest_finished=True, writers_stopped=True)
s = json.dumps(doc)
if mode == 'duplicate':
    s = s.replace('"Status": 0', '"Status": 9, "Status": 0')
Path('restore-evidence.json').write_text(s)
Path('system.img').write_text('synthetic disk')
if mode == 'alias':
    os.link('system.img', 'aux.img')
elif mode == 'symlink':
    Path('aux.img').symlink_to(a.firmware)
else:
    Path('aux.img').write_text('synthetic aux')
'''


class RestoreAdapterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='restore fixture ')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.args = argparse.Namespace(**{name: root / name for name in
                                           ('output','ipsw','controller','firmware','qemu')})
        with zipfile.ZipFile(self.args.ipsw, 'w') as z:
            z.writestr('BuildManifest.plist', 'synthetic manifest, not real Apple content')
        self.args.controller.write_text('#!' + sys.executable + '\n' + STUB)
        self.args.controller.chmod(0o700)
        self.args.firmware.write_text('pass')
        self.args.qemu.write_text('#!/bin/sh\nexit 99\n')
        self.args.qemu.chmod(0o700)

    def invoke(self, mode):
        self.args.firmware.write_text(mode)
        # Root test harnesses must still exercise the synthetic subprocess. Patch
        # our guard only via the module's os reference; retain the actual UID for file checks.
        actual = os.geteuid()
        with patch.dict(os.environ, RESTORE_TEST_SECRET='should-not-leak'):
            if actual:
                return run_restore.run(self.args)
            with patch.object(run_restore, 'effective_uid', return_value=1234):
                return run_restore.run(self.args)

    def test_reports_controller_handoff_not_independent_boot(self):
        self.assertEqual(self.invoke('pass'), {'controller_handoff_report_accepted': True,
                                               'independent_boot_proven': False})
        self.assertEqual(self.args.output.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(FileExistsError):
            self.invoke('pass')

    def test_exit_failure_is_not_handoff(self):
        with self.assertRaisesRegex(run_restore.RestoreError, 'controller exited 23'):
            self.invoke('failed')

    def test_zero_exit_alone_is_not_handoff(self):
        with self.assertRaises(FileNotFoundError):
            self.invoke('empty')

    def test_bool_status_is_not_zero(self):
        with self.assertRaisesRegex(run_restore.RestoreError, 'invalid-final-status-type'):
            self.invoke('bool')

    def test_receipt_must_be_drained(self):
        with self.assertRaisesRegex(run_restore.RestoreError, 'receipt-drained-unproven'):
            self.invoke('pending')

    def test_output_aliases_rejected(self):
        with self.assertRaisesRegex(run_restore.RestoreError, 'not hardlinked'):
            self.invoke('alias')

    def test_output_symlink_rejected(self):
        with self.assertRaisesRegex(run_restore.RestoreError, 'not a symlink'):
            self.invoke('symlink')

    def test_duplicate_keys_rejected(self):
        with self.assertRaisesRegex(run_restore.RestoreError, 'malformed controller evidence'):
            self.invoke('duplicate')

    def test_requires_explicit_execution(self):
        argv = [sys.executable, run_restore.__file__]
        for name, path in vars(self.args).items():
            argv += ['--' + name, str(path)]
        result = run_restore.subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('explicit --execute required', result.stderr)
        self.assertFalse(self.args.output.exists())
