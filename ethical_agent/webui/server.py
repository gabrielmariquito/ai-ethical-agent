from __future__ import annotations

import errno
import os
import socket
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Optional

# Importing these registers their @routing.route(...) handlers as a side
# effect. Explicit, fixed list (not plugin discovery) so it stays grep-able.
from . import (  # noqa: F401
    handlers_audit,
    handlers_browse,
    handlers_chat,
    handlers_check,
    handlers_choices,
    handlers_demo,
    handlers_eval,
    handlers_history,
)
from .auditor_log import (
    DEFAULT_AUDITOR_SESSION_LOG,
    DEFAULT_CHANGE_REQUESTS_LOG,
    AuditorSessionLogger,
    ChangeRequestLogger,
)
from .auth import AuditAuth
from .httphandler import make_handler
from .state import ServerState


class _ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """`ThreadingHTTPServer` que recusa uma porta em que outro já está: no
    Windows `SO_REUSEADDR` deixa um segundo socket ligar num endereço em uso
    ativo, e o navegador continuava falando com o processo antigo: `REGISTRO`, "Texto movido do código".
    """

    # POSIX keeps the inherited True; there the flag is not the problem and
    # dropping it would bring back "Address already in use" on restart.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class PortInUseError(Exception):
    """The port is taken. Raised instead of letting a bare WinError 10048 /
    EADDRINUSE traceback reach someone who just typed `serve`."""


class AuditLogCollisionError(Exception):
    """The auditor's log and the agent's audit trail resolved to the same
    file. Refusing to start beats writing behavioural telemetry into the
    record of what the agent decided: that trail is the object of study, and
    contaminating it is not something a later grep can undo."""


def make_server(
    port: int,
    initial_config: dict,
    audit_password: Optional[str] = None,
    auditor_session_log: Optional[str] = None,
    change_requests_log: Optional[str] = None,
) -> ThreadingHTTPServer:
    """Liga só em 127.0.0.1, sem flag para mudar; `audit_password` habilita o
    realm de auditoria e é passado como argumento, nunca por `initial_config`:
    `REGISTRO`, "Texto movido do código".
    """
    auditor_session_log = auditor_session_log or DEFAULT_AUDITOR_SESSION_LOG
    change_requests_log = change_requests_log or DEFAULT_CHANGE_REQUESTS_LOG
    _refuse_collision(initial_config.get("audit_log"), auditor_session_log, "auditor session log")
    _refuse_collision(initial_config.get("audit_log"), change_requests_log, "change requests log")

    audit_auth = AuditAuth(audit_password)
    state = ServerState(initial_config, audit_auth=audit_auth)
    if audit_auth.enabled:
        # Only created when the screen exists, so a plain chat server does
        # not touch (or create) the auditor's files at all.
        state.auditor_logger = AuditorSessionLogger(auditor_session_log, state.auditor_lock)
        state.change_request_logger = ChangeRequestLogger(change_requests_log, state.auditor_lock)

    handler_cls = make_handler(state)
    try:
        server = _ExclusiveThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    except OSError as exc:
        # errno.EADDRINUSE is 48 on macOS and 98 on Linux; on Windows the
        # winerror is 10048 and errno surfaces as EADDRINUSE too. Anything
        # else -- a privileged port (EACCES), a bad interface -- is a
        # different story and keeps its own message.
        if exc.errno != errno.EADDRINUSE:
            raise
        raise PortInUseError(str(port)) from exc
    server.daemon_threads = True
    # Exposed for tests that need to reach into ServerState (job registry GC,
    # conversation store) without a second, parallel way to construct it.
    # Not used by any handler -- they all receive `state` as an argument.
    server.state = state
    return server


def _refuse_collision(audit_log: Optional[str], other: str, label: str) -> None:
    if not audit_log:
        return
    try:
        same = Path(audit_log).resolve() == Path(other).resolve()
    except OSError:
        same = str(audit_log) == str(other)
    if same:
        raise AuditLogCollisionError(
            f"the {label} ({other}) is the same file as the agent's audit trail "
            f"({audit_log}); they must be separate files -- the trail is the "
            "object of study and mixing the auditor's own behaviour into it "
            "would corrupt it"
        )
