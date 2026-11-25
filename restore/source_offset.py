#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Observe a Linux restore client's source file offset, not guest progress."""
import argparse
import json
import os
from pathlib import Path


def observe(pid, fd, source):
    expected = source.stat()
    proc = Path('/proc') / str(pid)
    descriptor = proc / 'fd' / str(fd)
    identity = (expected.st_dev, expected.st_ino)
    def verify():
        current = descriptor.stat()
        if (current.st_dev, current.st_ino) != identity:
            raise ValueError('descriptor is not the specified source file')
    # A pidfd lets us reject a sample if the original process exited mid-read.
    import select
    process = os.pidfd_open(pid)
    try:
        verify()
        lines = (proc / 'fdinfo' / str(fd)).read_text().splitlines()
        position = int(next(line.split(':', 1)[1] for line in lines if line.startswith('pos:')))
        verify()
        poll = select.poll()
        poll.register(process, select.POLLIN)
        if poll.poll(0):
            raise ValueError('source process exited during observation')
        return {'host_read_offset_bytes': position, 'source_bytes': expected.st_size}
    finally:
        os.close(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid', type=int)
    parser.add_argument('fd', type=int)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    if args.pid <= 0 or args.fd < 0:
        parser.error('invalid PID or descriptor')
    try:
        print(json.dumps(observe(args.pid, args.fd, args.source)))
    except (OSError, ValueError, StopIteration) as exc:
        parser.error(str(exc) or 'descriptor position not available')


if __name__ == '__main__':
    main()
