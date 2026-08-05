from __future__ import annotations

import http.cookies
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from . import routing
from .auth import AUDIT_SESSION_COOKIE
from .errors import ApiError

STATIC_DIR = (Path(__file__).resolve().parent / "static").resolve()

# Clean URLs for the shell pages -- each maps 1:1 to a static HTML file that
# lives directly under static/.
PAGES = {
    "/": "index.html",
}

# Páginas e assets que só existem quando o realm está configurado,
# deliberadamente NÃO fundidos em `PAGES`: tabela separada é busca separada, e
# busca separada é a que não se alcança sem passar pelo portão — versão longa em `997a6fe^`.
GATED_PAGES = {
    "/audit": ("audit.html", "audit", False),
    "/check": ("check.html", "audit", True),
    "/demo": ("demo.html", "audit", True),
    "/eval": ("eval.html", "audit", True),
}

# E o mesmo para o JS/CSS dessas telas: barrar rota e página mas não os assets
# deixaria o frontend inteiro legível no modo chat.
GATED_ASSET_PREFIXES = (
    ("js/audit/", "audit", False),
    ("css/audit.css", "audit", False),
    ("js/tools/", "audit", True),
)

# Params whose names start with "_" are the server's own namespace: the
# dispatcher strips any the client sent before injecting its own, so a
# handler reading params["_session_id"] is reading something only the
# dispatcher can have put there. Without the strip, ?_session_id=whatever
# would be a forgeable identity.
_RESERVED_PARAM_PREFIX = "_"

# Teto do que se lê para descartar, em `_drain_request_body`. O corpo de uma
# requisição recusada é, por definição, de alguém que já errou a rota ou não
# tem sessão, então ler sem limite é aceitar trabalho de quem não passou por
# nenhuma checagem. Acima do teto, a conexão é fechada com o corpo pela
# metade -- o cliente pode perder a resposta, que é exatamente o defeito que a
# drenagem existe para evitar, mas é a troca certa: quem manda mais de 1 MiB
# para uma rota que não existe não está esperando ler o 404 com cuidado.
_MAX_DRAIN_BYTES = 1 << 20

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

        # Default de classe além do reset por requisição em `_dispatch`. Hoje
        # todo caminho até `_send_bytes` passa por lá, então isto não cobre
        # nenhum caso conhecido -- é para que um caminho novo que responda sem
        # passar pelo dispatch falhe drenando à toa, e não com AttributeError
        # no meio de uma resposta.
        _body_consumed = False

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
            # Reset per REQUEST, not per instance: with HTTP/1.1 keep-alive one
            # Handler serves several requests on the same connection, and a
            # session cached across them would outlive the cookie that proved
            # it.
            self._session_resolved = False
            self._session = None
            # Por REQUISIÇÃO, pela mesma razão da sessão logo acima: com
            # keep-alive um Handler serve várias, e o corpo de uma não pode
            # contar como lido para a seguinte.
            self._body_consumed = False
            parsed = urllib.parse.urlsplit(self.path)
            path = urllib.parse.unquote(parsed.path)
            # Query params entram no mesmo dict dos params de caminho, só primeiro valor,
            # e os de caminho vencem em colisão.
            query_params = {
                k: v[0]
                for k, v in urllib.parse.parse_qs(parsed.query).items()
                if not k.startswith(_RESERVED_PARAM_PREFIX)
            }

            matched, path_params, path_known = routing.match(
                method, path, state.realm_enabled, self._has_session
            )
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
                filename, realm, needs_session = gated
                if state.realm_enabled(realm) and (
                    not needs_session or self._has_session()
                ):
                    # `/audit` é servido sem sessão de propósito: é a casca de login e não contém
                    # registro nenhum; todo endpoint de dados atrás dela ainda responde 401.
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
            """Conferência central de sessão; devolve False já tendo respondido.
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

        def _has_session(self) -> bool:
            """Zero-arg predicate for routing.match / the gated tables.
            Memoized for the current request so a path that consults it twice
            (route lookup, then _authorize) parses the cookie once."""
            return self._resolve_session() is not None

        def _resolve_session(self):
            if self._session_resolved:
                return self._session
            self._session_resolved = True
            self._session = self._resolve_session_uncached()
            return self._session

        def _resolve_session_uncached(self):
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
            # Marcado mesmo com length 0: o que interessa a `_send_bytes` é se
            # ainda sobrou byte no socket, e com corpo vazio não sobrou.
            self._body_consumed = True
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

        def _drain_request_body(self) -> None:
            """Lê e descarta o corpo que handler nenhum leu, ANTES de responder.

            Sem isto, responder 404/405/401 a um POST deixa o corpo parado no
            buffer de recepção do socket. Fechar um socket nessa situação manda
            RST no lugar de FIN -- é o comportamento do Windows, medido aqui --
            e o RST descarta a resposta que o servidor JÁ tinha escrito, mas que
            o cliente ainda não terminou de ler. O cliente levanta
            `ConnectionAbortedError` (WinError 10053) e nunca vê o 404.

            Não é problema de teste: `urllib` manda `Connection: close`, e um
            `fetch()` de navegador numa rota gated tem o mesmo par de condições.
            Medido antes do conserto: 6 falhas em 3000 POSTs, ~0,2%. É pouco por
            requisição e muito por suíte -- era a instabilidade de
            `test_webui_tools_gate.py`.

            A ordem importa: drenar DEPOIS de escrever a resposta não adianta,
            porque o fechamento vem logo em seguida e a corrida é a mesma.
            """
            if self._body_consumed:
                return
            self._body_consumed = True
            try:
                restante = min(int(self.headers.get("Content-Length") or 0), _MAX_DRAIN_BYTES)
            except (TypeError, ValueError):
                # Content-Length ilegível: não dá para saber onde o corpo
                # termina, e ler às cegas travaria até o timeout.
                return
            while restante > 0:
                pedaco = self.rfile.read(min(restante, 64 * 1024))
                if not pedaco:  # cliente fechou antes de mandar tudo
                    break
                restante -= len(pedaco)

        def _send_bytes(
            self, status: int, body: bytes, content_type: str, extra_headers=None
        ) -> None:
            self._drain_request_body()
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
            for prefix, realm, needs_session in GATED_ASSET_PREFIXES:
                if not rel_path.startswith(prefix):
                    continue
                if not state.realm_enabled(realm) or (
                    needs_session and not self._has_session()
                ):
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
