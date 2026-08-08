# ai-ethical-guardrail

**Verificação simbólica e auditável de princípios éticos em Foundation Models**

Projeto Final de Programação (INF2102), Departamento de Informática, PUC-Rio
Autor Gabriel Mariquito

---

## Breve Descrição

**A principal função do programa.** O programa é um guardrail simbólico e auditável para Foundation Models. Ele avalia cada entrada antes que ela chegue ao modelo, e cada resposta antes que ela seja entregue. A verificação tem duas camadas, uma que opera sobre o texto e outra que opera sobre conceitos, e as duas produzem vereditos independentes. Vence o mais restritivo.

O julgamento normativo fica nas camadas simbólicas, e ao modelo resta gerar conteúdo. Como o critério não mora dentro de um sistema estocástico, alguém pode traçar, justificar, contestar e calibrar cada decisão.

```
entrada ──► [ regras + conceitos ] ──► modelo ──► [ regras + conceitos ] ──► resposta
                    │                                      │
                    ▼                                      ▼
              veredito + evidências                  veredito + evidências
                    └────────── trilha de auditoria (JSONL) ──────────┘
```

**Funções específicas que o programa oferece.**

- **Suporte a auditoria.** Uma interface apresenta, para cada decisão, a norma que decidiu com seu princípio e justificativa, o trecho de texto que a ativou, o que foi afastado por exceção, e sob qual configuração a decisão aconteceu. O registro bruto fica disponível junto.
- **Escolha entre três motores intercambiáveis.** Só as regras sobre texto, só os conceitos, ou os dois. Isso permite medir quanto cada camada contribui e diagnosticar de onde veio uma decisão.
- **Trilha em JSONL.** Uma linha por processamento, com o princípio, a norma e a configuração que governou cada decisão. Serve para agregar decisões tomadas sob as mesmas regras e responder quantas vezes cada princípio foi violado ou quais normas mais disparam.
- **Registro da sessão de auditoria.** O programa registra quais registros o auditor abriu, em que ordem e se já os tinha visto antes, em que ordem ele expandiu as camadas de detalhe, o tempo de parede e o tempo visível de cada registro, os filtros aplicados, as marcações de discordância e as tentativas de entrada.
- **Avaliação de texto isolado.** Verificar como o guardrail reage a um trecho, de entrada ou de saída, sem chamar nenhum modelo. O código de saída indica se houve intervenção, o que permite usar o comando dentro de outros scripts.
- **Avaliação contra datasets.** Medir o desempenho contra conjuntos rotulados, com erro-padrão para distinguir ganho real de flutuação, e metade dos casos reservada para que o número não seja inflado. As divergências saem listadas uma a uma.
- **Demonstração offline.** Ver o pipeline inteiro funcionando sem instalar modelo nenhum, com prompts fixos e respostas simuladas que percorrem uma liberação, um bloqueio e uma reescrita.
- **Conversa.** Falar com um modelo real ou simulado pela tela web, com histórico e, a cada intervenção, uma faixa que diz o que o guardrail fez, em que estágio e por qual regra.
- **Portabilidade.** O núcleo é importável e não tem dependência externa, o que permite acrescentar a verificação a outro sistema existente.
- **Critério editável sem código.** O critério ético vive em arquivos versionados, que o programa aceita por parâmetro junto com a escolha do motor.

**Usuários primordialmente contemplados.** O primeiro público são pesquisadores de Interação Humano-IA que precisam de um guardrail que produza registros das decisões tomadas, para estudar como pessoas os leem. É para eles que existem a divisão tune/holdout, o registro da sessão de auditoria e a instrumentação de medição.

O segundo público são auditores de ética, conformidade ou governança em sistemas de IA sem formação técnica em computação, que precisam julgar se uma decisão do modelo foi adequada às expectativas da organização. Para eles, o programa oferece uma tela de auditoria em três camadas de profundidade, que explica cada decisão em linguagem comum e apresenta a proveniência na própria interface, sem exigir que o auditor abra arquivos ou leia código.

**A natureza do programa.** É uma prova de conceito funcional e uma ferramenta utilitária, correspondente aos itens iniciais do roteiro de pesquisa de um projeto de mestrado sobre como embutir princípios éticos em agentes baseados em Foundation Models. O núcleo é estável e testado, mas segue em desenvolvimento pelo autor.

**Ressalvas.** No momento o guardrail alcança apenas Foundation Models, e a extensão a agentes fica como trabalho futuro. A cobertura normativa, o suporte ao português e algumas capacidades do motor permanecem incompletos. Os cenários negativos abaixo demonstram as duas limitações mais consequentes. As normas reconhecem coocorrência de conceitos sem distinguir polaridade, e a ativação depende de termos literais, de modo que o programa não alcança uma paráfrase fora do léxico.

---

## Visão de Projeto

### Cenário Positivo 1 (i.e. cenário que dá certo)

Marina coordena o comitê de ética de uma seguradora que acaba de ligar um assistente interno para a equipe de atendimento. Para iniciar a revisão, ela entra na tela de auditoria com a sua senha e filtra a lista pelas conversas da semana, descendo pelos distintivos de gravidade até parar num vermelho. Marina expande a segunda camada do registro e vê a regra que decidiu, o princípio que a justifica, e o trecho exato do pedido que a acionou, com a posição no texto. Ela discorda da decisão, porque acredita que um bloqueio não seria a resposta mais apropriada. Clica em **"Isso deveria ser diferente"**, escreve o motivo no campo aberto e registra. O programa guarda a objeção junto com a decisão e a regra que ela contesta, e também na própria sessão de auditoria. Depois, quem responde pela política lê as objeções de Marina no arquivo de marcações e decide se altera as regras.

> Este cenário evoca a função central do programa para o auditor. O programa não existe para bloquear, existe para tornar o bloqueio inspecionável. Repare que a objeção não altera nada automaticamente, porque a edição das regras é manual, e o texto na tela diz isso. O que o programa garante é que a discordância fique registrada, ancorada à decisão e à norma que a motivou.

### Cenário Positivo 2

