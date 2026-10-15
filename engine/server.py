"""
server.py - A tiny private website that runs on your own laptop (http://localhost:8765).

Plain English: a normal web page can only show things. This little server lets the Radar page
also DO things: add or remove watchlist topics, pin stories to your Case Board, and start a check
right now. It only listens on your own computer ("localhost"), so nobody else can reach it.

Standard terms: a local HTTP server with a small JSON API (application programming interface).
"""

import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

DATA = "data.json"
PINS = "pins.json"
WATCHLIST = os.path.join("..", "watchlist.txt")  # lives one folder up, next to the Start button
GUIDE = os.path.join("..", "Narrative-Radar-Guide.png")
_lock = threading.Lock()
check_now = threading.Event()  # watch.py waits on this between rounds


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def write_data(obj):
    with _lock:
        _write_json(DATA, obj)


def watch_lines():
    with open(WATCHLIST, encoding="utf-8") as f:
        return f.read().splitlines()


def add_topic(text: str) -> str:
    text = " ".join(text.replace('"', " ").split())[:80]
    if len(text) < 2:
        raise ValueError("topic too short")
    line = f'"{text}" sourcelang:english'
    with _lock:
        lines = watch_lines()
        if any(l.strip().lower() == line.lower() for l in lines):
            return line
        with open(WATCHLIST, "a", encoding="utf-8") as f:
            f.write(("\n" if lines and lines[-1].strip() else "") + "# added from the Radar page\n" + line + "\n")
    return line


def remove_topic(line: str) -> bool:
    with _lock:
        lines = watch_lines()
        keep = [l for l in lines if l.strip() != line.strip()]
        if len(keep) == len(lines):
            return False
        with open(WATCHLIST, "w", encoding="utf-8") as f:
            f.write("\n".join(keep) + "\n")
    return True


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the black window clean
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/app.html"
        if self.path.startswith("/api/data"):
            return self._send(200, _read_json(DATA, {"loading": True}))
        if self.path.startswith("/api/pins"):
            return self._send(200, _read_json(PINS, []))
        if self.path.split("?")[0] == "/Narrative-Radar-Guide.png" and os.path.exists(GUIDE):
            with open(GUIDE, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.split("?")[0] not in ("/app.html", "/dashboard.html"):
            return self._send(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 100_000)
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self._send(400, {"error": "bad json"})
        try:
            if self.path == "/api/watch":
                if body.get("action") == "remove":
                    ok = remove_topic(str(body.get("line", "")))
                    check_now.set()
                    return self._send(200, {"removed": ok})
                line = add_topic(str(body.get("topic", "")))
                check_now.set()
                return self._send(200, {"added": line})
            if self.path == "/api/pins":
                pins = body.get("pins")
                if not isinstance(pins, list):
                    return self._send(400, {"error": "pins must be a list"})
                with _lock:
                    _write_json(PINS, pins[:500])
                return self._send(200, {"saved": len(pins)})
            if self.path == "/api/check":
                check_now.set()
                return self._send(200, {"ok": True})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(404, {"error": "not found"})


def start(port=8765):
    """Start the server in the background. Tries the next port if one is busy. Returns the URL."""
    for p in range(port, port + 10):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return f"http://localhost:{p}/"
    return ""
