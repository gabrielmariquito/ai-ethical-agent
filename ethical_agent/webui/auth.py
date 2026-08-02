from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

from ..ollama_install import read_env_var

# Access separation for the audit screen.
#
# READ THIS BEFORE CHANGING ANYTHING HERE. What this module provides is a
# *role barrier*, not security, and the difference is documented for the
# auditor on screen and in README.md / AUDIT_GUIDE.pt-BR.md in those words.
# The server is http://127.0.0.1 with no TLS and no authentication
# infrastructure: the password and the session token cross the loopback in
# clear text, the token lives only in this process's memory, and anyone with
# access to the machine can read logs/audit.jsonl directly without ever
# passing through the screen. What the password buys is that the audit trail
# does not open by accident, by curiosity, or because somebody typed /audit
# into the address bar -- which, in a study with two separated roles (the
# employee who chats, the auditor who reviews afterwards), is precisely the
# property that has to hold. Do not grow this into something that invites
# being trusted with more than that.
#
# The barrier is structural rather than visual: with no password configured,
# routing.match() never even considers the audit routes, so they 404 exactly
# like a path nobody registered (see routing.match's own comment). Hiding a
# link would not have been enough -- the local server is reachable from the
# URL bar and from devtools.

ENV_PASSWORD_VAR = "ETHICAL_AGENT_AUDIT_PASSWORD"

# .../ai-ethical-agent -- this file is at webui/auth.py, two packages deep.
# Where the project's .env lives, and where a password file inside the repo
# would be at risk of being committed. Only points at the real project root
# on an editable install, which is what wizard_gui.py does (`pip install -e`);
# the same assumption read_env_model already makes in __main__.py.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Absolute lifetime of an audit session. No idle timeout: an auditor reading
# one difficult record for forty minutes is doing the task, not idling, and
# being logged out mid-read would corrupt the dwell-time measurement that is
# half the point of the screen.
SESSION_TTL_SECONDS = 12 * 3600

# Failed-login handling. Deliberately no artificial sleep on a wrong password:
# this server is threaded, so sleeping would let anyone trivially exhaust the
# thread pool, and it would buy nothing against someone who already has a
# shell on the machine (and could just read the JSONL file).
MAX_FAILED_ATTEMPTS = 5
FAILURE_WINDOW_SECONDS = 300
LOCKOUT_SECONDS = 60


class AuditPasswordError(Exception):
    """Raised at startup for a password source that exists but is unusable
    (e.g. an empty file). Failing loudly beats silently starting a server
    whose audit screen quietly does not exist -- the operator asked for it."""


@dataclass
class AuditSession:
    session_id: str
    token: str
    created_at: float
    last_seen: float


