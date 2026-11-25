# SPDX-License-Identifier: GPL-3.0-or-later
"""Buffered JSON-line control stream; wire recovery ACK ordering is unchanged."""
import json

# USB payloads can carry 65535 bytes plus the six-byte packet header.
# JSON hex encoding doubles that size; allow bounded envelope overhead.
MAX_CONTROL_LINE = 2 * (65535 + 6) + 1024

class ControlStream:
    def __init__(self, sock):
        # Raw SocketIO.readline issues tiny reads; buffer the input only.
        self.reader = sock.makefile("rb", buffering=16384)
        self.sock = sock

    def receive(self):
        line = self.reader.readline(MAX_CONTROL_LINE + 1)
        if not line or len(line) > MAX_CONTROL_LINE or not line.endswith(bytes([10])):
            raise ValueError("invalid or oversized control request")
        return json.loads(line)

    def respond(self, result):
        # sendall is immediate: no buffered writer needing implicit flush.
        self.sock.sendall(json.dumps(result).encode() + bytes([10]))

    def close(self):
        self.reader.close()
