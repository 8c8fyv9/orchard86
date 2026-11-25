#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Nonblocking owned seqpacket access; no waiting for a USB request response."""
import socket
import struct

class Endpoint:
    def __init__(self, connection):
        if connection.family != socket.AF_UNIX or connection.type != socket.SOCK_SEQPACKET:
            raise ValueError("private UNIX seqpacket required")
        self.connection = connection
        connection.setblocking(False)

    def send(self, frame):
        if not 6 <= len(frame) <= 65542:
            raise ValueError('invalid frame size')
        length, endpoint, kind = struct.unpack_from('<IBB', frame)
        expected = 6 + (length if endpoint < 128 and kind == 1 else 0)
        if len(frame) != expected or endpoint not in (0, 1, 129) or kind not in (1, 2):
            raise ValueError('invalid USB frame')
        try:
            count = self.connection.send(frame)
        except BlockingIOError:
            return False
        if count != len(frame):
            raise ConnectionError('partial seqpacket send')
        return True

    def receive(self):
        try:
            frame = self.connection.recv(65543)
        except BlockingIOError:
            return None
        if not frame:
            raise EOFError('runtime USB backend closed')
        if not 2 <= len(frame) <= 65538:
            raise ValueError('invalid guest response size')
        return frame

    def handle(self, request):
        operation = request.get('operation')
        if operation == 'send':
            return {'accepted': self.send(bytes.fromhex(request['frame_hex']))}
        if operation == 'receive':
            frame = self.receive()
            return {'available': False} if frame is None else {
                'available': True, 'reply_hex': frame.hex()}
        raise ValueError('unsupported packet operation')
