from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

from .. import senha_auditoria
from ..ollama_install import (
    AUDIT_PASSWORD_ENV_VAR,
    audit_password_conflict_against,
    migrar_senha_do_env,
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
) -> Tuple[Optional[object], Optional[str], List[str]]:
    """Devolve (credencial, descrição da origem, avisos), com a descrição e os
    avisos seguros de imprimir e a senha nunca — e são **duas** fontes,
    `--audit-password-file` e o `.audit-password`, com a variável de ambiente
    fora: versão longa em `997a6fe^`.

    A credencial é um `RegistroSenha` (hash + sal, do disco) ou, no caminho da
    flag, a senha em claro que o operador declarou naquela invocação. Quem
    recebe é `AuditAuth`, que trata as duas — é lá que "o que a fonte deu" vira
    verificador, e o único lugar onde isso acontece.
    """
    env = os.environ if env is None else env
    root = REPO_ROOT if root is None else root
    warnings: List[str] = []

    # MIGRAÇÃO, E ELA VEM ANTES DE TUDO -- inclusive do ramo da flag.
    #
    # Antes da checagem de conflito porque essa é a interação que quebraria
    # calado: a leva anterior fez o `serve` recusar quando uma variável
    # remanescente discorda da senha em vigor, e numa máquina não migrada o
    # registro ainda não existe. A checagem rodando primeiro chamaria a variável
    # de órfã e recusaria a subir uma máquina perfeitamente configurada.
    #
    # Antes do ramo da flag porque a promessa desta leva é que a senha em claro
    # não exista mais em arquivo nenhum. Migrar só no caminho sem flag deixaria
    # a linha do `.env` sobreviver indefinidamente em quem sempre usa a flag.
    # Migrar aqui não muda qual senha vale nesta invocação -- a flag continua
    # ganhando logo abaixo --, só tira do disco a que já não é fonte.
    migrado = migrar_senha_do_env(root)
    if migrado:
        # Dito em voz alta: migração silenciosa que apaga linha de arquivo de
        # configuração é o tipo de coisa que assusta quando descoberta depois.
        # Nomeia o arquivo e a receita, nunca o valor.
        warnings.append(
            f"[senha] migrada para hash em {migrado.name} "
            f"({senha_auditoria.RECEITA_SENHA}); linha removida do .env"
        )

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

    # Um arquivo ausente é "não configurada", não erro -- ao contrário de um
    # --audit-password-file vazio, que é falha de arranque porque o operador
    # apontou explicitamente para ele. Um arquivo que existe e não é legível é
    # erro: alguém quis configurar e o que está no disco não serve.
    try:
        registro = senha_auditoria.ler(root)
    except senha_auditoria.SenhaInvalida as exc:
        raise AuditPasswordError(
            f"{senha_auditoria.caminho_do_registro(root)} existe e não é um "
            f"registro de senha legível: {exc}\n"
            "Apague o arquivo e defina a senha de novo rodando o instalador "
            "(`python wizard_gui.py`)."
        ) from exc

    # Lido uma vez, acima, e entregue ao arame de tropeço. Deixar a checagem ler
    # o arquivo por conta própria seriam duas leituras de algo que o instalador
    # reescreve, e elas poderiam discordar.
    conflict = audit_password_conflict_against(root, registro, env, password_file)
    if conflict:
        raise AuditPasswordError(conflict)

    if registro is not None:
        return registro, f"{senha_auditoria.NOME_ARQUIVO} ({registro.receita})", warnings

    return None, None, warnings


def dotenv_password_present(root: Optional[Path] = None) -> bool:
    """Se há senha configurada no disco, independentemente de quem venceu, usado
    só para dizer ao operador que a flag o superou; devolve booleano e nunca o
    valor, porque quem chama imprime.

    Lê o registro hasheado, não mais o `.env` — o nome sobreviveu à mudança de
    lugar porque a pergunta é a mesma: "a fonte que a flag passou por cima tem
    alguma coisa?".
    """
    raiz = REPO_ROOT if root is None else root
    try:
        return senha_auditoria.ler(raiz) is not None
    except senha_auditoria.SenhaInvalida:
        # Existe e está corrompido: para esta pergunta, existe.
        return True


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


class AuditAuth:
    """Verificação de senha mais a tabela de sessões em memória do realm de
    auditoria — reiniciar o servidor invalida todas, e isso é comportamento
    documentado: persistir token seria gravar credencial ao lado da trilha.
    """

    def __init__(self, password=None):
        """`password` é a credencial que a fonte entregou, e são duas formas:

        - um `RegistroSenha` lido do `.audit-password` — sal e hash, o caminho
          normal desde a leva do hash;
        - uma senha em claro, do `--audit-password-file`, que é declaração
          explícita do operador para *aquela* invocação. Ela é hasheada com sal
          fresco aqui, uma vez (≈197 ms), para que exista **um** caminho de
          verificação e não dois.

        Este é o único lugar do projeto onde "o que a fonte deu" vira
        verificador, que é por que a união de tipos mora aqui e não espalhada
        pelos chamadores.

        Havia aqui um `_digest` com `sha256` cru, e um comentário sustentando
        que "uma KDF com sal implicaria um modelo de ameaça de armazenamento que
        não existe". **Passou a existir.** Antes desta leva a senha ficava em
        claro no `.env` e o digest era só uma comparação em memória; agora a
        senha é guardada, e o que se guarda tem de resistir a quem lê o disco. O
        que continua não valendo é o outro lado: nada disto protege contra quem
        **substitui** o arquivo, e o `AUDIT_GUIDE` diz isso com estas palavras.
        """
        self._lock = threading.Lock()
        if password is None or password == "":
            self._registro = None
        elif isinstance(password, senha_auditoria.RegistroSenha):
            self._registro = password
        else:
            self._registro = senha_auditoria.registrar_senha(password)
        self._sessions: dict = {}
        self._failures: List[float] = []
        self._locked_until = 0.0

    @property
    def enabled(self) -> bool:
        return self._registro is not None

    def verify(self, candidate: str) -> bool:
        # `senha_auditoria.verificar` recomputa o scrypt com o sal e os
        # parâmetros do próprio registro e compara com `hmac.compare_digest`,
        # nunca `==` -- `==` sobre digest vaza por tempo de resposta.
        if self._registro is None:
            return False
        return senha_auditoria.verificar(self._registro, candidate or "")

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