def load_audit_password(
    password_file: Optional[str],
    env: Optional[Mapping[str, str]] = None,
    root: Optional[Path] = None,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Returns (password, source_description, warnings).

    The description and the warnings are safe to print; the password itself
    never is. Precedence, highest first:

      1. --audit-password-file ARQUIVO
      2. $ETHICAL_AGENT_AUDIT_PASSWORD
      3. ETHICAL_AGENT_AUDIT_PASSWORD= in <root>/.env   (written by wizard_gui)
      4. nothing -- the audit screen does not exist

    Environment above .env is the python-dotenv convention and matches how
    OLLAMA_API_KEY already resolves here (llm.py calls load_dotenv(), which
    does not override an existing variable, then reads os.environ): a real
    variable is the per-invocation override, .env is the persistent setting.
    Two different precedences for two keys of the same .env would be worse
    than either order.

    That does mean a stale `export` in someone's shell profile can quietly
    outrank the password their installer wrote. The startup banner is what
    covers it -- cmd_serve names the winning source, and says so explicitly
    when the variable beat a password that .env also had.

    There is deliberately no --audit-password VALUE flag: an argument value
    lands in the process list and in shell history, which is a worse place
    for a secret than any of the three sources supported here.
    """
    env = os.environ if env is None else env
    root = REPO_ROOT if root is None else root
    warnings: List[str] = []

    if password_file:
        path = Path(password_file)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AuditPasswordError(
                f"could not read --audit-password-file {password_file}: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc
        password = raw.strip()
        if not password:
            raise AuditPasswordError(
                f"--audit-password-file {password_file} is empty; either put a "
                "password in it or omit the flag to run without the audit screen"
            )
        warnings.extend(_password_file_warnings(path))
        return password, f"--audit-password-file {path}", warnings

    env_password = (env.get(ENV_PASSWORD_VAR) or "").strip()
    if env_password:
        return env_password, f"${ENV_PASSWORD_VAR}", warnings

    # An empty or absent key in .env means "not configured", not an error --
    # unlike an empty --audit-password-file, which is a startup failure
    # because the operator explicitly pointed at it. Nobody points at .env;
    # it is just where the installer happens to keep things.
    dotenv_password = read_env_var(root, ENV_PASSWORD_VAR)
    if dotenv_password:
        return dotenv_password, f".env ({ENV_PASSWORD_VAR})", warnings

    return None, None, warnings


def dotenv_password_present(root: Optional[Path] = None) -> bool:
    """Whether .env carries a password, regardless of who won.

    Only used to tell the operator that a higher-precedence source overrode
    it. Returns a boolean and never the value, because the caller prints.
    """
    return read_env_var(REPO_ROOT if root is None else root, ENV_PASSWORD_VAR) is not None


def _password_file_warnings(path: Path) -> List[str]:
    warnings: List[str] = []
    try:
        resolved = path.resolve()
    except OSError:
        return warnings

    # A password file living inside the repository is one `git add -A` away
    # from being committed, which is the exact failure the "never in a
    # versioned file" requirement is about. (.env is the exception: it is
    # inside the repo but listed in .gitignore.)
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        warnings.append(
            f"[audit] warning: the password file {resolved} is inside the "
            "repository, so it can be committed by accident; consider "
            "~/.ethical-agent-audit-password instead"
        )

    if os.name != "nt":
        try:
            mode = resolved.stat().st_mode
        except OSError:
            return warnings
        if mode & 0o077:
            warnings.append(
                f"[audit] warning: {resolved} is readable by other users "
                f"(mode {mode & 0o777:o}); consider chmod 600"
            )
    return warnings


def _digest(value: str) -> bytes:
    # hmac.compare_digest raises TypeError on non-ASCII str, and a pt-BR
    # password with an accent in it is entirely likely -- so both sides are
    # hashed to bytes first and compared as bytes. This is an equality check
    # against a secret that is already sitting in memory in the clear; a
    # salted KDF here would imply a storage threat model that does not exist.
    return hashlib.sha256(value.encode("utf-8")).digest()


class AuditAuth:
    """Password check plus the in-memory session table for the audit realm.

    Sessions live only here, so restarting the server invalidates every one
    of them: the next audit request answers 401 and the screen drops back to
    the login form. That is documented behaviour, not a bug -- persisting
    session tokens to disk would mean writing a credential next to the very
    trail this screen exists to read.
    """

    def __init__(self, password: Optional[str] = None):
        self._lock = threading.Lock()
        self._password_digest = _digest(password) if password else None
        self._sessions: dict = {}
        self._failures: List[float] = []
        self._locked_until = 0.0

    @property
    def enabled(self) -> bool:
        return self._password_digest is not None

    def verify(self, candidate: str) -> bool:
        if self._password_digest is None:
            return False
        return hmac.compare_digest(self._password_digest, _digest(candidate or ""))

    # -- lockout ---------------------------------------------------------

    def lockout_remaining(self, now: Optional[float] = None) -> float:
        now = time.time() if now is None else now
        with self._lock:
            return max(0.0, self._locked_until - now)

    def register_failure(self, now: Optional[float] = None) -> float:
        """Records a wrong password and returns the seconds of lockout now in
        effect (0.0 if still under the threshold)."""
        now = time.time() if now is None else now
        with self._lock:
            self._failures = [t for t in self._failures if now - t < FAILURE_WINDOW_SECONDS]
            self._failures.append(now)
            if len(self._failures) >= MAX_FAILED_ATTEMPTS:
                self._locked_until = now + LOCKOUT_SECONDS
                self._failures = []
            return max(0.0, self._locked_until - now)

    def register_success(self, now: Optional[float] = None) -> None:
        with self._lock:
            self._failures = []
            self._locked_until = 0.0

    # -- sessions --------------------------------------------------------

    def start_session(self, now: Optional[float] = None) -> AuditSession:
        now = time.time() if now is None else now
        session = AuditSession(
            # Two distinct identifiers on purpose. The token authenticates
            # and is never written anywhere; the session_id is what appears
            # in logs/auditor_sessions.jsonl to tie one auditor's events
            # together. Logging the token would put a live credential in a
            # file whose whole purpose is to be read and analysed later.
            session_id=uuid.uuid4().hex,
            token=secrets.token_urlsafe(32),
            created_at=now,
            last_seen=now,
        )
        with self._lock:
            self._sweep_locked(now)
            self._sessions[session.token] = session
        return session

    def resolve(self, token: Optional[str], now: Optional[float] = None) -> Optional[AuditSession]:
        if not token or not self.enabled:
            return None
        now = time.time() if now is None else now
        with self._lock:
            self._sweep_locked(now)
            session = self._sessions.get(token)
            if session is None:
                return None
            session.last_seen = now
            return session

    def revoke(self, token: Optional[str]) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def _sweep_locked(self, now: float) -> None:
        expired = [
            token
            for token, session in self._sessions.items()
            if now - session.created_at > SESSION_TTL_SECONDS
        ]
        for token in expired:
            del self._sessions[token]
