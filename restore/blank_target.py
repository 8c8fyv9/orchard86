#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check an offline QCOW2 target before any restore controller writes to it."""
import argparse
import json
from pathlib import Path
import subprocess


def check(tool, target, expected_bytes):
    if target.is_symlink() or not target.is_file():
        raise ValueError('target must be a regular file, not a symlink')
    def inspect(command):
        return json.loads(subprocess.check_output(
            [str(tool), command, '--output=json', '-f', 'qcow2', str(target)]))
    info = inspect('info')
    if (info.get('format') != 'qcow2' or info.get('virtual-size') != expected_bytes
            or info.get('backing-filename') or info.get('full-backing-filename')
            or info.get('snapshots') or info.get('dirty-flag')
            or info.get('format-specific', {}).get('data', {}).get('data-file')):
        raise ValueError('target is not a clean standalone QCOW2 of the expected size')
    end = 0
    for extent in inspect('map'):
        length = extent.get('length')
        if (extent.get('start') != end or type(length) is not int or length <= 0
                or extent.get('depth') != 0 or extent.get('zero') is not True
                or extent.get('data') is not False):
            raise ValueError('target contains data or has an invalid extent map')
        end += length
    if end != expected_bytes:
        raise ValueError('extent map does not span the whole target')
    return {'virtual_bytes': end, 'standalone_zero_map_verified': True}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu-img', type=Path, required=True)
    p.add_argument('--target', type=Path, required=True)
    p.add_argument('--gib', type=int, required=True)
    args = p.parse_args()
    if args.gib <= 0:
        p.error('positive size required')
    try:
        print(json.dumps(check(args.qemu_img.resolve(strict=True), args.target.absolute(), args.gib * 1024**3)))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        p.error(str(exc))


if __name__ == '__main__':
    main()
