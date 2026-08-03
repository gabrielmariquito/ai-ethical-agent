"""Pure helpers for wizard_gui.py's optional Ollama server/model install step.

Detecting an existing Ollama install, downloading/running the platform
installer, verifying it, watching for the server to come up, and pulling a
model are all here as plain functions with injectable subprocess/urlopen
hooks, so they're testable without tkinter, a display, real network access,
or a real Ollama install. wizard_gui.py wires these into its
thread+queue+polling ProgressPage.

Lives inside ethical_agent/ (like gui_choices.py) rather than at the repo
root so it stays importable as `ethical_agent.ollama_install` regardless of
the current working directory pytest is run from -- a bare module at the
repo root is not reliably importable when the CWD differs from the repo
root, which previously broke test_gui_audit.py.

`process` can answer from Ollama local, Ollama Cloud, or the MockLLM
fallback. Which one actually produced a given response is not left implicit:
llm.resolve_llm classifies it, llm.describe_llm_provenance prints it, and
GuardedAgent._finish (agent.py) stores it in every audit record under
`llm_provenance`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional, Tuple

DEFAULT_LOCAL_MODEL = "llama3.2:3b"

# (download size in GB, recommended RAM in GB). Extend as more models get a
# wizard-verified estimate; unknown models fall back to a generic message
# instead of guessing a number.
KNOWN_MODEL_SIZES: dict[str, tuple[float, float]] = {
    "llama3.1:8b": (4.7, 16.0),
    "llama3.2:3b": (2.0, 8.0),
}

WINDOWS_INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
LINUX_INSTALL_SCRIPT_URL = "https://ollama.com/install.sh"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


def estimate_model_size_text(model: str) -> str:
    sizes = KNOWN_MODEL_SIZES.get(model.strip())
    if sizes is None:
        return (
            "Tamanho de download desconhecido para este modelo -- confira "
            f"https://ollama.com/library/{model.strip()}"
        )
    download_gb, ram_gb = sizes
    download_str = f"{download_gb:.1f}".replace(".", ",")
    return f"~{download_str} GB de download, ~{ram_gb:.0f} GB de RAM recomendados"


def find_ollama_exe(which: Callable[[str], Optional[str]] = shutil.which) -> Optional[Path]:
    """Looks on PATH first, then well-known install locations.

    A fallback beyond PATH matters right after a fresh install: environment
    variable changes made by an installer don't propagate to this
    already-running process, so `which("ollama")` can miss a real install.
    """
    found = which("ollama")
    if found:
        return Path(found)
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            candidate = Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe"
            if candidate.exists():
                return candidate
    else:
        for candidate in (
            Path("/usr/local/bin/ollama"),
            Path("/usr/bin/ollama"),
            Path.home() / ".ollama" / "bin" / "ollama",
        ):
            if candidate.exists():
                return candidate
    return None


@dataclass(frozen=True)
class InstallerPlan:
    kind: str  # "download_exe" (Windows) | "shell_script" (Linux)
    source_url: str
    command: Optional[Tuple[str, ...]] = None


def installer_plan_for_platform(platform: Optional[str] = None) -> Optional[InstallerPlan]:
    """Returns how to install Ollama on this platform, or None if the wizard
    doesn't attempt an automated install here (macOS: the official installer
    is a .app dragged into /Applications by hand, no clean way to script
    that)."""
    platform = platform if platform is not None else sys.platform
    if platform == "win32":
        return InstallerPlan(kind="download_exe", source_url=WINDOWS_INSTALLER_URL)
    if platform.startswith("linux"):
        return InstallerPlan(
            kind="shell_script",
            source_url=LINUX_INSTALL_SCRIPT_URL,
            command=("sh", "-c", f"curl -fsSL {LINUX_INSTALL_SCRIPT_URL} | sh"),
        )
    return None


def download_file(
    url: str,
    dest: Path,
    on_progress: Optional[Callable[[int, Optional[int]], None]] = None,
    chunk_size: int = 1 << 16,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response:
        total_header = response.headers.get("Content-Length")
        total = int(total_header) if total_header else None
        downloaded = 0
        with open(dest, "wb") as fh:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                if on_progress is not None:
                    on_progress(downloaded, total)


def verify_windows_signature(path: Path, run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run) -> bool:
    """Confirms `path` carries a valid Authenticode signature before it gets
    executed. Fail-closed: any error (PowerShell missing, timeout,
    unexpected output) is treated as "not verified", never as "assume ok".
    """
    try:
        proc = run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f"(Get-AuthenticodeSignature -LiteralPath '{path}').Status",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "Valid"


def iter_stream_chunks(stream) -> Iterator[str]:
    """Reads a text-mode stream, yielding a chunk each time it hits '\\n' OR
    '\\r'. `ollama pull` (and some installers) print progress with '\\r'
    in-place updates; a plain `for line in stream` only yields on '\\n' and
    would sit silent until the whole run finishes.
    """
    buf: list[str] = []
    while True:
        ch = stream.read(1)
        if ch == "":
            break
        if ch in ("\n", "\r"):
            if buf:
                yield "".join(buf)
                buf = []
        else:
            buf.append(ch)
    if buf:
        yield "".join(buf)


def wait_for_server(
    host: str = DEFAULT_OLLAMA_HOST,
    timeout: float = 15.0,
    poll: float = 0.5,
    urlopen: Callable[..., object] = urllib.request.urlopen,
) -> bool:
    url = host.rstrip("/") + "/api/tags"
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urlopen(url, timeout=2) as resp:
                status = getattr(resp, "status", 200)
                if status == 200:
                    return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


# Read via getattr because these constants only exist on Windows builds of
# subprocess -- naming them unconditionally keeps the win32 branch below
# importable (and testable with an injected platform) on Linux/macOS.
_WIN_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_WIN_BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)


def start_ollama_server(
    ollama_exe: Path,
    popen: Callable[..., "subprocess.Popen"] = subprocess.Popen,
    platform: Optional[str] = None,
) -> Optional["subprocess.Popen"]:
    """Starts `ollama serve` detached, so it outlives the wizard.

    On Windows the Ollama app registers itself as a login item: it comes up
    when the user logs in, not when an installer invokes it. So "installed
    but not running" is the common state, and nothing else in this project
    ever starts the server -- without this, wait_for_server() times out on a
    machine where nothing is actually missing.

    Detaching mirrors wizard_gui's _launch_interface: the server has to stay
    up for the model pull and for the app afterwards, so it is deliberately
    never waited on or killed. CREATE_NO_WINDOW because ollama.exe is a
    console app and the wizard is a GUI -- otherwise a console window flashes.
    """
    platform = platform if platform is not None else sys.platform
    cmd = [str(ollama_exe), "serve"]
    kwargs = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    if platform == "win32":
        flags = _WIN_NEW_GROUP | _WIN_NO_WINDOW
        try:
            # CREATE_BREAKAWAY_FROM_JOB lets the server survive even if the
            # wizard runs under a job object; some job policies forbid
            # breakaway, so fall back to the plain flags.
            return popen(cmd, creationflags=flags | _WIN_BREAKAWAY, **kwargs)
        except OSError:
            pass
        try:
            return popen(cmd, creationflags=flags, **kwargs)
        except OSError:
            return None
    try:
        return popen(cmd, start_new_session=True, **kwargs)
    except OSError:
        return None


def _normalize_tag(tag: str) -> str:
    return tag[: -len(":latest")] if tag.endswith(":latest") else tag


def model_already_pulled(
    ollama_exe: Path,
    model: str,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> bool:
    try:
        proc = run([str(ollama_exe), "list"], capture_output=True, text=True, timeout=30)
    except Exception:
        return False
    if proc.returncode != 0:
        return False
    target = _normalize_tag(model.strip())
    for line in proc.stdout.splitlines()[1:]:  # skip the header row
        parts = line.split()
        if parts and _normalize_tag(parts[0]) == target:
            return True
    return False


def _upsert_env_var(root: Path, key: str, value: str) -> Path:
    """Creates/updates `.env` at `root`, replacing an existing `key=` line
    in place rather than duplicating it, and leaving every other line
    untouched."""
    env_path = root / ".env"
    prefix = f"{key}="
    lines: list[str] = []
    replaced = False
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix):
                lines.append(f"{prefix}{value}")
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"{prefix}{value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path


def remove_env_var(root: Path, key: str) -> Optional[Path]:
    """Drops every `key=` line from `.env`, leaving the other lines exactly
    as they were. Returns None when there was nothing to remove -- no file,
    or a file that never had the key.

    The counterpart to _upsert_env_var, which can only add or replace. A
    caller that wants a setting *gone* (rather than set to empty) needs this:
    `KEY=` with an empty value and no `KEY=` line at all are the same thing
    to the readers here, but only the second one keeps .env honest about
    what is configured -- and it is what the uninstaller's key listing
    (uninstall.env_keys_present) reports on.
    """
    env_path = root / ".env"
    if not env_path.exists():
        return None
    prefix = f"{key}="
    lines = env_path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not line.startswith(prefix)]
    if len(kept) == len(lines):
        return None
    env_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return env_path


def write_env_api_key(root: Path, key: str) -> Path:
    return _upsert_env_var(root, "OLLAMA_API_KEY", key)


def write_env_model(root: Path, model: str) -> Path:
    return _upsert_env_var(root, "OLLAMA_MODEL", model)


def write_env_audit_password(root: Path, password: str) -> Path:
    """Persists the audit-screen password so `serve` finds it with no flag.

    Stripped before writing because read_env_var strips on the way out: a
    password stored with a trailing space would silently never match what
    the reader hands to the login check.
    """
    return _upsert_env_var(root, AUDIT_PASSWORD_ENV_VAR, password.strip())


def read_env_var(root: Path, key: str) -> Optional[str]:
    """Reads `key=` from `root`/.env, or None when it isn't set.

    Deliberately hand-rolled rather than python-dotenv: that package only
    arrives with the `llm` extra, and both callers here -- the uninstaller
    and the audit-password loader in webui/auth.py -- have to work on an
    install that never opted into a real model.
    """
    env_path = root / ".env"
    if env_path.exists():
        prefix = f"{key}="
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix):
                value = line[len(prefix):].strip()
                if value:
                    return value
    return None


# -- two audit passwords at once ---------------------------------------------
#
# The audit-screen password can arrive from two *ambient* places: the
# environment variable, and .env at the project root (where the graphical
# installer writes it). Both defined at the same time used to be a precedence
# question -- the variable won, and the startup banner named the loser. In
# use that turned out to be the wrong shape for the problem: the banner is in
# a terminal window nobody is necessarily watching, and the person who then
# types the .env password into the browser is simply rejected, with no
# explanation available anywhere on screen. Two configured passwords is a
# configuration error, and the server refuses to start on it.
#
# This lives here, next to the .env reader, because it is the only module
# both callers can reach: webui/auth.py imports it, and wizard_gui.py imports
# it while running on the *system* Python before the project is installed
# (see wizard_gui.py's comment on AUDIT_PASSWORD_ENV_VAR, which is why the
# installer cannot import webui/auth at all).

AUDIT_PASSWORD_ENV_VAR = "ETHICAL_AGENT_AUDIT_PASSWORD"


def env_audit_password_present(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether the environment defines a usable audit password.

    Stripped, so that an exported-but-empty variable -- how a shell profile
    leaves a name defined without meaning anything by it -- counts as absent,
    exactly as read_env_var already treats a bare `KEY=` line in .env. The
    two halves of the conflict check have to agree on what "defined" means,
    or they disagree about how many passwords exist.
    """
    source = os.environ if env is None else env
    return bool((source.get(AUDIT_PASSWORD_ENV_VAR) or "").strip())


