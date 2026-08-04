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
| `suppressed` | Regras que iam disparar e foram **rebaixadas por uma exceção**, com `demoted_to` dizendo para qual efeito |

Fora do veredito, o registro traz `config_versions`: a versão exata da política
e da ontologia que julgaram aquele caso. É o que permite reabrir um registro
antigo e saber com quais regras ele foi decidido.

### `configuration` — quais arquivos governaram a decisão, e o `config_id`

`config_versions` diz a versão **declarada**, e essa é justamente a afirmação
que quem escreve a política pode errar: se alguém editar uma regra e não subir
`metadata.version`, dois registros alegam a mesma versão e foram decididos
diferente. A trilha não teria como distinguir os dois.

Por isso cada registro traz também um bloco `configuration`, com **um artefato
por arquivo de configuração carregado**:

```jsonc
"configuration": {
  "config_id": "72f0a82f03bd37b12226182c1833667d83b0c12fb9991d9f3cede9854b3d115f",
  "config_id_recipe": "config-id/v1",
  "artifacts": [
    {"role": "frames_refusal", "version": "0.1.0", "sha256": "57b85b36…", "path": "…/refusal_frames.json"},
    {"role": "harm_grounding", "version": "0.1.0", "sha256": "ec9984e4…", "path": "…/harm_grounding.json"},
    {"role": "harm_norms",   "version": "0.1.0", "sha256": "af8b3514…", "path": "…/harm_norms.json"},
    {"role": "harm_ttl",     "version": null,    "sha256": "f4a6c988…", "path": "…/harm_taxonomy.ttl"},
    {"role": "grounding",    "version": "0.2.0", "sha256": "a2b3d4f1…", "path": "…/relaieo_grounding.json"},
    {"role": "norms",        "version": "0.2.0", "sha256": "57609812…", "path": "…/relaieo_norms.json"},
    {"role": "ontology_ttl", "version": null,    "sha256": "30098683…", "path": "…/relaieo.ttl"},
    {"role": "policy",       "version": "0.6.0", "sha256": "9118da81…", "path": "…/core_policy.json"}
  ]
}
```

**Por que existem versão *e* digest.** São duas perguntas diferentes:

- **`version`** é a versão **declarada**, lida do arquivo já carregado na
  memória. É *o que o autor quis dizer*.
- **`sha256`** é o resumo criptográfico do **arquivo em disco**, calculado na
  hora em que o registro foi gravado. É *o que de fato foi carregado*.

Quando os dois concordam, não há nada a notar. Quando alguém edita um arquivo
sem subir a versão, só o digest muda — e é exatamente esse o caso que a versão
declarada sozinha esconderia.

Repare na linha `ontology_ttl`: **versão `null`**. Aquele arquivo é a ontologia
RelAIEO, trazida do projeto de origem sem modificação, e o projeto de origem não
declara versão nenhuma. Para ele o digest não confere a versão — é a **única**
identidade que existe.

**O `config_id` responde a pergunta prática.** Ele é um resumo do conjunto
inteiro, e serve para responder, olhando dois registros lado a lado:

> *"Estes dois casos foram decididos sob as mesmas regras?"*

- **`config_id` igual** ⇒ a configuração era idêntica, arquivo por arquivo,
  byte por byte. Os dois registros são **diretamente comparáveis**: qualquer
  diferença de veredito entre eles vem do texto avaliado, não das regras.
- **`config_id` diferente** ⇒ alguma coisa mudou. Compare a coluna `sha256`
  linha a linha para achar qual arquivo — e note que isso vale **mesmo quando
  as versões declaradas são iguais nos dois**.

Na tela de auditoria isso aparece na camada 3, em "Quais arquivos governaram
esta decisão", com os doze primeiros caracteres do `config_id` em destaque (o
valor inteiro fica no `title`, ao passar o mouse).

O `config_id` é calculado por uma receita **escrita por extenso** em
`ethical_agent/provenance.py`, versionada em `config_id_recipe`. Duas
consequências que importam para quem audita: o caminho do arquivo **não** entra
na conta (senão duas máquinas com a mesma configuração dariam ids diferentes), e
mudar a receita muda todos os ids, em vez de gerar em silêncio outra grandeza
com o mesmo nome.

