"""Shared helpers for tests/test_webui_*.py -- not a test module itself (no
test_ prefix), so pytest never collects it directly.

Spins up a real ethical_agent.webui server on an ephemeral 127.0.0.1 port and
talks to it over real HTTP (urllib), rather than importing handler functions
directly -- this is deliberate: it exercises the same code path a browser
would, including routing, JSON (de)serialization, and the job-polling flow,
so these tests can't pass while the actual wiring is broken.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from ethical_agent import (
    default_grounding_path,
    default_norms_path,
    default_policy_path,
    default_relaieo_ttl,
)
from ethical_agent.webui.server import make_server


# The evaluator's tools (Check, Demo, Eval) live behind the audit realm and
# require a session, so a server for them needs a password and a login. This
# is the password those tests use; nothing depends on its value.
TOOLS_PASSWORD = "senha-do-avaliador"


def running_tools_server(tmp_path, **overrides):
    """A RunningServer already signed in as the auditor, for the tool tests.

    Kept here rather than repeated in three modules so that "these screens
    need a session" is stated once. A test that wants the *unauthenticated*
    behaviour builds a RunningServer directly and does not log in -- see
    tests/test_webui_tools_gate.py, which is about exactly that.
    """
    running = RunningServer(tmp_path, audit_password=TOOLS_PASSWORD, **overrides)
    status, body, _ = running.login_as_auditor(TOOLS_PASSWORD)
    assert status == 200, (status, body)
    return running


def make_initial_config(tmp_path, engine="rule", mock=True, model="llama3.2:3b", **overrides):
    config = {
        "policy": str(default_policy_path()),
        "ontology": str(default_relaieo_ttl()),
        "grounding": str(default_grounding_path()),
        "norms": str(default_norms_path()),
        "engine": engine,
        "audit_log": str(tmp_path / "audit.jsonl"),
        "model": model,
        "mock": mock,
    }
    config.update(overrides)
    return config


class RunningServer:
    def __init__(
        self,
        tmp_path,
        audit_password=None,
        auditor_session_log=None,
        change_requests_log=None,
        **config_overrides,
    ):
        self.initial_config = make_initial_config(tmp_path, **config_overrides)
        self.auditor_session_log = auditor_session_log or str(tmp_path / "auditor_sessions.jsonl")
        self.change_requests_log = change_requests_log or str(tmp_path / "change_requests.jsonl")
        self.server = make_server(
            0,
            self.initial_config,
            audit_password=audit_password,
            auditor_session_log=self.auditor_session_log,
            change_requests_log=self.change_requests_log,
        )
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        self.base_url = f"http://127.0.0.1:{self.port}"
        # urllib has no cookie handling of its own, and the audit session is
        # a cookie (chosen so navigator.sendBeacon can carry it at page-hide
        # time). Holding it here keeps the tests exercising the same
        # credential flow a browser would.
        self.cookies: dict = {}

    @property
    def audit_log_path(self):
        return self.initial_config["audit_log"]

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # ---------------------------------------------------------------- HTTP

    def request(self, method: str, path: str, body=None, host: str | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json; charset=utf-8"} if data is not None else {}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        base = f"http://{host}:{self.port}" if host else self.base_url
        req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                self._store_cookies(resp.headers)
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            self._store_cookies(exc.headers)
            return exc.code, exc.read(), dict(exc.headers)

    def _store_cookies(self, headers) -> None:
        for raw in headers.get_all("Set-Cookie") or []:
            morsel = raw.split(";", 1)[0]
            if "=" not in morsel:
                continue
            name, value = morsel.split("=", 1)
            if value == "":
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value

    def login_as_auditor(self, password: str):
        status, body, headers = self.post("/api/audit/login", {"password": password})
        return status, body, headers

    def get(self, path: str):
        status, raw, headers = self.request("GET", path)
        return status, _maybe_json(raw), headers

    def post(self, path: str, body=None):
        status, raw, headers = self.request("POST", path, body if body is not None else {})
        return status, _maybe_json(raw), headers

    def wait_for_job(self, job_id: str, timeout: float = 20.0):
        deadline = time.time() + timeout
        phases_seen = []
        while time.time() < deadline:
            status, job, _ = self.get(f"/api/chat/jobs/{job_id}")
            phases_seen.append(job["phase"])
            if job["phase"] in ("done", "error"):
                job["_phases_seen"] = phases_seen
                return job
            time.sleep(0.03)
        raise TimeoutError(f"job {job_id} did not finish within {timeout}s (saw {phases_seen})")

    def send_chat_message(self, conversation_id: str, text: str, config: dict | None = None):
        status, body, _ = self.post(
            "/api/chat/message",
            {"conversation_id": conversation_id, "text": text, "config": config or {}},
        )
        assert status == 202, body
        return self.wait_for_job(body["job_id"])


def _maybe_json(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw
