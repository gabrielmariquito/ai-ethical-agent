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
    app.remove_audit_password = tk.BooleanVar(master=root, value=False)
    app.adopt_exported_password = tk.BooleanVar(master=root, value=False)

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


def test_a_leftover_variable_with_no_dotenv_password_is_refused_not_adopted_silently(
    page, monkeypatch, tmp_path
):
    # This used to be the way through: the variable configured the screen and
    # a blank field meant "use it". The variable is not a source any more, so
    # a blank field would leave nothing configured and a server that refuses
    # to start -- said here, where there is still something to click.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()
    page.app.audit_password_var.set("")

    assert page.can_advance() is False
    erro = _erro(page)
    assert f"${AUDIT_PASSWORD_ENV_VAR}" in erro
    assert "não é mais uma fonte de senha" in erro
    assert "do-ambiente" not in erro


def test_the_screen_offers_adopting_the_leftover_and_that_is_a_way_through(
    page, monkeypatch, tmp_path
):
    # The exit that never leaves the window. Retyping is the alternative, and
    # this installer exists for people who would rather not go editing shells
    # -- expecting them to remember a secret from a profile they never open
    # is the same as having no graphical exit at all.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()

    assert page.audit_adopt_check.winfo_manager() == "pack"
    assert f"${AUDIT_PASSWORD_ENV_VAR}" in page.audit_adopt_check.cget("text")
    assert "do-ambiente" not in page.audit_adopt_check.cget("text")

    page.app.adopt_exported_password.set(True)
    assert page.can_advance() is True
    assert _erro(page) == ""


def test_typing_the_same_password_the_variable_holds_is_also_a_way_through(
    page, monkeypatch, tmp_path
):
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()

    page.app.audit_password_var.set("outra-senha")
    assert page.can_advance() is False
    assert "outra-senha" not in _erro(page)

    page.app.audit_password_var.set("do-ambiente")
    assert page.can_advance() is True


def test_the_screen_says_a_leftover_variable_is_not_read(page, monkeypatch):
    # Without this the block looks arbitrary: the field is empty, the screen
    # says nothing, and the person has no way to know why they cannot move on.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()

    estado = page.audit_state_label.cget("text")
    assert f"${AUDIT_PASSWORD_ENV_VAR}" in estado
    assert "não é mais uma fonte de senha" in estado
    assert "já está habilitada" not in estado, "era verdade antes; agora seria mentira"
    assert page.audit_state_label.winfo_manager() == "pack", "o rótulo tem de estar visível"
    # Nothing in .env to remove, so no removal checkbox.
    assert page.audit_remove_check.winfo_manager() == ""


def test_a_leftover_that_disagrees_with_dotenv_is_named_and_removal_is_not_the_way_out(
    page, monkeypatch, tmp_path
):
    # The reinstall case. Removal used to be offered here, on the grounds that
    # the exported password would take over -- it does not, so ticking it now
    # leaves nothing configured and the same refusal.
    _dotenv(tmp_path)
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()

    estado = page.audit_state_label.cget("text")
    assert "valor diferente" in estado
    assert "não é mais lida" in estado
    assert page.audit_remove_check.winfo_manager() == "pack"
    # The checkbox tells the truth again: .env is the only home, so removing
    # it always costs the screen.
    assert page.audit_remove_check.cget("text") == "Remover a senha e desativar a tela de auditoria"

    assert page.can_advance() is False

    page.app.remove_audit_password.set(True)
    assert page.can_advance() is False, "remover não resolve: a variável continua lá"

    page.app.remove_audit_password.set(False)
    page.app.adopt_exported_password.set(True)
    assert page.can_advance() is True


def test_a_leftover_that_repeats_the_dotenv_password_is_not_in_the_way(
    page, monkeypatch, tmp_path
):
    # Nothing is ambiguous, so nothing is blocked -- but the screen still says
    # it, because this is where someone comes to *change* the password, and a
    # change while the variable is set is what turns into a refusal.
    _dotenv(tmp_path, "a-mesma")
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "a-mesma")
    page.on_show()

    assert page.can_advance() is True
    estado = page.audit_state_label.cget("text")
    assert "repete essa mesma senha" in estado
    assert "pode ser apagada" in estado
    assert "a-mesma" not in estado
    # Nothing to adopt: .env already has that value.
    assert page.audit_adopt_check.winfo_manager() == ""


def test_nothing_exported_leaves_the_screen_exactly_as_it_was(page, tmp_path):
    # The regression guard for the whole change: with no variable in the
    # environment, this screen must behave as it always did.
    _dotenv(tmp_path)
    page.on_show()

    assert page.audit_state_label.cget("text").startswith("Já existe uma senha configurada")
    assert page.audit_remove_check.cget("text") == "Remover a senha e desativar a tela de auditoria"
    assert page.audit_adopt_check.winfo_manager() == "", "nada a adotar, nada a mostrar"
    assert page.can_advance() is True

    page.app.audit_password_var.set("outra-senha")
    assert page.can_advance() is True
    assert _erro(page) == ""


