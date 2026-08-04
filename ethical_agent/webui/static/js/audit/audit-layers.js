// As três camadas e a redação pt-BR delas: o servidor devolve estrutura
// neutra e este módulo a nomeia, e a gradação em si é o objeto de estudo —
// versão longa em `997a6fe^`.

import { escapeHtml } from "../markdown.js";
import { renderVerdict } from "../verdict-view.js";

const GRAVITY_LABELS = {
  deny: "Bloqueado",
  rewrite: "Reescrito",
  error: "Falha técnica",
  none: "Sem intervenção",
};

const KIND_LABELS = {
  web_chat: "conversa",
  cli_process: "linha de comando",
  demo: "demonstração",
  check: "avaliação de texto",
  synthetic: "dado sintético",
};

const STAGE_WORDS = {
  input: "antes de enviar ao modelo",
  output: "depois de o modelo responder",
};

// O trabalho inteiro da camada 1: dizer o que aconteceu numa frase, sem
// vocabulário que o leitor precise ter aprendido.
const WHAT_HAPPENED = {
  blocked_input: "O sistema recusou o pedido e não chegou a consultar o modelo.",
  blocked_output: "O modelo respondeu, mas o sistema não entregou a resposta.",
  rewrite: "O sistema alterou o texto antes de seguir adiante.",
  none: "O sistema deixou passar: nada foi bloqueado nem alterado.",
};

// A natureza da preocupação, na língua do leitor: uma contagem manda o leitor
// à camada 2 para o que ele veio buscar — versão longa em `997a6fe^`.
const PRINCIPLE_LABELS = {
  security: "segurança",
  privacy: "privacidade",
  fairness: "equidade",
  non_maleficence: "prevenção de dano",
  autonomy: "autonomia",
  transparency: "transparência",
};

const DEONTIC_SENTENCES = {
  prohibition: "A política trata isso como proibido.",
  obligation: "A política trata isso como uma obrigação do sistema.",
};

export function principleLabel(principle) {
  return PRINCIPLE_LABELS[principle] || principle;
}

function joinPt(items) {
  if (items.length <= 1) return items[0] || "";
  return `${items.slice(0, -1).join(", ")} e ${items[items.length - 1]}`;
}

export function gravityLabel(gravity) {
  return GRAVITY_LABELS[gravity] || gravity;
}

export function kindLabel(kind) {
  return KIND_LABELS[kind] || kind;
}

export function formatTimestamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR");
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function quoted(text) {
  const block = el("blockquote", "ea-audit-quote");
  block.textContent = text;
  return block;
}

// --- layer 1 --------------------------------------------------------------

