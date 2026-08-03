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
from ethical_agent.ollama_install import AUDIT_PASSWORD_ENV_VAR  # noqa: E402


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
    app.remove_audit_password = tk.BooleanVar(master=root, value=False)

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


def test_typing_a_password_while_one_is_exported_is_refused_with_both_ways_out(
    page, monkeypatch, tmp_path
):
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.app.audit_password_var.set("senha-nova")

    assert page.can_advance() is False

    erro = _erro(page)
    assert f"${AUDIT_PASSWORD_ENV_VAR}" in erro
    assert str(tmp_path / ".env") in erro
    # Both ways forward, because someone with that variable in their shell
    # profile is not doing anything wrong and has to be able to finish.
    assert "apague a variável de ambiente" in erro
    assert "deixe este campo em branco" in erro
    # And never the password itself.
    assert "senha-nova" not in erro


def test_leaving_the_field_blank_is_the_way_through_when_one_is_exported(page, monkeypatch):
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.app.audit_password_var.set("")

    assert page.can_advance() is True
    assert _erro(page) == ""


def test_the_screen_says_a_password_it_did_not_write_is_already_in_effect(page, monkeypatch):
    # Without this the block above looks arbitrary: the field is empty, the
    # screen says nothing, and the person has no way to know a password is
    # already active.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()

    estado = page.audit_state_label.cget("text")
    assert f"${AUDIT_PASSWORD_ENV_VAR}" in estado
    assert "já está habilitada" in estado
    assert page.audit_state_label.winfo_manager() == "pack", "o rótulo tem de estar visível"
    # Nothing in .env to remove, so no checkbox.
    assert page.audit_remove_check.winfo_manager() == ""


def test_an_existing_conflict_is_named_and_the_checkbox_becomes_the_way_out(
    page, monkeypatch, tmp_path
):
    # The reinstall case: .env already has one and the variable is exported,
    # so the machine is already in the state the server refuses to start on.
    _dotenv(tmp_path)
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()

    estado = page.audit_state_label.cget("text")
    assert "duas senhas" in estado
    assert page.audit_remove_check.winfo_manager() == "pack"
    # The checkbox must not still promise to disable the screen -- with a
    # password exported, removing the .env one is the remedy, not a loss.
    rotulo = page.audit_remove_check.cget("text")
    assert "desativar" not in rotulo
    assert "variável de ambiente" in rotulo

    # Blank field, conflict on disk: still refused, and the message points at
    # the checkbox that is now on screen.
    assert page.can_advance() is False
    assert "marque a remoção" in _erro(page).lower()

    # Ticking it is what lets the install proceed.
    page.app.remove_audit_password.set(True)
    assert page.can_advance() is True


def test_nothing_exported_leaves_the_screen_exactly_as_it_was(page, tmp_path):
    # The regression guard for the whole change: with no variable in the
    # environment, this screen must behave as it always did.
    _dotenv(tmp_path)
    page.on_show()

    assert page.audit_state_label.cget("text").startswith("Já existe uma senha configurada")
    assert page.audit_remove_check.cget("text") == "Remover a senha e desativar a tela de auditoria"
    assert page.can_advance() is True

    page.app.audit_password_var.set("outra-senha")
    assert page.can_advance() is True
    assert _erro(page) == ""


def _progress_page(monkeypatch, tmp_path, password="", remove=False):
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
    app.chosen_remove_audit_password = remove
    app.audit_enabled = None
    progress.app = app
    return progress


def _log(progress):
    linhas = []
    while not progress._queue.empty():
        linhas.append(progress._queue.get_nowait())
    return "".join(linhas)


def test_the_install_step_refuses_to_write_a_second_password(monkeypatch, tmp_path):
    # can_advance already refuses this, but it runs before the snapshot is
    # taken and Back stays enabled during the install -- so the state it
    # validated is not necessarily the state that gets written.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    progress = _progress_page(monkeypatch, tmp_path, password="senha-nova")

    assert progress._apply_audit_password() is False
    assert not (tmp_path / ".env").exists(), "nada pode ter sido gravado"

    log = _log(progress)
    assert f"${AUDIT_PASSWORD_ENV_VAR}" in log
    assert "Nada foi gravado" in log
    assert "limpe o campo" in log and "apague a variável" in log
    assert "senha-nova" not in log
    # The screen is not lost: the exported password still enables it.
    assert progress.app.audit_enabled is True


def test_the_install_step_writes_normally_when_nothing_is_exported(monkeypatch, tmp_path):
    progress = _progress_page(monkeypatch, tmp_path, password="senha-nova")

    assert progress._apply_audit_password() is True
    assert "ETHICAL_AGENT_AUDIT_PASSWORD=senha-nova" in (tmp_path / ".env").read_text(
        encoding="utf-8"
    )
    assert progress.app.audit_enabled is True
    assert "senha-nova" not in _log(progress), "o log nomeia o arquivo, nunca o valor"


def test_a_blank_field_reports_the_exported_password_as_the_reason_audit_is_on(
    monkeypatch, tmp_path
):
    # The way out offered on the options screen. If this branch reported the
    # audit screen as disabled, the wizard's last page would tell the person
    # the opposite of what the server is about to do.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    progress = _progress_page(monkeypatch, tmp_path, password="")

    assert progress._apply_audit_password() is True
    assert progress.app.audit_enabled is True
    assert not (tmp_path / ".env").exists()
    assert "variável de ambiente" in _log(progress)


def test_removing_the_dotenv_password_does_not_claim_the_screen_is_gone(monkeypatch, tmp_path):
    # The checkbox is offered as the way out of an existing conflict, so its
    # progress line has to describe what actually happens: the exported
    # password takes over.
    _dotenv(tmp_path)
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    progress = _progress_page(monkeypatch, tmp_path, remove=True)

    assert progress._apply_audit_password() is True
    assert progress.app.audit_enabled is True
    log = _log(progress)
    assert "variável de ambiente" in log
    assert "deixa de existir" not in log


def test_removing_it_with_nothing_exported_still_disables_the_screen(monkeypatch, tmp_path):
    _dotenv(tmp_path)
    progress = _progress_page(monkeypatch, tmp_path, remove=True)

    assert progress._apply_audit_password() is True
    assert progress.app.audit_enabled is False
    assert "/audit deixa de existir" in _log(progress)


def test_the_old_contradiction_check_still_wins(page, monkeypatch, tmp_path):
    # "New password" + "remove it" is refused for its own reason, and that
    # message must not be replaced by the newer one just because a variable
    # happens to be exported too.
    _dotenv(tmp_path)
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.app.audit_password_var.set("senha-nova")
    page.app.remove_audit_password.set(True)

    assert page.can_advance() is False
    assert "Escolha uma coisa só" in _erro(page)
