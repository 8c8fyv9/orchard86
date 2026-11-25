#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated CLI smoke test; only a test-owned loopback TCP peer is used."""
import argparse
import asyncio
import json
from pathlib import Path
import socket
import stat
import sys
import tempfile

from tornado.httpclient import AsyncHTTPClient, HTTPClientError, HTTPRequest
from tornado.websocket import websocket_connect


async def smoke(novnc):
    root = Path(__file__).resolve().parents[1]
    payload = b'\x00\xffclient'
    exchanged = asyncio.Event()

    async def peer(reader, writer):
        try:
            writer.write(b'RFB 003.008\n')
            await writer.drain()
            data = await reader.readexactly(len(payload))
            if data == payload:
                exchanged.set()
            writer.write(data)
            await writer.drain()
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    listener = await asyncio.start_server(peer, '127.0.0.1', 0)
    async with listener:
        vnc_port = listener.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory() as temp:
            access = Path(temp) / 'access.json'
            # Reserve a fresh port before starting the child. If another process wins
            # the bind race, readiness fails and we never send anything to that port.
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            base = f'http://127.0.0.1:{port}'
            ws_url = f'ws://127.0.0.1:{port}/ws'
            child = await asyncio.create_subprocess_exec(
                sys.executable, str(root / 'server.py'), '--novnc-dir', str(novnc),
                '--vnc', str(vnc_port), '--port', str(port), '--access-file', str(access),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            client = AsyncHTTPClient(force_instance=True)
            try:
                line = await asyncio.wait_for(child.stdout.readline(), 5)
                if base.encode() not in line:
                    _, err = await asyncio.wait_for(child.communicate(), 5)
                    raise RuntimeError(f'Gateway failed to start: {err.decode()}')
                assert stat.S_IMODE(access.stat().st_mode) == 0o600
                assert json.loads(access.read_text()) == {
                    'url': base + '/', 'vnc_port': vnc_port, 'auth': 'none', 'pid': child.pid,
                }
                page = await client.fetch(base + '/', request_timeout=5)
                assert b'/assets/console.js' in page.body
                assert page.headers['Cache-Control'] == 'no-store'
                assert "frame-ancestors 'none'" in page.headers['Content-Security-Policy']
                for rel, path in (
                    ('assets/console.js', root / 'web/console.js'),
                    ('assets/console.css', root / 'web/console.css'),
                    ('novnc/core/rfb.js', novnc / 'core/rfb.js'),
                    ('novnc/vendor/pako/lib/zlib/inflate.js', novnc / 'vendor/pako/lib/zlib/inflate.js'),
                    ('novnc/LICENSE.txt', novnc / 'LICENSE.txt'),
                ):
                    res = await client.fetch(base + '/' + rel, request_timeout=5)
                    assert res.body == path.read_bytes(), rel
                for path, headers, code in (
                    ('/', {'Host': 'not-local.invalid'}, 403),
                    ('/novnc/.git/config', {}, 404),
                ):
                    res = await client.fetch(base + path, headers=headers,
                                             raise_error=False, request_timeout=5)
                    assert res.code == code
                try:
                    await websocket_connect(HTTPRequest(ws_url, headers={'Origin': 'http://not-local.invalid'},
                                                           connect_timeout=5, request_timeout=5),
                                            subprotocols=['binary'])
                except HTTPClientError as exc:
                    assert exc.code == 403, exc
                else:
                    raise AssertionError('foreign Origin accepted')
                ws = await websocket_connect(HTTPRequest(ws_url, headers={'Origin': base}, connect_timeout=5,
                                                        request_timeout=5), subprotocols=['binary'])
                try:
                    assert ws.selected_subprotocol == 'binary'
                    assert await asyncio.wait_for(ws.read_message(), 5) == b'RFB 003.008\n'
                    await ws.write_message(payload, binary=True)
                    assert await asyncio.wait_for(ws.read_message(), 5) == payload
                    assert exchanged.is_set()
                    await ws.write_message('text is not RFB')
                    assert await asyncio.wait_for(ws.read_message(), 5) is None
                    assert ws.close_code == 1003
                finally:
                    ws.close()
                print('PASS: HTTP/assets/CSP/access file, Host/Origin rejection, binary relay and text rejection')
            finally:
                client.close()
                if child.returncode is None:
                    child.terminate()
                    try:
                        await asyncio.wait_for(child.communicate(), 5)
                    except TimeoutError:
                        child.kill()
                        await child.communicate()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--novnc-dir', type=Path, required=True)
    asyncio.run(smoke(parser.parse_args().novnc_dir.resolve()))
