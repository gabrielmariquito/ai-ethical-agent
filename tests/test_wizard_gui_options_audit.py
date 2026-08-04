# The audit-password field, exercised as a real widget.
#
# tests/test_wizard_gui.py reads wizard_gui.py as source text on purpose --
# it is the only way to assert on a tkinter file without a display. That is
# enough to check a guard is *written*; it cannot check the guard *works*,
# and a refusal that blocks the install is exactly the kind of thing that has
# to be seen rendering. So this module builds the actual OptionsPage against
# a withdrawn Tk root and reads the labels back out of the widgets.
#
# Skipped, never failed, where tkinter itself is missing: this must not turn
# a headless CI run red for a reason that has nothing to do with the code
# (the same rule test_wizard_gui_launch.py already follows). A *present*
# tkinter that then fails is a different thing and is not skipped -- see
# _tk_root below.
import queue

import pytest

tk = pytest.importorskip("tkinter")

import wizard_gui  # noqa: E402
from ethical_agent.ollama_install import (  # noqa: E402
    AUDIT_PASSWORD_ENV_VAR,
    read_env_var,
)


def _tk_root():
    """A withdrawn Tk root, retried once.

    Every Tk() builds a fresh Tcl interpreter, which re-reads init.tcl from
    disk -- and on this machine that read intermittently fails with "no such
    file or directory" for a file that is demonstrably there (measured: 0
    failures in 300 in-process creations and in 40 separate processes, but
    roughly one pytest run in six). It is a transient at the filesystem
    level, not a missing display and not anything about the code under test.

    Retried rather than skipped, because the first version of this fixture
    turned that transient into `pytest.skip("sem display")`: a run that
    quietly tested nothing and still reported green, which is the one
    outcome a test guarding a refusal must never produce. If the retry fails
    too, the error propagates and the test goes red -- also on purpose.
    """
    try:
        root = tk.Tk()
    except tk.TclError:
        root = tk.Tk()
    root.withdraw()
    return root


@pytest.fixture(autouse=True)
def no_exported_password(monkeypatch):
    """No test here may see the developer's own exported password.

    This is not hypothetical: the machine this was written on exports
    ETHICAL_AGENT_AUDIT_PASSWORD, which is the very condition the guards
    under test react to -- so without this, every "nothing is exported"
    case silently tests the opposite of what it says, and passes or fails
    depending on whose shell is running it. Each test sets the variable
    itself when it wants one. Same rule, and the same reason, as
    test_webui_bind.isolated_password_sources.
    """
    monkeypatch.delenv(AUDIT_PASSWORD_ENV_VAR, raising=False)


@pytest.fixture
def page(monkeypatch, tmp_path):
    """A real OptionsPage whose ROOT is tmp_path, so the .env it reads is
    the test's and never the developer's own."""
    root = _tk_root()
    monkeypatch.setattr(wizard_gui, "ROOT", tmp_path)

    app = wizard_gui.WizardApp.__new__(wizard_gui.WizardApp)
    app.want_llm = tk.BooleanVar(master=root, value=False)
    app.llm_mode = tk.StringVar(master=root, value="local")
    app.ollama_model_var = tk.StringVar(master=root, value="llama3.2:3b")
    app.ollama_api_key_var = tk.StringVar(master=root, value="")
    app.audit_password_var = tk.StringVar(master=root, value="")

    frame = tk.Frame(root)
    options = wizard_gui.OptionsPage(frame, app)
    try:
        yield options
    finally:
        root.destroy()


def _dotenv(root, value="do-dotenv"):
    (root / ".env").write_text(
        f"OLLAMA_MODEL=llama3.2:3b\n{AUDIT_PASSWORD_ENV_VAR}={value}\n", encoding="utf-8"
    )


def _erro(page):
    return page.validation_label.cget("text")




def test_an_existing_password_makes_the_field_inert_and_says_so(page, tmp_path):
    # Typing over an existing password must not change it. The field is
    # DISABLED rather than ignored: a box that takes what you type and
    # discards it is the shape of defect this project treats as the worst,
    # and the label has to say where the password can actually be changed.
    _dotenv(tmp_path)
    page.on_show()

    assert page.audit_entry.cget("state") == "disabled"
    estado = page.audit_state_label.cget("text")
    assert "não pode ser trocada nem removida por aqui" in estado
    assert str(tmp_path / ".env") in estado, "tem de dizer onde ela mora"
    assert "digite outra para trocar" not in estado