export function renderLayer1(detail) {
  const l1 = detail.layer1;
  const wrap = el("div", "ea-audit-layer1");

  const head = el("div", "ea-audit-layer1__head");
  const badge = el("span", `ea-audit-badge ea-audit-badge--${l1.gravity}`, gravityLabel(l1.gravity));
  head.appendChild(badge);
  head.appendChild(el("span", "ea-audit-layer1__when", formatTimestamp(l1.timestamp)));
  head.appendChild(el("span", "ea-audit-layer1__kind", kindLabel(detail.kind)));
  wrap.appendChild(head);

  // 1. What the person asked.
  const asked = el("section", "ea-audit-block");
  asked.appendChild(el("h3", null, "O que a pessoa pediu"));
  if (l1.asked_present && l1.asked) {
    asked.appendChild(quoted(l1.asked));
  } else {
    asked.appendChild(
      el(
        "p",
        "ea-audit-absent",
        "Este registro não guarda um texto de entrada — foi uma avaliação " +
          "isolada de um texto de saída, não uma conversa."
      )
    );
  }
  wrap.appendChild(asked);

  // 2. What the system did.
  const did = el("section", "ea-audit-block");
  did.appendChild(el("h3", null, "O que o sistema fez"));
  did.appendChild(el("p", "ea-audit-layer1__what", WHAT_HAPPENED[l1.intervention] || ""));
  if (l1.system_error) {
    did.appendChild(
      el(
        "p",
        "ea-audit-layer1__what",
        "Houve uma falha técnica ao gerar a resposta; o que está registrado " +
          "abaixo é o que o sistema conseguiu apurar."
      )
    );
  }
  if (l1.answered_present && l1.answered) {
    did.appendChild(el("p", "ea-audit-label", "Texto entregue à pessoa:"));
    did.appendChild(quoted(l1.answered));
  } else if (l1.intervention === "blocked_output") {
    // Not a filter on this screen: the record genuinely does not contain it.
    did.appendChild(
      el(
        "p",
        "ea-audit-absent",
        "A resposta bloqueada não está no registro. Por decisão de projeto, " +
          "conteúdo bloqueado na saída nunca é guardado — nem aqui, nem no " +
          "arquivo. Não é esta tela que o esconde."
      )
    );
  }
  wrap.appendChild(did);

  // 3. Why.
  const why = el("section", "ea-audit-block");
  why.appendChild(el("h3", null, "Por quê"));
  if (l1.rule_count > 0) {
    // A preocupação primeiro, a contabilidade depois: inverter é o que fazia o
    // leitor abrir a camada 2 só para saber do que se tratava.
    const principles = (l1.principles || []).map(principleLabel);
    if (principles.length > 0) {
      why.appendChild(
        el(
          "p",
          "ea-audit-layer1__what",
          principles.length === 1
            ? `A decisão foi por uma questão de ${principles[0]}.`
            : `A decisão foi por questões de ${joinPt(principles)}.`
        )
      );
    }
    // Só quando não-ambíguo: um veredito que mistura proibição e obrigação não
    // cabe numa destas frases, e adivinhar qual mostrar diria algo falso.
    const deontics = l1.deontics || [];
    if (deontics.length === 1 && DEONTIC_SENTENCES[deontics[0]]) {
      why.appendChild(el("p", null, DEONTIC_SENTENCES[deontics[0]]));
    }

    // Contando só as regras do veredito que decidiu, porque `rule_count` cruza
    // os dois estágios — versão longa em `997a6fe^`.
    const stage = STAGE_WORDS[l1.deciding_stage] || "";
    const staged = l1.deciding_rule_count || 0;
    if (staged > 0) {
      const count =
        staged === 1
          ? "Uma norma da política se aplicou"
          : `${staged} normas da política se aplicaram`;
      why.appendChild(el("p", null, stage ? `${count} ${stage}.` : `${count}.`));
    }
    if (l1.rule_count > staged) {
      why.appendChild(
        el("p", null, `No total, ${l1.rule_count} normas se aplicaram neste registro.`)
      );
    }

    if (l1.has_hard_rule) {
      why.appendChild(
        el("p", null, "É uma regra rígida: não admite ponderação caso a caso.")
      );
    }
  } else if (l1.intervention === "none") {
    why.appendChild(el("p", null, "Nenhuma norma da política se aplicou a este caso."));
  } else {
    why.appendChild(el("p", null, "O registro não aponta nenhuma norma para esta decisão."));
  }
  if (l1.suppressed_count > 0) {
    why.appendChild(
      el(
        "p",
        null,
        l1.suppressed_count === 1
          ? "Uma norma chegou a se aplicar mas foi afastada por uma exceção."
          : `${l1.suppressed_count} normas foram afastadas por exceções.`
      )
    );
  }
  // Por último, sempre: a passagem de bastão fecha o bloco em vez de sentar no
  // meio dele — versão longa em `997a6fe^`.
  if (l1.rule_count > 0 || l1.suppressed_count > 0) {
    why.appendChild(
      el(
        "p",
        "ea-audit-layer1__pointer",
        "Qual norma, e com que prova, está na camada seguinte."
      )
    );
  }
  wrap.appendChild(why);

  return wrap;
}

// --- layer 2 --------------------------------------------------------------

// A nota que explicava a assimetria do `matched_text` saiu daqui e vive no
// AUDIT_GUIDE, Passo 3; o que esta camada guarda é a *marcação* no ponto da
// ausência, que é rótulo e não nota — versão longa em `997a6fe^`.

