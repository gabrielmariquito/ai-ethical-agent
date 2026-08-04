"""As ferramentas do avaliador não **existem** sem sessão, e não apenas são
recusadas — 401 confirma que o endpoint está lá, e 405 confirma ainda mais.
A distinção contra `/api/audit/*`, que responde 401, é deliberada e também
testada aqui: `REGISTRO`, "Texto movido do código".
"""

from __future__ import annotations

import pytest

from webui_support import TOOLS_PASSWORD, RunningServer

TOOL_ENDPOINTS = ("/api/check", "/api/demo", "/api/eval")
TOOL_PAGES = ("/check", "/demo", "/eval")
TOOL_ASSETS = (
    "/static/js/tools/check.js",
    "/static/js/tools/demo.js",
    "/static/js/tools/eval.js",
)
NEVER_REGISTERED = "/api/definitivamente-nao-existe"
NEVER_REGISTERED_PAGE = "/pagina-que-nunca-existiu"
NEVER_REGISTERED_ASSET = "/static/js/tools/nao-existe.js"


@pytest.fixture
def no_password(tmp_path):
    running = RunningServer(tmp_path, engine="rule")
    yield running
    running.close()


@pytest.fixture
def password_no_session(tmp_path):
    running = RunningServer(tmp_path, engine="rule", audit_password=TOOLS_PASSWORD)
    yield running
    running.close()


@pytest.fixture
def signed_in(tmp_path):
    running = RunningServer(tmp_path, engine="rule", audit_password=TOOLS_PASSWORD)
    status, body, _ = running.login_as_auditor(TOOLS_PASSWORD)
    assert status == 200, (status, body)
    yield running
    running.close()


# --------------------------------------------------- byte-identical 404s


@pytest.mark.parametrize("fixture_name", ["no_password", "password_no_session"])
@pytest.mark.parametrize("path", TOOL_ENDPOINTS)
def test_tool_endpoints_answer_exactly_like_a_path_nobody_registered(
    fixture_name, path, request
):
    server = request.getfixturevalue(fixture_name)
    status, body, _ = server.post(path, {})
    baseline_status, baseline_body, _ = server.post(NEVER_REGISTERED, {})

    assert status == 404, path
    assert baseline_status == 404
    # The message names the path, so compare the shape and every other field:
    # a difference anywhere else is itself the disclosure.
    assert body.keys() == baseline_body.keys()
    assert body["error"] == baseline_body["error"]
    assert body["message"] == f"no route for POST {path}"


@pytest.mark.parametrize("fixture_name", ["no_password", "password_no_session"])
@pytest.mark.parametrize("path", TOOL_ENDPOINTS)
def test_the_wrong_method_is_404_too_not_405(fixture_name, path, request):
    # This is the one that actually leaks. path_known is what separates 404
    # from 405, so a route skipped *after* it is set answers "wrong method"
    # and thereby confirms the endpoint exists. routing.match() skips before.
    server = request.getfixturevalue(fixture_name)
    status, body, _ = server.get(path)
    baseline_status, baseline_body, _ = server.get(NEVER_REGISTERED)

    assert status == 404, f"{path} respondeu {status} -- 405 confirma que a rota existe"
    assert baseline_status == 404
    assert body.keys() == baseline_body.keys()
    assert body["error"] == baseline_body["error"]


@pytest.mark.parametrize("fixture_name", ["no_password", "password_no_session"])
@pytest.mark.parametrize("path", TOOL_PAGES)
def test_tool_pages_answer_exactly_like_a_page_nobody_registered(
    fixture_name, path, request
):
    server = request.getfixturevalue(fixture_name)
    status, raw, _ = server.request("GET", path)
    baseline_status, baseline_raw, _ = server.request("GET", NEVER_REGISTERED_PAGE)

    assert status == 404, path
    assert baseline_status == 404
    # Byte-identical apart from the path each names.
    assert raw.replace(path.encode(), b"") == baseline_raw.replace(
        NEVER_REGISTERED_PAGE.encode(), b""
    )


@pytest.mark.parametrize("fixture_name", ["no_password", "password_no_session"])
@pytest.mark.parametrize("path", TOOL_ASSETS)
def test_tool_assets_answer_exactly_like_a_missing_file(fixture_name, path, request):
    # Gating the routes and the page but not the JS would leave the whole
    # tool frontend readable, which is why they live under one prefix.
    server = request.getfixturevalue(fixture_name)
    status, raw, _ = server.request("GET", path)
    baseline_status, baseline_raw, _ = server.request("GET", NEVER_REGISTERED_ASSET)

    assert status == 404, path
    assert baseline_status == 404
    assert raw == baseline_raw


# ----------------------------------------------------- and they do work


@pytest.mark.parametrize("path", TOOL_PAGES)
def test_the_pages_are_served_once_signed_in(signed_in, path):
    status, raw, headers = signed_in.request("GET", path)
    assert status == 200, path
    assert b"<title>" in raw
    assert headers["Content-Type"].startswith("text/html")


@pytest.mark.parametrize("path", TOOL_ASSETS)
def test_the_assets_are_served_once_signed_in(signed_in, path):
    status, raw, headers = signed_in.request("GET", path)
    assert status == 200, path
    assert headers["Content-Type"].startswith("text/javascript")
    assert raw


def test_the_endpoints_answer_once_signed_in(signed_in):
    status, body, _ = signed_in.post(
        "/api/check", {"text": "Why is the sky blue?", "stage": "input", "config": {}}
    )
    assert status == 200
    assert body["verdict"]["decision"] == "ALLOW"


# ------------------------------------ the chat is untouched by all of this


@pytest.mark.parametrize("fixture_name", ["no_password", "password_no_session"])
def test_the_employee_still_has_the_chat(fixture_name, request):
    server = request.getfixturevalue(fixture_name)
    status, raw, _ = server.request("GET", "/")
    assert status == 200
    status, body, _ = server.post("/api/chat/new", {})
    assert status == 200
    assert body["conversation_id"]


# ------------------- the audit API keeps 401, and that is the whole point


def test_audit_api_still_refuses_rather_than_vanishing(password_no_session):
    # If this ever turns into a 404, the login screen loses the ability to
    # tell "not signed in" from "not there" -- and the reason the tools 404
    # stops being a criterion and becomes a coincidence.
    status, _, _ = password_no_session.get("/api/audit/records")
    assert status == 401


def test_the_two_answers_are_different_on_purpose(password_no_session):
    tool_status, _, _ = password_no_session.post("/api/check", {})
    audit_status, _, _ = password_no_session.get("/api/audit/records")
    assert (tool_status, audit_status) == (404, 401)


def test_the_audit_login_shell_is_still_reachable(password_no_session):
    # The one deliberate exception to "the screen does not exist": /audit is
    # the door, and it has to open for someone with no session yet.
    status, raw, _ = password_no_session.request("GET", "/audit")
    assert status == 200
    assert b"<title>" in raw
