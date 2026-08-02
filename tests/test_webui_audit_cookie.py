"""The side that writes the session cookie and the side that reads it agree.

handlers_audit.py sets it on login; httphandler.py looks it up on every
request. The name used to be a separate literal in each file with nothing
tying them together, and getting them out of step fails quietly in the worst
way: login still answers 200 and still sets a cookie, the dispatcher simply
never finds it, and every request afterwards answers 401. On screen that
reads as "a sessão de auditoria expirou" -- immediately, repeatedly, for a
password that is perfectly correct.

It is now one constant in auth.py. These tests are the behavioural half: they
would fail on a rename in either module even if someone re-introduced the
second literal, because they go through real HTTP and never mention the name.
"""

from __future__ import annotations

import http.cookies

import pytest

from ethical_agent.webui import auth, handlers_audit, httphandler
from webui_support import TOOLS_PASSWORD, RunningServer


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path, engine="rule", audit_password=TOOLS_PASSWORD)
    yield running
    running.close()


def test_the_cookie_login_sets_is_the_one_the_dispatcher_accepts(server):
    # The round trip, with the name never written down here: log in, take
    # whatever cookie came back, and use only that.
    status, _, headers = server.login_as_auditor(TOOLS_PASSWORD)
    assert status == 200

    jar = http.cookies.SimpleCookie()
    jar.load(headers["Set-Cookie"])
    assert len(jar) == 1, "o login devia definir exatamente um cookie"
    (name, morsel), = jar.items()

    # Fresh client state: only the cookie the server just handed out.
    server.cookies = {name: morsel.value}
    status, _, _ = server.get("/api/audit/records")
    assert status == 200, "o servidor não reconheceu o cookie que ele mesmo definiu"


def test_a_cookie_by_any_other_name_is_not_a_session(server):
    status, _, headers = server.login_as_auditor(TOOLS_PASSWORD)
    assert status == 200
    jar = http.cookies.SimpleCookie()
    jar.load(headers["Set-Cookie"])
    (name, morsel), = jar.items()

    # Same token, wrong name -- this is what a rename on one side produces.
    server.cookies = {name + "_x": morsel.value}
    status, _, _ = server.get("/api/audit/records")
    assert status == 401


def test_logout_clears_the_same_cookie_it_was_given(server):
    server.login_as_auditor(TOOLS_PASSWORD)
    status, _, headers = server.post("/api/audit/logout", {})
    assert status == 200

    jar = http.cookies.SimpleCookie()
    jar.load(headers["Set-Cookie"])
    (name, morsel), = jar.items()
    assert morsel.value == "", "o logout tem de esvaziar o cookie, não só expirá-lo"
    assert morsel["max-age"] == "0"

    status, _, _ = server.get("/api/audit/records")
    assert status == 401


def test_there_is_exactly_one_definition_of_the_name():
    # The structural half. Both modules must be looking at auth's object, not
    # at a copy that happens to spell the same thing today.
    assert handlers_audit.AUDIT_SESSION_COOKIE is auth.AUDIT_SESSION_COOKIE
    assert httphandler.AUDIT_SESSION_COOKIE is auth.AUDIT_SESSION_COOKIE
