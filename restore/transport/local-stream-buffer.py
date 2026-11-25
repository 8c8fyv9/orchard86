# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded receive ownership before ACK; no sendall on nonblocking streams."""
class ReceiveBuffer:
    def __init__(self, *, sequence=1, limit=1048576):
        if type(sequence) is not int or sequence < 0 or type(limit) is not int or limit <= 0:
            raise ValueError('invalid buffer configuration')
        self.accepted_sequence = sequence
        self.limit = limit
        self.pending = bytearray()
        self.accepted = 0
        self.delivered = 0
        self.aborted = 0
        self.closed = False
        self.fin_sequence = None

    def accept(self, sequence, payload):
        if self.closed or self.fin_sequence is not None or sequence != self.accepted_sequence:
            raise ValueError('closed or noncontiguous stream')
        if not isinstance(payload, bytes):
            raise TypeError('payload must be bytes')
        if len(payload) > self.limit-len(self.pending):
            raise BufferError('receive capacity exhausted')
        self.pending.extend(payload)
        self.accepted += len(payload)
        self.accepted_sequence += len(payload)
        return self.accepted_sequence

    def drain(self, send):
        if not self.pending or self.closed:
            return 0
        try:
            count = send(bytes(self.pending))
        except (BlockingIOError, InterruptedError):
            return 0
        if type(count) is not int or not 0 < count <= len(self.pending):
            raise ConnectionError('invalid or zero write')
        del self.pending[:count]
        self.delivered += count
        return count

    def accept_fin(self, sequence):
        if self.closed:
            raise ValueError('closed stream')
        if self.fin_sequence is not None:
            if sequence != self.fin_sequence:
                raise ValueError('conflicting FIN')
            return self.accepted_sequence
        if sequence != self.accepted_sequence:
            raise ValueError('noncontiguous FIN')
        self.fin_sequence = sequence
        self.accepted_sequence += 1
        return self.accepted_sequence

    @property
    def eof_ready(self):
        return self.fin_sequence is not None and not self.pending and not self.closed

    def abort(self):
        self.aborted += len(self.pending)
        self.pending.clear()
        self.closed = True
