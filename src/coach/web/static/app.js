// ---------- session id (per device) ----------
let sessionId = localStorage.getItem("coach_session");
if (!sessionId) {
  sessionId = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
  localStorage.setItem("coach_session", sessionId);
}

const $ = (id) => document.getElementById(id);

// ---------- tab navigation ----------
const TITLES = { chat: "Coach", stats: "Dashboard", reports: "Reviews" };
const VIEWS = new Set(Object.keys(TITLES));
let currentView = "chat";
let syncPromise = null;

function switchView(view) {
  currentView = view;
  for (const s of document.querySelectorAll(".view")) s.hidden = s.id !== `view-${view}`;
  for (const b of document.querySelectorAll("#tabbar button")) {
    b.classList.toggle("active", b.dataset.view === view);
  }
  $("title").textContent = TITLES[view];
  if (view === "stats") loadStats();
  if (view === "reports") { loadActions(); loadReports(); }
  history.replaceState(null, "", "#" + view);
}

document.querySelectorAll("#tabbar button").forEach((b) =>
  b.addEventListener("click", () => switchView(b.dataset.view))
);

// ---------- chat ----------
const messages = $("messages");
const form = $("composer");
const input = $("input");
const send = $("send");
let busy = false;

function showEmptyState() {
  if (messages.children.length === 0) {
    const el = document.createElement("div");
    el.className = "empty";
    el.innerHTML = "<strong>Ask your coach</strong>Questions about your training, recovery, or progress — grounded in your synced data.";
    messages.appendChild(el);
  }
}
function clearEmptyState() {
  const e = messages.querySelector(".empty");
  if (e) e.remove();
}
function addMessage(role, text) {
  clearEmptyState();
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}
function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
}

async function sendMessage(text) {
  busy = true;
  send.disabled = true;
  addMessage("user", text);
  const coachEl = addMessage("coach", "");
  coachEl.classList.add("pending");
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    });
    if (resp.status === 401) { location.href = "/login"; return; }
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const evt = JSON.parse(line);
        if (evt.type === "text") {
          coachEl.textContent += evt.text;
          messages.scrollTop = messages.scrollHeight;
        }
      }
    }
  } catch (err) {
    coachEl.textContent += (coachEl.textContent ? "\n\n" : "") + `⚠️ ${err.message}`;
  } finally {
    coachEl.classList.remove("pending");
    busy = false;
    send.disabled = false;
    input.focus();
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  autosize();
  sendMessage(text);
});
input.addEventListener("input", autosize);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
});

// ---------- stats (design dashboard, live data) ----------
const syncButton = $("sync-data");
let statsStarted = false;

function setSyncStatus(text) {
  const m = $("stats-meta");
  if (m) m.textContent = text || "";
}

async function loadStats() {
  try {
    await window.CoachData.ready;
  } catch (err) {
    setSyncStatus(`Couldn't load stats: ${err.message}`);
    return;
  }
  if (!statsStarted) { window.CoachStats.init(); statsStarted = true; }
  else window.CoachStats.render();
}

function syncSummary(data) {
  if (data.running) return data.message || "Sync already running.";
  const results = data.results || [];
  const synced = results.filter((r) => r.status === "synced");
  if (!synced.length) return "Up to date";
  return `Updated ${synced.map((r) => r.source).join(", ")}`;
}

async function syncData({ silent = false } = {}) {
  if (syncPromise) return syncPromise;

  const label = syncButton ? syncButton.textContent : "";
  if (syncButton) { syncButton.disabled = true; syncButton.textContent = "Syncing…"; }
  if (!silent) setSyncStatus("Syncing data…");

  syncPromise = (async () => {
    try {
      const resp = await fetch("/api/sync", { method: "POST" });
      if (resp.status === 401) { location.href = "/login"; return; }
      const data = await resp.json();
      if (!resp.ok && resp.status !== 202) throw new Error(data.detail || `HTTP ${resp.status}`);

      setSyncStatus(syncSummary(data));
      if (resp.status !== 202) {
        await window.CoachData.reload();
        if (statsStarted) window.CoachStats.render();
      }
    } catch (err) {
      if (!silent || currentView === "stats") setSyncStatus(`Sync failed: ${err.message}`);
    } finally {
      if (syncButton) { syncButton.disabled = false; syncButton.textContent = label; }
      syncPromise = null;
    }
  })();

  return syncPromise;
}

if (syncButton) syncButton.addEventListener("click", () => syncData());

// ---------- reports ----------
let reportKind = "readiness";
const reportsList = $("reports-list");
const generateBtn = $("generate");
const pushToggle = $("push-toggle");
const pushStatus = $("push-status");
const actionForm = $("action-form");
const actionTitle = $("action-title");
const actionDue = $("action-due");
const actionsList = $("actions-list");
const actionStatus = $("action-status");
const importActions = $("import-actions");
let pushPublicKey = null;
let serviceWorkerReady = null;
let cachedActions = [];

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function setActionStatus(text) {
  if (actionStatus) actionStatus.textContent = text || "";
}

