"""Pure helpers for the uninstaller -- the counterpart to ollama_install.py.

wizard_gui.py creates a venv, installs the package, optionally installs the
Ollama server and pulls a multi-gigabyte model, and writes .env. Nothing
undid any of that. This module works out what is there, how big it is, what
is currently running, and removes what it is told to -- as plain functions
with injectable subprocess/urlopen hooks, so it is testable without tkinter,
a real venv, a real Ollama or network access. uninstall.py (CLI) and
uninstall_gui.py (Tk) are thin shells over it.

The rule the whole module is built around: *the uninstaller must not be more
confident than the installer was.* It deletes without asking only what
nothing else could plausibly own -- the venv and build artifacts -- and
everything else is an opt-in that defaults to off. Two consequences worth
naming, because they look like omissions:

  * `dist/` and `*.spec` are gitignored build output, but the wizard never
    creates them, so they are deliberately NOT removed. A `.spec` file in
    particular is usually hand-written. Do not "fix" this.
  * The Ollama server is never uninstalled by a guessed silent command. The
    installer verifies an Authenticode signature before executing the
    installer it downloaded (wizard_gui.py); running some `unins*.exe` found
    by wildcard without the same check would leave the uninstaller with a
    *worse* security posture than the installer, which is precisely what the
    rule forbids. So: verify, or print the manual steps.

Lives inside ethical_agent/ (like ollama_install.py) so it stays importable
as `ethical_agent.uninstall` regardless of the current working directory.
Stdlib only, plus ollama_install -- it has to run on the system Python with
nothing installed, since the venv it removes is the thing that would have
held the dependencies.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import (
    AbstractSet,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from .install_record import InstallRecord, read_record, record_path
from .ollama_install import (
    DEFAULT_OLLAMA_HOST,
    find_ollama_exe,
    read_env_model_optional,
    verify_windows_signature,
    wait_for_server,
)

PROJECT_NAME = "ai-ethical-agent"

# Pruned from every recursive walk. `.venv` above all: a recursive
# __pycache__ or *.egg-info scan that descends into site-packages finds tens
# of thousands of directories belonging to third-party packages, and would
# happily report them as this project's build artifacts.
PRUNED_DIRS: AbstractSet[str] = frozenset({".venv", ".git", "build", "dist", "node_modules"})

AUDIT_LOG_GLOB = "logs/*.jsonl"
VENV_DIRNAME = ".venv"

# Removal statuses. English tokens (stable for tests); the pt-BR phrasing
# lives in RemovalResult.detail.
REMOVED = "removed"
MOVED = "moved"
WOULD_REMOVE = "would_remove"
SKIPPED = "skipped"
FAILED = "failed"
MANUAL = "manual"


@dataclass(frozen=True)
class Candidate:
    key: str
    path: Optional[Path]
    kind: str  # "dir" | "file" | "external"
    size_bytes: Optional[int] = None
    label: str = ""
    detail: str = ""
    optin_flag: Optional[str] = None  # None => removed without asking


@dataclass(frozen=True)
class LogsSummary:
    files: Tuple[Path, ...]
    record_count: int
    total_bytes: int
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None


@dataclass(frozen=True)
class RunningServices:
    web_ui: bool = False
    ollama: bool = False
    web_port: int = 0


@dataclass(frozen=True)
class Choices:
    remove_logs: bool = False
    move_logs_to: Optional[Path] = None
    remove_model: bool = False
    remove_env: bool = False
    remove_ollama: bool = False


@dataclass(frozen=True)
class RemovalResult:
    key: str
    target: str
    status: str
    detail: str = ""


@dataclass(frozen=True)
class UninstallPlan:
    root: Path
    mandatory: Tuple[Candidate, ...] = ()
    optional: Tuple[Candidate, ...] = ()
    logs: Optional[LogsSummary] = None
    model: Optional[str] = None
    ollama_exe: Optional[Path] = None
    record: Optional[InstallRecord] = None
    running: RunningServices = field(default_factory=RunningServices)
    notes: Tuple[str, ...] = ()

    def candidate(self, key: str) -> Optional[Candidate]:
        for cand in tuple(self.mandatory) + tuple(self.optional):
            if cand.key == key:
                return cand
        return None

    @property
    def has_anything_to_remove(self) -> bool:
        return bool(self.mandatory or self.optional)


# -- guards ----------------------------------------------------------------


def looks_like_project_root(root: Path) -> bool:
    """Cheap belt-and-braces: is this actually the ai-ethical-agent repo?

    The shells derive the root from their own __file__, so this only ever
    catches someone copying uninstall.py somewhere else -- but that is
    exactly the case where being wrong deletes a stranger's directory.
    """
    try:
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    return f'name = "{PROJECT_NAME}"' in text or f"name = '{PROJECT_NAME}'" in text


def _is_inside(path: str, parent: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(parent.resolve())
    except (OSError, ValueError):
        return False


def running_inside_venv(
    root: Path,
    prefix: Optional[str] = None,
    executable: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Returns a pt-BR reason to refuse, or None when it is safe to proceed.

    On Windows a running executable is locked by the OS: deleting
    `.venv\\Scripts\\python.exe` while it *is* the running interpreter cannot
    succeed, so `ethical-agent uninstall` as a console script inside the venv
    would not merely fail -- it would leave a half-deleted venv, which is
    worse than not offering it. Hence both shells run under the system
    Python, and this refuses when they don't.

    A merely *activated* venv (VIRTUAL_ENV set, but the running interpreter
    is elsewhere) locks nothing -- that is a stale PATH, so it warns rather
    than refusing.
    """
    prefix = sys.prefix if prefix is None else prefix
    executable = sys.executable if executable is None else executable
    env = os.environ if env is None else env

    venv_dir = root / VENV_DIRNAME
    if executable and _is_inside(executable, venv_dir):
        return (
            f"este desinstalador está rodando com o Python do próprio venv "
            f"({executable}) -- que é justamente o que ele vai apagar."
        )
    if prefix and _is_inside(prefix, venv_dir):
        return (
            f"este desinstalador está rodando dentro do venv do projeto "
            f"({prefix}) -- que é justamente o que ele vai apagar."
        )
    return None


