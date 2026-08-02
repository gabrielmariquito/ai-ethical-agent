from __future__ import annotations

from typing import Callable, List

from ethical_agent import LLMClient


class ProgressReportingLLM(LLMClient):
    """Wraps another LLMClient purely to report phase transitions for the
    chat job's polling status: generation is in flight until .chat() returns,
    then the guardrail is verifying the output. Delegates every call
    unchanged and never inspects or alters messages/response -- it observes
    the boundary GuardedAgent(llm=...) already exposes by dependency
    injection, it does not duplicate any branch of GuardedAgent.process()
    (DENY/REWRITE/etc), so it cannot affect what gets decided.
    """

    def __init__(self, inner: LLMClient, on_phase: Callable[[str], None]):
        self._inner = inner
        self._on_phase = on_phase

    def chat(self, messages: List[dict]) -> str:
        response = self._inner.chat(messages)
        self._on_phase("verifying")
        return response
