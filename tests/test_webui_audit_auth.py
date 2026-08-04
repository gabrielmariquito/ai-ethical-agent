"""Access separation for the audit screen.

The requirement these tests encode is that the separation is *structural*,
not visual: hiding a link would not do, because the server is local and
anyone can reach an endpoint from the URL bar or devtools. So with no
password configured the audit surface must not merely refuse -- it must be
indistinguishable from a path that was never registered, for every method.
"""
from __future__ import annotations

import json

import pytest

from ethical_agent.webui.auth import (
    AuditPasswordError,
    dotenv_password_present,
    load_audit_password,
)
from webui_support import RunningServer

PASSWORD = "senha-de-teste"

# Every audit path, so a route added later without a realm= marker shows up
# here as a failure rather than as a quiet hole.
AUDIT_API_PATHS = [
    "/api/audit/login",
    "/api/audit/logout",
    "/api/audit/session",
    "/api/audit/session/events",
    "/api/audit/records",
    "/api/audit/records/some-event-id",
    "/api/audit/conversations/some-conversation",
    "/api/audit/telemetry",
    "/api/audit/change-requests",
]


@pytest.fixture
def chat_server(tmp_path):
    """No password -> the audit screen does not exist."""
    running = RunningServer(tmp_path)
    yield running
    running.close()


@pytest.fixture
def audit_server(tmp_path):
    running = RunningServer(tmp_path, audit_password=PASSWORD)
    yield running
    running.close()


def test_audit_api_requires_password_when_configured(audit_server):
    # Without a session, no audit data is reachable at all.
    status, body, _ = audit_server.get("/api/audit/records")
    assert status == 401, body
    assert body["error"] == "unauthorized"

    # A wrong password neither logs in nor loosens anything.
    status, body, _ = audit_server.login_as_auditor("nao-e-a-senha")
    assert status == 401, body
    assert body["error"] == "invalid_password"
    status, _, _ = audit_server.get("/api/audit/records")
    assert status == 401

    status, body, _ = audit_server.login_as_auditor(PASSWORD)
    assert status == 200, body
    status, body, _ = audit_server.get("/api/audit/records")
    assert status == 200, body
    assert "records" in body


def test_audit_endpoints_do_not_exist_in_chat_mode(chat_server):
    # The reference 404s: one for an unregistered API path, one for a missing
    # static file (the two answer with different wording, so each gated
    # surface has to match the right one -- a distinctive body would itself
    # announce that the thing exists and is merely switched off).
    _, api_404, _ = chat_server.request("GET", "/api/does-not-exist")
    _, static_404, _ = chat_server.request("GET", "/static/js/nope.js")

    for path in AUDIT_API_PATHS + ["/audit"]:
        for method in ("GET", "POST"):
            status, raw, _ = chat_server.request(
                method, path, {} if method == "POST" else None
            )
            assert status == 404, (method, path, raw)
            expected = json.dumps(
                {"error": "not_found", "message": f"no route for {method} {path}"},
                ensure_ascii=False,
            ).encode("utf-8")
            assert raw == expected, (method, path, raw)
    assert api_404.startswith(b'{"error": "not_found"')

    # The screen's own assets are gated too. Serving them would leave the
    # whole audit frontend readable in chat mode; that they live under one
    # static/js/audit/ prefix is what makes the gate a single check.
    for path in (
        "/static/js/audit/audit-app.js",
        "/static/js/audit/audit-layers.js",
        "/static/css/audit.css",
    ):
        status, raw, _ = chat_server.request("GET", path)
        assert status == 404, path
        assert raw == static_404, path


def test_audit_wrong_method_is_404_not_405_in_chat_mode(chat_server):
    # The regression this guards: _dispatch marks path_known from any pattern
    # that matches, ignoring the method. If the realm were filtered after
    # that, a POST to a GET-only audit path would answer 405 and confirm the
    # route exists. The gate has to happen inside routing.match(), before
    # path_known is set.
    status, body, _ = chat_server.post("/api/audit/records", {})
    assert status == 404, body
    assert body["error"] == "not_found"

    # Sanity: a genuinely known path still 405s, so the test above is not
    # passing because 405 stopped happening everywhere.
    status, body, _ = chat_server.get("/api/chat/new")
    assert status == 405, body