def venv_activated_warning(
    root: Path, env: Optional[Mapping[str, str]] = None
) -> Optional[str]:
    """The softer sibling of running_inside_venv: activated but not running."""
    env = os.environ if env is None else env
    virtual_env = env.get("VIRTUAL_ENV")
    if virtual_env and _is_inside(virtual_env, root / VENV_DIRNAME):
        return (
            "o venv do projeto está ativado nesta sessão -- nada fica travado "
            "por isso, mas rode `deactivate` depois, ou o PATH continuará "
            "apontando para um diretório que deixou de existir."
        )
    return None


# -- sizes -----------------------------------------------------------------


def format_size(num_bytes: Optional[int]) -> str:
    """pt-BR size, decimal comma, matching estimate_model_size_text's style."""
    if num_bytes is None:
        return "tamanho desconhecido"
    if num_bytes < 1024:
        return f"{num_bytes} B"
    for unit, threshold in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if num_bytes >= threshold:
            value = num_bytes / threshold
            if unit == "KB":
                return f"{value:.0f} KB"
            return f"{value:.1f} {unit}".replace(".", ",")
    return f"{num_bytes} B"


def dir_size(path: Path) -> int:
    """Total bytes under `path`, skipping anything unreadable.

    A permission error on one entry must not make the whole preview fail --
    an approximate size is far more useful than a traceback.
    """
    try:
        if path.is_symlink():
            return 0
        if path.is_file():
            return path.stat().st_size
    except OSError:
        return 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in filenames:
            try:
                entry = Path(dirpath) / name
                if not entry.is_symlink():
                    total += entry.stat().st_size
            except OSError:
                continue
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
    return total


# -- discovery -------------------------------------------------------------


def iter_pycache_dirs(root: Path, pruned: AbstractSet[str] = PRUNED_DIRS) -> Iterator[Path]:
    """Yields every __pycache__ under `root`, pruning in place.

    The pruning has to happen by mutating `dirnames` during the walk, not by
    filtering results afterwards: post-filtering still pays the cost of
    walking all of .venv/Lib/site-packages.
    """
    for dirpath, dirnames, _filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in pruned]
        if "__pycache__" in dirnames:
            dirnames.remove("__pycache__")
            yield Path(dirpath) / "__pycache__"


def find_build_artifacts(root: Path) -> List[Path]:
    """build/, *.egg-info/, .pytest_cache/ and every __pycache__.

    *.egg-info is matched at the root only -- a recursive match would find
    the egg-info of every third-party package inside .venv.
    """
    found: List[Path] = []
    for name in ("build", ".pytest_cache"):
        path = root / name
        if path.exists():
            found.append(path)
    found.extend(sorted(p for p in root.glob("*.egg-info") if p.is_dir()))
    found.extend(sorted(iter_pycache_dirs(root)))
    return found


# -- audit trail -----------------------------------------------------------