def audit_password_conflict(
    root: Path,
    env: Optional[Mapping[str, str]] = None,
    password_file: Optional[str] = None,
) -> Optional[str]:
    """The message to show when both ambient sources define a password, or
    None when there is no conflict. Returning the text, rather than a bool,
    is what keeps the CLI and the installer saying the same thing.

    `password_file` is a parameter here rather than a check the callers do
    for themselves. The flag is an explicit, per-invocation answer to "which
    one", so it silences the conflict -- and that exception has to live in
    the same place as the rule. Implemented twice, the two callers would
    drift apart on the *exception* while still appearing to share the rule,
    which is the divergence nobody notices.
    """
    if password_file:
        return None
    if not env_audit_password_present(env):
        return None
    if read_env_var(root, AUDIT_PASSWORD_ENV_VAR) is None:
        return None

    env_path = (root / ".env").resolve()
    return (
        "há duas senhas de auditoria definidas ao mesmo tempo, e não dá para "
        "saber qual delas é a que vale:\n"
        f"  - a variável de ambiente ${AUDIT_PASSWORD_ENV_VAR}\n"
        f"  - a chave {AUDIT_PASSWORD_ENV_VAR} do arquivo {env_path}\n"
        "Usar uma das duas em silêncio faz a outra ser recusada no login sem "
        "explicação nenhuma, que foi como este caso apareceu. Remova uma das "
        "duas -- qual delas é decisão de quem instalou, não deste programa.\n"
        "Para subir agora sem mexer em nenhuma das duas: "
        "--audit-password-file ARQUIVO, que tem precedência sobre ambas."
    )


