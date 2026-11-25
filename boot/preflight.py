#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only input checks, not an installer or a boot launcher."""
import argparse
from pathlib import Path
import zipfile


def input_file(path):
    path = path.resolve(strict=True)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'expected a nonempty regular file: {path}')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='stage', required=True)
    restore = commands.add_parser('restore', help='check IPSW and new output path')
    restore.add_argument('--ipsw', type=Path, required=True)
    restore.add_argument('--output', type=Path, required=True)
    boot = commands.add_parser('boot', help='check disk pair and firmware paths')
    for name in ('system', 'aux', 'firmware'):
        boot.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.stage == 'restore':
            ipsw = input_file(args.ipsw)
            if args.output.exists() or args.output.is_symlink():
                raise ValueError('output path already exists')
            if not args.output.parent.is_dir():
                raise ValueError('output parent must exist')
            with zipfile.ZipFile(ipsw) as archive:
                if not any(x.filename == 'BuildManifest.plist' and x.file_size > 0
                           for x in archive.infolist()):
                    raise ValueError('missing nonempty BuildManifest.plist')
        else:
            files = [input_file(path) for path in (args.system, args.aux, args.firmware)]
            identities = {(st.st_dev, st.st_ino) for st in (path.stat() for path in files)}
            if len(identities) != len(files):
                raise ValueError('system disk, AUX and firmware must be distinct files')
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print(f'{args.stage}: structural preflight passed; no VM started')


if __name__ == '__main__':
    main()