def count_lines(path: Path, chunk_size: int = 1 << 16) -> int:
    """Counts records in a .jsonl without json.loads per line.

    Counting b"\\n" in chunks is CRLF-safe by construction (\\r\\n holds one
    \\n), which matters because AuditLogger opens the trail in text mode, so
    on Windows every record ends \\r\\n.
    """
    total = 0
    last = b""
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                total += chunk.count(b"\n")
                last = chunk[-1:]
    except OSError:
        return 0
    if last and last != b"\n":
        total += 1  # a file not ending in a newline still holds a final record
    return total


def first_nonblank_line(path: Path) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    return line
    except OSError:
        return None
    return None


def tail_lines(path: Path, count: int = 3, chunk_size: int = 1 << 16) -> List[str]:
    """Last `count` non-blank lines, read backwards from the end.

    More than one, because a run killed mid-write leaves a truncated final
    line -- the caller falls back to the one before it rather than reporting
    an unknown period.
    """
    data = b""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            pos = fh.tell()
            while pos > 0 and data.count(b"\n") <= count:
                step = min(chunk_size, pos)
                pos -= step
                fh.seek(pos)
                data = fh.read(step) + data
    except OSError:
        return []
    lines = [line.strip() for line in data.decode("utf-8", "replace").splitlines()]
    return [line for line in lines if line][-count:]


def _timestamp_of(line: Optional[str]) -> Optional[str]:
    if not line:
        return None
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if isinstance(record, dict):
        stamp = record.get("timestamp")
        if isinstance(stamp, str) and stamp:
            return stamp
    return None


def audit_log_paths(root: Path) -> List[Path]:
    """Every logs/*.jsonl -- audit.jsonl plus the auditor-session and
    change-request trails, without hardcoding their names."""
    return sorted(root.glob(AUDIT_LOG_GLOB))


def summarize_logs(root: Path) -> Optional[LogsSummary]:
    paths = audit_log_paths(root)
    if not paths:
        return None
    stamps: List[str] = []
    total_bytes = 0
    records = 0
    for path in paths:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            pass
        records += count_lines(path)
        first = _timestamp_of(first_nonblank_line(path))
        if first:
            stamps.append(first)
        for line in reversed(tail_lines(path)):
            last = _timestamp_of(line)
            if last:
                stamps.append(last)
                break
    # ISO-8601 sorts lexicographically, so min/max over every file's ends is
    # the true period even when the files aren't named in date order.
    return LogsSummary(
        files=tuple(paths),
        record_count=records,
        total_bytes=total_bytes,
        first_timestamp=min(stamps) if stamps else None,
        last_timestamp=max(stamps) if stamps else None,
    )


def _date_only(timestamp: str) -> str:
    """DD/MM/AAAA a partir do ISO gravado na trilha.

    A hora, os microssegundos e o fuso continuam no arquivo -- só não cabem
    numa linha cuja única pergunta é "que período eu perco?".
    """
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        # Registro de outra origem, com carimbo em formato desconhecido: a
        # data ainda é mais legível que a linha inteira.
        return timestamp[:10]


def describe_logs(summary: LogsSummary) -> str:
    """What is lost -- the question must say this, not just "apagar logs?"."""
    plural = "s" if len(summary.files) != 1 else ""
    text = (
        f"{len(summary.files)} arquivo{plural}, {summary.record_count} registro"
        f"{'s' if summary.record_count != 1 else ''}, {format_size(summary.total_bytes)}"
    )
    if summary.first_timestamp and summary.last_timestamp:
        first = _date_only(summary.first_timestamp)
        last = _date_only(summary.last_timestamp)
        # Um dia só não é um intervalo.
        text += f"\nPeríodo: {first}" + (f" a {last}" if last != first else "")
    return text


# -- .env ------------------------------------------------------------------


def env_keys_present(root: Path) -> List[str]:
    """Key names in .env. Never the values -- OLLAMA_API_KEY is a secret and
    this string ends up on screen."""
    env_path = root / ".env"
    keys: List[str] = []
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return keys
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.append(line.split("=", 1)[0].strip())
    return keys


# -- Ollama ----------------------------------------------------------------


