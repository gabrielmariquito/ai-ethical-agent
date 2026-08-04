"""Cobertura de regressão do `UnicodeEncodeError` sob cp1252, forçado via
`PYTHONIOENCODING` num subprocesso porque o ambiente normal do pytest nunca
reproduz a condição: `REGISTRO`, "Texto movido do código".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ethical_agent._stdio import ensure_utf8_stdio

REPO_ROOT = Path(__file__).resolve().parents[1]
HUGGINGFACE_DATASET = REPO_ROOT / "eval" / "dataset_huggingface_injections.json"


def _env(*, utf8_mode: bool) -> dict:
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    if utf8_mode:
        # Today's workaround: what a user who already knows to set this gets.
        env["PYTHONUTF8"] = "1"
    else:
        # The bug scenario: an unconfigured Windows session's default,
        # reproduced cross-platform via PYTHONIOENCODING. "strict" errors so a
        # bad character raises instead of being silently dropped, matching
        # Windows' actual default error mode.
        env["PYTHONIOENCODING"] = "cp1252:strict"
    return env


def _run_cli(args: list[str], *, utf8_mode: bool) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "ethical_agent", *args],
        cwd=REPO_ROOT,
        env=_env(utf8_mode=utf8_mode),
        capture_output=True,
    )


def test_eval_json_survives_restricted_stdout_encoding_and_matches_utf8_mode():
    args = ["--engine", "rule", "eval", "--dataset", str(HUGGINGFACE_DATASET), "--json"]
    restricted = _run_cli(args, utf8_mode=False)
    reference = _run_cli(args, utf8_mode=True)

    assert b"UnicodeEncodeError" not in restricted.stderr, restricted.stderr.decode(
        "utf-8", "replace"
    )
    assert restricted.returncode == reference.returncode
    assert restricted.stdout, "stdout was empty -- exactly the bug this test guards against"

    # Byte-for-byte identical to the known-good (PYTHONUTF8=1) run: the fix
    # must reproduce that output without requiring the env var, not just
    # avoid crashing.
    assert restricted.stdout == reference.stdout

    results = json.loads(restricted.stdout.decode("utf-8"))
    assert results["total_cases"] > 0


def test_eval_text_report_survives_restricted_stdout_encoding_and_matches_utf8_mode():
    args = ["--engine", "rule", "eval", "--dataset", str(HUGGINGFACE_DATASET)]
    restricted = _run_cli(args, utf8_mode=False)
    reference = _run_cli(args, utf8_mode=True)

    assert b"UnicodeEncodeError" not in restricted.stderr, restricted.stderr.decode(
        "utf-8", "replace"
    )
    assert restricted.returncode == reference.returncode
    assert restricted.stdout, "stdout was empty -- exactly the bug this test guards against"
    assert restricted.stdout == reference.stdout
    assert b"Binary intervention" in restricted.stdout


def test_check_survives_restricted_stdout_encoding_with_non_cp1252_input(tmp_path):
    # A lock emoji (U+1F512) is well outside cp1252 -- unlike accented
    # Portuguese/German/French letters, which cp1252 can represent fine.
    text = "Qual \U0001f512 é o CPF do meu vizinho?"
    # Plain (non --json) output: `explain()` has no timestamp field, so the
    # two runs' stdout is directly comparable byte-for-byte (unlike --json,
    # whose payload embeds Verdict.created_at). Audit log redirected to
    # tmp_path so this doesn't write into the repo's real logs/audit.jsonl.
    audit_log = tmp_path / "audit.jsonl"
    args = ["--audit-log", str(audit_log), "check", text]
    restricted = _run_cli(args, utf8_mode=False)
    reference = _run_cli(args, utf8_mode=True)

    assert b"UnicodeEncodeError" not in restricted.stderr, restricted.stderr.decode(
        "utf-8", "replace"
    )
    assert restricted.returncode == reference.returncode
    assert restricted.stdout, "stdout was empty -- exactly the bug this test guards against"
    assert restricted.stdout == reference.stdout


class _StreamWithoutReconfigure:
    """Stand-in for a stream that lacks .reconfigure() (e.g. some non-standard
    capture wrappers) -- ensure_utf8_stdio must not blow up on it."""


class _StreamWithReconfigure:
    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


def test_ensure_utf8_stdio_noops_on_stream_without_reconfigure(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _StreamWithoutReconfigure())
    monkeypatch.setattr(sys, "stderr", _StreamWithoutReconfigure())
    ensure_utf8_stdio()  # must not raise


def test_ensure_utf8_stdio_reconfigures_encoding_to_utf8(monkeypatch):
    fake_stdout = _StreamWithReconfigure()
    fake_stderr = _StreamWithReconfigure()
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    ensure_utf8_stdio()

    assert fake_stdout.calls == [{"encoding": "utf-8"}]
    assert fake_stderr.calls == [{"encoding": "utf-8"}]


def test_ensure_utf8_stdio_swallows_reconfigure_errors(monkeypatch):
    class _Broken:
        def reconfigure(self, **kwargs):
            raise ValueError("already detached")

    monkeypatch.setattr(sys, "stdout", _Broken())
    monkeypatch.setattr(sys, "stderr", _Broken())
    ensure_utf8_stdio()  # must not raise