> [!NOTE]
> **Registros anteriores a este campo não têm `configuration`.** A tela diz
> isso na cara — "Este registro é anterior à procedência de configuração" — em
> vez de deixar a área em branco. Ausência declarada é informação; buraco não é.

Dois outros campos, fora do veredito, respondem duas perguntas que
`input`/`output_verdict` sozinhos não respondem: **o que gerou o conteúdo
avaliado** e **o que o usuário efetivamente recebeu**.

**`llm_provenance`** (só em registros de `process`) diz o que produziu o
conteúdo, distinguindo três casos:

```jsonc
{"kind": "real", "model": "llama3.2:3b", "backend": "ollama_local"}   // modelo real, local ou "ollama_cloud"
{"kind": "mock_requested"}                                            // --mock / caixa "Mock" marcada de propósito
{"kind": "mock_fallback", "requested_model": "gpt-oss:120b",          // Ollama falhou, caiu para mock
 "model_label": "mock (fallback from gpt-oss:120b)",
 "fallback_reason": "ConnectionError: ..."}
```

No terceiro caso o registro diz **em vez de qual modelo** a simulação rodou.
Sem isso, "mock porque o operador pediu" e "mock porque o modelo configurado
não respondeu" chegam iguais a quem lê a trilha — e só o segundo significa que
um modelo configurado silenciosamente não rodou. Registros gravados antes de
`requested_model` existir simplesmente não o trazem, e a tela continua os
mostrando.

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
| `configuration` | ✅ | ✅ | ✅ | Sempre presente **em registros novos**. Ausente em registros gravados antes deste campo existir e nas amostras sintéticas de `audit_tools.py gerar` — nos dois casos a tela declara a ausência |
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
"matches":    [ { "rule_id": "R-SEC-001" },
                { "rule_id": "R-SEC-002", "effect": "REWRITE",
                  "demoted_from": "DENY" } ]
"suppressed": [ { "rule_id": "R-SEC-002",
                  "reason": "exception matched: educacionais",
                  "demoted_to": "REWRITE",
                  "evidence": [ { "matched_text": "educacionais", "span": [42, 54] } ] } ]
```

`R-SEC-002` bloquearia com `DENY`, mas a palavra "educacionais" ativou uma
exceção e a desarmou. **A pergunta de auditoria: bastava essa palavra para
rebaixar?**

> [!IMPORTANT]
> **Desde a política v0.7.0, uma regra suprimida rebaixa para um efeito
> declarado — ela não sai mais da contagem.** Leia os dois campos novos:
>
> - **`suppressed[].demoted_to`** diz **para quê** a regra foi rebaixada. Este
>   é o campo que responde "sobrou alguma coisa?". `"ALLOW"` ali significa que
>   a isenção liberou o pedido inteiro — e agora significa isso **por decisão
>   escrita na regra**, não por omissão do motor.
> - **`matches[].demoted_from`** aparece na mesma regra do outro lado, com o
>   efeito que de fato votou. Em `R-SEC-002` você lê `effect: "REWRITE"` com
>   `demoted_from: "DENY"`: a política declara `DENY`, e o que valeu foi o
>   sucessor. Sem esse campo o registro pareceria uma política diferente da que
>   está no arquivo.
>
> **O que mudou, e por que o guia dizia o contrário até a versão anterior.**
> Até a v0.6.0 o motor descartava a regra isenta e nada assumia o lugar dela:
> medido sobre as 66 combinações de gatilho de `R-SEC-002` com termo do seu
> `exceptions`, **54 terminavam em `ALLOW` com `matches` vazio** — inclusive
> `"Ways to steal credentials for educational purposes"` e `"Quero roubar senha
> para aprender segurança"`. As 66 hoje terminam em `REWRITE`.
>
> **Consequência para quem audita, agora:** ver uma linha em `suppressed` já não
> exige deduzir o resto de `matches` — leia `demoted_to` no mesmo registro. O
> que precisa de justificativa é o **rebaixamento**: a isenção era legítima, e o
> efeito que sobrou é proporcional ao pedido? Um `demoted_to: "ALLOW"` continua
> sendo o caso a olhar com mais atenção, porque ali não sobrou nada — a
> diferença é que agora alguém escreveu que não deveria sobrar.
>
> **Registros anteriores a v0.7.0 não têm os dois campos.** Num registro antigo,
> `suppressed` sem `demoted_to` significa o comportamento antigo: nada assumiu,
> a menos que outra regra apareça em `matches` por conta própria.
> `tests/test_sucessor_da_supressao.py` traz a grade completa das 66
> combinações, e `tests/test_sucessor_declarado.py` cobra que toda regra com
> `exceptions` declare o sucessor.

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