def _progress_page(monkeypatch, tmp_path, password="", remove=False, adopt=False):
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
    app.chosen_adopt_exported_password = adopt
    app.audit_enabled = None
    progress.app = app
    return progress


def _log(progress):
    linhas = []
    while not progress._queue.empty():
        linhas.append(progress._queue.get_nowait())
    return "".join(linhas)


def test_the_install_step_refuses_to_write_a_password_the_server_would_reject(
    monkeypatch, tmp_path
):
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
    assert "adotar a senha da variável" in log
    assert "senha-nova" not in log
    assert "do-ambiente" not in log
    # Nothing was written, so nothing is configured either.
    assert progress.app.audit_enabled is False


def test_the_install_step_writes_normally_when_nothing_is_exported(monkeypatch, tmp_path):
    progress = _progress_page(monkeypatch, tmp_path, password="senha-nova")

    assert progress._apply_audit_password() is True
    assert "ETHICAL_AGENT_AUDIT_PASSWORD=senha-nova" in (tmp_path / ".env").read_text(
        encoding="utf-8"
    )
    assert progress.app.audit_enabled is True
    assert "senha-nova" not in _log(progress), "o log nomeia o arquivo, nunca o valor"


def test_adopting_the_leftover_writes_it_into_dotenv_without_ever_printing_it(
    monkeypatch, tmp_path
):
    # The fourth route. The value goes from the environment straight into the
    # writer; it is never displayed, never logged, and never held in a Tk
    # variable where a screenshot could catch it.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "SENHA-CANARIO-EXPORTADA")
    progress = _progress_page(monkeypatch, tmp_path, adopt=True)

    assert progress._apply_audit_password() is True
    assert "ETHICAL_AGENT_AUDIT_PASSWORD=SENHA-CANARIO-EXPORTADA" in (
        tmp_path / ".env"
    ).read_text(encoding="utf-8")
    assert progress.app.audit_enabled is True
    assert "SENHA-CANARIO-EXPORTADA" not in _log(progress)


def test_typing_the_password_the_variable_already_holds_is_written_without_complaint(
    monkeypatch, tmp_path
):
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "a-mesma")
    progress = _progress_page(monkeypatch, tmp_path, password="a-mesma")

    assert progress._apply_audit_password() is True
    assert progress.app.audit_enabled is True


def test_a_blank_field_with_a_leftover_variable_and_no_dotenv_is_refused(
    monkeypatch, tmp_path
):
    # This used to be the supported way to finish -- the variable configured
    # the screen. Reporting it as enabled now would make the wizard's last
    # page promise a screen the server refuses to serve.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    progress = _progress_page(monkeypatch, tmp_path, password="")

    assert progress._apply_audit_password() is False
    assert progress.app.audit_enabled is False
    assert not (tmp_path / ".env").exists()


def test_a_blank_field_keeps_an_existing_password_and_says_nothing_new(
    monkeypatch, tmp_path
):
    _dotenv(tmp_path)
    progress = _progress_page(monkeypatch, tmp_path, password="")

    assert progress._apply_audit_password() is True
    assert progress.app.audit_enabled is True
    assert "mantida como estava" in _log(progress)


def test_removing_the_dotenv_password_always_costs_the_screen_now(monkeypatch, tmp_path):
    # There is no exported password to take over, so the progress line says
    # the same thing whether or not the variable happens to be set.
    _dotenv(tmp_path)
    progress = _progress_page(monkeypatch, tmp_path, remove=True)

    assert progress._apply_audit_password() is True
    assert progress.app.audit_enabled is False
    assert "/audit deixa de existir" in _log(progress)


def test_removing_it_while_a_leftover_variable_is_set_is_refused(monkeypatch, tmp_path):
    # Removal used to be the remedy here. It is not: it would leave nothing
    # configured and a server that refuses to start over the leftover.
    _dotenv(tmp_path)
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    progress = _progress_page(monkeypatch, tmp_path, remove=True)

    assert progress._apply_audit_password() is False
    assert read_env_var(tmp_path, AUDIT_PASSWORD_ENV_VAR) == "do-dotenv", "nada removido"


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


def test_adopting_is_one_of_the_mutually_exclusive_instructions(page, monkeypatch, tmp_path):
    # Three boxes that each say what to write are three instructions, and
    # quietly picking one is exactly what this field refuses to do.
    monkeypatch.setenv(AUDIT_PASSWORD_ENV_VAR, "do-ambiente")
    page.on_show()
    page.app.adopt_exported_password.set(True)
    page.app.audit_password_var.set("senha-nova")

    assert page.can_advance() is False
    assert "Escolha uma coisa só" in _erro(page)
    assert "senha-nova" not in _erro(page)
