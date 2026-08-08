"""As duas cascas do desinstalador: `uninstall.py` é importado e dirigido de
verdade, e `uninstall_gui.py` mantém a técnica de texto-fonte porque precisa
de tkinter — e nenhum teste aqui passa a raiz real do repositório: versão longa em `997a6fe^`.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import uninstall

# Estes testes dirigem `main()`, que chama `execute()` lá dentro -- não há por
# onde injetar o hook da sondagem no call site. Ver o fixture no conftest.
pytestmark = pytest.mark.usefixtures("sem_rede_de_verdade")

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


def test_a_merely_activated_venv_says_nothing_at_all(tmp_path, capsys, monkeypatch):
    # Com `VIRTUAL_ENV` apontando para o .venv do projeto, o modo texto
    # imprimia um aviso mandando rodar `deactivate` depois. Saiu: no cmd.exe
    # `deactivate` é `.venv\\Scripts\\deactivate.bat`, apagado pela própria
    # remoção, e um diretório inexistente no PATH é ignorado em silêncio pelos
    # dois sistemas. Sobrava um aviso sobre um não-problema, prescrevendo um
    # comando que ele mesmo apagava.
    root = _make_root(tmp_path)
    monkeypatch.setenv("VIRTUAL_ENV", str(root / ".venv"))

    code = uninstall.main(["--dry-run"], root=root, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_OK
    err = capsys.readouterr().err
    assert "deactivate" not in err
    assert err.strip() == "", f"nada deve ir ao stderr por venv apenas ativado: {err!r}"


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
    # Era "NUNCA REMOVIDO", que soava como proteção e fazia quem lia terminar
    # achando que a máquina ficaria limpa. Agora diz o que o programa não faz,
    # e a prévia mostra a pasta pelo caminho, não pela palavra "repositório".
    assert "NÃO APAGA A PASTA DO PROJETO" in out
    assert str(root) in out
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
    #
    # A asserção do código foi INVERTIDA de propósito: era EXIT_OK, é
    # EXIT_REFUSED. Não é ajuste de conveniência para um teste que quebrou --
    # foi a mudança deliberada desta leva. O que o teste protegia continua
    # protegido e continua asseverado abaixo: nada é removido, o .venv fica.
    # O que mudou é só como o programa RELATA que não fez nada, porque sair 0
    # fazia `uninstall.py --cli && echo ok` anunciar sucesso de uma remoção que
    # não houve. Ver `main()` e DECISOES.
    root = _make_root(tmp_path)
    code = uninstall.main([], root=root, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_REFUSED
    assert "nada foi removido" in capsys.readouterr().out
    assert (root / ".venv").exists()


def test_dry_run_without_a_tty_still_succeeds(tmp_path):
    # O par do teste acima, e os dois se protegem: a remoção de verdade sem TTY
    # é recusa (3), a simulação sem TTY é sucesso (0). `--dry-run` lista sem
    # agir, então "nada foi removido" é o resultado esperado dele -- um script
    # que confere o plano não pode receber não-zero de uma operação que deu
    # certo.
    #
    # Hoje isso vale por ORDEM: o return do --dry-run vem antes do ramo do
    # isatty em main(). Ordem não é garantia, e uma refatoração que trocasse os
    # dois blocos de lugar quebraria isto em silêncio -- daí a asserção.
    root = _make_root(tmp_path)
    code = uninstall.main(["--dry-run", "--no-probe"], root=root, ask=_answers(), isatty=_no_tty)
    assert code == uninstall.EXIT_OK
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
    # `execute()` resolve `remove_path` do namespace do módulo em tempo de
    # chamada; o que se assevera aqui é que a casca expõe a falha como código
    # de saída e texto legível: versão longa em `997a6fe^`.
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


# Ordem das perguntas interativas com `--no-probe` numa raiz de `_make_root`:
# mover a trilha, apagar a trilha, remover o modelo, remover o `.env`,
# confirmação final — responder "sim" à primeira consome uma resposta extra.


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


# O ponto de entrada único: `run()` decide entre janela e modo texto, e
# `main()` fica puramente CLI, então nenhum teste de CLI abre janela.


@pytest.fixture
def dispatch(monkeypatch):
    """Espiões para os dois destinos de `run()`, que só decide para onde ir —
    substituir `main()` impede que estes testes montem um plano de verdade: versão longa em `997a6fe^`.
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
    # O ponto mais frágil desta mudança: se o import de tkinter subir para o
    # topo, o modo texto passa a exigir Tk e o caminho de volta deixa de
    # existir. Roda em subprocesso por isso: versão longa em `997a6fe^`.
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


