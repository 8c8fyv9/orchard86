#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Realize a paused VMApple with empty synthetic input and query QOM."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

if os.geteuid() == 0:
    raise SystemExit('refuse root')
qemu = Path(os.environ['QEMU_BINARY']).resolve(strict=True)
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    for role in ('bios', 'aux', 'root'):
        (p / role).write_bytes(bytes(16384))
    properties = ('recovery-shared-page', 'recovery-rtc-selector', 'recovery-protection')
    args = [str(qemu), '-machine', 'vmapple,accel=tcg,' + ','.join(k + '=on' for k in properties),
            '-cpu', 'max,experimental-pac-init=on', '-m', '1G', '-S', '-nodefaults',
            '-display', 'none', '-serial', 'none', '-monitor', 'none', '-qmp', 'stdio',
            '-bios', str(p / 'bios')]
    for role in ('aux', 'root'):
        args += ['-drive', f'file={p / role},if=pflash,format=raw']
    commands = [{'execute': 'qmp_capabilities', 'id': 'hello'},
                {'execute': 'query-status', 'id': 'state'},
                *[{'execute': 'qom-get', 'arguments': {'path': '/machine', 'property': k}, 'id': k}
                  for k in properties],
                {'execute': 'quit', 'id': 'quit'}]
    result = subprocess.run(args, input=''.join(json.dumps(c) + chr(10) for c in commands),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    replies = {m['id']: m for l in result.stdout.splitlines() if 'id' in (m := json.loads(l))}
    assert replies['state']['return']['status'] == 'prelaunch', replies
    assert all(replies[k].get('return') is True for k in properties), replies
    print('PASS: recovery platform properties and experimental-pac-init realized without starting the guest')
