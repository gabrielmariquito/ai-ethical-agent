from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from ethical_agent.llm import describe_llm_provenance

from .dto import classify_intervention

# Lê `logs/audit.jsonl` para reconstruir a lista de conversas e a transcrição
# somente-leitura, sendo a única fonte de histórico que sobrevive a reinício, e
# varre de trás para a frente parando assim que tem o que precisa:
# versão longa em `997a6fe^`.

LIST_LIMIT = 50
MAX_SCAN_LINES = 20_000


def iter_lines_reverse_offsets(
    path: Path, chunk_size: int = 65536, end_offset: Optional[int] = None
) -> Iterator[Tuple[int, str]]:
    """Devolve (offset em bytes, linha) do fim do arquivo para trás, em blocos,
    com o offset permanecendo válido pela vida de um arquivo append-only — é
    o que deixa a tela paginar por cursor e pular direto a um registro: versão longa em `997a6fe^`.
    """
    with path.open("rb") as handle:
        if end_offset is None:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
        else:
            position = max(0, end_offset)
        # Offset of the first byte of `trailing`, i.e. of the partial line
        # carried over from the chunk we have not read yet.
        trailing = b""
        trailing_offset = position
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            data = handle.read(read_size) + trailing
            parts = data.split(b"\n")
            trailing = parts[0]
            trailing_offset = position
            # parts[i] starts after all preceding parts plus their "\n".
            offset = position + len(parts[0]) + 1
            starts = []
            for part in parts[1:]:
                starts.append(offset)
                offset += len(part) + 1
            for part, start in zip(reversed(parts[1:]), reversed(starts)):
                stripped = part.rstrip(b"\r")
                if stripped:
                    yield start, stripped.decode("utf-8", errors="replace")
        stripped = trailing.rstrip(b"\r")
        if stripped:
            yield trailing_offset, stripped.decode("utf-8", errors="replace")


def _iter_lines_reverse(path: Path, chunk_size: int = 65536) -> Iterator[str]:
    """Lines only, newest first -- the original API, kept because the sidebar
    functions below have no use for offsets and reading them without the
    extra tuple is clearer."""
    for _offset, line in iter_lines_reverse_offsets(path, chunk_size):
        yield line


def iter_records_reverse(
    path: Path, end_offset: Optional[int] = None
) -> Iterator[Tuple[int, Optional[dict]]]:
    """Yields (byte_offset, record_or_None), newest first. A None record is a
    line that would not parse -- surfaced rather than skipped, because a
    reader for auditors should be able to say "there is something unreadable
    here" instead of quietly shortening the trail."""
    for offset, line in iter_lines_reverse_offsets(path, end_offset=end_offset):
        yield offset, _parse_line(line)


def _is_web_chat_turn(record: dict) -> bool:
    """Verdadeiro só para turnos que passaram pelo chat web, porque a presença
    da chave `conversation_id` já isola — o teste de `source` é guarda
    independente, não o filtro primário.
    """
    return "conversation_id" in record and record.get("source") != "demo"


def _parse_line(line: str) -> Optional[dict]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        # Tolerate a malformed line (e.g. a process killed mid-write)
        # instead of failing the whole listing.
        return None
    return record if isinstance(record, dict) else None


def summarize_conversations(audit_log_path: str, limit: int = LIST_LIMIT) -> dict:
    """Devolve as conversas mais recentes primeiro, com `truncated` verdadeiro
    quando a varredura parou por limite ou por teto de linhas.
    """
    path = Path(audit_log_path)
    if not path.exists():
        return {"conversations": [], "truncated": False}

    seen: Dict[str, dict] = {}
    scanned = 0
    hit_scan_cap = False
    for line in _iter_lines_reverse(path):
        if len(seen) >= limit:
            break
        scanned += 1
        if scanned > MAX_SCAN_LINES:
            hit_scan_cap = True
            break
        record = _parse_line(line)
        if record is None or not _is_web_chat_turn(record):
            continue
        conversation_id = record["conversation_id"]
        if conversation_id in seen:
            continue  # already captured this conversation's most recent turn
        preview_source = record.get("input") or record.get("message") or ""
        seen[conversation_id] = {
            "conversation_id": conversation_id,
            "turn_count": record.get("turn_index") or 1,
            "updated_at": record.get("timestamp"),
            "preview": preview_source[:80],
        }

    # Insertion order already matches the backward scan, i.e. newest first.
    # `truncated` can be a false positive in the rare case where the trail
    # has *exactly* `limit` conversations total (nothing was actually left
    # out) -- distinguishing that from "there's more" would cost an extra
    # lookahead read for a purely cosmetic difference, not worth it here.
    truncated = hit_scan_cap or len(seen) >= limit
    return {"conversations": list(seen.values()), "truncated": truncated}


def build_readonly_transcript(audit_log_path: str, conversation_id: str) -> Optional[List[dict]]:
    """`None` se a conversa não está na trilha; cada turno tem a mesma forma que
    um turno vivo **exceto** `response`, porque reusar `raw_response` ali
    derrotaria a razão de aquela chave ser condicional: versão longa em `997a6fe^`.
    """
    path = Path(audit_log_path)
    if not path.exists():
        return None

    matched: List[dict] = []
    scanned = 0
    for line in _iter_lines_reverse(path):
        scanned += 1
        if scanned > MAX_SCAN_LINES:
            break
        record = _parse_line(line)
        if record is None or not _is_web_chat_turn(record):
            continue
        if record.get("conversation_id") != conversation_id:
            continue
        matched.append(record)
        if record.get("turn_index") == 1:
            break  # reached this conversation's first turn; nothing earlier to find

    if not matched:
        return None
    matched.reverse()  # was newest-first from the backward scan; render oldest-first

    turns = []
    for record in matched:
        input_verdict = record.get("input_verdict")
        output_verdict = record.get("output_verdict")
        llm_provenance = record.get("llm_provenance")
        intervention = classify_intervention(
            (input_verdict or {}).get("decision", "ALLOW"),
            (output_verdict or {}).get("decision") if output_verdict else None,
        )
        turns.append(
            {
                "turn_index": record.get("turn_index"),
                "user_text": record.get("input", ""),
                "status": record.get("status"),
                "message": record.get("message", ""),
                "response": None,
                "llm_provenance": llm_provenance,
                "llm_provenance_text": describe_llm_provenance(llm_provenance) if llm_provenance else None,
                "input_verdict": input_verdict,
                "output_verdict": output_verdict,
                "intervention": intervention,
                "system_error": record.get("status") == "system_error",
            }
        )
    return turns
