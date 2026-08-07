import json
from pathlib import Path

import pytest

from webui_support import running_tools_server


@pytest.fixture
def server(tmp_path):
    # Ferramenta do avaliador: exige sessão de auditoria.
    running = running_tools_server(tmp_path, engine="rule")
    yield running
    running.close()


from ethical_agent.webui.handlers_eval import default_dataset_path, eval_dir

# Os identificadores dourados vêm de `test_divisao.py`, não de uma segunda
# cópia: dois literais que precisam ser iguais são um literal.
from test_divisao import IDENTIFICADOR_DOURADO

# The dataset is no longer an arbitrary path: post_eval confines it to eval/.
# So these run against the repo's real datasets rather than fixtures written
# into tmp_path. The confinement itself is tested at the bottom of the file.
REAL_DATASET = "dataset.json"
EXTERNO = "dataset_beavertails.json"


def _uma(body):
    """A resposta traz sempre uma LISTA de avaliações, com um ou seis itens.

    Uma forma que muda com a quantidade de resultados é uma armadilha: quem
    escreve o consumidor testa com um e descobre a lista com seis.
    """
    assert len(body["avaliacoes"]) == 1, body["avaliacoes"]
    return body["avaliacoes"][0]


def test_eval_happy_path(server):
    status, body, _ = server.post("/api/eval", {"dataset": REAL_DATASET, "config": {}})
    assert status == 200
    avaliacao = _uma(body)
    assert avaliacao["total_cases"] > 0
    assert "report_text" in avaliacao and isinstance(avaliacao["report_text"], str)
    assert avaliacao["report_text"]


def test_eval_names_the_half_and_carries_the_noise_floor(server):
    """A regra de relatório alcança a tela de auditoria, não só a CLI: `full`
    é uma metade como outra qualquer e tem de se nomear: versão longa em `997a6fe^`.
    """
    status, body, _ = server.post("/api/eval", {"dataset": REAL_DATASET, "config": {}})
    assert status == 200
    avaliacao = _uma(body)

    divisao = avaliacao["divisao"]
    assert divisao["metade"] == "full"
    assert divisao["receita"] == "divisao/v1"
    assert divisao["casos"] == avaliacao["total_cases"]
    assert divisao["identificador"]

    # A escala do número viaja junto com o número.
    assert avaliacao["binary"]["recall_erro_padrao"] is not None

    # E o auditor lê a mesma procedência que a CLI imprime, porque report_text
    # é o mesmo format_report.
    assert "Divisão : full" in avaliacao["report_text"]
    assert "metade-id :" in avaliacao["report_text"]


def test_eval_accepts_the_absolute_path_the_screen_was_handed(server):
    # /api/choices advertises dataset_default as an absolute path and eval.js
    # posts it straight back, so the absolute form has to keep working.
    status, body, _ = server.post("/api/eval", {"dataset": default_dataset_path(), "config": {}})
    assert status == 200
    assert _uma(body)["total_cases"] > 0


def test_eval_rejects_invalid_engine_config(server):
    status, body, _ = server.post(
        "/api/eval", {"dataset": REAL_DATASET, "config": {"policy": "/does/not/exist.json"}}
    )
    assert status == 400
    assert body["error"] == "engine_build_failed"


def test_eval_never_writes_to_audit_log_even_if_config_has_one(server):
    # Even if a caller's shared config object happens to carry audit_log
    # (the same object the chat/check screens use), eval must never read it.
    status, body, _ = server.post(
        "/api/eval", {"dataset": REAL_DATASET, "config": {"audit_log": server.audit_log_path}}
    )
    assert status == 200
    assert not Path(server.audit_log_path).exists()


# ----------------------------------------- o motor é escolhido NA TELA, e a
# ----------------------------------------- escolha é local a esta execução


