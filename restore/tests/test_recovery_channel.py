# SPDX-License-Identifier: GPL-3.0-or-later
import runpy
import socket
import unittest
from pathlib import Path

Channel = runpy.run_path(str((Path(__file__).resolve().parents[1] / "transport" / 'local-recovery-channel.py')))['Channel']


class RecoveryChannelTests(unittest.TestCase):
    def test_timed_out_request_must_receive_original_reply(self):
        client, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        with client, peer:
            channel = Channel(client, timeout=.02)
            original, following = b'frame1', b'frame2'
            with self.assertRaises(TimeoutError):
                channel.exchange(original)
            self.assertEqual(peer.recv(32), original)
            with self.assertRaises(RuntimeError):
                channel.send(following)
            peer.send(b'OK')
            self.assertEqual(channel.receive(), b'OK')
            channel.send(following)
            self.assertEqual(peer.recv(32), following)
