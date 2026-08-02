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

Pending, deliberately out of scope here: `process` can now end up answering
from Ollama local, Ollama Cloud, or MockLLM fallback, but neither the CLI/GUI
output nor the audit record (GuardedAgent._finish in agent.py) says which one
actually produced a given response. That's a separate change.
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
from typing import Callable, Iterator, Optional, Tuple

DEFAULT_LOCAL_MODEL = "llama3.1:8b"

# (download size in GB, recommended RAM in GB). Extend as more models get a
# wizard-verified estimate; unknown models fall back to a generic message
# instead of guessing a number.
KNOWN_MODEL_SIZES: dict[str, tuple[float, float]] = {
    "llama3.1:8b": (4.7, 16.0),
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


def write_env_api_key(root: Path, key: str) -> Path:
    """Creates/updates `.env` at `root`, replacing an existing
    OLLAMA_API_KEY= line in place rather than duplicating it, and leaving
    every other line untouched."""
    env_path = root / ".env"
    lines: list[str] = []
    replaced = False
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("OLLAMA_API_KEY="):
                lines.append(f"OLLAMA_API_KEY={key}")
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"OLLAMA_API_KEY={key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return env_path
