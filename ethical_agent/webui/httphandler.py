from __future__ import annotations

import http.cookies
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from . import routing
from .errors import ApiError

STATIC_DIR = (Path(__file__).resolve().parent / "static").resolve()

# Clean URLs for the shell pages -- each maps 1:1 to a static HTML file that
# lives directly under static/.
PAGES = {
    "/": "index.html",
    "/check": "check.html",
    "/demo": "demo.html",
    "/eval": "eval.html",
}

# Pages and static assets that only exist when their realm is configured.
# Deliberately NOT merged into PAGES: a separate table is a separate lookup,
# and a separate lookup is one that cannot be reached without passing the
# gate. Someone adding a sixth ordinary page to PAGES gets no chance to
# accidentally add a gated one.
GATED_PAGES = {"/audit": ("audit.html", "audit")}

# ... and the same for the screen's own JS/CSS. Gating the routes and the
# page but not the assets would leave the whole audit frontend readable in
# chat mode, which is why every audit module lives under static/js/audit/:
# one prefix to gate instead of nine filenames to remember.
GATED_ASSET_PREFIXES = (
    ("js/audit/", "audit"),
    ("css/audit.css", "audit"),
)

AUDIT_SESSION_COOKIE = "ea_audit_session"

# Params whose names start with "_" are the server's own namespace: the
# dispatcher strips any the client sent before injecting its own, so a
# handler reading params["_session_id"] is reading something only the
# dispatcher can have put there. Without the strip, ?_session_id=whatever
# would be a forgeable identity.
_RESERVED_PARAM_PREFIX = "_"

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
            query_params = {
                k: v[0]
                for k, v in urllib.parse.parse_qs(parsed.query).items()
                if not k.startswith(_RESERVED_PARAM_PREFIX)
            }

            matched, path_params, path_known = routing.match(method, path, state.realm_enabled)
            if matched is not None:
                params = {**query_params, **(path_params or {})}
                if not self._authorize(matched, params):
                    return
                self._call_api_handler(matched.handler, params)
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
            gated = GATED_PAGES.get(path)
            if gated is not None:
                filename, realm = gated
                if state.realm_enabled(realm):
                    # Served without a session on purpose: this is the login
                    # shell, and it contains no records. Every data endpoint
                    # behind it still answers 401. Documented as the one
                    # deliberate exception to "the screen does not exist".
                    self._serve_static(filename)
                    return
            self._not_found(method, path)

        def _not_found(self, method: str, path: str) -> None:
            # One place, one wording. A gated path that is switched off must
            # be byte-identical to a path that was never registered -- if the
            # two ever drift, the difference is itself the disclosure.
            self._send_json(
                404, {"error": "not_found", "message": f"no route for {method} {path}"}
            )

        def _authorize(self, matched, params: dict) -> bool:
            """Central session check. Returns False having already answered.

            This lives here rather than in each handler so that a route added
            later is protected by declaring requires_session=True, with no
            second chance to forget the check in the handler body.
            """
            if not matched.requires_session:
                return True
            session = self._resolve_session()
            if session is None:
                self._send_json(
                    401,
                    {
                        "error": "unauthorized",
                        "message": "sessão de auditoria ausente ou expirada",
                    },
                )
                return False
            params["_session_id"] = session.session_id
            params["_session_token"] = session.token
            return True

        def _resolve_session(self):
            raw = self.headers.get("Cookie")
            if not raw:
                return None
            try:
                jar = http.cookies.SimpleCookie()
                jar.load(raw)
            except http.cookies.CookieError:
                return None
            morsel = jar.get(AUDIT_SESSION_COOKIE)
            if morsel is None:
                return None
            return state.audit_auth.resolve(morsel.value)

        def _call_api_handler(self, handler, params: dict) -> None:
            try:
                body = self._read_json_body()
                result = handler(state, params, body)
                # (status, payload) or (status, payload, extra_headers). The
                # third element is how the login route sets its cookie without
                # every other handler learning about response headers.
                if isinstance(result, tuple):
                    status, payload, *rest = result
                    extra_headers = rest[0] if rest else None
                else:
                    status, payload, extra_headers = 200, result, None
                self._send_json(status, payload, extra_headers)
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

        def _send_json(self, status: int, payload, extra_headers=None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(status, body, "application/json; charset=utf-8", extra_headers)

        def _send_bytes(
            self, status: int, body: bytes, content_type: str, extra_headers=None
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra_headers or []):
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _serve_static(self, rel_path: str) -> None:
            if not rel_path:
                rel_path = "index.html"
            for prefix, realm in GATED_ASSET_PREFIXES:
                if rel_path.startswith(prefix) and not state.realm_enabled(realm):
                    # Must be byte-identical to the "no such static file"
                    # answer a few lines below, not to the API 404 -- a
                    # distinctive wording here would announce that the file
                    # exists and is merely switched off, which is the one
                    # thing the gate is for.
                    self._send_json(404, {"error": "not_found", "message": "not found"})
                    return
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
