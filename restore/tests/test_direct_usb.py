# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import runpy
import socket
import struct
import unittest

Endpoint = runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / 'local-usb-packet-endpoint.py')))['Endpoint']


class DirectTests(unittest.TestCase):
    def test_binary_backpressure_and_completion(self):
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with a, b:
            a.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            b.settimeout(1)
            endpoint = Endpoint(a)
            frame = struct.pack('<IBB', 4096, 1, 1) + bytes(4096)
            accepted = 0
            for _ in range(32):
                if not endpoint.send(frame):
                    break
                accepted += 1
            self.assertGreater(accepted, 0)
            self.assertLess(accepted, 32)
            for _ in range(accepted):
                self.assertEqual(b.recv(8192), frame)
            self.assertTrue(endpoint.send(frame))
            self.assertEqual(b.recv(8192), frame)
            self.assertIsNone(endpoint.receive())
            b.send(bytes([1, 129, 0, 255]))
            self.assertEqual(endpoint.receive(), bytes([1, 129, 0, 255]))
            with self.assertRaises(ValueError):
                endpoint.send(frame[:-1])
