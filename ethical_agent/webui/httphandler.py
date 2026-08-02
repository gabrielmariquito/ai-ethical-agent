from __future__ import annotations

import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from . import routing
from .errors import ApiError

STATIC_DIR = (Path(__file__).resolve().parent / "static").resolve()

# Clean URLs for the shell pages -- each maps 1:1 to a static HTML file that
# lives directly under static/. Adding the audit screen later is one more
# entry here (plus its own handlers_audit.py route registrations).
PAGES = {
    "/": "index.html",
    "/check": "check.html",
    "/demo": "demo.html",
    "/eval": "eval.html",
}

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def make_handler(state) -> type:
    """Builds a BaseHTTPRequestHandler subclass closed over `state`, since
    http.server wants a handler *class*, not an instance, per connection."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "EthicalAgentWebUI/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            # Default BaseHTTPRequestHandler.log_message already writes to
            # stderr; overridden only to control the format, keeping stdout
            # free for the one-line "serving at" banner cmd_serve prints.
            sys.stderr.write(
                "%s - - [%s] %s\n"
                % (self.address_string(), self.log_date_time_string(), fmt % args)
            )

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def _dispatch(self, method: str) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            # Query params are merged into the same `params` dict a handler
            # already receives for path params (e.g. {conversation_id}) --
            # first-value-only, since nothing here needs repeated keys. Path
            # params win on a name collision (there isn't one today, but if
            # there ever is, the explicit part of the URL should be
            # authoritative over an incidental query string).
            query_params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

            handler, path_params, path_known = routing.match(method, path)
            if handler is not None:
                self._call_api_handler(handler, {**query_params, **(path_params or {})})
                return
            if path_known:
                self._send_json(
                    405,
                    {
                        "error": "method_not_allowed",
                        "message": f"{method} not allowed for {path}",
                    },
                )
                return
            if path.startswith("/static/"):
                self._serve_static(path[len("/static/") :])
                return
            if path in PAGES:
                self._serve_static(PAGES[path])
                return
            self._send_json(
                404, {"error": "not_found", "message": f"no route for {method} {path}"}
            )

        def _call_api_handler(self, handler, params: dict) -> None:
            try:
                body = self._read_json_body()
                result = handler(state, params, body)
                status, payload = result if isinstance(result, tuple) else (200, result)
                self._send_json(status, payload)
            except ApiError as exc:
                self._send_bytes(exc.status, exc.to_bytes(), "application/json; charset=utf-8")
            except Exception as exc:  # noqa: BLE001 -- never let an unexpected error hang the socket
                print(
                    f"[webui] unhandled exception in {handler}: "
                    f"{exc.__class__.__name__}: {exc}",
                    file=sys.stderr,
                )
                self._send_json(
                    500, {"error": "internal_error", "message": f"{exc.__class__.__name__}: {exc}"}
                )

        def _read_json_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ApiError(
                    400, "invalid_json", f"request body is not valid UTF-8 JSON: {exc}"
                ) from exc
            if not isinstance(payload, dict):
                raise ApiError(400, "invalid_json", "request body must be a JSON object")
            return payload

        def _send_json(self, status: int, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(status, body, "application/json; charset=utf-8")

        def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_static(self, rel_path: str) -> None:
            if not rel_path:
                rel_path = "index.html"
            candidate = (STATIC_DIR / rel_path).resolve()
            try:
                candidate.relative_to(STATIC_DIR)
            except ValueError:
                self._send_json(404, {"error": "not_found", "message": "not found"})
                return
            if not candidate.is_file():
                self._send_json(404, {"error": "not_found", "message": "not found"})
                return
            content_type = _CONTENT_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
            self._send_bytes(200, candidate.read_bytes(), content_type)

    return Handler
