# Guia de auditoria

Como examinar uma decisão do `ethical_agent`.

Nada depende de um modelo de IA. As decisões vêm de regras escritas em arquivos
versionados, e a mesma entrada sempre produz o mesmo resultado.

> [!NOTE]
> Existe uma engine experimental de LLM-como-juiz (`LLMJudgeEngine`) que **não**
> entra na configuração padrão, justamente porque quebraria essa propriedade. O
> campo `engine` de cada registro mostra quais camadas votaram.

---

## Passo 1 — Abrir a trilha

Por padrão, toda chamada a `check`, `process` ou `demo` — pela CLI
(`ethical_agent`) ou pela interface web (`ethical-agent serve`) — grava um registro
JSON em `logs/audit.jsonl`. O objetivo é permitir auditar o **uso real** do
sistema depois do fato: cada registro traz, além do resultado, a versão exata
da política e da ontologia (`config_versions`) que produziu aquele veredito.

### 1.1 Onde ela fica

- Caminho padrão: `logs/audit.jsonl`, um objeto JSON por linha.
- Pode ser trocado com `--audit-log CAMINHO` (CLI) ou pelo campo `Audit log`
  no painel **Configuração** da interface web.
- O arquivo e o diretório `logs/` são criados na primeira gravação. O
  instalador (`wizard_gui.py`) já cria `logs/` ao final, como conveniência.
- `eval` **nunca** grava: roda centenas de casos sintéticos direto contra a
  engine, e gravá-los poluiria a trilha com o que não é uso real.

### 1.2 Por que é obrigatória

Gravar o texto de entrada completo — que pode incluir dado pessoal — é uma
postura deliberada, não um acidente. E a trilha só sustenta a afirmação de
auditabilidade do projeto se não puder ser desligada: um registro que pode
ser silenciado é indistinguível, para quem lê depois, de "não houve
atividade". Por isso `check`/`process`/`demo` sempre gravam, na CLI e na
interface web — não existe flag, variável de ambiente ou checkbox para
desativar. O que continua configurável é **onde** ela grava (`--audit-log` /
campo equivalente na interface web), nunca **se** ela grava.

Na primeira gravação bem-sucedida de cada processo é impresso um aviso de uma
linha em `stderr` (e, na interface web, também como aviso na própria
conversa, já que uma aba de navegador pode não ter console visível):

```
[audit] writing to logs/audit.jsonl (mandatory; see AUDIT_GUIDE.pt-BR.md)
```

Uma falha ao gravar — permissão negada, caminho inválido — **nunca derruba o
comando nem muda o veredito**. É reportada como aviso e a execução segue:

```
[audit] could not write audit record to naodá (IsADirectoryError: ...); continuing without logging this event
```

> [!CAUTION]
> O registro guarda o texto de entrada **completo**. Trate `logs/audit.jsonl`
> como arquivo sensível.

> [!NOTE]
> **Registros antigos podem trazer mais do que os novos.** Até certo ponto, a
> evidência de uma regra com cláusula de ausência (`not`) era gravada com a
> condição inteira serializada — a lista completa das expressões que impedem a
> regra de disparar. Isso foi corrigido na origem, então **registros novos não
> carregam mais esse texto**; mas a trilha é append-only e **não foi
> reescrita**, de propósito: reescrever histórico de auditoria destrói a
> propriedade que faz a trilha valer alguma coisa, e seria um remédio pior que
> a doença.
>
> Consequência prática: quem abrir o `logs/audit.jsonl` direto, em vez de pela
> tela, ainda pode encontrar esse trecho em registros gravados antes da
> correção. A tela não o mostra mais. Se você for compartilhar um recorte da
> trilha, é um dos pontos a conferir.

### 1.3 Visão geral

```bash
python audit_tools.py resumir
```

```
Arquivo: logs/audit.jsonl
Total de registros: 3 (0 sintéticos)
Período: 2026-08-01T00:49:40.255684+00:00 .. 2026-08-01T00:49:40.578405+00:00
Por status:
  ok: 2
  denied: 1
Por engine:
  hybrid: 3
```

O contador de sintéticos separa uso real de dados de teste gerados por
`python audit_tools.py gerar` (marcados com `engine: "SYNTHETIC-SAMPLE-DATA"`).

### 1.4 Achar o caso que interessa

O `resumir` diz *quantos*, não *quais*. Para listar, copie este comando inteiro:

