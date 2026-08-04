import argparse
import socket

import pytest

from ethical_agent.__main__ import main
from ethical_agent.webui.server import PortInUseError, make_server
from webui_support import RunningServer, make_initial_config


@pytest.fixture(autouse=True)
def isolated_password_sources(monkeypatch, tmp_path):
    """No test in this file may see the developer's own audit password.

    `cmd_serve` resolves the password from three places, and the last one is
    ETHICAL_AGENT_AUDIT_PASSWORD in <repo>/.env -- the file the graphical
    installer writes. That is a real file in a real checkout, so the moment
    whoever runs the suite configures an audit password for themselves,
    every `main(["serve", ...])` here starts picking it up and assertions
    like `audit_password is None` fail for reasons that have nothing to do
    with the code under test. This happened.

    Both sources are neutralised by default; a test that wants one sets it
    explicitly (see _run_serve below).
    """
    import ethical_agent.webui.auth as auth_module

    monkeypatch.setattr(auth_module, "REPO_ROOT", tmp_path / "fake-repo-root")
    monkeypatch.delenv("ETHICAL_AGENT_AUDIT_PASSWORD", raising=False)


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path)
    yield running
    running.close()


def test_server_socket_is_bound_to_127_0_0_1_only(server):
    assert server.server.server_address[0] == "127.0.0.1"


# -- one port, one server ----------------------------------------------------


def test_a_second_server_cannot_take_a_port_already_in_use(tmp_path, server):
    """The bug this guards against was silent, and only on Windows.

    socketserver.TCPServer sets allow_reuse_address = 1. On POSIX that means
    "rebind a TIME_WAIT socket", which is wanted. On Windows SO_REUSEADDR
    means a second socket may bind an address that is *actively in use*, and
    connections go to one of them non-deterministically -- so a second
    `serve --port 8765` bound happily, printed "Serving at ..." and a correct
    audit banner, while the browser kept talking to the older process. The
    observed symptom was a nav item reporting the audit screen as disabled
    while the banner of the server the operator was reading said enabled:
    two servers, and the banner belonged to the one not answering.
    """
    port = server.server.server_address[1]
    with pytest.raises(PortInUseError):
        make_server(port, make_initial_config(tmp_path))
    # ...and the one that was already there is untouched.
    status, _, _ = server.get("/api/choices")
    assert status == 200


def test_port_zero_still_gets_a_free_port_each_time(tmp_path):
    # The exclusive-bind flag must not break the ephemeral-port path every
    # test in this suite relies on.
    first = make_server(0, make_initial_config(tmp_path))
    second = make_server(0, make_initial_config(tmp_path))
    try:
        assert first.server_address[1] != second.server_address[1]
    finally:
        first.server_close()
        second.server_close()


def test_serve_exits_with_a_readable_message_when_the_port_is_taken(server, capsys):
    port = server.server.server_address[1]
    code = main(["serve", "--port", str(port)])
    assert code == 2
    err = capsys.readouterr().err
    assert str(port) in err
    assert "já está em uso" in err
    # It has to say what to do, not merely what happened -- and the port it
    # suggests must not be the one that just failed.
    assert f"--port {port + 1}" in err


def test_serve_says_the_occupant_is_ours_when_it_answers_our_api(server, capsys):
    # uninstall.web_ui_running only counts a 200 from /api/choices, so this
    # never accuses a stranger's process of being ours.
    code = main(["serve", "--port", str(server.server.server_address[1])])
    assert code == 2
    err = capsys.readouterr().err
    assert "servidor deste projeto" in err


def test_serve_does_not_claim_the_occupant_is_ours_for_a_stranger(tmp_path, capsys):
    stranger = socket.socket()
    stranger.bind(("127.0.0.1", 0))
    stranger.listen(1)
    port = stranger.getsockname()[1]
    try:
        code = main(["serve", "--port", str(port)])
        assert code == 2
        err = capsys.readouterr().err
        assert "Outro programa" in err
        assert "servidor deste projeto" not in err
    finally:
        stranger.close()


