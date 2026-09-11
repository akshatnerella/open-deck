"""Localhost endpoint that harness hooks POST lifecycle events to.

Claude Code pipes each hook's payload as JSON on stdin; our hook script
enriches it with the tmux target and forwards it here. This is how the deck
learns that a pane is blocked on a decision rather than merely busy - tmux
cannot see that difference.

Bound to 127.0.0.1 only. It accepts unauthenticated local POSTs and must never
be exposed off-machine.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)

DEFAULT_PORT = 8787


class _Handler(BaseHTTPRequestHandler):
    dispatch = None

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body.decode(errors="replace") or "{}")
        except json.JSONDecodeError:
            payload = {}

        event = self.path.lstrip("/") or payload.get("hook_event_name", "unknown")
        try:
            if _Handler.dispatch:
                _Handler.dispatch(event, payload)
        except Exception:
            # A hook must never break the agent it fired from.
            log.exception("hook dispatch failed for %s", event)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"opendeck alive\n")

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)


class HookServer(threading.Thread):
    def __init__(self, dispatch, port: int = DEFAULT_PORT) -> None:
        super().__init__(daemon=True)
        _Handler.dispatch = dispatch
        self.port = port
        self._httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)

    def run(self) -> None:
        log.info("hook server on http://127.0.0.1:%d", self.port)
        self._httpd.serve_forever()

    def stop(self) -> None:
        self._httpd.shutdown()
