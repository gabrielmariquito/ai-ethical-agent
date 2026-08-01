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
(`ethical_agent`) ou pela interface gráfica (`gui_app.py`) — grava um registro
JSON em `logs/audit.jsonl`. O objetivo é permitir auditar o **uso real** do
sistema depois do fato: cada registro traz, além do resultado, a versão exata
da política e da ontologia (`config_versions`) que produziu aquele veredito.

### 1.1 Onde ela fica

- Caminho padrão: `logs/audit.jsonl`, um objeto JSON por linha.
- Pode ser trocado com `--audit-log CAMINHO` (CLI) ou pelo campo `--audit-log`
  ao lado do checkbox "Enable audit log" no painel **Engine settings** da GUI.
- O arquivo e o diretório `logs/` são criados na primeira gravação. O
  instalador (`wizard_gui.py`) já cria `logs/` ao final, como conveniência.
- `eval` **nunca** grava: roda centenas de casos sintéticos direto contra a
  engine, e gravá-los poluiria a trilha com o que não é uso real.

### 1.2 Como desativar

Gravar o texto de entrada completo — que pode incluir dado pessoal — é uma
postura deliberada, não um acidente. Três formas independentes desligam:

- `--no-audit` (CLI), em qualquer subcomando;
- `ETHICAL_AGENT_NO_AUDIT=1` (qualquer processo, CLI ou GUI);
- desmarcar "Enable audit log" no painel **Engine settings** da GUI.

Na primeira gravação bem-sucedida de cada processo é impresso um aviso de uma
linha em `stderr` (e, na GUI, também no painel de resultado, já que uma janela
pode não ter console visível):

```
[audit] writing to logs/audit.jsonl (disable with --no-audit or ETHICAL_AGENT_NO_AUDIT=1; see AUDIT_GUIDE.pt-BR.md)
```

Uma falha ao gravar — permissão negada, caminho inválido — **nunca derruba o
comando nem muda o veredito**. É reportada como aviso e a execução segue:

```
[audit] could not write audit record to naodá (IsADirectoryError: ...); continuing without logging this event
```

> [!CAUTION]
> O registro guarda o texto de entrada **completo**. Trate `logs/audit.jsonl`
> como arquivo sensível.

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
python -m ethical_agent --no-audit check "We are building a tool to detect and avoid bias in our hiring model."
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
  python -m ethical_agent --no-audit --engine $e check "SEU TEXTO" | sed -n 1p
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
  python -m ethical_agent --no-audit check --json "Deploy a hiring model that reproduces bias against women." \
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
python -m ethical_agent --no-audit eval
python -m ethical_agent --no-audit eval --dataset eval/dataset_huggingface_injections.json
python -m ethical_agent --no-audit eval --dataset eval/dataset_beavertails.json
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

## O que **não** dá para auditar

| Limite | Consequência |
|--------|--------------|
| Conteúdo bloqueado no `stage=output` (via `process`/`demo`, ou `check --stage output`) | É descartado antes de chegar ao log. Ver `tests/test_agent.py::test_denied_output_is_never_retained` e o equivalente de CLI em `tests/test_main.py::test_check_output_stage_denied_content_not_retained` |
| Casos de `eval` | `ethical_agent eval` roda os casos sintéticos direto contra a engine e nunca grava no audit log, por desenho |
| **`ALLOW` por falta de regra ≠ `ALLOW` por julgamento** | Os dois aparecem como `matches: []`. Com 12 entradas de política, a maior parte dos `ALLOW` é do primeiro tipo. Ausência de bloqueio raramente significa "foi julgado seguro" |
| 7 das 9 regras têm `scopes: ["input"]` | Uma resposta nociva gerada pelo modelo passa mesmo usando o vocabulário exato de uma regra. É lacuna estrutural, não lexical |
| O léxico cobre 8 dos 154 conceitos | A maior parte da ontologia está carregada mas inerte. `hate_speech` tem termos e nenhuma norma o referencia — ativá-lo não faz nada |
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
