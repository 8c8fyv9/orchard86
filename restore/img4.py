#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""IMG4 / IM4P / IM4R encapsulation with explicit restore generator."""
import hashlib

LIMIT = 16 * 1024**2
STREAM_LIMIT = 512 * 1024**2
MINIMAL_LPOL_IM4P = bytes.fromhex('30141604494d345016046c706f6c1603312e30040100')


def tlv(tag, data):
    if not 0 <= tag < 256 or len(data) > LIMIT:
        raise ValueError('invalid tag or oversized object')
    n = len(data)
    b = n.to_bytes(max(1, (n.bit_length() + 7) // 8), 'big')
    return bytes([tag]) + (bytes([n]) if n < 128 else bytes([0x80 | len(b)]) + b) + data


def private_property(name, data):
    if len(name) != 4:
        raise ValueError('private tag must have four characters')
    n = int.from_bytes(name, 'big')
    groups = [n & 127]
    n >>= 7
    while n:
        groups.append(128 | (n & 127))
        n >>= 7
    element = tlv(0x30, tlv(0x16, name) + tlv(4, data))
    ordinary = tlv(0xFF, element)
    return b'\xff' + bytes(reversed(groups)) + ordinary[1:]


def require_sequence(data):
    if len(data) < 2 or len(data) > LIMIT or data[0] != 0x30:
        raise ValueError('input must be one bounded DER SEQUENCE')
    n = data[1]
    offset = 2
    if n & 128:
        count = n & 127
        if not 1 <= count <= 4 or len(data) < 2 + count or data[2] == 0:
            raise ValueError('invalid DER length')
        n = int.from_bytes(data[2:2 + count], 'big')
        offset += count
        if n < 128:
            raise ValueError('nonminimal DER length')
    if offset + n != len(data):
        raise ValueError('truncated or trailing DER data')


def generator_nonce(generator):
    if len(generator) != 8:
        raise ValueError('restore generator must be 8 bytes')
    return hashlib.sha384(generator).digest()[:32]


def wrap(payload, ticket, generator=None):
    require_sequence(payload)
    require_sequence(ticket)
    body = tlv(0x16, b'IMG4') + payload + tlv(0xA0, ticket)
    if generator is not None:
        generator_nonce(generator)
        restore = tlv(0x30, tlv(0x16, b'IM4R') + tlv(0x31, private_property(b'BNCN', generator)))
        body += tlv(0xA1, restore)
    return tlv(0x30, body)


def wrap_large(payload_bytes, ticket, generator=None):
    """Wrap an IMG4 up to STREAM_LIMIT (e.g., RestoreKernelCache or RestoreRamDisk)."""
    if not isinstance(payload_bytes, bytes) or not 2 <= len(payload_bytes) <= STREAM_LIMIT:
        raise ValueError('payload exceeds stream budget')
    require_sequence(ticket)
    def _tlv_big(tag, data):
        n = len(data)
        b = n.to_bytes(max(1, (n.bit_length() + 7) // 8), 'big')
        return bytes([tag]) + (bytes([n]) if n < 128 else bytes([0x80 | len(b)]) + b) + data
    body = tlv(0x16, b'IMG4') + payload_bytes + _tlv_big(0xA0, ticket)
    if generator is not None:
        generator_nonce(generator)
        restore = tlv(0x30, tlv(0x16, b'IM4R') + tlv(0x31, private_property(b'BNCN', generator)))
        body += _tlv_big(0xA1, restore)
    return _tlv_big(0x30, body)
