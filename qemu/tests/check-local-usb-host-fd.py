#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate private backend socket admission; not a USB transfer test."""
import json
import os
from pathlib import Path
import socket
import subprocess

if os.geteuid() == 0:
    raise SystemExit("Refusing root execution")
qemu = str(Path(os.environ["QEMU_BINARY"]).resolve(strict=True))
base = [qemu, "-machine", "virt,accel=tcg",
        "-cpu", "max", "-m", "128M", "-nodefaults", "-display", "none", "-S",
        "-monitor", "none", "-serial", "none", "-qmp", "stdio"]
for kind, accepted in [(socket.SOCK_SEQPACKET, True), (socket.SOCK_STREAM, False),
                       (socket.SOCK_DGRAM, False)]:
    host, guest = socket.socketpair(socket.AF_UNIX, kind)
    try:
        args = base + ["-device", f"vmapple-virtio-usb-pci,host-fd={guest.fileno()}"]
        args[-1] += ',id=restoreusb'
        commands = [{"execute": "qmp_capabilities"}]
        if accepted:
            commands.append({"execute": "x-query-virtio-status",
                             "arguments": {"path": "/machine/peripheral/restoreusb/virtio-backend"},
                             "id": "usb-status"})
        commands.append({"execute": "quit"})
        r = subprocess.run(args, input="".join(json.dumps(x) + chr(10) for x in commands),
                           text=True, capture_output=True, pass_fds=(guest.fileno(),), timeout=20)
        if accepted:
            assert r.returncode == 0, r.stderr
            messages = [json.loads(line) for line in r.stdout.splitlines()]
            assert not any('error' in message for message in messages), messages
            assert any(message.get('id') == 'usb-status' and 'return' in message
                       for message in messages), messages
        else:
            assert r.returncode != 0 and "host-fd requires" in r.stderr, r.stderr
    finally:
        host.close()
        guest.close()
print("PASS: private seqpacket accepted; stream/datagram rejected")
