#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic real-socket recovery MMIO test; no firmware inputs."""
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile

if os.geteuid() == 0:
    raise SystemExit("refuse root")
qemu = str(Path(os.environ["QEMU_BINARY"]).resolve(strict=True))
with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    for name in ("bios", "aux", "root"):
        (p / name).write_bytes(bytes(16384))
    host, guest = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    host.settimeout(3)
    args = [qemu,
            "-machine", "vmapple,uuid=1,accel=tcg", "-cpu", "max", "-m", "1G",
            "-nodefaults", "-display", "none", "-serial", "none", "-monitor", "none",
            "-S", "-qtest", "stdio", "-bios", str(p / "bios"),
            "-drive", f"file={p/'aux'},if=pflash,format=raw",
            "-drive", f"file={p/'root'},if=pflash,format=raw",
            "-global", f"vmapple-bdif.recovery-host-fd={guest.fileno()}"]
    with (p / "stderr").open("w") as err:
        q = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=err, text=True, pass_fds=(guest.fileno(),))
        guest.close()
        def call(command):
            q.stdin.write(command + "\n")
            q.stdin.flush()
            answer = q.stdout.readline().strip()
            assert answer.startswith("OK"), (command, answer, (p / "stderr").read_text())
            return answer.split()
        def write(addr, data):
            call(f"write {addr:#x} {len(data)} 0x{data.hex()}")
        def read(addr, size):
            return bytes.fromhex(call(f"read {addr:#x} {size}")[1][2:])
        desc, buffer = 0x70001000, 0x70002000
        def post(queue, data_addr, length, flags):
            call(f"writel 0x30100410 {queue}")
            write(desc, struct.pack("<QIHH", data_addr, length, 1, flags))
            call(f"writeq 0x30100408 {desc:#x}")
        def flags():
            return struct.unpack("<QIHH", read(desc, 16))[3]
        try:
            assert int(call("readl 0x30100004")[1], 0) == 0x1a01
            call("writel 0x30100404 1")
            post(0, buffer, 2062, 2)
            assert flags() == 2  # No fabricated connection.
            frame = struct.pack("<IBB", 0, 128, 2)
            host.send(frame)
            assert int(call("readl 0x30100010")[1], 0) == 1
            assert flags() == 3 and read(buffer, len(frame)) == frame
            write(buffer, b"\x04\x00")
            post(1, buffer, 2, 0)
            assert flags() == 1 and host.recv(4096) == b"\x04\x00"
            # Completed descriptors cannot retransmit.
            call(f"writeq 0x30100408 {desc:#x}")
            host.setblocking(False)
            try:
                host.recv(4096)
                raise AssertionError("replayed completed response")
            except BlockingIOError:
                pass
            host.settimeout(3)
            # Late host request is delivered by native busy polling.
            setup = struct.pack("<IBB", 8, 0, 1) + struct.pack("<BBHHH", 128, 6, 256, 0, 18)
            post(0, buffer, 2062, 2)
            host.send(setup)
            assert int(call("readl 0x30100010")[1], 0) == 1
            assert flags() == 3 and read(buffer, len(setup)) == setup
            # A new stage may post a different valid RX buffer without reset.
            post(0, buffer, 2062, 2)
            write(desc + 64, struct.pack("<QIHH", buffer + 4096, 1048582, 1, 2))
            host.send(setup)
            call(f"writeq 0x30100408 {desc + 64:#x}")
            assert int(call("readl 0x30100010")[1], 0) == 1
            assert read(buffer + 4096, len(setup)) == setup
            # Bad selectors, direction, MMIO aliases, overlap cannot complete.
            for queue, addr, length, bits in ((2, buffer, 32, 2), (0, buffer, 32, 0),
                                             (0, 0x30100000, 32, 2), (0, desc, 32, 2),
                                             (1, buffer, 4097, 0)):
                post(queue, addr, length, bits)
                assert flags() == bits
            call("writel 0x30100404 0")
            post(0, buffer, 2062, 2)
            host.send(frame)
            assert flags() == 2
            print("recovery host MMIO: PASS (real bidirectional socket, late delivery, no fixture, replay, DMA bounds, config)")
        finally:
            q.terminate()
            q.wait(timeout=5)
            host.close()