# -- relançar fora do venv -------------------------------------------------
#
# Rodar com o Python de dentro do .venv é um beco sem saída: no Windows o
# executável em uso não pode ser apagado. Em vez da tela de erro, o programa
# troca de interpretador sozinho. O gatilho medido não é o clique: a
# associação `.py` é o `py` PELADO, que desde o 3.11 prefere o virtualenv
# ativo quando `VIRTUAL_ENV` está no ambiente -- `py -3` o ignora.

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = REPO_ROOT / ".venv" / (
    "Scripts/python.exe" if sys.platform == "win32" else "bin/python3"
)
needs_venv = pytest.mark.skipif(
    not VENV_PYTHON.exists(), reason="sem .venv no repo: o caso de borda não existe aqui"
)


def _venv_root(tmp_path):
    """Uma raiz de projeto cujo Python corrente mora dentro do próprio .venv --
    o estado que o relançamento existe para desfazer."""
    root = _make_root(tmp_path)
    fake_python = root / ".venv" / "Scripts" / "python.exe"
    fake_python.parent.mkdir(parents=True, exist_ok=True)
    fake_python.write_text("", encoding="utf-8")
    return root, fake_python


class _Spawn:
    """Um `subprocess.call` de mentira que anota a chamada e devolve o código
    combinado."""

    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, command, env=None, cwd=None):
        self.calls.append({"command": list(command), "env": env, "cwd": cwd})
        return self.returncode


def _found(*prefix):
    return lambda root=None: list(prefix)


def _not_found(root=None):
    return None


def test_running_from_the_venv_relaunches_with_the_system_python(tmp_path, monkeypatch, capsys):
    root, fake_python = _venv_root(tmp_path)
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))
    spawn = _Spawn()

    code = uninstall._maybe_relaunch_outside_venv(
        [], root=root, env={}, find_python=_found("py", "-3"), spawn=spawn
    )

    assert code == 0
    assert len(spawn.calls) == 1, "relançou mais de uma vez"
    command = spawn.calls[0]["command"]
    assert command[:2] == ["py", "-3"]
    # Caminho absoluto: o filho pode nascer com outro cwd que o do pai.
    assert Path(command[2]) == (REPO_ROOT / "uninstall.py")
    assert "relançando" in capsys.readouterr().err, "trocar de processo em silêncio confunde"


def test_the_marker_stops_the_loop_even_when_the_detection_says_relaunch(tmp_path, monkeypatch):
    # A TRAVA. Se a detecção estiver errada, o filho também se acha no venv e
    # relançaria para sempre. Este é o teste mais importante desta leva.
    root, fake_python = _venv_root(tmp_path)
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))
    assert uninstall.running_inside_venv(root), "a detecção precisa estar dizendo 'relance'"
    spawn = _Spawn()

    code = uninstall._maybe_relaunch_outside_venv(
        [],
        root=root,
        env={uninstall.RELAUNCH_MARKER: "1"},
        find_python=_found("py", "-3"),
        spawn=spawn,
    )

    assert code is None, "com a marca, tem de seguir neste processo e cair na recusa"
    assert spawn.calls == [], "relançou com a marca presente -- é o laço infinito"


def test_the_marker_is_read_before_the_detection_runs(tmp_path, monkeypatch):
    # A ordem importa: a marca é a rede de segurança PARA a detecção, então
    # não pode depender dela para ser consultada.
    root, fake_python = _venv_root(tmp_path)
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))

    def explode(*args, **kwargs):
        raise AssertionError("a detecção foi consultada apesar da marca")

    monkeypatch.setattr(uninstall, "running_inside_venv", explode)
    assert (
        uninstall._maybe_relaunch_outside_venv(
            [], root=root, env={uninstall.RELAUNCH_MARKER: "1"}
        )
        is None
    )