```bash
python -c "import json;[print(i,json.loads(l)['status'].ljust(7),(','.join(m['rule_id'] for m in json.loads(l)['input_verdict']['matches']) or '-').ljust(11),json.loads(l)['input'][:45]) for i,l in enumerate(open('logs/audit.jsonl',encoding='utf-8'),1)]"
```

```
1 ok      -           Por que o céu é azul?
2 denied  N-REL-005   We are building a tool to detect and avoid bi
3 ok      R-SEC-001   Me explique técnicas de invasão para fins edu
```

O número da esquerda é a linha do arquivo. É o que você usa no passo seguinte.

### 1.5 Abrir um registro

```bash
sed -n 2p logs/audit.jsonl | python -m json.tool --no-ensure-ascii
```

O `2p` é o número da linha. O `--no-ensure-ascii` preserva os acentos — sem
ele, "céu" sai como `c\u00e9u` e parece arquivo corrompido.

> [!NOTE]
> **Por que não abrir no bloco de notas?** O formato é JSONL: um registro
> completo por linha, sem quebras. É como um livro de ocorrências — ótimo para
> a máquina, ilegível para o olho. Você veria três linhas gigantescas.

---

## Passo 2 — Entender o registro

O julgamento está dentro de `input_verdict` (e de `output_verdict`, quando a
resposta do modelo também foi avaliada).

| Campo | Leitura |
|-------|---------|
| `decision` | `ALLOW` passou · `FLAG` passou marcado · `REWRITE` foi alterado · `DENY` bloqueado |
| `stage` | Avaliou o pedido da pessoa (`input`) ou a resposta do modelo (`output`) |
| `reason` | O voto de **cada camada**, separado por `\|`. Vence a mais restritiva |
| `matches` | As regras que dispararam — cada uma com seu ID, princípio e prova |
| `evidence` | **O trecho literal do texto que casou**, com as posições |
| `system_error` | Se `true`, o bloqueio veio de **falha interna**, não de regra |
| `suppressed` | Regras que iam disparar e foram **desarmadas por uma exceção** |

Fora do veredito, o registro traz `config_versions`: a versão exata da política
e da ontologia que julgaram aquele caso. É o que permite reabrir um registro
antigo e saber com quais regras ele foi decidido.

Dois outros campos, fora do veredito, respondem duas perguntas que
`input`/`output_verdict` sozinhos não respondem: **o que gerou o conteúdo
avaliado** e **o que o usuário efetivamente recebeu**.

**`llm_provenance`** (só em registros de `process`) diz o que produziu o
conteúdo, distinguindo três casos:

```jsonc
{"kind": "real", "model": "llama3.2:3b", "backend": "ollama_local"}   // modelo real, local ou "ollama_cloud"
{"kind": "mock_requested"}                                            // --mock / caixa "Mock" marcada de propósito
{"kind": "mock_fallback", "fallback_reason": "ConnectionError: ..."}  // Ollama falhou, caiu para mock
```

Antes desse campo, um `mock_fallback` era indistinguível de um `real`
bem-sucedido: o aviso ia só para `stderr` (CLI), nunca para o registro. Na
interface web, a caixa "Mock" vem **desmarcada** por padrão (chama o modelo
de verdade primeiro) e um `mock_fallback` agora também aparece como aviso
visível na própria conversa, não só neste campo do registro — mas o campo
continua sendo a fonte definitiva para quem lê a trilha depois.

**`message`** (em todo registro de `process`/`demo`) é o texto efetivamente
entregue ao usuário — a recusa em `DENY`/erro interno, ou a resposta final em
`ok`/`REWRITE`. Antes, só dava para inferir o conteúdo de uma reescrita via
`rewritten_output`; uma recusa (`DENY`) não deixava nenhum registro do que foi
dito. Isso fechava especificamente a auditoria de regras como `R-HARM-002`
(automutilação), cuja obrigação declarada é "surface help resources": sem
`message`, não havia como confirmar que o texto de ajuda (CVV, 988 etc.) foi
de fato mostrado.

`message` nunca reintroduz conteúdo que a regra de retenção descrita no Passo
1 protege: a recusa é montada só a partir de `rationale`/`user_message` das
regras que dispararam, nunca do conteúdo gerado ou bloqueado — o mesmo texto
que já aparece em `result.message` para quem chama a API diretamente.

Nem todo registro tem os quatro campos abaixo — a ausência costuma ser
deliberada, não esquecimento:

