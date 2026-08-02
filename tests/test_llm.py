import pytest

from ethical_agent import llm as llm_module
from ethical_agent.llm import MockLLM, OllamaClient, describe_llm_provenance, resolve_llm


@pytest.fixture(autouse=True)
def _no_ollama_env(monkeypatch):
    # OllamaClient.__init__ calls load_dotenv(), which would otherwise pick
    # up the repo's own .env (OLLAMA_MODEL=... only, no key/host today) --
    # clear explicitly so these tests don't depend on that file's contents.
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)


def test_ollama_client_backend_is_local_without_api_key():
    client = OllamaClient(model="llama3.2:3b")
    assert client.backend == "ollama_local"


def test_ollama_client_backend_is_cloud_with_api_key():
    client = OllamaClient(model="llama3.2:3b", api_key="sk-test")
    assert client.backend == "ollama_cloud"


def test_resolve_llm_mock_requested():
    llm, provenance = resolve_llm("llama3.2:3b", mock=True)
    assert isinstance(llm, MockLLM)
    assert provenance == {"kind": "mock_requested"}


def test_resolve_llm_real(monkeypatch):
    class _FakeOllamaClient:
        def __init__(self, model):
            self.model = model
            self.backend = "ollama_local"

        def chat(self, messages):
            return "pong"

    monkeypatch.setattr(llm_module, "OllamaClient", _FakeOllamaClient)
    llm, provenance = resolve_llm("llama3.2:3b", mock=False)
    assert isinstance(llm, _FakeOllamaClient)
    assert provenance == {
        "kind": "real",
        "model": "llama3.2:3b",
        "backend": "ollama_local",
    }


def test_resolve_llm_mock_fallback_on_failure(monkeypatch):
    class _BrokenOllamaClient:
        def __init__(self, model):
            raise ConnectionError("no server")

    monkeypatch.setattr(llm_module, "OllamaClient", _BrokenOllamaClient)
    llm, provenance = resolve_llm("llama3.2:3b", mock=False)
    assert isinstance(llm, MockLLM)
    assert provenance["kind"] == "mock_fallback"
    assert "ConnectionError" in provenance["fallback_reason"]
    assert "no server" in provenance["fallback_reason"]


def test_describe_llm_provenance_covers_all_kinds():
    assert "llama3.2:3b" in describe_llm_provenance(
        {"kind": "real", "model": "llama3.2:3b", "backend": "ollama_local"}
    )
    assert "mock requested" in describe_llm_provenance({"kind": "mock_requested"})
    text = describe_llm_provenance(
        {"kind": "mock_fallback", "fallback_reason": "ConnectionError: boom"}
    )
    assert "ConnectionError: boom" in text
