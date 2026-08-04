"""Helpers puros do passo opcional de Ollama do `wizard_gui.py`, como funções
com hooks injetáveis de subprocess/urlopen, testáveis sem tkinter, display,
rede ou Ollama real: versão longa em `997a6fe^`.
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
    """Procura no PATH e depois nos locais conhecidos, porque logo após uma
    instalação as mudanças de ambiente não chegam a este processo.
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
    """Sobe `ollama serve` destacado para sobreviver ao wizard, porque no
    Windows o app é item de login e "instalado mas parado" é o estado comum —
    sem isto `wait_for_server()` expira onde nada falta: versão longa em `997a6fe^`.
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
    """Remove toda linha `key=` do `.env` preservando as outras, e devolve
    `None` quando não havia o que remover — contraparte de `_upsert_env_var`,
    que só sabe acrescentar ou substituir: versão longa em `997a6fe^`.
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
    """Persiste a senha da tela de auditoria para o `serve` achá-la sem flag,
    com strip na escrita porque o leitor também faz strip.
    """
    return _upsert_env_var(root, AUDIT_PASSWORD_ENV_VAR, password.strip())


def read_env_var(root: Path, key: str) -> Optional[str]:
    """Lê `key=` do `.env`, ou `None`; feito à mão em vez de python-dotenv
    porque aquele só chega com o extra `llm` e os dois chamadores precisam
    funcionar numa instalação que nunca optou por modelo real.
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


# Uma fonte ambiente só, e um arame de tropeço na que morreu: o `.env` é a
# única fonte ambiente da senha, e a variável de ambiente não é mais lida como
# senha — só comparada — versão longa em `997a6fe^`.

AUDIT_PASSWORD_ENV_VAR = "ETHICAL_AGENT_AUDIT_PASSWORD"


def exported_audit_password(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """A senha exportada no ambiente, ou `None`, com strip para que exportada-e-
    vazia conte como ausente; não é mais *fonte*, e o valor é lido só para
    comparação: versão longa em `997a6fe^`.
    """
    source = os.environ if env is None else env
    return (source.get(AUDIT_PASSWORD_ENV_VAR) or "").strip() or None


def env_audit_password_present(env: Optional[Mapping[str, str]] = None) -> bool:
    """Se o ambiente ainda tem a variável setada — presença, não usabilidade,
    porque ela não configura mais nada e o que se pergunta é se há uma
    remanescente sobre a qual avisar.
    """
    return exported_audit_password(env) is not None


def audit_password_conflict_against(
    root: Path,
    effective: Optional[str],
    env: Optional[Mapping[str, str]] = None,
    password_file: Optional[str] = None,
) -> Optional[str]:
    """A mensagem quando uma variável remanescente discorda de `effective`, ou
    `None` quando não há o que dizer — devolver o texto em vez de um booleano
    é o que mantém CLI e instalador dizendo a mesma coisa: versão longa em `997a6fe^`.
    """
    if password_file:
        return None
    exported = exported_audit_password(env)
    if exported is None:
        return None
    if effective is not None and effective == exported:
        return None

    env_path = (root / ".env").resolve()
    saida = (
        "\nPara subir agora sem mexer em configuração nenhuma: "
        "--audit-password-file ARQUIVO."
    )
    if effective is not None:
        return (
            f"a variável de ambiente ${AUDIT_PASSWORD_ENV_VAR} está definida com "
            "um valor diferente da senha que está em vigor.\n"
            f"A senha de auditoria mora em {env_path}, e é essa que vale. A "
            "variável não é mais lida -- quem entrar com o valor dela vai ser "
            "recusado no login sem explicação.\n"
            "Apague a variável de ambiente." + saida
        )
    return (
        f"a variável de ambiente ${AUDIT_PASSWORD_ENV_VAR} está definida, mas "
        "ela não é mais uma fonte de senha de auditoria.\n"
        f"A senha mora em {env_path}, que não tem nenhuma -- do jeito que está, "
        "a tela de auditoria não existiria, e quem entrasse com o valor da "
        "variável seria recusado sem explicação.\n"
        "Grave a senha no .env (rode o instalador, `python wizard_gui.py`) e "
        "apague a variável de ambiente." + saida
    )


def audit_password_conflict(
    root: Path,
    env: Optional[Mapping[str, str]] = None,
    password_file: Optional[str] = None,
) -> Optional[str]:
    """Is this machine already in the refusing state? Reads .env for the
    password in effect and compares. Same name and signature as when it
    guarded two competing sources -- it is still asking whether something
    contradicts the password that will be used."""
    return audit_password_conflict_against(
        root, read_env_var(root, AUDIT_PASSWORD_ENV_VAR), env, password_file
    )


# Havia aqui uma terceira função para o instalador perguntar o mesmo sobre uma
# senha que ia escrever; ela saiu junto com a segunda explicação do instalador
# sobre a variável remanescente — versão longa em `997a6fe^`.


def read_env_model_optional(root: Path) -> Optional[str]:
    """Lê `OLLAMA_MODEL=` do `.env`, ou `None`; separado do `read_env_model`
    porque a diferença entre "não configurado" e "configurado no default"
    importa para uma decisão **destrutiva**: versão longa em `997a6fe^`.
    """
    return read_env_var(root, "OLLAMA_MODEL")


def read_env_model(root: Path, default: str) -> str:
    """Reads `OLLAMA_MODEL=` from `root`/.env, without requiring
    python-dotenv to be installed -- this has to work even when the `llm`
    extra (which pulls in python-dotenv) was never installed."""
    model = read_env_model_optional(root)
    return model if model is not None else default
