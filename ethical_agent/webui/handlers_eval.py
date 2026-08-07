from __future__ import annotations

from pathlib import Path

from ethical_agent.evaluate import (
    METADES,
    PAPEIS_DAS_METADES,
    dataset_curado,
    evaluate_engine,
    format_report,
    load_dataset,
    recusa_de_divisao,
    resumo_da_divisao,
    selecionar_metade,
)
from ethical_agent.evaluate import eval_dir as _eval_dir
from ethical_agent.gui_choices import ENGINE_COMPARE_VALUE, METADE_AMBAS, engine_values

from . import routing
from .engine_factory import build_engine
from .errors import bad_request


def eval_dir() -> Path:
    # Delega: até aqui esta função e `__main__.dataset_curado` computavam o
    # mesmo caminho por rotas diferentes. O nome fica porque os testes o
    # importam, mas a definição é uma só.
    return _eval_dir()


def default_dataset_path() -> str:
    return str(dataset_curado())


def _resolve_dataset(raw) -> str:
    """Confina o dataset a `eval/`: sem isto, qualquer JSON com um array
    `cases` era legível e as mensagens distinguiam os erros — um oráculo: versão longa em `997a6fe^`.
    """
    if raw is None or raw == "":
        return default_dataset_path()
    if not isinstance(raw, str):
        raise bad_request("invalid_request", "'dataset' must be a string")
    root = eval_dir()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    # Rejected, never silently redirected: taking only the basename would let
    # "/etc/passwd/dataset.json" quietly become eval/dataset.json and report
    # success for a file the caller never asked about. The screen sends the
    # absolute path /api/choices advertised, so both forms have to be
    # accepted -- but only inside eval/.
    try:
        candidate.relative_to(root)
    except ValueError:
        raise bad_request("invalid_request", "'dataset' must name a file in eval/") from None
    if not candidate.is_file():
        # Same wording whatever the reason. Distinguishing "outside eval/"
        # from "not a file" would answer questions about the filesystem.
        raise bad_request("invalid_request", "'dataset' must name a file in eval/")
    return str(candidate)


def _resolve_engines(raw, config, state) -> list:
    """Os motores desta execução, escolhidos NA TELA e não no painel compartilhado.

    Precedência: corpo → `config` → configuração inicial. O corpo tem slot
    próprio de propósito: `config` é o objeto do painel que toda tela manda
    igual, e "o motor desta avaliação" é outro fato. Com slot separado, trocar a
    engine aqui não pode alcançar a tela de conversa nem por regressão do
    frontend.

    O valor desconhecido é recusado **aqui** e não em `build_engine`, que hoje o
    deixa cair no ramo híbrido com `ontology=None`: o `KnowledgeGraphEngine`
    levanta em cada caso, a falha fechada da composta converte cada exceção em
    DENY, e a tela devolve 200 com um relatório inteiro de lixo rotulado
    `hybrid`. Um resultado errado com aparência de resultado.
    """
    conhecidos = list(engine_values())
    if raw is None or raw == "":
        raw = config.get("engine", state.initial_config["engine"])
    if raw == ENGINE_COMPARE_VALUE:
        return conhecidos
    if not isinstance(raw, str) or raw not in conhecidos:
        raise bad_request(
            "invalid_request",
            f"'engine' must be one of {', '.join(conhecidos + [ENGINE_COMPARE_VALUE])}",
        )
    return [raw]


def _resolve_metades(raw, dataset) -> list:
    """As metades desta execução, e a recusa de dividir o conjunto curado.

    A recusa é a MESMA da CLI (`__main__.cmd_eval`), pelo mesmo predicado e lendo
    a mesma frase de `evaluate.recusa_de_divisao`. Tela e linha de comando
    discordando sobre o mesmo dataset fariam o teste que registra a recusa valer
    em só um dos caminhos.
    """
    if raw is None or raw == "":
        raw = "full"
    if not isinstance(raw, str) or raw not in tuple(METADES) + (METADE_AMBAS,):
        raise bad_request(
            "invalid_request",
            f"'half' must be one of {', '.join(tuple(METADES) + (METADE_AMBAS,))}",
        )
    metades = ["tune", "holdout"] if raw == METADE_AMBAS else [raw]

    if any(m != "full" for m in metades) and Path(dataset).resolve() == dataset_curado():
        raise bad_request(
            "dataset_not_split",
            f"{recusa_de_divisao(Path(dataset).name)} Esta tela o reporta inteiro.",
        )
    return metades


@routing.route(
    "POST", "/api/eval", realm="audit", requires_session=True, hidden_without_session=True
)
def post_eval(state, params, body):
    """Espelha o `eval` da CLI e nunca toca no `AuditLogger`, porque roda um
    lote de casos sintéticos direto no motor: versão longa em `997a6fe^`.

    Devolve sempre uma LISTA de avaliações, de uma a seis (três motores × duas
    metades). Forma que mudasse com a quantidade seria armadilha: quem escreve o
    consumidor testa com uma e descobre a lista com seis.
    """
    dataset = _resolve_dataset(body.get("dataset"))
    config = body.get("config") or {}
    if not isinstance(config, dict):
        raise bad_request("invalid_request", "'config' must be an object")

    engine_kinds = _resolve_engines(body.get("engine"), config, state)
    metades = _resolve_metades(body.get("half"), dataset)

    policy = config.get("policy", state.initial_config["policy"])
    ontology = config.get("ontology", state.initial_config["ontology"])
    grounding = config.get("grounding", state.initial_config["grounding"])
    norms = config.get("norms", state.initial_config["norms"])

    try:
        cases = load_dataset(dataset)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise bad_request("dataset_load_failed", f"{exc.__class__.__name__}: {exc}") from exc

    # Uma lista e um `divisao` por metade, computados UMA vez e partilhados por
    # todos os motores: é isso que faz os relatórios comparados carregarem o
    # mesmo `metade-id` por construção, e não por coincidência de determinismo.
    # `full` é uma metade como outra qualquer e tem de se nomear.
    try:
        por_metade = [(m, selecionar_metade(cases, m)) for m in metades]
    except ValueError as exc:  # dataset em eval/ sem `id` estável
        raise bad_request("dataset_not_split", str(exc)) from exc
    divisoes = {m: resumo_da_divisao(sel, cases, m) for m, sel in por_metade}

    avaliacoes = []
    for kind in engine_kinds:
        # Construída imediatamente antes do uso: o registro de condições é
        # global e cada `build_engine` reescreve as fábricas.
        try:
            engine = build_engine(policy, ontology, grounding, norms, kind)
        except Exception as exc:  # noqa: BLE001 -- bad config path/JSON, not a server bug
            raise bad_request("engine_build_failed", f"{exc.__class__.__name__}: {exc}") from exc
        for metade, da_metade in por_metade:
            # `divisoes[metade]` é o MESMO objeto para os três motores, e é essa
            # partilha que garante o `metade-id` comum. Nada aqui o muta.
            results = evaluate_engine(engine, da_metade, divisao=divisoes[metade])
            results["engine_kind"] = kind
            results["papel"] = PAPEIS_DAS_METADES[metade]
            results["report_text"] = format_report(results)
            avaliacoes.append(results)

    return {
        "dataset": dataset,
        "dataset_nome": Path(dataset).name,
        "avaliacoes": avaliacoes,
    }
