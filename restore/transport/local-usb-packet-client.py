#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""One private control request per packet operation, without coupling IN to OUT."""
import json
import socket

class Client:
    def __init__(self, path):
        self.path = str(path)

    def request(self, message):
        with socket.socket(socket.AF_UNIX) as connection:
            # Bounds a single control exchange, never the guest's USB operation.
            connection.settimeout(30)
            connection.connect(self.path)
            connection.sendall((json.dumps(message) + "\n").encode())
            response = json.loads(connection.makefile("rb").readline(262144))
            if "error" in response:
                raise RuntimeError(response["error"])
            return response

    def send(self, frame):
        return self.request({"operation":"send", "frame_hex":frame.hex()})["accepted"]

    def receive(self):
        response = self.request({"operation":"receive"})
        return bytes.fromhex(response["reply_hex"]) if response["available"] else None