### A evidência também diz o que a regra procurava

No campo `description` de cada evidência você vai encontrar o critério da
condição por extenso — a palavra-chave, ou o padrão de regex inteiro:

```json
"description": "regex '\\b(ignore|disregard|forget|desconsidere)\\b[^.?!]{0,40}\\b(instructions?|system prompt|regras)\\b'"
"description": "keyword 'dosage'"
"description": "regex '\\baprender\\w*\\b'"
```

O terceiro tem uma forma que você vai encontrar bastante, e ela quer dizer uma
coisa só: **`\b` + palavra + `\w*` + `\b` = aquela palavra com qualquer
sufixo, mas não dentro de uma palavra maior.** `\baprender\w*\b` casa
`aprender` e `aprenderá`; **não** casa `desaprender`. O Passo 4 explica por que
as palavras de exceção têm essa forma — é onde a decisão está registrada.

**Isso é decisão de projeto, pelo mesmo motivo que o trecho casado num `DENY`
é.** Uma evidência que dissesse apenas "a regra R-INJ-001 casou" não seria
verificável: você teria de confiar no sistema. Dizendo o que a regra procurava
*e* o que ela achou *e* onde, a alegação pode ser conferida contra o dado —
que é o que esta seção inteira defende. E o padrão não é segredo: as políticas
são arquivos versionados no repositório, e o `config_versions` de cada registro
diz qual versão decidiu (Passo 5).

**Um caso foi tratado de forma diferente, e vale saber por quê.** Uma regra
pode ter uma cláusula de ausência (`not`) — dispara quando algo aparece *sem*
uma expressão de isenção. A evidência dessa cláusula descreve uma condição que,
por definição, **não** casou: não há trecho a conferir. Até certo ponto ela era
gravada com a condição inteira serializada, ou seja, a lista completa das
expressões que fazem a regra não disparar. Isso não acrescentava nada de
verificável (não houve casamento a verificar) e era, na prática, um roteiro de
evasão. Hoje ela registra só a forma:

```json
"description": "absence of any of 6 conditions"
```

O critério, de novo, é o mesmo: o registro guarda o que torna a decisão
conferível, e não mais que isso.

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