export function renderLayer2(detail, handlers) {
  const l2 = detail.layer2;
  const wrap = el("div", "ea-audit-layer2");

  if (l2.input_verdict) {
    wrap.appendChild(el("h4", "ea-audit-verdict-title", "Verificação da entrada"));
    const box = el("div");
    box.innerHTML = renderVerdict(l2.input_verdict);
    wrap.appendChild(box);
  }
  if (l2.output_verdict) {
    wrap.appendChild(el("h4", "ea-audit-verdict-title", "Verificação da saída"));
    const box = el("div");
    box.innerHTML = renderVerdict(l2.output_verdict);
    wrap.appendChild(box);
  }

  const policy = l2.matched_text_policy || {};

  // Original vs reescrito, e qual "original" está em oferta depende de ONDE a
  // reescrita aconteceu — confundir os dois rotularia mal a evidência:
  // versão longa em `997a6fe^`.
  const texts = l2.texts || {};
  const rewroteInput = Boolean(texts.rewritten_input);
  const rewroteOutput = Boolean(texts.rewritten_output);
  const redactedStages = policy.redacted_stages || [];
  const redactedOutput = redactedStages.includes("output");

  if (rewroteInput || rewroteOutput || redactedOutput) {
    const section = el("section", "ea-audit-block");
    section.appendChild(el("h4", "ea-audit-verdict-title", "Antes e depois"));

    if (rewroteInput) {
      section.appendChild(el("p", "ea-audit-label", "Como a pessoa escreveu:"));
      section.appendChild(quoted(detail.layer1.asked || ""));
      section.appendChild(el("p", "ea-audit-label", "Como foi enviado ao modelo:"));
      section.appendChild(quoted(texts.rewritten_input));
    }

    if (rewroteOutput) {
      section.appendChild(el("p", "ea-audit-label", "Resposta entregue à pessoa:"));
      section.appendChild(quoted(texts.rewritten_output));

      if (texts.raw_response_present && texts.raw_response !== null) {
        const details = el("details", "ea-audit-note ea-audit-note--original");
        const summary = el("summary", null, "Ver o texto original");
        summary.appendChild(
          el(
            "span",
            "ea-audit-note__hint",
            " — o que o modelo respondeu antes da reescrita, como está guardado no registro"
          )
        );
        details.appendChild(summary);
        // Rótulo, não uma segunda nota: sem ele um <details> aberto mostra uma
        // citação cuja única identificação está lá em cima, na linha do summary.
        details.appendChild(el("p", "ea-audit-label", "Resposta original do modelo:"));
        details.appendChild(quoted(texts.raw_response));
        details.addEventListener("toggle", () => {
          if (details.open && handlers && handlers.onLayer) handlers.onLayer("raw_response");
        });
        section.appendChild(details);
      } else {
        section.appendChild(
          el(
            "p",
            "ea-audit-absent",
            "O texto original não está no registro. Quando a alteração é uma " +
              "redação, o valor bruto não é guardado — é exatamente o que a " +
              "redação faz. Não é esta tela que o esconde."
          )
        );
      }
    } else if (redactedOutput) {
      section.appendChild(
        el(
          "p",
          "ea-audit-absent",
          "A saída passou por uma redação e o valor bruto não está no registro."
        )
      );
    }

    wrap.appendChild(section);
  }

  return wrap;
}

// --- layer 3 --------------------------------------------------------------

const CONFIG_LABELS = {
  policy_schema_version: "esquema da política",
  policy_version: "versão da política",
  ontology_schema_version: "esquema da ontologia",
  ontology_grounding_version: "versão do grounding",
  ontology_norms_version: "versão das normas",
  synthetic: "dado sintético",
};

const ENGINE_LABELS = {
  "rule-based": "regras",
  "knowledge-graph": "grafo de conhecimento",
  hybrid: "híbrido (regras + grafo)",
  composite: "composto",
};

