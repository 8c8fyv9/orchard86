# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded raw stream relay; caller owns sockets and thread lifecycle."""
import plistlib
import select
import socket
import struct
import time

def relay(left, right, *, deadline, stop, limit=1048576, transform=None):
    if type(limit) is not int or limit <= 0:
        raise ValueError('invalid relay capacity')
    sockets = (left, right)
    original = [s.gettimeout() for s in sockets]
    pending = [bytearray(), bytearray()]  # bytes destined to each socket
    tx_frame_buf = bytearray()
    eof = [False, False]
    shut = [False, False]
    delivered = [0, 0]
    high = [0, 0]
    operation = "start"
    side = None
    try:
        for s in sockets:
            s.setblocking(False)
        while True:
            if stop.is_set():
                raise InterruptedError('relay cancelled')
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('relay deadline')
            if transform is not None and eof[0] and tx_frame_buf:
                pending[1].extend(tx_frame_buf)
                tx_frame_buf.clear()
            for i in (0, 1):
                if eof[1-i] and not pending[i] and not shut[i]:
                    operation, side = "shutdown-write", i
                    sockets[i].shutdown(socket.SHUT_WR)
                    shut[i] = True
            if all(eof) and not any(pending):
                return {'delivered': delivered, 'pending_high_water': high,
                        'clean_eof': True}
            readable = [sockets[i] for i in (0, 1)
                        if not eof[i] and len(pending[1-i]) < limit]
            writable = [sockets[i] for i in (0, 1) if pending[i]]
            ready_r, ready_w, _ = select.select(readable, writable, [], min(.05, remaining))
            for i in (0, 1):
                if sockets[i] in ready_w:
                    try:
                        operation, side = "send", i
                        n = sockets[i].send(pending[i])
                    except (BlockingIOError, InterruptedError):
                        continue
                    if not n:
                        raise ConnectionError('zero relay write')
                    del pending[i][:n]
                    delivered[i] += n
            for i in (0, 1):
                if sockets[i] not in ready_r:
                    continue
                try:
                    operation, side = "receive", i
                    data = sockets[i].recv(min(65536, limit-len(pending[1-i])))
                except (BlockingIOError, InterruptedError):
                    continue
                if data:
                    if i == 0 and transform is not None:
                        tx_frame_buf.extend(data)
                        while len(tx_frame_buf) >= 4:
                            flen = struct.unpack_from('!I', tx_frame_buf)[0]
                            if flen > limit:
                                pending[1].extend(tx_frame_buf)
                                tx_frame_buf.clear()
                                break
                            if len(tx_frame_buf) < 4 + flen:
                                break
                            raw = bytes(tx_frame_buf[4:4 + flen])
                            del tx_frame_buf[:4 + flen]
                            try:
                                msg = plistlib.loads(raw)
                                new_msg = transform(msg)
                                if new_msg is not msg:
                                    raw = plistlib.dumps(new_msg, fmt=plistlib.FMT_BINARY)
                            except Exception:
                                pass
                            pending[1].extend(struct.pack('!I', len(raw)) + raw)
                    else:
                        pending[1-i].extend(data)
                    high[1-i] = max(high[1-i], len(pending[1-i]))
                else:
                    eof[i] = True
    except OSError as error:
        error.add_note(f"relay operation={operation} side={side} (0=host,1=guest) delivered={delivered} pending={[len(x) for x in pending]} eof={eof} shut={shut} monotonic={time.monotonic()}")
        raise
    finally:
        for s, timeout in zip(sockets, original):
            s.settimeout(timeout)