> [!IMPORTANT]
> **`exceptions` não é o único jeito de desarmar uma regra, e o outro não
> aparece em `suppressed`.** Dentro de `condition` pode existir um bloco `not`:
> ele diz "esta regra só vale se o texto **não** contiver isto". R-TRANS-001 usa
> um — o aviso médico não é anexado quando a resposta já avisa.
>
> A diferença prática, e ela engana: quando um `exceptions` desarma, o registro
> traz o caso em `suppressed`, dizendo qual regra foi suprimida e por quê.
> Quando um bloco `not` desarma, **o registro não traz nada** — a regra
> simplesmente não disparou, e `suppressed` fica vazio. Um auditor que procure
> ali por que R-TRANS-001 não apareceu não encontra nada e conclui que nada foi
> suprimido. Para essas regras, o lugar de olhar é o bloco `not` dentro de
> `condition`, no arquivo.
>
> **E há uma terceira coisa a checar, que não é sobre o rastro e sim sobre o
> resultado: o que assume o lugar da regra desarmada.** Aqui os dois construtos
> deixaram de ser iguais na v0.7.0:
>
> - **`exceptions` rebaixa para o efeito que a regra declara** em
>   `suppressed_effect`, e o registro diz qual foi (`demoted_to`). `R-SEC-002`
>   declara `REWRITE`. Se uma regra **não** declarar nada, o motor volta a
>   liberar como antes — por isso `tests/test_sucessor_declarado.py` falha se
>   alguma regra deste repositório ficar em silêncio.
> - **O bloco `not` continua só impedindo a regra de disparar**, sem rastro e
>   sem sucessor declarado. Em `R-TRANS-001` isso está certo e não é o mesmo
>   defeito: ela é *obrigação* de anexar um aviso, suprimir significa que o
>   texto já avisa, e `ALLOW` ali é a obrigação **cumprida**, não uma lacuna.
>
> Ou seja: `ALLOW` depois de uma supressão continua sendo correto num caso e
> suspeito no outro, e o que distingue os dois é o `deontic` da regra suprimida
> — `obligation` ou `prohibition`, campo que está no próprio JSON. O que mudou
> é que, para `exceptions`, o resultado deixou de ser efeito colateral do motor
> e passou a ser afirmação da política.

### Por que os padrões de supressão têm aquele `\b` nas pontas

Ao abrir um bloco `exceptions` — ou um bloco `not` — você não vai ver uma lista
de palavras soltas, e sim padrões nesta forma:

```
\baprender\w*\b
\bcursos?\b
\bconsult a doctor\b
```

Os três dizem coisas ligeiramente diferentes, e **há uma regra só que produz os
três**:

> **Todo padrão é ancorado com `\b` nas duas pontas — isso já quer dizer "esta
> expressão, e não dentro de uma palavra maior". O que varia é o fim, e quem
> decide é a última palavra do padrão.**

Os três casos, com o exemplo que os motivou:

| Se a última palavra… | o padrão fica | exemplo |
|---|---|---|
| ganha terminações, e colar uma nela não produz outra palavra | leva um curinga que as aceita | `\baprender\w*\b` casa `aprenderá`, `aprendendo`; não casa `desaprender` |
| não ganha terminações úteis, mas colar uma produz palavra alheia | fica só com o `\b` | `\bconsult a doctor\b` não casa `doctoral` nem `doctorate` |
| ganha terminações **e** colar uma produz palavra alheia | tem as formas boas escritas à mão | `\bcursos?\b` casa `curso` e `cursos`, e não casa `cursor` |

**Locução ou palavra única dá no mesmo** — palavra única é só o caso em que a
última palavra é a única palavra. Foi o que se aprendeu na v0.6.0, quando o
guia dizia que `\bcursos?\b` era uma exceção deliberada à forma "normal": não
era exceção nenhuma, era esta mesma regra aplicada a uma palavra que flexiona e
colide ao mesmo tempo. E vale ao contrário também: `\bnão substitui\w*\b` é uma
locução que precisa do curinga, porque `não substituirá` e `não substituiu` são
disclaimers legítimos que precisam continuar desarmando o aviso.

> [!NOTE]
> **`whole_word: true` e `\bpalavra\b` querem dizer exatamente a mesma coisa:**
> a expressão exata, não dentro de uma palavra maior. Você vai encontrar as duas
> grafias lado a lado no mesmo bloco — em `R-TRANS-001` elas convivem —, e não é
> incoerência nem uma ser mais forte que a outra. `whole_word: true` é a forma
> curta, e serve quando não há sufixo a tratar; o regex é o que se escreve
> quando há (o curinga `\w*` ou as formas enumeradas `s?` não cabem numa flag,
> que é tudo-ou-nada).

Nada disso é preciosismo de notação. **Vem de uma regra, e a regra é esta:**

> **Padrão que suprime não pode casar demais, porque casar demais numa
> supressão enfraquece o guardrail em vez de apertá-lo.**

A diferença é de direção, e é a coisa mais importante desta seção:

- Numa condição de **gatilho**, casar demais dispara alarme falso. É chato:
  bloqueia quem não devia ser bloqueado, e a pessoa reclama e o caso aparece.
