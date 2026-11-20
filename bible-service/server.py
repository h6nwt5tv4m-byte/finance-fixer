#!/usr/bin/env python3
"""Small, read-only YouVersion gateway. The App Key never enters a response."""
import argparse
import collections
import hashlib
import http.client
import ipaddress
import json
import math
import os
import secrets
from pathlib import Path
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1] / "bible"
BOOKS = {b["id"]: b for b in json.loads((ROOT / "books.json").read_text())}
ORIGINS = {"https://finance-fixer.net", "https://www.finance-fixer.net"}
MAX_RESPONSE = 2_000_000


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UpstreamError(Exception):
    pass


class UpstreamLimited(UpstreamError):
    pass


class Budget:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.clients = {}
        self.daily_clients = collections.OrderedDict()
        self.minute = collections.deque()
        self.hour = collections.deque()
        self.client_hours = {}
        self.day_start = clock()
        self.day_count = 0

    def take(self, client, cost):
        with self.lock:
            now = self.clock()
            cutoff = now - 60
            while self.minute and self.minute[0] <= cutoff:
                self.minute.popleft()
            while self.hour and self.hour[0] <= now-3600:
                self.hour.popleft()
            for key in list(self.client_hours):
                q = self.client_hours[key]
                while q and q[0] <= now-3600:
                    q.popleft()
                if not q:
                    del self.client_hours[key]
            for key in list(self.clients):
                q = self.clients[key]
                while q and q[0][0] <= cutoff:
                    q.popleft()
                if not q:
                    del self.clients[key]
            for key, (started, _) in list(self.daily_clients.items()):
                if now-started >= 86400:
                    del self.daily_clients[key]
            if now - self.day_start >= 86400:
                self.day_start, self.day_count = now, 0
            # Portal currently reports 200 calls/hour. Leave room for metadata
            # diagnostics; these are our caps, not a claim about future quotas.
            if len(self.minute) + cost > 60 or len(self.hour)+cost > 180 or self.day_count + cost > 10000:
                return False
            if len(self.client_hours.get(client, ()))+cost > 36:
                return False
            if client not in self.clients and len(self.clients) >= 1024:
                return False
            started, used = self.daily_clients.get(client, (now, 0))
            if used + cost > 240:
                return False
            q = self.clients.setdefault(client, collections.deque())
            # A reader can use at most one fifth of the shared upstream window.
            if len(q) >= 30 or sum(item[1] for item in q)+cost > 12:
                return False
            q.append((now, cost))
            self.minute.extend([now] * cost)
            self.hour.extend([now] * cost)
            if cost:
                self.client_hours.setdefault(client, collections.deque()).extend([now] * cost)
            self.day_count += cost
            if cost:
                if client not in self.daily_clients and len(self.daily_clients) >= 4096:
                    self.daily_clients.popitem(last=False)
                self.daily_clients[client] = (started, used+cost)
            return True


