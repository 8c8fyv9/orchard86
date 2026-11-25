# SPDX-License-Identifier: GPL-3.0-or-later
"""Strict metadata parser for TCP-shaped packets on a private mux route."""
import struct

def parse(packet):
    if not isinstance(packet, bytes) or len(packet) < 36:
        raise ValueError('truncated mux TCP packet')
    protocol, total, magic, tx, rx = struct.unpack_from('!IIIHH', packet)
    if protocol != 6 or total != len(packet) or magic != 0xfaceface:
        raise ValueError('invalid mux envelope')
    source, destination, seq, ack, offset, flags, window, checksum, urgent = struct.unpack_from('!HHIIBBHHH', packet, 16)
    header_size = (offset >> 4)*4
    # Private mux guest sets low-nibble extension bits (observed 0x53).
    # Only the high nibble defines the byte offset; do not reject extensions.
    if not 20 <= header_size <= len(packet)-16:
        raise ValueError('invalid TCP header length')
    if flags & 2 and flags & 5:
        raise ValueError('conflicting SYN/FIN/RST')
    return dict(source=source, destination=destination, sequence=seq,
                acknowledgement=ack if flags & 16 else None,
                flags=flags, window=window, payload=packet[16+header_size:])
