"""Exemplo mínimo de uso da biblioteca: engine híbrida + GuardedAgent.

Nada aqui é próprio do exemplo além do laço de impressão. A construção do
LLM vem de `resolve_llm` e os prompts de `ethical_agent.demo.DEMO_CASES`, que
são os mesmos que a CLI (`ethical_agent demo`) e a tela Demo da interface web
usam. Isso é deliberado: este arquivo já teve um `build_llm()` próprio, escrito
antes de a proveniência existir, e os registros que ele gravava saíam sem
`llm_provenance` -- a mesma divergência que `check_audit_record` e
`resolve_llm` já custaram a este projeto, numa quarta cópia.
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
