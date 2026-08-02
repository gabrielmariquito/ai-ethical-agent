// The record panel: layer 1 always open, layers 2 and 3 behind a click, and
// the timing of exactly that as instrumentation.

import { getJSON } from "../api.js";
import { renderLayer1, renderLayer2, renderLayer3, renderRawJson } from "./audit-layers.js";
import { createChangeRequestControl } from "./audit-change-request.js";
import { createConversationStrip } from "./audit-conversation.js";
import {
  layerCollapsed,
  layerExpanded,
  recordClosed,
  recordOpened,
  track,
} from "./audit-telemetry.js";

function layerDetails(title, hint, layerKey, build) {
  const details = document.createElement("details");
  details.className = "ea-audit-layer";
  const summary = document.createElement("summary");
  summary.className = "ea-audit-layer__summary";
  const strong = document.createElement("strong");
  strong.textContent = title;
  summary.appendChild(strong);
  const small = document.createElement("span");
  small.className = "ea-audit-layer__hint";
  small.textContent = hint;
  summary.appendChild(small);
  details.appendChild(summary);

  let built = false;
  details.addEventListener("toggle", () => {
    if (details.open) {
      if (!built) {
        details.appendChild(build());
        built = true;
      }
      layerExpanded(layerKey);
    } else {
      layerCollapsed(layerKey);
    }
  });
  return details;
}

export function createRecordPanel(panelEl, onOpenRecord) {
  async function open(summary, context) {
    // Closing the previous one first is what makes dwell time mean
    // "time on that record" rather than "time until the next click".
    recordClosed();

    const params = new URLSearchParams();
    if (summary.offset !== undefined && summary.offset !== null) {
      params.set("offset", String(summary.offset));
    }
    const query = params.toString();
    const detail = await getJSON(
      `/api/audit/records/${encodeURIComponent(summary.event_id)}${query ? `?${query}` : ""}`
    );

    recordOpened(summary, context);
    render(detail, summary);
  }

  function render(detail, summary) {
    panelEl.innerHTML = "";

    panelEl.appendChild(renderLayer1(detail));

    const layer2 = layerDetails(
      "Camada 2 — a norma e a prova",
      "qual regra disparou, com que evidência",
      "layer2",
      () =>
        renderLayer2(detail, {
          onLayer: (key) => layerExpanded(key),
        })
    );
    panelEl.appendChild(layer2);

    const layer3 = layerDetails(
      "Camada 3 — de onde veio esta decisão",
      "versões de política e ontologia, modelo, conversa",
      "layer3",
      () => renderLayer3(detail)
    );
    panelEl.appendChild(layer3);

    const raw = layerDetails(
      "Ver o registro bruto",
      "o JSON exatamente como está no arquivo",
      "raw_json",
      () => renderRawJson(detail)
    );
    panelEl.appendChild(raw);

    // The seam for the next change: one control per rule that fired, so the
    // marking is anchored to a rule and not just to a record.
    const matches = [];
    for (const key of ["input_verdict", "output_verdict"]) {
      const verdict = detail.layer2[key];
      if (verdict && verdict.matches) matches.push(...verdict.matches);
    }
    const seam = document.createElement("section");
    seam.className = "ea-audit-seam";
    const seamTitle = document.createElement("h4");
    seamTitle.textContent = "Discorda desta decisão?";
    seam.appendChild(seamTitle);
    if (matches.length === 0) {
      seam.appendChild(createChangeRequestControl({}, detail.event_id));
    } else {
      for (const match of matches) {
        seam.appendChild(createChangeRequestControl(match, detail.event_id));
      }
    }
    panelEl.appendChild(seam);

    if (detail.layer3.conversation_id) {
      panelEl.appendChild(
        createConversationStrip(detail.layer3.conversation_id, detail.event_id, onOpenRecord)
      );
    }

    panelEl.scrollTop = 0;
  }

  return { open };
}
