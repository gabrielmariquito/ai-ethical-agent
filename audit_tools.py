#!/usr/bin/env python3
"""Leitura e geração de dados de exemplo para a trilha de auditoria:
`resumir` e `gerar`. `REGISTRO`, "Texto movido do código".
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ethical_agent._stdio import ensure_utf8_stdio

DEFAULT_AUDIT_LOG = "logs/audit.jsonl"
SYNTHETIC_ENGINE = "SYNTHETIC-SAMPLE-DATA"
# Matches the source="demo" GuardedAgent gets from `ethical_agent demo`, the
# web interface's Demo screen, and examples/demo.py.
DEMO_SOURCE = "demo"


def _is_synthetic(record: dict) -> bool:
    return record.get("engine") == SYNTHETIC_ENGINE or record.get("source") == DEMO_SOURCE


def _read_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def cmd_resumir(args: argparse.Namespace) -> int:
    path = Path(args.audit_log)
    records = _read_records(path)
    if not records:
        print(f"Nenhum registro em {path}.")
        return 0

    synthetic = [r for r in records if _is_synthetic(r)]
    real = [r for r in records if not _is_synthetic(r)]

    status_counts = Counter(r.get("status", "?") for r in real)
    engine_counts = Counter(r.get("engine", "?") for r in real)
    timestamps = sorted(r.get("timestamp", "") for r in real if r.get("timestamp"))

    print(f"Arquivo: {path}")
    print(f"Total de registros: {len(records)} ({len(synthetic)} sintéticos)")
    if real:
        print(f"Período: {timestamps[0]} .. {timestamps[-1]}")
        print("Por status:")
        for status, count in status_counts.most_common():
            print(f"  {status}: {count}")
        print("Por engine:")
        for engine, count in engine_counts.most_common():
            print(f"  {engine}: {count}")
    if synthetic:
        gerados = sum(1 for r in synthetic if r.get("engine") == SYNTHETIC_ENGINE)
        demo = sum(1 for r in synthetic if r.get("source") == DEMO_SOURCE)
        origens = []
        if gerados:
            origens.append(f"{gerados} de `audit_tools.py gerar`")
        if demo:
            origens.append(f"{demo} do comando `demo`")
        print(
            f"({len(synthetic)} registro(s) sintético(s) -- {'; '.join(origens)} "
            "-- dados de teste, não uso real)"
        )
    return 0


def cmd_gerar(args: argparse.Namespace) -> int:
    path = Path(args.audit_log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for i in range(args.n):
            record = {
                "event_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "denied" if i % 3 == 0 else "ok",
                "engine": SYNTHETIC_ENGINE,
                "config_versions": {"synthetic": True},
                "note": (
                    "Registro sintético gerado por `audit_tools.py gerar` "
                    "para demonstração -- não é uso real do sistema."
                ),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"{args.n} registro(s) sintético(s) adicionado(s) a {path}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="audit_tools.py",
        description="Ferramentas de leitura/geração de exemplo para logs/audit.jsonl.",
    )
    parser.add_argument("--audit-log", default=DEFAULT_AUDIT_LOG)
    sub = parser.add_subparsers(dest="command", required=True)

    p_resumir = sub.add_parser("resumir", help="resume o conteúdo do log de auditoria")
    p_resumir.set_defaults(func=cmd_resumir)

    p_gerar = sub.add_parser(
        "gerar", help="adiciona registros sintéticos de exemplo (dados de teste, não reais)"
    )
    p_gerar.add_argument("-n", type=int, default=5)
    p_gerar.set_defaults(func=cmd_gerar)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