Na mesma seguradora, a equipe de atendimento usa o assistente interno para consultar e resumir informações de beneficiários. Uma atendente pede o resumo do histórico de um paciente para preparar uma ligação. O modelo responde normalmente, mas inclui na resposta o CPF e o telefone que constavam do cadastro, que são informações confidenciais. O guardrail detecta os dados sensíveis, redata os dois, e entrega o restante da resposta. A atendente recebe o histórico completo e faz a ligação, respeitando a privacidade do beneficiário.

Durante a revisão desse caso, Marina vê no registro qual regra decidiu, o princípio que a justifica, e as posições exatas de onde o programa removeu os dados. Os valores redigidos, porém, ficam ocultos até para ela.

> Este cenário evoca a decisão de reescrita, que é a única que modifica o texto e a única que preserva o restante. Ele evoca também uma escolha deliberada. A redação apaga o valor de toda parte, inclusive da trilha. O registro guarda a posição e a descrição do casamento, mas não o dado, porque o sistema não abre exceção para si mesmo.

### Cenário Negativo 1 (i.e. cenário que expõe uma limitação conhecida e esperada do programa)

Renata redige a política de contratação da empresa e pede ajuda ao assistente com um trecho, *"We should avoid age bias when designing the hiring funnel"*. A requisição volta bloqueada por ferir o princípio de equidade. As provas são as palavras *bias* e *designing*, porque a norma exige o par viés mais construção para disparar, e a frase tem os dois. Só que a proposta de Renata é justamente *evitar* o viés ao projetar, e o guardrail não distingue falar sobre viés de construir com viés. Renata reescreve a frase até passar e, quando tira a palavra *designing*, a mensagem passa. Ela aprendeu a contornar a norma, e na próxima vez que o guardrail a bloquear com razão, ela fará o mesmo.

> As normas descrevem coocorrência de conceitos, sem polaridade. Uma norma só sabe que dois conceitos apareceram juntos, e não diferencia intenção. A consequência mais séria não é o falso positivo em si, e sim o que ele ensina. Um usuário que aprende a contornar uma norma legítima leva esse aprendizado para os casos em que a norma estava certa.

### Cenário Negativo 2

Numa consultoria de tecnologia, um gerente pede ao assistente interno que o ajude a especificar uma ferramenta para espionar seus funcionários. Escreve *"criar um mecanismo que monitore os funcionários da empresa"*, e o guardrail bloqueia o pedido. A camada de conceitos reconheceu vigilância e a intenção de construir, e a norma escrita sobre esse casamento negou a requisição. Ele reformula para *"crie um sistema que vigie os funcionários da empresa"* e a mensagem passa. O modelo responde, e a conversa segue normalmente.

> Semanticamente é o mesmo pedido, mas há diferença lexical. Uma expressão do vocabulário em inglês alcançou *monitore*, por coincidência de radical, enquanto *vigie* não está registrado, porque a lista de conceitos guarda apenas *vigiar* e *vigilância*. O programa registra o turno como liberado. Este é o limite esperado de um verificador simbólico, que decide só sobre o que alguém escreveu de antemão e não improvisa julgamento. Estender a cobertura é ampliar o léxico por um arquivo de configuração, sem tocar em código.

---

## Documentação Técnica do Projeto

### Requisitos funcionais

| # | O sistema deve |
|---|---|
| RF1 | avaliar os estágios de entrada e de saída separadamente, aplicando a cada um as regras e normas pertinentes |
| RF2 | avaliar um conteúdo textual e produzir um veredito entre ALLOW, FLAG, REWRITE ou DENY, com as evidências que o motivaram e uma razão em texto |
| RF3 | avaliar primeiro as constraints rígidas, que sempre resultam em DENY e não admitem exceções |
| RF4 | aplicar regras deônticas associadas a princípios éticos, com efeitos graduados e exceções opcionais, incluindo reescrita por template e redação de dados pessoais por span |
| RF5 | resolver o conflito entre engines pela decisão mais restritiva, de modo que acrescentar um motor nunca reduza a intervenção |
| RF6 | intervir sem descartar a resposta, apagando identificadores pessoais ou substituindo o conteúdo por formulação declarada em template |
| RF7 | registrar trilha de auditoria completa em JSONL, com regras e normas disparadas, texto casado com offsets, caminhos de inferência e o que foi suprimido por exceção |
| RF8 | oferecer uma tela de auditoria com autenticação, que apresente cada decisão em camadas de profundidade crescente |
| RF9 | carregar políticas, ontologias e normas de arquivos externos, de modo que alguém possa editá-las, acrescentá-las ou removê-las sem alteração de código |
| RF10 | permitir que o auditor registre discordância de uma decisão, sem que isso altere a política, guardando a objeção junto ao registro que a motivou |
| RF11 | garantir que a falha de uma engine resulte sempre em negação, nunca em liberação |

### Requisitos não funcionais

| # | Qualidade | O sistema deve |
|---|---|---|
| RNF1 | Auditabilidade | explicar toda decisão a partir dos artefatos que a produziram |
| RNF2 | Usabilidade | apresentar o registro de decisão de modo compreensível para auditores sem conhecimento de computação |
| RNF3 | Confiabilidade | produzir um veredito de bloqueio diante de qualquer falha na avaliação, e nunca liberar conteúdo cuja verificação não tenha terminado |
| RNF4 | Determinismo | garantir que a mesma entrada, sob a mesma configuração, produza sempre o mesmo veredito |
| RNF5 | Manutenibilidade | permitir que alguém altere os critérios éticos por edição de arquivos, sem recompilação nem alteração de código |
| RNF6 | Privacidade | não reter o conteúdo bloqueado nem os dados redigidos em nenhum arquivo, incluindo a trilha de auditoria |
| RNF7 | Rastreabilidade | garantir que todo registro contenha a versão declarada e o digest de cada arquivo de configuração que o governou |
| RNF8 | Usabilidade | atender ao nível AA da WCAG 2.1 quanto ao contraste entre texto e fundo, nos dois temas |
| RNF9 | Portabilidade | depender, no núcleo, apenas da biblioteca padrão do Python 3.10 ou superior |
| RNF10 | Manutenibilidade | permitir que alguém acrescente novas engines, tipos de condição e camadas de verificação por contratos declarados, sem alterar o motor de composição |