def test_audit_page_serves_login_shell_but_no_records_without_session(audit_server):
    # The one deliberate exception to "the screen does not exist": with a
    # password configured, /audit serves the login form, which holds no
    # records. Everything behind it still 401s.
    status, raw, headers = audit_server.request("GET", "/audit")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"ea-audit-login" in raw
    for path in ("/api/audit/records", "/api/audit/session"):
        status, _, _ = audit_server.get(path)
        assert status == 401, path


def test_login_cookie_is_httponly_samesite_and_has_no_secure_flag(audit_server):
    status, _, headers = audit_server.login_as_auditor(PASSWORD)
    assert status == 200
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    # No Secure attribute, deliberately: this server is plain HTTP on
    # 127.0.0.1 and a Secure cookie would never be sent back, breaking the
    # screen entirely. Asserted so nobody "hardens" it into non-function.
    assert "Secure" not in cookie


def test_session_token_never_appears_in_any_log_file(audit_server, tmp_path):
    status, body, headers = audit_server.login_as_auditor(PASSWORD)
    assert status == 200
    token = headers["Set-Cookie"].split("=", 1)[1].split(";", 1)[0]
    assert token

    audit_server.post(
        "/api/audit/telemetry",
        {"events": [{"seq": 1, "type": "session_started", "payload": {}}]},
    )
    audit_server.post(
        "/api/audit/change-requests", {"record_event_id": "abc", "rule_id": "R-1"}
    )

    # The session_id identifies the session in the file; the token
    # authenticates. Writing the latter would put a live credential in an
    # artifact meant to be read and shared.
    for path in (
        audit_server.auditor_session_log,
        audit_server.change_requests_log,
        audit_server.audit_log_path,
    ):
        try:
            with open(path, encoding="utf-8") as handle:
                assert token not in handle.read(), path
        except FileNotFoundError:
            pass
    assert body["session_id"] != token


def test_lockout_after_five_failures_returns_429_with_retry_after(audit_server):
    for _ in range(4):
        status, _, _ = audit_server.login_as_auditor("errada")
        assert status == 401
    status, body, _ = audit_server.login_as_auditor("errada")
    assert status == 429, body
    assert body["error"] == "too_many_attempts"
    # Even the correct password is refused while locked out -- otherwise the
    # lockout would only slow down someone who never guesses right.
    status, body, _ = audit_server.login_as_auditor(PASSWORD)
    assert status == 429, body


def test_session_invalid_after_server_restart(tmp_path):
    first = RunningServer(tmp_path, audit_password=PASSWORD)
    try:
        status, _, _ = first.login_as_auditor(PASSWORD)
        assert status == 200
        cookies = dict(first.cookies)
        status, _, _ = first.get("/api/audit/records")
        assert status == 200
    finally:
        first.close()

    second = RunningServer(tmp_path, audit_password=PASSWORD)
    try:
        # Sessions live in process memory only, so a restart invalidates
        # them. Documented behaviour: persisting a session token to disk
        # would mean writing a credential next to the trail it unlocks.
        second.cookies = cookies
        status, body, _ = second.get("/api/audit/records")
        assert status == 401, body
    finally:
        second.close()


def test_reserved_underscore_params_cannot_be_forged(audit_server):
    # Handlers read params["_session_id"], which the dispatcher injects. Any
    # client-supplied param starting with "_" is stripped first, so the query
    # string cannot manufacture an identity.
    status, body, _ = audit_server.get("/api/audit/records?_session_id=forjado")
    assert status == 401, body

    status, _, _ = audit_server.login_as_auditor(PASSWORD)
    assert status == 200
    status, body, _ = audit_server.get("/api/audit/session?_session_id=forjado")
    assert status == 200
    assert body["session_id"] != "forjado"


def test_choices_endpoint_never_exposes_the_password(audit_server):
    # handlers_choices.py serves dict(initial_config) verbatim, unauthenticated.
    # The password is kept in AuditAuth precisely so it cannot ride along;
    # this asserts the whole payload, not just the keys we expect.
    status, raw, _ = audit_server.request("GET", "/api/choices")
    assert status == 200
    assert PASSWORD.encode("utf-8") not in raw
    body = json.loads(raw)
    assert body["audit_screen_enabled"] is True
    assert not any("password" in key.lower() for key in body["defaults"])


def test_choices_reports_audit_disabled_in_chat_mode(chat_server):
    status, body, _ = chat_server.get("/api/choices")
    assert status == 200
    assert body["audit_screen_enabled"] is False


