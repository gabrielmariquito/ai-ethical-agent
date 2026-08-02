// Renders a Verdict.to_dict() payload (as returned by the API's
// input_verdict/output_verdict fields) into an HTML fragment. Shared by the
// chat's per-turn expandable detail (this screen) and, later, check/demo.

import { escapeHtml } from "./markdown.js";

const STAGE_LABELS = { input: "entrada", output: "saída" };

const EFFECT_LABELS = {
  ALLOW: "permitido",
  FLAG: "sinalizado",
  REWRITE: "reescrito",
  DENY: "bloqueado",
};

function stageLabel(stage) {
  return STAGE_LABELS[stage] || escapeHtml(stage);
}

function effectLabel(effect) {
  return EFFECT_LABELS[effect] || escapeHtml(effect);
}

// `redacted` is the match's flag, not the evidence's: a rule with
// redact=true scrubs its own matched_text (Evidence.without_matched_text, in
// engine.py), so the field arrives null by design. Rendering that as silence
// -- description straight to span, no mention -- makes the rule working look
// like the record failing, and leaves the audit screen's note about it
// pointing at nothing. The absence is stated where it happens.
function renderEvidence(evidence, redacted) {
  if (!evidence || evidence.length === 0) return "";
  const items = evidence
    .map((ev) => {
      const parts = [];
      if (ev.description) parts.push(escapeHtml(ev.description));
      if (ev.matched_text) {
        parts.push(`trecho: “${escapeHtml(ev.matched_text)}”`);
      } else if (redacted) {
        parts.push(
          '<span class="ea-evidence__redacted">trecho: removido pela própria redação</span>'
        );
      }
      if (ev.span) parts.push(`posição ${ev.span[0]}–${ev.span[1]}`);
      return `<li>${parts.join(" — ")}</li>`;
    })
    .join("");
  return `<ul class="ea-evidence">${items}</ul>`;
}

function renderMatch(match) {
  const hardBadge = match.hard ? '<span class="ea-badge ea-badge--hard">regra rígida</span>' : "";
  return `
    <li class="ea-match">
      <div class="ea-match__head">
        <code>${escapeHtml(match.rule_id)}</code>
        <span class="ea-match__effect">${effectLabel(match.effect)}</span>
        ${hardBadge}
      </div>
      <div class="ea-match__meta">${escapeHtml(match.principle)} · ${escapeHtml(match.deontic)} · severidade ${escapeHtml(match.severity)}</div>
      ${match.rationale ? `<p class="ea-match__rationale">${escapeHtml(match.rationale)}</p>` : ""}
      ${renderEvidence(match.evidence, match.redacted)}
    </li>`;
}

export function renderVerdict(verdict) {
  if (!verdict) return "";
  const matches = (verdict.matches || []).map(renderMatch).join("");
  const rewritten = verdict.rewritten_content
    ? `<div class="ea-rewritten"><strong>Conteúdo reescrito:</strong><p>${escapeHtml(verdict.rewritten_content)}</p></div>`
    : "";
  const reason = verdict.reason ? `<p class="ea-verdict__reason">${escapeHtml(verdict.reason)}</p>` : "";
  return `
    <div class="ea-verdict">
      <div class="ea-verdict__head">
        <span class="ea-badge ea-badge--${escapeHtml((verdict.decision || "").toLowerCase())}">${effectLabel(verdict.decision)}</span>
        <span class="ea-verdict__stage">estágio: ${stageLabel(verdict.stage)}</span>
        <span class="ea-verdict__engine">engine: ${escapeHtml(verdict.engine)}</span>
      </div>
      ${reason}
      ${matches ? `<ul class="ea-matches">${matches}</ul>` : '<p class="ea-verdict__none">Nenhuma regra disparada.</p>'}
      ${rewritten}
    </div>`;
}