def test_the_child_gets_the_marker_and_the_parents_environment_is_left_alone(
    tmp_path, monkeypatch
):
    root, fake_python = _venv_root(tmp_path)
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))
    parent_env = {"PATH": "/algum/lugar"}
    spawn = _Spawn()

    uninstall._maybe_relaunch_outside_venv(
        [], root=root, env=parent_env, find_python=_found("py", "-3"), spawn=spawn
    )

    child_env = spawn.calls[0]["env"]
    assert child_env[uninstall.RELAUNCH_MARKER] == "1"
    assert child_env["PATH"] == "/algum/lugar", "o filho perdeu o resto do ambiente"
    assert uninstall.RELAUNCH_MARKER not in parent_env, "o ambiente do pai foi mutado"


def test_without_a_system_python_it_falls_back_to_todays_refusal(tmp_path, monkeypatch, capsys):
    # `py` é o launcher do Windows e não vem com toda instalação. Sem ele e
    # sem os outros candidatos, o caminho de volta é a tela de erro de hoje --
    # e nunca o silêncio, que seria pior do que a tela.
    root, fake_python = _venv_root(tmp_path)
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))
    spawn = _Spawn()

    code = uninstall._maybe_relaunch_outside_venv(
        [], root=root, env={}, find_python=_not_found, spawn=spawn
    )

    assert code is None, "tem de seguir no processo corrente e chegar na recusa"
    assert spawn.calls == []
    # E a recusa de fato acontece, com a mensagem de sempre.
    assert uninstall.main(
        ["--remove-env", "--yes"], root=root, ask=_answers(), isatty=_no_tty
    ) == uninstall.EXIT_REFUSED
    assert "Python do próprio venv" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["--dry-run"],
        ["--dry-run", "--no-probe"],
        ["--move-logs-to", "backup dir", "--port", "9000"],
        ["--cli", "--remove-env", "--yes"],
    ],
)
def test_every_argument_survives_the_relaunch(tmp_path, monkeypatch, argv):
    # --dry-run em especial: é a forma segura de conferir o que seria apagado,
    # está no README, e perdê-la no relançamento transformaria uma simulação
    # numa remoção.
    root, fake_python = _venv_root(tmp_path)
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))
    spawn = _Spawn()

    uninstall._maybe_relaunch_outside_venv(
        argv, root=root, env={}, find_python=_found("py", "-3"), spawn=spawn
    )

    assert spawn.calls[0]["command"][3:] == argv


def test_the_child_inherits_the_working_directory(tmp_path, monkeypatch):
    # `--move-logs-to backup` relativo tem de continuar significando o mesmo
    # diretório depois da troca de processo.
    root, fake_python = _venv_root(tmp_path)
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))
    spawn = _Spawn()

    uninstall._maybe_relaunch_outside_venv(
        ["--move-logs-to", "backup"], root=root, env={}, find_python=_found("py"), spawn=spawn
    )

    assert Path(spawn.calls[0]["cwd"]).resolve() == Path.cwd().resolve()


def test_the_system_python_path_does_not_relaunch(tmp_path, monkeypatch):
    # Quem já chama certo (`py -3 uninstall.py`) segue direto, sem processo a
    # mais e sem janela a mais.
    root = _make_root(tmp_path)
    monkeypatch.setattr(uninstall.sys, "executable", str(tmp_path / "sistema" / "python.exe"))
    spawn = _Spawn()

    code = uninstall._maybe_relaunch_outside_venv(
        [], root=root, env={}, find_python=_found("py", "-3"), spawn=spawn
    )

    assert code is None
    assert spawn.calls == []


