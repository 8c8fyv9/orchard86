#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run a trusted, explicitly supplied restore controller under the v1 contract."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile

from handoff_gate import evaluate


class RestoreError(ValueError):
    pass


def regular(path, role, *, executable=False, fresh=False):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
        raise RestoreError(f'{role} must be a nonempty regular file (not a symlink)')
    if executable and not os.access(path, os.X_OK):
        raise RestoreError(f'{role} must be executable')
    if fresh and (st.st_nlink != 1 or st.st_uid != os.geteuid()):
        raise RestoreError(f'{role} must be owned by the caller and not hardlinked')
    return st.st_dev, st.st_ino


def evidence(path):
    # Refuse FIFO/device inputs without blocking and never follow output symlinks.
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
        st = os.fstat(f.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
                or st.st_uid != os.geteuid() or st.st_size > 16384):
            raise RestoreError('invalid evidence file')
        raw = f.read(16385)
    if len(raw) > 16384:
        raise RestoreError('evidence file too large')
    try:
        record = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, RecursionError) as exc:
        raise RestoreError('malformed controller evidence') from exc
    expected = {'schema', 'final_message', 'client_result', 'receipt_drained',
                'guest_finished', 'writers_stopped'}
    if type(record) is not dict or set(record) != expected or record['schema'] != 'restore-v1':
        raise RestoreError('unexpected evidence schema')
    record.pop('schema')
    message, result = record['final_message'], record['client_result']
    if (type(message) is not dict or set(message) - {'MsgType','Status','AMRError','ErrorCode'}
            or type(result) is not dict or set(result) != {'returncode','timed_out','cancelled'}):
        raise RestoreError('unexpected status or client fields')
    return evaluate(**record)


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise RestoreError('duplicate evidence key')
        obj[key] = value
    return obj


def effective_uid():
    return os.geteuid()


def run(args):
    if effective_uid() == 0:
        raise RestoreError('controller must not run as root')
    paths = {name: getattr(args, name).absolute()
             for name in ('controller', 'ipsw', 'qemu', 'firmware')}
    inputs = {regular(path, name, executable=name in {'controller', 'qemu'})
              for name, path in paths.items()}
    if len(inputs) != len(paths):
        raise RestoreError('controller and restore inputs must be distinct files')
    with zipfile.ZipFile(paths['ipsw']) as archive:
        entries = [x for x in archive.infolist() if x.filename == 'BuildManifest.plist']
        if len(entries) != 1 or entries[0].file_size == 0:
            raise RestoreError('expected exactly one nonempty BuildManifest.plist')
    output = args.output.parent.resolve(strict=True) / args.output.name
    # Atomic reservation; no reuse even on failure. Keep artifacts for diagnosis.
    output.mkdir(mode=0o700)
    reserved = output.lstat()
    argv = [str(paths['controller']), '--ipsw', str(paths['ipsw']),
            '--qemu', str(paths['qemu']), '--firmware', str(paths['firmware']),
            '--output', str(output)]
    result = subprocess.run(argv, cwd=output, stdin=subprocess.DEVNULL, check=False,
                            env={'PATH': os.defpath, 'HOME': str(output), 'LANG': 'C'},
                            umask=0o077)
    if result.returncode != 0:
        raise RestoreError(f'controller exited {result.returncode}; no handoff')
    finished = output.lstat()
    if (not stat.S_ISDIR(finished.st_mode)
            or (finished.st_dev, finished.st_ino) != (reserved.st_dev, reserved.st_ino)):
        raise RestoreError('controller replaced the reserved output directory')
    gate = evidence(output / 'restore-evidence.json')
    if not gate['handoff_ready']:
        raise RestoreError('handoff rejected: ' + ', '.join(gate['reasons']))
    system = regular(output / 'system.img', 'system disk', fresh=True)
    aux = regular(output / 'aux.img', 'AUX disk', fresh=True)
    if system == aux or {system, aux} & inputs:
        raise RestoreError('system, AUX and restore inputs must be distinct files')
    return {'controller_handoff_report_accepted': True, 'independent_boot_proven': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('controller', 'ipsw', 'qemu', 'firmware', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='allow the supplied controller to run')
    args = parser.parse_args()
    if not args.execute:
        parser.error('explicit --execute required; use preflight.py for a read-only check')
    try:
        print(json.dumps(run(args)))
    except RestoreError as exc:
        parser.exit(1, f'restore: {exc}\n')
    except (OSError, ValueError, zipfile.BadZipFile):
        parser.exit(1, 'restore: invalid or unavailable input/output; no handoff\n')


if __name__ == '__main__':
    main()
