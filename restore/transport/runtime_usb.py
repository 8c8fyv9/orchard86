# SPDX-License-Identifier: GPL-3.0-or-later
"""Enumerate a private VMApple restore USB endpoint through an injected transport."""
import struct


def enumerate_runtime(transport, stop, *, interval=.002):
    def exchange(frame):
        while not stop.is_set():
            if transport.send(frame):
                break
            stop.wait(interval)
        while not stop.is_set():
            reply = transport.receive()
            if reply is not None:
                return reply
            stop.wait(interval)
        raise InterruptedError('runtime USB enumeration cancelled')

    def setup(bm, req, value=0, length=0, index=0):
        return exchange(struct.pack('<IBB', 8, 0, 1) +
                        struct.pack('<BBHHH', bm, req, value, index, length))

    if exchange(struct.pack('<IBB', 0, 0, 2)) != bytes([4, 16]):
        raise ValueError('unexpected runtime reset reply')
    reply = setup(128, 6, 256, 18)
    if len(reply) != 20 or reply[:4] != bytes([1, 0, 18, 1]):
        raise ValueError('invalid device descriptor')
    device = reply[2:]
    configs = []
    for i in range(device[17]):
        reply = setup(128, 6, 512 + i, 4096)
        data = reply[2:]
        if (reply[:4] != bytes([1, 0, 9, 2]) or len(data) < 9
                or len(data) != int.from_bytes(data[2:4], 'little')):
            raise ValueError('invalid configuration descriptor')
        offset = 0
        matched = False
        while offset < len(data):
            size = data[offset]
            if size < 2 or offset + size > len(data):
                raise ValueError('truncated USB descriptor')
            part = data[offset:offset + size]
            if part[1] == 4:
                if size < 9:
                    raise ValueError('truncated interface descriptor')
                matched |= part[2] == 0 and part[5:8] == bytes([255, 254, 2])
            offset += size
        if matched:
            configs.append(data[5])
    if len(configs) != 1 or setup(0, 9, configs[0]) != bytes([1, 0]):
        raise ValueError('restore mux interface not configured')
    version = struct.pack('!IIIII', 0, 20, 2, 0, 0)
    if exchange(struct.pack('<IBB', len(version), 1, 1) + version) != bytes([1, 1]):
        raise ValueError('mux negotiation request not accepted')
    reply = exchange(struct.pack('<IBB', 16384, 129, 1))
    if len(reply) != 22 or reply[:2] != bytes([1, 129]) or reply[2:18] != version[:16]:
        raise ValueError('unexpected mux version reply')
    reply = setup(128, 6, 0x300 + device[16], 255, 0x409)
    if (len(reply) < 4 or reply[:2] != bytes([1, 0]) or reply[2] != len(reply) - 2
            or reply[3] != 3):
        raise ValueError('invalid USB serial descriptor')
    serial = reply[4:].decode('utf-16le').rstrip(chr(0))
    if not serial:
        raise ValueError('empty USB serial')
    return serial, int.from_bytes(device[10:12], 'little')
