// The three layers, and all the pt-BR wording for them.
//
// The server (webui/audit_view.py) returns neutral structure -- "blocked_input",
// "deny", "input" -- and this module names it, the same split verdict-view.js
// already uses for dto.classify_intervention. The gradation itself is the
// object of study: layer 1 has to be judgeable by someone who has never read
// a policy file, and layers 2 and 3 have to be there for when it isn't.

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

// Layer 1's whole job: say what happened in a sentence, with no vocabulary
// the reader has to have been taught. No rule identifiers, no spans, no
// "verdict"/"stage"/"engine".
const WHAT_HAPPENED = {
  blocked_input: "O sistema recusou o pedido e não chegou a consultar o modelo.",
  blocked_output: "O modelo respondeu, mas o sistema não entregou a resposta.",
  rewrite: "O sistema alterou o texto antes de seguir adiante.",
  none: "O sistema deixou passar: nada foi bloqueado nem alterado.",
};

// The nature of the concern, in the reader's language. A count ("uma norma
// se aplicou") says how many and when, then sends the reader to layer 2 for
// what they actually came for -- which puts the basics one click too deep.
// These two closed vocabularies are what layer 1 can say without borrowing
// layer 2's: no rule id, no span, no engine name.
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
    // The concern first, the bookkeeping after. Reversing these is what made
    // the reader open layer 2 to learn whether this was about privacy or
    // about self-harm.
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
    // Only when unambiguous: a record whose deciding verdict mixes a
    // prohibition and an obligation cannot be summed up in one of these
    // sentences, and guessing which to show would misstate the policy.
    const deontics = l1.deontics || [];
    if (deontics.length === 1 && DEONTIC_SENTENCES[deontics[0]]) {
      why.appendChild(el("p", null, DEONTIC_SENTENCES[deontics[0]]));
    }

    // Counting only the deciding verdict's rules: rule_count spans both
    // stages, and pairing that total with a single stage word would say
    // something false about half of them.
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
  // Last, always: the hand-off closes the block instead of sitting in the
  // middle of it. It used to be appended inside the rule_count branch, so a
  // record with a suppressed rule read "...está na camada seguinte." and
  // then kept going.
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

// The note that used to explain the matched_text asymmetry here was removed.
// The explanation itself still exists, in AUDIT_GUIDE.pt-BR.md (Passo 3); what
// this layer keeps is the *marking* at the point of absence -- "trecho:
// removido pela própria redação", drawn by verdict-view.js -- which is a
// label, not a note, and is what distinguishes a deliberate absence from
// there having been no excerpt at all.

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

  // Original vs rewritten -- only when something actually was rewritten.
  //
  // Which "original" is on offer depends on WHERE the rewrite happened, and
  // conflating the two would mislabel the evidence:
  //   input rewritten  -> the before/after is the person's text vs the text
  //                       the model was actually given. raw_response is the
  //                       answer to the *rewritten* prompt, so it is not an
  //                       "original" of anything and must not be offered as
  //                       one.
  //   output rewritten -> raw_response IS the text before the rewrite, and
  //                       that comparison is the only way to judge whether
  //                       the rewrite was appropriate.
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
        // The sibling block above carries its own ea-audit-label next to the
        // text it describes. Without one here, an open <details> shows a bare
        // quote whose only identification is back up in the summary line --
        // the reader has to remember what they clicked. This is a label, not
        // a second note: the asymmetry note stays the only note in this layer.
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
  wrap.appendChild(engine);

  const model = el("section", "ea-audit-block");
  model.appendChild(el("h4", "ea-audit-verdict-title", "Quem respondeu"));
  // An output verdict exists only once the model has answered, so its
  // absence is the reliable signal that nothing was consulted. The record
  // still carries the *configured* provenance in that case (the agent
  // attaches it before knowing the input would be refused), and showing it
  // as though something had answered would be plainly wrong.
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
    // safe_provenance_text returned nothing: a record written by a version
    // that knew a provenance kind this one does not. Say so plainly instead
    // of pretending the field is empty.
    model.appendChild(
      el("p", "ea-audit-absent", "Proveniência registrada num formato que esta tela não reconhece:")
    );
    const pre = el("pre", "ea-audit-pre", JSON.stringify(l3.llm_provenance, null, 2));
    model.appendChild(pre);
  } else if (detail.layer2 && detail.layer2.output_verdict) {
    // The model *was* called -- there is an output verdict, which only
    // exists once it answered -- but this record does not say which model.
    // Demo runs are the usual case (source="demo" already marks them, so
    // provenance is not written). Saying "no model was consulted" here
    // would be simply false.
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
