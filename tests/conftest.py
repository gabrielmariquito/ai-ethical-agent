"""Guarantees the repo root is on sys.path so tests can import root-level
modules (audit_tools, uninstall, uninstall_gui, wizard_gui) directly,
regardless of the directory or import-mode pytest is invoked with.
"""
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def sem_rede_de_verdade(monkeypatch):
    """Corta a sondagem HTTP do desinstalador antes que ela pergunte à máquina
    de quem roda a suíte.

    `execute()` re-sonda a porta da interface web de propósito -- o estado pode
    mudar entre montar o plano e confirmar a remoção --, e os testes que passam
    por `main()` não têm onde injetar o hook. Com a interface web aberta na
    8765, a sondagem achava um servidor vivo, corretamente NÃO conseguia provar
    que ele era da raiz temporária do teste, e recusava remover o `.venv`. O
    resultado eram 16 falhas que descreviam a máquina e não o código -- e que
    sumiam sozinhas quando a janela da interface estava fechada, que é a pior
    forma de um teste falhar.

    Não é autouse de propósito: a suíte da webui sobe servidor de verdade e
    precisa da rede. Quem quer o corte declara `pytestmark`.
    """

    def _recusa(url, timeout=None):
        raise OSError(f"a suíte não fala com a rede de verdade (tentou {url})")

    monkeypatch.setattr(urllib.request, "urlopen", _recusa)