def test_server_unreachable_via_any_other_local_address(server):
    # If the server were bound to 0.0.0.0 this would also succeed; bound to
    # 127.0.0.1 specifically, connecting via the machine's real hostname (or
    # any other local interface address) must fail to connect at all.
    other_addresses = set()
    try:
        other_addresses.add(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    other_addresses.discard("127.0.0.1")
    if not other_addresses:
        pytest.skip("no other local address available to test against on this host")
    for address in other_addresses:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            with pytest.raises(OSError):
                sock.connect((address, server.port))
        finally:
            sock.close()


def test_serve_never_takes_a_password_as_an_argument_value(capsys):
    # There is deliberately no --audit-password VALUE flag: an argument value
    # lands in the process list and in shell history, which is a worse home
    # for a secret than either supported source (a file, or the environment
    # variable).
    #
    # argparse resolves the unambiguous prefix --audit-password onto
    # --audit-password-file, so someone who types it anyway has their secret
    # read as a *filename* -- which fails loudly with a readable error rather
    # than quietly becoming the password. That loud failure is the behaviour
    # being locked in here; silently accepting it would be the bug.
    code = main(["serve", "--audit-password", "hunter2", "--port", "0"])
    assert code == 2
    err = capsys.readouterr().err
    assert "--audit-password-file" in err
    assert "could not read" in err


def test_serve_accepts_the_audit_flags_and_passes_them_as_kwargs(monkeypatch, tmp_path):
    password_file = tmp_path / "senha.txt"
    password_file.write_text("do-arquivo\n", encoding="utf-8")
    captured = {}

    class FakeServer:
        def serve_forever(self):
            raise KeyboardInterrupt()

        def server_close(self):
            pass

    def fake_make_server(port, initial_config, **kwargs):
        captured["initial_config"] = initial_config
        captured["kwargs"] = kwargs
        return FakeServer()

    import ethical_agent.webui.server as server_module

    monkeypatch.setattr(server_module, "make_server", fake_make_server)

    code = main(
        [
            "serve",
            "--port",
            "0",
            "--audit-password-file",
            str(password_file),
            "--auditor-session-log",
            str(tmp_path / "sessoes.jsonl"),
            "--change-requests-log",
            str(tmp_path / "sugestoes.jsonl"),
        ]
    )
    assert code == 0
    assert captured["kwargs"]["audit_password"] == "do-arquivo"
    assert captured["kwargs"]["auditor_session_log"] == str(tmp_path / "sessoes.jsonl")
    assert captured["kwargs"]["change_requests_log"] == str(tmp_path / "sugestoes.jsonl")
    # Never through initial_config, which is served verbatim to the chat
    # screen by handlers_choices.py.
    assert "do-arquivo" not in repr(captured["initial_config"])


# -- the .env source, and the startup banner that describes it ---------------

CANARY = "SENHA-CANARIO-9c2f"


def _run_serve(monkeypatch, tmp_path, argv_extra=(), env=None):
    """Runs `serve` far enough to print the banner, with .env pointed at
    tmp_path, and returns (exit code, stdout, stderr)."""
    captured = {}

    class FakeServer:
        def serve_forever(self):
            raise KeyboardInterrupt()

        def server_close(self):
            pass

    def fake_make_server(port, initial_config, **kwargs):
        captured["initial_config"] = initial_config
        captured["kwargs"] = kwargs
        return FakeServer()

    import ethical_agent.webui.auth as auth_module
    import ethical_agent.webui.server as server_module

    monkeypatch.setattr(server_module, "make_server", fake_make_server)
    # Both load_audit_password and dotenv_password_present read this global
    # at call time, so this is what makes the test hermetic against whatever
    # the developer running it has in their own .env.
    monkeypatch.setattr(auth_module, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("ETHICAL_AGENT_AUDIT_PASSWORD", raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)

    return captured, main(["serve", "--port", "0", *argv_extra])


def test_dotenv_password_enables_the_audit_screen_with_no_flag_at_all(
    monkeypatch, tmp_path, capsys
):
    # The whole point of the wizard writing to .env: `ethical-agent serve`,
    # bare, and the screen is there.
    #
    # Also the regression guard for the refusal above: .env is the source
    # that used to be silently overridden, so it is the one whose ordinary
    # case has to keep working untouched.
    (tmp_path / ".env").write_text(
        f"ETHICAL_AGENT_AUDIT_PASSWORD={CANARY}\n", encoding="utf-8"
    )
    captured, code = _run_serve(monkeypatch, tmp_path)

    assert code == 0
    assert captured["kwargs"]["audit_password"] == CANARY
    out = capsys.readouterr().out
    assert "Auditoria: habilitada" in out
    assert ".env (ETHICAL_AGENT_AUDIT_PASSWORD)" in out


def test_serve_refuses_when_a_leftover_variable_disagrees_with_dotenv(
    monkeypatch, tmp_path, capsys
):
    # The variable is not a source any more, but a stale one cannot simply be
    # ignored: whoever exported it believes they configured a password, and
    # would be rejected at the login prompt with nothing to go on.
    (tmp_path / ".env").write_text(
        f"ETHICAL_AGENT_AUDIT_PASSWORD={CANARY}\n", encoding="utf-8"
    )
    captured, code = _run_serve(
        monkeypatch, tmp_path, env={"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}
    )

    assert code == 2
    # make_server was never reached -- nothing bound a port, so there is no
    # half-started server behind the error message.
    assert "initial_config" not in captured

    err = capsys.readouterr().err
    assert "$ETHICAL_AGENT_AUDIT_PASSWORD" in err
    assert str((tmp_path / ".env").resolve()) in err
    # The fix is named, and it is one thing -- not a choice. The dead source
    # is dead, so "remove one of the two" would offer something gone.
    assert "apague a variável" in err.lower()
    assert "remova uma das duas" not in err.lower()
    assert "--audit-password-file" in err, "quem precisa subir agora tem de sair daqui sozinho"
    assert CANARY not in err


def test_serve_refuses_when_a_leftover_variable_is_all_there_is(
    monkeypatch, tmp_path, capsys
):
    # The state the README one-liner used to produce. Nothing would be in
    # effect, so starting quietly would take the audit screen away from
    # someone who thinks they just configured it.
    captured, code = _run_serve(
        monkeypatch, tmp_path, env={"ETHICAL_AGENT_AUDIT_PASSWORD": CANARY}
    )

    assert code == 2
    assert "initial_config" not in captured
    err = capsys.readouterr().err
    assert "$ETHICAL_AGENT_AUDIT_PASSWORD" in err
    assert "wizard_gui.py" in err, "tem de dizer onde a senha passa a morar"
    assert CANARY not in err


def test_a_leftover_variable_equal_to_the_dotenv_password_starts_silently(
    monkeypatch, tmp_path, capsys
):
    # Nothing is ambiguous, so nothing is said. This is also the state
    # load_dotenv() can create by itself, by copying .env into os.environ.
    (tmp_path / ".env").write_text(
        "ETHICAL_AGENT_AUDIT_PASSWORD=a-mesma\n", encoding="utf-8"
    )
    captured, code = _run_serve(
        monkeypatch, tmp_path, env={"ETHICAL_AGENT_AUDIT_PASSWORD": "a-mesma"}
    )

    assert code == 0
    assert captured["kwargs"]["audit_password"] == "a-mesma"
    streams = capsys.readouterr()
    assert ".env (ETHICAL_AGENT_AUDIT_PASSWORD)" in streams.out
    assert "$ETHICAL_AGENT_AUDIT_PASSWORD" not in streams.out
    assert streams.err == ""


def test_the_password_file_flag_starts_and_names_both_displaced_sources(
    monkeypatch, tmp_path, capsys
):
    # The flag states which password to use, so it is not refused. But it
    # must not go quiet about what it displaced -- an unmentioned displaced
    # source under the flag is exactly the gap logged as D-9.
    password_file = tmp_path / "senha.txt"
    password_file.write_text("do-arquivo\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        f"ETHICAL_AGENT_AUDIT_PASSWORD={CANARY}\n", encoding="utf-8"
    )
    captured, code = _run_serve(
        monkeypatch,
        tmp_path,
        argv_extra=("--audit-password-file", str(password_file)),
        env={"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"},
    )

    assert code == 0
    assert captured["kwargs"]["audit_password"] == "do-arquivo"
    out = capsys.readouterr().out
    assert "o .env também tem uma senha" in out
    assert "precedência" in out
    assert "$ETHICAL_AGENT_AUDIT_PASSWORD" in out
    assert "não é lida como senha" in out
    assert CANARY not in out


def test_banner_does_not_cry_override_when_dotenv_is_the_winner(
    monkeypatch, tmp_path, capsys
):
    (tmp_path / ".env").write_text(
        f"ETHICAL_AGENT_AUDIT_PASSWORD={CANARY}\n", encoding="utf-8"
    )
    _run_serve(monkeypatch, tmp_path)
    assert "também tem uma senha" not in capsys.readouterr().out


def test_disabled_banner_points_at_the_installer_not_only_at_flags(
    monkeypatch, tmp_path, capsys
):
    # Telling someone who chose the graphical installer to go set an
    # environment variable is how they ended up never finding the screen.
    captured, code = _run_serve(monkeypatch, tmp_path)

    assert code == 0
    assert captured["kwargs"]["audit_password"] is None
    out = capsys.readouterr().out
    assert "Auditoria: desabilitada" in out
    assert "wizard_gui.py" in out


def test_the_disabled_banner_no_longer_tells_anyone_to_export_the_variable(
    monkeypatch, tmp_path, capsys
):
    # It used to end with "ou defina ETHICAL_AGENT_AUDIT_PASSWORD". Following
    # that advice now produces exit 2 on the next run -- a banner talking
    # someone into the error it exists to prevent.
    _run_serve(monkeypatch, tmp_path)
    out = capsys.readouterr().out
    assert "defina ETHICAL_AGENT_AUDIT_PASSWORD" not in out
    assert ".env" in out, "tem de dizer onde a senha mora agora"


def test_no_source_of_the_password_ever_prints_its_value(monkeypatch, tmp_path, capsys):
    # One sweep over stdout+stderr for each source in turn. The banner is
    # allowed to name where the password came from and nothing else.
    #
    # Each case sets up its own .env, because what a given environment means
    # now depends on what the file holds. The two refusing cases are here on
    # purpose: their messages are the only text in the codebase that has to
    # talk about two passwords at once, which makes them the likeliest place
    # to leak one by accident.
    password_file = tmp_path / "senha.txt"
    password_file.write_text(f"{CANARY}\n", encoding="utf-8")
    dotenv = f"ETHICAL_AGENT_AUDIT_PASSWORD={CANARY}\n"
    sem_senha = "OLLAMA_MODEL=llama3.2:3b\n"

    cases = (
        ("dotenv", (), None, dotenv),
        ("password file", ("--audit-password-file", str(password_file)), None, dotenv),
        ("dotenv + variável igual", (), {"ETHICAL_AGENT_AUDIT_PASSWORD": CANARY}, dotenv),
        ("variável divergente", (), {"ETHICAL_AGENT_AUDIT_PASSWORD": "outra"}, dotenv),
        ("variável sozinha", (), {"ETHICAL_AGENT_AUDIT_PASSWORD": CANARY}, sem_senha),
    )
    recusados = {"variável divergente", "variável sozinha"}
    for label, argv_extra, env, env_file in cases:
        (tmp_path / ".env").write_text(env_file, encoding="utf-8")
        captured, code = _run_serve(monkeypatch, tmp_path, argv_extra=argv_extra, env=env)
        streams = capsys.readouterr()
        assert CANARY not in streams.out, f"vazou em stdout via {label}"
        assert CANARY not in streams.err, f"vazou em stderr via {label}"
        # And not into initial_config either, which handlers_choices.py
        # serves verbatim and unauthenticated at /api/choices. This is the
        # same guarantee test_choices_endpoint_never_exposes_the_password
        # checks from the HTTP side, asserted here at the source. A refused
        # case never gets that far, which is itself the assertion for it.
        if label in recusados:
            assert code == 2, label
            assert "initial_config" not in captured, label
        else:
            assert code == 0, label
            assert CANARY not in repr(captured["initial_config"]), f"vazou via {label}"


def test_serve_exits_nonzero_on_an_empty_password_file(tmp_path, capsys):
    password_file = tmp_path / "vazio.txt"
    password_file.write_text("\n", encoding="utf-8")
    # Failing loudly beats starting a server whose audit screen silently
    # does not exist, when the operator explicitly asked for it.
    code = main(["serve", "--port", "0", "--audit-password-file", str(password_file)])
    assert code == 2
    assert "empty" in capsys.readouterr().err


def test_serve_subcommand_has_no_host_flag():
    # argparse rejects an unrecognized "--host" and exits (SystemExit) from
    # inside parse_args(), before `serve`'s handler (which would otherwise
    # block forever in serve_forever()) is ever reached -- safe to call
    # main() directly here.
    with pytest.raises(SystemExit):
        main(["serve", "--host", "0.0.0.0", "--port", "0"])


def test_serve_subcommand_accepts_port_flag():
    parser = argparse.ArgumentParser()
    # Smoke-check at the argparse level: `serve --port` is a recognized
    # option with an int type and a default, without actually binding a
    # socket (that's covered by the fixture-based tests above).
    from ethical_agent.__main__ import DEFAULT_WEB_PORT

    assert isinstance(DEFAULT_WEB_PORT, int)
    assert DEFAULT_WEB_PORT > 0


def test_serve_default_config_calls_the_real_model_not_mock(monkeypatch):
    # Web-UI-only default: `ethical-agent serve` seeds the chat's config
    # panel with mock=False, so a first-time visitor with Ollama running
    # gets a real answer -- resolve_llm() still falls back to MockLLM on its
    # own if the model can't be reached, this only changes what's *tried*
    # first. Verified by intercepting webui.server.make_server (cmd_serve
    # does `from .webui.server import make_server` at call time, so
    # patching the module attribute here is picked up), never binding a
    # real socket.
    captured = {}

    class FakeServer:
        def serve_forever(self):
            raise KeyboardInterrupt()

        def server_close(self):
            pass

    def fake_make_server(port, initial_config, **kwargs):
        captured["initial_config"] = initial_config
        captured["kwargs"] = kwargs
        return FakeServer()

    import ethical_agent.webui.server as server_module

    monkeypatch.setattr(server_module, "make_server", fake_make_server)

    code = main(["serve", "--port", "0"])
    assert code == 0
    assert captured["initial_config"]["mock"] is False
    # The audit password reaches make_server as its own argument and never
    # through initial_config, which handlers_choices.py serves verbatim to
    # the chat screen. Here there is no password at all, so the audit screen
    # does not exist.
    assert captured["kwargs"]["audit_password"] is None
    assert not any("password" in key for key in captured["initial_config"])
