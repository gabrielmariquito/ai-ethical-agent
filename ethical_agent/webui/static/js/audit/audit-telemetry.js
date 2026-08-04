// Instrumentação da própria sessão do auditor, divulgada antes do login e
// permanentemente durante o trabalho, com relógio monotônico e dois números de
// permanência — REGISTRO, "Texto movido do código".

const FLUSH_EVERY_MS = 10_000;
const FLUSH_AT_QUEUED = 20;

let seq = 0;
let queue = [];
let flushTimer = null;
let lastAckedSeq = 0;
let lastSentSeq = 0;
let onCount = null;

function nowMs() {
  return performance.now();
}

function isAttending() {
  return document.visibilityState === "visible" && document.hasFocus();
}

// Um cronômetro por coisa cronometrada: um acumulador só seria zerado a cada
// registro aberto.
function createAttentionClock() {
  let accumulated = 0;
  let running = isAttending();
  let since = running ? nowMs() : 0;
  return {
    pause() {
      if (running) accumulated += nowMs() - since;
      running = false;
      since = 0;
    },
    resume() {
      if (!running) {
        running = true;
        since = nowMs();
      }
    },
    read() {
      return Math.round(accumulated + (running ? nowMs() - since : 0));
    },
  };
}

// Every live clock, so a single visibility change updates all of them.
const clocks = new Set();

function newClock() {
  const clock = createAttentionClock();
  clocks.add(clock);
  return clock;
}

function releaseClock(clock) {
  if (clock) clocks.delete(clock);
}

export function track(type, payload) {
  seq += 1;
  queue.push({ seq, type, client_ts: new Date().toISOString(), payload: payload || {} });
  if (onCount) onCount(seq);
  if (queue.length >= FLUSH_AT_QUEUED) {
    flush();
  } else if (flushTimer === null) {
    flushTimer = setTimeout(flush, FLUSH_EVERY_MS);
  }
}

export async function flush() {
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (queue.length === 0) return;
  const batch = queue;
  queue = [];
  lastSentSeq = batch[batch.length - 1].seq;
  try {
    const response = await fetch("/api/audit/telemetry", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ events: batch }),
    });
    if (!response.ok) return;
    const data = await response.json();
    if (typeof data.last_seq === "number") {
      // Uma lacuna significa evento gravado sem confirmação, e registrá-la
      // transforma perda silenciosa em buraco visível no arquivo.
      if (data.last_seq > lastAckedSeq + batch.length) {
        emitGap(lastAckedSeq + 1, data.last_seq);
      }
      lastAckedSeq = Math.max(lastAckedSeq, data.last_seq);
    }
  } catch (_err) {
    // The screen must keep working when telemetry cannot be written; the
    // study is the reading, not the measurement of it.
  }
}

function emitGap(expected, received) {
  queue.push({
    seq: ++seq,
    type: "telemetry_gap_detected",
    client_ts: new Date().toISOString(),
    payload: { expected_seq: expected, received_seq: received, lost: received - expected },
  });
}

// `sendBeacon` sobrevive ao page-hide onde o `fetch` não, mas não lê resposta
// — daí a detecção de lacuna acima.
export function flushBeacon() {
  if (queue.length === 0) return;
  const batch = queue;
  queue = [];
  try {
    const blob = new Blob([JSON.stringify({ events: batch })], {
      type: "application/json; charset=utf-8",
    });
    navigator.sendBeacon("/api/audit/telemetry", blob);
  } catch (_err) {
    /* nothing further to try at page-hide time */
  }
}

// --- per-record timing ----------------------------------------------------

let openRecord = null;

export function recordOpened(summary, context) {
  const seen = seenRecords.get(summary.event_id);
  const times = seen ? seen.count : 0;
  openRecord = {
    eventId: summary.event_id,
    startedAt: nowMs(),
    clock: newClock(),
    layers: [],
  };
  openIndex += 1;
  seenRecords.set(summary.event_id, { count: times + 1 });
  track("record_opened", {
    record_event_id: summary.event_id,
    record_kind: summary.kind,
    intervention: summary.intervention,
    gravity: summary.gravity,
    open_index: openIndex,
    // Captured client-side AND re-derivable server-side from a second
    // record_opened with the same session_id: a dropped beacon degrades the
    // count without invalidating the file.
    revisit: times > 0,
    times_seen_before: times,
    from: context || "list",
  });
}

export function recordClosed() {
  if (!openRecord) return;
  const dwell = Math.round(nowMs() - openRecord.startedAt);
  track("record_closed", {
    record_event_id: openRecord.eventId,
    dwell_ms: dwell,
    visible_dwell_ms: openRecord.clock.read(),
    layers_expanded_in_order: openRecord.layers.slice(),
  });
  releaseClock(openRecord.clock);
  openRecord = null;
}

export function layerExpanded(layer) {
  if (!openRecord) return;
  openRecord.layers.push(layer);
  track("layer_expanded", {
    record_event_id: openRecord.eventId,
    layer,
    order_index: openRecord.layers.length,
    ms_since_open: Math.round(nowMs() - openRecord.startedAt),
  });
}

export function layerCollapsed(layer) {
  if (!openRecord) return;
  track("layer_collapsed", {
    record_event_id: openRecord.eventId,
    layer,
    ms_open: Math.round(nowMs() - openRecord.startedAt),
  });
}

export function currentRecordId() {
  return openRecord ? openRecord.eventId : null;
}

const seenRecords = new Map();
let openIndex = 0;
let sessionStartedAt = 0;
let sessionClock = null;

export function sessionStarted(payload) {
  sessionStartedAt = nowMs();
  sessionClock = newClock();
  track("session_started", payload);
}

export function sessionEnded(reason) {
  recordClosed();
  track("session_ended", {
    reason,
    duration_ms: sessionStartedAt ? Math.round(nowMs() - sessionStartedAt) : 0,
    visible_duration_ms: sessionClock ? sessionClock.read() : 0,
  });
}

export function onEventCount(callback) {
  onCount = callback;
}

function pauseAll() {
  for (const clock of clocks) clock.pause();
}

function resumeAll() {
  for (const clock of clocks) clock.resume();
}

export function install() {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      resumeAll();
      return;
    }
    pauseAll();
    if (openRecord) {
      // Not a close: the auditor may come back to the same record, and
      // closing here would double-count the view when they do.
      track("record_dwell_tick", {
        record_event_id: openRecord.eventId,
        visible_dwell_ms_so_far: openRecord.clock.read(),
      });
    }
    flushBeacon();
  });
  window.addEventListener("focus", resumeAll);
  window.addEventListener("blur", pauseAll);
  // pagehide, never beforeunload/unload -- those are unreliable in current
  // browsers and would lose the end of every session.
  window.addEventListener("pagehide", () => {
    sessionEnded("pagehide");
    flushBeacon();
  });
}
