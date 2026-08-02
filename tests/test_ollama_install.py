import io
import subprocess
from pathlib import Path

import pytest

from ethical_agent.ollama_install import (
    DEFAULT_LOCAL_MODEL,
    InstallerPlan,
    download_file,
    estimate_model_size_text,
    find_ollama_exe,
    installer_plan_for_platform,
    iter_stream_chunks,
    model_already_pulled,
    verify_windows_signature,
    wait_for_server,
    write_env_api_key,
)


def test_estimate_model_size_text_known_model_shows_size_and_ram():
    text = estimate_model_size_text(DEFAULT_LOCAL_MODEL)
    assert "2,0 GB" in text
    assert "8 GB" in text


def test_estimate_model_size_text_unknown_model_points_to_library_page():
    text = estimate_model_size_text("some-custom-model:latest")
    assert "some-custom-model:latest" in text
    assert "ollama.com/library" in text
    assert "GB" not in text  # never invent a number


def test_find_ollama_exe_prefers_which_result():
    result = find_ollama_exe(which=lambda name: "/usr/local/bin/ollama")
    assert result == Path("/usr/local/bin/ollama")


def test_find_ollama_exe_falls_back_to_known_windows_path(monkeypatch, tmp_path):
    monkeypatch.setattr("ethical_agent.ollama_install.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    candidate = tmp_path / "Programs" / "Ollama" / "ollama.exe"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("stub")

    result = find_ollama_exe(which=lambda name: None)
    assert result == candidate


def test_find_ollama_exe_returns_none_when_nothing_found(monkeypatch, tmp_path):
    monkeypatch.setattr("ethical_agent.ollama_install.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert find_ollama_exe(which=lambda name: None) is None


@pytest.mark.parametrize(
    "platform, expected_kind",
    [("win32", "download_exe"), ("linux", "shell_script")],
)
def test_installer_plan_for_platform_known_platforms(platform, expected_kind):
    plan = installer_plan_for_platform(platform)
    assert isinstance(plan, InstallerPlan)
    assert plan.kind == expected_kind
    assert plan.source_url.startswith("https://ollama.com/")


def test_installer_plan_for_platform_macos_has_no_automated_install():
    assert installer_plan_for_platform("darwin") is None


def test_iter_stream_chunks_splits_on_newline_and_carriage_return():
    stream = io.StringIO("hello\rworld\nlast")
    assert list(iter_stream_chunks(stream)) == ["hello", "world", "last"]


def test_iter_stream_chunks_ignores_empty_segments():
    stream = io.StringIO("a\r\rb\n\nc")
    assert list(iter_stream_chunks(stream)) == ["a", "b", "c"]


def test_model_already_pulled_true_when_model_listed():
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="NAME\tID\tSIZE\nllama3.1:8b\tabc123\t4.7 GB\n",
        )

    assert model_already_pulled(Path("ollama"), "llama3.1:8b", run=fake_run) is True


def test_model_already_pulled_false_when_model_absent():
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="NAME\tID\tSIZE\nmistral:7b\txyz\t4.1 GB\n"
        )

    assert model_already_pulled(Path("ollama"), "llama3.1:8b", run=fake_run) is False


def test_model_already_pulled_false_on_error():
    def fake_run(*args, **kwargs):
        raise OSError("not found")

    assert model_already_pulled(Path("ollama"), "llama3.1:8b", run=fake_run) is False


def test_model_already_pulled_matches_ignoring_latest_suffix():
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="NAME\tID\tSIZE\nllama3.1:8b:latest\tabc\t4.7 GB\n"
        )

    assert model_already_pulled(Path("ollama"), "llama3.1:8b", run=fake_run) is True


def test_write_env_api_key_creates_new_file(tmp_path):
    path = write_env_api_key(tmp_path, "abc123")
    assert path == tmp_path / ".env"
    assert path.read_text(encoding="utf-8") == "OLLAMA_API_KEY=abc123\n"


def test_write_env_api_key_replaces_existing_key_without_duplicating(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OTHER_VAR=keep\nOLLAMA_API_KEY=old\n", encoding="utf-8")

    write_env_api_key(tmp_path, "new-key")

    content = env_path.read_text(encoding="utf-8")
    assert content.count("OLLAMA_API_KEY=") == 1
    assert "OLLAMA_API_KEY=new-key" in content
    assert "OTHER_VAR=keep" in content


def test_verify_windows_signature_valid():
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="Valid\r\n")

    assert verify_windows_signature(Path("C:/tmp/OllamaSetup.exe"), run=fake_run) is True


def test_verify_windows_signature_invalid_status():
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="NotSigned\r\n")

    assert verify_windows_signature(Path("C:/tmp/OllamaSetup.exe"), run=fake_run) is False


def test_verify_windows_signature_false_on_exception():
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("powershell missing")

    assert verify_windows_signature(Path("C:/tmp/OllamaSetup.exe"), run=fake_run) is False


def test_wait_for_server_succeeds_immediately():
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    assert wait_for_server(urlopen=lambda url, timeout=2: _Resp(), poll=0.01, timeout=1) is True


def test_wait_for_server_times_out_when_unreachable():
    def always_fails(url, timeout=2):
        raise OSError("connection refused")

    assert wait_for_server(urlopen=always_fails, poll=0.01, timeout=0.05) is False


def test_download_file_writes_content_and_reports_progress(tmp_path, monkeypatch):
    payload = b"x" * 10

    class _FakeResponse:
        headers = {"Content-Length": str(len(payload))}

        def __init__(self):
            self._remaining = payload

        def read(self, chunk_size):
            chunk, self._remaining = self._remaining[:chunk_size], self._remaining[chunk_size:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        "ethical_agent.ollama_install.urllib.request.urlopen",
        lambda url: _FakeResponse(),
    )

    progress_calls = []
    dest = tmp_path / "sub" / "file.bin"
    download_file(
        "https://example.invalid/file.bin",
        dest,
        on_progress=lambda done, total: progress_calls.append((done, total)),
        chunk_size=4,
    )

    assert dest.read_bytes() == payload
    assert progress_calls[-1] == (10, 10)
