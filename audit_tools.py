#!/usr/bin/env python3
"""Leitura e geração de dados de exemplo para a trilha de auditoria.

Lê `logs/audit.jsonl` (mesmo arquivo que `check`/`process`/`demo` gravam por
padrão, na CLI e na GUI -- ver AUDIT_GUIDE.pt-BR.md) usando apenas as chaves
do envelope comum a todo registro (`event_id`, `timestamp`, `status`,
`engine`, `config_versions`), presentes tanto num registro de `check` quanto
num de `process`/`demo`, sem precisar diferenciar a origem.

Uso:
    python3 audit_tools.py resumir [--audit-log logs/audit.jsonl]
    python3 audit_tools.py gerar [-n 5] [--audit-log logs/audit.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_AUDIT_LOG = "logs/audit.jsonl"
SYNTHETIC_ENGINE = "SYNTHETIC-SAMPLE-DATA"


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

    synthetic = [r for r in records if r.get("engine") == SYNTHETIC_ENGINE]
    real = [r for r in records if r.get("engine") != SYNTHETIC_ENGINE]

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
        print(
            f"({len(synthetic)} registro(s) gerado(s) por `audit_tools.py gerar` "
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