def test_o_motor_do_corpo_vence_o_painel_compartilhado(server):
    """A separação estrutural desta leva, do lado do servidor.

    `config` é o objeto do painel compartilhado, mandado igual por toda tela. O
    motor do eval é outro fato, e tem slot próprio no topo do pedido: mesmo que
    o frontend regredisse e mandasse `config.engine`, ele não alcança mais o
    eval. Vermelho hoje: o handler só lê `config["engine"]`.
    """
    status, body, _ = server.post(
        "/api/eval",
        {"dataset": REAL_DATASET, "engine": "rule", "config": {"engine": "hybrid"}},
    )
    assert status == 200, body
    assert _uma(body)["engine"] == "rule-based"

    status, body, _ = server.post(
        "/api/eval",
        {"dataset": REAL_DATASET, "engine": "hybrid", "config": {"engine": "rule"}},
    )
    assert status == 200, body
    assert _uma(body)["engine"] == "hybrid"


def test_omitir_o_motor_reproduz_o_comportamento_de_hoje(server):
    """Sem `engine` no corpo, vale o configurado — o primeiro carregamento da
    tela tem de ser idêntico ao de antes da leva.
    """
    status, body, _ = server.post("/api/eval", {"dataset": REAL_DATASET, "config": {}})
    assert status == 200
    assert _uma(body)["engine"] == "rule-based"  # o server sobe com engine="rule"


def test_a_comparacao_dos_tres_roda_sobre_o_mesmo_conjunto(server):
    """Um POST, uma leitura do dataset, um `divisao` — o mesmo `metade-id` nos
    três sai por construção e não por coincidência de determinismo.
    """
    status, body, _ = server.post(
        "/api/eval", {"dataset": EXTERNO, "engine": "comparar", "half": "holdout"}
    )
    assert status == 200, body
    avaliacoes = body["avaliacoes"]

    assert len(avaliacoes) == 3
    assert [a["engine_kind"] for a in avaliacoes] == ["rule", "kg", "hybrid"]
    assert {a["engine"] for a in avaliacoes} == {"rule-based", "knowledge-graph", "hybrid"}
    assert {a["total_cases"] for a in avaliacoes} == {103}
    # Conjunto de UM: "o mesmo id" é a asserção, não três asserções soltas.
    assert {a["divisao"]["identificador"] for a in avaliacoes} == {
        IDENTIFICADOR_DOURADO[(EXTERNO, "holdout")]
    }


def test_o_eval_recusa_um_motor_que_nao_conhece(server):
    """Hoje devolve 200 com um relatório rotulado `hybrid` em que TODO caso é
    DENY: o valor desconhecido cai no ramo híbrido com `ontology=None`, o
    `KnowledgeGraphEngine` levanta, e a falha fechada da composta converte cada
    exceção em DENY. Um relatório inteiro de lixo, com aparência de resultado.
    """
    status, body, _ = server.post(
        "/api/eval", {"dataset": REAL_DATASET, "engine": "banana"}
    )
    assert status == 400, body
    assert body["error"] == "invalid_request"
    for valor in ("rule", "kg", "hybrid", "comparar"):
        assert valor in body["message"]


def test_o_eval_recusa_uma_metade_que_nao_conhece(server):
    status, body, _ = server.post(
        "/api/eval", {"dataset": EXTERNO, "half": "treino"}
    )
    assert status == 400, body
    assert body["error"] == "invalid_request"


# ------------------------------------------------- tune e holdout, separados


def test_as_duas_metades_saem_em_duas_caixas(server):
    """`tune ∪ holdout == full`, então isto custa o mesmo que rodar `full`."""
    status, body, _ = server.post(
        "/api/eval", {"dataset": EXTERNO, "engine": "rule", "half": "ambas"}
    )
    assert status == 200, body
    avaliacoes = body["avaliacoes"]

    assert len(avaliacoes) == 2
    assert [a["divisao"]["metade"] for a in avaliacoes] == ["tune", "holdout"]
    assert [a["divisao"]["casos"] for a in avaliacoes] == [117, 103]
    assert sum(a["divisao"]["casos"] for a in avaliacoes) == 220
    assert {a["divisao"]["casos_no_conjunto"] for a in avaliacoes} == {220}
    assert [a["divisao"]["identificador"] for a in avaliacoes] == [
        IDENTIFICADOR_DOURADO[(EXTERNO, "tune")],
        IDENTIFICADOR_DOURADO[(EXTERNO, "holdout")],
    ]


