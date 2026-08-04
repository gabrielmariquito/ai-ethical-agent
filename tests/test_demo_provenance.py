import argparse
import json
from pathlib import Path

import pytest

from ethical_agent.__main__ import main
from test_engine import POLICY

import audit_tools


@pytest.fixture
def policy_path(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(POLICY), encoding="utf-8")
    return p


def _base_argv(policy_path, audit_log):
    return ["--engine", "rule", "--policy", str(policy_path), "--audit-log", str(audit_log)]


def _read_records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]


def test_cli_demo_records_are_tagged_with_demo_source(policy_path, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    code = main(_base_argv(policy_path, log_path) + ["demo"])
    assert code == 0
    records = _read_records(log_path)
    assert len(records) == 7
    assert all(r.get("source") == "demo" for r in records)


def test_resumir_excludes_demo_records_from_real_counts(policy_path, tmp_path, capsys):
    log_path = tmp_path / "audit.jsonl"
    main(_base_argv(policy_path, log_path) + ["demo"])
    main(_base_argv(policy_path, log_path) + ["check", "what is the capital of Brazil?"])

    records = _read_records(log_path)
    assert len(records) == 8  # 7 demo + 1 real

    args = argparse.Namespace(audit_log=str(log_path))
    audit_tools.cmd_resumir(args)
    out = capsys.readouterr().out

    assert "Total de registros: 8 (7 sintéticos)" in out
    assert "do comando `demo`" in out
    # only the 1 real check record should feed the status/engine breakdown
    assert "ok: 1" in out
    assert "denied" not in out


# O teste de texto-fonte sobre o antigo `gui_app.py` que morava aqui foi
# superado por um equivalente comportamental contra `/api/demo`.
# 
# O quarto demo compartilha as mesmas partes: `examples/demo.py` carregava um
# `build_llm()` próprio e gravava sem `llm_provenance` — `REGISTRO`, "Texto movido do código".
# 
# WHAT THIS DOES NOT GUARANTEE: read as text, not imported. It cannot tell
# you the example works, only that it is still wired to the shared parts
# instead of to copies of them.

EXAMPLE = (Path(__file__).resolve().parent.parent / "examples" / "demo.py").read_text(
    encoding="utf-8"
)


def test_the_example_builds_its_llm_through_resolve_llm():
    assert "resolve_llm" in EXAMPLE
    # The shape of the old hand-rolled copy: a try/except around OllamaClient
    # with a MockLLM fallback, which is resolve_llm's body written again.
    assert "OllamaClient(" not in EXAMPLE, "voltou a construir o cliente por conta própria"


def test_the_example_records_which_model_answered():
    # The concrete thing the divergence cost: records with no llm_provenance,
    # so the trail could not say what produced them.
    assert "llm_provenance=provenance" in EXAMPLE


def test_the_example_uses_the_shared_prompts():
    # audit_tools.py counts source="demo" records as synthetic and names
    # three producers; a fourth prompt list would make "the demo cases" mean
    # different things depending on which of them wrote the record.
    assert "from ethical_agent.demo import DEMO_CASES" in EXAMPLE
    assert "for prompt in DEMO_CASES:" in EXAMPLE


def test_the_example_still_tags_its_records_as_demo():
    assert 'source="demo"' in EXAMPLE