def list_models(
    ollama_exe: Path,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> Dict[str, str]:
    """Maps model tag -> human size, parsed from `ollama list`."""
    try:
        proc = run([str(ollama_exe), "list"], capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return {}
    if proc.returncode != 0 or not proc.stdout:
        return {}
    models: Dict[str, str] = {}
    for line in proc.stdout.splitlines()[1:]:  # skip the header row
        parts = line.split()
        if not parts:
            continue
        # NAME  ID  SIZE  MODIFIED, where SIZE is two tokens ("2.0 GB").
        # Cloud models print "-" for size, and blindly taking parts[2:4]
        # there would splice in the first token of MODIFIED ("- 3", from
        # "3 days ago").
        if len(parts) >= 4 and parts[2] != "-":
            models[parts[0]] = " ".join(parts[2:4])
        else:
            models[parts[0]] = ""
    return models


def lookup_model_size(models: Mapping[str, str], model: str) -> Optional[str]:
    """`ollama list` prints `llama3.2:3b`; .env may say `llama3.2:3b:latest`
    or vice versa -- normalise both sides before comparing."""
    from .ollama_install import _normalize_tag

    target = _normalize_tag(model.strip())
    for tag, size in models.items():
        if _normalize_tag(tag) == target:
            return size or None
    return None


def model_is_present(models: Mapping[str, str], model: str) -> bool:
    from .ollama_install import _normalize_tag

    target = _normalize_tag(model.strip())
    return any(_normalize_tag(tag) == target for tag in models)


def find_ollama_uninstaller(
    ollama_exe: Path,
    platform: Optional[str] = None,
    verify: Callable[[Path], bool] = verify_windows_signature,
) -> Optional[Path]:
    """The official uninstaller next to ollama.exe, only if its signature checks out.

    Fail-closed by design, and the manual path is expected to be the common
    one: uninstallers generated at install time are frequently unsigned. That
    is not a degradation -- executing an unverified binary found by wildcard
    would be a lower bar than the installer holds itself to.
    """
    platform = platform if platform is not None else sys.platform
    if platform != "win32":
        return None
    try:
        candidates = sorted(ollama_exe.parent.glob("unins*.exe"))
    except OSError:
        return None
    if len(candidates) != 1:
        return None
    return candidates[0] if verify(candidates[0]) else None


def ollama_manual_steps(
    platform: Optional[str] = None, ollama_exe: Optional[Path] = None
) -> List[str]:
    platform = platform if platform is not None else sys.platform
    steps: List[str] = []
    if platform == "win32":
        steps.append("Abra Configurações > Aplicativos > Aplicativos instalados.")
        steps.append('Procure por "Ollama" e clique em Desinstalar.')
    elif platform.startswith("linux"):
        steps.append("sudo systemctl stop ollama && sudo systemctl disable ollama")
        steps.append("sudo rm /etc/systemd/system/ollama.service")
        steps.append(
            f"sudo rm {ollama_exe if ollama_exe else '/usr/local/bin/ollama'}"
        )
        steps.append("sudo userdel ollama && sudo groupdel ollama   (se existirem)")
    else:
        steps.append("Arraste o Ollama.app de /Applications para o Lixo.")
    steps.append(
        "Os modelos baixados ficam em ~/.ollama -- esse diretório é "
        "compartilhado com qualquer outro projeto que use o Ollama e não é "
        "tocado por este desinstalador."
    )
    return steps


# -- running processes -----------------------------------------------------


def web_ui_running(
    port: int,
    timeout: float = 1.0,
    urlopen: Callable[..., object] = urllib.request.urlopen,
) -> bool:
    """Asks the web UI's own API, not a bare socket connect.

    "Something is listening on 8765" could be a stranger's process, and
    telling the user to kill a stranger's process is exactly the kind of
    confidence this uninstaller is not allowed to have. Only a 200 from
    /api/choices counts as ours.
    """
    url = f"http://127.0.0.1:{port}/api/choices"
    try:
        with urlopen(url, timeout=timeout) as resp:  # type: ignore[union-attr]
            return getattr(resp, "status", 200) == 200
    except Exception:  # noqa: BLE001
        return False


def detect_running(
    port: int,
    host: str = DEFAULT_OLLAMA_HOST,
    timeout: float = 1.0,
    urlopen: Callable[..., object] = urllib.request.urlopen,
) -> RunningServices:
    return RunningServices(
        web_ui=web_ui_running(port, timeout=timeout, urlopen=urlopen),
        ollama=wait_for_server(host, timeout=0.0, poll=0.1, urlopen=urlopen),
        web_port=port,
    )


def stop_hint(service: str, platform: Optional[str] = None, port: int = 0) -> List[str]:
    """How to stop it: COMMANDS ONLY, one per line, nothing else.

    Discovery commands at that -- we have no PID, so nothing here is ever run
    for the user. Every line must be something they can copy and paste
    verbatim, because the shells render this as a block and offer to copy it;
    a line of prose in here becomes a line that fails in their terminal.
    Guidance that is not a command belongs in stop_note().
    """
    platform = platform if platform is not None else sys.platform
    windows = platform == "win32"
    if service == "web_ui":
        if windows:
            return [
                f"netstat -ano | findstr :{port}",
                "taskkill /PID <pid> /F",
            ]
        return [f"lsof -ti :{port} | xargs kill"]
    if windows:
        return [
            "taskkill /IM ollama.exe /F",
            'taskkill /IM "ollama app.exe" /F',
        ]
    return ["sudo systemctl stop ollama", "pkill -f 'ollama serve'"]


def stop_note(service: str, platform: Optional[str] = None) -> Optional[str]:
    """The prose that goes NEXT TO stop_hint's commands, never inside them.

    These two lived in one list, prose as item 0, and every caller then glued
    the list together as if it were all commands: the GUI joined it with "; "
    and rendered "Saia do Ollama pelo ícone na bandeja do sistema, ou:;
    taskkill ..." -- the double punctuation being the seam showing. The POSIX
    branch had the same defect more quietly, shipping "ou: pkill -f 'ollama
    serve'" as if the "ou: " were part of the command.
    """
    platform = platform if platform is not None else sys.platform
    windows = platform == "win32"
    if service == "web_ui":
        if windows:
            # Sem isto, o <pid> literal da segunda linha é colado como está.
            return "O netstat mostra o PID; troque <pid> por ele na segunda linha."
        return None
    if windows:
        # Duas linhas porque são dois processos: o servidor e o app da bandeja.
        return "Saia do Ollama pelo ícone na bandeja do sistema, ou rode as duas linhas:"
    return "Qualquer uma das duas resolve."


# -- the plan --------------------------------------------------------------


def build_plan(
    root: Path,
    *,
    port: int,
    which: Callable[[str], Optional[str]] = shutil.which,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
    urlopen: Callable[..., object] = urllib.request.urlopen,
    platform: Optional[str] = None,
    probe: bool = True,
) -> UninstallPlan:
    """Everything the shells render. The single source of truth behind both
    the CLI's --dry-run and the GUI's summary page, so the two cannot drift."""
    platform = platform if platform is not None else sys.platform
    record = read_record(root)
    notes: List[str] = []

    mandatory: List[Candidate] = []
    venv_dir = root / VENV_DIRNAME
    if venv_dir.exists():
        mandatory.append(
            Candidate(
                key="venv",
                path=venv_dir,
                kind="dir",
                size_bytes=dir_size(venv_dir),
                label=f"{VENV_DIRNAME}/",
                detail="Ambiente virtual criado pelo instalador",
            )
        )
    for path in find_build_artifacts(root):
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        mandatory.append(
            Candidate(
                key="build",
                path=path,
                kind="dir",
                size_bytes=dir_size(path),
                label=f"{rel.as_posix()}/",
                detail="Artefato de build",
            )
        )
    if record_path(root).exists():
        mandatory.append(
            Candidate(
                key="record",
                path=record_path(root),
                kind="file",
                size_bytes=dir_size(record_path(root)),
                label=record_path(root).name,
                detail="Registro de instalação deste desinstalador",
            )
        )

    running = (
        detect_running(port, urlopen=urlopen)
        if probe
        else RunningServices(web_port=port)
    )

    optional: List[Candidate] = []

    logs = summarize_logs(root)
    if logs is not None:
        optional.append(
            Candidate(
                key="logs",
                path=root / "logs",
                kind="dir",
                size_bytes=logs.total_bytes,
                label="Trilha de auditoria (logs/*.jsonl)",
                detail=describe_logs(logs),
                optin_flag="--remove-logs",
            )
        )

    ollama_exe = find_ollama_exe(which=which) if probe else None
    if ollama_exe is not None:
        optional.append(
            Candidate(
                key="ollama",
                path=ollama_exe,
                kind="external",
                label=f"Servidor Ollama ({ollama_exe})",
                detail=_ollama_ownership_text(record),
                optin_flag="--remove-ollama",
            )
        )

    model = read_env_model_optional(root)
    if model and ollama_exe is not None and probe:
        models = list_models(ollama_exe, run=run)
        if model_is_present(models, model):
            size = lookup_model_size(models, model)
            optional.append(
                Candidate(
                    key="model",
                    path=None,
                    kind="external",
                    label=f"Modelo {model}" + (f" ({size})" if size else ""),
                    detail="Esta ação afeta qualquer outro projeto que use essa "
                    "instalação do Ollama.",
                    optin_flag="--remove-model",
                )
            )
        else:
            model = None
    elif model and not probe:
        optional.append(
            Candidate(
                key="model",
                path=None,
                kind="external",
                label=f"Modelo {model}",
                detail="Tamanho não consultado (--no-probe)",
                optin_flag="--remove-model",
            )
        )
    else:
        model = None

    env_path = root / ".env"
    if env_path.exists():
        keys = env_keys_present(root)
        # O que o arquivo É, e não mais a lista de chaves: "contém:
        # OLLAMA_MODEL" só significa alguma coisa para quem já sabe o que é
        # um .env, que é justamente quem não precisa da linha.
        detail = (
            "Guarda o que o instalador configurou: o modelo escolhido, a "
            "chave da Ollama Cloud e a senha da tela de auditoria."
        )
        if "OLLAMA_API_KEY" in keys:
            detail += (
                "\nOLLAMA_API_KEY é a chave da Ollama Cloud -- perdê-la por "
                "engano significa gerar outra em ollama.com/settings/keys."
            )
        # A consequência antes do detalhe: some a TELA, não só uma senha. Fica
        # condicionado à chave existir porque, sem ela, a tela já está
        # desligada e prometer que ela some seria falso.
        if "ETHICAL_AGENT_AUDIT_PASSWORD" in keys:
            # ...a menos que o ambiente exporte uma, caso em que ela assume e
            # a tela continua de pé. Prometer o desligamento nesse caso seria
            # tão falso quanto prometê-lo sem a chave.
            from .ollama_install import env_audit_password_present

            if env_audit_password_present():
                detail += (
                    "\nA senha da tela de auditoria (/audit) mora aqui, mas o "
                    "ambiente exporta ETHICAL_AGENT_AUDIT_PASSWORD -- remover "
                    "este arquivo passa a tela a usar essa, não a desativa."
                )
            else:
                detail += (
                    "\nRemover este arquivo desativa a tela de auditoria "
                    "(/audit): a senha dela mora aqui. É recuperável -- rode o "
                    "instalador de novo, ou defina a senha à mão."
                )
        optional.append(
            Candidate(
                key="env",
                path=env_path,
                kind="file",
                size_bytes=dir_size(env_path),
                label=".env",
                detail=detail,
                optin_flag="--remove-env",
            )
        )

    if record is not None and record.installer_download:
        leftover = Path(record.installer_download)
        if leftover.exists():
            notes.append(
                f"O instalador deixou {leftover} em %TEMP% "
                f"({format_size(dir_size(leftover))}). Não é removido: está "
                "fora do diretório do projeto e não é nem o Ollama nem o modelo."
            )
    notes.append(
        "Se você instalou com `pip install -e .` fora do .venv, rode "
        "`pip uninstall ai-ethical-agent` no ambiente correspondente -- este "
        "desinstalador não pode e não deve tocar nessa instalação."
    )

    return UninstallPlan(
        root=root,
        mandatory=tuple(mandatory),
        optional=tuple(optional),
        logs=logs,
        model=model,
        ollama_exe=ollama_exe,
        record=record,
        running=running,
        notes=tuple(notes),
    )


def _ollama_ownership_text(record: Optional[InstallRecord]) -> str:
    """Who put Ollama there. The record can only make this more cautious or
    better informed -- in every branch the answer still defaults to "keep"."""
    if record is None or record.ollama_was_present_before is None:
        return (
            "Não há registro de quem instalou o Ollama. Pode estar em uso por "
            "outro projeto."
        )
    if record.ollama_was_present_before:
        return "O Ollama já existia nesta máquina antes desta instalação."
    return (
        "Não havia Ollama localizável antes desta instalação, então "
        "provavelmente foi ela que o instalou. Ainda assim, outro projeto pode "
        "ter passado a usá-lo desde então."
    )


# -- removal ---------------------------------------------------------------


def _is_in_use(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    return getattr(exc, "winerror", None) in (5, 32)


def _force_remove(
    path: Path,
    remove: Callable[[str], None],
    chmod: Callable[[str, int], None],
) -> None:
    """Removes a file, clearing the read-only bit if that was the problem.

    pip leaves read-only files inside a venv, and on Windows os.remove
    refuses those with PermissionError even when nothing holds the file.
    """
    try:
        remove(str(path))
    except PermissionError:
        chmod(str(path), stat.S_IWRITE)
        remove(str(path))


def remove_path(
    path: Path,
    key: str = "",
    *,
    remove: Callable[[str], None] = os.remove,
    rmdir: Callable[[str], None] = os.rmdir,
    chmod: Callable[[str, int], None] = os.chmod,
) -> RemovalResult:
    """Deletes a file or tree, collecting per-entry errors instead of raising.

    Deliberately not shutil.rmtree: "a failure to remove one item must not
    abort the rest" applies *inside* the venv too. One locked python.exe
    (held by a web server the wizard started) must not abandon the other few
    thousand files, and the report should say "3120 de 3124, 4 em uso"
    instead of surfacing a bare PermissionError. Sidesteps rmtree's
    onerror/onexc signature change across 3.10-3.12 as a bonus.
    """
    target = str(path)
    if not path.exists() and not path.is_symlink():
        return RemovalResult(key, target, SKIPPED, "não existe")

    failures: List[Tuple[Path, OSError]] = []
    removed = 0

    def _try(entry: Path, action: Callable[[], None]) -> None:
        nonlocal removed
        try:
            action()
            removed += 1
        except OSError as exc:
            failures.append((entry, exc))

    if path.is_dir() and not path.is_symlink():
        for dirpath, dirnames, filenames in os.walk(path, topdown=False, followlinks=False):
            for name in filenames:
                entry = Path(dirpath) / name
                _try(entry, lambda e=entry: _force_remove(e, remove, chmod))
            for name in dirnames:
                entry = Path(dirpath) / name
                if entry.is_symlink():
                    _try(entry, lambda e=entry: _force_remove(e, remove, chmod))
                else:
                    _try(entry, lambda e=entry: rmdir(str(e)))
        _try(path, lambda: rmdir(target))
    else:
        _try(path, lambda: _force_remove(path, remove, chmod))

    if not failures:
        return RemovalResult(key, target, REMOVED, "")

    total = removed + len(failures)
    detail = f"removidos {removed} de {total} itens; {len(failures)} falharam"
    if any(_is_in_use(exc) for _entry, exc in failures):
        detail += (
            " (arquivo em uso -- o servidor web ou o Ollama podem estar "
            "rodando; veja os avisos acima)"
        )
    first = failures[0]
    detail += f"\n  primeiro erro: {first[0]} -- {first[1]}"
    return RemovalResult(key, target, FAILED, detail)


def move_logs(
    summary: LogsSummary,
    dest_dir: Path,
    root: Path,
    *,
    move: Callable[[str, str], object] = shutil.move,
) -> List[RemovalResult]:
    """Moves the audit trail instead of deleting it.

    Move-or-fail, never move-then-delete: if anything goes wrong the
    originals are still there. This is the most consequential branch in the
    program -- the trail may be the only copy of a study's data.
    """
    logs_dir = (root / "logs").resolve()
    try:
        resolved_dest = dest_dir.resolve()
    except OSError as exc:
        return [RemovalResult("logs", str(dest_dir), FAILED, f"destino inválido: {exc}")]

    if resolved_dest == logs_dir or resolved_dest.is_relative_to(logs_dir):
        return [
            RemovalResult(
                "logs",
                str(dest_dir),
                FAILED,
                "o destino está dentro de logs/ -- escolha um diretório fora dele",
            )
        ]

    for path in summary.files:
        if (dest_dir / path.name).exists():
            return [
                RemovalResult(
                    "logs",
                    str(dest_dir),
                    FAILED,
                    f"já existe {dest_dir / path.name} -- nada foi movido",
                )
            ]

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [
            RemovalResult("logs", str(dest_dir), FAILED, f"não foi possível criar {dest_dir}: {exc}")
        ]

    results: List[RemovalResult] = []
    for path in summary.files:
        try:
            move(str(path), str(dest_dir / path.name))
            results.append(
                RemovalResult("logs", str(path), MOVED, f"movido para {dest_dir / path.name}")
            )
        except OSError as exc:
            results.append(
                RemovalResult("logs", str(path), FAILED, f"não foi possível mover: {exc}")
            )
    return results


def remove_model(
    ollama_exe: Optional[Path],
    model: str,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> RemovalResult:
    manual = f"remova manualmente com: ollama rm {model}"
    if ollama_exe is None:
        return RemovalResult("model", model, FAILED, f"ollama não encontrado -- {manual}")
    try:
        proc = run([str(ollama_exe), "rm", model], capture_output=True, text=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return RemovalResult("model", model, FAILED, f"{exc} -- {manual}")
    if proc.returncode != 0:
        # `ollama rm` needs the server up. Starting one just to uninstall
        # would be odd, so report and hand over the command instead.
        message = (proc.stderr or proc.stdout or "").strip().splitlines()
        reason = message[0] if message else f"código {proc.returncode}"
        return RemovalResult(
            "model",
            model,
            FAILED,
            f"{reason} (o servidor Ollama precisa estar no ar) -- {manual}",
        )
    return RemovalResult("model", model, REMOVED, "")


def remove_ollama(
    ollama_exe: Path,
    *,
    platform: Optional[str] = None,
    verify: Callable[[Path], bool] = verify_windows_signature,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> RemovalResult:
    """Runs the official uninstaller if -- and only if -- it is signed.

    Otherwise this reports the manual steps and returns MANUAL, not FAILED:
    nothing failed, it simply isn't this program's place to guess how to
    uninstall someone else's software.
    """
    platform = platform if platform is not None else sys.platform
    uninstaller = find_ollama_uninstaller(ollama_exe, platform=platform, verify=verify)
    steps = "\n".join(f"  {step}" for step in ollama_manual_steps(platform, ollama_exe))
    if uninstaller is None:
        return RemovalResult(
            "ollama",
            str(ollama_exe),
            MANUAL,
            "nenhum desinstalador oficial verificável foi encontrado. "
            f"Passos manuais:\n{steps}",
        )
    try:
        proc = run([str(uninstaller)])
    except OSError as exc:
        return RemovalResult(
            "ollama", str(ollama_exe), FAILED, f"{exc}\nPassos manuais:\n{steps}"
        )
    if proc.returncode != 0:
        return RemovalResult(
            "ollama",
            str(ollama_exe),
            FAILED,
            f"o desinstalador terminou com código {proc.returncode}\n"
            f"Passos manuais:\n{steps}",
        )
    return RemovalResult("ollama", str(ollama_exe), REMOVED, f"via {uninstaller}")


def execute(
    plan: UninstallPlan,
    choices: Choices,
    *,
    dry_run: bool = False,
    remove: Callable[[str], None] = os.remove,
    rmdir: Callable[[str], None] = os.rmdir,
    chmod: Callable[[str, int], None] = os.chmod,
    move: Callable[[str, str], object] = shutil.move,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
    platform: Optional[str] = None,
    verify: Callable[[Path], bool] = verify_windows_signature,
) -> List[RemovalResult]:
    """Runs the plan, isolating every item. Never raises.

    Ordering matters: the model goes before the Ollama server (removing it
    needs the binary), and the install record goes last (it is what tells a
    later run what happened).

    With dry_run=True nothing is called -- not one filesystem hook -- so a
    test can assert both the reported statuses and that the tree is untouched.
    """
    results: List[RemovalResult] = []

    def _wipe(cand: Candidate) -> None:
        if cand.path is None:
            return
        if dry_run:
            results.append(RemovalResult(cand.key, str(cand.path), WOULD_REMOVE, cand.label))
        else:
            results.append(remove_path(cand.path, cand.key, remove=remove, rmdir=rmdir, chmod=chmod))

    if choices.remove_model and plan.model:
        if dry_run:
            results.append(RemovalResult("model", plan.model, WOULD_REMOVE, f"ollama rm {plan.model}"))
        else:
            results.append(remove_model(plan.ollama_exe, plan.model, run=run))

    if choices.remove_ollama and plan.ollama_exe is not None:
        if dry_run:
            results.append(
                RemovalResult("ollama", str(plan.ollama_exe), WOULD_REMOVE, "desinstalador oficial ou passos manuais")
            )
        else:
            results.append(
                remove_ollama(plan.ollama_exe, platform=platform, verify=verify, run=run)
            )

    if plan.logs is not None and (choices.remove_logs or choices.move_logs_to):
        if choices.move_logs_to is not None:
            if dry_run:
                results.append(
                    RemovalResult("logs", str(plan.logs.files[0].parent), WOULD_REMOVE,
                                  f"mover {len(plan.logs.files)} arquivo(s) para {choices.move_logs_to}")
                )
            else:
                results.extend(move_logs(plan.logs, choices.move_logs_to, plan.root, move=move))
        else:
            for path in plan.logs.files:
                if dry_run:
                    results.append(RemovalResult("logs", str(path), WOULD_REMOVE, ""))
                else:
                    results.append(remove_path(path, "logs", remove=remove, rmdir=rmdir, chmod=chmod))
        # The directory itself only if it came out empty -- anything else in
        # there was not ours to take.
        logs_dir = plan.root / "logs"
        if not dry_run and logs_dir.is_dir():
            try:
                leftover = list(logs_dir.iterdir())
            except OSError:
                leftover = [logs_dir]
            if not leftover:
                results.append(remove_path(logs_dir, "logs", remove=remove, rmdir=rmdir, chmod=chmod))
            else:
                names = ", ".join(sorted(p.name for p in leftover)[:5])
                results.append(
                    RemovalResult("logs", str(logs_dir), SKIPPED, f"mantido: ainda contém {names}")
                )

    for key in ("env", "venv", "build"):
        for cand in plan.mandatory + plan.optional:
            if cand.key != key:
                continue
            if key == "env" and not choices.remove_env:
                continue
            _wipe(cand)

    for cand in plan.mandatory:
        if cand.key == "record":
            _wipe(cand)

    return results


def summarize_results(results: Sequence[RemovalResult]) -> Tuple[int, int, int]:
    """(removed, failed, manual) -- what the final report leads with."""
    removed = sum(1 for r in results if r.status in (REMOVED, MOVED, WOULD_REMOVE))
    failed = sum(1 for r in results if r.status == FAILED)
    manual = sum(1 for r in results if r.status == MANUAL)
    return removed, failed, manual