| Campo | `check` | `process` | `demo` | Por que a ausência (quando há) é deliberada |
|-------|:-------:|:---------:|:------:|----------------------------------------------|
| `config_versions` | ✅ | ✅ | ✅ | Sempre presente — não há caso de ausência |
| `llm_provenance` | ❌ | ✅ | ❌ | `check` nunca chama LLM. `demo` usa um `MockLLM` com respostas roteirizadas direto (fora do `resolve_llm`); já é inequivocamente sintético por causa do `source="demo"`, então o campo seria redundante |
| `message` | ❌ | ✅ | ✅ | `check` avalia conteúdo mas não gera mensagem para ninguém — forçar o campo seria um valor vazio/repetitivo, não sinal |
| `source` | ❌ | ❌ | ✅ | Marca especificamente dados sintéticos de demonstração (ver `audit_tools.py resumir`); `process` é uso real, não leva a marca |

### `conversation_id` / `turn_index` — conversas de múltiplos turnos

`GuardedAgent.process()` pode receber o histórico de turnos anteriores da
mesma conversa (para o **modelo** continuar de onde parou) junto de um
`conversation_id`/`turn_index` (para a **trilha** poder ser remontada
depois). Só a tela de conversa da interface web (`ethical-agent serve`) usa
isso hoje — a CLI continua turno único, sem esses dois campos. Quando
presentes, o registro traz:

```jsonc
{"conversation_id": "3f9a2b7c1e4d4a9f8b21...", "turn_index": 2}
```

`conversation_id` identifica a conversa; `turn_index` (a partir de 1) dá a
posição do turno dentro dela. Para reconstruir uma conversa em ordem:

```bash
python -c "
import json
records = [json.loads(l) for l in open('logs/audit.jsonl', encoding='utf-8')]
turns = sorted(
    (r for r in records if r.get('conversation_id') == 'SEU_ID_AQUI'),
    key=lambda r: r['turn_index'],
)
for r in turns:
    print(r['turn_index'], r['status'], r['message'][:80])"
```

Ambos os campos são omitidos (não aparecem como `null`) quando a chamada não
faz parte de uma conversa com histórico — mesmo padrão de `llm_provenance`,
acima.

**O histórico vivo de uma conversa existe só na memória do processo do
servidor** — reiniciar `ethical-agent serve` perde o contexto que o modelo
tinha das conversas em curso. Isso não afeta a trilha: cada turno já foi
gravado em `logs/audit.jsonl` no momento em que aconteceu. A lista lateral de
conversas anteriores da interface web faz exatamente a reconstrução do
comando acima (por trás, uma varredura do arquivo, não uma segunda cópia do
histórico) — mas sempre **somente leitura**: reabrir uma conversa antiga
nunca a realimenta para o modelo, porque o servidor não tem mais o contexto
vivo dela depois de reiniciar, e fingir que tem seria enganoso.

**O que o modelo recebe de um turno anterior que foi bloqueado ou
reescrito** — nunca o conteúdo bruto, sempre `message` (o texto que o
usuário de fato recebeu naquele turno):

| O que aconteceu no turno anterior | O que entra no histórico enviado ao modelo | Por quê |
|---|---|---|
| `input` foi `DENY` | **Nada** — o turno inteiro é omitido do histórico | O modelo nunca chegou a ver esse pedido (nem foi chamado); reintroduzi-lo depois anularia o bloqueio |
| `output` foi `DENY` | O texto de recusa (`message`) | O modelo viu o pedido do usuário — o que foi barrado foi a resposta dele, não o pedido |
| `output` foi `REWRITE` (redação, ex. PII) | A versão redigida (`message`) | O valor original nunca chega ao modelo, mesma garantia que já protege a trilha (Passo 1, "O que não dá para auditar") |
| `output` foi `REWRITE` (template) | A versão reescrita com aviso (`message`) | Igual acima, sem valor a redigir |
| Turno correu normalmente (`ok`) | A resposta entregue (`message`) | É o que de fato aconteceu na conversa do ponto de vista do usuário |

A entrada `DENY` de input e a `DENY` de output recebem tratamento diferente
de propósito, não por descuido: no primeiro caso o modelo nunca processou o
pedido; no segundo, ele processou e gerou uma resposta que foi barrada
depois — são situações diferentes.

