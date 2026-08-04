from __future__ import annotations

import sys
import threading
from typing import Callable, List, Optional, Sequence, Union

from ethical_agent import (
    CompositeEngine,
    KnowledgeGraphEngine,
    Policy,
    RuleBasedEngine,
    load_relaieo,
    register_concept_condition,
    resolve_llm,
)
from ethical_agent.audit import audit_init_failure_message

from .state import _WebAuditLogger

# Espelha o `_build_engine`/`_build_llm` do `__main__.py`, sem nenhuma lógica de
# guardrail — só construção, e fica fino de propósito: `REGISTRO`, "Texto movido do código".


def build_engine(policy_path, ontology_path, grounding_path, norms_path, engine_kind):
    ontology = None
    if engine_kind in ("kg", "hybrid"):
        ontology = load_relaieo(ontology_path, grounding_path, norms_path)
        register_concept_condition(ontology)
    if engine_kind == "kg":
        return KnowledgeGraphEngine(ontology)
    rule_engine = RuleBasedEngine(Policy.from_file(policy_path))
    if engine_kind == "rule":
        return rule_engine
    return CompositeEngine([rule_engine, KnowledgeGraphEngine(ontology)], name="hybrid")


def build_llm(
    model: str,
    mock: bool,
    responses: Union[Sequence[str], Callable[[List[dict]], str], None] = None,
):
    """Thin wrapper over ethical_agent.resolve_llm, kept for naming parity
    with __main__.py's _build_llm / the former gui_app.py's build_llm.
    `responses` is forwarded as-is; see resolve_llm's own docstring."""
    return resolve_llm(model, mock, responses=responses)


def build_audit(path: str, lock: threading.Lock):
    """Devolve (logger ou None, aviso de inicialização ou None); a mesma frase
    do `_build_audit` da CLI, mas esta também a **devolve**, porque uma aba de
    navegador não tem stderr visível.
    """
    try:
        return _WebAuditLogger(path, lock), None
    except Exception as exc:  # noqa: BLE001
        msg = audit_init_failure_message(path, exc)
        print(msg, file=sys.stderr)
        return None, msg


def audit_notice_lines(audit: Optional[_WebAuditLogger], init_warning: Optional[str]) -> List[str]:
    """Collects any first-write disclosure / failure text to surface
    on-screen -- a browser tab has exactly the same "stderr may not be
    visible" problem the old Tkinter window had."""
    lines: List[str] = []
    if init_warning:
        lines.append(init_warning)
    if audit is not None:
        if audit.notice:
            lines.append(audit.notice)
        if audit.warning:
            lines.append(audit.warning)
    return lines
