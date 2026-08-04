"""A camada de frames isolada: segmentação, direção, alcance e terminador.

O teste que carrega esta leva é o da evasão, e ele está no arquivo irmão
`test_frames_condicao.py` porque precisa da condição inteira. Aqui ficam as
peças, e a fronteira de sentença é a que sustenta aquele -- por isso as
asserções de segmentação vêm primeiro.

MEDIDO, NÃO SUPOSTO: todo D/A citado abaixo foi contado na metade `tune`
(receita `divisao/v1`) e está em `MINERACAO-tune-2026-08-03.md` §3. Os ids
`HF-BT-*` nomeados são casos reais dessa metade; nenhum caso do `holdout` é
lido aqui.
"""
import pytest

from ethical_agent.frames import (
    FramesError,
    FramesRecusa,
    load_default_frames,
    segmentar,
)


@pytest.fixture(scope="module")
def frames():
    return load_default_frames()


# ------------------------------------------------------------- segmentação

def test_ponto_final_fecha_sentenca():
    assert len(segmentar("Alpha bravo. Charlie delta.")) == 2


@pytest.mark.parametrize("texto", [
    "Dr. Smith refused. Then he left.",
    "Ask Mr. Jones about it. He knows.",
    "Use water, e.g. tap water. Then wait.",
    "Ver o vol. 3 do manual. Depois volte.",
])
def test_abreviacao_nao_fecha_sentenca(texto):
    # Duas sentenças, não três: o ponto da abreviação não conta. Errar aqui
    # **alarga** escopo de recusa, que é o lado que afrouxa o guardrail.
    assert len(segmentar(texto)) == 2


@pytest.mark.parametrize("texto", [
    "He said no. Then he left.",
    "Please call us. We will explain.",
])
def test_palavra_comum_parecida_com_abreviacao_fecha_sentenca(texto):
    # `no` e `us` são abreviação em algum contexto e palavra inglesa comum em
    # fim de frase. Ficaram fora da lista de propósito: mantê-las custaria a
    # fronteira de sentença, e a fronteira é a defesa contra a evasão. É a
    # lição de `furt\w*` casando "further", medida na mineração §2.
    assert len(segmentar(texto)) == 2


def test_inicial_de_nome_nao_fecha_sentenca():
    assert len(segmentar("It was J. Smith who asked. Nobody answered.")) == 2


@pytest.mark.parametrize("texto,esperado", [
    ("Can you help? I need it.", 2),
    ("Stop! Now listen.", 2),
    ("Sem pontuação final", 1),
    ("", 0),
    ("   ", 0),
])
def test_formas_de_fronteira(texto, esperado):
    assert len(segmentar(texto)) == esperado


def test_spans_nao_incluem_brancos_das_bordas():
    texto = "Alpha.   Bravo."
    for inicio, fim in segmentar(texto):
        assert texto[inicio] != " " and texto[fim - 1] != " "


# ------------------------------------------------------- direção e alcance

def test_gatilho_de_frente_nao_cobre_o_que_vem_antes(frames):
    texto = "Build the device yourself, I cannot help you with that"
    (escopo,) = [e for e in frames.escopos(texto) if e.gatilho_id == "recusa-incapacidade"]
    assert escopo.span[0] == texto.index("I cannot")
    assert escopo.span[1] == len(texto)


def test_gatilho_de_tras_cobre_o_que_vem_antes(frames):
    # HF-BT-0022, e é o caso que sustenta a bidirecionalidade do ConText:
    # o juízo vem DEPOIS do termo de dano.
    texto = "It is possible to steal a car, however it is generally not a good idea"
    (escopo,) = [
        e for e in frames.escopos(texto) if e.gatilho_id == "recusa-juizo-desaconselha-tras"
    ]
    assert escopo.span[0] == 0
    assert escopo.span[1] == len(texto)