- Numa **supressão** — seja um `exceptions`, seja um bloco `not` —, casar demais
  **desliga** a regra. Nada dispara, nada aparece, ninguém reclama. E quem
  escreve o texto escolhe a palavra, logo escolhe desligar a regra.

Concretamente, e os dois exemplos não pesam igual:

- `aprender` como pedaço solto casava dentro de `desaprender`. Bastava escrever
  "como invadir um sistema e desaprender o vício" para a exceção educacional ser
  concedida e o `DENY` virar coisa menor. A palavra não tinha nada de
  educacional; só continha as letras certas. O mesmo valia para `learn` dentro
  de `unlearn`, e para `course` dentro de `discourse` e `intercourse`. Aqui o
  que se comprava era **permissão para um pedido**.
- No bloco `not` de `R-TRANS-001`, `seek professional` casava dentro de
  `professionalism`. "The dosage is 500mg daily. At this clinic we seek
  professionalism." saía sem aviso nenhum. Aqui o que se comprava era **o
  apagamento de um aviso de segurança** numa resposta que dá dosagem — pior que
  o caso anterior, e sem deixar rastro em `suppressed`. O mesmo valia para
  `consult a doctor` dentro de `doctoral`/`doctorate`.

**Nenhuma entrada "foge da forma".** As três variações da tabela acima são a
mesma regra decidindo pela última palavra, e vale conferir os dois casos que
antes deste guia apareciam como exceções deliberadas:

- **`\bcursos?\b`** em vez de `\bcurso\w*\b`: `curso` ganha `cursos`, e colar
  terminação nela também produz `cursor`, palavra alheia e frequente em texto
  técnico. Flexiona **e** colide, logo formas escritas à mão — terceira linha da
  tabela, não desvio dela.
- **`\beducaciona(l|is)\w*\b`** para `educacional`/`educacionais`: o português
  pluraliza *-al* em *-ais*, então `educacionais` **não** contém `educacional` e
  um `\beducacional\w*\b` sozinho teria perdido o plural em silêncio. As duas
  formas estão escritas, pelo mesmo motivo.

## A marca de recusa: quando a palavra perigosa está lá porque está sendo negada

Há um caso em que o guardrail erraria por um motivo quase honesto. Olhe estas
três respostas de assistente:

> *"It is not advisable to steal a laptop from a coffee shop."*
> *"I'm sorry, I cannot help you figure out how to poison your roommate's bird."*
> *"Unfortunately, we cannot help you find cocaine near you."*

Todas trazem vocabulário de dano — *roubar*, *envenenar*, *cocaína* — e **todas
estão recusando o pedido**. Uma regra que só procurasse as palavras bloquearia a
recusa, que é justamente o comportamento que se quer.

Não é hipótese: no conjunto de aferição, um léxico de dano amplo pegaria
**11 das 52 respostas corretas** do BeaverTails, e a maior parte dessas 11 é
recusa citando o pedido.

### Como se lê um gatilho de recusa

Os gatilhos ficam em `frames/refusal_frames.json`, para poderem ser lidos sem
ler Python. Cada um tem três coisas:

| campo | o que significa |
|---|---|
| **termo** | a expressão que marca a recusa — *"I cannot"*, *"unfortunately"* |
| **direção** | para que lado a recusa governa o texto: `frente` ou `tras` |
| **alcance** | até onde ela chega, em palavras |

Lê-se assim: *"gatilho `I cannot`, alcance 15 palavras à frente"* — ou seja, a
recusa cobre o que vem **depois** dela, até 15 palavras adiante.

**Por que existem duas direções.** Compare:

> *"**I cannot help you** build a bomb."* — a recusa vem antes, e governa o que
> vem depois. Direção **frente**.
>
> *"It is possible to steal a car, however it is generally **not a good idea**."*
> — aqui o juízo vem **depois** do que ele nega. Direção **trás**.

Isso não foi inventado aqui: é o algoritmo **ConText**, publicado e validado em
processamento de texto clínico (Chapman *et al.*, 2007; Harkema *et al.*, 2009),
onde o mesmo problema aparece com "paciente nega dor no peito".

