# Ao contrário de `test_wizard_gui.py`, estes exercitam o comportamento real
# de `_launch_interface`; o módulo inteiro é pulado onde falta tkinter, em
# vez de deixar a execução vermelha por motivo alheio: `REGISTRO`, "Texto movido do código".
import pytest

pytest.importorskip("tkinter")

import wizard_gui  # noqa: E402


class _FakeProc:
    pid = 4242

    def __init__(self, returncode=None):
        # None means "still running", exactly as subprocess.Popen.poll()
        # reports it -- which is what distinguishes a server that is merely
        # slow from one that started and died.
        self.returncode = returncode

    def poll(self):
        return self.returncode


def _bare_app():
    # _launch_interface never touches `self` -- it's a plain function
    # attached to the class for organization. __new__ skips Tk.__init__ (the
    # part that would actually open a window), so no real display is needed.
    return wizard_gui.WizardApp.__new__(wizard_gui.WizardApp)


def test_launch_command_uses_serve_module_invocation(monkeypatch):
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(wizard_gui, "_is_headless", lambda: False)
    monkeypatch.setattr(wizard_gui.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(wizard_gui, "_wait_for_web_ui", lambda port, **kw: False)

    wizard_gui.WizardApp._launch_interface(_bare_app())

    assert captured["cmd"][1:] == [
        "-m",
        "ethical_agent",
        "serve",
        "--port",
        str(wizard_gui.DEFAULT_WEB_PORT),
    ]


def test_launch_skips_everything_when_headless(monkeypatch):
    monkeypatch.setattr(wizard_gui, "_is_headless", lambda: True)

    def fail_popen(*args, **kwargs):
        raise AssertionError("Popen must never be called when headless")

    monkeypatch.setattr(wizard_gui.subprocess, "Popen", fail_popen)

    wizard_gui.WizardApp._launch_interface(_bare_app())  # must not raise


def test_launch_never_raises_when_popen_fails(monkeypatch):
    # "Never treated as an install failure" -- a broken venv/interpreter
    # path must not propagate out of _launch_interface.
    monkeypatch.setattr(wizard_gui, "_is_headless", lambda: False)

    def broken_popen(*args, **kwargs):
        raise OSError("no such file or directory")

    monkeypatch.setattr(wizard_gui.subprocess, "Popen", broken_popen)

    wizard_gui.WizardApp._launch_interface(_bare_app())  # must not raise


def test_launch_opens_browser_only_when_server_responds(monkeypatch):
    opened = {}

    monkeypatch.setattr(wizard_gui, "_is_headless", lambda: False)
    monkeypatch.setattr(wizard_gui.subprocess, "Popen", lambda cmd, **kw: _FakeProc())
    monkeypatch.setattr(wizard_gui, "_wait_for_web_ui", lambda port, **kw: True)
    monkeypatch.setattr(wizard_gui.webbrowser, "open", lambda url: opened.setdefault("url", url))

    wizard_gui.WizardApp._launch_interface(_bare_app())

    assert opened["url"] == f"http://127.0.0.1:{wizard_gui.DEFAULT_WEB_PORT}"


def test_launch_skips_browser_when_server_never_responds(monkeypatch):
    def fail_open(*args, **kwargs):
        raise AssertionError("webbrowser.open must not be called if the server never answered")

    monkeypatch.setattr(wizard_gui, "_is_headless", lambda: False)
    monkeypatch.setattr(wizard_gui.subprocess, "Popen", lambda cmd, **kw: _FakeProc())
    monkeypatch.setattr(wizard_gui, "_wait_for_web_ui", lambda port, **kw: False)
    monkeypatch.setattr(wizard_gui.webbrowser, "open", fail_open)

    wizard_gui.WizardApp._launch_interface(_bare_app())  # must not raise either


def test_launch_prints_the_servers_own_error_when_it_exits_immediately(monkeypatch, capsys):
    # O instalador é o único lugar onde a pessoa vê isto, e o que o servidor
    # dizia ao sair era descartado e reportado como "não respondeu a tempo" —
    # mensagem de timeout para algo que não expirou: `REGISTRO`, "Texto movido do código".
    recusa = "error: há duas senhas de auditoria definidas ao mesmo tempo"

    def fake_popen(cmd, **kwargs):
        # Write through the very handle _launch_interface passed us, which
        # is what a real child process does.
        kwargs["stderr"].write(recusa + "\n")
        kwargs["stderr"].flush()
        return _FakeProc(returncode=2)

    monkeypatch.setattr(wizard_gui, "_is_headless", lambda: False)
    monkeypatch.setattr(wizard_gui.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(wizard_gui, "_wait_for_web_ui", lambda port, **kw: False)

    wizard_gui.WizardApp._launch_interface(_bare_app())

    out = capsys.readouterr().out
    assert recusa in out
    assert "encerrou assim que subiu" in out
    assert "código 2" in out
    assert "ainda estar subindo" not in out, "não é timeout: o processo morreu"


def test_launch_keeps_the_timeout_wording_when_the_server_is_merely_slow(monkeypatch, capsys):
    # poll() is None -- still running, just not answering yet. Unchanged
    # behaviour, asserted so the branch above cannot swallow this one.
    monkeypatch.setattr(wizard_gui, "_is_headless", lambda: False)
    monkeypatch.setattr(wizard_gui.subprocess, "Popen", lambda cmd, **kw: _FakeProc())
    monkeypatch.setattr(wizard_gui, "_wait_for_web_ui", lambda port, **kw: False)

    wizard_gui.WizardApp._launch_interface(_bare_app())

    out = capsys.readouterr().out
    assert "não respondeu" in out
    assert "ainda estar subindo" in out
    assert "encerrou assim que subiu" not in out


def test_launch_never_pipes_the_servers_stderr(monkeypatch):
    # httphandler writes a line to stderr per request and nothing here ever
    # drains it, so a PIPE would freeze the web interface for good once the
    # buffer filled -- a worse defect than the discarded error message that
    # motivated capturing stderr in the first place.
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["stderr"] = kwargs["stderr"]
        return _FakeProc()

    monkeypatch.setattr(wizard_gui, "_is_headless", lambda: False)
    monkeypatch.setattr(wizard_gui.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(wizard_gui, "_wait_for_web_ui", lambda port, **kw: True)
    monkeypatch.setattr(wizard_gui.webbrowser, "open", lambda url: None)

    wizard_gui.WizardApp._launch_interface(_bare_app())

    assert captured["stderr"] is not wizard_gui.subprocess.PIPE


def test_finish_text_does_not_mention_nonexistent_gui_readme():
    assert "GUI_README" not in wizard_gui.FINISH_TEXT


def test_manual_launch_instructions_reference_serve_command():
    text = wizard_gui._manual_launch_instructions()
    assert "-m ethical_agent serve" in text
    assert f"--port {wizard_gui.DEFAULT_WEB_PORT}" in text
    assert f"127.0.0.1:{wizard_gui.DEFAULT_WEB_PORT}" in text
