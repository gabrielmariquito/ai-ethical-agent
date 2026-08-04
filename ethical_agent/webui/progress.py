from __future__ import annotations

from typing import Callable, List

from ethical_agent import LLMClient


class ProgressReportingLLM(LLMClient):
    """Envolve outro `LLMClient` só para reportar transição de fase, sem tocar
    no conteúdo.
    """

    def __init__(self, inner: LLMClient, on_phase: Callable[[str], None]):
        self._inner = inner
        self._on_phase = on_phase

    def chat(self, messages: List[dict]) -> str:
        response = self._inner.chat(messages)
        self._on_phase("verifying")
        return response
