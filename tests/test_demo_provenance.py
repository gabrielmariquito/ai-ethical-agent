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


def test_gui_demo_tags_source():
    # Read the source directly rather than `import gui_app` -- importing it
    # needs tkinter and a sys.path/CWD setup this test shouldn't depend on
    # (same reasoning tests/test_gui_audit.py documents).
    source = (Path(__file__).resolve().parent.parent / "gui_app.py").read_text(encoding="utf-8")
    assert 'source="demo"' in source
