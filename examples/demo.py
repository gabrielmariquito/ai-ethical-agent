"""Exemplo mínimo de uso da biblioteca: engine híbrida mais `GuardedAgent`,
ligado ao `resolve_llm` e ao `DEMO_CASES` compartilhados: versão longa em `997a6fe^`.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ethical_agent import (
    AuditLogger,
    CompositeEngine,
    GuardedAgent,
    KnowledgeGraphEngine,
    Policy,
    RuleBasedEngine,
    default_policy_path,
    describe_llm_provenance,
    load_default_ontology,
    resolve_llm,
)
from ethical_agent.demo import DEMO_CASES
from ethical_agent.ontology import register_concept_condition


def main():
    ontology = load_default_ontology()
    # A condição 'concept' só existe depois disto; sem o registro, uma política
    # que a use falha ao carregar.
    register_concept_condition(ontology)

    engine = CompositeEngine(
        [
            RuleBasedEngine(Policy.from_file(default_policy_path())),
            KnowledgeGraphEngine(ontology),
        ],
        name="hybrid",
    )

    # Sem mock: tenta o Ollama e cai para MockLLM se ele não responder,
    # dizendo qual dos dois foi -- é o que `provenance` carrega.
    llm, provenance = resolve_llm(model="llama3.2:3b", mock=False)
    print(describe_llm_provenance(provenance))

    agent = GuardedAgent(
        engine=engine,
        llm=llm,
        audit=AuditLogger("logs/audit.jsonl"),
        source="demo",
        llm_provenance=provenance,
    )

    for prompt in DEMO_CASES:
        result = agent.process(prompt)
        print("=" * 72)
        print(f"USER   : {prompt}")
        print(f"STATUS : {result.status.upper()}")
        print(f"AGENT  : {result.message}")
    print("=" * 72)
    print("Trilha completa em logs/audit.jsonl (source=\"demo\").")


if __name__ == "__main__":
    main()
