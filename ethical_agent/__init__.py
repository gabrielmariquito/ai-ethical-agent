# ai-ethical-agent -- guardrail simbólico e auditável para agentes baseados em
# modelos de linguagem.
# Copyright (C) 2026  Gabriel Mariquito
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# O aviso fica aqui e em `__main__.py`, os dois pontos de entrada, e **não** nos
# arquivos de configuração: o sha256 de cada um deles é a identidade que entra
# no `config_id` da trilha, e um byte a mais tornaria todo registro já gravado
# não comparável com os novos. Procedência do que é emprestado e do que é
# autoral em `ontologies/PROVENANCE.md`.

from .agent import AgentResult, GuardedAgent
from .audit import AuditLogger, build_check_audit_record
from .conditions import (
    Condition,
    ConditionError,
    condition_from_dict,
    register_condition_type,
)
from .engine import CompositeEngine, PolicyEngine, RuleBasedEngine
from .kg_engine import KnowledgeGraphEngine
from .llm import (
    LLMClient,
    MockLLM,
    OllamaClient,
    describe_llm_provenance,
    resolve_llm,
)
from .llm_judge import LLMJudgeEngine
from .ontology import (
    Concept,
    ConceptCondition,
    Norm,
    Ontology,
    OntologyError,
    Relation,
    register_concept_condition,
)
from .relaieo import (
    default_grounding_path,
    default_norms_path,
    default_relaieo_ttl,
    load_default_ontology,
    load_relaieo,
    parse_relaieo,
)
from .policy import Policy, PolicyError, Rule, default_policy_path
from .types import (
    ActionContext,
    Decision,
    Evidence,
    RuleMatch,
    Severity,
    Stage,
    SuppressedMatch,
    Verdict,
)

# Lido da distribuição instalada, não copiado do `pyproject`: dois literais que
# precisam ser iguais são um literal (achado 7 do REGISTRO), e o fallback **não**
# repete o número — versão longa em `997a6fe^`.
try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _distribution_version

    __version__ = _distribution_version("ai-ethical-agent")
except PackageNotFoundError:  # checkout sem instalar
    __version__ = "0+desconhecida"

__all__ = [
    "ActionContext",
    "AgentResult",
    "AuditLogger",
    "CompositeEngine",
    "Concept",
    "ConceptCondition",
    "Condition",
    "ConditionError",
    "Decision",
    "Evidence",
    "GuardedAgent",
    "KnowledgeGraphEngine",
    "LLMClient",
    "LLMJudgeEngine",
    "MockLLM",
    "Norm",
    "OllamaClient",
    "Ontology",
    "OntologyError",
    "Policy",
    "PolicyEngine",
    "PolicyError",
    "Relation",
    "Rule",
    "RuleBasedEngine",
    "RuleMatch",
    "Severity",
    "Stage",
    "SuppressedMatch",
    "Verdict",
    "build_check_audit_record",
    "condition_from_dict",
    "default_grounding_path",
    "default_norms_path",
    "default_policy_path",
    "default_relaieo_ttl",
    "describe_llm_provenance",
    "load_default_ontology",
    "load_relaieo",
    "parse_relaieo",
    "register_concept_condition",
    "register_condition_type",
    "resolve_llm",
    "__version__",
]
