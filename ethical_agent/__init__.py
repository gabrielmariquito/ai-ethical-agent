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

# Lido da distribuição instalada, não copiado do pyproject.
#
# Era `__version__ = "0.3.0"` aqui e `version = "0.3.0"` em pyproject.toml:
# dois literais que precisam ser iguais, sem nada prendendo os dois. Mesma
# forma do AUDIT_SESSION_COOKIE duplicado (achado 7 da DIVIDA-TECNICA), e a
# disposição registrada lá vale aqui -- **dois literais que precisam ser
# iguais são um literal**, e a solução é unificar, não escrever um teste
# prendendo os dois. Nenhum leitor de `__version__` existe hoje, então a
# divergência seria silenciosa até o primeiro, que receberia um número velho
# com cara de atual: proveniência falsa, que é o defeito que esta leva fecha.
#
# O fallback **não** repete o número. Fora de uma instalação a resposta certa
# é "não sei", não um valor plausível de origem desconhecida -- a mesma regra
# da coluna de assinatura em branco na tabela de marcos.
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
