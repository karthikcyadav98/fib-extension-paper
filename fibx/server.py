"""Zero-dependency dashboard server (stdlib http.server)."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
STATE = os.path.join(ROOT, "state")

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript",
        ".json": "application/json", ".svg": "image/svg+xml", ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the console clean

    def _send(self, body, ctype="application/json", code=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json_file(self, name):
        path = os.path.join(STATE, name)
        if not os.path.exists(path):
            return self._send(json.dumps({"error": f"{name} not generated yet"}), code=404)
        with open(path, "rb") as f:
            self._send(f.read())

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/portfolio":
            return self._json_file("portfolio.json")
        if path == "/api/backtest":
            return self._json_file("backtest.json")
        if path == "/api/signals":
            return self._json_file("signals.json")
        if path == "/api/charts":
            return self._json_file("charts.json")
        if path == "/api/refresh":
            from . import paper
            state = paper.update(verbose=False)
            paper.save(state)
            return self._send(json.dumps({"ok": True, "equity_mtm": state["equity_mtm"]}))

        rel = "index.html" if path == "/" else path.lstrip("/")
        fpath = os.path.normpath(os.path.join(WEB, rel))
        if not fpath.startswith(WEB) or not os.path.isfile(fpath):
            return self._send("not found", "text/plain", 404)
        ext = os.path.splitext(fpath)[1]
        with open(fpath, "rb") as f:
            self._send(f.read(), MIME.get(ext, "application/octet-stream"))


def serve(port=8787):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"  dashboard -> http://127.0.0.1:{port}")
    print("  ctrl-c to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
