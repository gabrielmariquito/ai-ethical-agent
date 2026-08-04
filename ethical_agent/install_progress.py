"""Plano de fases e aritmética da barra do instalador, que era uma barra
`indeterminate` correndo do primeiro ao último segundo sem dizer em que passo
estava: `REGISTRO`, "Texto movido do código".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .ollama_install import KNOWN_MODEL_SIZES

PHASE_VENV = "venv"
PHASE_PIP = "pip"
PHASE_OLLAMA = "ollama"
PHASE_MODEL = "model"
PHASE_CONFIG = "config"

# Relative wall-clock cost, not equal steps: on a cold Windows machine the
# model download alone is the majority of the time, and giving it the same
# slice as "write a line to .env" is what makes a bar feel dishonest. These
# get normalized to sum to 100 for whichever subset actually runs.
_WEIGHTS = {
    PHASE_VENV: 8.0,
    PHASE_PIP: 20.0,
    PHASE_OLLAMA: 22.0,
    PHASE_MODEL: 45.0,
    PHASE_CONFIG: 5.0,
}

# `ollama pull` prints 1000-based units ("2.0 GB"), and so does
# KNOWN_MODEL_SIZES' GB figure. Both sides of every ratio computed here come
# from the same convention, so the choice only ever affects the fallback
# denominator -- by ~7%, which no progress bar cares about.
_UNIT_BYTES = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
}

# "pulling dde5aa3fc5ff:  12% ..." -- the digest is what makes a layer
# identifiable across the \r refreshes that iter_stream_chunks yields. The
# gap between the two is punctuation and right-alignment padding only, so it
# is matched as "no digits", which is what keeps the percentage unambiguous
# however wide ollama decides to pad that field.
_PULL_LAYER_RE = re.compile(
    r"pulling\s+(?P<digest>[0-9a-f]{6,})[^%\d]{0,8}(?P<pct>\d{1,3})\s*%"
)

# "245 MB/2.0 GB". Both sides must be byte units, which is what keeps the
# trailing speed field ("45 MB/s") from being read as a done/total pair.
_SIZE_PAIR_RE = re.compile(
    r"(?P<done>\d+(?:[.,]\d+)?)\s*(?P<du>TB|GB|MB|KB|B)\s*/\s*"
    r"(?P<total>\d+(?:[.,]\d+)?)\s*(?P<tu>TB|GB|MB|KB|B)(?![/\w])"
)

# The completed form drops the pair and prints the total alone: "... 2.0 GB".
_SIZE_ONE_RE = re.compile(r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>TB|GB|MB|KB|B)(?![/\w])")


def _to_bytes(value: str, unit: str) -> float:
    return float(value.replace(",", ".")) * _UNIT_BYTES[unit]


def format_bytes(size: float) -> str:
    """Human size in the same pt-BR decimal-comma style as
    ollama_install.estimate_model_size_text ("~2,0 GB de download")."""
    for unit in ("TB", "GB", "MB", "KB"):
        scale = _UNIT_BYTES[unit]
        if size >= scale:
            return f"{size / scale:.1f}".replace(".", ",") + f" {unit}"
    return f"{int(size)} B"


def expected_model_bytes(model: str) -> Optional[float]:
    """Tamanho de download do modelo pela tabela do wizard, ou `None` — nunca
    adivinha, e sem denominador tudo a jusante degrada para progresso por
    fase em vez de inventar um número.
    """
    sizes = KNOWN_MODEL_SIZES.get(model.strip())
    if sizes is None:
        return None
    return sizes[0] * _UNIT_BYTES["GB"]


@dataclass(frozen=True)
class Phase:
    key: str
    label: str
    weight: float


def plan_phases(
    *,
    want_llm: bool,
    llm_mode: str,
    model: str,
    writes_config: bool,
) -> tuple[Phase, ...]:
    """Os passos que esta instalação vai rodar, decididos de antemão;
    `writes_config` é separado de `want_llm` porque a senha é escrita em toda
    instalação que define ou remove uma: `REGISTRO`, "Texto movido do código".
    """
    keys = [PHASE_VENV, PHASE_PIP]
    if want_llm and llm_mode == "local":
        keys += [PHASE_OLLAMA, PHASE_MODEL]
    if want_llm or writes_config:
        keys.append(PHASE_CONFIG)

    labels = {
        PHASE_VENV: "Criando o ambiente virtual (venv)",
        PHASE_PIP: "Instalando o ai-ethical-agent e suas dependências",
        PHASE_OLLAMA: "Instalando o Ollama",
        PHASE_MODEL: f"Baixando o modelo {model}",
        PHASE_CONFIG: "Gravando a configuração",
    }
    total = sum(_WEIGHTS[key] for key in keys)
    return tuple(
        Phase(key=key, label=labels[key], weight=_WEIGHTS[key] * 100.0 / total)
        for key in keys
    )


class ProgressTracker:
    """Monotonic overall percentage plus the label of the current phase."""

    def __init__(self, phases: tuple[Phase, ...]) -> None:
        self.phases = tuple(phases)
        self._index = {phase.key: i for i, phase in enumerate(self.phases)}
        self._offsets: list[float] = []
        running = 0.0
        for phase in self.phases:
            self._offsets.append(running)
            running += phase.weight
        self._current: Optional[int] = None
        self._detail = ""
        self._percent = 0.0
        self._done = False

    # -- updates -----------------------------------------------------------

    def start(self, key: str) -> None:
        index = self._index.get(key)
        if index is None:
            return
        self._current = index
        self._detail = ""
        self._bump(self._offsets[index])

    def set_fraction(self, fraction: float) -> None:
        """Progress *within* the current phase, 0..1. Ignored when no phase is
        running, so a stray update can never invent one."""
        if self._current is None:
            return
        fraction = min(max(fraction, 0.0), 1.0)
        phase = self.phases[self._current]
        self._bump(self._offsets[self._current] + phase.weight * fraction)

    def set_detail(self, detail: str) -> None:
        self._detail = detail

    def finish(self, key: str) -> None:
        """Completes `key`, whether it ran or was skipped ("já instalado")."""
        index = self._index.get(key)
        if index is None:
            return
        if self._current == index:
            self._detail = ""
        self._bump(self._offsets[index] + self.phases[index].weight)

    def complete(self) -> None:
        self._done = True
        self._detail = ""
        self._bump(100.0)

    def _bump(self, value: float) -> None:
        self._percent = max(self._percent, min(value, 100.0))

    # -- what the widgets read ---------------------------------------------

    @property
    def percent(self) -> float:
        return self._percent

    @property
    def label(self) -> str:
        if self._done:
            return "Concluído."
        if self._current is None:
            return f"Preparando... (0 de {len(self.phases)} etapas)"
        phase = self.phases[self._current]
        text = f"Etapa {self._current + 1} de {len(self.phases)} -- {phase.label}"
        if self._detail:
            text += f" -- {self._detail}"
        return text


class PullProgress:
    """Transforma a saída do `ollama pull` numa fração somando bytes por camada,
    porque ler a porcentagem por camada direto é o caminho óbvio e errado:
    `REGISTRO`, "Texto movido do código".
    """

    def __init__(self, model: str) -> None:
        self._expected = expected_model_bytes(model)
        self._layers: dict[str, tuple[float, float]] = {}

    def update(self, chunk: str) -> tuple[Optional[float], Optional[str]]:
        """Consome um chunk e devolve (fração, detalhe), qualquer um podendo ser
        `None` quando a linha não carrega número ou o modelo não tem
        denominador confiável: `REGISTRO`, "Texto movido do código".
        """
        match = _PULL_LAYER_RE.search(chunk)
        if match is None:
            return None, None
        digest = match.group("digest")
        pct = min(int(match.group("pct")), 100) / 100.0

        done, total = self._sizes(chunk[match.end() :], pct)
        if total is None:
            return None, None

        # Never let a layer's counters go backwards (a \r refresh arriving out
        # of order, a restarted layer): the sum below relies on it.
        previous = self._layers.get(digest)
        if previous is not None:
            done = max(done, previous[0])
            total = max(total, previous[1])
        self._layers[digest] = (done, total)

        done_sum = sum(d for d, _ in self._layers.values())
        total_sum = sum(t for _, t in self._layers.values())
        detail = f"{format_bytes(done_sum)} de {format_bytes(max(total_sum, self._expected or 0))}"
        if self._expected is None:
            return None, detail
        # max(): layers are announced as the pull walks them, so the sum only
        # becomes the real total near the end -- until then the table's figure
        # is the better denominator, and after that the sum is.
        return done_sum / max(total_sum, self._expected), detail

    def _sizes(self, tail: str, pct: float) -> tuple[float, Optional[float]]:
        pair = _SIZE_PAIR_RE.search(tail)
        if pair is not None:
            return (
                _to_bytes(pair.group("done"), pair.group("du")),
                _to_bytes(pair.group("total"), pair.group("tu")),
            )
        # A finished layer prints its total alone ("100% ... 2.0 GB"). The
        # percentage is what says how much of it is already down.
        one = _SIZE_ONE_RE.search(tail)
        if one is not None:
            total = _to_bytes(one.group("value"), one.group("unit"))
            return total * pct, total
        return 0.0, None
