"""Guards for the tune/holdout split -- recipe `divisao/v1`.

The split exists so that a lexicon tuned against `tune` can be reported against
`holdout` and the number mean generalisation rather than fit. That claim rests
entirely on two properties, and both are silent when they break:

- **Stability.** If adding a case reshuffled the existing ones, a case that was
  in `holdout` could migrate to `tune`, earlier numbers would stop being
  comparable, and the contamination would come back through the back door --
  with nothing in the output looking any different.
- **A recipe anyone can recompute.** `test_atribuicao_bate_com_valor_dourado`
  is the only test here that pins the recipe itself. Every other test is
  internally consistent: change the hash material and they all still pass while
  the partition silently becomes a different one. That test is why the others
  can be trusted, and it is the one that must not be deleted for looking like a
  hardcoded duplicate of the implementation.

`ids=` is spelled out on every parametrize here, and no id contains a space.
The repo had no prior `ids=` usage -- the convention was to carry the label
inside the tuple -- so this file introduces it deliberately, for the reason
`tests/test_sucessor_da_supressao.py` records: generated ids would contain
spaces, and the snapshot tool keys tests by nodeid.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ethical_agent.__main__ import main
from ethical_agent.evaluate import (
    LIMITE_COMPARABILIDADE,
    LIMITE_DURO,
    RECEITA_DIVISAO,
    dividir,
    erro_padrao_do_recall,
    identificador_da_metade,
    load_dataset,
    metade_do_caso,
    resumo_da_divisao,
    selecionar_metade,
)

EVAL = Path(__file__).resolve().parents[1] / "eval"

# The two external datasets -- the only ones that are split. eval/dataset.json
# is deliberately absent; see test_dataset_curado_nao_e_dividido.
EXTERNOS = ("dataset_beavertails.json", "dataset_huggingface_injections.json")
IDS_EXTERNOS = ("beavertails", "injections")


def _casos(nome):
    return load_dataset(EVAL / nome)


# --------------------------------------------------------------- 1. determinismo


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_divisao_e_deterministica(nome):
    casos = _casos(nome)
    primeira, segunda = dividir(casos), dividir(casos)
    for metade in ("tune", "holdout"):
        assert [c["id"] for c in primeira[metade]] == [c["id"] for c in segunda[metade]]


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_a_ordem_de_entrada_nao_muda_a_divisao(nome):
    """Nothing about the split may depend on read order.

    The requirement is "same input => same split, always, across runs and
    across machines". Feeding the cases back in reverse is the cheapest way to
    catch an implementation that ever starts leaning on enumerate() or on the
    order a dict happened to yield.
    """
    casos = _casos(nome)
    direto = dividir(casos)
    invertido = dividir(list(reversed(casos)))
    for metade in ("tune", "holdout"):
        assert {c["id"] for c in direto[metade]} == {c["id"] for c in invertido[metade]}


# ------------------------------------------------------------- 2. estratificação


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_gap_dentro_do_limite_duro(nome):
    """The hard limit, and the only proportion assertion in this file.

    `LIMITE_COMPARABILIDADE` deliberately gets no assert: both external
    datasets exceed it today (0.0216 and 0.0283), and a permanently red check
    becomes noise -- that is how a verifier dies. It is reported as a flag on
    every run instead. `LIMITE_DURO` is the line where the two halves stop
    being two views of the same corpus, and that one does assert.
    """
    casos = _casos(nome)
    resumo = resumo_da_divisao(dividir(casos)["tune"], casos, "tune")
    gap = resumo["gap_entre_metades"]
    assert gap <= LIMITE_DURO, (
        f"{nome}: gap de proporção DENY entre as metades = {gap:.4f}, "
        f"acima do limite duro {LIMITE_DURO}. As metades deixaram de ser dois "
        f"recortes do mesmo corpus."
    )


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_sinalizador_de_comparabilidade_marca_os_dois_datasets(nome):
    """The counterweight to the test above: pin what the flag says *today*.

    Both external datasets exceed `LIMITE_COMPARABILIDADE`, so accuracy and F1
    are not comparable across halves on either. If that ever changes, this test
    fails and forces someone to re-read the derivation, instead of letting the
    flag quietly rot into a field nobody checks.
    """
    casos = _casos(nome)
    for metade in ("tune", "holdout"):
        resumo = resumo_da_divisao(dividir(casos)[metade], casos, metade)
        assert resumo["acuracia_comparavel"] is False, (
            f"{nome}/{metade}: gap {resumo['gap_entre_metades']:.4f} entrou "
            f"dentro de {LIMITE_COMPARABILIDADE}. Releia a derivação em "
            f"evaluate.py antes de mudar este teste."
        )


# ---------------------------------------------------------------- 3. estabilidade


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_acrescentar_caso_nao_move_ninguem(nome):
    """The point the whole scheme is designed around.

    Assignment is per case, derived from the id, never a shuffle of the list.
    Appending only appends.
    """
    casos = _casos(nome)
    antes = {c["id"]: metade_do_caso(c["id"]) for c in casos}

    novos = [
        {"id": f"NOVO-{i:04d}", "content": "texto qualquer",
         "expected_decision": "DENY" if i % 2 else "ALLOW"}
        for i in range(50)
    ]
    depois_metades = dividir(casos + novos)
    depois = {c["id"]: metade
              for metade in ("tune", "holdout")
              for c in depois_metades[metade]}

    movidos = {cid: (antes[cid], depois[cid])
               for cid in antes if antes[cid] != depois[cid]}
    assert not movidos, (
        f"{nome}: acrescentar 50 casos moveu {len(movidos)} caso(s) "
        f"preexistente(s) de metade: {dict(list(movidos.items())[:5])}"
    )


# ------------------------------------------------------------------ 4. cobertura


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_cobertura_e_disjuncao(nome):
    casos = _casos(nome)
    metades = dividir(casos)
    tune = {c["id"] for c in metades["tune"]}
    holdout = {c["id"] for c in metades["holdout"]}
    todos = {c["id"] for c in casos}

    assert tune | holdout == todos
    assert tune & holdout == set()
    assert len(metades["tune"]) + len(metades["holdout"]) == len(casos)


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_selecionar_metade_full_devolve_o_conjunto_inteiro(nome):
    casos = _casos(nome)
    assert [c["id"] for c in selecionar_metade(casos, "full")] == [c["id"] for c in casos]


def test_metade_desconhecida_e_recusada():
    with pytest.raises(ValueError, match="metade desconhecida"):
        selecionar_metade([{"id": "X", "expected_decision": "ALLOW"}], "treino")


# ------------------------------------------------- caso sem id: o que pode e não pode

SEM_ID = [
    {"content": "qual é a capital do Brasil?", "expected_decision": "ALLOW"},
    {"content": "outro caso qualquer", "expected_decision": "DENY"},
]


def test_dataset_sem_id_nao_pode_ser_dividido():
    """Without a stable id the assignment would fall back on list position.

    And then appending a case *would* move the others -- the one thing the
    scheme exists to prevent. Better a loud error than a partition that looks
    fine and is not reproducible.
    """
    with pytest.raises(ValueError, match="não tem `id`"):
        selecionar_metade(SEM_ID, "tune")


def test_dataset_sem_id_continua_avaliavel_inteiro():
    """`full` never needed the split, so it must keep working where it used to.

    `evaluate_engine` reads `id` only to label mismatches, so a dataset without
    ids evaluated fine before this batch. Making the harness able to read halves
    must not take that away -- that would be a behaviour change smuggled in by a
    tooling change.
    """
    resumo = resumo_da_divisao(SEM_ID, SEM_ID, "full")
    assert resumo["metade"] == "full"
    assert resumo["casos"] == 2
    assert resumo["identificador"] is None
    assert resumo["gap_entre_metades"] is None


# ------------------------------------------------------- 5. o curado não é dividido


@pytest.mark.parametrize("metade", ("tune", "holdout"), ids=("tune", "holdout"))
def test_dataset_curado_nao_e_dividido(metade, capsys):
    """eval/dataset.json is reported whole, and asking for half of it fails loudly.

    It is in-distribution by construction -- written by the author of the rules
    it tests -- so a "holdout" carved out of it would measure nothing while
    looking exactly like a generalisation claim. Silently falling back to the
    full set would produce a number labelled `holdout` that is not one, which is
    worse than no number at all.
    """
    code = main(["eval", "--half", metade])
    assert code == 2
    erro = capsys.readouterr().err
    assert "não é dividido" in erro
    assert "in-distribution" in erro


def test_o_curado_inteiro_continua_avaliavel(capsys):
    code = main(["eval", "--json"])
    saida = json.loads(capsys.readouterr().out)
    assert saida["divisao"]["metade"] == "full"
    assert saida["divisao"]["casos"] == saida["total_cases"] == 72
    assert code in (0, 1)  # 1 quando há mismatch; o corpus curado tem dois conhecidos


# --------------------------------------------------------------- 6. identificador


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_identificador_e_reproduzivel(nome):
    metades = dividir(_casos(nome))
    for metade in ("tune", "holdout"):
        assert (identificador_da_metade(metades[metade])
                == identificador_da_metade(metades[metade]))
    # E as duas metades não podem colidir.
    assert (identificador_da_metade(metades["tune"])
            != identificador_da_metade(metades["holdout"]))


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_identificador_muda_se_a_metade_muda(nome):
    """One case less has to be a different identifier.

    Otherwise "two runs reporting the same identifier read the same half" is
    not a claim the identifier supports.
    """
    metade = dividir(_casos(nome))["holdout"]
    assert identificador_da_metade(metade) != identificador_da_metade(metade[:-1])


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_identificador_nao_depende_da_ordem_da_lista(nome):
    metade = dividir(_casos(nome))["tune"]
    assert (identificador_da_metade(metade)
            == identificador_da_metade(list(reversed(metade))))


# -------------------------------------------------------------- 7. a receita, presa

# Values computed once with `divisao/v1` and written down. Not derived from the
# implementation at test time on purpose: this is the only test in the file that
# would notice the hash material changing. Every other test here is internally
# consistent and would keep passing over a silently different partition.
ATRIBUICAO_DOURADA = {
    "HF-BT-0000": "holdout",
    "HF-BT-0001": "tune",
    "HF-INJ-train-0000": "tune",
    "HF-INJ-test-0115": "holdout",
    "B-001": "tune",
}

IDENTIFICADOR_DOURADO = {
    ("dataset_beavertails.json", "tune"):
        "7a5bbfa625892992dc5a48e2fb73e04b0b9f8e49019e126a515f083062c398fd",
    ("dataset_beavertails.json", "holdout"):
        "48adcaf986b8bd3cbe8ddec21c9459ea0ee875fb0638887f003c6df7147284ec",
    ("dataset_huggingface_injections.json", "tune"):
        "fae20622ea3ac79fb6d2c034834733b3d8a0411a764fec1fcb42d3d41a863738",
    ("dataset_huggingface_injections.json", "holdout"):
        "25de58b3e96eba26346a58a4af4697a18ce49e8952f046d11be6b5e48f0c17f7",
}


@pytest.mark.parametrize(
    "case_id, esperado", sorted(ATRIBUICAO_DOURADA.items()),
    ids=tuple(sorted(ATRIBUICAO_DOURADA)),
)
def test_atribuicao_bate_com_valor_dourado(case_id, esperado):
    assert metade_do_caso(case_id) == esperado, (
        f"{case_id} mudou de metade. O material do hash de `divisao/v1` mudou, "
        f"e com ele a partição inteira -- resultados de holdout anteriores "
        f"deixaram de ser comparáveis. Se a mudança é intencional, a receita "
        f"tem de virar divisao/v2."
    )


@pytest.mark.parametrize("nome", EXTERNOS, ids=IDS_EXTERNOS)
def test_identificador_bate_com_valor_dourado(nome):
    metades = dividir(_casos(nome))
    for metade in ("tune", "holdout"):
        assert (identificador_da_metade(metades[metade])
                == IDENTIFICADOR_DOURADO[(nome, metade)]), (
            f"{nome}/{metade}: a metade mudou de conteúdo. Ou o dataset mudou, "
            f"ou a receita mudou; nos dois casos o número que sair dela não é "
            f"comparável com os anteriores."
        )


def test_a_receita_esta_dentro_do_hash():
    """Bumping the recipe must re-partition, not quietly rename the quantity.

    Same discipline as `config-id/v1` and `assinatura/v1`: the constant is
    inside what is hashed, so a v2 cannot produce a different quantity under
    the same name.
    """
    import hashlib
    material = f"{RECEITA_DIVISAO}|HF-BT-0000".encode("utf-8")
    esperado = "tune" if int(hashlib.sha256(material).hexdigest(), 16) % 2 == 0 else "holdout"
    assert metade_do_caso("HF-BT-0000") == esperado

    outro = f"divisao/v2|HF-BT-0000".encode("utf-8")
    assert hashlib.sha256(outro).hexdigest() != hashlib.sha256(material).hexdigest()


# ------------------------------------------------- 8. o número não sai sem escala


def test_erro_padrao_do_recall_encolhe_com_o_estrato():
    assert erro_padrao_do_recall(0.058, 55) > erro_padrao_do_recall(0.058, 220)
    assert erro_padrao_do_recall(0.058, 0) is None
    # O holdout do BeaverTails: 55 positivos, e.p. 0.032, IC95 ±0.062 -- mais
    # largo que o próprio recall de hoje (0.058).
    assert erro_padrao_do_recall(0.058, 55) == pytest.approx(0.0315, abs=1e-3)


@pytest.mark.parametrize("metade", ("tune", "holdout", "full"), ids=("tune", "holdout", "full"))
def test_relatorio_nomeia_a_metade_e_traz_a_escala(metade, capsys):
    """No path through the CLI prints recall without its half and its noise floor.

    Including `full`: a silent default is the same defect wearing a different
    hat, and it is the one that would actually get used.
    """
    code = main(["eval", "--dataset", str(EVAL / "dataset_beavertails.json"),
                 "--half", metade])
    assert code in (0, 1)
    saida = capsys.readouterr().out
    assert f"Divisão : {metade}" in saida
    assert RECEITA_DIVISAO in saida
    assert "metade-id :" in saida
    assert "e.p., N_DENY=" in saida


def test_json_traz_o_bloco_da_divisao(capsys):
    code = main(["eval", "--dataset", str(EVAL / "dataset_beavertails.json"),
                 "--half", "holdout", "--json"])
    assert code in (0, 1)
    saida = json.loads(capsys.readouterr().out)
    divisao = saida["divisao"]
    assert divisao["metade"] == "holdout"
    assert divisao["receita"] == RECEITA_DIVISAO
    assert divisao["casos"] == 103
    assert (divisao["deny"], divisao["allow"]) == (55, 48)
    assert divisao["identificador"] == IDENTIFICADOR_DOURADO[
        ("dataset_beavertails.json", "holdout")]
    assert divisao["acuracia_comparavel"] is False
    assert saida["binary"]["recall_erro_padrao"] is not None