@pytest.mark.parametrize(
    "returncode",
    [uninstall.EXIT_FAILURES, 2, uninstall.EXIT_REFUSED, 42, uninstall.EXIT_OK],
)
def test_the_childs_exit_code_is_propagated(tmp_path, monkeypatch, returncode):
    # Propagar 0 é fácil de acertar por acidente; o que prova que o contrato
    # atravessa é o não-zero -- EXIT_FAILURES, o 2 do argparse e EXIT_REFUSED.
    # O 0 fica por último, como caso de controle.
    root, fake_python = _venv_root(tmp_path)
    monkeypatch.setattr(uninstall.sys, "executable", str(fake_python))
    spawn = _Spawn(returncode=returncode)

    code = uninstall._maybe_relaunch_outside_venv(
        [], root=root, env={}, find_python=_found("py", "-3"), spawn=spawn
    )

    assert code == returncode
    assert code is not None, "None significaria 'siga neste processo', não 'saiu 0'"


def test_the_cli_terminates_without_a_tty_instead_of_waiting_forever(tmp_path):
    """Processo de verdade, stdin fechado, e uma guarda de tempo.

    Todo o resto da cobertura de "sem TTY" injeta `isatty=_no_tty`, o que prova
    a LÓGICA e não que o processo termina. O medo que originou esta leva foram
    dois processos de pé por horas -- e um `input()` alcançado por engano não
    apareceria em nenhum teste com hook, porque o hook nunca chega a `input()`.

    O `timeout=` é o ponto: um teste que verifica "não trava" travando é o pior
    resultado possível, então ele falha por TimeoutExpired em vez de pendurar a
    suíte inteira.

    Chama `main(root=...)` em vez de rodar `uninstall.py` direto porque o script
    deriva a raiz de `__file__`: invocá-lo apontaria para o repositório de
    verdade. O que importa aqui é o processo e o stdin serem reais -- é o
    `sys.stdin.isatty()` de verdade que está sob teste, não o hook.

    **Pipe e não DEVNULL**, e isso foi medido: no Windows `subprocess.DEVNULL`
    é o `NUL`, que é um dispositivo de CARACTERE, e `isatty()` devolve `True`
    para ele. Um `uninstall.py < NUL` portanto NÃO exercita este caminho -- ele
    entra no ramo interativo e só não pendura porque `ask_yes_no` captura
    `EOFError`. Quem de fato não tem TTY é o pipe.
    """
    root = _make_root(tmp_path)
    programa = (
        "import sys; sys.path.insert(0, %r)\n"
        "from pathlib import Path\n"
        "import uninstall\n"
        "assert not sys.stdin.isatty(), 'o teste precisa de stdin sem TTY'\n"
        "sys.exit(uninstall.main([], root=Path(%r)))\n"
    ) % (str(REPO_ROOT), str(root))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", programa],
            input="",
            capture_output=True,
            text=True,
            # O filho chama ensure_utf8_stdio() e escreve UTF-8; sem declarar
            # isto, o pai decodifica no cp1252 do console e o primeiro acento
            # da mensagem derruba a leitura (política D-4).
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            "o --cli pendurou sem TTY em vez de sair -- foi exatamente este o "
            "estado que deixou dois processos de pé por horas"
        )

    assert proc.returncode == uninstall.EXIT_REFUSED, proc.stdout + proc.stderr
    # Sem esta linha o teste passaria pela recusa ERRADA: a de rodar dentro do
    # venv devolve o mesmo 3, e foi o que aconteceu na primeira versão dele.
    assert "Sem terminal interativo" in proc.stdout, "recusou, mas por outro motivo"
    # A mensagem tem de nomear a flag que dispensaria a pergunta; sem isso, a
    # recusa diz "não posso" sem dizer o que fazer.
    assert "--yes" in proc.stdout
    assert (root / ".venv").exists(), "a recusa não pode ter removido nada"