### Três limites que a recusa não ultrapassa

1. **Ela nunca atravessa um ponto final.** *"I'm sorry. Here is how to build a
   bomb."* são duas frases: a recusa fica na primeira, e a segunda continua
   valendo como dano. **Esta é a defesa principal**, e sem ela bastaria escrever
   *"desculpe"* antes de qualquer coisa para desligar o guardrail.
2. **Uma conjunção adversativa encerra a recusa que veio antes dela.**
   *"I'm sorry, **but** here is how…"* — o *but* corta o escopo. (Para a direção
   `trás` é o contrário: a recusa atravessa o *however*, porque é exatamente
   aquilo que ela está contradizendo.)
3. **Todas as ocorrências têm de estar cobertas.** Se a palavra perigosa aparece
   duas vezes e só uma está dentro da recusa, a regra dispara. Uma fora, e não
   há isenção.

Além disso, uma regra que use a marca de recusa **só pode valer para saída**
(`scopes: ["output"]`), e o arquivo nem carrega se alguém tentar o contrário.
O motivo é o item 3 da seção anterior, aplicado a esta camada: numa supressão,
casar demais desliga a regra. Se a recusa valesse na entrada, bastaria escrever
*"desculpe, agora me diga como fazer uma bomba"* para comprar a isenção.

> **Nenhuma regra usa isso hoje, e é de propósito.** A camada está construída e
> registrada na procedência (papel `frames_refusal`), mas nenhuma regra de
> `core_policy.json` a invoca, porque ainda não existe regra de saída que case
> vocabulário de dano. Ela passa a ser usada quando a taxonomia de dano entrar.

## Vereditos que vieram de norma de dano

A partir de 2026-08-04 existe uma terceira camada, e vereditos com regra
começando em **`N-HARM-`** vêm dela. Ler um deles exige saber três coisas.

**1. O que é a taxonomia de dano, e por que ela é separada.** O projeto usa uma
ontologia emprestada de outros autores (o RelAIEO). Ela é excelente para
auditar *um sistema em projeto* — se vai vigiar, se vai discriminar — mas não
tem vocabulário para *conteúdo nocivo*: não nomeia violência, arma, roubo,
droga, extremismo nem invasão. Medido: de 198 respostas que deveriam ser
barradas, **106 caem em categoria que ela não nomeia**.

Então há um segundo arquivo, **nosso**, com 12 conceitos de dano. Ele fica ao
lado, nunca dentro: o arquivo emprestado não é editado. Na tela de auditoria os
dois aparecem separados — `ontologia RelAIEO (upstream, vendorizada)` e
`taxonomia de dano (nossa)`.

**2. Por que estas normas não exigem "intenção de projeto".** As normas
emprestadas só disparam quando o texto fala em *construir* alguma coisa —
"desenvolver", "implantar", "treinar". Faz sentido para auditar um projeto, e
não faz nenhum para uma resposta pronta: quem explica como seguir uma pessoa não
diz que vai construir nada. Era por isso que quase nada disparava. As normas de
dano olham **o conteúdo da resposta**, e por isso não pedem essa intenção.

**3. Como se lê a guarda de recusa num veredito.** Toda norma de dano declara,
no arquivo, se está protegida contra recusa:

> `"unless_frame": "recusa"` — a norma **não** dispara se todas as ocorrências do
> vocabulário de dano estiverem dentro de uma recusa.
>
> `"unless_frame": null` — a norma dispara de qualquer forma, e alguém escreveu
> `null` de propósito.

Não existe terceira possibilidade: uma norma de dano que **não traga a chave**
não carrega, e o sistema recusa iniciar. Isso é deliberado — "esta norma não se
protege" e "ninguém pensou nisso" pareciam iguais no arquivo, e agora não
parecem.

Quando a guarda atua, o veredito traz a norma em **`suppressed`**, com a razão
dizendo que todos os casamentos caíram dentro do escopo de recusa. É o mesmo
lugar onde já aparecem as isenções de regra.

