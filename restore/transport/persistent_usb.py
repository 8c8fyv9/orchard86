# SPDX-License-Identifier: GPL-3.0-or-later
"""Opt-in persistent JSON control stream; never retry an ambiguous request."""
import json
from pathlib import Path
import runpy
import socket
import threading

_api = runpy.run_path(str(Path(__file__).with_name('local-recovery-control-stream.py')))
ControlStream = _api['ControlStream']
LIMIT = _api['MAX_CONTROL_LINE']


def serve(connection, endpoint):
    """Serve one dedicated connection, serially, until EOF or protocol error."""
    with connection, connection.makefile('rb') as reader:
        while line := reader.readline(LIMIT + 1):
            if len(line) > LIMIT or not line.endswith(bytes([10])):
                raise ValueError('invalid control line')
            message = json.loads(line)
            if message.get('operation') == 'send_batch':
                frames = message.get('frames')
                if not isinstance(frames, list) or not 1 <= len(frames) <= 8:
                    raise ValueError('invalid batch size')
                count = 0
                for frame in frames:
                    if not endpoint.handle({'operation': 'send', 'frame_hex': frame})['accepted']:
                        break
                    count += 1
                reply = {'accepted_prefix': count}
            else:
                reply = endpoint.handle(message)
            connection.sendall(json.dumps(reply).encode() + bytes([10]))


class Client:
    def __init__(self, connection, timeout=30):
        self.connection = connection
        connection.settimeout(timeout)
        self.stream = ControlStream(connection)
        self.lock = threading.Lock()
        self.failed = False

    def request(self, message):
        with self.lock:
            if self.failed:
                raise RuntimeError('control connection unusable after failure')
            try:
                self.stream.respond(message)
                return self.stream.receive()
            except (OSError, ValueError):
                self.failed = True
                self.connection.close()
                self.stream.close()
                raise

    def send(self, frame):
        return self.request({'operation': 'send', 'frame_hex': frame.hex()})['accepted']

    def send_batch(self, frames):
        """Return accepted prefix length; callers may retry only the remaining suffix."""
        if not 1 <= len(frames) <= 8:
            raise ValueError('invalid batch size')
        message = {'operation': 'send_batch', 'frames': [f.hex() for f in frames]}
        if len(json.dumps(message).encode()) + 1 > LIMIT:
            raise ValueError('batch exceeds control line limit')
        return self.request(message)['accepted_prefix']

    def receive(self):
        reply = self.request({'operation': 'receive'})
        return bytes.fromhex(reply['reply_hex']) if reply['available'] else None
