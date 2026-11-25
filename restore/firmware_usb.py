#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage 1 (DFU) and Stage 2 (iBEC) USB host transport over vmapple-bdif.recovery-host-fd."""
import struct
import time
import zlib

HEADER = struct.Struct('<IBB')
CHUNK_SIZE = 2048
MAX_FRAME = 2062


def encode_frame(channel, kind, payload=b''):
    if len(payload) > MAX_FRAME - HEADER.size:
        raise ValueError(f'payload too large for frame: {len(payload)}')
    return HEADER.pack(len(payload), channel, kind) + payload


def dfu_suffix(data):
    suffix = struct.pack('<HHHH3sB', 0xFFFF, 0xFFFF, 0x05AC, 0x0100, b'UFD', 16)
    body = data + suffix
    crc = zlib.crc32(body) ^ 0xFFFFFFFF
    return body + struct.pack('<I', crc)


class BdifRecoveryTransport:
    """Host-side driver for vmapple-bdif.recovery-host-fd SOCK_SEQPACKET."""

    def __init__(self, sock, *, timeout=10.0):
        self.sock = sock
        self.sock.settimeout(timeout)

    def send_and_recv(self, frame):
        self.sock.send(frame)
        return self.sock.recv(4096)

    def control_out(self, bm, b, val, index, payload=b''):
        setup = struct.pack('<BBHHH', bm, b, val, index, len(payload))
        return self.send_and_recv(encode_frame(0, 1, setup + payload))

    def control_in(self, bm, b, val, index, length):
        setup = struct.pack('<BBHHH', bm, b, val, index, length)
        return self.send_and_recv(encode_frame(0, 1, setup))

    def dfu_get_status(self):
        resp = self.control_in(0xA1, 3, 0, 0, 6)
        if len(resp) < 8:
            raise RuntimeError(f'unexpected DFU GETSTATUS reply: {resp.hex()}')
        return resp[2], int.from_bytes(resp[3:6], 'little'), resp[6]

    def enumerate_dfu(self):
        """Standard EP0 enumeration + SET_CONFIGURATION(1) before DFU transfers."""
        self.control_in(0x80, 6, 0x100, 0, 18)
        self.control_out(0x00, 9, 1, 0)

    def read_apnonce(self):
        """Read live ApNonce bytes from AVPBooter USB string descriptor 1 (NONC:...)."""
        self.enumerate_dfu()
        resp = self.control_in(0x80, 6, 0x301, 0x0409, 255)
        text = resp[4:].decode('utf-16-le', errors='replace')
        for token in text.split():
            if token.startswith('NONC:'):
                return bytes.fromhex(token[5:])
        raise RuntimeError(f'NONC not found in USB string descriptor 1: {text!r}')

    def upload_dfu(self, data):
        """Send an IMG4-wrapped image over DFU EP0 and trigger manifestation."""
        self.enumerate_dfu()
        wire = dfu_suffix(data)
        suffix = wire[-16:]
        count = (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE
        for idx in range(count):
            chunk = data[idx * CHUNK_SIZE:(idx + 1) * CHUNK_SIZE]
            if idx == count - 1:
                if len(chunk) + 16 <= CHUNK_SIZE:
                    chunk = chunk + suffix
                else:
                    self.control_out(0x21, 1, idx, 0, chunk)
                    chunk = suffix
            self.control_out(0x21, 1, idx, 0, chunk)
            status, poll_ms, _ = self.dfu_get_status()
            if status != 0:
                raise RuntimeError(f'DFU download error status={status} at block {idx}')
            if poll_ms:
                time.sleep(min(poll_ms, 50) / 1000.0)
        self.control_out(0x21, 1, count, 0, b'')
        for _ in range(16):
            status, poll_ms, state = self.dfu_get_status()
            if status != 0:
                raise RuntimeError(f'DFU manifest error status={status} state={state}')
            if state in (2, 8):
                break
            time.sleep(max(poll_ms, 50) / 1000.0)

    def usb_reset(self):
        """Send USB bus reset/reconnect event (channel 128, kind 2) after DFU manifest."""
        return self.send_and_recv(encode_frame(128, 2))

    def stage1_select(self):
        """Configure Stage 1b recovery bulk endpoint (SET_CONFIGURATION(1) + GET_CONFIGURATION)."""
        self.control_out(0x00, 9, 1, 0)
        self.control_in(0x80, 8, 0, 0, 1)

    def stage2_select(self):
        """Configure Stage 2 recovery endpoints."""
        self.control_out(0x00, 9, 1, 0)
        self.control_out(0x01, 11, 1, 1)

    def send_command(self, cmd, *, request_mode=0):
        payload = cmd.encode('ascii') + b'\x00'
        setup = struct.pack('<BBHHH', 0x40, request_mode, 0, 0, len(payload))
        return self.send_and_recv(encode_frame(0, 1, setup + payload))

    def getenv(self, name):
        self.send_command(f'getenv {name}')
        resp = self.control_in(0xC0, 0, 0, 0, 255)
        if not resp.startswith(bytes([1, 0])):
            raise RuntimeError(f'unexpected getenv reply: {resp.hex()}')
        return resp[2:].rstrip(b'\x00').decode('ascii', errors='replace')

    def upload_bulk(self, data):
        """Upload IMG4 payload over Stage 2 bulk OUT (channel 4) and verify filesize."""
        self.control_out(0x41, 0, 0, 0)
        for off in range(0, len(data), CHUNK_SIZE):
            chunk = data[off:off + CHUNK_SIZE]
            ack = self.send_and_recv(encode_frame(4, 1, chunk))
            if ack != bytes([1, 4]):
                raise RuntimeError(f'unexpected bulk ACK at {off}: {ack.hex()}')
        reported = self.getenv('filesize')
        if int(reported, 16) != len(data):
            raise RuntimeError(f'filesize mismatch: expected {len(data)}, got {reported}')