def test_an_existing_password_advances_even_with_a_leftover_variable_matching(
    page, monkeypatch, tmp_path
):
    _dotenv(tmp_path, "a-mesma")
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "a-mesma")
    page.on_show()

    assert page.can_advance() is True
    assert "a-mesma" not in page.audit_state_label.cget("text")



def test_nothing_exported_and_a_password_already_there_leaves_the_field_disabled(
    page, tmp_path
):
    # The regression guard: with no variable in the environment and a password
    # already written, this screen is purely informative and advances.
    _dotenv(tmp_path)
    page.on_show()

    assert page.audit_entry.cget("state") == "disabled"
    assert page.can_advance() is True

    # Even if a value somehow reaches the variable, it changes nothing.
    page.app.audit_password_var.set("outra-senha")
    assert page.can_advance() is True
    assert _erro(page) == ""


def test_a_first_definition_still_works_when_nothing_is_configured(page, tmp_path):
    # The installer did not stop being able to configure the audit screen --
    # it stopped being able to *change* one. A clean machine still gets a
    # password from this field.
    page.on_show()

    assert page.audit_entry.cget("state") == "normal"
    assert page.audit_state_label.winfo_manager() == ""
    page.app.audit_password_var.set("primeira-senha")
    assert page.can_advance() is True


def _progress_page(monkeypatch, tmp_path, password=""):
    """A ProgressPage with just enough wired up to run _apply_audit_password.

    No Tk here: the method reads the snapshot fields and writes to the queue,
    and __new__ skips the widget construction that would need a display.
    """
    monkeypatch.setattr(wizard_gui, "ROOT", tmp_path)
    progress = wizard_gui.ProgressPage.__new__(wizard_gui.ProgressPage)
    progress._queue = queue.Queue()
    progress._record_env_key = lambda key: None
    app = wizard_gui.WizardApp.__new__(wizard_gui.WizardApp)
    app.chosen_audit_password = password
    app.audit_enabled = None
    progress.app = app
    return progress


def _log(progress):
    linhas = []
    while not progress._queue.empty():
        linhas.append(progress._queue.get_nowait())
    return "".join(linhas)



def test_the_install_step_writes_normally_when_nothing_is_exported(monkeypatch, tmp_path):
    progress = _progress_page(monkeypatch, tmp_path, password="senha-nova")

    assert progress._apply_audit_password() is True
    assert "ETHICAL_AGENT_AUDIT_PASSWORD=senha-nova" in (tmp_path / ".env").read_text(
        encoding="utf-8"
    )
    assert progress.app.audit_enabled is True
    assert "senha-nova" not in _log(progress), "o log nomeia o arquivo, nunca o valor"




def test_a_blank_field_keeps_an_existing_password_and_says_so(monkeypatch, tmp_path):
    _dotenv(tmp_path)
    progress = _progress_page(monkeypatch, tmp_path, password="")

    assert progress._apply_audit_password() is True
    assert progress.app.audit_enabled is True
    log = _log(progress)
    assert "mantida como estava" in log
    # And the log says it will not be changed, so a field that was typed into
    # and ignored can never look like it took.
    assert "não a altera" in log
    assert str(tmp_path / ".env") in log


def test_the_install_step_never_overwrites_an_existing_password(monkeypatch, tmp_path):
    # The rule lives here and not only in the disabled widget: can_advance
    # runs before the snapshot, and Back stays enabled during the install, so
    # a typed value can reach this method even with the field disabled.
    _dotenv(tmp_path, "a-original")
    progress = _progress_page(monkeypatch, tmp_path, password="tentativa-de-troca")

    assert progress._apply_audit_password() is True
    assert read_env_var(tmp_path, AUDIT_PASSWORD_ENV_VAR) == "a-original"
    assert "tentativa-de-troca" not in _log(progress)


def test_the_installer_says_nothing_about_a_leftover_variable(monkeypatch, tmp_path):
    # Deliberate: the server is the one thing that refuses, so it is the one
    # thing that explains. A second explanation here would be a second text to
    # keep true, and _launch_interface already prints the server's verbatim.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    progress = _progress_page(monkeypatch, tmp_path, password="primeira-senha")

    assert progress._apply_audit_password() is True
    assert read_env_var(tmp_path, AUDIT_PASSWORD_ENV_VAR) == "primeira-senha"
    log = _log(progress)
    assert "variável de ambiente" not in log
    assert "primeira-senha" not in log


def test_the_options_screen_says_nothing_about_a_leftover_variable(
    page, monkeypatch, tmp_path
):
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()

    # Nothing on screen mentions it, and nothing blocks on it.
    assert page.audit_state_label.winfo_manager() == ""
    assert page.can_advance() is True
    assert _erro(page) == ""



