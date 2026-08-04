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

from ..ollama_install import (
    AUDIT_PASSWORD_ENV_VAR,
    audit_password_conflict_against,
    read_env_var,
)

# Separação de acesso da tela de auditoria: o que este módulo entrega é uma
# **barreira de papel**, não segurança, e a diferença está escrita para o
# auditor na tela, no README e no AUDIT_GUIDE — versão longa em `997a6fe^`.
ENV_PASSWORD_VAR = AUDIT_PASSWORD_ENV_VAR

# O nome do cookie de sessão, definido uma vez porque dois módulos precisam do
# MESMO: renomear um lado não quebraria nada alto, só faria toda requisição
# depois do login responder 401 — versão longa em `997a6fe^`.
AUDIT_SESSION_COOKIE = "ea_audit_session"

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
    """Levantada no arranque para fonte de senha que existe e é inutilizável,
    ou para variável remanescente que contradiz a senha em vigor: falhar alto
    bate subir em silêncio um servidor cuja tela não existe — versão longa em `997a6fe^`."""


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
    """Devolve (senha, descrição da origem, avisos), com a descrição e os avisos
    seguros de imprimir e a senha nunca — e são **duas** fontes,
    `--audit-password-file` e o `.env`, com a variável de ambiente fora:
    versão longa em `997a6fe^`.
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

    # An empty or absent key in .env means "not configured", not an error --
    # unlike an empty --audit-password-file, which is a startup failure
    # because the operator explicitly pointed at it. Nobody points at .env;
    # it is just where the installer happens to keep things.
    dotenv_password = read_env_var(root, ENV_PASSWORD_VAR)

    # Read once, above, and handed to the tripwire. Letting the check read
    # .env for itself would be two reads of a file the installer rewrites,
    # and they could disagree. There is no flag on this path -- the branch
    # above already returned -- so the carve-out cannot fire here; it is
    # passed anyway, because the rule and its exception belong in one place.
    conflict = audit_password_conflict_against(root, dotenv_password, env, password_file)
    if conflict:
        raise AuditPasswordError(conflict)

    if dotenv_password:
        return dotenv_password, f".env ({ENV_PASSWORD_VAR})", warnings

    return None, None, warnings


def dotenv_password_present(root: Optional[Path] = None) -> bool:
    """Se o `.env` carrega senha, independentemente de quem venceu, usado só
    para dizer ao operador que a flag o superou; devolve booleano e nunca o
    valor, porque quem chama imprime.
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
    """Verificação de senha mais a tabela de sessões em memória do realm de
    auditoria — reiniciar o servidor invalida todas, e isso é comportamento
    documentado: persistir token seria gravar credencial ao lado da trilha.
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
