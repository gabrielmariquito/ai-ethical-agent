"""Helpers puros do desinstalador, contraparte de `ollama_install.py`: apuram
o que existe, o tamanho, o que está rodando, e removem o que mandarem — como
funções com hooks injetáveis, testáveis sem tkinter: versão longa em `997a6fe^`.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
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
# Parar um serviço não é remover nada, então STOPPED fica fora da contagem de
# `summarize_results`: dizer "3 itens removidos" por ter fechado uma janela
# inflaria o número que o relatório usa para prestar contas.
STOPPED = "stopped"


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
    # Não há `remove_audit_password`: o `.audit-password` é artefato do
    # instalador, como o `.venv`, e sai sempre. Ver a nota em build_plan.


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
    """Cinto e suspensório barato: isto é mesmo o repositório? Só pega quem
    copiou o arquivo para outro lugar — que é exatamente o caso em que errar
    apaga o diretório de um estranho.
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
    """Devolve uma razão pt-BR para recusar, ou `None` quando é seguro seguir:
    no Windows apagar o interpretador em execução deixaria um venv pela
    metade, que é pior que não oferecer — versão longa em `997a6fe^`.
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
    """Devolve todo `__pycache__` sob `root`, podando durante a caminhada e não
    filtrando depois, senão paga-se o custo de andar o `site-packages` inteiro.
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
    """Conta registros num `.jsonl` sem `json.loads` por linha, contando bytes
    de nova linha em blocos, o que é CRLF-safe por construção.
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
    """As últimas `count` linhas não-vazias, lidas de trás; mais de uma porque
    uma execução morta no meio da escrita deixa a última truncada.
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
    """O desinstalador oficial ao lado do `ollama.exe`, só se a assinatura
    conferir: fail-closed por desenho, e o caminho manual é o comum.
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
    """Pergunta à API da própria interface, não a um socket: "algo escutando na
    8765" pode ser processo de terceiro, e mandar matá-lo é confiança que
    este desinstalador não tem.
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
    """Como parar: SÓ COMANDOS, um por linha, porque as cascas renderizam isto
    como bloco copiável e prosa aqui vira linha que falha no terminal: versão longa em `997a6fe^`.
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
    """A prosa que vai AO LADO dos comandos de `stop_hint`, nunca dentro deles:
    as duas moravam numa lista só e os chamadores colavam tudo como comando: versão longa em `997a6fe^`.
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


# -- stopping what is running ----------------------------------------------
#
# A janela existe para quem não abre terminal, então mandar a pessoa ler um PID
# de uma saída de `netstat` e transcrevê-lo num `taskkill` é pedir exatamente o
# que o instalador gráfico existe para não pedir. E não era só atrito: quem não
# rodava os comandos via a remoção do .venv falhar com WinError 5, porque o
# servidor web segura `.venv\Scripts\python.exe`.
#
# `stop_hint`/`stop_note` acima continuam vivos, mas mudaram de papel: eram a
# instrução normal, agora são o caminho de exceção do modo texto, mostrados só
# depois de a parada automática ter falhado.


