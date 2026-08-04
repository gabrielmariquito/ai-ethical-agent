import pytest

from ethical_agent.webui.handlers_browse import ALLOWED_ROOTS, REPO_ROOT
from webui_support import RunningServer


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path)
    yield running
    running.close()


def test_browse_defaults_to_repo_root(server):
    status, body, _ = server.get("/api/browse")
    assert status == 200
    assert body["path"] == str(REPO_ROOT)
    assert isinstance(body["entries"], list)
    assert all({"name", "is_dir"} <= entry.keys() for entry in body["entries"])


def test_browse_lists_a_known_subdirectory(server):
    status, body, _ = server.get(f"/api/browse?path={REPO_ROOT / 'policies'}")
    assert status == 200
    names = {entry["name"] for entry in body["entries"]}
    assert "core_policy.json" in names


def test_browse_rejects_paths_outside_allowed_roots(server):
    outside = REPO_ROOT.parent.parent  # well above both the repo and (almost certainly) the home dir
    if any(str(outside).startswith(str(root)) for root in ALLOWED_ROOTS):
        pytest.skip("test host's directory layout puts this path inside an allowed root")
    status, body, _ = server.get(f"/api/browse?path={outside}")
    assert status == 400
    assert body["error"] == "path_not_allowed"


def test_browse_rejects_dot_dot_escape(server):
    escape_attempt = f"{REPO_ROOT}/../../../../../../"
    status, body, _ = server.get(f"/api/browse?path={escape_attempt}")
    # Either it resolves to something still inside an allowed root (unlikely
    # at 6 levels up) and succeeds, or it's rejected -- what must never
    # happen is a 200 response whose *resolved* path is outside every
    # allowed root.
    if status == 200:
        assert any(body["path"].startswith(str(root)) for root in ALLOWED_ROOTS)
    else:
        assert status == 400


def test_browse_rejects_file_path_as_not_a_directory(server):
    policy_file = REPO_ROOT / "policies" / "core_policy.json"
    status, body, _ = server.get(f"/api/browse?path={policy_file}")
    assert status == 400
    assert body["error"] == "not_a_directory"


def test_browse_hides_dotfiles(server):
    status, body, _ = server.get("/api/browse")
    assert status == 200
    assert not any(entry["name"].startswith(".") for entry in body["entries"])


def test_browse_only_exposes_name_and_is_dir(server):
    status, body, _ = server.get("/api/browse")
    assert status == 200
    for entry in body["entries"]:
        assert set(entry.keys()) == {"name", "is_dir"}
