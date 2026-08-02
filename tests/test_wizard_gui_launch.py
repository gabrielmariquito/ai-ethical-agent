# Unlike tests/test_wizard_gui.py (which reads wizard_gui.py as source text
# specifically to avoid a tkinter dependency), these tests exercise
# _launch_interface's actual behavior -- there was no runtime coverage of it
# at all before this change (mocked Popen/webbrowser/_is_headless). tkinter
# is stdlib but not guaranteed present in every environment (minimal/headless
# CI images), so this whole module is skipped where it's missing rather than
# failing the run.
import pytest

pytest.importorskip("tkinter")

import wizard_gui  # noqa: E402


class _FakeProc:
    pid = 4242


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


def test_finish_text_does_not_mention_nonexistent_gui_readme():
    assert "GUI_README" not in wizard_gui.FINISH_TEXT


def test_manual_launch_instructions_reference_serve_command():
    text = wizard_gui._manual_launch_instructions()
    assert "-m ethical_agent serve" in text
    assert f"--port {wizard_gui.DEFAULT_WEB_PORT}" in text
    assert f"127.0.0.1:{wizard_gui.DEFAULT_WEB_PORT}" in text