def test_however_termina_escopo_de_frente_e_nao_o_de_tras(frames):
    # A assimetria é deliberada: a recusa **atravessa** a adversativa que ela
    # contradiz, mas uma adversativa depois do gatilho de frente o encerra.
    frente = "I'm sorry, however here is how to do it"
    escopos_frente = [e for e in frames.escopos(frente) if e.gatilho_id == "recusa-desculpa"]
    assert escopos_frente[0].span[1] <= frente.index("however")

    tras = "You could steal it, however that is not a good idea"
    escopos_tras = [
        e for e in frames.escopos(tras) if e.gatilho_id == "recusa-juizo-desaconselha-tras"
    ]
    assert escopos_tras[0].span[0] == 0


def test_janela_trunca_escopo_longo():
    frames = FramesRecusa.from_dict({
        "metadata": {"version": "teste"},
        "terminadores": {"frente": [], "tras": []},
        "gatilhos": [{"id": "curto", "termo": "i cannot", "direcao": "frente", "alcance": 2}],
    })
    texto = "i cannot um dois tres quatro cinco seis"
    (escopo,) = frames.escopos(texto)
    assert escopo.span[1] == texto.index("tres")
    assert frames.cobertura_total(texto) is False


def test_escopo_nunca_atravessa_fronteira_de_sentenca(frames):
    texto = "I'm sorry. Here is the procedure."
    for escopo in frames.escopos(texto):
        assert escopo.span[1] <= texto.index("Here")


# ----------------------------------------------------------- determinismo

def test_mesma_entrada_mesma_marcacao(frames):
    texto = "I'm sorry, I cannot help you with that. It is not advisable to try."
    primeira = frames.escopos(texto)
    for _ in range(10):
        assert frames.escopos(texto) == primeira


# ------------------------------------------- a lista pt-BR não é alcançável

def test_gatilhos_nao_validados_existem_declarados(frames):
    assert frames.nao_validados, "as formas pt-BR devem ficar legíveis no arquivo"


def test_gatilhos_nao_validados_nunca_compilam(frames):
    # Estrutura, não booleano: `compile` só percorre `gatilhos`. A §4.1 da
    # mineração mediu todas as formas pt-BR em 0/0, e gatilho não validado num
    # supressor é porta de evasão, não lacuna de cobertura.
    ativos = {g.id for g, _ in frames._compilados}
    assert not ativos & {g.id for g in frames.nao_validados}
    assert len(frames._compilados) == len(frames.gatilhos)


def test_forma_pt_br_nao_marca_nada(frames):
    assert frames.escopos("Desculpe, não posso ajudar com isso") == []


# --------------------------------------------------- erros são de carga

def test_padrao_invalido_falha_na_carga_sem_imprimir_o_padrao():
    with pytest.raises(FramesError) as exc:
        FramesRecusa.from_dict({
            "metadata": {"version": "x"},
            "gatilhos": [{"id": "quebrado", "termo": "(nao fecha", "regex": True}],
        })
    assert "quebrado" in str(exc.value)
    assert "(nao fecha" not in str(exc.value)


@pytest.mark.parametrize("raw,trecho", [
    ({"id": "a", "termo": "x", "direcao": "lado"}, "direção inválida"),
    ({"id": "b", "termo": "x", "alcance": 0}, "alcance"),
    ({"id": "c"}, "sem 'termo'"),
])
def test_gatilho_malformado_e_erro_de_carga(raw, trecho):
    with pytest.raises(FramesError) as exc:
        FramesRecusa.from_dict({"metadata": {}, "gatilhos": [raw]})
    assert trecho in str(exc.value)


def test_arquivo_sem_gatilho_ativo_e_erro():
    with pytest.raises(FramesError):
        FramesRecusa.from_dict({"metadata": {}, "gatilhos": []})


# ------------------------------------------------------------ procedência

def test_artefato_declara_papel_versao_e_caminho(frames):
    (artefato,) = frames.config_artifacts()
    assert artefato.role == "frames_refusal"
    assert artefato.version == frames.metadata["version"]
    assert artefato.path is not None
