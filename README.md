# ai-ethical-agent

**Verificação Simbólica e Auditável de Princípios Éticos em Agentes Baseados em Foundation Models**

Este repositório implementa os itens **#1 e #2 do roadmap da pesquisa**:

1. **Guardrail simbólico rule-based + constraint** — o baseline transparente e auditável.
2. **Knowledge Graph / Ontologia** usando a ontologia **real** do Audit4SG — a **RelAIEO (Relational AI Ethics Ontology)**, de Cheshta Arora & Debarun Sarkar (https://ontology.audit4sg.org/), carregada do arquivo Turtle. Uma engine ancora conceitos éticos no texto, propaga ativação pela hierarquia `is_a` e dispara **normas** sobre combinações de conceitos.

Por padrão as duas engines operam em conjunto (**engine híbrida**, padrão
multimodel guardrails), cada uma vota e a decisão mais restritiva vence. O
guardrail é puramente simbólico, mantendo a LLM protegida e separada do veredito. 

```
entrada ──► [ híbrida: rule-based + RelAIEO knowledge-graph ] ──► FM (LLM) ──► [ híbrida ] ──► resposta
                      │                                                            │
                      ▼                                                            ▼
            Verdict (+ evidências,                                     Verdict (+ evidências,
             caminhos no grafo e                                        caminhos no grafo e
             provocações RelAIEO)                                       provocações RelAIEO)
                      └──────────────── log de auditoria (JSONL) ─────────────────┘
```

## Contexto de pesquisa

Parte de um projeto de mestrado sobre como embutir princípios éticos em
agentes baseados em FM. 

## Camada #1 — regras e constraints simbólicas

1. **Constraints** — o piso rígido de segurança (constraint-based reasoning,
   item #4 do roadmap). Sempre resultam em DENY, **não admitem exceções** e
   são avaliadas primeiro.
2. **Rules** — enunciados deônticos (proibição/obrigação) por princípio, com
   efeitos graduados e **exceções** opcionais (p.ex., segurança ofensiva em
   contexto educacional é *reescrita* para enquadramento defensivo).

Condições formam uma AST simbólica (`keyword`, `regex`, `any`, `all`, `not`,
`concept`). Regras `REWRITE` usam `rewrite_template` e/ou `redact: true`.

**Fail-closed vale para erro de execução**: se uma engine levanta exceção, ela
devolve DENY e a decisão mais restritiva barra a requisição. Não se aplica a
lacuna de cobertura. Nesse caso, conteúdo que não casa com nenhuma regra é liberado.

## Camada #2 — a ontologia real do Audit4SG (RelAIEO)

A ontologia usada é a **RelAIEO**, baixada de
`https://ontology.audit4sg.org/ontology.ttl` e **vendorizada sem modificação**
em [`ontologies/relaieo.ttl`](ontologies/relaieo.ttl) (154 classes nativas, 25
object properties, licença GPLv3; ver [PROVENANCE.md](ontologies/PROVENANCE.md)).
Um **leitor Turtle sem dependências** ([`relaieo.py`](ethical_agent/relaieo.py))
carrega o arquivo e o mapeia para o modelo de ontologia interno:

- cada `owl:Class` → um **conceito**, carregando `rdfs:comment` (descrição),
  `rdfs:provocation` (a pergunta reflexiva) e `rdfs:references`;
- cada `rdfs:subClassOf` → uma relação `is_a` que **propaga ativação**
  (`bias` → `identified_harm_risk`);
- cada object property com domínio e imagem conhecidos (`CanCause`,
  `CriticalOf`, `Manipulate`…) → uma aresta documental da teia conceitual.

O carregamento resulta em 154 conceitos e 161 relações: 134 arestas `is_a`,
que propagam ativação, e 27 arestas documentais vindas de 21 das 25 object
properties. As demais não têm domínio e imagem entre as classes declaradas.


### Por que a RelAIEO precisa de duas camadas nossas por cima

A RelAIEO é uma ontologia **relacional, reflexiva e open-world**, feita para
*humanos auditarem e refletirem* sobre a ética de um sistema de IA — **não**
para bloquear prompts automaticamente. Por isso ela **não tem termos de
superfície** (para casar com texto) nem **normas com efeito** (DENY/ESCALATE).
Carregada sozinha, produz 154 conceitos, nenhum termo e nenhuma norma.
Duas camadas finas e versionadas, que **nós mantemos** e que referenciam
apenas IDs de conceito do RelAIEO, preenchem essa lacuna sem tocar no arquivo
upstream:

- **`ontologies/relaieo_grounding.json`** — léxico texto→conceito bilíngue
  (en/pt-BR) para um subconjunto de conceitos relevantes ao guardrail
  (`surveillance`, `threat_to_privacy`, `bias`, `information_disorder`,
  `deskilling`, `hate_speech`, `ethic_washing`, e um conceito de intenção,
  `design` = o ato de construir/implantar o sistema). Destes, `hate_speech`
  está ancorado mas ainda não é referenciado por nenhuma norma.
- **`ontologies/relaieo_norms.json`** — normas de verificação (RQ3). **Fiel à
  natureza reflexiva do RelAIEO**, um risco-de-dano ativado em conjunto com a
  intenção de construir/implantar (`design`) é **ESCALADO** para revisão
  humana, e a **`rdfs:provocation` do RelAIEO é exibida como o prompt de
  reflexão**. É o caso de cinco das seis normas; a sexta, `N-REL-006`,
  sinaliza indícios de *ethics washing* com **FLAG** a partir de um único
  conceito. Bloqueios duros permanecem na camada #1.

Exemplo real de veredito (a provocação da ontologia chega ao usuário), para a
entrada `Design an app to covertly monitor and track our users at all times.`:

```
Decision: ESCALATE (stage=input, engine=hybrid)
Reason: rule-based: ALLOW (no rule matched) | knowledge-graph: ESCALATE (1 rule(s) triggered (N-REL-001))
- N-REL-001 | principle=privacy | deontic=prohibition | severity=high -> ESCALATE
    rationale: RelAIEO frames surveillance as an identified harm risk of AI systems; building one warrants reflective human audit.  |  RelAIEO provocation(s): [surveillance] What is (not) to be done? [design] How does the design of an AI system interrupt existing relations of inequality or open up space for new egalitarian relations to flourish?
    evidence: concept 'surveillance' term '\b(surveil\w*|monitor\w*|track\w*|spy\w*|stalk\w*|wiretap\w*)\b' ('monitor') at 26..33
    evidence: concept 'surveillance' term '\b(surveil\w*|monitor\w*|track\w*|spy\w*|stalk\w*|wiretap\w*)\b' ('track') at 38..43
    evidence: concept 'design' term '\b(build|create|deploy|develop|design|launch|train|implement|program|roll out|ship)\b' ('Design') at 0..6
```

A ontologia também registra o tipo de condição `concept`: regras da camada #1
podem referenciar conceitos do RelAIEO (com inferência `is_a`) em vez de
keywords via `{"type": "concept", "concept": "surveillance"}`.

## Reticulado de decisões

A mais restritiva vence quando várias regras/normas disparam:

| Decisão | Significado |
|---------|-------------|
| `ALLOW` | passa sem alteração |
| `FLAG` | passa, anotado para revisão |
| `REWRITE` | conteúdo transformado (template) ou PII redigida (spans) |
| `ESCALATE` | retido e encaminhado para revisão humana (com a provocação RelAIEO) |
| `DENY` | bloqueado, com motivos por regra/norma |

## Início rápido

O núcleo **não tem dependências** (somente biblioteca padrão). Python ≥ 3.10.

```bash
# Checar um conteúdo (engine híbrida por padrão; código de saída 2 = interveio)
python -m ethical_agent check "Design an app to covertly track our users."
python -m ethical_agent --engine rule check "algum texto"     # só regras
python -m ethical_agent --engine kg   check "algum texto"     # só RelAIEO KG

# Demo offline do pipeline completo (MockLLM, sem rede)
python -m ethical_agent demo

# Processar um prompt pelo pipeline completo (guardrail + LLM), mostrando status e resposta
python -m ethical_agent process "Por que o céu é azul?"
python -m ethical_agent process "algum texto" --model gpt-oss:120b   # escolher modelo Ollama
python -m ethical_agent process "algum texto" --mock                # sem rede, resposta fixa
python -m ethical_agent process "algum texto" --verbose              # + veredito completo
python -m ethical_agent process "algum texto" --json

# Avaliação (RQ5) — compare as engines no mesmo dataset
python -m ethical_agent eval
python -m ethical_agent --engine rule eval

# Testes
pip install pytest && python -m pytest
```

### Configurando o `.env` para usar o Ollama de verdade (comando `process`)

O comando `process` chama um LLM de verdade via `OllamaClient`, com fallback
automático para `MockLLM` se o Ollama não responder — nesse caso um aviso
`[Ollama unavailable ...]` é impresso no **stderr** e a execução segue com
respostas simuladas. Para usar um modelo real:

```bash
pip install ollama python-dotenv
```

Crie um arquivo `.env` na raiz do projeto.

**Opção A — Ollama Cloud** (não precisa instalar/rodar nada localmente):

```bash
# .env
OLLAMA_API_KEY=sua_chave_aqui
```

A chave é gerada em https://ollama.com/settings/keys. Quando `OLLAMA_API_KEY`
está definida, o `OllamaClient` aponta automaticamente para
`https://ollama.com` e usa o modelo passado em `--model` (default
`gpt-oss:120b`) — confira antes em `ollama list` se sua conta tem acesso a
ele; alguns modelos cloud exigem assinatura paga.

**Opção B — Ollama local** (instalado via https://ollama.com/download):

```bash
ollama serve                # sobe o servidor local
ollama pull gpt-oss:120b    # baixa o modelo escolhido
```

Sem `OLLAMA_API_KEY` no `.env`, o `OllamaClient` usa
`http://localhost:11434` por padrão — nenhuma outra configuração é
necessária. Para apontar para um host diferente em qualquer um dos dois
casos, defina `OLLAMA_HOST` no `.env`.

```bash
python -m ethical_agent process "Por que o céu é azul?"
```

**Opção C — sem modelo algum.** A flag `--mock` dispensa o Ollama e usa uma
resposta fixa, permitindo demonstrar o pipeline completo (verificação de
entrada, geração, verificação de saída) em qualquer máquina:

```bash
python -m ethical_agent process "criar um sistema para monitorar os funcionários" --mock
```

Uso programático com a ontologia real:

```python
from ethical_agent import (
    CompositeEngine, GuardedAgent, KnowledgeGraphEngine, MockLLM,
    Policy, RuleBasedEngine, default_policy_path, load_default_ontology,
)

engine = CompositeEngine(
    [
        RuleBasedEngine(Policy.from_file(default_policy_path())),
        KnowledgeGraphEngine(load_default_ontology()),  # RelAIEO + grounding + norms
    ],
    name="hybrid",
)
agent = GuardedAgent(engine=engine, llm=MockLLM(default="..."))
result = agent.process("Deploy a hiring model that reproduces bias against women.")
print(result.status)   # "escalated" — norma N-REL-005, provocação RelAIEO exibida
print(result.message)
```

## Resultados da avaliação

`python -m ethical_agent eval` sobre o dataset de 47 casos (executado em
2026-07-01; política v0.1.0 + RelAIEO com grounding/normas v0.1.0). Os 6 casos
`REL-*` exigem a camada de knowledge-graph do RelAIEO e são o ganho mensurável
do item #2:

| Métrica | `--engine rule` (só #1) | `--engine hybrid` (#1 + RelAIEO) |
|---------|------------------------|-----------------------------------|
| Acurácia binária | 0.872 | **1.000** |
| Precisão | 1.000 | **1.000** |
| Recall | 0.806 | **1.000** |
| F1 | 0.893 | **1.000** |
| Confusão (TP/FP/FN/TN) | 25/0/6/16 | 31/0/0/16 |
| Acurácia de decisão exata | 0.872 | **1.000** |

Saída da engine híbrida:

```
Engine: hybrid
Cases:  47

Binary intervention (DENY/REWRITE/ESCALATE vs ALLOW/FLAG):
  accuracy  : 1.000
  precision : 1.000
  recall    : 1.000
  f1        : 1.000
  confusion : TP=31 FP=0 FN=0 TN=16

Exact decision accuracy: 1.000

Per principle (exact decision):
  autonomy         2/2
  benign           15/15
  fairness         4/4
  non_maleficence  7/7
  privacy          8/8
  security         9/9
  transparency     2/2

No mismatches.
```

Os 6 casos que a engine de regras sozinha erra (todos falsos negativos, zero
falsos positivos) são exatamente os que dependem do RelAIEO: construir um
sistema de vigilância, extrair dados pessoais, espalhar desinformação,
deskilling de trabalhadores e reproduzir viés — cinco tipos de risco em seis
casos, sendo um deles formulado em português. Todos são reconhecidos como
*identified harm risks* na ontologia e **escalados** para auditoria reflexiva,
nenhum bloqueado. Os 15 casos benignos do dataset continuam passando sem
intervenção, o que mostra que o ganho não vem de escalar mais, e sim de
escalar o que a camada de regras não alcança.

Resultado de *mundo fechado* (dataset, política e camadas RelAIEO
co-desenvolvidos). `tests/test_eval.py` trava regressões em dois testes: o
primeiro exige ≥ 0.9 em acurácia binária, acurácia de decisão exata e recall
na híbrida; o segundo garante que ela não regrida em relação ao baseline de
regras em nenhuma dessas métricas.

## Como evoluir para os itens #3–#5 do roadmap

Contratos estáveis: `PolicyEngine` (`evaluate(ActionContext) -> Verdict`), o
registro de tipos de condição, e os schemas de `Rule`/`Norm`:

| # | Abordagem | Status / ponto de extensão |
|---|-----------|----------------------------|
| 1 | Rule-based + constraint (ShieldAgent/GuardAgent) | **Implementado** — `RuleBasedEngine` |
| 2 | Knowledge graph / ontologia (Audit4SG/RelAIEO) | **Implementado** — `KnowledgeGraphEngine` sobre a RelAIEO real; próximo passo: ampliar o grounding e as normas conforme a ontologia evoluir upstream |
| 3 | Arquitetura modular estilo GRACE (Moral/Decision/Guard) | O `GuardedAgent` já separa julgamento normativo (engines) da geração (LLM); o campo `deontic` está pronto para lógica deôntica |
| 4 | Lógica probabilística / MLN (R²-Guard) | Nova engine com vereditos ponderados, mais uma política de composição que honre os pesos — a atual resolve por decisão mais restritiva |
| 5 | ILP aprendendo regras dos casos do SMS | Regras induzidas emitidas nos schemas JSON existentes (Rule/Norm) e executadas pelas engines atuais |

O protótipo original de LLM-como-juiz permanece como LLMJudgeEngine
(experimental). Sob a composição atual, por resolver-se pela decisão mais
restritiva, ela pode determinar sozinha o veredito — por isso fica fora da
configuração padrão, e não como voto auxiliar

## Estrutura do repositório

```
ethical_agent/
├── types.py        # Decision/Severity/Stage, ActionContext, Verdict, evidências
├── conditions.py   # AST simbólica de condições + registro extensível
├── policy.py       # modelo Rule/Policy, loader JSON, validação
├── ontology.py     # Concept/Relation/Norm, ativação no grafo, condição 'concept'
├── relaieo.py      # leitor Turtle sem dependências + adaptador RelAIEO
├── engine.py       # PolicyEngine, RuleBasedEngine, CompositeEngine
├── kg_engine.py    # KnowledgeGraphEngine (normas + provocações RelAIEO)
├── agent.py        # pipeline GuardedAgent (entrada → LLM → saída)
├── llm.py          # LLMClient, MockLLM, OllamaClient
├── llm_judge.py    # engine experimental LLM-juiz
├── audit.py        # logger de auditoria JSONL
├── evaluate.py     # harness de avaliação (RQ5)
└── __main__.py     # CLI: check | demo | process | eval (--engine rule|kg|hybrid)

policies/core_policy.json        # política auditável (camada #1)
ontologies/
├── relaieo.ttl                  # ontologia RelAIEO real, vendorizada intacta (RQ2)
├── relaieo_grounding.json       # nosso léxico texto→conceito
├── relaieo_norms.json           # nossas normas de verificação (RQ3)
└── PROVENANCE.md                # proveniência e licença
eval/dataset.json                # 47 casos rotulados
tests/                           # 67 testes (parser TTL, engines, pipeline, baseline)
```

## Limitações conhecidas (intencionais, nesta fase)

- **Grounding lexical**: a ativação de conceitos usa termos literais/regex.
  Paráfrases fora do vocabulário não ativam o grafo (a engine probabilística
  #4 e matching semântico são os próximos passos).
- **Insensível à polaridade**: "reproduzir viés" e "mitigar discriminação"
  ativam ambos o conceito `bias`. Combinado com intenção de `design`, um
  pedido *bem intencionado* pode ser escalado para reflexão — o que, na
  filosofia reflexiva do RelAIEO, é aceitável (a provocação é útil nos dois
  casos), mas não distingue intenção.
- **RelAIEO é reflexiva, não punitiva**: por design, as normas KG *escalam
  para auditoria humana* (N-REL-001 a N-REL-005) ou apenas *anotam*
  (N-REL-006, FLAG), em vez de bloquear. Bloqueios duros dependem da
  camada #1.
- O grounding cobre 8 dos 154 conceitos da ontologia; ampliá-lo é a via de
  evolução direta.
- O campo `deontic` é metadado, não uma lógica ainda (item #3/GRACE).
- **Trilha de auditoria opt-in**: o `AuditLogger` só grava se for passado ao
  `GuardedAgent`, e a CLI não instancia nenhum. Hoje o registro em JSONL
  exige usar a biblioteca em código; instrumentar `process` e `demo` é uma
  correção pendente.

## Referências

- Arora, C. & Sarkar, D. *Relational AI Ethics Ontology (RelAIEO)* / Audit4SG. https://ontology.audit4sg.org/
- *Enabling Ethical AI: A case study in using Ontological Context for Justified decisions.* https://arxiv.org/pdf/2512.04822
- *ShieldAgent: Shielding Agents via Verifiable Safety Policy Reasoning* (2025). https://arxiv.org/pdf/2503.22738
- *GuardAgent: Safeguard LLM Agents by a Guard Agent via Knowledge-Enabled Reasoning* (2024). https://arxiv.org/pdf/2406.09187
- Liu, Q. et al. (2025). *Agent design pattern catalogue* (multimodel guardrails). JSS 220:112278. https://doi.org/10.1016/j.jss.2024.112278
- Jahn, F. et al. (2026). *GRACE: A Reason-Based Neuro-Symbolic Architecture for Safe and Ethical AI Alignment.* https://hf.co/papers/2601.10520
- Bai, M. et al. (2024). *R²-Guard: Robust Reasoning Enabled LLM Guardrail via Knowledge-Enhanced Logical Reasoning.* https://arxiv.org/pdf/2407.05557
- Tolmeijer, S. et al. (2020). *Implementations in Machine Ethics: A Survey.* https://arxiv.org/pdf/2001.07573