def test_metades_lado_a_lado_carregam_o_aviso_de_comparabilidade(server):
    """Estruturalmente inalcançável hoje: o handler fixa `"full"`, então
    `gap_entre_metades` é sempre None e o aviso nunca pode aparecer na tela.

    Mostrar as duas metades lado a lado é exatamente quando ele TEM de aparecer
    — `test_divisao.py` registra que `acuracia_comparavel` é False nos dois
    datasets externos hoje.
    """
    status, body, _ = server.post(
        "/api/eval", {"dataset": EXTERNO, "engine": "rule", "half": "ambas"}
    )
    assert status == 200, body

    for avaliacao in body["avaliacoes"]:
        divisao = avaliacao["divisao"]
        assert divisao["gap_entre_metades"] is not None
        assert divisao["acuracia_comparavel"] is False
        assert "NÃO são comparáveis" in avaliacao["report_text"]
        assert "Compare recall" in avaliacao["report_text"]


def test_a_caixa_de_holdout_vem_marcada_como_reporte(server):
    """A marcação vem do servidor, e viaja também no texto copiável.

    Um dicionário de papéis não impede ninguém de calibrar contra o holdout — o
    que ele garante é que nenhum número de holdout chega sem o papel colado.
    """
    status, body, _ = server.post(
        "/api/eval", {"dataset": EXTERNO, "engine": "rule", "half": "holdout"}
    )
    assert status == 200, body
    avaliacao = _uma(body)

    assert "reporte" in avaliacao["papel"]
    assert "reporte" in avaliacao["report_text"]


def test_a_caixa_de_tune_se_diz_instrumento_de_trabalho(server):
    status, body, _ = server.post(
        "/api/eval", {"dataset": EXTERNO, "engine": "rule", "half": "tune"}
    )
    assert status == 200, body
    assert "ajuste" in _uma(body)["papel"]


# --------------------------------------------- uma caixa por avaliação, nomeada


def test_cada_avaliacao_nomeia_o_dataset_o_motor_e_a_metade(server):
    """Hoje a caixa não diz de que dataset é: quem olha uma captura de tela
    depois não sabe se aquilo é o conjunto curado ou um dos externos.
    """
    status, body, _ = server.post(
        "/api/eval", {"dataset": EXTERNO, "engine": "comparar", "half": "holdout"}
    )
    assert status == 200, body

    assert body["dataset_nome"] == EXTERNO
    assert body["dataset"].endswith(EXTERNO)
    assert Path(body["dataset"]).is_absolute()
    for avaliacao in body["avaliacoes"]:
        assert avaliacao["engine_kind"] in ("rule", "kg", "hybrid")
        assert avaliacao["divisao"]["metade"] == "holdout"
        assert avaliacao["report_text"]


def test_a_matriz_inteira_sao_seis_caixas_e_nenhuma_escrita_na_trilha(server):
    """O caso mais caro da tela, e o que mais tinha a ganhar em escapar da
    regra: seis avaliações, zero linha na trilha.
    """
    status, body, _ = server.post(
        "/api/eval",
        {
            "dataset": EXTERNO,
            "engine": "comparar",
            "half": "ambas",
            "config": {"audit_log": server.audit_log_path},
        },
    )
    assert status == 200, body
    assert len(body["avaliacoes"]) == 6
    assert not Path(server.audit_log_path).exists()


# ------------------------------------------------------- atribuição na tela


def test_o_hibrido_atribui_cada_decisao_a_uma_camada(server):
    status, body, _ = server.post(
        "/api/eval", {"dataset": REAL_DATASET, "engine": "hybrid"}
    )
    assert status == 200, body
    avaliacao = _uma(body)

    camadas = avaliacao["camadas"]
    assert camadas["engines"] == ["rule-based", "knowledge-graph"]
    assert sum(c["casos"] for c in camadas["combinacoes"]) == avaliacao["total_cases"] == 72
    assert camadas["indisponivel"] == 0

    por_combinacao = {tuple(c["camadas"]): c["casos"] for c in camadas["combinacoes"]}
    assert por_combinacao[("rule-based",)] == 35
    assert por_combinacao[("knowledge-graph",)] == 14
    assert por_combinacao[("rule-based", "knowledge-graph")] == 23
    assert "Camada decisória" in avaliacao["report_text"]


