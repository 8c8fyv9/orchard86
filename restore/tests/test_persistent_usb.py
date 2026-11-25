# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import runpy
import socket
import struct
import threading
import unittest

from persistent_usb import Client, serve

Endpoint = runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / 'local-usb-packet-endpoint.py')))['Endpoint']


class PersistentTests(unittest.TestCase):
    def test_timeout_disables_connection_without_replay(self):
        a, b = socket.socketpair()
        with a, b:
            b.settimeout(1)
            client = Client(a, timeout=.02)
            with self.assertRaises(TimeoutError):
                client.receive()
            with self.assertRaises(RuntimeError):
                client.receive()
            with b.makefile('rb') as reader:
                self.assertEqual(reader.readline().strip(), b'{"operation": "receive"}')
                self.assertEqual(reader.readline(), b'')

    def test_batch_stops_at_first_backpressure(self):
        a, b = socket.socketpair()
        seen = []

        class LimitedEndpoint:
            def handle(self, message):
                seen.append(bytes.fromhex(message['frame_hex']))
                return {'accepted': len(seen) < 2}

        with a, b:
            worker = threading.Thread(target=serve, args=(b, LimitedEndpoint()), daemon=True)
            worker.start()
            client = Client(a, timeout=1)
            try:
                self.assertEqual(client.send_batch([b'a', b'b', b'c']), 1)
                self.assertEqual(seen, [b'a', b'b'])
            finally:
                client.stream.close()
                a.close()
                worker.join(2)
            self.assertFalse(worker.is_alive())

    def test_multiple_packets_on_one_connection(self):
        a, b = socket.socketpair()
        x, y = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with a, b, x, y:
            y.settimeout(1)
            worker = threading.Thread(target=serve, args=(b, Endpoint(x)), daemon=True)
            worker.start()
            client = Client(a, timeout=1)
            try:
                for n in range(16):
                    frame = struct.pack('<IBB', 1, 1, 1) + bytes([n])
                    self.assertTrue(client.send(frame))
                    self.assertEqual(y.recv(32), frame)
                    self.assertIsNone(client.receive())
                    y.send(bytes([1, n]))
                    self.assertEqual(client.receive(), bytes([1, n]))
            finally:
                client.stream.close()
                a.close()
                worker.join(2)
            self.assertFalse(worker.is_alive())
