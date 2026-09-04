"""Localhost HTTP endpoint that harness hooks POST lifecycle events to.

Claude Code fires hooks (SessionStart, UserPromptSubmit, PreToolUse,
Notification, Stop) with a JSON payload on stdin; our hook script forwards
that JSON here. This is how the deck knows an agent is blocked rather than
screen-scraping a terminal.

Bound to 127.0.0.1 only - this accepts unauthenticated local POSTs and must
never be exposed off-machine.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("opendeck.hooks")

DEFAULT_PORT = 8787


class _Handler(BaseHTTPRequestHandler):
    dispatch = None  # set by HookServer

    def do_POST(self):  # noqa: N802 (stdlib naming)
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode(errors="replace") or "{}")
        except json.JSONDecodeError:
            payload = {"raw": body.decode(errors="replace")}

        event = self.path.lstrip("/") or payload.get("hook_event_name", "unknown")
        try:
            if _Handler.dispatch:
                _Handler.dispatch(event, payload)
        except Exception:  # a hook must never break the agent it fired from
            log.exception("hook dispatch failed for %s", event)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"opendeck bridge alive\n")

    def log_message(self, fmt, *args):  # silence per-request stderr spam
        log.debug(fmt, *args)


class HookServer(threading.Thread):
    def __init__(self, dispatch, port: int = DEFAULT_PORT):
        super().__init__(daemon=True)
        _Handler.dispatch = dispatch
        self.port = port
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)

    def run(self) -> None:
        log.info("hook server listening on http://127.0.0.1:%d", self.port)
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()