def _listening_pids(
    port: int,
    *,
    platform: Optional[str] = None,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> List[int]:
    """Quem escuta na porta, por PID. Nunca por nome de imagem: nesta máquina
    havia cinco `python.exe` e nenhum era o servidor, então `taskkill /IM` seria
    um tiro no escuro que acerta o resto.
    """
    platform = platform if platform is not None else sys.platform
    pids: List[int] = []
    try:
        if platform == "win32":
            proc = run(["netstat", "-ano"], capture_output=True, text=True, timeout=15)
            for line in (proc.stdout or "").splitlines():
                parts = line.split()
                # proto, local, remoto, estado, pid -- só as de escuta, e o
                # endereço local tem de terminar na porta, senão `:87650` e a
                # porta de origem de uma conexão de saída entrariam junto.
                if len(parts) < 5 or "LISTENING" not in parts:
                    continue
                if not parts[1].endswith(f":{port}"):
                    continue
                try:
                    pids.append(int(parts[-1]))
                except ValueError:
                    continue
        else:
            proc = run(["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=15)
            for line in (proc.stdout or "").split():
                try:
                    pids.append(int(line))
                except ValueError:
                    continue
    except Exception:  # noqa: BLE001
        # Não achar é "não sei quem é", e "não sei quem é" nunca vira "mate".
        return []
    # IPv4 e IPv6 na mesma porta são duas linhas do mesmo processo.
    return sorted(set(pids))


def _process_image(
    pid: int,
    *,
    platform: Optional[str] = None,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> Tuple[Optional[str], str]:
    """(executável, linha de comando) de um PID, ou (None, "") se não der para
    saber. O PowerShell aqui segue o precedente de `verify_windows_signature`,
    que já consulta o sistema por esse caminho, com o mesmo hook `run`.
    """
    platform = platform if platform is not None else sys.platform
    try:
        if platform == "win32":
            # O '---' separa os dois campos: um ExecutablePath pode conter
            # espaços, e a CommandLine quase sempre contém.
            script = (
                "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(pid) + "'; "
                "if ($p) { $p.ExecutablePath; '---'; $p.CommandLine }"
            )
            proc = run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=20,
            )
            raw = (proc.stdout or "").split("---", 1)
            exe = raw[0].strip() or None
            cmdline = raw[1].strip() if len(raw) > 1 else ""
            return exe, cmdline
        try:
            exe = os.readlink(f"/proc/{pid}/exe")
        except OSError:
            exe = None
        proc = run(["ps", "-p", str(pid), "-o", "args="], capture_output=True, text=True, timeout=15)
        return exe, (proc.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return None, ""


def our_web_ui_pids(
    root: Path,
    port: int,
    *,
    platform: Optional[str] = None,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> Tuple[List[int], List[int]]:
    """(nossos, alheios) entre os PIDs que escutam na porta.

    Duas provas, as duas obrigatórias, porque matar o processo errado é o erro
    que não dá para desfazer: o processo aponta para o .venv DESTA raiz, e é o
    comando que o instalador lança (`-m ethical_agent serve`). A terceira prova
    é do chamador: `web_ui_running` já respondeu 200 na API da interface.

    O apontar-para-o-.venv aceita duas evidências porque uma delas falha no
    Windows. Medido: um processo iniciado com `.venv\\Scripts\\python.exe` tem
    `ExecutablePath` = `...\\Python313\\python.exe`, o interpretador BASE -- o
    venv do Windows redireciona, e o caminho do .venv sobrevive só na
    `CommandLine`. Exigir o ExecutablePath dentro do .venv, como esta função
    fazia, classificava o nosso próprio servidor como alheio e nunca o fechava.
    No POSIX o ExecutablePath aponta para dentro do venv, e aí vale ele.

    Que a linha de comando seja forjável não muda nada aqui: o risco de que
    esta função existe para evitar é derrubar por engano um programa alheio que
    calhou de estar na porta, não um adversário que queira ser morto.

    Os PIDs deste processo e do pai saem da lista antes de qualquer teste. Isso
    NÃO é redundante com a prova do .venv: a leva do relançamento fez o
    desinstalador rodar como filho, e o pai é justamente o Python do .venv --
    as provas abaixo o aprovariam.
    """
    venv = (root / VENV_DIRNAME).resolve()
    forbidden = {os.getpid(), os.getppid()}
    ours: List[int] = []
    strangers: List[int] = []
    for pid in _listening_pids(port, platform=platform, run=run):
        if pid in forbidden:
            continue
        exe, cmdline = _process_image(pid, platform=platform, run=run)
        if not exe and not cmdline:
            strangers.append(pid)
            continue
        # Caminho do Windows não distingue maiúsculas, e a extensão vem como o
        # disco a guardou (`ollama.EXE` numa medição).
        alvo = str(venv).lower() if platform == "win32" else str(venv)
        def _dentro(texto: Optional[str]) -> bool:
            if not texto:
                return False
            candidato = texto.lower() if platform == "win32" else texto
            return alvo in candidato

        aponta_para_o_venv = _dentro(cmdline)
        if not aponta_para_o_venv and exe:
            try:
                aponta_para_o_venv = Path(exe).resolve().is_relative_to(venv)
            except (OSError, ValueError):
                aponta_para_o_venv = _dentro(exe)
        lowered = cmdline.lower()
        if aponta_para_o_venv and "ethical_agent" in lowered and "serve" in lowered:
            ours.append(pid)
        else:
            strangers.append(pid)
    return ours, strangers


def stop_web_ui(
    root: Path,
    port: int,
    *,
    platform: Optional[str] = None,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
    urlopen: Callable[..., object] = urllib.request.urlopen,
    settle: Callable[[float], None] = time.sleep,
) -> Optional[RemovalResult]:
    """Fecha a interface web para o .venv poder sair. `None` quando não havia
    nada no ar -- silêncio é a resposta certa para o caso comum, e uma linha
    "[skipped] interface web" em toda desinstalação seria ruído.

    As duas falhas são resultados diferentes de propósito: "não confirmei que é
    nosso" é uma decisão de não agir, "tentei e não consegui" é uma ação que
    falhou. Quem lê precisa saber qual das duas aconteceu.
    """
    platform = platform if platform is not None else sys.platform
    target = f"interface web (http://127.0.0.1:{port})"
    if not web_ui_running(port, urlopen=urlopen):
        return None

    ours, strangers = our_web_ui_pids(root, port, platform=platform, run=run)
    if not ours:
        quantos = f"{len(strangers)} programa(s)" if strangers else "um programa"
        return RemovalResult(
            "web_ui",
            target,
            FAILED,
            f"Encontrei {quantos} usando a porta {port}, mas não consegui "
            "confirmar que é a interface deste projeto -- então NÃO FECHEI "
            "NADA, para não derrubar outra coisa da sua máquina.\n"
            "Feche a janela em que a interface web está rodando e abra o "
            "desinstalador de novo.",
        )

    for pid in ours:
        try:
            if platform == "win32":
                run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True, timeout=30)
            else:
                os.kill(pid, signal.SIGTERM)
        except Exception:  # noqa: BLE001
            # Já morrer entre o netstat e o kill é sucesso, não erro. Quem
            # decide se parou é a sondagem abaixo, não o código de saída.
            pass

    # Verificar que parou, e não confiar no taskkill: PID reciclado, permissão
    # negada e processo já morto dão saídas diferentes e nenhuma delas responde
    # "a porta está livre?". Quem responde isso é a porta.
    for espera in (0.2, 0.5, 1.0):
        if not web_ui_running(port, urlopen=urlopen):
            return RemovalResult("web_ui", target, STOPPED, "estava aberta e foi fechada")
        settle(espera)
    if not web_ui_running(port, urlopen=urlopen):
        return RemovalResult("web_ui", target, STOPPED, "estava aberta e foi fechada")

    return RemovalResult(
        "web_ui",
        target,
        FAILED,
        "TENTEI FECHAR a interface web e não consegui. Por isso não removi o "
        ".venv -- removê-lo com ela aberta deixaria a pasta pela metade.\n"
        "Feche a janela em que a interface web está rodando e abra o "
        "desinstalador de novo.",
    )


def stop_ollama(
    *,
    platform: Optional[str] = None,
    run: Callable[..., "subprocess.CompletedProcess"] = subprocess.run,
) -> RemovalResult:
    """Para o servidor Ollama. Só é chamada quando o usuário escolheu removê-lo,
    e depois de o modelo já ter saído -- `ollama rm` fala com o servidor e falha
    sem ele (ver remove_model).
    """
    platform = platform if platform is not None else sys.platform
    if platform == "win32":
        # Dois processos: o servidor e o app da bandeja.
        cmds = [["taskkill", "/IM", "ollama.exe", "/F"], ["taskkill", "/IM", "ollama app.exe", "/F"]]
    else:
        # `sudo systemctl stop ollama` fica de fora de propósito: rodar sudo
        # sozinho trava num prompt de senha que a janela não mostra.
        cmds = [["pkill", "-f", "ollama serve"]]
    parou = False
    for cmd in cmds:
        try:
            proc = run(cmd, capture_output=True, text=True, timeout=30)
            if getattr(proc, "returncode", 1) == 0:
                parou = True
        except Exception:  # noqa: BLE001
            continue
    if parou:
        return RemovalResult("ollama_stop", "servidor Ollama", STOPPED, "estava rodando e foi parado")
    return RemovalResult(
        "ollama_stop",
        "servidor Ollama",
        SKIPPED,
        "não estava rodando, ou já havia parado",
    )


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

    # Obrigatório, e não uma caixa a mais: o `.audit-password` é artefato do
    # instalador, como o `.venv` -- ele o cria, e sem o resto da instalação o
    # arquivo não protege tela nenhuma. O que se perde é recuperável sem sair
    # da máquina (rodar o instalador de novo define outra senha), e o que está
    # dentro é hash, não a senha: manter o arquivo não guardaria um segredo,
    # guardaria um resto.
    from . import senha_auditoria

    senha_path = senha_auditoria.caminho_do_registro(root)
    if senha_path.exists():
        mandatory.append(
            Candidate(
                key="audit_password",
                path=senha_path,
                kind="file",
                size_bytes=dir_size(senha_path),
                label=senha_auditoria.NOME_ARQUIVO,
                # Uma linha só: os obrigatórios são impressos em tabela, e o
                # detalhe entra na mesma linha do rótulo.
                detail=(
                    "Hash da senha da tela de auditoria (/audit) -- desativa a "
                    "tela; o instalador define outra"
                ),
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
        # E o que ele é para ESTE .env: prometer "a chave da Ollama Cloud" num
        # arquivo que só tem OLLAMA_MODEL descreve outro arquivo, e a linha
        # existe justamente para quem não sabe o que tem dentro.
        detail = (
            "Arquivo de configuração escrito pelo instalador: guarda as "
            "escolhas da instalação -- qual modelo usar, como falar com o "
            "Ollama -- para o projeto reencontrá-las a cada execução. "
            "Removê-lo não apaga nada além dessas escolhas; rodar o "
            "instalador de novo o recria."
        )
        if "OLLAMA_API_KEY" in keys:
            detail += (
                "\nOLLAMA_API_KEY é a chave da Ollama Cloud -- perdê-la por "
                "engano significa gerar outra em ollama.com/settings/keys."
            )
        # A senha da auditoria saiu deste arquivo na leva do hash, e por isso
        # saiu daqui também: ela é item próprio, logo abaixo. Um `.env` que
        # ainda tenha a chave é uma máquina que nunca subiu depois da mudança --
        # a primeira subida migra e apaga a linha --, e vale dizer isso em vez
        # de descrever um arquivo que já não é o que ele foi.
        if "ETHICAL_AGENT_AUDIT_PASSWORD" in keys:
            detail += (
                "\nEste .env ainda tem a senha da auditoria em texto plano, de "
                "uma instalação anterior. Ela é migrada para hash (e a linha "
                "some daqui) na primeira vez que `ethical-agent serve` ou o "
                "instalador rodarem."
            )
        optional.append(
            Candidate(
                key="env",
                path=env_path,
                kind="file",
                size_bytes=dir_size(env_path),
                label="Arquivo .env",
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


def plan_totals(
    plan: UninstallPlan, choices: Optional[Choices] = None
) -> Tuple[int, int, int]:
    """(quantidade, bytes, sem_tamanho) do plano, em dois recortes.

    Um cálculo só para as duas telas, porque elas respondiam perguntas
    diferentes sem dizer qual: a de boas-vindas contava só o obrigatório --
    ela roda antes de existir escolha --, e o resumo listava o obrigatório mais
    o que foi marcado. Quem lia via um número virar outro e concluía, com razão,
    que um dos dois estava errado.

    `choices=None` é o recorte automático (o que sai sem perguntar); com
    `choices`, o total já escolhido. Quem chama diz qual quer, e a tela nomeia
    o recorte que mostrou -- um total sem rótulo de escopo recria o problema.

    `sem_tamanho` existe porque somar `size_bytes or 0` faz um tamanho
    desconhecido virar zero calado, e o total sai menor do que a verdade sem
    nada na tela denunciando isso. O modelo do Ollama é o caso real: ele vem
    com `size_bytes=None` quando o `ollama list` não informa.
    """
    itens = list(plan.mandatory)
    if choices is not None:
        marcado = {
            "logs": choices.remove_logs or choices.move_logs_to is not None,
            "ollama": choices.remove_ollama,
            "model": choices.remove_model,
            "env": choices.remove_env,
        }
        itens += [c for c in plan.optional if marcado.get(c.key)]
    total = sum(c.size_bytes or 0 for c in itens)
    sem_tamanho = sum(1 for c in itens if c.size_bytes is None)
    return len(itens), total, sem_tamanho


def describe_totals(plan: UninstallPlan, choices: Optional[Choices] = None) -> str:
    """A frase que as duas telas imprimem, para não divergirem na redação
    depois de já concordarem no número."""
    quantos, total, sem_tamanho = plan_totals(plan, choices)
    frase = f"{quantos} {'item' if quantos == 1 else 'itens'}, {format_size(total)}"
    if sem_tamanho:
        frase += f" (+{sem_tamanho} de tamanho desconhecido)"
    return frase


def _ollama_ownership_text(record: Optional[InstallRecord]) -> str:
    """Who put Ollama there. The record can only make this more cautious or
    better informed -- in every branch the answer still defaults to "keep"."""
    # A frase começa pela resposta -- "foi este projeto" / "não foi" --, porque
    # é essa a única coisa que decide a caixa. O caso sem registro existe (o
    # arquivo é removível, e uma remoção anterior pode tê-lo levado), e aí a
    # resposta honesta é que não dá para saber: inventar um "não foi" seria
    # mandar a pessoa desinstalar o Ollama de outro projeto.
    if record is None or record.ollama_was_present_before is None:
        return (
            "Não dá para dizer se foi este projeto que instalou o Ollama: o "
            "registro da instalação não está mais aqui. Pode estar em uso por "
            "outro projeto."
        )
    if record.ollama_was_present_before:
        return (
            "Não foi este projeto que instalou o Ollama: ele já existia nesta "
            "máquina antes desta instalação, e quase certamente pertence a "
            "outra coisa."
        )
    return (
        "Foi provavelmente este projeto que instalou o Ollama: não havia "
        "nenhum localizável antes desta instalação. Ainda assim, outro projeto "
        "pode ter passado a usá-lo desde então."
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
    """Apaga arquivo ou árvore coletando erros por entrada em vez de levantar,
    porque "falhar em remover um item não pode abortar o resto" vale *dentro*
    do venv também: versão longa em `997a6fe^`.
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
    """Move a trilha em vez de apagá-la, mover-ou-falhar e nunca mover-e-apagar:
    é o ramo mais consequente do programa, porque a trilha pode ser a única
    cópia dos dados de um estudo.
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
    """Roda o desinstalador oficial se — e só se — ele estiver assinado; caso
    contrário reporta os passos manuais e devolve MANUAL, não FAILED.
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
    # A sondagem "a interface ainda responde?" precisa ser injetável como todo
    # o resto do módulo: sem isto, a parada da web só seria testável com um
    # servidor de verdade no ar.
    urlopen: Callable[..., object] = urllib.request.urlopen,
) -> List[RemovalResult]:
    """Roda o plano isolando cada item e nunca levanta; a ordem importa, e com
    `dry_run=True` nada é chamado — nem um hook de sistema de arquivos.
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
            # AQUI, e não antes: parar o Ollama só porque ele estava no ar
            # derrubaria um serviço que outro projeto pode estar usando, para
            # uma remoção que talvez nem tenha sido pedida. E este ramo já vem
            # DEPOIS do ramo do modelo, então a ordem que o `ollama rm` exige --
            # servidor no ar enquanto o modelo sai -- se mantém sozinha.
            if plan.running.ollama:
                results.append(stop_ollama(platform=platform, run=run))
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

    # A interface web é fechada AQUI, e não no arranque do programa: assim
    # cancelar em qualquer tela anterior não derruba nada, e o --dry-run fica
    # seguro por construção. É também o único ponto em que o resultado da
    # parada consegue impedir a remoção do .venv, que é o que ela precisa
    # impedir quando falha.
    venv_liberado = True
    if not dry_run and plan.candidate("venv") is not None:
        parada = stop_web_ui(
            plan.root,
            plan.running.web_port or 0,
            platform=platform,
            run=run,
            urlopen=urlopen,
        )
        if parada is not None:
            results.append(parada)
            venv_liberado = parada.status != FAILED

    for key in ("audit_password", "env", "venv", "build"):
        for cand in plan.mandatory + plan.optional:
            if cand.key != key:
                continue
            if key == "env" and not choices.remove_env:
                continue
            if key == "venv" and not venv_liberado:
                # Tentar às cegas gastaria minutos apagando 3658 de 3661 itens
                # para parar no python.exe que a interface segura -- foi
                # exatamente esse o estado em que a falha de campo deixou a
                # máquina. Não tentar deixa o .venv inteiro e recuperável.
                results.append(
                    RemovalResult(
                        cand.key,
                        str(cand.path),
                        SKIPPED,
                        "não foi removido porque a interface web continua aberta; "
                        "feche-a e abra o desinstalador de novo",
                    )
                )
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
