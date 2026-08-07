"""A recusa de dividir o conjunto curado é UMA frase, lida pelos dois caminhos.

`eval/dataset.json` é in-distribution por construção — quem escreveu as regras
escreveu os casos —, então "holdout" dele não é held out de nada. A CLI já
recusa (`test_divisao.py::test_dataset_curado_nao_e_dividido`). A tela passa a
recusar também, e **pela mesma constante**.

Por que isso é um teste e não uma convenção: tela e linha de comando
discordando sobre o mesmo dataset fariam aquele teste registrar uma regra válida
em só um dos caminhos. Não é lacuna — é garantia falsa, e garantia falsa ninguém
questiona.

O compartilhado é o **motivo**, verbatim nos dois. Cada caminho acrescenta o
próprio remédio, que é específico da interface por natureza (`--half full` na
CLI, o seletor na tela); é isso que mantém o stderr da CLI byte a byte igual ao
de hoje. O que este arquivo afirma é que o motivo é idêntico caractere a
caractere e que nenhum dos dois o carrega como literal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ethical_agent.__main__ import main
from webui_support import running_tools_server

CURADO = "dataset.json"
RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def server(tmp_path):
    running = running_tools_server(tmp_path, engine="rule")
    yield running
    running.close()


# ------------------------------------------------------------- a tela recusa


@pytest.mark.parametrize("metade", ("tune", "holdout", "ambas"))
def test_a_tela_recusa_dividir_o_conjunto_curado(server, metade):
    """Vermelho hoje por motivo próprio: `half` não existe no corpo, é ignorado
    em silêncio, e a tela devolve 200 com o dataset inteiro rotulado `full`.
    """
    status, body, _ = server.post(
        "/api/eval", {"dataset": CURADO, "half": metade, "config": {}}
    )
    assert status == 400, body
    assert body["error"] == "dataset_not_split"
    # As mesmas duas afirmações que `test_divisao.py:194-195` faz do stderr.
    assert "não é dividido" in body["message"]
    assert "in-distribution" in body["message"]


def test_a_tela_continua_avaliando_o_curado_inteiro(server):
    """O contraponto: recusar a metade não pode recusar o dataset."""
    status, body, _ = server.post("/api/eval", {"dataset": CURADO, "config": {}})
    assert status == 200, body
    avaliacao = body["avaliacoes"][0]
    assert avaliacao["divisao"]["metade"] == "full"
    assert avaliacao["divisao"]["casos"] == avaliacao["total_cases"] == 72


# --------------------------------------------- e é a MESMA frase nos dois lados


def test_o_motivo_e_o_mesmo_caractere_a_caractere_nos_dois_caminhos(server, capsys):
    """A exigência central: um lugar só, lido pelos dois caminhos.

    Vermelho hoje por motivo próprio: `evaluate.recusa_de_divisao` não existe.
    """
    from ethical_agent.evaluate import recusa_de_divisao

    motivo = recusa_de_divisao(CURADO)

    codigo = main(["eval", "--half", "tune"])
    erro_cli = capsys.readouterr().err
    assert codigo == 2

    _, body, _ = server.post("/api/eval", {"dataset": CURADO, "half": "tune", "config": {}})

    assert motivo in erro_cli, "a CLI parou de usar a constante"
    assert motivo in body["message"], "a tela parou de usar a constante"


def test_a_cli_nao_muda_de_comportamento(capsys):
    """O remédio da CLI continua nomeando a flag, e o código de saída é 2.

    Se esta afirmação cair junto com a unificação, a unificação levou junto algo
    que não era dela.
    """
    assert main(["eval", "--half", "tune"]) == 2
    erro = capsys.readouterr().err
    assert "--half full" in erro


# ------------------------------------------------- e nenhum dos dois a copia


@pytest.mark.parametrize(
    "arquivo",
    (
        "ethical_agent/__main__.py",
        "ethical_agent/webui/handlers_eval.py",
    ),
)
def test_o_motivo_nao_aparece_como_literal_em_nenhum_dos_dois(arquivo):
    """Guarda de texto-fonte, no padrão de `test_webui_audit_wording.py`.

    Uma frase igual escrita duas vezes anda sozinha. O teste acima já falharia
    se as duas divergissem — este falha antes, no momento em que alguém colar a
    segunda cópia, que é quando o conserto ainda é de uma linha.
    """
    from ethical_agent.evaluate import recusa_de_divisao

    # O trecho invariante da frase, sem o nome do arquivo que a `f-string`
    # interpola: é ele que não pode ser copiado.
    motivo = recusa_de_divisao("X")
    nucleo = motivo[motivo.index("não é dividido"):]

    fonte = (RAIZ / arquivo).read_text(encoding="utf-8")
    assert nucleo not in fonte, f"{arquivo} carrega a frase como literal"
    assert "recusa_de_divisao" in fonte, f"{arquivo} deveria ler a frase da fonte única"
