// Renderiza o bloco compacto de "intervention" compartilhado por chat.js e
// demo.js, uma renderização só e não uma cópia por tela.

import { escapeHtml } from "./markdown.js";
import { renderVerdict } from "./verdict-view.js";

export const INTERVENTION_LABELS = {
  blocked_input: "Bloqueada na entrada",
  blocked_output: "Bloqueada na saída",
  rewrite: "Reescrita",
  system_error: "Falha do modelo",
};

export function interventionKind(item) {
  if (item.system_error) return "system_error";
  return item.intervention;
}

export function interventionSummary(item) {
  const kind = interventionKind(item);
  // `Verdict.to_dict()` não traz a chave "intervened", que é propriedade
  // computada só em Python e nunca serializada —
  // REGISTRO, "Texto movido do código".
  const outputIsRewrite = Boolean(item.output_verdict) && item.output_verdict.decision === "REWRITE";
  const usesOutput = kind === "blocked_output" || (kind === "rewrite" && outputIsRewrite);
  const verdict = usesOutput ? item.output_verdict : item.input_verdict;
  const ruleId = verdict && verdict.matches && verdict.matches.length > 0 ? verdict.matches[0].rule_id : null;
  const stageLabel = verdict && verdict.stage === "output" ? "saída" : "entrada";
  let text = `${INTERVENTION_LABELS[kind] || kind} · estágio: ${stageLabel}`;
  if (ruleId) text += ` · ${ruleId}`;
  return text;
}

export function renderIntervention(item) {
  const kind = interventionKind(item);
  const details = document.createElement("details");
  details.className = `ea-intervention ea-intervention--${kind}`;

  const summary = document.createElement("summary");
  summary.className = "ea-intervention__summary";
  summary.innerHTML = `<span>${escapeHtml(interventionSummary(item))}</span><span class="ea-intervention__hint">detalhes</span>`;
  details.appendChild(summary);

  const body = document.createElement("div");
  body.className = "ea-intervention__body";
  if (kind === "system_error") {
    body.innerHTML = "<p>O modelo não respondeu (falha interna); veja o registro de auditoria para detalhes técnicos.</p>";
  } else {
    let html = `<p><strong>Verificação de entrada</strong></p>${renderVerdict(item.input_verdict)}`;
    if (item.output_verdict) {
      html += `<p><strong>Verificação de saída</strong></p>${renderVerdict(item.output_verdict)}`;
    }
    body.innerHTML = html;
  }
  details.appendChild(body);
  return details;
}
