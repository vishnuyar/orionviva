"""A tiny local web server — Python standard library only, no dependencies.

Bound to localhost by default: the surface is for the person at this machine,
reading their own vault with their own passphrase. It serves one static page and
a handful of JSON endpoints over the service layer. Kept deliberately thin —
the logic and its tests live in ``service``.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import service

_INDEX = (Path(__file__).parent / "index.html").read_text()
log = logging.getLogger(__name__)


def make_handler(vault, read_fn):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):        # keep the console quiet
            pass

        def _send(self, obj, code=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self):
            body = _INDEX.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            log.info("GET %s", self.path)
            if u.path == "/":
                return self._html()
            if u.path == "/api/overview":
                return self._send(service.overview(vault))
            if u.path == "/api/review":
                return self._send(service.review_list(vault))
            if u.path == "/api/transfers":
                return self._send(service.transfer_review(vault))
            if u.path == "/api/account":
                acct = parse_qs(u.query).get("id", [""])[0]
                return self._send(service.account_view(vault, acct))
            self._send({"error": "not_found"}, 404)

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(n) if n else b""
            log.info("POST %s (%d bytes)", u.path, n)
            try:
                if u.path == "/api/confirm":
                    d = json.loads(raw or b"{}")
                    return self._send(service.confirm_correction(
                        vault, d["doc_id"], d["field"], d["value"],
                        d.get("target_index")))
                if u.path == "/api/confirm-identity":
                    d = json.loads(raw or b"{}")
                    return self._send(service.confirm_identity(
                        vault, d["doc_id"], d["decision"]))
                if u.path == "/api/confirm-transfer":
                    d = json.loads(raw or b"{}")
                    return self._send(service.confirm_transfer_link(
                        vault, d["a"], d["b"]))
                if u.path == "/api/reject-transfer":
                    d = json.loads(raw or b"{}")
                    return self._send(service.reject_transfer_link(
                        vault, d["a"], d.get("b", "")))
                if u.path == "/api/upload":
                    fn = self.headers.get("X-Filename", "upload.bin")
                    return self._send(service.upload(vault, fn, raw, read_fn))
            except Exception as e:                       # surface, never 500-silently
                return self._send({"error": str(e)}, 400)
            self._send({"error": "not_found"}, 404)

    return Handler


def serve(vault, read_fn, host: str = "127.0.0.1", port: int = 8765):
    """Build (do not start) a threading HTTP server bound to localhost."""
    return ThreadingHTTPServer((host, port), make_handler(vault, read_fn))
