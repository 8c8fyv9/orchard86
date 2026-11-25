#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import runpy
import socket
import threading
import unittest
api = runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / 'local-recovery-control-stream.py')))

class ControlTests(unittest.TestCase):
    def exchange(self, payload, expected=None):
        a,b=socket.socketpair()
        stream=api['ControlStream'](b)
        def send():
            a.sendall(payload)
            a.shutdown(socket.SHUT_WR)
        t=threading.Thread(target=send);t.start()
        try:
            if expected is None:
                with self.assertRaises(ValueError): stream.receive()
            else: self.assertEqual(stream.receive(),expected)
        finally:
            t.join();stream.close();a.close();b.close()
    def test_realistic_usb_out_hex_envelope(self):
        for size in (16384+36,65535+6):
            message={'operation':'send','frame_hex':('ab'*size)}
            self.exchange((json.dumps(message)+chr(10)).encode(),message)
    def test_oversized_and_unterminated_rejected(self):
        self.exchange(b'x'*(api['MAX_CONTROL_LINE']+1))
        self.exchange(b'x'*(api['MAX_CONTROL_LINE']))

if __name__=='__main__':unittest.main()
