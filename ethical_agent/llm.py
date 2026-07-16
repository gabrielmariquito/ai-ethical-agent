from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Callable, List, Optional, Sequence, Union


class LLMClient(ABC):
    @abstractmethod
    def chat(self, messages: List[dict]) -> str:
        ...


class MockLLM(LLMClient):
    def __init__(
        self,
        responses: Union[Sequence[str], Callable[[List[dict]], str], None] = None,
        default: str = "[mock response]",
    ):
        self._queue = list(responses) if isinstance(responses, (list, tuple)) else None
        self._fn = responses if callable(responses) else None
        self.default = default
        self.calls: List[List[dict]] = []

    def chat(self, messages: List[dict]) -> str:
        self.calls.append(messages)
        if self._fn is not None:
            return self._fn(messages)
        if self._queue:
            return self._queue.pop(0)
        return self.default


class OllamaClient(LLMClient):
    def __init__(
        self,
        model: str = "gpt-oss:120b",
        host: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        try:
            from ollama import Client
        except ImportError as exc:
            raise RuntimeError(
                "the 'ollama' package is required for OllamaClient "
                "(pip install ollama)"
            ) from exc

        self.model = model
        api_key = api_key or os.environ.get("OLLAMA_API_KEY")
        host = host or os.environ.get("OLLAMA_HOST") or (
            "https://ollama.com" if api_key else "http://localhost:11434"
        )
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        self._client = Client(host=host, headers=headers)

    def chat(self, messages: List[dict]) -> str:
        response = self._client.chat(self.model, messages=messages)
        return response.message.content or ""