document.querySelectorAll(".segmented button").forEach((b) =>
  b.addEventListener("click", () => {
    reportKind = b.dataset.kind;
    document.querySelectorAll(".segmented button").forEach((x) =>
      x.classList.toggle("active", x === b)
    );
    loadReports();
  })
);

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function fmtDue(iso) {
  if (!iso) return "";
  return new Date(iso + "T00:00:00").toLocaleDateString([], { month: "short", day: "numeric" });
}

function renderActions(actions) {
  if (!actionsList) return;
  cachedActions = actions || [];
  const open = cachedActions.filter((a) => a.status !== "done");
  const done = cachedActions.filter((a) => a.status === "done").slice(0, 5);
  if (!open.length && !done.length) {
    actionsList.innerHTML = `<div class="action-empty">No open actions.</div>`;
    return;
  }
  const row = (a) => `
    <div class="action-row ${a.status === "done" ? "done" : ""}" data-id="${a.id}">
      <label>
        <input type="checkbox" data-action-toggle="${a.id}" ${a.status === "done" ? "checked" : ""} />
        <span>${esc(a.title)}</span>
      </label>
      <div class="action-meta">
        ${a.due_date ? `<span>${fmtDue(a.due_date)}</span>` : ""}
        <button type="button" aria-label="Delete action" data-action-delete="${a.id}">×</button>
      </div>
    </div>`;
  actionsList.innerHTML = [
    open.map(row).join(""),
    done.length ? `<div class="actions-done-label">Done</div>${done.map(row).join("")}` : "",
  ].join("");

  actionsList.querySelectorAll("[data-action-toggle]").forEach((input) => {
    input.addEventListener("change", async () => {
      const id = input.dataset.actionToggle;
      await updateAction(id, { status: input.checked ? "done" : "open" });
    });
  });
  actionsList.querySelectorAll("[data-action-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      await deleteAction(button.dataset.actionDelete);
    });
  });
}

async function loadActions() {
  if (!actionsList) return;
  try {
    const resp = await fetch("/api/actions?limit=100");
    if (resp.status === 401) { location.href = "/login"; return; }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderActions(data.actions);
  } catch (err) {
    setActionStatus(`Actions failed: ${err.message}`);
  }
}

