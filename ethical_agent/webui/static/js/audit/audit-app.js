// Entry point for the audit screen.
//
// Two views in one page: the login shell (served without a session, holds no
// records) and the screen proper. Any audit request coming back 401 drops
// straight back to login -- sessions are in-process, so a server restart
// invalidates them, and pretending otherwise would leave the auditor
// clicking a dead screen.

import { getJSON, showErrorBanner } from "../api.js";
import { renderNav } from "../nav.js";
import { createLogin, renderCaveat } from "./audit-auth.js";
import { createList } from "./audit-list.js";
import { createRecordPanel } from "./audit-record.js";
import { renderSessionBanner } from "./audit-session-banner.js";
import {
  flush,
  install as installTelemetry,
  sessionEnded,
  sessionStarted,
} from "./audit-telemetry.js";

const els = {
  nav: document.getElementById("ea-nav"),
  bannerHost: document.getElementById("ea-banner-host"),
  login: document.getElementById("ea-audit-login"),
  loginForm: document.getElementById("ea-audit-login-form"),
  password: document.getElementById("ea-audit-password"),
  submit: document.getElementById("ea-audit-login-submit"),
  error: document.getElementById("ea-audit-login-error"),
  loginLogPath: document.getElementById("ea-audit-login-logpath"),
  caveatLogin: document.getElementById("ea-audit-caveat-login"),
  app: document.getElementById("ea-audit-app"),
  sessionBanner: document.getElementById("ea-audit-session-banner"),
  filter: document.getElementById("ea-audit-filter"),
  list: document.getElementById("ea-audit-list"),
  listFooter: document.getElementById("ea-audit-list-footer"),
  record: document.getElementById("ea-audit-record"),
};

let list = null;
let recordPanel = null;

function showLogin() {
  els.app.hidden = true;
  els.login.hidden = false;
  els.password.focus();
}

async function openRecord(summary, context) {
  try {
    await recordPanel.open(summary, context);
    list.selectById(summary.event_id);
  } catch (err) {
    handleError(err);
  }
}

function handleError(err) {
  if (err && err.status === 401) {
    sessionEnded("expired");
    flush();
    showLogin();
    showErrorBanner(
      els.bannerHost,
      new Error("A sessão de auditoria expirou (ou o servidor reiniciou). Entre novamente.")
    );
    return;
  }
  showErrorBanner(els.bannerHost, err);
}

async function startSession(session) {
  els.login.hidden = true;
  els.app.hidden = false;

  // The session just became real, so the evaluator's tools exist now. No
  // request needed to find that out -- being here is the answer.
  renderNav(els.nav, "/audit", { auditEnabled: true, sessionActive: true });
  renderSessionBanner(els.sessionBanner, session);
  installTelemetry();
  sessionStarted({
    audit_log_path: session.audit_log_path,
    kinds: session.default_kinds || [],
  });

  recordPanel = createRecordPanel(els.record, openRecord);
  list = createList(els.list, els.listFooter, els.filter, (summary, context) => {
    openRecord(summary, context);
  });
  try {
    await list.start();
  } catch (err) {
    handleError(err);
  }
}

async function init() {
  // auditEnabled is true by definition here: this page only exists when the
  // realm is configured (httphandler's GATED_PAGES), so reaching this code
  // at all means the item should link. sessionActive is deliberately left
  // unset until login succeeds -- this render is the one the login form sits
  // under, and the tools do not exist yet for whoever is looking at it.
  renderNav(els.nav, "/audit", { auditEnabled: true });
  renderCaveat(els.caveatLogin);
  createLogin(
    { form: els.loginForm, password: els.password, submit: els.submit, error: els.error },
    (session) => {
      startSession(session);
    }
  );

  // Already logged in (a reload inside a live session) -- skip the form.
  try {
    const session = await getJSON("/api/audit/session");
    els.loginLogPath.textContent = session.auditor_log_path || "logs/auditor_sessions.jsonl";
    await startSession(session);
  } catch (err) {
    if (err && err.status === 401) {
      showLogin();
      return;
    }
    showLogin();
    showErrorBanner(els.bannerHost, err);
  }
}

init();
