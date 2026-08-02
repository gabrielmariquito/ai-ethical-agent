// Renders the compact "intervention" block (collapsed summary + expandable
// detail) shared by chat.js and demo.js -- both work off objects with the
// same shape (intervention, system_error, input_verdict, output_verdict),
// since dto.agent_result_summary() is what builds both a chat turn and a
// demo case server-side. One rendering, not a second copy per screen.

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
  // Verdict.to_dict() (what the API actually sends) has no "intervened" key
  // -- that's a Python-only computed property on the Verdict object itself,
  // never serialized. The only way a "rewrite" item can be output-caused is
  // output_verdict.decision === "REWRITE" (DENY-at-output is already its
  // own "blocked_output" kind, handled above; FLAG doesn't count as an
  // intervention at all).
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
