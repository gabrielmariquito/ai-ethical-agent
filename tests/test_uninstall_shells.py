"""Tests for the two uninstaller shells: uninstall.py and uninstall_gui.py.

uninstall.py is imported and driven for real -- main(argv, root=..., ask=...,
isatty=...) -- rather than asserted on as source text. The reason
tests/test_wizard_gui.py reads its target as a string (importing it needs
tkinter and a display-dependent setup) simply does not apply to the CLI
shell: it is plain stdlib, and tests/conftest.py already puts the repo root
on sys.path. Driving it exercises the argument parsing, the guards, the
prompts and the exit codes together, which source text cannot.

uninstall_gui.py does need tkinter, so it keeps the source-text technique.

As in tests/test_uninstall.py, no test here passes the real repository root.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import uninstall

PYPROJECT = '[project]\nname = "ai-ethical-agent"\nversion = "0.3.0"\n'


def _make_root(tmp_path, *, logs=True, env="OLLAMA_MODEL=llama3.2:3b\n"):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "ethical_agent").mkdir()
    (root / "ethical_agent" / "keep.py").write_text("x = 1", encoding="utf-8")
    (root / "policies").mkdir()
    (root / "policies" / "core_policy.json").write_text("{}", encoding="utf-8")
    venv_lib = root / ".venv" / "Lib"
    venv_lib.mkdir(parents=True)
    (venv_lib / "thing.py").write_text("y = 2", encoding="utf-8")
    (root / "build").mkdir()
    (root / "build" / "out.txt").write_text("b", encoding="utf-8")
    if logs:
        (root / "logs").mkdir()
        (root / "logs" / "audit.jsonl").write_text(
            json.dumps({"event_id": "a", "timestamp": "2026-01-01T00:00:00+00:00"}) + "\n",
            encoding="utf-8",
        )
    if env is not None:
        (root / ".env").write_text(env, encoding="utf-8")
    return root


def _answers(*replies):
    """An injected input() that hands back canned replies in order."""
    pending = list(replies)

    def ask(prompt):
        return pending.pop(0) if pending else ""

    return ask


def _no_tty():
    return False


def _tty():
    return True


# -- guards ----------------------------------------------------------------


def test_main_refuses_a_directory_that_is_not_this_project(tmp_path, capsys):
    other = tmp_path / "elsewhere"
    other.mkdir()
    code = uninstall.main(["--dry-run"], root=other, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_REFUSED
    assert "não parece ser o repositório" in capsys.readouterr().err


def test_main_refuses_when_run_from_the_projects_own_venv(tmp_path, capsys, monkeypatch):
    root = _make_root(tmp_path)
    fake_python = root / ".venv" / "Scripts" / "python.exe"
    fake_python.parent.mkdir(parents=True, exist_ok=True)
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))

    code = uninstall.main(["--remove-env", "--yes"], root=root, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "Python do próprio venv" in err
    assert "uninstall.py" in err  # carries the exact fix
    assert (root / ".env").exists(), "nada pode ser removido quando a guarda recusa"


def test_dry_run_is_allowed_from_the_venv_because_it_touches_nothing(tmp_path, capsys, monkeypatch):
    # Refusing a simulation would be friction for nothing, and the
    # simulation is exactly what a cautious person runs first -- often with
    # the venv activated.
    root = _make_root(tmp_path)
    fake_python = root / ".venv" / "Scripts" / "python.exe"
    fake_python.parent.mkdir(parents=True, exist_ok=True)
    fake_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))

    code = uninstall.main(["--dry-run"], root=root, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_OK
    captured = capsys.readouterr()
    assert "SIMULAÇÃO" in captured.out
    assert "aviso:" in captured.err
    assert (root / ".venv").exists()


# -- dry run ---------------------------------------------------------------


def test_main_dry_run_exits_zero_prints_the_plan_and_deletes_nothing(tmp_path, capsys):
    root = _make_root(tmp_path)
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    code = uninstall.main(["--dry-run", "--no-probe"], root=root, ask=_answers(), isatty=_no_tty)

    assert code == uninstall.EXIT_OK
    out = capsys.readouterr().out
    assert "SIMULAÇÃO -- nada será removido." in out
    assert ".venv/" in out
    assert "[requer --remove-logs]" in out
    assert "[requer --remove-env]" in out
    assert "NUNCA REMOVIDO" in out
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before


def test_dry_run_creates_no_pycache_under_the_root_it_inspects(tmp_path):
    # ethical_agent/__init__.py imports ~11 submodules eagerly, so without
    # sys.dont_write_bytecode the uninstaller would create the very
    # __pycache__ directories it reports as removable.
    root = _make_root(tmp_path)
    uninstall.main(["--dry-run", "--no-probe"], root=root, ask=_answers(), isatty=_no_tty)
    assert list(root.rglob("__pycache__")) == []


def test_dry_run_lists_optional_items_even_when_their_flags_were_not_given(tmp_path, capsys):
    root = _make_root(tmp_path)
    uninstall.main(["--dry-run", "--no-probe"], root=root, ask=_answers(), isatty=_no_tty)
    out = capsys.readouterr().out
    assert "Trilha de auditoria" in out
    assert "1 registro" in out
    # Data, sem hora nem fuso: a pergunta é que período se perde.
    assert re.search(r"Período: \d{2}/\d{2}/\d{4}", out)


# -- non-interactive contract ----------------------------------------------


def test_main_without_yes_and_without_a_tty_prints_the_plan_and_deletes_nothing(tmp_path, capsys):
    # A piped or CI invocation must never delete by accident.
    root = _make_root(tmp_path)
    code = uninstall.main([], root=root, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_OK
    assert "nada foi removido" in capsys.readouterr().out
    assert (root / ".venv").exists()


def test_yes_confirms_only_the_final_question_and_implies_no_optional_item(tmp_path):
    # The flag-surface equivalent of "unchecked by default".
    root = _make_root(tmp_path)
    code = uninstall.main(["--yes", "--no-probe"], root=root, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_OK
    assert not (root / ".venv").exists()
    assert not (root / "build").exists()
    assert (root / "logs" / "audit.jsonl").exists()
    assert (root / ".env").exists()
    assert (root / "ethical_agent" / "keep.py").exists()
    assert (root / "policies" / "core_policy.json").exists()


@pytest.mark.parametrize(
    "flag,gone,kept",
    [
        ("--remove-logs", "logs/audit.jsonl", ".env"),
        ("--remove-env", ".env", "logs/audit.jsonl"),
    ],
)
def test_each_flag_in_isolation_removes_only_its_own_target(tmp_path, flag, gone, kept):
    root = _make_root(tmp_path)
    code = uninstall.main([flag, "--yes", "--no-probe"], root=root, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_OK
    assert not (root / gone).exists()
    assert (root / kept).exists()


def test_move_logs_to_implies_remove_logs_and_moves_instead_of_deleting(tmp_path):
    root = _make_root(tmp_path)
    dest = tmp_path / "backup"
    original = (root / "logs" / "audit.jsonl").read_text(encoding="utf-8")

    code = uninstall.main(
        ["--move-logs-to", str(dest), "--yes", "--no-probe"],
        root=root, ask=_answers(), isatty=_no_tty,
    )
    assert code == uninstall.EXIT_OK
    assert not (root / "logs").exists()
    assert (dest / "audit.jsonl").read_text(encoding="utf-8") == original


def test_main_exits_nonzero_when_something_failed(tmp_path, monkeypatch, capsys):
    # execute() resolves remove_path from the module namespace at call time,
    # so replacing it here is enough. (The real in-use detection is covered
    # against the filesystem in tests/test_uninstall.py; what this asserts is
    # that the shell surfaces a failure as a non-zero exit and readable text
    # rather than swallowing it.)
    import ethical_agent.uninstall as lib

    root = _make_root(tmp_path)
    real_remove_path = lib.remove_path

    def flaky_remove_path(path, key="", **hooks):
        if key == "venv":
            return lib.RemovalResult(
                key, str(path), lib.FAILED,
                "removidos 1 de 2 itens; 1 falharam (arquivo em uso -- o "
                "servidor web ou o Ollama podem estar rodando)",
            )
        return real_remove_path(path, key, **hooks)

    monkeypatch.setattr(lib, "remove_path", flaky_remove_path)
    code = uninstall.main(["--yes", "--no-probe"], root=root, ask=_answers(), isatty=_no_tty)

    assert code == uninstall.EXIT_FAILURES
    out = capsys.readouterr().out
    assert "[failed]" in out
    assert "arquivo em uso" in out
    # The failure did not abort the rest.
    assert not (root / "build").exists()


def test_nothing_to_remove_reports_so_and_exits_zero(tmp_path, capsys):
    root = tmp_path / "clean"
    root.mkdir()
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    code = uninstall.main(["--no-probe"], root=root, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_OK
    assert "Nada a remover." in capsys.readouterr().out


# -- interactive prompts ---------------------------------------------------


# Interactive question order with --no-probe on a root built by _make_root:
#   1. mover a trilha?        2. apagar a trilha? (+ palavra digitada)
#   3. remover o modelo?      4. remover o .env?
#   5. confirmação final
# Answering "yes" to (1) consumes an extra reply for the destination and
# skips (2).


def test_an_empty_answer_is_no_for_every_optional_question(tmp_path):
    # Enter must never mean yes anywhere in this program.
    root = _make_root(tmp_path)
    code = uninstall.main(
        ["--no-probe"], root=root,
        ask=_answers("", "", "", "", "s"),  # every optional empty, final confirm yes
        isatty=_tty,
    )
    assert code == uninstall.EXIT_OK
    assert not (root / ".venv").exists()
    assert (root / "logs" / "audit.jsonl").exists()
    assert (root / ".env").exists()


def test_removing_the_audit_trail_requires_a_second_confirmation(tmp_path, capsys):
    root = _make_root(tmp_path)
    # "no" to moving, "yes" to deleting -- and then "no" to the confirmation
    # that spells out the consequence. Choosing the item is not confirming it,
    # which is the same two-step the window enforces with two checkboxes.
    code = uninstall.main(
        ["--no-probe"], root=root,
        ask=_answers("n", "s", "n", "n", "n", "s"),
        isatty=_tty,
    )
    assert code == uninstall.EXIT_OK
    assert (root / "logs" / "audit.jsonl").exists(), "a trilha não pode sumir com uma resposta só"
    out = capsys.readouterr().out
    assert "Cancelado -- a trilha será mantida." in out
    # The second question has to name what is lost, not just ask again: in the
    # window that job belongs to the grey line under the checkbox, and a
    # terminal has no room for a secondary line.
    assert "irreversível" in out


def test_confirming_twice_actually_removes_the_audit_trail(tmp_path):
    root = _make_root(tmp_path)
    code = uninstall.main(
        ["--no-probe"], root=root,
        ask=_answers("n", "s", "s", "n", "n", "s"),
        isatty=_tty,
    )
    assert code == uninstall.EXIT_OK
    assert not (root / "logs").exists()
    # Only the trail: answering "no" to the others has to hold.
    assert (root / ".env").exists()


def test_declining_the_final_confirmation_removes_nothing(tmp_path, capsys):
    root = _make_root(tmp_path)
    code = uninstall.main(
        ["--no-probe"], root=root,
        ask=_answers("n", "n", "n", "n", "n"),  # every question no, including the final one
        isatty=_tty,
    )
    assert code == uninstall.EXIT_OK
    assert "Cancelado." in capsys.readouterr().out
    assert (root / ".venv").exists()
    assert (root / "build").exists()


def test_interactive_run_can_move_the_trail_to_a_typed_directory(tmp_path):
    root = _make_root(tmp_path)
    dest = tmp_path / "arquivo-da-pesquisa"
    code = uninstall.main(
        ["--no-probe"], root=root,
        # mover? sim -> destino -> modelo? não -> .env? não -> confirmar
        ask=_answers("s", str(dest), "n", "n", "s"),
        isatty=_tty,
    )
    assert code == uninstall.EXIT_OK
    assert (dest / "audit.jsonl").exists()
    assert not (root / "logs").exists()


def test_removing_env_while_keeping_the_model_prints_how_to_remove_it_later(tmp_path, capsys):
    # The .env held the pointer to the model; without it the model is
    # orphaned, so the literal command has to survive on screen.
    root = _make_root(tmp_path)

    class Completed:
        returncode = 0
        stdout = "NAME ID SIZE MODIFIED\nllama3.2:3b abc 2.0 GB 3 days ago\n"
        stderr = ""

    import ethical_agent.uninstall as lib

    plan = lib.build_plan(
        root, port=8765,
        which=lambda name: str(tmp_path / "ollama"),
        run=lambda *a, **k: Completed(),
        urlopen=lambda *a, **k: (_ for _ in ()).throw(OSError("refused")),
    )
    assert plan.model == "llama3.2:3b"

    code = uninstall.main(
        ["--remove-env", "--yes", "--no-probe"], root=root, ask=_answers(), isatty=_no_tty
    )
    assert code == uninstall.EXIT_OK
    # With --no-probe the model is listed from .env alone, so the hint fires.
    assert "ollama rm llama3.2:3b" in capsys.readouterr().out


# -- the single entry point ------------------------------------------------
#
# run() decides between the window and text mode; main() stays purely the
# CLI, which is what every test above drives -- so no CLI test can ever
# accidentally open a window.


@pytest.fixture
def dispatch(monkeypatch):
    """Espiões para os dois destinos de run().

    run() só decide para onde ir; o que o modo texto faz depois já é coberto
    pelos testes de main() acima. Substituir main() aqui mantém estes testes
    focados na decisão -- e impede que eles montem um plano de verdade, que
    sondaria a rede e o `ollama list` da máquina.
    """

    class Spy:
        def __init__(self):
            self.gui_ports = []
            self.cli_argv = []

        def open_gui(self, port):
            self.gui_ports.append(port)
            return 0

    spy = Spy()

    def fake_main(argv=None, **kwargs):
        spy.cli_argv.append(argv)
        return uninstall.EXIT_OK

    monkeypatch.setattr(uninstall, "main", fake_main)
    return spy


def test_no_arguments_with_a_graphical_session_opens_the_window(dispatch):
    assert uninstall.run([], open_gui=dispatch.open_gui, graphical=True) == 0
    assert dispatch.gui_ports == [uninstall.DEFAULT_WEB_PORT]
    assert dispatch.cli_argv == []


def test_no_graphical_session_falls_back_to_text_mode(dispatch):
    # Servidor, SSH, CI: a janela não é uma opção, e o caminho de volta não
    # pode depender dela.
    assert uninstall.run([], open_gui=dispatch.open_gui, graphical=False) == 0
    assert dispatch.gui_ports == []
    assert dispatch.cli_argv == [[]]


def test_cli_flag_forces_text_mode_even_with_a_display(dispatch):
    assert uninstall.run(["--cli"], open_gui=dispatch.open_gui, graphical=True) == 0
    assert dispatch.gui_ports == []
    assert dispatch.cli_argv == [["--cli"]]


@pytest.mark.parametrize(
    "flag",
    ["--dry-run", "--yes", "--remove-logs", "--remove-model", "--remove-env",
     "--remove-ollama", "--no-probe"],
)
def test_an_explicit_flag_means_the_person_already_knows_what_they_want(dispatch, flag):
    uninstall.run([flag], open_gui=dispatch.open_gui, graphical=True)
    assert dispatch.gui_ports == [], f"{flag} deveria ter ficado no modo texto"
    assert dispatch.cli_argv == [[flag]]


def test_move_logs_to_also_means_text_mode(dispatch, tmp_path):
    uninstall.run(["--move-logs-to", str(tmp_path / "bk")],
                  open_gui=dispatch.open_gui, graphical=True)
    assert dispatch.gui_ports == []


def test_port_alone_still_opens_the_window(dispatch):
    # --port diz *como sondar*, não *o que remover*: a janela também a
    # entende, então não é motivo para cair no modo texto.
    assert uninstall.run(["--port", "9000"], open_gui=dispatch.open_gui, graphical=True) == 0
    assert dispatch.gui_ports == [9000]
    assert dispatch.cli_argv == []


def test_a_window_that_refuses_to_open_falls_back_to_text_mode(dispatch, capsys):
    # Sessão gráfica que existe no papel mas quebra (TclError, X remoto) não
    # pode ser o fim do caminho de volta.
    def broken_gui(port):
        raise RuntimeError("no display name and no $DISPLAY environment variable")

    code = uninstall.run(["--port", "9000"], open_gui=broken_gui, graphical=True)
    assert code == uninstall.EXIT_OK
    assert "não foi possível abrir a interface gráfica" in capsys.readouterr().err
    assert dispatch.cli_argv == [["--port", "9000"]]


def test_graphical_detection_reuses_the_wizards_headless_check():
    # _is_headless() já resolve isto (CI, ausência de DISPLAY), e duas cópias
    # dessa heurística divergiriam.
    source = (Path(__file__).resolve().parent.parent / "uninstall.py").read_text(encoding="utf-8")
    assert "from wizard_gui import _is_headless" in source
    body = source[source.index("def _graphical_session_available") :]
    body = body[: body.index("\ndef ")]
    # Tk ausente numa imagem mínima é "sem sessão gráfica", não um crash.
    assert "except Exception" in body
    assert "return False" in body


def test_importing_the_entry_point_never_imports_tkinter():
    # O ponto mais frágil desta mudança. Se o import de tkinter subir para o
    # topo de uninstall.py, o modo texto passa a exigir Tk instalado -- numa
    # imagem mínima ou num servidor, o caminho de volta simplesmente deixa de
    # existir. Rodado num subprocesso porque nesta mesma sessão do pytest
    # outro módulo (test_wizard_gui_launch) já pode ter importado tkinter.
    repo_root = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; import uninstall; "
         "print('tkinter' in sys.modules or 'wizard_gui' in sys.modules)"],
        capture_output=True, text=True, cwd=repo_root,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "False", (
        "importar uninstall.py puxou tkinter/wizard_gui -- o import tem de "
        "ficar dentro de _graphical_session_available()/_open_gui()"
    )


def test_the_entry_point_has_no_module_level_tkinter_import():
    # Statements, not the word: the module docstring explains the rule and
    # legitimately says "tkinter" in prose.
    source = (Path(__file__).resolve().parent.parent / "uninstall.py").read_text(encoding="utf-8")
    header = source[: source.index("\ndef ")]
    for forbidden in (r"import tkinter", r"from tkinter", r"import uninstall_gui",
                      r"from wizard_gui", r"import wizard_gui"):
        assert not re.search(rf"^\s*{forbidden}", header, re.MULTILINE), (
            f"{forbidden!r} no topo de uninstall.py -- o modo texto passaria a exigir Tk"
        )


def test_running_the_script_dispatches_through_run_not_main():
    source = (Path(__file__).resolve().parent.parent / "uninstall.py").read_text(encoding="utf-8")
    assert source.rstrip().endswith("sys.exit(run())")


# -- the Tk shell ----------------------------------------------------------

GUI_SOURCE = (Path(__file__).resolve().parent.parent / "uninstall_gui.py").read_text(
    encoding="utf-8"
)


def test_gui_disables_bytecode_writing_before_importing_the_package():
    # Same paradox as the CLI: opening the window must not create the
    # __pycache__ the window lists as removable. Order matters -- the flag is
    # consulted at import time.
    flag = GUI_SOURCE.index("sys.dont_write_bytecode = True")
    first_package_import = GUI_SOURCE.index("from ethical_agent")
    assert flag < first_package_import


def test_gui_options_all_start_unchecked():
    # The central requirement of the options screen: nothing is removed
    # because the person did not look.
    #
    # Stated as "none of them starts checked" rather than "there are exactly
    # five unchecked ones". The count was coupled to how many options the
    # screen happens to offer -- it broke when one was added for reasons
    # having nothing to do with defaults, and it never proved that the five
    # counted were the five that matter. The negative is what carries the
    # requirement, and it keeps holding as the screen grows.
    assert "tk.BooleanVar(value=True)" not in GUI_SOURCE
    assert "tk.BooleanVar(value=False)" in GUI_SOURCE
    # Every BooleanVar in the file is explicitly initialised: a bare
    # tk.BooleanVar() defaults to False today, but silently, which is the
    # kind of default this screen should not be relying on.
    assert "tk.BooleanVar()" not in GUI_SOURCE


def test_gui_has_a_summary_page_that_is_the_simulation():
    assert "class SummaryPage" in GUI_SOURCE
    assert "Nada foi removido ainda" in GUI_SOURCE
    # The summary must render the same plan object the CLI's --dry-run does.
    assert "self.app.plan" in GUI_SOURCE
    assert "build_plan" in GUI_SOURCE


def test_gui_requires_a_separate_confirmation_before_deleting_the_audit_trail():
    # A checkbox here, a second question in the CLI (see
    # test_removing_the_audit_trail_requires_a_second_confirmation) -- the
    # same two steps on both sides. Ticking "remove the audit trail" is not by
    # itself enough, because moving it is right there as the non-destructive
    # answer.
    assert "logs_confirm" in GUI_SOURCE
    body = GUI_SOURCE[GUI_SOURCE.index("class OptionsPage") : GUI_SOURCE.index("class SummaryPage")]
    assert "def can_advance" in body
    assert "logs_confirm" in body
    assert "move_logs_to" in body, "apagar só pode ter atrito extra se mover for a saída"


def test_gui_offers_moving_the_trail_instead_of_deleting_it():
    assert "filedialog.askdirectory" in GUI_SOURCE
    assert "move_logs_to" in GUI_SOURCE


def test_gui_refuses_to_run_from_the_venv_it_would_delete():
    assert "running_inside_venv" in GUI_SOURCE
    body = GUI_SOURCE[GUI_SOURCE.index("class WelcomePage") : GUI_SOURCE.index("class OptionsPage")]
    assert "set_next_enabled(False)" in body


def test_gui_warns_about_running_services_before_removing():
    assert "stop_hint" in GUI_SOURCE
    assert "running.web_ui" in GUI_SOURCE
    assert "running.ollama" in GUI_SOURCE


def test_gui_grades_the_warnings_instead_of_painting_them_all_red():
    # The three are not equivalent: an activated venv locks nothing, the web
    # UI genuinely makes the .venv removal fail in part, and a running Ollama
    # blocks neither. In one uniform red the eye treated them as equally
    # grave and skipped all three -- including the one that matters.
    assert "SEVERITY_FG" in GUI_SOURCE
    poll = GUI_SOURCE[
        GUI_SOURCE.index("def _poll", GUI_SOURCE.index("class WelcomePage")) :
        GUI_SOURCE.index("class OptionsPage")
    ]
    assert "severity=NOTE" in poll, "venv apenas ativado não é aviso, é nota"
    assert "severity=BLOCK" in poll, "a interface web é o único impedimento real"
    assert "severity=WARN" in poll, "o Ollama no ar não impede a remoção do projeto"


def test_gui_shows_the_stop_commands_as_a_block_it_can_copy():
    # Squeezed into prose and separated by semicolons they were unreadable,
    # uncopiable, and the separator collided with the shell's own syntax.
    assert '"; ".join(stop_hint' not in GUI_SOURCE, "comandos de volta para dentro da prosa"
    assert "stop_note" in GUI_SOURCE, "a prosa dos comandos tem função própria"
    assert "clipboard_append" in GUI_SOURCE
    # A fixed family ("Menlo", "Consolas") is a guess that fails silently --
    # Tk falls back to the proportional default and the block stops being
    # monospaced with nothing to show for it. The helper lives in wizard_gui
    # (one copy, both shells), so the intent is pinned on both sides.
    assert "_mono_font()" in GUI_SOURCE
    assert '("Menlo"' not in GUI_SOURCE
    wizard = (Path(__file__).resolve().parent.parent / "wizard_gui.py").read_text(
        encoding="utf-8"
    )
    assert "TkFixedFont" in wizard
    assert '("Menlo"' not in wizard


def test_gui_reuses_the_wizards_helpers_instead_of_copying_them():
    assert "from wizard_gui import _autowrap, _is_headless, _mono_font" in GUI_SOURCE


def test_gui_reads_the_options_on_the_main_thread_not_in_the_worker():
    # Reading a tk.BooleanVar from the worker thread raises "main thread is
    # not in main loop": Tk widgets belong to the thread running mainloop.
    # This bit really did fail that way -- the whole removal was swallowed
    # into "Erro inesperado" and nothing was deleted.
    assert "self.app.executed_choices = self.app.choices()" in GUI_SOURCE
    run_body = GUI_SOURCE[GUI_SOURCE.index("    def _run(self)") :]
    run_body = run_body[: run_body.index("    def _poll")]
    assert "self.app.choices()" not in run_body, "a thread de trabalho não pode ler tk vars"
    assert "executed_choices" in run_body


def test_gui_delegates_every_removal_to_the_shared_library():
    # The shell must not grow its own deletion logic -- one implementation,
    # so the GUI and the CLI cannot drift.
    assert "execute(self.app.plan" in GUI_SOURCE
    assert "shutil.rmtree" not in GUI_SOURCE
    assert "os.remove" not in GUI_SOURCE
