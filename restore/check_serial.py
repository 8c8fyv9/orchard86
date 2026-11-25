#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Confirm a same-run serial log contains kernel-era output before ASR."""
import argparse
from pathlib import Path


def kernel_output_seen(lines):
    handoff = False
    for line in lines:
        if 'End of iBootStage2 serial output.' in line:
            handoff = True
        elif handoff and ('Darwin Kernel Version ' in line
                          or line.startswith('com.apple.xpc.launchd|')):
            return True
    return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('serial_log', type=Path)
    args = parser.parse_args()
    with args.serial_log.open(errors='replace') as lines:
        if not kernel_output_seen(lines):
            parser.exit(1, 'serial positive control missing after iBoot handoff\n')
    print('post-handoff guest diagnostic output observed')