### Arquitetura e organização do software

A arquitetura segue o padrão de multi-model guardrails (Liu et al., 2025). O `GuardedAgent` cerca o modelo e verifica o texto de entrada e o de saída, e essa verificação decide se a mensagem chega ao modelo e se a resposta chega ao usuário.

O contrato central é a interface `PolicyEngine`, cujo método `evaluate(ActionContext)` devolve um veredito. Quatro classes a implementam. A `RuleBasedEngine`, a `KnowledgeGraphEngine` e a `CompositeEngine` formam o guardrail. A `LLMJudgeEngine` é um protótipo experimental, que fica fora da composição e serve de linha de comparação na avaliação.

**O fluxo de uma verificação.** O sistema percorre o mesmo caminho duas vezes por turno, uma sobre a entrada da pessoa e outra sobre a resposta do modelo, e as regras que se aplicam mudam conforme o estágio. A `RuleBasedEngine` percorre primeiro as constraints, que são rígidas e não admitem exceção, e depois as regras da política. A `KnowledgeGraphEngine` avalia as normas sobre os conceitos que a ontologia ativou. Cada uma produz duas listas. A primeira guarda os casamentos, que são as regras que dispararam sobre aquele texto. A segunda guarda as supressões, que são as regras que dispararam mas uma exceção rebaixou.

As duas engines recebem o mesmo texto e trabalham de forma independente, e nenhuma consulta o resultado da outra. A `CompositeEngine` chama as duas e monta um veredito novo, no qual vence a decisão mais restritiva. Se uma engine levanta exceção, a exceção vira um DENY marcado como erro de sistema, e a outra roda mesmo assim.

**Os agregados de dados.** Três agregados organizam o sistema. A `Policy` reúne duas listas de `Rule` e avalia primeiro as constraints. A `Ontology` reúne `Concept`, `Lexicalization` e `Relation`, e sobre esse grafo ficam as `Norm`. O `Verdict` carrega a decisão, o estágio, o motor, o conteúdo reescrito quando houve, e duas listas. Os `RuleMatch` trazem identificador, princípio, deontologia, severidade, efeito, justificativa e a `Evidence` com o trecho literal e sua posição. Os `SuppressedMatch` trazem a regra suprimida, a razão, a evidência e o efeito que passou a valer.

**A camada de regras.** O motor lê uma política em JSON com 3 constraints e 9 regras. Cada regra monta a condição a partir de sete tipos combináveis, em três grupos. A `keyword` e a `regex` casam texto. A `any`, a `all` e a `not` compõem outras condições. A `concept` pergunta se um conceito da ontologia está ativo, com a inferência incluída, e a `refusal` desliga a regra quando o que a disparou cai dentro de uma recusa do modelo. As duas últimas estão implementadas, mas a política atual ainda não as usa.