A garantia por trás da coluna "o que entra no histórico" não é "cada campo
foi auditado caso a caso" — é estrutural: `message` é, por construção em
`GuardedAgent.process()`, o único campo que nunca carrega conteúdo
suprimido (uma `DENY` de saída nunca o preenche com o que foi bloqueado; uma
`REWRITE` por redação nunca o preenche com o valor bruto — é exatamente o
que os testes `test_denied_output_is_never_retained` e
`test_redacted_output_raw_response_not_retained_in_trace` já garantem, em
`tests/test_agent.py`). Usar `message` como único canal para o histórico
herda essas garantias já existentes, em vez de abrir uma superfície de
vazamento nova.

**Decisão de desenho, deliberada**: o guardrail avalia **só o turno novo** —
o `input` da vez e a `output` gerada para ele — nunca a conversa acumulada.
Por quê:

- Preserva a auditabilidade por decisão: cada registro continua explicável
  isoladamente, sem precisar reconstruir a conversa inteira para saber por
  que aquele turno específico foi liberado, bloqueado ou reescrito.
- Mantém válidos os números publicados de `eval` (Passo 7) — `eval` avalia
  turnos isolados direto contra a engine; se o guardrail passasse a depender
  de contexto acumulado, esses números deixariam de refletir o
  comportamento real numa conversa.
- Evita que uma mensagem bloqueada uma vez volte a disparar em todo turno
  seguinte só por estar sentada no histórico.

**Limite conhecido que essa decisão cria**: um ataque distribuído em vários
turnos individualmente inofensivos **não é detectado** por este desenho —
nada acumula entre turnos na avaliação do guardrail. Ver também a linha
correspondente em "O que não dá para auditar", abaixo.

**Nota**: turnos da mesma `conversation_id` podem legitimamente ter
`engine`/`config_versions`/`llm_provenance` diferentes entre si (a interface
web permite trocar modelo/engine entre turnos) — isso não é uma
inconsistência a investigar, é o comportamento esperado.

### Dois campos que mudam a leitura

**`system_error: true`** não é julgamento ético — é erro de execução que virou
`DENY` por segurança (*fail-closed*). Confundir os dois leva a auditar uma
regra que nunca disparou.

**`suppressed`** é onde se vê o sistema decidindo **não** intervir. Exemplo real
(registro 3 da listagem acima):

```
"decision":   "REWRITE"
"matches":    [ { "rule_id": "R-SEC-001" } ]
"suppressed": [ { "rule_id": "R-SEC-002",
                  "reason": "exception matched: educacionais",
                  "evidence": [ { "matched_text": "educacionais", "span": [42, 54] } ] } ]
```

`R-SEC-002` bloquearia com `DENY`, mas a palavra "educacionais" ativou uma
exceção e a desarmou. Sobrou `R-SEC-001`, que só reescreve. **A pergunta de
auditoria: bastava essa palavra para liberar?**

---

## Passo 3 — Conferir a prova

Este é o coração da auditoria. Rode o mesmo texto direto:

```bash
python -m ethical_agent check "We are building a tool to detect and avoid bias in our hiring model."
```

```
Decision: DENY (stage=input, engine=hybrid)
Reason: rule-based: ALLOW (no rule matched) | knowledge-graph: DENY (1 rule(s) triggered (N-REL-005))
- N-REL-005 | principle=fairness | deontic=prohibition | severity=high -> DENY
    rationale: RelAIEO frames bias as an identified harm risk rooted in structural inequality...
    evidence: concept 'bias' term '\bbias(ed|es)?\b' ('bias') at 43..47
    evidence: concept 'design' term '\b(build\w*|creat\w*|deploy\w*|...)\b' ('building') at 7..15
```

O `evidence` afirma que os caracteres 43 a 47 são a palavra `bias`, e que 7 a 15
são `building`. **Confira você mesmo**, direto do registro:

```bash
python -c "
import json
d = json.loads(open('logs/audit.jsonl', encoding='utf-8').readlines()[1])
t = d['input']; print('texto:', t)
for m in d['input_verdict']['matches']:
    for e in m['evidence']:
        a, b = e['span']
        print(f'  span {a}..{b} -> {t[a:b]!r}  (bate? {t[a:b] == e[\"matched_text\"]})')"
```

```
texto: We are building a tool to detect and avoid bias in our hiring model.
  span 43..47 -> 'bias'  (bate? True)
  span 7..15 -> 'building'  (bate? True)
```

A alegação foi verificada contra o dado, sem confiar no sistema. É isso que
torna a decisão auditável.