def test_non_ascii_password_round_trips(tmp_path):
    # hmac.compare_digest raises TypeError on non-ASCII str, so both sides
    # are hashed to bytes first. A pt-BR password with an accent is entirely
    # likely, and this is the trap that would only surface in the field.
    password = "sênha-com-acento-çãó"
    server = RunningServer(tmp_path, audit_password=password)
    try:
        status, body, _ = server.login_as_auditor(password)
        assert status == 200, body
        status, _, _ = server.get("/api/audit/records")
        assert status == 200
    finally:
        server.close()


# -- the three password sources and their order ------------------------------
#
# Every one of these passes root=tmp_path explicitly. The default is the real
# repository root, so a developer who has configured an audit password for
# themselves -- which this feature now makes easy -- would otherwise watch
# these tests start failing for reasons that have nothing to do with the code.


def _dotenv(root, value):
    (root / ".env").write_text(
        f"OLLAMA_MODEL=llama3.2:3b\nETHICAL_AGENT_AUDIT_PASSWORD={value}\n",
        encoding="utf-8",
    )
    return root


def test_password_file_takes_precedence_over_env_var(tmp_path):
    path = tmp_path / "senha.txt"
    path.write_text("do-arquivo\n", encoding="utf-8")
    password, source, _ = load_audit_password(
        str(path), {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}, root=tmp_path
    )
    assert password == "do-arquivo"
    assert str(path) in source
    # ...and the value itself never appears in the description, which is the
    # only part of this that gets printed.
    assert "do-arquivo" not in source


def test_the_env_var_is_not_a_password_source_any_more(tmp_path):
    # It was, and it outranked .env. What replaced it is not "the variable
    # loses" -- it is not read at all, so leaving it set has to be refused
    # rather than ignored: someone who exported it believes they configured
    # a password, and silence would take the audit screen away without ever
    # telling them.
    with pytest.raises(AuditPasswordError) as excinfo:
        load_audit_password(
            None, {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}, root=tmp_path
        )

    message = str(excinfo.value)
    assert "$ETHICAL_AGENT_AUDIT_PASSWORD" in message
    assert "apague a variável" in message.lower()
    assert "do-ambiente" not in message


def test_dotenv_used_when_there_is_no_file_and_no_env_var(tmp_path):
    # The wizard's path: a password in .env and `serve` with no flag at all.
    password, source, _ = load_audit_password(None, {}, root=_dotenv(tmp_path, "do-dotenv"))
    assert password == "do-dotenv"
    assert source == ".env (ETHICAL_AGENT_AUDIT_PASSWORD)"
    assert "do-dotenv" not in source