function configTable(configVersions, shape) {
  const table = el("table", "ea-audit-table");
  const body = el("tbody");
  const addRow = (label, value) => {
    const tr = el("tr");
    tr.appendChild(el("th", null, label));
    tr.appendChild(el("td", null, String(value)));
    body.appendChild(tr);
  };

  if (!configVersions || Object.keys(configVersions).length === 0) {
    return el("p", "ea-audit-absent", "O registro não guarda versões de configuração.");
  }
  if (shape === "nested") {
    // hybrid/composite: one block of versions per child engine. This is the
    // default engine, so it is most of the trail.
    for (const [engine, versions] of Object.entries(configVersions)) {
      if (versions && typeof versions === "object") {
        for (const [key, value] of Object.entries(versions)) {
          addRow(`${ENGINE_LABELS[engine] || engine} · ${CONFIG_LABELS[key] || key}`, value);
        }
      } else {
        addRow(ENGINE_LABELS[engine] || engine, versions);
      }
    }
  } else {
    for (const [key, value] of Object.entries(configVersions)) {
      addRow(CONFIG_LABELS[key] || key, value);
    }
  }
  table.appendChild(body);
  return table;
}

// Nomes de arquivo de configuração para quem não lê o repositório; `role` vem
// do código que os carrega, não de uma lista escrita à mão aqui.
const ROLE_LABELS = {
  policy: "política de regras",
  ontology: "ontologia",
  ontology_ttl: "ontologia RelAIEO (upstream, vendorizada)",
  grounding: "léxico de ancoragem",
  norms: "normas de verificação",
  frames_refusal: "gatilhos de recusa (camada de frames)",
};

// A tabela que responde "quais arquivos governaram esta decisão", com versão
// declarada **e** digest porque as duas respondem perguntas diferentes:
// versão longa em `997a6fe^`.
function artifactsTable(configuration) {
  const artifacts = configuration && configuration.artifacts;
  if (!Array.isArray(artifacts) || artifacts.length === 0) {
    return el(
      "p",
      "ea-audit-absent",
      "Este registro é anterior à procedência de configuração: ele não diz " +
        "quais arquivos governaram a decisão, só as versões declaradas acima."
    );
  }
  const table = el("table", "ea-audit-table");
  const head = el("thead");
  const headRow = el("tr");
  for (const title of ["arquivo", "versão declarada", "digest do arquivo"]) {
    headRow.appendChild(el("th", null, title));
  }
  head.appendChild(headRow);

  const body = el("tbody");
  for (const artifact of artifacts) {
    const row = el("tr");
    const name = el("td", null, ROLE_LABELS[artifact.role] || artifact.role);
    if (artifact.path) name.title = artifact.path;
    row.appendChild(name);
    row.appendChild(el("td", null, artifact.version || "não declarada"));
    const digest = el("td", null, artifact.sha256 ? `${artifact.sha256.slice(0, 12)}…` : "—");
    if (artifact.sha256) digest.title = artifact.sha256;
    if (artifact.digest_error) digest.title = `não foi possível ler: ${artifact.digest_error}`;
    row.appendChild(digest);
    body.appendChild(row);
  }
  table.appendChild(head);
  table.appendChild(body);
  return table;
}