def test_cada_divergencia_na_tela_nomeia_a_camada(server):
    status, body, _ = server.post(
        "/api/eval", {"dataset": REAL_DATASET, "engine": "hybrid"}
    )
    avaliacao = _uma(body)
    assert avaliacao["mismatches"]
    for erro in avaliacao["mismatches"]:
        assert erro["camada"]


def test_um_motor_de_camada_unica_nao_afirma_camada_nenhuma(server):
    status, body, _ = server.post(
        "/api/eval", {"dataset": REAL_DATASET, "engine": "rule"}
    )
    avaliacao = _uma(body)
    assert "camadas" not in avaliacao
    assert "Camada decisória" not in avaliacao["report_text"]


# ----------------------------------------- a engine da conversa não se mexe


def test_escolher_motor_no_eval_nao_muda_a_engine_da_conversa(server):
    """O servidor não tem configuração mutável, e esta é a asserção que impede
    alguém de acrescentar uma por conveniência ("lembrar o último motor").

    Guarda, não vermelho: passa hoje porque `state.initial_config` é escrito uma
    vez. Existe para que apagá-la seja um ato deliberado.
    """
    _, antes, _ = server.get("/api/choices")
    server.post("/api/eval", {"dataset": REAL_DATASET, "engine": "kg"})
    _, depois, _ = server.get("/api/choices")

    assert antes["defaults"] == depois["defaults"]
    assert depois["defaults"]["engine"] == "rule"


# O caminho do dataset é confinado: antes, qualquer JSON com um array
# "cases" era legível, e as mensagens distinguiam os erros — um oráculo de
# arquivos: versão longa em `997a6fe^`.


@pytest.mark.parametrize(
    "raw",
    [
        "../pyproject.toml",
        "../policies/core_policy.json",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
    ],
)
def test_eval_refuses_a_dataset_outside_eval(server, raw):
    status, body, _ = server.post("/api/eval", {"dataset": raw, "config": {}})
    assert status == 400
    assert body["error"] == "invalid_request"
    assert "eval/" in body["message"]


def test_eval_refusal_does_not_report_on_the_filesystem(server, tmp_path):
    # One wording for every rejection: "outside eval/" and "not a file" must
    # not be distinguishable, or the refusal itself answers questions.
    existing = tmp_path / "real.json"
    existing.write_text(json.dumps({"cases": []}), encoding="utf-8")

    _, outside_existing, _ = server.post("/api/eval", {"dataset": str(existing), "config": {}})
    _, outside_missing, _ = server.post(
        "/api/eval", {"dataset": str(tmp_path / "nope.json"), "config": {}}
    )
    _, inside_missing, _ = server.post("/api/eval", {"dataset": "nope.json", "config": {}})

    assert outside_existing == outside_missing == inside_missing


def test_eval_does_not_silently_redirect_to_a_same_named_file_in_eval(server, tmp_path):
    # Taking only the basename would turn "/somewhere/else/dataset.json" into
    # eval/dataset.json and report success for a file nobody asked about.
    decoy = tmp_path / "dataset.json"
    decoy.write_text(json.dumps({"cases": []}), encoding="utf-8")
    status, body, _ = server.post("/api/eval", {"dataset": str(decoy), "config": {}})
    assert status == 400, body


def test_eval_dir_is_where_the_default_dataset_lives(server):
    assert Path(default_dataset_path()).parent == eval_dir()


def test_eval_uses_default_dataset_when_none_given(server):
    # /api/choices advertises the same default the CLI/former EvalTab used;
    # omitting "dataset" in the request body should fall back to it and
    # succeed against the repo's real eval/dataset.json.
    status, body, _ = server.post("/api/eval", {"config": {}})
    assert status == 200
    assert _uma(body)["total_cases"] > 0