class Gateway:
    def __init__(self, key, enabled=True):
        self.key = key
        self.enabled = enabled
        self.opener = urllib.request.build_opener(NoRedirect())
        self.budget = Budget()
        self.font_cache = None
        self.font_cached_at = 0
        self.font_lock = threading.Lock()
        self.blocked_until = 0
        self.block_lock = threading.Lock()

    def fetch(self, path, *, as_json=True, deadline=None):
        if self.blocked_until > time.monotonic():
            raise UpstreamLimited()
        deadline = deadline or time.monotonic()+15
        req = urllib.request.Request(
            "https://api.youversion.com" + path,
            headers={"X-YVP-App-Key": self.key, "Accept": "application/json" if as_json else "text/css"},
        )
        try:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise UpstreamError()
            with self.opener.open(req, timeout=min(5, remaining)) as response:
                if response.status != 200:
                    raise UpstreamError()
                chunks = []
                size = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise UpstreamError()
                    chunk = response.read1(min(65536, MAX_RESPONSE+1-size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_RESPONSE:
                        raise UpstreamError()
                raw = b"".join(chunks)
            if len(raw) > MAX_RESPONSE or self.key.encode() in raw:
                raise UpstreamError()
            return json.loads(raw) if as_json else raw
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    delay = max(1, min(86400, int(exc.headers.get("Retry-After", "300"))))
                except (ValueError, TypeError):
                    delay = 300
                with self.block_lock:
                    self.blocked_until = max(self.blocked_until, time.monotonic()+delay)
                raise UpstreamLimited() from None
            raise UpstreamError() from None
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
            raise UpstreamError() from None

    def fonts(self):
        with self.font_lock:
            if self.font_cache is None or time.monotonic()-self.font_cached_at >= 900:
                self.font_cache = self.fetch("/v1/fonts/1/stylesheet", as_json=False)
                self.font_cached_at = time.monotonic()
            return self.font_cache

    def chapter(self, book, chapter):
        if not self.enabled:
            raise UpstreamError()
        reference = f"{book}.{chapter}"
        deadline = time.monotonic()+15
        metadata = self.fetch("/v1/bibles/111", deadline=deadline)
        copyright_text = metadata.get("copyright")
        if not isinstance(copyright_text, str) or not copyright_text.strip():
            raise UpstreamError()
        passage = self.fetch(f"/v1/bibles/111/passages/{reference}?format=html&include_headings=true&include_notes=true", deadline=deadline)
        if passage.get("id") != reference or not isinstance(passage.get("content"), str) or not passage["content"].strip():
            raise UpstreamError()
        return {"id": reference, "reference": passage.get("reference", reference),
                "html": passage["content"], "copyright": copyright_text, "version": "NIV 2011"}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, gateway, development=False):
        self.gateway = gateway
        self.development = development
        self.ip_salt = secrets.token_bytes(32)
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        # Never emit upstream exceptions, keys, response bodies or user addresses.
        pass


class Handler(SimpleHTTPRequestHandler):
    server_version = "BibleGateway"
    sys_version = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def setup(self):
        super().setup()
        self.connection.settimeout(12)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        origin = self.headers.get("Origin", "")
        if origin in ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Expose-Headers", "Retry-After")
        super().end_headers()

    def reply(self, status, data, mime="application/json; charset=utf-8", retry_after=60):
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        if status == 429:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def client_id(self):
        address = self.client_address[0]
        if not self.server.development:
            # Production listens only on loopback and is reached directly by cloudflared.
            address = self.headers.get("CF-Connecting-IP", "")
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return None
        if ip.version == 6:
            # Group a routed IPv6 allocation so changing /64 subnets does not
            # cheaply multiply the reader's budget or fill the client tables.
            address = str(ipaddress.ip_network(f"{ip}/48", strict=False))
        else:
            address = str(ip)
        return hashlib.sha256(self.server.ip_salt+address.encode()).hexdigest()

    def do_HEAD(self):
        if urllib.parse.urlsplit(self.path).path == "/healthz":
            return self.reply(200, {"ok": True})
        return self.reply(405, {"error": "method_not_allowed"})

    def do_GET(self):
        if len(self.path) > 500:
            return self.reply(400, {"error": "invalid_request"})
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/healthz":
            return self.reply(200, {"ok": True, "niv_enabled": self.server.gateway.enabled})
        if self.server.development and path.startswith("/bible/") and not path.startswith("/bible/api/"):
            # Local preview serves only the public Bible directory, never its sibling service or key file.
            relative = urllib.parse.unquote(path[len("/bible/"):])
            target = (ROOT / relative).resolve()
            if not target.is_relative_to(ROOT) or target.suffix not in ("", ".html", ".css", ".js", ".json"):
                return self.reply(404, {"error": "not_found"})
            self.path = "/" + relative
            return super().do_GET() if self.command != "HEAD" else super().do_HEAD()
        if path.startswith("/bible/api/") and self.server.development:
            path = path[len("/bible/api"):]
        if path not in ("/chapter", "/fonts.css"):
            return self.reply(404, {"error": "not_found"})
        origin = self.headers.get("Origin", "")
        if not self.server.development and origin not in ORIGINS:
            return self.reply(403, {"error": "origin_not_allowed"})
        if self.server.development and origin and origin not in ORIGINS and origin not in {
            f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"
        }:
            return self.reply(403, {"error": "origin_not_allowed"})
        client = self.client_id()
        if client is None:
            return self.reply(403, {"error": "proxy_required"})
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        if path == "/chapter":
            if set(query) != {"book", "chapter"} or any(len(v) != 1 for v in query.values()):
                return self.reply(400, {"error": "invalid_request"})
            book, chapter_text = query["book"][0], query["chapter"][0]
            if book not in BOOKS or not chapter_text.isascii() or not chapter_text.isdecimal() or len(chapter_text) > 3:
                return self.reply(400, {"error": "invalid_reference"})
            chapter = int(chapter_text)
            if not 1 <= chapter <= BOOKS[book]["chapters"]:
                return self.reply(400, {"error": "invalid_reference"})
        elif query:
            return self.reply(400, {"error": "invalid_request"})
        if not self.server.gateway.enabled:
            return self.reply(503, {"error": "niv_suspended"})
        cached_font = path == "/fonts.css" and self.server.gateway.font_cache is not None and time.monotonic()-self.server.gateway.font_cached_at < 900
        if not cached_font and self.server.gateway.blocked_until > time.monotonic():
            return self.reply(429, {"error":"try_later"}, retry_after=math.ceil(self.server.gateway.blocked_until-time.monotonic()))
        if not self.server.gateway.budget.take(client, 2 if path == "/chapter" else 0 if cached_font else 1):
            return self.reply(429, {"error": "try_later"})
        try:
            if path == "/fonts.css":
                css = self.server.gateway.fonts()
                return self.reply(200, css, "text/css; charset=utf-8")
            return self.reply(200, self.server.gateway.chapter(book, chapter))
        except UpstreamLimited:
            return self.reply(429, {"error":"try_later"}, retry_after=max(1, math.ceil(self.server.gateway.blocked_until-time.monotonic())))
        except (UpstreamError, AttributeError, TypeError):
            return self.reply(502, {"error": "niv_unavailable"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8760)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    key_path = Path(os.environ.get("YVP_KEY_FILE", "~/.config/finance-fixer/youversion-app-key")).expanduser()
    if key_path.stat().st_mode & 0o077:
        raise SystemExit("App Key file must be private (chmod 600).")
    key = key_path.read_text().strip()
    if not key or any(c.isspace() for c in key):
        raise SystemExit("A valid App Key file is required.")
    gateway = Gateway(key, os.environ.get("NIV_ENABLED", "1") == "1")
    server = Server(("127.0.0.1", args.port), gateway, args.development)
    print(f"Bible gateway listening on loopback port {args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