### Por que às vezes o trecho aparece e às vezes não

Conferindo vários registros, você vai encontrar duas situações que parecem
contraditórias e não são:

| Situação | `matched_text` | `span` |
|---|---|---|
| Constraint `DENY` (ex.: `R-INJ-001`, `N-REL-005`) | **presente** — o trecho exato do conteúdo bloqueado | presente |
| Regra com `redact: true` (ex.: `R-PRIV-002`) | `null` | presente |

É uma política só, com um critério só: **o motivo da intervenção**.

Bloquear conteúdo proibido precisa ser conferível. Se o registro de um
`DENY` não guardasse o excerto, você não teria como decidir se o bloqueio foi
correto — que é justamente a tarefa desta auditoria. Por isso a evidência de
uma constraint `DENY` retém o trecho casado de propósito, mesmo quando ele é
desagradável de ler (`'build a pipe bomb'`). Não é vazamento: o resto do
conteúdo bloqueado continua não sendo guardado (ver "O que **não** dá para
auditar").

Remover um dado pessoal precisa remover o dado. Uma regra de redação existe
para tirar um e-mail ou um CPF de circulação; guardá-lo no `matched_text` da
evidência anularia a própria regra. Por isso `Evidence.without_matched_text()`
(aplicada em `ethical_agent/engine.py`) limpa o campo quando `rule.redact` é
verdadeiro — e, no mesmo movimento, `raw_response` não é gravado
(`Verdict.suppresses_raw_content`).

O `span` fica nos dois casos, então você sempre sabe **onde** no texto a regra
casou, mesmo quando não pode ver **o quê**.

Na tela de auditoria (Passo 8) esta seção é a explicação: a tela marca a
ausência onde ela acontece — a evidência de uma regra de redação aparece com
"trecho: removido pela própria redação", em vez de simplesmente pular o campo —
mas não repete o porquê. É aqui que ele está.

---

## Passo 4 — Achar a regra no arquivo

Pegue o ID que apareceu e vá ler a definição. Cada prefixo mora num arquivo:

| Prefixo | Origem | Arquivo |
|---------|--------|---------|
| `C-*` | Constraint — piso rígido, sempre `DENY`, sem exceções | `policies/core_policy.json` |
| `R-*` | Rule — regra deôntica com efeito graduado | `policies/core_policy.json` |
| `N-REL-*` | Norma sobre conceitos da ontologia RelAIEO | `ontologies/relaieo_norms.json` |

```bash
python -c "
import json
n = json.load(open('ontologies/relaieo_norms.json'))
print(json.dumps([x for x in n['norms'] if x['id']=='N-REL-005'][0], ensure_ascii=False, indent=2))"
```

```json
{
  "id": "N-REL-005",
  "principle": "fairness",
  "effect": "DENY",
  "scopes": ["input", "output"],
  "when": ["bias", "design"],
  "description": "Designing/deploying a system that encodes or reproduces bias/discrimination."
}
```

Para `R-*` e `C-*`, troque o arquivo:

```bash
python -c "
import json
p = json.load(open('policies/core_policy.json'))
todos = p['constraints'] + p['rules']
print(json.dumps([x for x in todos if x['id']=='R-SEC-002'][0], ensure_ascii=False, indent=2))"
```

Três campos decidem a leitura:

- **`when`** (normas) ou **`condition`** (regras) — o que precisa acontecer para
  disparar. Em `N-REL-005`, os conceitos `bias` **e** `design` juntos.
- **`scopes`** — em quais estágios a regra roda. Sete das nove regras só olham
  o `input`.
- **`exceptions`** (só regras) — o que a desarma. É o que aparece em
  `suppressed`.

Para saber por que uma palavra ativou um conceito, olhe o léxico:

```bash
python -c "
import json
g = json.load(open('ontologies/relaieo_grounding.json'))
print(json.dumps(g['grounding']['bias'], ensure_ascii=False, indent=2))"
```

---

## Passo 5 — Descobrir qual camada decidiu

São duas camadas independentes que votam, e a mais restritiva vence. Rode o
mesmo texto nas três configurações:

```bash
for e in rule kg hybrid; do
  printf "%-7s " "$e"
  python -m ethical_agent --engine $e check "SEU TEXTO" | sed -n 1p
done
```

```
rule    Decision: ALLOW (stage=input, engine=rule-based)
kg      Decision: DENY (stage=input, engine=knowledge-graph)
hybrid  Decision: DENY (stage=input, engine=hybrid)
```

| Resultado | Significa |
|-----------|-----------|
| Só `rule` bloqueia | Decisão lexical — casou uma palavra ou padrão de texto |
| Só `kg` bloqueia | Decisão conceitual — a ontologia ativou conceitos |
| Os dois bloqueiam | Duas justificativas independentes |
| Os dois liberam, `hybrid` bloqueia | **Impossível** — se acontecer, é bug |

> [!TIP]
> Use `sed -n 1p`, não `head -1`. O `head` fecha o pipe cedo e a CLI imprime um
> `BrokenPipeError` que não tem nada a ver com o guardrail.

---

## Passo 6 — Reproduzir

Rode a mesma entrada duas vezes e compare, descartando o carimbo de tempo:

```bash
for i in 1 2; do
  python -m ethical_agent check --json "Deploy a hiring model that reproduces bias against women." \
  | python -c "import json,sys; d=json.load(sys.stdin); d.pop('created_at'); print(json.dumps(d,sort_keys=True))" > /tmp/run$i.json
done
diff /tmp/run1.json /tmp/run2.json && echo "IDÊNTICOS"
```

Reproduzir exige **três coisas iguais**: o texto, a configuração de engine
(`--engine`), e as versões de política e ontologia — aquelas gravadas em
`config_versions`. Se as versões mudarem, decisões antigas podem não se
reproduzir. Isso não é defeito: é exatamente por isso que a versão é gravada
junto com cada registro.

---

## Passo 7 — Testar a cobertura

Auditar uma decisão não diz se o sistema é bom no geral. Para isso, os três
datasets:

```bash
python -m ethical_agent eval
python -m ethical_agent eval --dataset eval/dataset_huggingface_injections.json
python -m ethical_agent eval --dataset eval/dataset_beavertails.json
```

Resultados da engine `hybrid` (medidos em 2026-08-01):

| | interno (47) | HF injections (662) | BeaverTails (220) |
|---|---|---|---|
| Precisão | 1.000 | 1.000 | 0.778 |
| Recall | 1.000 | 0.038 | 0.058 |
| TP/FP/FN/TN | 31/0/0/16 | 10/0/253/399 | 7/2/113/98 |

| Métrica | Pergunta que responde |
|---------|-----------------------|
| **Precisão** | Quando bloqueia, está certo? |
| **Recall** | Do que deveria bloquear, quanto pega? |
| **FP** | Bloqueou algo legítimo — o erro visível |
| **FN** | Deixou passar algo nocivo — o erro perigoso, e o mais comum aqui |

> [!IMPORTANT]
> **O dataset interno dá 1.000 em tudo, e isso não é boa notícia.** Ele foi
> escrito pela mesma pessoa e no mesmo momento que as regras: mede consistência
> interna, não capacidade de generalizar. Uma auditoria honesta usa os dois
> externos, onde o recall cai para 0.038 e 0.058 — e onde aparecem os primeiros
> falsos positivos medidos do projeto.

A saída lista os casos errados em `Mismatches`, com ID, esperado, obtido e
texto. É por ali que se investiga um erro específico.

---

## Passo 8 — A tela de auditoria

Tudo até aqui é feito na linha de comando. Existe também uma tela de leitura da
trilha, pensada para quem **não** vai rodar `python -c`: um auditor não técnico,
depois do fato, sobre decisões que não são dele.

```bash
ethical-agent serve --audit-password-file ~/.ethical-agent-audit-password
# ou:  ETHICAL_AGENT_AUDIT_PASSWORD=... ethical-agent serve
```

Depois, `http://127.0.0.1:8765/audit`.

### O registro em três camadas

A tela não mostra o registro inteiro de uma vez — mostrar tudo afoga quem não é
técnico, mostrar pouco impede o julgamento. A gradação é:

| Camada | Conteúdo | Estado |
|---|---|---|
| 1 | O que a pessoa pediu, o que o sistema fez, e por quê — em linguagem comum, sem identificador de regra e sem span | sempre visível |
| 2 | A norma que disparou, o `rationale` (que já traz a provocação RelAIEO), as evidências com trecho e posição, e o que foi afastado por exceção (`suppressed`) | um clique |
| 3 | Proveniência: `config_versions`, `llm_provenance`, `conversation_id`, `turn_index` | um clique |

Registros de uma mesma conversa são navegáveis em ordem — uma decisão só é
julgável em contexto. Quando uma regra de redação limpou o próprio trecho, a
camada 2 diz isso na evidência ("trecho: removido pela própria redação") em vez
de deixar um campo vazio; o motivo dessa assimetria está no Passo 3.

A lista marca as intervenções distinguindo **bloqueio** de **reescrita** — um
`DENY` e uma redação de e-mail têm gravidade bem diferente. O filtro padrão
mostra só conversas reais da web; demo, `check` e dados sintéticos ficam atrás
de "mostrar tudo", e a tela sempre diz quantos registros o filtro está
escondendo e quantas linhas da trilha varreu.

### A senha: o que ela é e o que não é

> [!CAUTION]
> **Isto é uma barreira, não segurança.** A senha existe para separar dois
> papéis — quem conversa com o agente e quem audita as decisões — não para
> resistir a um atacante. O servidor roda em `127.0.0.1`, sem HTTPS e sem
> infraestrutura de autenticação: a senha e o código de sessão trafegam em texto
> claro pelo loopback, o código de sessão vive apenas na memória do processo, e
> qualquer pessoa com acesso ao computador onde o servidor roda pode ler
> `logs/audit.jsonl` diretamente, sem passar por esta tela. O cookie é
> `HttpOnly`, o que impede o JavaScript da página de lê-lo; não impede que
> alguém sentado na máquina o veja nas ferramentas do navegador. O que a senha
> garante é que a trilha não abre por acidente, por curiosidade, ou porque
> alguém digitou `/audit` na barra de endereços. Não trate isto como controle de
> acesso a dado sensível.

A separação é estrutural, não visual: **sem senha configurada, a tela não
existe**. `/audit`, os endpoints `/api/audit/*` e os arquivos estáticos da tela
respondem o mesmo `404` de uma rota inexistente, para qualquer método —
esconder o link não bastaria, porque o servidor é local e qualquer um chega ao
endereço pela barra do navegador ou pelo devtools.

Não use `--audit-password VALOR` (não existe): um valor de argumento apareceria
na lista de processos e no histórico do shell. Também não guarde a senha num
arquivo dentro do repositório — o servidor avisa no `stderr` se você fizer isso,
porque é um `git add -A` de distância de ser commitada.

Reiniciar o servidor invalida todas as sessões (elas vivem só na memória do
processo). É comportamento documentado, não defeito: persistir um token de
sessão em disco seria gravar uma credencial ao lado da trilha que ela abre.

### A sessão do auditor é registrada — e ele é avisado

Numa aplicação sobre transparência, instrumentar sem avisar seria contraditório.
A tela avisa antes de pedir a senha, mantém um aviso permanente enquanto o
auditor trabalha, lista cada tipo de evento que pode gravar, e permite que ele
leia os próprios eventos (leitura que também é registrada).

```
logs/auditor_sessions.jsonl        --auditor-session-log
logs/policy_change_requests.jsonl  --change-requests-log
```

**Nenhum dos dois é `logs/audit.jsonl`, e o servidor se recusa a iniciar se
apontarem para o mesmo arquivo.** Misturar comportamento do auditor com decisão
do agente corromperia a trilha, que é o objeto de estudo — o mesmo raciocínio
que fez os registros de demo ganharem `source="demo"`.

O que é gravado: qual registro foi aberto, quanto tempo permaneceu nele
(`dwell_ms` e `visible_dwell_ms`, este só enquanto a aba está visível e com
foco — uma aba esquecida aberta a noite toda não vira "oito horas de leitura"),
quais camadas expandiu e em que ordem, se voltou a um registro já visto, e a
sequência de navegação.

O que **não** é gravado: nome, e-mail, endereço de rede, identificação do
navegador. O único identificador é um código de sessão anônimo gerado no
servidor; o vínculo entre sessão e participante, se existir, fica fora do
sistema. Para apagar o histórico de sessões, basta remover o arquivo — ele não
faz parte da trilha do agente.

Para inspecionar:

```bash
python -c "
import json
for line in open('logs/auditor_sessions.jsonl', encoding='utf-8'):
    e = json.loads(line)
    print(e['timestamp'], e['session_id'][:8], e['type'], e.get('record_event_id',''), e.get('dwell_ms',''))"
```

### "Isso deveria ser diferente"

Cada norma que disparou tem um botão para marcar que ela deveria ser outra,
ancorado em `(event_id, rule_id)`, com motivo **opcional de verdade** (forçar
justificativa produziria justificativas sobre ter sido perguntado). A marcação
vai para `logs/policy_change_requests.jsonl` com `"applied": false`.

**Nada muda na política.** É registro de intenção; a edição efetiva das regras,
com versionamento e histórico, é a mudança seguinte. A tela diz isso no
formulário e na confirmação, porque um auditor que acredita ter corrigido uma
regra passaria a julgar os registros seguintes contra uma política que não se
moveu.

---

## O que **não** dá para auditar

| Limite | Consequência |
|--------|--------------|
| Conteúdo bloqueado no `stage=output` (via `process`/`demo`, ou `check --stage output`) | É descartado antes de chegar ao log. Ver `tests/test_agent.py::test_denied_output_is_never_retained` e o equivalente de CLI em `tests/test_main.py::test_check_output_stage_denied_content_not_retained` |
| A senha da tela `/audit` | Não é controle de acesso: barra o acesso casual, não quem tem acesso ao computador — que lê `logs/audit.jsonl` direto. Ver Passo 8 |
| Casos de `eval` | `ethical_agent eval` roda os casos sintéticos direto contra a engine e nunca grava no audit log, por desenho |
| **`ALLOW` por falta de regra ≠ `ALLOW` por julgamento** | Os dois aparecem como `matches: []`. Com 12 entradas de política, a maior parte dos `ALLOW` é do primeiro tipo. Ausência de bloqueio raramente significa "foi julgado seguro" |
| 7 das 9 regras têm `scopes: ["input"]` | Uma resposta nociva gerada pelo modelo passa mesmo usando o vocabulário exato de uma regra. É lacuna estrutural, não lexical |
| O léxico cobre 8 dos 154 conceitos | A maior parte da ontologia está carregada mas inerte. `hate_speech` tem termos e nenhuma norma o referencia — ativá-lo não faz nada |
| Ataque distribuído em vários turnos, cada um individualmente inofensivo | O guardrail avalia só o turno novo (input + output da vez), nunca a conversa acumulada — ver `conversation_id`/`turn_index` no Passo 2. Um objetivo nocivo montado por partes ao longo de vários turnos não é detectado por desenho |
| Não distingue polaridade nem intenção |

---

## Checklist

**Auditando uma decisão:**

- [ ] Localizei o registro na trilha (`resumir` → listagem → `sed -n Np`)
- [ ] Conferi os spans do `evidence` contra o texto original
- [ ] `system_error` é `false`? (senão não é julgamento, é falha)
- [ ] Olhei o `suppressed` — alguma exceção desarmou uma regra? Ela se justifica?
- [ ] Abri a regra no JSON e li o `when` / `condition`, o `scopes` e as `exceptions`
- [ ] Rodei nas três engines para saber qual camada decidiu
- [ ] Reproduzi e anotei as `config_versions`
- [ ] Se o `matched_text` veio `null`, confirmei que a regra tem `redact: true` (e não que a evidência sumiu) — Passo 3

**Auditando o sistema:**

- [ ] Rodei os **três** datasets, não só o interno
- [ ] Li os `Mismatches`, não só as métricas agregadas
- [ ] Testei frases bem-intencionadas (falsos positivos)
- [ ] Testei frases nocivas fora do vocabulário (falsos negativos)
- [ ] Li as limitações do [`README.md`](README.md) antes de concluir qualquer coisa

---

## Apêndice — `audit_tools.py`

Script auxiliar na raiz do repositório, com dois comandos. Ambos aceitam
`--audit-log CAMINHO`.

```bash
python audit_tools.py resumir
```

Lê `logs/audit.jsonl` e imprime contagens por status e por engine, mais o
período coberto e quantos registros são sintéticos. É o Passo 1.3 deste guia.

```bash
python audit_tools.py gerar -n 5
```

Adiciona registros **sintéticos**, claramente marcados com
`engine: "SYNTHETIC-SAMPLE-DATA"`, para testar o `resumir` ou gerar capturas de
tela de documentação.

> [!WARNING]
> Registros gerados assim **nunca são uso real**. Não confunda com a trilha
> produzida por `check`/`process`/`demo`. O `resumir` conta os dois
> separadamente justamente para evitar que alguém audite dados de teste
> achando que auditou o sistema em produção.

---

Veja também a seção "Registro de auditoria e versionamento de configuração" no
[`README.md`](README.md).
Veja também a seção "Registro de auditoria e versionamento de configuração"
no `README.md`.
