#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic AUX writes: real backing bytes, default-off and bounds failures."""
import os
from pathlib import Path
import struct
import subprocess
import tempfile

if os.geteuid() == 0:
    raise SystemExit("refuse root")
qemu = str(Path(os.environ["QEMU_BINARY"]).resolve(strict=True))
for enabled in (False, True):
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp)
        for name in ("bios", "aux", "root"):
            (p / name).write_bytes(bytes(16384))
        args = [qemu,
                "-machine", "vmapple,uuid=1,accel=tcg", "-cpu", "max", "-m", "1G",
                "-nodefaults", "-display", "none", "-serial", "none", "-monitor", "none",
                "-S", "-qtest", "stdio", "-bios", str(p / "bios"),
                "-drive", f"file={p/'aux'},if=pflash,format=raw",
                "-drive", f"file={p/'root'},if=pflash,format=raw"]
        if enabled:
            args += ["-global", "vmapple-bdif.aux-writable=on"]
        with (p / "stderr").open("w") as err:
            q = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=err, text=True)
            def call(cmd):
                q.stdin.write(cmd + chr(10))
                q.stdin.flush()
                result = q.stdout.readline().strip()
                assert result.startswith("OK"), (cmd, result, (p / "stderr").read_text())
                return result.split()
            def write(addr, data):
                call(f"write {addr:#x} {len(data)} 0x{data.hex()}")
            def read(addr, size):
                return bytes.fromhex(call(f"read {addr:#x} {size}")[1][2:])
            def request(device, sector=1, data_addr=0x70003000, size=512):
                write(0x70002000, struct.pack("<IIII", 1, 0, sector, 0))
                write(0x70004000, bytes([127]))
                desc = (struct.pack("<QII", 0x70002000, 16, 0x10001) +
                        struct.pack("<QII", data_addr, size, 0x10001) +
                        struct.pack("<QII", 0x70004000, 1, 0x20001))
                write(0x70001000, desc)
                call(f"writeq {device + 0x408:#x} 0x70001000")
                return read(0x70004000, 1)[0]
            try:
                payload = bytes(range(256)) * 2
                write(0x70003000, payload)
                assert request(0x30010000) == (0 if enabled else 1)
                expected = payload if enabled else bytes(512)
                assert (p / "aux").read_bytes()[512:1024] == expected
                assert request(0x30000000) == 1  # Root never becomes writable.
                assert (p / "root").read_bytes() == bytes(16384)
                baseline = (p / "aux").read_bytes()
                for sector, addr, size in ((32, 0x70003000, 512),
                                           (1, 0x30000000, 512),
                                           (1, 0x70003000, 0)):
                    assert request(0x30010000, sector, addr, size) == 1
                    assert (p / "aux").read_bytes() == baseline
            finally:
                q.terminate()
                q.wait(timeout=5)
print("AUX write MMIO: PASS (default-off, persisted bytes, root denied, bounds, DMA, empty)")
