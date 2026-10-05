"""Dependency-free development HTTP server for the UV tool.

Run with: python -m app.server --reload is intentionally not supported; the
algorithm and HTTP layer only use the Python standard library.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import samples
from .core import MeshError, prepare_chart, solve_lscm

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"


class Handler(BaseHTTPRequestHandler):
    server_version = "SmallLSCM/0.1"

    def _send_json(self, payload, status: int = 200) -> None:
        data = json.dumps(payload, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
            ".svg": "image/svg+xml",
        }
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_types.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            self._send_json({"status": "ok"})
        elif path == "/api/samples":
            self._send_json({"samples": list(samples.SAMPLES)})
        elif path.startswith("/api/samples/"):
            name = path.rsplit("/", 1)[-1]
            if name not in samples.SAMPLES:
                self._send_json({"detail": f"unknown sample {name}"}, 404)
            else:
                self._send_json(samples.SAMPLES[name]())
        elif path.startswith("/api/"):
            self.send_error(404)
        else:
            if path == "/":
                target = DIST / "index.html"
            else:
                target = (DIST / path.lstrip("/")).resolve()
                if not str(target).startswith(str(DIST.resolve())):
                    self.send_error(403)
                    return
            self._send_static(target)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"detail": f"invalid JSON: {exc}"}, 400)
            return

        try:
            if parsed.path == "/api/prepare":
                self._send_json(prepare_chart(payload))
            elif parsed.path == "/api/solve":
                self._send_json(solve_lscm(payload.get("mesh"), payload.get("anchors")))
            else:
                self.send_error(404)
        except MeshError as exc:
            self._send_json({"detail": str(exc)}, 400)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving on http://{args.host}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