async function createAction(payload) {
  const resp = await fetch("/api/actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (resp.status === 401) { location.href = "/login"; return null; }
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function updateAction(id, payload) {
  try {
    const resp = await fetch(`/api/actions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (resp.status === 401) { location.href = "/login"; return; }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadActions();
  } catch (err) {
    setActionStatus(`Update failed: ${err.message}`);
  }
}

async function deleteAction(id) {
  try {
    const resp = await fetch(`/api/actions/${id}`, { method: "DELETE" });
    if (resp.status === 401) { location.href = "/login"; return; }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadActions();
  } catch (err) {
    setActionStatus(`Delete failed: ${err.message}`);
  }
}

function extractReportActions(markdown) {
  const lines = (markdown || "").split(/\r?\n/);
  const out = [];
  let capture = false;
  for (const line of lines) {
    const clean = line.trim();
    if (/^#{1,6}\s+/.test(clean)) {
      capture = /action|next|plan|week/i.test(clean);
      continue;
    }
    if (!capture) continue;
    const item = clean.match(/^(?:[-*]|\d+[.)])\s+(.*)$/);
    if (item && item[1]) out.push(item[1].replace(/\*\*/g, "").trim());
  }
  if (!out.length) {
    for (const line of lines) {
      const item = line.trim().match(/^(?:[-*]|\d+[.)])\s+(.*)$/);
      if (item && item[1]) out.push(item[1].replace(/\*\*/g, "").trim());
    }
  }
  return [...new Set(out.map((x) => x.replace(/\.$/, "").trim()).filter(Boolean))].slice(0, 6);
}

if (actionForm) {
  actionForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = actionTitle.value.trim();
    if (!title) return;
    const label = actionForm.querySelector("button").textContent;
    actionForm.querySelector("button").disabled = true;
    try {
      await createAction({ title, due_date: actionDue.value || null });
      actionTitle.value = "";
      actionDue.value = "";
      setActionStatus("");
      await loadActions();
    } catch (err) {
      setActionStatus(`Add failed: ${err.message}`);
    } finally {
      actionForm.querySelector("button").disabled = false;
      actionForm.querySelector("button").textContent = label;
    }
  });
}

if (importActions) {
  importActions.addEventListener("click", async () => {
    importActions.disabled = true;
    const label = importActions.textContent;
    importActions.textContent = "Adding…";
    try {
      const resp = await fetch("/api/reports?kind=weekly&limit=1");
      if (resp.status === 401) { location.href = "/login"; return; }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const report = data.reports && data.reports[0];
      const items = extractReportActions(report && report.content);
      const existing = new Set(cachedActions.map((a) => a.title.toLowerCase()));
      const fresh = items.filter((item) => !existing.has(item.toLowerCase()));
      for (const title of fresh) await createAction({ title, source_report_id: report.id });
      setActionStatus(fresh.length ? `Added ${fresh.length} actions` : "No new actions found");
      await loadActions();
    } catch (err) {
      setActionStatus(`Import failed: ${err.message}`);
    } finally {
      importActions.disabled = false;
      importActions.textContent = label;
    }
  });
}

function renderReports(reports) {
  if (!reports.length) {
    reportsList.innerHTML = `<div class="empty">No ${reportKind} reports yet. Generate one above.</div>`;
    return;
  }
  reportsList.innerHTML = "";
  reports.forEach((r, i) => {
    const el = document.createElement("details");
    el.className = "report";
    if (i === 0) el.open = true;
    const title = reportKind === "weekly" ? "Weekly review" : "Daily readiness";
    el.innerHTML =
      `<summary>${title} <span class="date">· ${fmtDate(r.created_at)}</span></summary>` +
      `<div class="body">${marked.parse(r.content || "")}</div>`;
    reportsList.appendChild(el);
  });
}

async function loadReports() {
  const resp = await fetch(`/api/reports?kind=${reportKind}&limit=20`);
  if (resp.status === 401) { location.href = "/login"; return; }
  const d = await resp.json();
  renderReports(d.reports);
}

generateBtn.addEventListener("click", async () => {
  generateBtn.disabled = true;
  const label = generateBtn.textContent;
  generateBtn.textContent = "Generating… (this can take a minute)";
  try {
    const resp = await fetch("/api/reports/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: reportKind }),
    });
    if (resp.status === 401) { location.href = "/login"; return; }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadReports();
  } catch (err) {
    alert(`Failed to generate: ${err.message}`);
  } finally {
    generateBtn.disabled = false;
    generateBtn.textContent = label;
  }
});

function pushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function setPushStatus(text) {
  pushStatus.textContent = text;
}

function urlBase64ToUint8Array(value) {
  const padding = "=".repeat((4 - value.length % 4) % 4);
  const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
  return output;
}

function ensureServiceWorker() {
  if (!("serviceWorker" in navigator)) return null;
  if (!serviceWorkerReady) {
    serviceWorkerReady = navigator.serviceWorker
      .register("sw.js")
      .then(() => navigator.serviceWorker.ready);
  }
  return serviceWorkerReady;
}

async function updatePushUi() {
  if (!pushPublicKey || !pushSupported()) {
    pushToggle.hidden = true;
    setPushStatus("");
    return;
  }

  pushToggle.hidden = false;
  pushToggle.disabled = false;
  if (Notification.permission === "denied") {
    pushToggle.textContent = "Notifications blocked";
    pushToggle.disabled = true;
    setPushStatus("Notifications are blocked in browser settings.");
    return;
  }

  const registration = await ensureServiceWorker();
  const subscription = await registration.pushManager.getSubscription();
  pushToggle.textContent = subscription ? "Disable notifications" : "Enable notifications";
  setPushStatus(subscription ? "Notifications enabled" : "");
}

async function subscribeToPush() {
  const registration = await ensureServiceWorker();
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    await updatePushUi();
    return;
  }

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(pushPublicKey),
  });
  const resp = await fetch("/api/push/subscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subscription.toJSON()),
  });
  if (resp.status === 401) { location.href = "/login"; return; }
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  await updatePushUi();
}

async function unsubscribeFromPush() {
  const registration = await ensureServiceWorker();
  const subscription = await registration.pushManager.getSubscription();
  if (!subscription) {
    await updatePushUi();
    return;
  }

  await fetch("/api/push/unsubscribe", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  });
  await subscription.unsubscribe();
  await updatePushUi();
}

async function initPushNotifications() {
  if (!pushSupported()) return;

  try {
    const resp = await fetch("/api/push/config");
    if (resp.status === 401) { location.href = "/login"; return; }
    const config = await resp.json();
    if (!config.enabled || !config.public_key) return;
    pushPublicKey = config.public_key;
    await updatePushUi();
  } catch {
    setPushStatus("");
  }
}

pushToggle.addEventListener("click", async () => {
  pushToggle.disabled = true;
  const label = pushToggle.textContent;
  pushToggle.textContent = "Working...";
  setPushStatus("");
  try {
    const registration = await ensureServiceWorker();
    const subscription = await registration.pushManager.getSubscription();
    if (subscription) {
      await unsubscribeFromPush();
    } else {
      await subscribeToPush();
    }
  } catch (err) {
    pushToggle.textContent = label;
    pushToggle.disabled = false;
    setPushStatus(`Notifications failed: ${err.message}`);
  }
});

// ---------- boot ----------
showEmptyState();
const initialView = VIEWS.has(location.hash.slice(1)) ? location.hash.slice(1) : "chat";
switchView(initialView);
syncData({ silent: true });
initPushNotifications();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => ensureServiceWorker());
}
