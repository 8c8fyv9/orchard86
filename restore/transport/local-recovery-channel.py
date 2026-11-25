# SPDX-License-Identifier: GPL-3.0-or-later
"""One outstanding recovery request; timeout never permits a second send.

No protocol transaction id exists. Recover by receiving the original response,
not by blindly draining then assuming a quiet interval means synchronized.
"""
import socket


class Channel:
    def __init__(self, sock, timeout=15):
        self.sock = sock
        self.sock.settimeout(timeout)
        self.pending = False
        self.poisoned = False

    def send(self, frame):
        if self.poisoned or self.pending:
            raise RuntimeError("channel has unresolved request or invalid response")
        if not isinstance(frame, bytes) or not 6 <= len(frame) <= 4096:
            raise ValueError("invalid recovery frame")
        count = self.sock.send(frame)
        if count != len(frame):
            self.poisoned = True
            raise RuntimeError("incomplete packet send")
        self.pending = True

    def receive(self):
        if self.poisoned or not self.pending:
            raise RuntimeError("no recoverable pending request")
        # Timeout leaves pending=True: receive may be retried, send may not.
        try:
            data = self.sock.recv(4096, socket.MSG_TRUNC)
        except TimeoutError:
            raise
        except OSError as exc:
            self.poisoned = True
            raise ValueError("recovery peer disconnected") from exc
        if not 2 <= len(data) <= 4096:
            self.poisoned = True
            raise ValueError("invalid or closed response")
        self.pending = False
        return data

    def exchange(self, frame):
        self.send(frame)
        return self.receive()