export function renderLayer3(detail) {
  const l3 = detail.layer3;
  const wrap = el("div", "ea-audit-layer3");

  const engine = el("section", "ea-audit-block");
  engine.appendChild(el("h4", "ea-audit-verdict-title", "Quem decidiu"));
  engine.appendChild(
    el("p", null, `Motor de decisão: ${ENGINE_LABELS[l3.engine] || l3.engine || "—"}`)
  );
  engine.appendChild(configTable(l3.config_versions, l3.config_versions_shape));
  engine.appendChild(
    el(
      "p",
      "ea-audit-hint",
      "Estas são as versões da política e da ontologia vigentes no momento " +
        "desta decisão — não necessariamente as de hoje."
    )
  );

  engine.appendChild(
    el("h4", "ea-audit-verdict-title", "Quais arquivos governaram esta decisão")
  );
  engine.appendChild(artifactsTable(l3.configuration));
  if (l3.config_id_short) {
    const id = el("p", "ea-audit-configid", `config_id: ${l3.config_id_short}…`);
    id.title = l3.config_id;
    engine.appendChild(id);
    engine.appendChild(
      el(
        "p",
        "ea-audit-hint",
        "O config_id é um resumo do conjunto inteiro. Dois registros com o " +
          "mesmo config_id foram decididos sob uma configuração idêntica, " +
          "arquivo por arquivo — são diretamente comparáveis. Se ele difere, " +
          "alguma coisa mudou, mesmo que as versões declaradas acima sejam as " +
          "mesmas."
      )
    );
  }
  wrap.appendChild(engine);

  const model = el("section", "ea-audit-block");
  model.appendChild(el("h4", "ea-audit-verdict-title", "Quem respondeu"));
  // Um veredito de saída só existe depois de o modelo responder, então a
  // ausência dele é o sinal confiável de que nada foi consultado —
  // versão longa em `997a6fe^`.
  const modelWasCalled = Boolean(detail.layer2 && detail.layer2.output_verdict);
  if (!modelWasCalled) {
    model.appendChild(
      el(
        "p",
        "ea-audit-absent",
        "Nenhum modelo foi consultado: a decisão foi tomada antes de chegar a ele."
      )
    );
    if (l3.llm_provenance_text) {
      model.appendChild(
        el("p", "ea-audit-hint", `Modelo configurado na ocasião: ${l3.llm_provenance_text}`)
      );
    }
  } else if (l3.llm_provenance_text) {
    model.appendChild(el("p", null, l3.llm_provenance_text));
  } else if (l3.llm_provenance) {
    // `safe_provenance_text` não devolveu nada: registro escrito por uma versão
    // que conhecia um tipo de procedência que esta não conhece.
    model.appendChild(
      el("p", "ea-audit-absent", "Proveniência registrada num formato que esta tela não reconhece:")
    );
    const pre = el("pre", "ea-audit-pre", JSON.stringify(l3.llm_provenance, null, 2));
    model.appendChild(pre);
  } else if (detail.layer2 && detail.layer2.output_verdict) {
    // O modelo *foi* chamado, mas este registro não diz qual — dizer "nenhum
    // modelo foi consultado" aqui seria simplesmente falso.
    model.appendChild(
      el(
        "p",
        "ea-audit-absent",
        "Um modelo respondeu, mas este registro não guarda qual — registros " +
          "de demonstração não gravam essa informação."
      )
    );
  } else {
    model.appendChild(
      el(
        "p",
        "ea-audit-absent",
        "Nenhum modelo foi consultado: a decisão foi tomada antes de chegar a ele."
      )
    );
  }
  if (l3.llm_error) {
    model.appendChild(el("p", "ea-audit-absent", `Erro do modelo: ${l3.llm_error}`));
  }
  wrap.appendChild(model);

  const ctx = el("section", "ea-audit-block");
  ctx.appendChild(el("h4", "ea-audit-verdict-title", "Onde isto aconteceu"));
  const table = el("table", "ea-audit-table");
  const body = el("tbody");
  const row = (label, value) => {
    const tr = el("tr");
    tr.appendChild(el("th", null, label));
    tr.appendChild(el("td", null, value === null || value === undefined ? "—" : String(value)));
    body.appendChild(tr);
  };
  row("identificador do evento", l3.event_id);
  row("conversa", l3.conversation_id);
  row("turno na conversa", l3.turn_index);
  if (l3.source) row("origem", kindLabel(l3.source));
  table.appendChild(body);
  ctx.appendChild(table);
  wrap.appendChild(ctx);

  const unknown = l3.unknown_fields || {};
  if (Object.keys(unknown).length > 0) {
    const extra = el("section", "ea-audit-block");
    extra.appendChild(el("h4", "ea-audit-verdict-title", "Campos que esta tela não conhece"));
    extra.appendChild(
      el(
        "p",
        "ea-audit-hint",
        "O registro traz campos que esta versão da tela não sabe onde colocar. " +
          "Aparecem aqui em vez de serem descartados."
      )
    );
    extra.appendChild(el("pre", "ea-audit-pre", JSON.stringify(unknown, null, 2)));
    wrap.appendChild(extra);
  }

  return wrap;
}

export function renderRawJson(detail) {
  return el("pre", "ea-audit-pre", JSON.stringify(detail.raw, null, 2));
}

export { escapeHtml };
