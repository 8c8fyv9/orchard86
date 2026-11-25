#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Per-live-session mux counters; commit sends only after transport acceptance."""
import struct

class State:
    def __init__(self):
        self.tx = 0
        self.peer_next = 0
        self.pending = None

    def prepare(self, protocol, payload):
        if self.pending is not None:
            raise ValueError("pending transport response must be received first")
        if protocol not in (2, 6):
            raise ValueError("unsupported mux protocol")
        if len(payload) > 65520:
            raise ValueError("oversized mux payload")
        self.pending = struct.pack("!IIIHH", protocol, 16 + len(payload),
                                   0xfeedface, self.tx, self.peer_next) + payload
        return self.pending

    def accepted(self):
        if self.pending is None:
            raise ValueError("no pending send")
        self.tx = (self.tx + 1) & 65535
        self.pending = None

    def receive(self, packet):
        if len(packet) < 16:
            raise ValueError("short mux packet")
        protocol, length, magic, tx, rx = struct.unpack_from("!IIIHH", packet)
        if length != len(packet) or magic != 0xfaceface or protocol not in (1, 2, 6):
            raise ValueError("invalid guest mux packet")
        if tx != self.peer_next:
            raise ValueError("out-of-order guest mux sequence")
        self.peer_next = (tx + 1) & 65535
        return protocol, packet[16:]