def audit_password_would_conflict(
    root: Path, env: Optional[Mapping[str, str]] = None
) -> Optional[str]:
    """The other half of the same rule: the environment already defines a
    password and the caller is about to write a second one into .env. None
    when there is nothing exported and the write is fine.

    Separate from audit_password_conflict because the two are asked at
    different moments and answer different questions -- "is this machine
    already misconfigured?" versus "would what I am about to do misconfigure
    it?" -- and because the second one has to be answerable *before* the .env
    key exists, which is exactly when the first one is still None. Callers
    append their own way out: what that is depends on whether there is still
    a field on screen to edit.

    Returned ready to display, first letter and all. A caller that
    capitalized it would lowercase the variable name in the middle of it,
    which is how the message ends up naming a variable that does not exist.
    """
    if not env_audit_password_present(env):
        return None

    env_path = (root / ".env").resolve()
    return (
        f"A variável de ambiente ${AUDIT_PASSWORD_ENV_VAR} já define uma senha "
        f"de auditoria nesta máquina. Gravar outra em {env_path} deixaria duas "
        "definidas ao mesmo tempo, e a interface web se recusa a subir assim."
    )


def read_env_model_optional(root: Path) -> Optional[str]:
    """Reads `OLLAMA_MODEL=` from `root`/.env, or None when it isn't set.

    Separate from read_env_model below because the difference between "not
    configured" and "configured to the default" matters for a *destructive*
    decision. In cloud mode the wizard writes only OLLAMA_API_KEY
    (_run_llm_setup_cloud), never an OLLAMA_MODEL line -- so a defaulting
    reader would report llama3.2:3b as this project's model on a machine
    where this project never pulled a model at all, and the uninstaller
    would offer to delete someone else's.
    """
    return read_env_var(root, "OLLAMA_MODEL")


def read_env_model(root: Path, default: str) -> str:
    """Reads `OLLAMA_MODEL=` from `root`/.env, without requiring
    python-dotenv to be installed -- this has to work even when the `llm`
    extra (which pulls in python-dotenv) was never installed."""
    model = read_env_model_optional(root)
    return model if model is not None else default
