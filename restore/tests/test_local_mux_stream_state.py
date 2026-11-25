#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import runpy
import struct
import unittest
from pathlib import Path
State = runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / "local-mux-stream-state.py")))["State"]
class TestState(unittest.TestCase):
    def test_continuous(self):
        s = State()
        for n in range(8):
            p = s.prepare(6, b"request")
            self.assertEqual(struct.unpack_from("!HH", p, 12), (n, n))
            with self.assertRaises(ValueError):s.prepare(6, b"duplicate")
            self.assertEqual(s.tx, n)
            s.accepted()
            self.assertEqual(s.receive(struct.pack("!IIIHH",6,17,0xfaceface,n,n)+b"r"),(6,b"r"))
    def test_reject_preserves(self):
        s = State()
        with self.assertRaises(ValueError):s.receive(struct.pack("!IIIHH",6,16,0xfaceface,1,0))
        self.assertEqual(s.peer_next,0)
        with self.assertRaises(ValueError):s.accepted()
    def test_wrap(self):
        s=State();s.tx=65535;s.peer_next=65535
        s.prepare(2,b"x");s.accepted();s.receive(struct.pack("!IIIHH",6,16,0xfaceface,65535,0))
        self.assertEqual((s.tx,s.peer_next),(0,0))
if __name__ == "__main__":unittest.main()
