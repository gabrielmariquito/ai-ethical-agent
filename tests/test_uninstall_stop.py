"""A parada automática dos serviços.

O desinstalador gráfico existe para quem não abre terminal, mas mandava a pessoa
rodar comandos para parar a interface web -- inclusive ler um PID de uma saída e
transcrevê-lo. Quem não fazia isso via a remoção do `.venv` falhar com WinError
5 no `python.exe` que o servidor segurava: 3658 de 3661 itens removidos, e uma
instalação nem removida nem inteira.

Os testes daqui fixam as três coisas que podem dar errado ao parar sozinho --
matar processo alheio, matar o próprio pai, e não perceber que não parou -- e a
ordem entre o modelo e o servidor Ollama.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ver o fixture no conftest: os testes daqui injetam o `urlopen` que precisam,
# e este corte garante que os que NÃO injetam não caiam na porta de verdade.
pytestmark = pytest.mark.usefixtures("sem_rede_de_verdade")

from ethical_agent.uninstall import (  # noqa: E402
    FAILED,
    SKIPPED,
    STOPPED,
    Candidate,
    Choices,
    RunningServices,
    UninstallPlan,
    describe_totals,
    execute,
    our_web_ui_pids,
    plan_totals,
    stop_ollama,
    stop_web_ui,
)


class FakeRun:
    """Registra o que foi executado e devolve o que mandarem, porque o que
    importa nestes testes é quais comandos saíram e em que ordem."""

    def __init__(self, stdout_por_comando=None, returncode=0):
        self.calls: list[list[str]] = []
        self._stdout = stdout_por_comando or {}
        self._returncode = returncode

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        saida = ""
        for chave, valor in self._stdout.items():
            if any(chave in str(parte) for parte in cmd):
                saida = valor
                break

        class Proc:
            returncode = self._returncode
            stdout = saida
            stderr = ""

        return Proc()

    @property
    def flat(self) -> str:
        return " | ".join(" ".join(str(p) for p in c) for c in self.calls)


def _urlopen_que_responde(sequencia):
    """`web_ui_running` faz um GET; aqui a sequência decide o que ele encontra
    em cada chamada, para simular "parou" e "não parou"."""
    estado = {"i": 0}

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(url, timeout=None):
        i = min(estado["i"], len(sequencia) - 1)
        estado["i"] += 1
        if sequencia[i]:
            return Resp()
        raise OSError("recusado")

    return urlopen


def _plano(root: Path, *, web=False, ollama=False, com_venv=True, ollama_exe=None, model=None):
    venv = root / ".venv"
    mandatory = []
    if com_venv:
        venv.mkdir(parents=True, exist_ok=True)
        (venv / "marcador.txt").write_text("x", encoding="utf-8")
        mandatory.append(
            Candidate(key="venv", path=venv, kind="dir", size_bytes=10, label=".venv/")
        )
    return UninstallPlan(
        root=root,
        mandatory=tuple(mandatory),
        optional=(),
        model=model,
        ollama_exe=ollama_exe,
        running=RunningServices(web_ui=web, ollama=ollama, web_port=8765),
    )


# -- 1. a web para antes de o .venv sair ------------------------------------


def test_web_ui_is_stopped_before_the_venv_is_removed(tmp_path, monkeypatch):
    plano = _plano(tmp_path, web=True)
    exe = tmp_path / ".venv" / "Scripts" / "python.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")

    run = FakeRun({"netstat": f"  TCP    127.0.0.1:8765   0.0.0.0:0   LISTENING   4242\n"})
    monkeypatch.setattr(
        "ethical_agent.uninstall._process_image",
        lambda pid, **kw: (str(exe), f"{exe} -m ethical_agent serve --port 8765"),
    )
    # No ar na primeira sondagem, fora do ar depois do kill. Passado como hook
    # e não por monkeypatch: `urlopen` é argumento com valor padrão, preso no
    # momento em que a função foi definida, então trocar o atributo do módulo
    # depois não muda nada.
    resultados = execute(
        plano,
        Choices(),
        run=run,
        platform="win32",
        urlopen=_urlopen_que_responde([True, False]),
    )

    assert any("taskkill" in c and "4242" in " ".join(c) for c in run.calls), run.flat
    parada = [r for r in resultados if r.key == "web_ui"]
    assert parada and parada[0].status == STOPPED
    assert "foi fechada" in parada[0].detail
    venv = [r for r in resultados if r.key == "venv"]
    assert venv and venv[0].status != SKIPPED, "o .venv precisa ter sido removido de verdade"
    assert not (tmp_path / ".venv").exists()


# -- 2. processo alheio na porta não é morto --------------------------------


def test_a_stranger_on_the_port_is_never_killed(tmp_path, monkeypatch):
    plano = _plano(tmp_path, web=True)
    run = FakeRun({"netstat": "  TCP    127.0.0.1:8765   0.0.0.0:0   LISTENING   4242\n"})
    # Um python qualquer da máquina, fora do .venv desta raiz.
    monkeypatch.setattr(
        "ethical_agent.uninstall._process_image",
        lambda pid, **kw: (r"C:\Python313\python.exe", "python.exe outra_coisa.py"),
    )
    resultado = stop_web_ui(
        tmp_path, 8765, platform="win32", run=run, urlopen=_urlopen_que_responde([True])
    )

    assert not any("taskkill" in " ".join(c) for c in run.calls), run.flat
    assert resultado is not None and resultado.status == FAILED
    assert "NÃO FECHEI NADA" in resultado.detail
    # A frase de "tentei" não pode aparecer onde não se tentou: quem lê precisa
    # distinguir "decidi não agir" de "agi e falhei".
    assert "TENTEI FECHAR" not in resultado.detail
    assert "netstat" not in resultado.detail


# -- 3. parada que falha não deixa remover o .venv às cegas -----------------


def test_a_failed_stop_skips_the_venv_instead_of_trying_blind(tmp_path, monkeypatch):
    plano = _plano(tmp_path, web=True)
    exe = tmp_path / ".venv" / "Scripts" / "python.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")

    run = FakeRun({"netstat": "  TCP    127.0.0.1:8765   0.0.0.0:0   LISTENING   4242\n"})
    monkeypatch.setattr(
        "ethical_agent.uninstall._process_image",
        lambda pid, **kw: (str(exe), f"{exe} -m ethical_agent serve"),
    )
    monkeypatch.setattr("ethical_agent.uninstall.time.sleep", lambda _s: None)

    removidos: list[str] = []
    resultados = execute(
        plano,
        Choices(),
        run=run,
        platform="win32",
        # Continua respondendo depois do kill: não parou.
        urlopen=_urlopen_que_responde([True]),
        remove=lambda p: removidos.append(p),
        rmdir=lambda p: removidos.append(p),
    )

    parada = [r for r in resultados if r.key == "web_ui"][0]
    assert parada.status == FAILED
    assert "TENTEI FECHAR" in parada.detail
    assert "netstat" not in parada.detail and "taskkill" not in parada.detail
    venv = [r for r in resultados if r.key == "venv"][0]
    assert venv.status == SKIPPED
    assert not removidos, "nada do .venv pode ser tocado quando a parada falhou"


# -- 4. Ollama não escolhido não é tocado -----------------------------------


def test_ollama_is_untouched_when_the_user_did_not_choose_to_remove_it(tmp_path, monkeypatch):
    ollama = tmp_path / "ollama.exe"
    ollama.write_text("", encoding="utf-8")
    plano = _plano(tmp_path, ollama=True, com_venv=False, ollama_exe=ollama, model="llama3.2:3b")
    run = FakeRun()
    execute(
        plano,
        Choices(remove_ollama=False, remove_model=False),
        run=run,
        platform="win32",
        urlopen=_urlopen_que_responde([False]),
    )

    assert not any("taskkill" in " ".join(c) for c in run.calls), run.flat
    assert not any("pkill" in " ".join(c) for c in run.calls), run.flat


# -- 5. o modelo sai antes de o servidor parar ------------------------------


def test_the_model_is_removed_before_the_ollama_server_stops(tmp_path, monkeypatch):
    ollama = tmp_path / "ollama.exe"
    ollama.write_text("", encoding="utf-8")
    plano = _plano(tmp_path, ollama=True, com_venv=False, ollama_exe=ollama, model="llama3.2:3b")
    run = FakeRun()
    execute(
        plano,
        Choices(remove_model=True, remove_ollama=True),
        run=run,
        platform="win32",
        verify=lambda _p: False,
        urlopen=_urlopen_que_responde([False]),
    )

    indices_rm = [i for i, c in enumerate(run.calls) if "rm" in c]
    indices_kill = [i for i, c in enumerate(run.calls) if "taskkill" in " ".join(c)]
    assert indices_rm and indices_kill, run.flat
    # `ollama rm` fala com o servidor e falha sem ele.
    assert min(indices_rm) < min(indices_kill), f"o modelo tem de sair primeiro: {run.flat}"


def test_stop_ollama_never_runs_sudo_on_posix():
    # Rodar sudo sozinho travaria num prompt de senha que a janela não mostra.
    run = FakeRun()
    stop_ollama(platform="linux", run=run)
    assert "sudo" not in run.flat, run.flat
    assert "pkill" in run.flat


# -- 6. nunca mata a si mesmo nem o pai -------------------------------------


def test_the_uninstaller_never_kills_its_own_process_or_its_parent(tmp_path, monkeypatch):
    venv = tmp_path / ".venv" / "Scripts"
    venv.mkdir(parents=True, exist_ok=True)
    exe = venv / "python.exe"
    exe.write_text("", encoding="utf-8")

    eu, pai = os.getpid(), os.getppid()
    monkeypatch.setattr("ethical_agent.uninstall._listening_pids", lambda *a, **k: [eu, pai])
    # O pai do desinstalador relançado É o python do .venv, então o filtro de
    # caminho sozinho o aprovaria -- por isso a exclusão por PID existe.
    monkeypatch.setattr(
        "ethical_agent.uninstall._process_image",
        lambda pid, **kw: (str(exe), f"{exe} -m ethical_agent serve"),
    )

    nossos, alheios = our_web_ui_pids(tmp_path, 8765, platform="win32")

    assert eu not in nossos and eu not in alheios
    assert pai not in nossos and pai not in alheios
    assert nossos == []


def test_a_windows_venv_process_is_recognised_despite_the_base_executable(tmp_path, monkeypatch):
    """No Windows, `ExecutablePath` de um processo do venv aponta para o
    interpretador BASE, não para o `python.exe` do venv.

    Medido com o servidor de verdade no ar: PID 22072, iniciado com
    `.venv\\Scripts\\python.exe -m ethical_agent serve --port 8765`, tinha
    ExecutablePath = `C:\\...\\Python313\\python.exe`. A versão anterior desta
    função exigia o ExecutablePath dentro do .venv e por isso classificava o
    nosso próprio servidor como alheio -- ou seja, nunca o fecharia, e a
    remoção do .venv voltaria a falhar exatamente como falhou em campo.
    """
    venv = tmp_path / ".venv" / "Scripts"
    venv.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("ethical_agent.uninstall._listening_pids", lambda *a, **k: [22072])
    monkeypatch.setattr(
        "ethical_agent.uninstall._process_image",
        lambda pid, **kw: (
            r"C:\Users\alguem\AppData\Local\Programs\Python\Python313\python.exe",
            f'"{venv / "python.exe"}" -m ethical_agent serve --port 8765',
        ),
    )

    nossos, alheios = our_web_ui_pids(tmp_path, 8765, platform="win32")

    assert nossos == [22072], "o servidor do próprio projeto tem de ser reconhecido"
    assert alheios == []


def test_a_process_from_another_clone_is_not_ours(tmp_path, monkeypatch):
    # A linha de comando certa, mas o .venv de OUTRA cópia do repositório:
    # fechar esse seria derrubar a interface de outra instalação.
    outro = tmp_path.parent / "outra-copia" / ".venv" / "Scripts" / "python.exe"
    monkeypatch.setattr("ethical_agent.uninstall._listening_pids", lambda *a, **k: [777])
    monkeypatch.setattr(
        "ethical_agent.uninstall._process_image",
        lambda pid, **kw: (str(outro), f'"{outro}" -m ethical_agent serve --port 8765'),
    )

    nossos, alheios = our_web_ui_pids(tmp_path, 8765, platform="win32")

    assert nossos == []
    assert alheios == [777]


# -- 7. --dry-run não para nada ---------------------------------------------


def test_dry_run_stops_nothing(tmp_path, monkeypatch):
    ollama = tmp_path / "ollama.exe"
    ollama.write_text("", encoding="utf-8")
    plano = _plano(tmp_path, web=True, ollama=True, ollama_exe=ollama, model="llama3.2:3b")
    run = FakeRun()

    def explode(*a, **k):
        raise AssertionError("a simulação sondou a rede")

    resultados = execute(
        plano,
        Choices(remove_model=True, remove_ollama=True),
        dry_run=True,
        run=run,
        platform="win32",
        urlopen=explode,
    )

    assert run.calls == [], f"a simulação executou comandos: {run.flat}"
    assert (tmp_path / ".venv").exists()
    assert all(r.status != STOPPED for r in resultados)


# -- 8. as duas telas contam a mesma coisa ----------------------------------


def test_the_two_screens_count_the_same_thing(tmp_path):
    venv = Candidate(key="venv", path=tmp_path / ".venv", kind="dir", size_bytes=1000, label=".venv/")
    modelo = Candidate(key="model", path=None, kind="external", size_bytes=None, label="Modelo x")
    env = Candidate(key="env", path=tmp_path / ".env", kind="file", size_bytes=26, label=".env")
    plano = UninstallPlan(root=tmp_path, mandatory=(venv,), optional=(modelo, env))

    # O recorte da boas-vindas: só o automático, porque ela roda antes de
    # existir escolha.
    assert plan_totals(plano) == (1, 1000, 0)
    # O recorte do resumo: o automático mais o que foi marcado.
    assert plan_totals(plano, Choices(remove_env=True)) == (2, 1026, 0)
    # Tamanho desconhecido é dito, não somado como zero.
    quantos, total, sem_tamanho = plan_totals(plano, Choices(remove_model=True))
    assert (quantos, total, sem_tamanho) == (2, 1000, 1)
    assert "tamanho desconhecido" in describe_totals(plano, Choices(remove_model=True))


def test_the_welcome_screen_labels_its_number_as_the_automatic_slice():
    fonte = (Path(__file__).resolve().parent.parent / "uninstall_gui.py").read_text(encoding="utf-8")
    # Um total sem rótulo de escopo recria o defeito em escala menor: a pessoa
    # lê um número aqui, outro maior no resumo, e conclui que um está errado.
    assert "Sairão automaticamente" in fonte
    assert "Total automático" in fonte
    assert "Total a remover" in fonte
    # E o cálculo é um só, para os dois números não poderem divergir.
    assert "describe_totals" in fonte
    assert "sum(c.size_bytes or 0 for c in item.mandatory)" not in fonte


def test_the_screens_say_the_folder_is_not_deleted(tmp_path):
    import uninstall_gui

    texto = uninstall_gui.welcome_text(tmp_path)
    # "permanecem" soava como proteção; o que a pessoa precisa saber é que
    # sobrou uma tarefa para ela, e qual pasta é.
    #
    # Sem `.lower()` isto fixava a CAIXA da frase, e não a frase: a versão em
    # maiúsculas era uma escolha de ênfase, não o que o teste existe para
    # garantir. O que não pode sumir é a negação estar lá e ser sobre a pasta.
    assert "não apaga a pasta do projeto" in texto.lower()
    assert str(tmp_path) in texto
    assert "repositório" not in texto.lower()