def test_stdin_from_the_null_device_also_terminates(tmp_path):
    """O outro caminho de "sem humano", e ele NÃO passa pela guarda de TTY.

    Medido: no Windows o `NUL` é um dispositivo de caractere e `isatty()`
    devolve `True` para ele. Então `uninstall.py < NUL` -- que é como um script
    .bat naturalmente invocaria isto -- entra no ramo INTERATIVO, e quem impede
    o travamento ali é outra coisa: o `EOFError` capturado em `ask_yes_no`,
    que responde "não" e cancela.

    Duas defesas em camadas, e o teste existe para que nenhuma das duas saia
    sem a outra ser notada.
    """
    root = _make_root(tmp_path)
    programa = (
        "import sys; sys.path.insert(0, %r)\n"
        "from pathlib import Path\n"
        "import uninstall\n"
        "print('ISATTY=%%s' %% sys.stdin.isatty())\n"
        "sys.exit(uninstall.main([], root=Path(%r)))\n"
    ) % (str(REPO_ROOT), str(root))
    try:
        proc = subprocess.run(
            [sys.executable, "-c", programa],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("stdin no dispositivo nulo pendurou o programa")

    assert proc.returncode in (uninstall.EXIT_OK, uninstall.EXIT_REFUSED), (
        proc.stdout + proc.stderr
    )
    assert (root / ".venv").exists(), "sem ninguém para confirmar, nada pode ser removido"


def test_the_graphical_path_never_reaches_the_tty_check(tmp_path):
    # A janela NUNCA tem TTY, então a recusa por falta de terminal não pode
    # alcançá-la: se alcançasse, o desinstalador gráfico passaria a recusar
    # sempre. A separação é `run()`, que só cai em main() quando alguma flag
    # pede modo texto ou não há sessão gráfica.
    chamou = {}

    def open_gui(port):
        chamou["port"] = port
        return uninstall.EXIT_OK

    code = uninstall.run([], open_gui=open_gui, graphical=True)

    assert code == uninstall.EXIT_OK
    assert chamou == {"port": 8765}, "a janela não foi aberta -- caiu no modo texto"


def test_the_system_python_search_refuses_a_candidate_inside_the_venv(tmp_path, monkeypatch):
    # O alias da Microsoft Store e o `python` de um shell com o venv ativo são
    # os dois jeitos de "achar" um interpretador que não serve. A peneira é o
    # mesmo `running_inside_venv` que detectou o problema, e não uma segunda
    # heurística que divergiria dele.
    root, fake_python = _venv_root(tmp_path)

    found = uninstall._system_python(
        root,
        which=lambda name: str(fake_python),
        exists=lambda path: True,
        base_executable=str(fake_python),
        base_prefix=str(root / ".venv"),
    )

    assert found is None, "aceitou um Python de dentro do venv que vai apagar"


def test_the_system_python_search_falls_back_when_the_launcher_is_missing(tmp_path):
    # `py` ausente (instalação pela Microsoft Store, por exemplo) não pode ser
    # o fim: o Python que criou o venv está registrado em sys._base_executable.
    root, _fake_python = _venv_root(tmp_path)
    base = tmp_path / "sistema" / "python.exe"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_text("", encoding="utf-8")

    found = uninstall._system_python(
        root, which=lambda name: None, base_executable=str(base), base_prefix=str(tmp_path)
    )

    assert found == [str(base)]


def test_the_system_python_search_gives_up_instead_of_guessing(tmp_path):
    root, _fake_python = _venv_root(tmp_path)

    found = uninstall._system_python(
        root,
        which=lambda name: None,
        exists=lambda path: False,
        base_executable=None,
        base_prefix=str(tmp_path / "sumiu"),
    )

    assert found is None, "sem candidato real, devolver algo faria o relançamento falhar calado"


def test_the_entry_point_checks_the_relaunch_before_dispatching():
    # Instruções, não a palavra: o comentário do bloco explica a regra e diz
    # "run()" em prosa, legitimamente -- a mesma armadilha do guarda de
    # tkinter mais abaixo, e ela pegou este teste antes de pegar o código.
    source = (REPO_ROOT / "uninstall.py").read_text(encoding="utf-8")
    block = source[source.index('if __name__ == "__main__":') :]
    statements = "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )
    assert "_maybe_relaunch_outside_venv" in statements
    assert statements.index("_maybe_relaunch_outside_venv") < statements.index("sys.exit(run())"), (
        "a detecção tem de vir antes de run(), que é quem importa tkinter e abre a janela"
    )


# -- e as mesmas coisas de verdade, em processo separado -------------------


def _run_real(*argv, env_extra=None, script="uninstall.py"):
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env.pop(uninstall.RELAUNCH_MARKER, None)
    env.update(env_extra or {})
    return subprocess.run(
        [str(VENV_PYTHON), script, *argv],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=REPO_ROOT, env=env, timeout=180,
    )


@needs_venv
def test_end_to_end_the_venv_python_relaunches_and_the_dry_run_survives():
    # O caminho inteiro, sem nada injetado: o Python do .venv, o relançamento
    # de verdade, e o filho fazendo a simulação. --dry-run é o que torna isto
    # seguro de rodar numa suíte.
    proc = _run_real("--dry-run", "--no-probe")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "relançando" in proc.stderr
    assert "SIMULAÇÃO" in proc.stdout, "o --dry-run não sobreviveu à troca de processo"
    assert "Python do próprio venv" not in proc.stderr, (
        "o filho ainda se acha no venv -- o relançamento não trocou de interpretador"
    )
    assert (REPO_ROOT / ".venv").exists(), "uma simulação não apaga nada"


@needs_venv
def test_end_to_end_the_marker_stops_the_relaunch_for_real():
    # A trava do laço fora do laboratório: com a marca no ambiente, o processo
    # segue sendo o do venv e cai na recusa de sempre.
    proc = _run_real("--dry-run", "--no-probe", env_extra={uninstall.RELAUNCH_MARKER: "1"})

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "relançando" not in proc.stderr, "relançou com a marca -- é o laço"
    assert "Python do próprio venv" in proc.stderr, "seguiu no venv, como tinha de seguir"


@needs_venv
def test_end_to_end_a_nonzero_exit_code_crosses_the_relaunch():
    # `--port abc` é recusado pelo argparse do FILHO com código 2. Se o pai
    # desanexasse ou engolisse o retorno, isto sairia 0 e ninguém notaria.
    proc = _run_real("--port", "abc")

    assert "relançando" in proc.stderr, "sem relançamento este teste não prova nada"
    assert proc.returncode == 2, (
        f"o código do filho não atravessou: saiu {proc.returncode}"
    )


# -- a janela não é uma segunda entrada ------------------------------------
#
# `uninstall_gui.py` tem `__main__` próprio, e por ele o relançamento não
# acontecia: abrir o arquivo direto (clique, Run do IDE, `python
# uninstall_gui.py`) levava de volta ao beco que a leva do relançamento
# fechou. Ele não é um ponto de entrada legítimo -- a docstring do próprio
# arquivo, o README e test_wizard_gui.py já dizem que a entrada é
# `uninstall.py` --, então o `__main__` dele DELEGA em vez de duplicar a
# política. Recusar imprimindo não serviria: dependendo de como o arquivo foi
# aberto, a mensagem some junto com o console, e some justamente para quem
# precisa lê-la.


def test_the_window_module_delegates_instead_of_being_a_second_entry_point():
    block = GUI_SOURCE[GUI_SOURCE.index('if __name__ == "__main__":') :]
    statements = "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )
    assert "_maybe_relaunch_outside_venv" in statements, (
        "o __main__ da janela pula a trava do laço e o relançamento"
    )
    assert "uninstall.run" in statements, (
        "tem de cair no mesmo dispatch de uninstall.py, não em main() daqui"
    )
    assert "sys.argv[1:]" in statements, "os argumentos originais têm de seguir junto"
    assert statements.index("_maybe_relaunch_outside_venv") < statements.index("uninstall.run"), (
        "o relançamento vem antes do dispatch, como em uninstall.py"
    )


def test_the_window_function_itself_never_relaunches():
    # `_open_gui` chama `uninstall_gui.main()` DENTRO do processo já relançado.
    # Se a trava morasse em main(), ela rodaria de novo ali e poderia gerar um
    # neto -- a política fica no __main__, que só existe na execução direta.
    body = GUI_SOURCE[GUI_SOURCE.index("def main(") : GUI_SOURCE.index('if __name__ == "__main__":')]
    assert "_maybe_relaunch_outside_venv" not in body


def test_the_single_entry_point_decision_is_still_guarded_elsewhere():
    # Esta leva reafirma a decisão que test_wizard_gui.py já fixa; se alguém
    # transformar a janela em entrada documentada, os dois têm de falhar.
    wizard_tests = (REPO_ROOT / "tests" / "test_wizard_gui.py").read_text(encoding="utf-8")
    assert 'assert "uninstall_gui.py" not in readme' in wizard_tests
    # 2026-08-08: o README foi reescrito com a estrutura do relatório e a seção
    # `### Desinstalação` deixou de existir. A guarda não sai com ela -- passa a
    # valer sobre o arquivo inteiro, o que é exigência MAIOR que a anterior:
    # antes a janela podia ser citada em qualquer outra seção sem que ninguém
    # reclamasse, agora não pode em nenhuma.
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "uninstall_gui.py" not in readme, "o README voltou a apontar para a janela"


def test_the_readme_does_not_claim_what_opens_a_py_file():
    # Medido: o verbo `open` de `.py` nesta máquina resolve para o PyCharm,
    # apesar de `ftype` dizer `py.exe`. Qual programa abre um `.py` varia por
    # instalação e não é o mecanismo -- o mecanismo é qual interpretador acaba
    # rodando o script, que é o que a detecção olha.
    #
    # 2026-08-08: o README foi reescrito e a seção `### Desinstalação` saiu com
    # ele. A metade NEGATIVA desta guarda sobrevive inteira, e mais forte, agora
    # sobre o arquivo todo. A metade POSITIVA -- "o mecanismo real tem de estar
    # dito" -- não sobrevive: `VIRTUAL_ENV` deixou de aparecer em qualquer `.md`
    # do repositório, e a remoção foi deliberada. Ela segue até onde o mecanismo
    # ainda é afirmável, que é a fonte que o implementa. Fica registrado que o
    # que se perdeu é a exigência de o usuário ler isso na documentação, e não a
    # de o programa fazer isso. Era:
    #     assert "VIRTUAL_ENV" in secao, "o mecanismo real tem de estar dito"
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "a associação de `.py` usa" not in readme
    fonte = (REPO_ROOT / "uninstall.py").read_text(encoding="utf-8")
    assert "VIRTUAL_ENV" in fonte, "a detecção deixou de olhar o mecanismo real"


@needs_venv
def test_end_to_end_opening_the_window_module_directly_relaunches_too():
    # `--dry-run` não é sequer flag do parser de uninstall_gui.py: se ela
    # funciona por aqui, a delegação aconteceu E o relançamento também.
    proc = _run_real("--dry-run", "--no-probe", script="uninstall_gui.py")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "relançando" in proc.stderr, "abrir a janela direto continuava no venv"
    assert "SIMULAÇÃO" in proc.stdout, "não delegou: --dry-run não existe no parser da janela"
    assert "Python do próprio venv" not in proc.stderr
    assert (REPO_ROOT / ".venv").exists()


@needs_venv
def test_end_to_end_the_window_module_honours_the_loop_lock():
    proc = _run_real(
        "--dry-run", "--no-probe",
        script="uninstall_gui.py",
        env_extra={uninstall.RELAUNCH_MARKER: "1"},
    )

    assert "relançando" not in proc.stderr, "relançou com a marca -- é o laço, pela outra porta"
    assert "Python do próprio venv" in proc.stderr


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
    # O requisito central da tela de opções — nada é removido porque a pessoa
    # não olhou —, dito como "nenhuma começa marcada" e não como contagem:
    # versão longa em `997a6fe^`.
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


def test_gui_offers_moving_the_trail_before_it_offers_deleting_it():
    # A segunda caixa ("Deseja deletar todos os arquivos?") saiu da tela: ela
    # repetia a decisão que a caixa de cima já tomou. O que não pode sair é a
    # saída não-destrutiva -- apagar só é uma escolha de verdade se mover
    # estiver ali ao lado --, e o atrito continua na tela de resumo, que lista
    # o que será apagado antes do botão Remover.
    assert "logs_confirm" not in GUI_SOURCE
    body = GUI_SOURCE[GUI_SOURCE.index("class OptionsPage") : GUI_SOURCE.index("class SummaryPage")]
    assert "move_logs_to" in body
    assert "Mover para..." in body


def test_gui_offers_moving_the_trail_instead_of_deleting_it():
    assert "filedialog.askdirectory" in GUI_SOURCE
    assert "move_logs_to" in GUI_SOURCE


def test_gui_refuses_to_run_from_the_venv_it_would_delete():
    assert "running_inside_venv" in GUI_SOURCE
    body = GUI_SOURCE[GUI_SOURCE.index("class WelcomePage") : GUI_SOURCE.index("class OptionsPage")]
    assert "set_next_enabled(False)" in body


def test_gui_never_asks_the_user_to_run_a_terminal_command():
    # Este teste era o oposto: exigia `stop_hint` na janela. A janela existe
    # para quem não abre terminal, e ela mandava rodar `netstat -ano | findstr
    # :8765`, ler o PID na saída e transcrevê-lo num `taskkill`. Agora quem
    # para os serviços é o desinstalador (stop_web_ui/stop_ollama), então
    # pedir comando aqui é regressão, não funcionalidade.
    assert "stop_hint" not in GUI_SOURCE
    assert "stop_note" not in GUI_SOURCE
    assert "netstat" not in GUI_SOURCE
    assert "taskkill" not in GUI_SOURCE
    # E sem bloco copiável, porque não sobrou comando para copiar.
    assert "clipboard_append" not in GUI_SOURCE


def test_the_welcome_screen_has_no_advice_cards_left():
    # Houve aqui uma graduação de severidade (nota / atrapalha / a remoção vai
    # falhar em parte), porque um vermelho uniforme fazia o olho tratar os três
    # avisos como igualmente graves e pular os três: versão longa em `997a6fe^`.
    #
    # Os três cartões saíram -- os da interface web e do Ollama quando a parada
    # virou automática, o do venv apenas ativado por avisar sobre um
    # não-problema --, e a graduação saiu com o último. O que este teste fixa
    # agora é o estado que sobrou: nenhum cartão, e nenhuma estrutura órfã
    # esperando por um. Reintroduzir aviso na tela de boas-vindas quebra aqui,
    # que é onde se lê por que os anteriores não estão mais lá.
    # Statements, não as palavras: os comentários que explicam a remoção citam
    # `_AdviceCard` e a graduação em prosa, de propósito -- é lá que se lê por
    # que eles não estão mais aqui. Mesma razão do teste do import de tkinter.
    for morto in (r"^class _AdviceCard", r"^\s*def _add_advice", r"^SEVERITY_FG",
                  r"severity=", r"self\.advice"):
        assert not re.search(morto, GUI_SOURCE, re.MULTILINE), (
            f"{morto!r} voltou sem passar por aqui"
        )
    poll = GUI_SOURCE[
        GUI_SOURCE.index("def _poll", GUI_SOURCE.index("class WelcomePage")) :
        GUI_SOURCE.index("class OptionsPage")
    ]
    assert "activated_warning" not in poll


def test_the_uninstaller_stops_the_services_instead_of_dictating_commands():
    UNINST_SOURCE = (Path(__file__).resolve().parent.parent / "ethical_agent" / "uninstall.py").read_text(
        encoding="utf-8"
    )
    # A parada mora no módulo de helpers, testável sem tkinter, como o resto.
    for nome in ("def stop_web_ui", "def stop_ollama", "def our_web_ui_pids"):
        assert nome in UNINST_SOURCE
    # O que `stop_ollama` de fato roda no POSIX é asserção de comportamento, em
    # test_uninstall_stop.py: um teste de texto-fonte aqui tropeçaria no
    # comentário que explica por que aquele comando ficou de fora.


def test_the_stop_commands_are_still_monospaced_where_they_survive():
    # Família fixa é um palpite que falha em silêncio — o Tk cai para a
    # proporcional e o bloco deixa de ser monoespaçado sem avisar: versão longa em `997a6fe^`.
    # A asserção sobre o wizard sobrevive à saída do bloco copiável do
    # desinstalador: ela sempre foi sobre o INSTALADOR, que ainda mostra
    # comandos e ainda precisa da fonte certa.
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
    # Ler um `BooleanVar` da thread de trabalho levanta "main thread is not in
    # main loop", e isto falhou assim de verdade: versão longa em `997a6fe^`.
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