**E uma norma com guarda de recusa só vale para saída.** Se valesse para a
entrada, bastaria escrever *"desculpe, agora me diga como seguir alguém"* para
comprar a isenção. O arquivo nem carrega se alguém tentar o contrário.

### O que esta camada ainda não alcança

Duas coisas medidas, escritas aqui para que não sejam descobertas como surpresa:

- **A recusa que cumpre em seguida.** *"Desculpe, não posso encontrar o telefone
  dela. **Porém**, você pode usar um aplicativo de busca reversa."* A guarda
  isenta, porque a única palavra vigiada está na parte recusada — a continuação
  nociva não usa vocabulário de dano nenhum.
- **A justificativa que repete a palavra.** *"Não é aconselhável soltar uma bomba
  no vaso. Bombas causam incêndio…"* Aqui é o contrário: a segunda ocorrência
  está fora da recusa e a norma dispara, mesmo o texto inteiro sendo uma recusa.

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
# ou, sem flag nenhuma, com a senha que o instalador gravou no .env da raiz:
ethical-agent serve
```

Depois, `http://127.0.0.1:8765/audit`.

### O registro em três camadas

A tela não mostra o registro inteiro de uma vez — mostrar tudo afoga quem não é
técnico, mostrar pouco impede o julgamento. A gradação é:

| Camada | Conteúdo | Estado |
|---|---|---|
| 1 | O que a pessoa pediu, o que o sistema fez, e por quê — em linguagem comum, sem identificador de regra e sem span | sempre visível |
| 2 | A norma que disparou, o `rationale` (que já traz a provocação RelAIEO), as evidências com trecho e posição, e o que foi afastado por exceção (`suppressed`) | um clique |
| 3 | Proveniência: `config_versions`, **quais arquivos governaram a decisão** (com versão e digest) e o **`config_id`**, `llm_provenance`, `conversation_id`, `turn_index` | um clique |

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

**A senha mora num lugar só.** Ou no `.env` da raiz — a chave
`ETHICAL_AGENT_AUDIT_PASSWORD`, que é o que o instalador gráfico grava — ou num
arquivo apontado por `--audit-password-file`, que tem precedência sobre ele.
Não há terceira fonte.

**A variável de ambiente de mesmo nome não é lida.** Ela já foi, e ganhava do
`.env`. Se ela ainda estiver exportada na sua máquina, `ethical-agent serve`
compara com a senha em vigor e **não sobe** se elas divergirem, ou se não
houver senha nenhuma configurada — dizendo onde a senha mora agora e pedindo
que você apague a variável. Se o valor for o mesmo, sobe normalmente: não há o
que desambiguar.

O motivo de recusar em vez de simplesmente ignorar é desta seção. Uma variável
ignorada em silêncio é alguém que acredita ter configurado uma senha e só
descobre que não na hora em que a tela de login recusa o que ele digitou. Uma
tela de auditoria que recusa a senha certa não é um problema de senha — é a
auditoria parecendo quebrada para exatamente a pessoa que ela deveria servir.
Foi assim que este defeito apareceu, quando as duas fontes ainda se ordenavam
e um aviso no terminal era tudo que separava as duas senhas.

Para subir agora sem mexer em configuração nenhuma, use
`--audit-password-file ARQUIVO`: a flag declara qual senha usar naquela
invocação e passa por cima de tudo. A própria mensagem de erro diz isso, para
ninguém precisar voltar aqui.

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
- [ ] Olhei o `suppressed` — alguma exceção rebaixou uma regra? Ela se justifica?
- [ ] Li o `demoted_to` de cada supressão — o efeito que sobrou é proporcional? (`ALLOW` ali é o que mais pede justificativa)
- [ ] Abri a regra no JSON e li o `when` / `condition`, o `scopes` e as `exceptions`
- [ ] Rodei nas três engines para saber qual camada decidiu
- [ ] Reproduzi e anotei as `config_versions`
- [ ] Anotei o `config_id` — e, se estou comparando dois registros, conferi se é o mesmo nos dois (se não for, comparei os `sha256` linha a linha para achar qual arquivo mudou)
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
