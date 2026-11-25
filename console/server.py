#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Loopback-only browser VNC console for the local macOS VM.

Serves a local noVNC client and relays binary WebSocket frames to QEMU VNC.
No shell, no QMP, no lifecycle.
"""
import argparse, json, logging, os
from pathlib import Path
import tornado.httpserver, tornado.ioloop, tornado.iostream, tornado.tcpclient, tornado.web, tornado.websocket

VNC = ('127.0.0.1', 5901)
ALLOWED_HOSTS = set()
HTML = ''


class Bridge(tornado.websocket.WebSocketHandler):
    def prepare(self):
        if self.request.host not in ALLOWED_HOSTS:
            raise tornado.web.HTTPError(403)

    def select_subprotocol(self, subprotocols):
        return 'binary' if 'binary' in subprotocols else None

    def check_origin(self, origin):
        return origin in {f'http://{h}' for h in ALLOWED_HOSTS}

    async def open(self):
        self.up = None
        try:
            up = await tornado.tcpclient.TCPClient().connect(*VNC, timeout=5)
        except Exception:
            logging.exception('VNC connection failed')
            self.close(code=4503, reason='VNC unavailable')
            return
        if self.ws_connection is None or self.ws_connection.is_closing():
            up.close()
            return
        self.up = up
        self.up.set_nodelay(True)
        self.set_nodelay(True)
        tornado.ioloop.IOLoop.current().spawn_callback(self._relay, up)

    async def _relay(self, up):
        try:
            while True:
                data = await up.read_bytes(65536, partial=True)
                if not data:
                    break
                await self.write_message(data, binary=True)
        except (tornado.iostream.StreamClosedError,
                tornado.websocket.WebSocketClosedError):
            pass
        except Exception as e:
            self.close(code=4503, reason=('vnc read failed: %s' % e)[:120])
            return
        try:
            self.close(code=4503, reason='vnc closed')
        except Exception:
            pass

    async def on_message(self, message):
        if isinstance(message, str):
            self.close(code=1003, reason='Binary RFB required')
            return
        if not self.up:
            return
        try:
            await self.up.write(message)
        except tornado.iostream.StreamClosedError:
            self.close(code=4503, reason='vnc write failed')

    def on_close(self):
        if getattr(self, 'up', None):
            self.up.close()
            self.up = None


class Static(tornado.web.StaticFileHandler):
    def prepare(self):
        if self.request.host not in ALLOWED_HOSTS:
            raise tornado.web.HTTPError(403)


class Page(tornado.web.RequestHandler):
    def prepare(self):
        if self.request.host not in ALLOWED_HOSTS:
            raise tornado.web.HTTPError(403)

    def get(self):
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        self.set_header('Cache-Control', 'no-store')
        self.set_header('Referrer-Policy', 'no-referrer')
        self.set_header(
            'Content-Security-Policy',
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws://127.0.0.1:* ws://localhost:*; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'none'")
        self.finish(HTML)


def main():
    global HTML, ALLOWED_HOSTS, VNC
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vnc', type=int, default=5901)
    p.add_argument('--port', type=int, default=8770)
    p.add_argument('--access-file', type=Path)
    p.add_argument('--novnc-dir', required=True, type=Path,
                   help='local noVNC v1.6.0 source checkout')
    a = p.parse_args()
    if os.getuid() == 0:
        p.error('refuse root')
    if a.access_file and a.access_file.exists():
        p.error('access file must be new')
    if any(not 1 <= port <= 65535 for port in (a.vnc, a.port)) or a.vnc == a.port:
        p.error('use distinct ports in 1–65535')
    if not all((a.novnc_dir / path).is_file() for path in
               ('core/rfb.js', 'vendor/pako/lib/zlib/inflate.js')):
        p.error('--novnc-dir must contain core/rfb.js and vendor/pako')
    VNC = ('127.0.0.1', a.vnc)
    ALLOWED_HOSTS = {f'127.0.0.1:{a.port}', f'localhost:{a.port}'}
    assets = Path(__file__).with_name('web')
    HTML = (assets / 'index.html').read_text(encoding='utf-8')
    app = tornado.web.Application([
        (r'/', Page), (r'/ws', Bridge),
        (r'/assets/(console\.(?:js|css))', Static, {'path': str(assets)}),
        (r'/novnc/(core/.+|vendor/pako/.+|LICENSE\.txt)', Static,
         {'path': str(a.novnc_dir.resolve())}),
    ], websocket_max_message_size=1024 * 1024)
    server = tornado.httpserver.HTTPServer(app)
    server.listen(a.port, address='127.0.0.1')
    if a.access_file:
        fd = os.open(a.access_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump({'url': f'http://127.0.0.1:{a.port}/',
                       'vnc_port': a.vnc, 'auth': 'none',
                       'pid': os.getpid()}, out)
    print(f'VNC web console on http://127.0.0.1:{a.port}/ (loopback, no token)',
          flush=True)
    tornado.ioloop.IOLoop.current().start()


if __name__ == '__main__':
    main()
