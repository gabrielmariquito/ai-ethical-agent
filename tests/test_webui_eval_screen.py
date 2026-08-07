"""Guardas de texto-fonte sobre a tela de Eval, no padrão de `test_webui_nav.py`.

A suíte nunca executa JS, então isto lê os módulos como texto. Grosseiro, e de
propósito: não checa que a tela está certa, só que os erros específicos pelos
quais ela foi escrita não podem voltar sem ninguém notar.

Os erros, nomeados:

1. **O motor do eval vazando para a conversa.** O painel de Configuração é
   compartilhado por todas as telas e persiste em `sessionStorage`; trocar a
   engine no `/eval` trocava a que o `/` mandava, na mesma aba. O controle desta
   tela é local, e "local" tem três propriedades verificáveis: não é campo do
   painel, não tem listener que grave, e viaja no topo do pedido.

2. **A caixa que não dizia de que dataset era.** Uma captura de tela de uma
   caixa só tem de se explicar sozinha.

3. **`null` lido como `false`.** `acuracia_comparavel` é `null` em `full` — "não
   computei o gap" não é "as metades não são comparáveis". Mesma disciplina do
   `undefined` em `nav.js`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "ethical_agent" / "webui" / "static"
EVAL_JS = STATIC / "js" / "tools" / "eval.js"
EVAL_HTML = STATIC / "eval.html"


@pytest.fixture(scope="module")
def js() -> str:
    return EVAL_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return EVAL_HTML.read_text(encoding="utf-8")


# ------------------------------------ 1. o motor é local, e local é verificável


def test_a_tela_de_eval_nunca_escreve_no_armazenamento_compartilhado(js):
    # `saveStoredConfig` só existe em config-panel.js e é o único caminho para
    # o sessionStorage. Esta tela não pode alcançá-lo por nenhum meio.
    assert "sessionStorage" not in js
    assert "saveStoredConfig" not in js


def _fatia(texto: str, inicio: str, fim: str, onde: str) -> str:
    """Recorta entre duas âncoras, afirmando cada uma antes de cortar.

    Sem isto, um `.index()` que não acha levanta `ValueError: substring not
    found` — vermelho idêntico para "o alvo ainda não existe" e para "o teste
    está procurando a string errada". O segundo caso só apareceria depois da
    implementação, quando o vermelho persistisse parecendo regressão.
    """
    assert inicio in texto, f"{onde}: não achei a âncora inicial {inicio!r}"
    resto = texto[texto.index(inicio) :]
    assert fim in resto, f"{onde}: não achei a âncora final {fim!r} depois de {inicio!r}"
    return resto[: resto.index(fim)]


def test_o_motor_viaja_no_topo_do_pedido_e_nunca_dentro_de_config(js):
    corpo = _fatia(js, 'postJSON("/api/eval"', ");", "eval.js: corpo do POST")
    assert "engine:" in corpo, "o motor tem de ir no topo do corpo do pedido"
    assert "half:" in corpo, "a metade também vai no topo do corpo do pedido"
    # Dobrar dentro de `config` recriaria a confusão que a leva desfez.
    assert "config.engine" not in js
    assert 'config["engine"]' not in js


def test_o_seletor_de_motor_nao_tem_listener_que_grave(js):
    # Semeado uma vez do painel, nunca escrito de volta. Um `addEventListener`
    # no seletor de engine é como a escrita de volta voltaria.
    assert "els.engine" in js, (
        "eval.js não tem seletor de engine próprio: a tela ainda tira o motor "
        "do painel compartilhado, que é o acoplamento que esta leva desfaz"
    )
    assert "els.engine.addEventListener" not in js, (
        "o seletor de engine ganhou listener; se ele gravar, a escolha volta a "
        "vazar para a tela de conversa"
    )


def test_a_tela_diz_que_a_escolha_e_local(html):
    # Escrito na tela, não em documentação que ninguém abre.
    assert "Não muda a engine da conversa" in html


# ---------------------------------------- 2. uma caixa por avaliação, nomeada


def test_a_tela_itera_as_avaliacoes_em_vez_de_ler_uma(js):
    assert "data.avaliacoes" in js, (
        "eval.js ainda lê um resultado só: a resposta passa a ser uma lista de "
        "1 a 6 avaliações, e uma caixa por avaliação"
    )
    # Asserção direta do laço, e não uma janela de N caracteres em torno da
    # primeira ocorrência: a primeira menção é a nota agregada de
    # comparabilidade, e uma janela arbitrária transformaria "o laço está longe"
    # em "não há laço".
    assert re.search(r"for \(const \w+ of data\.avaliacoes\)", js), (
        "as avaliações têm de ser iteradas, não indexadas: `avaliacoes[0]` "
        "renderizaria uma caixa só quando a comparação pedir seis"
    )


def test_a_caixa_nomeia_dataset_motor_e_metade(js):
    assert "__title" in js, (
        "nenhuma caixa tem título: hoje o resultado não diz de que dataset é, e "
        "quem olha uma captura de tela depois não sabe se é o curado ou externo"
    )
    i = js.index("__title")
    titulo = js[max(0, i - 400) : i + 400]
    for termo in ("engine_kind", "divisao.metade"):
        assert termo in titulo, f"o título da caixa não nomeia {termo}"
    assert "datasetNome" in titulo or "dataset_nome" in titulo, (
        "o título da caixa não nomeia o dataset"
    )


def test_a_limpeza_do_resultado_acontece_uma_vez_so(js):
    # Se o `innerHTML = ""` migrasse para dentro do construtor de caixa, a
    # segunda caixa apagaria a primeira e a comparação renderizaria uma linha.
    assert js.count('els.result.innerHTML = ""') == 1


def test_a_marcacao_de_holdout_aparece_na_caixa(js):
    # Vem do servidor (`papel`), não de literal em JS -- ver o teste de
    # vocabulário abaixo. O que se afirma aqui é que ela é RENDERIZADA na caixa.
    assert "papel" in js


# ----------------------------------------------- 3. null não é uma afirmação


def test_o_aviso_de_comparabilidade_so_dispara_num_false_definido(js):
    assert "acuracia_comparavel === false" in js
    assert "!a.divisao.acuracia_comparavel" not in js
    assert "!avaliacao.divisao.acuracia_comparavel" not in js


# ------------------------------------- o vocabulário vem do servidor, sempre


def test_a_tela_pega_o_vocabulario_do_servidor(js):
    assert "choices.eval_engines" in js
    assert "choices.halves" in js


@pytest.mark.parametrize(
    "literal", ("\"rule\"", "\"kg\"", "\"hybrid\"", "\"comparar\"",
                "\"tune\"", "\"holdout\"", "\"ambas\"")
)
def test_nenhum_valor_canonico_e_literal_no_js(js, literal):
    """`handlers_choices.py` existe para que não haja literal de engine/stage em
    JS. A leva acrescenta duas listas e não pode abrir exceção para si mesma.
    """
    assert literal not in js


def test_a_tela_explica_tune_e_holdout(html):
    for termo in ("tune", "holdout", "divisao/v1", "recall"):
        assert termo in html, termo
    # E diz por que o curado não é dividido, antes de alguém tentar.
    assert "não é dividido" in html
