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

# The dataset is no longer an arbitrary path: post_eval confines it to eval/.
# So these run against the repo's real datasets rather than fixtures written
# into tmp_path. The confinement itself is tested at the bottom of the file.
REAL_DATASET = "dataset.json"


def test_eval_happy_path(server):
    status, body, _ = server.post("/api/eval", {"dataset": REAL_DATASET, "config": {}})
    assert status == 200
    assert body["total_cases"] > 0
    assert "report_text" in body and isinstance(body["report_text"], str) and body["report_text"]


def test_eval_names_the_half_and_carries_the_noise_floor(server):
    """A regra de relatório alcança a tela de auditoria, não só a CLI: `full`
    é uma metade como outra qualquer e tem de se nomear: `REGISTRO`, "Texto movido do código".
    """
    status, body, _ = server.post("/api/eval", {"dataset": REAL_DATASET, "config": {}})
    assert status == 200

    divisao = body["divisao"]
    assert divisao["metade"] == "full"
    assert divisao["receita"] == "divisao/v1"
    assert divisao["casos"] == body["total_cases"]
    assert divisao["identificador"]

    # A escala do número viaja junto com o número.
    assert body["binary"]["recall_erro_padrao"] is not None

    # E o auditor lê a mesma procedência que a CLI imprime, porque report_text
    # é o mesmo format_report.
    assert "Divisão : full" in body["report_text"]
    assert "metade-id :" in body["report_text"]


def test_eval_accepts_the_absolute_path_the_screen_was_handed(server):
    # /api/choices advertises dataset_default as an absolute path and eval.js
    # posts it straight back, so the absolute form has to keep working.
    status, body, _ = server.post("/api/eval", {"dataset": default_dataset_path(), "config": {}})
    assert status == 200
    assert body["total_cases"] > 0


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


# O caminho do dataset é confinado: antes, qualquer JSON com um array
# "cases" era legível, e as mensagens distinguiam os erros — um oráculo de
# arquivos: `REGISTRO`, "Texto movido do código".


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
    assert body["total_cases"] > 0
