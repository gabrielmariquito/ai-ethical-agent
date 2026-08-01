# Guia da trilha de auditoria

Por padrão, toda chamada a `check`, `process` ou `demo` -- pela CLI
(`ethical_agent`) ou pela interface gráfica (`gui_app.py`) -- grava um
registro JSON em `logs/audit.jsonl`. O objetivo é permitir auditar o uso real
do sistema depois do fato: cada registro traz, além do resultado, a versão
exata da política/ontologia (`config_versions`) que produziu aquele veredito.

## Passo 1 -- a trilha de auditoria

### 1.1 Onde ela fica

- Caminho padrão: `logs/audit.jsonl`, um objeto JSON por linha.
- Pode ser trocado com `--audit-log CAMINHO` (CLI) ou pelo campo `--audit-log`
  ao lado do checkbox "Enable audit log" no painel **Engine settings** da GUI.
- O arquivo (e o diretório `logs/`) é criado automaticamente na primeira
  gravação -- não é preciso criar nada manualmente. O instalador
  (`wizard_gui.py`) já cria `logs/` ao final de uma instalação bem-sucedida,
  como conveniência.
- `eval` **nunca** grava: ele roda centenas de casos sintéticos do dataset de
  avaliação direto contra a engine, sem passar por `check`/`process`/`demo`,
  e gravá-los poluiria a trilha com dados que não são uso real.

### 1.2 Como desativar

Gravar o texto de entrada completo (que pode incluir dado pessoal) por padrão
é uma postura deliberada, não um acidente -- e por isso existem três formas
independentes de desligar:

- `--no-audit` (CLI), em qualquer subcomando.
- Variável de ambiente `ETHICAL_AGENT_NO_AUDIT=1` (equivalente a `--no-audit`
  em qualquer processo, CLI ou GUI).
- Desmarcar "Enable audit log" no painel **Engine settings** da GUI.

Na primeira gravação bem-sucedida de cada processo, é impresso um aviso de
uma linha em `stderr` (e, na GUI, também exibido no painel de resultado, já
que uma janela pode não ter console visível) dizendo onde a trilha está sendo
gravada e como desativá-la.

Uma falha ao gravar (por exemplo, permissão negada no caminho do log) nunca
derruba o comando nem muda o veredito: é reportada como aviso e o comando
segue normalmente.

## O que não dá para auditar

| Situação | Por que não aparece |
|---|---|
| Conteúdo bloqueado no `stage=output` (via `process`/`demo`, ou `check --stage output`) | É descartado antes de chegar ao log -- ver `tests/test_agent.py::test_denied_output_is_never_retained` e o equivalente de CLI em `tests/test_main.py` |
| Casos de `eval` | `ethical_agent eval` roda os casos sintéticos direto contra a engine e nunca grava no audit log, por desenho |

## `audit_tools.py`

Script auxiliar em `audit_tools.py`, na raiz do repositório:

- `python audit_tools.py resumir` -- lê `logs/audit.jsonl` e imprime contagens
  por status e por engine.
- `python audit_tools.py gerar -n 5` -- adiciona registros **sintéticos**
  claramente marcados (`engine: "SYNTHETIC-SAMPLE-DATA"`) para testar
  `resumir` ou gerar capturas de tela de documentação. **Nunca é uso real** --
  não confundir com a trilha gerada por `check`/`process`/`demo`.

Veja também a seção "Registro de auditoria e versionamento de configuração"
no `README.md`.
