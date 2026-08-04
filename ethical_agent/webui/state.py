from __future__ import annotations

import sys
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

from ethical_agent import AuditLogger
from ethical_agent.agent import AgentResult
from ethical_agent.audit import audit_first_write_notice, audit_write_failure_message

# Only jobs that have finished (phase "done"/"error") are ever candidates for
# GC, and only once they've sat unread for this long -- a job still in
# "generating"/"verifying" is never swept, no matter its age, because we
# impose no timeout on the LLM call it's waiting on (a local CPU model can
# legitimately take several minutes).
JOB_TERMINAL_GC_SECONDS = 300


class _WebAuditLogger(AuditLogger):
    """`AuditLogger` que falha macio, e que aqui também **serializa** escritas
    porque `.log()` pode ser chamado de mais de uma thread de requisição:
    versão longa em `997a6fe^`.
    """

    def __init__(self, path, lock: threading.Lock):
        self._lock = lock
        self._notice_shown = False
        self.warning: Optional[str] = None
        self.notice: Optional[str] = None
        super().__init__(path)

    def log(self, record: dict) -> Optional[str]:
        with self._lock:
            try:
                event_id = super().log(record)
            except Exception as exc:  # noqa: BLE001 -- mirrors the CLI logger's own broad catch
                # Same sentence as the CLI (audit.py owns the wording), but
                # kept on the instance as well: audit_notice_lines() hands it
                # to the browser, which has no stderr the reader can see.
                self.warning = audit_write_failure_message(self.path, exc)
                print(self.warning, file=sys.stderr)
                return None
            if not self._notice_shown:
                self._notice_shown = True
                self.notice = audit_first_write_notice(self.path)
                print(self.notice, file=sys.stderr)
            return event_id


class ConversationStore:
    """Histórico por conversa, só na memória do processo e nunca reconstruído da
    trilha, com um lock por conversa segurado pelo chamador durante o turno
    inteiro: versão longa em `997a6fe^`.
    """

    def __init__(self):
        self._dict_lock = threading.Lock()
        self._conversations: Dict[str, Tuple[List[AgentResult], threading.Lock]] = {}

    def create(self) -> str:
        conversation_id = uuid.uuid4().hex
        with self._dict_lock:
            self._conversations[conversation_id] = ([], threading.Lock())
        return conversation_id

    def exists(self, conversation_id: str) -> bool:
        with self._dict_lock:
            return conversation_id in self._conversations

    def turn_count(self, conversation_id: str) -> Optional[int]:
        entry = self._entry(conversation_id)
        if entry is None:
            return None
        history, conv_lock = entry
        with conv_lock:
            return len(history)

    def conversation_lock(self, conversation_id: str) -> Optional[threading.Lock]:
        entry = self._entry(conversation_id)
        return entry[1] if entry is not None else None

    def history_list(self, conversation_id: str) -> Optional[List[AgentResult]]:
        """Returns the *live* list object, not a copy. Caller must hold the
        lock from conversation_lock() for the duration of any read/append."""
        entry = self._entry(conversation_id)
        return entry[0] if entry is not None else None

    def _entry(self, conversation_id: str):
        with self._dict_lock:
            return self._conversations.get(conversation_id)


class JobRegistry:
    """Tracks in-flight/finished chat turns so the frontend can poll a
    lightweight status instead of blocking one HTTP request for the whole
    duration of a (possibly slow) LLM call. See webui/progress.py for how a
    job's phase actually advances from "generating" to "verifying".
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: Dict[str, dict] = {}

    def create(self) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._sweep_locked(now)
            self._jobs[job_id] = {
                "phase": "generating",
                "result": None,
                "error": None,
                "created_at": now,
                "finished_at": None,
            }
        return job_id

    def _sweep_locked(self, now: float) -> None:
        stale = [
            job_id
            for job_id, job in self._jobs.items()
            if job["phase"] in ("done", "error")
            and job["finished_at"] is not None
            and now - job["finished_at"] > JOB_TERMINAL_GC_SECONDS
        ]
        for job_id in stale:
            del self._jobs[job_id]

    def set_phase(self, job_id: str, phase: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["phase"] = phase

    def set_done(self, job_id: str, result: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["phase"] = "done"
                job["result"] = result
                job["finished_at"] = time.time()

    def set_error(self, job_id: str, error: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["phase"] = "error"
                job["error"] = error
                job["finished_at"] = time.time()

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None


class ServerState:
    """Tudo que o servidor guarda pela vida do processo, construído uma vez em
    `make_server()`; `initial_config` semeia o painel do frontend e é servido
    verbatim e sem autenticação por `handlers_choices` — versão longa em `997a6fe^`.
    """

    def __init__(
        self,
        initial_config: dict,
        audit_auth=None,
        auditor_logger=None,
        change_request_logger=None,
    ):
        from .auth import AuditAuth  # local import: keeps state.py importable standalone

        self.initial_config = initial_config
        self.conversations = ConversationStore()
        self.jobs = JobRegistry()
        self.audit_lock = threading.Lock()
        # A lock of its own, never audit_lock: the auditor's trail and the
        # agent's trail are different files with different writers, and
        # sharing a lock would make one wait on the other for no reason.
        self.auditor_lock = threading.Lock()
        self.audit_auth = audit_auth if audit_auth is not None else AuditAuth(None)
        self.auditor_logger = auditor_logger
        self.change_request_logger = change_request_logger

    def realm_enabled(self, realm: str) -> bool:
        """Whether a named group of routes exists at all right now. Passed to
        routing.match(), which skips a disabled realm's routes before it
        decides whether the path is known -- see the comment there for why
        that ordering carries the whole access separation."""
        if realm == "audit":
            return self.audit_auth.enabled
        return True
