#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private mux control for one already verified live guest; no USB discovery.

Caller supplies descriptor identity only after real mux negotiation and removes
it on disconnect. Connect success requires the caller's real stream handoff.
No listener, default daemon path, host USB, or guest response is created here.
"""
import plistlib
import socket
import struct

HEADER = struct.Struct("<4I")
MAX_FRAME = 65536


def receive(connection, *, request=True):
    def exact(n):
        result = bytearray()
        while len(result) < n:
            chunk = connection.recv(n - len(result))
            if not chunk:
                raise EOFError("private mux control EOF")
            result.extend(chunk)
        return bytes(result)
    is_request = request
    length, version, kind, tag = HEADER.unpack(exact(HEADER.size))
    if not HEADER.size < length <= MAX_FRAME or version != 1 or kind != 8:
        raise ValueError("invalid private mux control header")
    request = plistlib.loads(exact(length - HEADER.size))
    if not isinstance(request, dict) or (is_request and not isinstance(request.get("MessageType"), str)):
        raise ValueError("invalid private mux request")
    return tag, request


def send(connection, tag, message):
    raw = plistlib.dumps(message)
    if len(raw) > MAX_FRAME - HEADER.size:
        raise ValueError("private mux response exceeds bound")
    connection.sendall(HEADER.pack(len(raw) + HEADER.size, 1, 8, tag) + raw)


class GuestInventory:
    def __init__(self, *, serial, product_id, allowed_ports=(62078,)):
        # None explicitly permits dynamic ports on this one private guest only.
        # There is no host TCP route; actual connection still requires guest SYN-ACK.
        if allowed_ports is not None and (not allowed_ports or any(
                type(p) is not int or not 1 <= p <= 65535 for p in allowed_ports)):
            raise ValueError("invalid guest service port allowlist")
        self.allowed_ports = None if allowed_ports is None else frozenset(allowed_ports)
        if (not isinstance(serial, str) or not 0 < len(serial) <= 255
                or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in serial)
                or type(product_id) is not int or not 0 <= product_id <= 65535):
            raise ValueError("invalid descriptor identity")
        self.properties = {"DeviceID": 1, "ConnectionType": "USB",
                           "SerialNumber": serial, "ProductID": product_id,
                           "LocationID": 0}  # private route, not physical topology
        self.live = True

    def entry(self):
        return {"DeviceID": 1, "Properties": dict(self.properties)}

    def handle(self, connection, tag, request):
        """Return listen/connect/close. Connect is pending, NEVER auto-ACKed."""
        kind = request.get("MessageType")
        if kind == "ListDevices":
            send(connection, tag, {"DeviceList": [self.entry()] if self.live else []})
            return "close"
        if kind == "Listen":
            send(connection, tag, {"MessageType": "Result", "Number": 0})
            if self.live:
                send(connection, 0, dict(self.entry(), MessageType="Attached"))
            return "listen"
        if kind == "Connect":
            port = request.get("PortNumber")
            if (self.live and type(request.get("DeviceID")) is int
                    and request["DeviceID"] == 1 and type(port) is int
                    and 0 < port <= 65535
                    and (self.allowed_ports is None or socket.ntohs(port) in self.allowed_ports)):
                return "connect"
            send(connection, tag, {"MessageType": "Result", "Number": 3})
            return "close"
        send(connection, tag, {"MessageType": "Result", "Number": 1})
        return "close"

    def detach(self, listeners):
        self.live = False
        for connection in listeners:
            send(connection, 0, {"MessageType": "Detached", "DeviceID": 1})