def test_a_leftover_variable_that_disagrees_with_dotenv_is_refused(tmp_path):
    with pytest.raises(AuditPasswordError) as excinfo:
        load_audit_password(
            None,
            {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"},
            root=_dotenv(tmp_path, "do-dotenv"),
        )

    message = str(excinfo.value)
    assert "$ETHICAL_AGENT_AUDIT_PASSWORD" in message
    assert str((tmp_path / ".env").resolve()) in message
    assert "--audit-password-file" in message
    # It may say they differ. It may not say how, and may not quote either.
    assert "do-ambiente" not in message
    assert "do-dotenv" not in message


def test_a_leftover_variable_that_repeats_the_dotenv_password_is_silent(tmp_path):
    # Nothing is ambiguous, so there is nothing to refuse -- and this is the
    # state python-dotenv's load_dotenv() can produce on its own by copying
    # .env into os.environ, which a presence-only rule would refuse over one
    # password seen twice.
    password, source, _ = load_audit_password(
        None,
        {"ETHICAL_AGENT_AUDIT_PASSWORD": "a-mesma"},
        root=_dotenv(tmp_path, "a-mesma"),
    )
    assert password == "a-mesma"
    assert source == ".env (ETHICAL_AGENT_AUDIT_PASSWORD)"


def test_password_file_silences_the_tripwire(tmp_path):
    # The regression test for where the check sits: inside
    # load_audit_password, *after* the --audit-password-file branch has
    # already returned. The flag states which password to use, so a leftover
    # variable cannot make the invocation ambiguous. (cmd_serve still names
    # it in the banner -- silencing the refusal is not saying nothing.)
    path = tmp_path / "senha.txt"
    path.write_text("do-arquivo\n", encoding="utf-8")
    password, source, _ = load_audit_password(
        str(path), {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}, root=_dotenv(tmp_path, "do-dotenv")
    )
    assert password == "do-arquivo"
    assert "do-arquivo" not in source
    assert "do-dotenv" not in source
    assert "do-ambiente" not in source


def test_a_variable_with_a_dotenv_that_has_no_password_is_refused(tmp_path):
    # The .env exists and is read -- it just does not carry this key. Nothing
    # would be in effect, so the variable's owner would lose the screen in
    # silence. This is the case that used to work, and it is the one the
    # README's one-liner produced.
    (tmp_path / ".env").write_text("OLLAMA_MODEL=llama3.2:3b\n", encoding="utf-8")
    with pytest.raises(AuditPasswordError) as excinfo:
        load_audit_password(
            None, {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}, root=tmp_path
        )
    assert "wizard_gui.py" in str(excinfo.value), "tem de dizer onde a senha passa a morar"


def test_a_blank_env_var_is_not_a_leftover_at_all(tmp_path):
    # An exported-but-empty variable is how a shell profile leaves the name
    # defined without meaning anything by it. Refusing over that would be
    # refusing over nothing.
    password, source, _ = load_audit_password(
        None, {"ETHICAL_AGENT_AUDIT_PASSWORD": "   "}, root=_dotenv(tmp_path, "do-dotenv")
    )
    assert password == "do-dotenv"
    assert source == ".env (ETHICAL_AGENT_AUDIT_PASSWORD)"

    # ...and with nothing configured anywhere, a blank variable is still just
    # a disabled audit screen, not an error.
    password, source, _ = load_audit_password(
        None, {"ETHICAL_AGENT_AUDIT_PASSWORD": ""}, root=tmp_path / "vazio"
    )
    assert password is None
    assert source is None


def test_the_resolver_never_reads_the_real_environment_when_env_is_passed(monkeypatch, tmp_path):
    # The property every other test in this file leans on: `env` is honoured
    # exactly, so a developer's own exported password cannot reach in. It
    # matters more now that a stray variable raises instead of being ranked.
    monkeypatch.setenv("ETHICAL_AGENT_AUDIT_PASSWORD", "veneno-do-ambiente-real")
    password, source, _ = load_audit_password(None, {}, root=_dotenv(tmp_path, "do-dotenv"))
    assert password == "do-dotenv"
    assert source == ".env (ETHICAL_AGENT_AUDIT_PASSWORD)"


def test_dotenv_password_present_reports_the_loser_without_the_value(tmp_path):
    # What the startup banner uses to say "the .env also has one, and it is
    # not the one in effect" -- a boolean, never the value.
    assert dotenv_password_present(root=_dotenv(tmp_path, "do-dotenv")) is True
    assert dotenv_password_present(root=tmp_path / "vazio") is False


def test_empty_key_in_dotenv_is_not_configured_rather_than_an_error(tmp_path):
    # The opposite of an empty --audit-password-file below: nobody points at
    # .env on purpose, so a blank line there is silence, not a broken request.
    (tmp_path / ".env").write_text(
        "OLLAMA_MODEL=llama3.2:3b\nETHICAL_AGENT_AUDIT_PASSWORD=\n", encoding="utf-8"
    )
    password, source, _ = load_audit_password(None, {}, root=tmp_path)
    assert password is None
    assert source is None


def test_dotenv_password_may_contain_spaces_and_a_hash(tmp_path):
    # The hand-rolled parser is authoritative for this key, and it takes the
    # whole rest of the line: a `#` is part of the password, not a comment.
    # Surrounding whitespace is stripped on both write and read, so what the
    # login check compares is what the installer stored.
    from ethical_agent.ollama_install import write_env_audit_password

    write_env_audit_password(tmp_path, "  senha com espaços #1  ")
    password, _, _ = load_audit_password(None, {}, root=tmp_path)
    assert password == "senha com espaços #1"


def test_no_password_source_means_the_screen_is_disabled(tmp_path):
    password, source, warnings = load_audit_password(None, {}, root=tmp_path)
    assert password is None
    assert source is None
    assert warnings == []


def test_empty_password_file_is_a_startup_error(tmp_path):
    path = tmp_path / "vazio.txt"
    path.write_text("   \n", encoding="utf-8")
    # Failing loudly beats silently starting a server whose audit screen
    # quietly does not exist -- the operator explicitly asked for it.
    with pytest.raises(AuditPasswordError):
        load_audit_password(str(path), {}, root=tmp_path)
