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
)
from project import otel
from project.parse import ParseFailure, parse_reading
from project.store import connect

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
        with otel.http_request("GET", path) as status:
            self._otel_status = status
            root = STATIC.resolve()
            file = (root / path.lstrip("/")).resolve()
            if not file.is_relative_to(root) or not file.is_file():
                self.send_error(404)
                return
            data = file.read_bytes()
            self._bytes(data, TYPES.get(file.suffix, "application/octet-stream"))

    def do_POST(self):
        path = urlparse(self.path).path
        with otel.http_request("POST", path) as status:
            self._otel_status = status
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length < 0 or length > MAX_BYTES:
                self._json(Result(ok=False, code="fetch", message=MSG_FETCH).as_dict(), 413)
                return
            body = self.rfile.read(length) if length else b""
            if path == "/fetch":
                self._json(self._fetch(body).as_dict())
                return
            if path == "/file":
                name = unquote(self.headers.get("X-Filename", "file"))
                kind = self.headers.get("Content-Type", "")
                self._json(extract_bytes(body, name, kind).as_dict())
                return
            if path == "/accept":
                self._accept(body)
                return
            self.send_error(404)

    def _accept(self, body: bytes) -> None:
        try:
            payload = json.loads(body)
            reading = payload["reading"]
        except (json.JSONDecodeError, KeyError, TypeError):
            self._sse_start()
            self._sse({"type": "error", "ok": False, "message": "The reading did not parse."})
            return
        if type(reading) is not str:
            self._sse_start()
            self._sse({"type": "error", "ok": False, "message": "The reading did not parse."})
            return
        self._sse_start()
        chars = 0

        def on_delta(text: str) -> None:
            nonlocal chars
            chars += len(text)
            self._sse({"type": "delta", "chars": chars})

        db = connect(self.server.db_path)
        try:
            project = parse_reading(reading, self._complete(on_delta), db)
        except ParseFailure as exc:
            self._sse({"type": "error", "ok": False, "message": str(exc)})
            return
        finally:
            db.close()
        self._sse(
            {
                "type": "done",
                "ok": True,
                "pieces": [
                    {
                        "name": piece.name,
                        "copies": piece.copies,
                        "parsed": piece.parsed,
                        "sizes": [size.name for size in piece.sizes],
                    }
                    for piece in project.pieces
                ],
            }
        )

    def _complete(self, on_delta=None):
        if self.server.complete is not None:
            return self.server.complete
        from project.complete import complete

        return lambda reading: complete(reading, on_delta=on_delta)

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse(self, payload: dict) -> None:
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _fetch(self, body: bytes) -> Result:
        try:
            payload = json.loads(body)
            url = payload["url"]
        except (json.JSONDecodeError, KeyError, TypeError):
            return Result(ok=False, code="fetch", message=MSG_FETCH)
        if not isinstance(url, str):
            return Result(ok=False, code="fetch", message=MSG_FETCH)
        return fetch_url(url)

    def _json(self, payload: dict, status: int = 200):
        self._bytes(json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8", status)

    def send_response(self, code, message=None):
        status = getattr(self, "_otel_status", None)
        if status is not None:
            status["code"] = code
        super().send_response(code, message)

    def _bytes(self, data: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args):
        return


def make_server(port: int = 0, db_path: str | Path | None = None, complete=None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.db_path = Path("cardigan.sqlite") if db_path is None else Path(db_path)
    server.complete = complete
    return server


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = make_server(port)
    print(f"http://127.0.0.1:{server.server_address[1]}", flush=True)
    if otel.setup():
        print("OpenTelemetry on (OTLP → .env endpoint)", flush=True)
    else:
        print("OpenTelemetry off (no OTEL_EXPORTER_OTLP_ENDPOINT)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        otel.shutdown()


if __name__ == "__main__":
    main()
