import pytest

from webui_support import RunningServer


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path)
    yield running
    running.close()


def test_unknown_path_is_404(server):
    status, body, _ = server.get("/api/does-not-exist")
    assert status == 404
    assert body["error"] == "not_found"


def test_known_path_wrong_method_is_405(server):
    # /api/chat/new only accepts POST.
    status, body, _ = server.get("/api/chat/new")
    assert status == 405
    assert body["error"] == "method_not_allowed"


def test_chat_action_paths_do_not_collide_with_conversation_lookup(server):
    # Regression guard: GET /api/chat/conversations/{conversation_id} is a
    # single-segment wildcard under /api/chat/conversations/ specifically so
    # it can never be mistaken for the sibling literal paths /api/chat/new
    # and /api/chat/message -- a GET on either of those must 405 (wrong
    # method on a known path), never 200 with "new"/"message" treated as a
    # conversation id.
    for path in ("/api/chat/new", "/api/chat/message"):
        status, body, _ = server.get(path)
        assert status == 405, f"{path} unexpectedly matched a different route: {body}"


def test_index_page_served_at_root(server):
    status, raw, headers = server.request("GET", "/")
    assert status == 200
    assert b"<title>" in raw
    assert headers["Content-Type"].startswith("text/html")


def test_static_js_served_with_correct_content_type(server):
    status, raw, headers = server.request("GET", "/static/js/chat.js")
    assert status == 200
    assert headers["Content-Type"].startswith("text/javascript")
    assert b"conversation_id" in raw


def test_static_path_traversal_is_blocked(server):
    status, body, _ = server.get("/static/../../pyproject.toml")
    assert status == 404


def test_unknown_static_file_is_404(server):
    status, body, _ = server.get("/static/js/does-not-exist.js")
    assert status == 404


def test_check_demo_eval_pages_are_served(server):
    for path in ("/check", "/demo", "/eval"):
        status, raw, headers = server.request("GET", path)
        assert status == 200, path
        assert b"<title>" in raw
        assert headers["Content-Type"].startswith("text/html")


def test_audit_paths_do_not_collide_with_each_other(tmp_path):
    # Same hazard handlers_chat.py:26-33 documents: the router matches in
    # registration order with no literal-over-wildcard precedence, so a
    # single-segment wildcard sharing a level with a literal would swallow
    # it. /api/audit/records/{event_id} and
    # /api/audit/conversations/{conversation_id} each sit one segment deeper
    # than their sibling literals, and session/events is a literal pair --
    # this asserts that stays true.
    running = RunningServer(tmp_path, audit_password="senha-de-teste")
    try:
        status, _, _ = running.login_as_auditor("senha-de-teste")
        assert status == 200

        # GET-only paths must 405 on POST, i.e. still resolve to themselves
        # rather than being captured by a wildcard sibling.
        for path in ("/api/audit/records", "/api/audit/session"):
            status, body, _ = running.post(path, {})
            assert status == 405, (path, body)

        # POST-only paths must 405 on GET for the same reason.
        for path in ("/api/audit/login", "/api/audit/logout", "/api/audit/telemetry"):
            status, body, _ = running.get(path)
            assert status == 405, (path, body)

        # session/events is a real route, not "events" read as a parameter.
        status, body, _ = running.get("/api/audit/session/events")
        assert status == 200, body
        assert "events" in body
    finally:
        running.close()