**A camada de conceitos.** Um léxico de 54 expressões ancora trechos do texto em conceitos de duas taxonomias. A RelAIEO ([Arora & Sarkar, Audit4SG](https://ontology.audit4sg.org/)), vendorizada sem modificação, traz 154 conceitos, dos quais 8 têm ancoragem, e 6 normas operam sobre eles. Uma taxonomia de dano escrita para este trabalho traz 12 conceitos, todos ancorados, com 12 normas próprias, e se pendura na RelAIEO por cinco relações `is_a`. Somadas, são 167 conceitos e 18 normas. A ativação propaga pela hierarquia, do caso particular para o geral, o que faz um texto sobre vigilância dirigida acionar uma norma escrita sobre vigilância.

**A camada de frames.** Ela resolve um problema do estágio de saída, no qual uma resposta que recusa um pedido perigoso carrega o mesmo vocabulário da resposta que o cumpre. O mecanismo vem do algoritmo ConText. Gatilhos com direção e alcance em tokens marcam trechos como recusa, e nenhum trecho atravessa fronteira de sentença, porque senão bastaria escrever `"I'm sorry."` antes do conteúdo nocivo para desligar a norma. A guarda só isenta quando todos os casamentos caem dentro de um trecho de recusa.

**A trilha de auditoria.** Cada mensagem grava uma linha JSON. Ela identifica o evento com um UUID, um carimbo de tempo e o par conversa/turno, registra o estado, o motor que decidiu, a origem e a proveniência da configuração, e guarda o texto de entrada, os vereditos íntegros, a mensagem entregue e os textos reescritos.

A proveniência serve para saber qual configuração de fato governou cada decisão. Para cada arquivo de configuração usado naquela decisão, ela grava papel, versão declarada, caminho e sha256 do conteúdo, e sobre esse conjunto calcula um `config_id`. A versão declarada é a afirmação que o autor pode errar, e o digest é o que o programa de fato carregou. Dois registros com o mesmo `config_id` foram decididos sob configuração idêntica, arquivo por arquivo.

A escrita é obrigatória e não-fatal. O programa avisa, na primeira gravação de cada processo, onde a trilha vive, e se a escrita falhar, reporta o erro e continua sem registrar aquele evento. Perder a trilha nunca pode mudar um veredito.

**A interface de auditoria.** A tela pede senha e apresenta cada decisão em três camadas, mais o registro bruto. A camada 1 fala em linguagem comum e diz o que a pessoa pediu, o que o sistema fez e por quê. A camada 2 traz a norma e a prova, com cada regra disparada e cada evidência com o trecho casado e sua posição. A camada 3 traz a proveniência, e diz qual motor decidiu, quais arquivos governaram a decisão, o `config_id` e qual modelo respondeu.

Duas características percorrem a tela. A primeira, a tela sempre declara a ausência. Quando a resposta bloqueada não está no registro, ela diz que o sistema nunca guarda essa resposta. A segunda, o sistema também audita o auditor. Uma tarja que ninguém pode dispensar informa que a sessão está sendo registrada, e o auditor pode ler os próprios eventos, leitura que o sistema também registra.

**Configuração.** O critério ético vive fora do programa, em nove arquivos versionados, que são a política, as duas taxonomias em Turtle, os dois léxicos de ancoragem, os dois arquivos de normas e os gatilhos de frames.

A validação na carga é deliberadamente severa. Um princípio desconhecido, um efeito inválido, um conceito inexistente ou uma norma de dano sem guarda de frame declarada impedem o programa de iniciar, com uma mensagem que nomeia o item. É melhor não subir do que subir com uma regra que nunca vai disparar e ninguém vai notar.

### Modelo funcional do software

A engine pode chegar a quatro vereditos, que vão do mais permissivo ao mais restritivo. Quando várias regras disparam, ou vários motores opinam, vale a decisão mais restritiva.

| Veredito | O que faz | Quem pode declarar | Na avaliação |
|---|---|---|---|
| `ALLOW` | deixa passar intacto | ninguém, só como sucessor de supressão | não-intervenção |
| `FLAG` | deixa passar e anota para o auditor | qualquer regra ou norma | não-intervenção |
| `REWRITE` | altera o texto e segue | só a camada de regras | intervenção |
| `DENY` | bloqueia | regras, normas, constraints e falhas | intervenção |

O **ALLOW** é o ponto de partida, porque todo veredito começa nele enquanto nenhuma regra ou norma se aplica ao texto. Ele representa uma lista de casamentos vazia, e por isso nenhuma regra pode declarar ALLOW como efeito de disparo. Ele não responde a nada, ele é a ausência de qualquer resposta. Uma regra pode, no entanto, declarar ALLOW como efeito de supressão. Como decidir não intervir também é uma decisão, o sistema registra o turno mesmo assim.

O **FLAG** existe para o caso limiar, quando um texto não é inofensivo mas a severidade dele não justifica bloqueio. A mensagem segue intacta e a marca destina-se ao auditor. Na avaliação, o FLAG não conta como intervenção, e um caso que o sistema deveria detectar e recebe FLAG entra nas métricas como não-detectado.

O **REWRITE** é a única decisão que modifica o texto, e só a camada de regras pode declará-la, porque reescrever exige saber onde intervir. O campo `redact` apaga os trechos nas posições que o gatilho encontrou, e funde recortes sobrepostos. O `rewrite_template` substitui o texto, ou o envolve quando contém o marcador `{content}`. Se a reescrita veio de um `redact`, o sistema não guarda o texto original nem no registro nem na tela.

O **DENY** bloqueia o conteúdo por completo. Na entrada, o sistema nunca chega a consultar o modelo, e o histórico dos turnos seguintes omite o turno inteiro. Na saída, o modelo já gerou a resposta quando a política a reprova, e o sistema retém essa resposta sem guardá-la no resultado nem na trilha. A tela declara isso no lugar onde a resposta estaria.

Uma exceção não faz a regra desaparecer. Ela decai para o efeito que o campo `suppressed_effect` declara, e a entrada em `suppressed` sobrevive com a razão e o efeito sucessor, o que permite ao auditor distinguir um pedido liberado de um pedido apenas atenuado. A supressão tem três origens possíveis, que são as exceções de uma regra, os conceitos `unless` de uma norma, e a guarda de frame.

### Sobre o código

O programa é escrito em Python 3.10 ou superior e distribuído sob a GNU GPL v3 ou posterior. O núcleo usa apenas a biblioteca padrão. As dependências opcionais `ollama` e `python-dotenv`, agrupadas no extra `llm`, só entram para conectar um modelo real. Um segundo extra, `dev`, traz o ferramental de teste.

Três construções da linguagem sustentam os contratos. As dataclasses declaram todos os campos de um tipo em um só lugar. Os enums fecham as listas de opções, de modo que escrever qualquer coisa fora delas é erro detectado imediatamente, e são quatro decisões, quatro severidades e dois estágios. O vocabulário de oito princípios obedece ao mesmo fechamento, verificado no carregamento. As classes abstratas `Condition`, `PolicyEngine` e `LLMClient` definem o que uma condição, uma engine e um cliente de LLM precisam oferecer para serem aceitos. Os contratos públicos levam type hints, e os comentários em linha ficam reservados às decisões não óbvias.

O pacote `ethical_agent` se organiza em módulos de responsabilidade única, agrupados pelas camadas do sistema. Os tipos comuns ficam em `types.py`.

```
ethical_agent/
├── types.py         # Decision, Severity, Stage, ActionContext, Verdict, evidências
├── conditions.py    # árvore de condições e registro extensível
├── policy.py        # Rule, Policy, carregador e validação
├── engine.py        # PolicyEngine, RuleBasedEngine, CompositeEngine
├── frames.py        # camada de quadros de recusa (ConText)
├── ontology.py      # Concept, Lexicalization, Relation, Norm, ativação no grafo
├── relaieo.py       # leitor Turtle sem dependências, união das duas taxonomias
├── kg_engine.py     # KnowledgeGraphEngine
├── agent.py         # pipeline GuardedAgent
├── llm.py           # LLMClient, MockLLM, OllamaClient
├── audit.py         # trilha JSONL
├── provenance.py    # artefatos de configuração e config_id
├── llm_judge.py     # engine experimental, fora da composição
├── evaluate.py      # harness de avaliação e divisão das metades
├── demo.py          # prompts da demonstração offline
├── senha_auditoria.py
├── __main__.py      # CLI com check, process, demo, eval e serve
└── webui/           # interface web local e tela de auditoria

policies/            # a política, com constraints e regras
ontologies/          # RelAIEO vendorizada, taxonomia de dano, léxicos e normas
frames/              # gatilhos de recusa
eval/                # conjuntos rotulados
tests/               # suíte pytest
wizard_gui.py        # instalador gráfico
uninstall.py         # desinstalador
```

#### Controle de qualidade

O pytest automatiza o controle, e a suíte cobre as engines, a ontologia, o pipeline do agente e o carregamento e a validação das configurações, com testes de unidade por componente e testes de propriedade sobre o reticulado de decisões. Uma trava de baseline em `tests/test_eval.py` garante que a engine híbrida nunca fique pior que a de regras.

<!-- TODO: contagem de testes e tempo da execução de referência, preencher após a suíte fechar verde -->

#### Resultados da avaliação

São três conjuntos, com propósitos deliberadamente diferentes. O **conjunto curado** (72 casos) foi escrito pela mesma pessoa que escreveu as regras, e mede se o sistema é consistente com o critério que ele mesmo define, não se generaliza. Por isso o programa o reporta sempre inteiro e nunca o soma nem o promedia com os outros. O **BeaverTails** (220 casos, [PKU-Alignment](https://huggingface.co/datasets/PKU-Alignment/BeaverTails), CC BY-NC 4.0) e o **deepset/prompt-injections** (662 casos, [deepset](https://huggingface.co/datasets/deepset/prompt-injections), Apache 2.0) são externos, escritos por pessoas sem contato com este projeto.

**A divisão tune e holdout.** O programa divide os conjuntos externos ao meio antes de qualquer medição, porque ajustar o sistema e medi-lo se contaminam. Melhorar o guardrail exige olhar os erros dele, ver quais casos divergiram do rótulo, descobrir que a palavra que ativaria a regra falta no léxico, acrescentá-la e rodar de novo. Cada caso corrigido assim deixa de testar o sistema, porque ele passa a acertar aquele exemplo, não a generalizar a regra.

A metade **tune** absorve esse trabalho. O **holdout** fica fechado durante todo o ajuste, e é isso que dá valor ao número dele. Olhar o holdout para decidir uma correção o transforma em tune, sem volta. A divisão usa um hash do identificador de cada caso, não a posição na lista, então os mesmos casos caem sempre do mesmo lado, em qualquer máquina.

**Desempenho por conjunto e metade.** Compare recall entre as metades. Elas têm proporções diferentes de casos que devem ser bloqueados, e essa diferença desloca a acurácia e o F1.

| Conjunto | Metade | N | Prevalência | Recall regras | Recall híbrida | Δ |
|---|---|---|---|---|---|---|
| curado | inteiro | 72 | 0,681 | 0,714 | 0,980 | **+0,265** |
| BeaverTails | tune | 117 | 0,556 | 0,046 | 0,523 | **+0,477** |
| BeaverTails | holdout | 103 | 0,534 | 0,055 | 0,382 | **+0,327** |
| deepset | tune | 323 | 0,412 | 0,015 | 0,015 | **0,000** |
| deepset | holdout | 339 | 0,383 | 0,054 | 0,062 | **+0,008** |

**Qual camada decidiu.** A tabela registra, para cada caso avaliado pelo motor híbrido, qual das duas camadas produziu o veredito vencedor.

| Conjunto | Metade | Só regras | Só conceitos | Ambas | Total |
|---|---|---|---|---|---|
| curado | inteiro | 35 | 14 | 23 | 72 |
| BeaverTails | tune | 3 | 32 | 82 | 117 |
| BeaverTails | holdout | 2 | 25 | 76 | 103 |
| deepset | tune | 2 | 0 | 321 | 323 |
| deepset | holdout | 6 | 1 | 332 | 339 |

A coluna "ambas" reúne os casos em que as duas camadas chegaram à mesma decisão, incluindo os casos limpos, nos quais as duas devolveram ALLOW sem nenhum casamento. Os 653 casos do deepset são majoritariamente dessa natureza, e por isso o valor alto indica concordância em não intervir, não acordo sobre uma intervenção.

**O que os números dizem.** O ganho da camada de conceitos depende do domínio. No BeaverTails ela decide sozinha em 32 e 25 casos, e o recall sobe de 0,046 para 0,523. No deepset ela decide sozinha em 0 de 323 e 1 de 339, e o ganho desaparece. A camada que carrega o peso da decisão troca conforme o material avaliado, e a tabela de atribuição mede isso em vez de deixar inferir pela métrica.

A queda de tune para holdout no BeaverTails, de 0,523 para 0,382, mede generalização e não composição do conjunto, porque a métrica comparada é o recall. E o conjunto curado, com recall 0,980 contra 0,382 do holdout externo, é o argumento empírico para reportá-lo sempre em separado.

---

## Manual de Utilização para Usuários Contemplados

Este manual cobre os dois perfis contemplados, o auditor e o pesquisador, mais um terceiro caminho para quem escreve código próprio. Ele está organizado por **tarefa**, porque quase tudo que o sistema faz acontece tanto pela interface quanto pela linha de comando.

A interface tem cinco telas, nomeadas na barra de navegação, que são **Conversa**, **Avaliar texto**, **Demo**, **Eval** e **Auditoria**.

O núcleo não exige dependências além do Python 3.10 ou superior. O acesso a um modelo de linguagem real é opcional em todas as tarefas, e onde ele falta o sistema recorre ao `MockLLM`, que roda offline.

### Tarefa A. Instalar

```
Guia de Instruções:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Para [Tarefa A: INSTALAR] faça:
Passo 1: Execute o assistente de instalação.
         > py -3 wizard_gui.py
Passo 2: Percorra as páginas, confirmando cada uma.
Passo 3: Se quiser usar a tela Auditoria, preencha a senha quando o
         assistente pedir. Preenchida ali, a tela sobe habilitada sem
         precisar de nenhuma opção depois.
Passo 4: Ao terminar, o assistente prepara o ambiente Python do projeto
         (a pasta .venv), sobe o servidor e abre a interface no
         navegador sozinho.

>>> Esta tarefa se faz uma vez só. Para abrir a interface nas próximas
    vezes, veja a Tarefa B. Não rode o assistente de novo.

>>> O servidor escuta apenas em 127.0.0.1, o endereço da própria
    máquina. Não fica exposto na rede.

>>> A instalação não cria atalho. O que ela deixa pronto é o ambiente
    Python; abrir a interface depois é subir o servidor por ele.

Exceções ou potenciais problemas:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Se [o assistente terminar mas o navegador não abrir]
   {
   Então faça: abra http://127.0.0.1:8765 manualmente. O servidor já
               está no ar; o que falhou foi só a abertura automática.
   }

Se [você quiser encerrar o servidor que o assistente subiu]
   {
   Então faça: use o comando taskkill que o próprio assistente imprime,
               com o número do processo.
   É porque: o assistente sobe o servidor destacado de si mesmo, para
             que ele sobreviva ao fim da instalação. Não há janela de
             terminal para interromper com Ctrl+C.
   }

Se [você quiser desinstalar]
   {
   Então faça: > py -3 uninstall.py
   É porque: ele encerra o servidor antes de remover o ambiente. Remover
             com o servidor no ar deixaria arquivos presos e a remoção
             pela metade.
   }
```

### Tarefa B. Abrir a interface (com o programa já instalado)

```
Guia de Instruções:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Para [Tarefa B: ABRIR A INTERFACE] faça:
Passo 1: Abra o PowerShell e entre na pasta do projeto.
         > cd <pasta do projeto>
Passo 2: Suba o servidor com o Python do ambiente preparado na instalação.
         > .venv\Scripts\python.exe -m ethical_agent serve
Passo 3: Abra http://127.0.0.1:8765 no navegador.
Passo 4: Para parar, dê Ctrl+C na mesma janela do PowerShell.

>>> O passo 1 não é formalidade. A trilha de auditoria é gravada em
    logs\audit.jsonl relativo à pasta em que o comando roda: subir o
    servidor de outro lugar escreve a trilha em outro lugar. A senha da
    tela Auditoria não depende disso, porque é procurada sempre na raiz
    do projeto.

>>> Alternativa, se preferir ativar o ambiente antes:
         > .venv\Scripts\Activate.ps1
         > ethical-agent serve
    Mesmo resultado, comando mais curto.

>>> Para usar outra porta: serve --port 9000. Em qualquer porta, o
    servidor continua escutando só em 127.0.0.1.

>>> Fechar a aba do navegador não encerra o servidor. Ele é um processo
    à parte, e reabrir o endereço volta para a mesma sessão.

Exceções ou potenciais problemas:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Se [aparecer "a porta 8765 já está em uso"]
   {
   Então faça: leia a mensagem antes de agir. Ela distingue os dois
               casos, um servidor deste projeto já no ar ou outro
               programa ocupando a porta, e sugere --port 8766.
   É porque: se for um servidor deste projeto, basta abrir o navegador
             no endereço; não é preciso subir nada.
   }

Se [a interface abrir com uma configuração que você não reconhece]
   {
   É porque: o que você está vendo é um servidor antigo, de uma sessão
             anterior, que ficou no ar segurando a porta. Encerre-o e
             suba de novo, ou a tela continuará respondendo pela
             configuração velha.
   }

Se [a página abrir mas nenhuma ferramenta responder]
   {
   Então faça: confira no terminal se o servidor registrou erro ao
               carregar a política ou a ontologia.
   É porque: a interface é servida mesmo quando a configuração falha ao
             carregar; a falha aparece na primeira chamada, não na
             abertura.
   }
```

### Tarefa C. Checar um conteúdo e ler a explicação

```
Guia de Instruções:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Para [Tarefa C: CHECAR UM CONTEÚDO E LER A EXPLICAÇÃO] faça:

  Pela interface:
  Passo 1: Vá à tela Avaliar texto.
  Passo 2: Escreva ou cole o conteúdo a examinar e submeta.
  Passo 3: Leia o veredito e, abaixo dele, a explicação.

  Pela linha de comando:
  Passo 1: Execute o comando check com o texto entre aspas.
           $ python -m ethical_agent check "algum texto"
  Passo 2: Leia a decisão e a explicação com as evidências.

Passo comum: a explicação nomeia a regra ou norma que disparou, mostra o
             trecho exato do texto que a fez disparar, o caminho de
             inferência no grafo quando houver, e o que foi suprimido
             por exceção.

>>> Há três engines. A híbrida (padrão) combina regras e grafo; rule usa
    só regras; kg usa só o grafo. Rodar o mesmo texto em rule e em kg e
    comparar é o que isola de qual camada veio uma decisão.
         $ python -m ethical_agent --engine rule check "algum texto"
         $ python -m ethical_agent --engine kg   check "algum texto"
    Na interface, a engine é a que estiver escolhida no painel de
    Configuração.

Exceções ou potenciais problemas:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Se [você nunca vir um veredito FLAG]
   {
   É porque: FLAG só existe nas normas do grafo, e elas só são
             carregadas com as engines kg e híbrida. Com --engine rule,
             FLAG é inalcançável. Não é defeito, é o alcance daquela
             camada.
   }

Se [o conteúdo for considerado sensível, na linha de comando]
   {
   É porque: a saída traz a decisão e a explicação, e o código de saída
             é 2. Isso é esperado, não um erro. O código 2 sinaliza que
             o guardrail interveio.
   }

Se [o veredito parecer errado]
   {
   Então faça: confira o trecho casado antes de concluir. A explicação
               mostra exatamente o que o sistema leu; muitas divergências
               são de leitura, não de julgamento.
   }

Se [uma engine falhar internamente]
   {
   Então faça: verifique a configuração JSON carregada.
   É porque: a política fail-closed nega o conteúdo por segurança quando
             uma engine falha. A negação é a resposta correta a uma
             falha, não um julgamento sobre o conteúdo.
   }
```

### Tarefa D. Conversar com um modelo protegido pelo guardrail

```
Guia de Instruções:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Para [Tarefa D: CONVERSAR COM UM MODELO PROTEGIDO] faça:

  Pela interface:
  Passo 1: Vá à tela Conversa.
  Passo 2: Escreva a mensagem e envie.
  Passo 3: Leia a resposta e o status: aprovada, bloqueada ou reescrita.

  Pela linha de comando:
  Passo 1: Execute o comando process com o texto entre aspas.
           $ python -m ethical_agent process "Por que o céu é azul?"
  Passo 2: Leia o status e a resposta.

>>> O pipeline verifica duas vezes: a entrada, antes de chegar ao
    modelo, e a saída, antes de chegar a você. Uma entrada aprovada não
    garante uma saída aprovada.

>>> Opções da linha de comando:
    --model MODELO   escolhe o modelo Ollama
    --mock           ignora o Ollama, usa resposta fixa do MockLLM
    --verbose        imprime os vereditos de entrada e de saída
    --json           imprime o resultado como dado estruturado

>>> O modelo padrão é llama3.2:3b. Pode ser trocado de três formas, da
    mais específica à mais geral: a opção --model, a variável
    OLLAMA_MODEL no arquivo .env, ou o padrão embutido.

>>> Para usar um modelo Ollama de verdade, configure um .env na raiz:
    - Ollama Cloud: defina OLLAMA_API_KEY (chave em
      https://ollama.com/settings/keys); não precisa instalar nada.
    - Ollama local: instale por https://ollama.com/download, rode
      "ollama serve" e baixe o modelo escolhido.
    Em ambos os casos: $ pip install ollama python-dotenv

Exceções ou potenciais problemas:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Se [o Ollama não estiver configurado ou não responder]
   {
   É porque: o sistema tenta o modelo real primeiro e cai automaticamente
             para o MockLLM se ele falhar, avisando. Isso é esperado,
             não um erro.
   }

Se [a resposta vier reescrita e você quiser ver o original]
   {
   Então faça: na linha de comando, repita com --verbose. O veredito de
               saída nomeia o que foi reescrito e por qual regra.
   }
```

### Tarefa E. Rodar a demonstração

```
Guia de Instruções:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Para [Tarefa E: RODAR A DEMONSTRAÇÃO] faça:

  Pela interface:
  Passo 1: Vá à tela Demo.
  Passo 2: Clique em "Rodar demo".
  Passo 3: Acompanhe as etapas do pipeline, da entrada à resposta.

  Pela linha de comando:
  Passo 1: Execute o comando demo.
           $ python -m ethical_agent demo
  Passo 2: Acompanhe as mesmas etapas.

>>> A demonstração roda sempre com respostas simuladas, pelos dois
    caminhos. Nunca chama um modelo de verdade, e não há opção para
    isso: é o que a torna previsível e reproduzível.

>>> Ela existe para mostrar o pipeline inteiro num caso conhecido, e é
    o caminho mais curto para ver o que o sistema faz sem preparar nada.

>>> A demonstração é registrada na trilha de auditoria, no mesmo arquivo
    das decisões reais. Cada registro dela vem marcado com a origem
    "demo", que é como se distingue um do outro na leitura (Tarefa G).

Exceções ou potenciais problemas:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Se [você espera a resposta de um modelo real]
   {
   É porque: a demonstração é offline por desenho. Para um modelo real,
             veja a Tarefa D.
   }

Se [você não quiser a demonstração misturada às decisões reais]
   {
   Então faça: rode-a com o servidor subido de outra pasta, ou aponte a
               trilha para outro arquivo antes de rodar.
   É porque: os registros vão para a mesma trilha, marcados pela origem.
             A marca permite separá-los na leitura, mas não os mantém em
             arquivo à parte.
   }
```

### Tarefa F. Executar a avaliação

```
Guia de Instruções:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Para [Tarefa F: EXECUTAR A AVALIAÇÃO] faça:

  Pela interface:
  Passo 1: Vá à tela Eval.
  Passo 2: Escolha o dataset, a engine e a extensão do dataset.
  Passo 3: Execute e leia o relatório. Sai uma caixa por avaliação,
           titulada com o dataset, a engine e a metade.

  Pela linha de comando:
  Passo 1: Execute o comando eval (por padrão, a engine híbrida sobre o
           conjunto curado inteiro).
           $ python -m ethical_agent eval
  Passo 2: Para trocar a engine ou a metade, use --engine e --half.
           $ python -m ethical_agent --engine rule eval --half holdout

Passo comum: leia o bloco Divisão, que abre o relatório, ANTES das
             métricas. Ele diz qual conjunto foi avaliado, qual metade,
             quantos casos, e a proporção entre casos que deveriam ser
             bloqueados e casos que não deveriam.

>>> Por que o bloco Divisão vem primeiro: a acurácia depende da mistura
    do conjunto. Um conjunto com poucos casos que deveriam ser
    bloqueados produz acurácia alta mesmo num sistema que quase não
    bloqueia. Sem a proporção, o número engana.

>>> A extensão do dataset decide qual metade é avaliada:

    Inteiro   — o conjunto todo, sem separar ajuste de reporte.
    Tune      — a metade cujos erros se pode ler. Quando o sistema deixa
                passar um caso que deveria bloquear, é aqui que você vê
                qual foi, corrige o léxico ou a condição e roda de novo.
    Holdout   — a metade que se preserva sem olhar. Como o sistema nunca
                teve chance de ser moldado por esses casos, é este
                número que vale para o relatório.
    Separados — uma caixa para cada metade. A diferença entre elas mostra
                o quanto o sistema depende dos casos que já viu.

>>> Entre metades diferentes, compare recall. Elas têm proporções
    diferentes de casos que devem ser bloqueados, e isso desloca a
    acurácia e o F1. O recall não se desloca.

>>> O conjunto curado não é dividido. Ele foi escrito pelo autor das
    próprias regras, e é reportado sempre inteiro e separado.

>>> A avaliação nunca escreve na trilha de auditoria, por desenho.
    Rodar centenas de casos encheria a trilha de registros que não são
    decisões sobre conteúdo real de ninguém.

>>> Para levar os números para outro lugar, use --json na linha de
    comando. A tela hoje não exporta: o texto dela serve para copiar,
    não para somar.

Exceções ou potenciais problemas:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Se [você pedir uma metade do conjunto curado]
   {
   É porque: a tela e a linha de comando recusam, com o mesmo motivo
             escrito. Um número rotulado holdout que não é um holdout é
             pior que nenhum número.
   }

Se [comparar as três demorar]
   {
   É porque: roda o mesmo conjunto três vezes. Com "Tune e holdout,
             separados" junto, são seis avaliações. Prefira um dataset
             menor enquanto estiver explorando.
   }

Se [as métricas vierem diferentes das relatadas neste documento]
   {
   Então faça: compare o identificador de configuração impresso no
               relatório com o registrado aqui.
   É porque: o conjunto, a política ou a ontologia foram alterados, e o
             identificador permite verificar isso em vez de supor.
   }
```

### Tarefa G. Ler a trilha de auditoria

```
Guia de Instruções:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Para [Tarefa G: LER A TRILHA DE AUDITORIA] faça:
Passo 1: Vá à tela Auditoria.
Passo 2: Informe a senha, a mesma preenchida no assistente de instalação.
Passo 3: Percorra os registros. Cada um traz o conteúdo submetido, o
         veredito, as regras e normas disparadas, a origem do registro e
         o identificador da configuração vigente no momento da decisão.
Passo 4: Para conferir uma decisão antiga, compare o identificador de
         configuração do registro com o da configuração atual.

>>> A origem separa o que veio de uso real do que veio da demonstração.
    Registros marcados como "demo" são do caso roteirizado da Tarefa E.

>>> A senha separa papéis; ela não é medida de segurança. Quem tem
    acesso à máquina tem acesso ao arquivo da trilha.

>>> O identificador de configuração é o que torna um registro
    conferível: ele resume a política, a ontologia e as normas que
    valiam naquele momento. Dois registros com identificadores
    diferentes foram julgados por sistemas diferentes.

>>> A sessão dura 12 horas e não expira por inatividade. Fechar a aba
    não desloga. É deliberado: ninguém deveria ser desconectado no meio
    da leitura de um registro difícil.

Exceções ou potenciais problemas:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Se [a tela Auditoria não existir]
   {
   Então faça: leia o aviso que o servidor imprime ao subir. Ele diz
               como habilitá-la.
   É porque: nenhuma senha foi definida na instalação, e sem senha a
             tela não sobe.
   }

Se [a trilha estiver vazia]
   {
   Então faça: confira de qual pasta o servidor foi subido.
   É porque: ou nenhuma decisão foi registrada ainda, ou o servidor
             está gravando em logs\audit.jsonl de outra pasta. A trilha
             segue o diretório de onde o comando rodou (Tarefa B).
   }

Se [você não encontrar registros de uma avaliação que rodou]
   {
   É porque: a avaliação não é registrada, por desenho (Tarefa F). A
             trilha guarda decisões sobre conteúdo, não medições de
             desempenho.
   }

Se [um registro tiver identificador de configuração diferente dos demais]
   {
   É porque: a configuração mudou entre uma decisão e outra. Isso é
             informação, não defeito: é assim que se sabe que dois
             vereditos não são comparáveis.
   }
```

### Tarefa H. Proteger um modelo em código próprio

```
Guia de Instruções:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Para [Tarefa H: PROTEGER UM MODELO EM CÓDIGO PRÓPRIO] faça:
Passo 1: Instale as dependências opcionais.
         $ pip install ollama python-dotenv
Passo 2: Monte a engine híbrida (engine de regras + engine de grafo).
Passo 3: Crie o GuardedAgent com a engine, o cliente do modelo e o logger.
Passo 4: Submeta um conteúdo com process e leia o resultado e a explicação.

         from ethical_agent import (
             AuditLogger, CompositeEngine, GuardedAgent, KnowledgeGraphEngine,
             OllamaClient, Policy, RuleBasedEngine,
             default_policy_path, load_default_ontology,
         )
         engine = CompositeEngine([
             RuleBasedEngine(Policy.from_file(default_policy_path())),
             KnowledgeGraphEngine(load_default_ontology()),
         ], name="hybrid")
         agent = GuardedAgent(engine=engine,
                              llm=OllamaClient(model="llama3.2:3b"),
                              audit=AuditLogger("logs/audit.jsonl"))
         result = agent.process("...")
         print(result.status)
         print(result.input_verdict.explain())

>>> Para desenvolvimento e testes, troque OllamaClient por MockLLM, que
    dispensa rede.

>>> O caminho passado ao AuditLogger é usado como está. Um caminho
    relativo, como no exemplo, resolve contra o diretório de onde o
    programa roda, não contra a pasta do projeto.

>>> O GuardedAgent é o orquestrador, não o juiz. Ele encadeia
    verificação de entrada, chamada ao modelo e verificação de saída; o
    julgamento é todo da engine. Trocar a engine troca o critério sem
    tocar no agente.

>>> Passar o AuditLogger é o que faz a decisão ficar registrada. Sem
    ele, o agente decide e esquece, e a decisão deixa de ser auditável,
    que é justamente o que este sistema se propõe a garantir.

Exceções ou potenciais problemas:
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
Se [o serviço do modelo não estiver disponível]
   {
   Então faça: use o MockLLM no lugar do OllamaClient.
   É porque: sem o serviço ativo, a geração do modelo falha.
   }

Se [você precisar entender por que uma decisão foi tomada]
   {
   Então faça: chame verdict.explain(), que devolve as regras e normas
               disparadas, os trechos casados, os caminhos de inferência
               no grafo e o que foi suprimido por exceção.
   }

Se [uma camada da engine falhar]
   {
   É porque: a composição é fail-closed. A falha vira DENY, não ALLOW, e
             o conteúdo não passa por omissão.
   }
```
---

## Licença

O programa é distribuído sob a GNU GPL v3 ou posterior. O arquivo `ontologies/relaieo.ttl` é vendorizado sem modificação e mantém a licença original. Ver [`ontologies/PROVENANCE.md`](ontologies/PROVENANCE.md).

## Referências

- Arora, C. & Sarkar, D. *Relational AI Ethics Ontology (RelAIEO)* / Audit4SG. https://ontology.audit4sg.org/
- Liu, Q. et al. (2025). *Agent design pattern catalogue* (multimodel guardrails). JSS 220:112278.
- Chapman, W. et al. *ConText*, algoritmo de escopo por gatilhos, base da camada de frames.
- Ji, J. et al. (2023). *BeaverTails.* NeurIPS Datasets and Benchmarks.
- deepset. *prompt-injections.* Hugging Face.
