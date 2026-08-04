import io
import subprocess
from pathlib import Path

import pytest

from ethical_agent.ollama_install import (
    AUDIT_PASSWORD_ENV_VAR,
    DEFAULT_LOCAL_MODEL,
    InstallerPlan,
    _WIN_BREAKAWAY,
    _WIN_NEW_GROUP,
    _WIN_NO_WINDOW,
    audit_password_conflict,
    download_file,
    env_audit_password_present,
    estimate_model_size_text,
    find_ollama_exe,
    installer_plan_for_platform,
    iter_stream_chunks,
    model_already_pulled,
    start_ollama_server,
    read_env_var,
    remove_env_var,
    verify_windows_signature,
    wait_for_server,
    write_env_api_key,
    write_env_audit_password,
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


def test_read_env_var_returns_none_for_missing_file_key_or_empty_value(tmp_path):
    assert read_env_var(tmp_path, "ANYTHING") is None

    (tmp_path / ".env").write_text(
        "OTHER_VAR=keep\nBLANK=\nBLANK_SPACES=   \n", encoding="utf-8"
    )
    assert read_env_var(tmp_path, "MISSING") is None
    # Present but empty is "not configured" -- the audit-password loader
    # depends on this, so an empty key never enables a screen with a blank
    # password.
    assert read_env_var(tmp_path, "BLANK") is None
    assert read_env_var(tmp_path, "BLANK_SPACES") is None
    assert read_env_var(tmp_path, "OTHER_VAR") == "keep"


def test_read_env_var_keeps_everything_after_the_first_equals(tmp_path):
    # A password is not a tidy identifier: "=" and "#" are ordinary
    # characters in one, and neither may truncate the value.
    (tmp_path / ".env").write_text(
        "ETHICAL_AGENT_AUDIT_PASSWORD=a=b#c d\n", encoding="utf-8"
    )
    assert read_env_var(tmp_path, "ETHICAL_AGENT_AUDIT_PASSWORD") == "a=b#c d"


def test_write_env_audit_password_strips_so_write_and_read_agree(tmp_path):
    # Stored with surrounding spaces, the reader would strip them and the
    # login check would compare two different strings forever.
    write_env_audit_password(tmp_path, "  senha  ")
    assert (tmp_path / ".env").read_text(encoding="utf-8") == (
        "ETHICAL_AGENT_AUDIT_PASSWORD=senha\n"
    )
    assert read_env_var(tmp_path, "ETHICAL_AGENT_AUDIT_PASSWORD") == "senha"


def test_remove_env_var_drops_only_its_own_line(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OLLAMA_MODEL=llama3.2:3b\n"
        "ETHICAL_AGENT_AUDIT_PASSWORD=segredo\n"
        "OLLAMA_API_KEY=abc123\n",
        encoding="utf-8",
    )

    assert remove_env_var(tmp_path, "ETHICAL_AGENT_AUDIT_PASSWORD") == env_path

    content = env_path.read_text(encoding="utf-8")
    assert "ETHICAL_AGENT_AUDIT_PASSWORD" not in content
    assert "OLLAMA_MODEL=llama3.2:3b" in content
    assert "OLLAMA_API_KEY=abc123" in content


def test_remove_env_var_reports_when_there_was_nothing_to_remove(tmp_path):
    # None means "no change", which is what lets the wizard stay quiet in the
    # progress log instead of claiming it removed something.
    assert remove_env_var(tmp_path, "ETHICAL_AGENT_AUDIT_PASSWORD") is None

    (tmp_path / ".env").write_text("OLLAMA_MODEL=llama3.2:3b\n", encoding="utf-8")
    assert remove_env_var(tmp_path, "ETHICAL_AGENT_AUDIT_PASSWORD") is None
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "OLLAMA_MODEL=llama3.2:3b\n"


def test_remove_env_var_on_the_only_line_leaves_a_valid_empty_file(tmp_path):
    (tmp_path / ".env").write_text("ETHICAL_AGENT_AUDIT_PASSWORD=segredo\n", encoding="utf-8")
    remove_env_var(tmp_path, "ETHICAL_AGENT_AUDIT_PASSWORD")
    assert (tmp_path / ".env").read_text(encoding="utf-8") == ""
    assert read_env_var(tmp_path, "ETHICAL_AGENT_AUDIT_PASSWORD") is None


# Uma fonte ambiente só, e o arame de tropeço na que morreu: `.env` é a única
# fonte, e a variável é lida apenas para notar que alguém ainda a tem setada.
# CLI e instalador têm de responder igual, e o instalador não pode importar
# `webui/auth`, então o predicado e o texto moram aqui: `REGISTRO`, "Texto movido do código".


def _dotenv_with_password(root, value="do-dotenv"):
    (root / ".env").write_text(
        f"OLLAMA_MODEL=llama3.2:3b\n{AUDIT_PASSWORD_ENV_VAR}={value}\n", encoding="utf-8"
    )
    return root


def test_no_exported_variable_means_nothing_to_report(tmp_path):
    assert audit_password_conflict(tmp_path, {}) is None
    assert audit_password_conflict(_dotenv_with_password(tmp_path), {}) is None


def test_a_variable_repeating_the_dotenv_password_is_not_a_problem(tmp_path):
    # Nada é ambíguo quando os dois nomes têm a mesma string, e `load_dotenv()`
    # copia o `.env` para o ambiente — é estado que o processo alcança sozinho: `REGISTRO`, "Texto movido do código".
    _dotenv_with_password(tmp_path, "a-mesma")
    assert audit_password_conflict(tmp_path, {AUDIT_PASSWORD_ENV_VAR: "a-mesma"}) is None
    # Whitespace is stripped on both sides, as it is on write and on read.
    assert audit_password_conflict(tmp_path, {AUDIT_PASSWORD_ENV_VAR: "  a-mesma  "}) is None


def test_a_variable_that_disagrees_with_the_dotenv_password_is_refused(tmp_path):
    _dotenv_with_password(tmp_path, "do-dotenv")
    assert audit_password_conflict(tmp_path, {AUDIT_PASSWORD_ENV_VAR: "outra"}) is not None


def test_a_variable_with_no_dotenv_password_is_refused_rather_than_ignored(tmp_path):
    # O caso que funcionava: a variável sozinha era fonte. Agora nada estaria em
    # vigor, e quem a setou perderia a tela sem ser avisado: `REGISTRO`, "Texto movido do código".
    assert audit_password_conflict(tmp_path, {AUDIT_PASSWORD_ENV_VAR: "do-ambiente"}) is not None

    (tmp_path / ".env").write_text("OLLAMA_MODEL=llama3.2:3b\n", encoding="utf-8")
    assert audit_password_conflict(tmp_path, {AUDIT_PASSWORD_ENV_VAR: "do-ambiente"}) is not None


def test_a_source_that_is_defined_but_empty_is_not_a_source(tmp_path):
    # "Defined" has to mean the same thing on both sides. read_env_var already
    # treats `KEY=` as absent; the variable is measured the same way, so an
    # exported-but-empty name is silence rather than a claim.
    (tmp_path / ".env").write_text(f"{AUDIT_PASSWORD_ENV_VAR}=\n", encoding="utf-8")
    # Empty .env key + a real variable: nothing in effect, so it is refused.
    assert audit_password_conflict(tmp_path, {AUDIT_PASSWORD_ENV_VAR: "do-ambiente"}) is not None

    _dotenv_with_password(tmp_path)
    assert audit_password_conflict(tmp_path, {AUDIT_PASSWORD_ENV_VAR: "   "}) is None
    assert env_audit_password_present({AUDIT_PASSWORD_ENV_VAR: "   "}) is False
    assert env_audit_password_present({AUDIT_PASSWORD_ENV_VAR: "x"}) is True
    assert env_audit_password_present({}) is False


def test_the_password_file_flag_silences_the_tripwire(tmp_path):
    # A exceção mora no predicado e não em cada chamador, senão os dois divergem
    # na *exceção* parecendo compartilhar a regra: `REGISTRO`, "Texto movido do código".
    _dotenv_with_password(tmp_path)
    env = {AUDIT_PASSWORD_ENV_VAR: "outra"}

    assert audit_password_conflict(tmp_path, env) is not None
    assert audit_password_conflict(tmp_path, env, password_file="/tmp/senha.txt") is None


def test_both_messages_name_the_variable_the_path_and_removing_it(tmp_path):
    # Dois estados, duas mensagens, e ambas nomeiam *a* correção em vez de
    # oferecer escolha: `REGISTRO`, "Texto movido do código".
    _dotenv_with_password(tmp_path)
    divergente = audit_password_conflict(tmp_path, {AUDIT_PASSWORD_ENV_VAR: "outra"})

    vazio = tmp_path / "sem-dotenv"
    vazio.mkdir()
    sem_senha = audit_password_conflict(vazio, {AUDIT_PASSWORD_ENV_VAR: "outra"})

    assert divergente != sem_senha, "os dois estados não são a mesma notícia"
    for message in (divergente, sem_senha):
        assert f"${AUDIT_PASSWORD_ENV_VAR}" in message
        assert "apague a variável" in message.lower()
        assert "--audit-password-file" in message
    assert str((tmp_path / ".env").resolve()) in divergente
    assert str((vazio / ".env").resolve()) in sem_senha


def test_no_message_ever_reveals_or_compares_a_value(tmp_path):
    # The most likely place in the codebase to leak a password: the only text
    # that has to talk about two of them at once. It may say that they differ;
    # it may not say how, and it may not quote either one.
    _dotenv_with_password(tmp_path, "SENHA-CANARIO-DOTENV")
    env = {AUDIT_PASSWORD_ENV_VAR: "SENHA-CANARIO-VARIAVEL"}

    vazio = tmp_path / "sem-dotenv"
    vazio.mkdir()
    textos = [
        audit_password_conflict(tmp_path, env),
        audit_password_conflict(vazio, env),
    ]
    for message in textos:
        assert message is not None
        assert "SENHA-CANARIO-DOTENV" not in message
        assert "SENHA-CANARIO-VARIAVEL" not in message





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


class _RecordingPopen:
    """Substitui `subprocess.Popen` registrando toda tentativa de lançamento;
    `fail_first` reproduz o job cuja política proíbe
    `CREATE_BREAKAWAY_FROM_JOB`: `REGISTRO`, "Texto movido do código".
    """

    def __init__(self, fail_first: int = 0):
        self.calls: list[tuple[list[str], dict]] = []
        self._fail_first = fail_first

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if len(self.calls) <= self._fail_first:
            raise OSError("breakaway not permitted")
        return self


def test_start_ollama_server_runs_serve_detached_without_a_console():
    popen = _RecordingPopen()

    exe = Path("C:/ollama.exe")
    proc = start_ollama_server(exe, popen=popen, platform="win32")

    assert proc is popen
    cmd, kwargs = popen.calls[0]
    assert cmd == [str(exe), "serve"]
    # DEVNULL, not PIPE: nobody reads these, and a filled pipe buffer would
    # wedge the server the wizard just started.
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert "creationflags" in kwargs


def test_start_ollama_server_retries_without_breakaway_flag_on_oserror():
    popen = _RecordingPopen(fail_first=1)

    proc = start_ollama_server(Path("C:/ollama.exe"), popen=popen, platform="win32")

    assert proc is popen
    assert len(popen.calls) == 2
    first_flags = popen.calls[0][1]["creationflags"]
    second_flags = popen.calls[1][1]["creationflags"]
    # Compared against the module's constants rather than subprocess's, which
    # only define these on Windows -- this test drives the win32 branch with
    # an injected platform and must pass everywhere.
    assert first_flags == _WIN_NEW_GROUP | _WIN_NO_WINDOW | _WIN_BREAKAWAY
    assert second_flags == _WIN_NEW_GROUP | _WIN_NO_WINDOW


def test_start_ollama_server_returns_none_when_every_attempt_fails():
    popen = _RecordingPopen(fail_first=2)

    assert start_ollama_server(Path("C:/ollama.exe"), popen=popen, platform="win32") is None
    assert len(popen.calls) == 2


def test_start_ollama_server_uses_a_new_session_on_posix():
    popen = _RecordingPopen()

    exe = Path("/usr/local/bin/ollama")
    proc = start_ollama_server(exe, popen=popen, platform="linux")

    assert proc is popen
    cmd, kwargs = popen.calls[0]
    assert cmd == [str(exe), "serve"]
    assert kwargs["start_new_session"] is True
    assert "creationflags" not in kwargs


def test_start_ollama_server_returns_none_on_posix_failure():
    popen = _RecordingPopen(fail_first=1)

    assert start_ollama_server(Path("/usr/local/bin/ollama"), popen=popen, platform="linux") is None
    assert len(popen.calls) == 1


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
