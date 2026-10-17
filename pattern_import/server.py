"""Local page for pattern import. Listens on localhost only."""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from pattern_import.extract import (
    MAX_BYTES,
    MSG_FETCH,
    Result,
    extract_bytes,
    fetch_url,
    split_text,
)

STATIC = Path(__file__).resolve().parent / "static"
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/", ""}:
            path = "/index.html"
        root = STATIC.resolve()
        file = (root / path.lstrip("/")).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            self.send_error(404)
            return
        data = file.read_bytes()
        self._bytes(data, TYPES.get(file.suffix, "application/octet-stream"))

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 0 or length > MAX_BYTES:
            self._json(Result(ok=False, code="fetch", message=MSG_FETCH).as_dict(), 413)
            return
        body = self.rfile.read(length) if length else b""
        if path == "/fetch":
            self._json(self._fetch(body).as_dict())
            return
        if path == "/split":
            self._json(self._split(body).as_dict())
            return
        if path == "/file":
            name = unquote(self.headers.get("X-Filename", "file"))
            kind = self.headers.get("Content-Type", "")
            self._json(extract_bytes(body, name, kind).as_dict())
            return
        self.send_error(404)

    def _fetch(self, body: bytes) -> Result:
        try:
            payload = json.loads(body)
            url = payload["url"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return Result(ok=False, code="fetch", message=MSG_FETCH)
        if not isinstance(url, str):
            return Result(ok=False, code="fetch", message=MSG_FETCH)
        return fetch_url(url)

    def _split(self, body: bytes) -> Result:
        try:
            payload = json.loads(body)
            text = payload["text"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return Result(ok=False, code="fetch", message=MSG_FETCH)
        if not isinstance(text, str):
            return Result(ok=False, code="fetch", message=MSG_FETCH)
        return split_text(text)

    def _json(self, payload: dict, status: int = 200):
        self._bytes(json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8", status)

    def _bytes(self, data: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args):
        return


def make_server(port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = make_server(port)
    print(f"http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
