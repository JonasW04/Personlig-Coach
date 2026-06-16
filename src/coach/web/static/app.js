// ---------- conversation id (active chat; doubles as SDK session id) ----------
const newId = () => (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
let sessionId = localStorage.getItem("coach_session");
if (!sessionId) {
  sessionId = newId();
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
  document.body.classList.remove("view-chat", "view-stats", "view-reports");
  document.body.classList.add(`view-${view}`);
  $("title").textContent = TITLES[view];
  if (view === "stats") loadStats();
  if (view === "reports") { loadFocus(); loadMemories(); loadPlan(); loadReadinessHero(); loadReports(); }
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

const QUICK_PROMPTS = ["How's my recovery?", "Plan my week", "Why am I so tired?", "Review last workout"];

function fmtClock(iso) {
  const d = iso ? new Date(iso) : new Date();
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function showEmptyState() {
  if (messages.children.length) return;
  const el = document.createElement("div");
  el.className = "empty";
  el.innerHTML =
    `<div class="empty-orb"><i></i><i></i><i></i></div>` +
    `<div><strong>Ask your coach</strong><div class="empty-sub">Questions about your training, recovery, or progress — grounded in your synced data.</div></div>` +
    `<div class="empty-chips">${QUICK_PROMPTS.map((p) => `<button type="button" class="chip-prompt">${esc(p)}</button>`).join("")}</div>`;
  messages.appendChild(el);
  el.querySelectorAll(".chip-prompt").forEach((chip) =>
    chip.addEventListener("click", () => {
      if (busy) return;
      sendMessage(chip.textContent);
    })
  );
}
function clearEmptyState() {
  const e = messages.querySelector(".empty");
  if (e) e.remove();
}

// One chat turn (user or coach), with a timestamp. Coach bodies render markdown.
function addTurn(role, text, iso) {
  clearEmptyState();
  const turn = document.createElement("div");
  turn.className = `turn ${role}`;
  const body = document.createElement("div");
  body.className = "msg";
  if (role === "coach") body.innerHTML = marked.parse(text || "");
  else body.textContent = text;
  const time = document.createElement("div");
  time.className = "msg-time";
  time.textContent = fmtClock(iso);
  turn.append(body, time);
  messages.appendChild(turn);
  messages.scrollTop = messages.scrollHeight;
  return body;
}

// The animated "coach working" card with live status steps.
function addWorkingCard() {
  clearEmptyState();
  const card = document.createElement("div");
  card.className = "working";
  card.innerHTML =
    `<div class="working-title"><div class="working-dot"></div><span>Working through your data</span></div>` +
    `<div class="working-steps"></div>`;
  messages.appendChild(card);
  messages.scrollTop = messages.scrollHeight;
  const stepsEl = card.querySelector(".working-steps");
  let active = null;
  return {
    card,
    addStep(label) {
      if (active) active.className = "wstep done";
      const row = document.createElement("div");
      row.className = "wstep active";
      row.innerHTML = `<div class="wstep-icon"></div><span class="wstep-label">${esc(label)}</span>`;
      stepsEl.appendChild(row);
      active = row;
      messages.scrollTop = messages.scrollHeight;
    },
    finish() {
      stepsEl.querySelectorAll(".wstep.active").forEach((r) => (r.className = "wstep done"));
      card.remove();
    },
  };
}

function autosize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 140) + "px";
}

async function sendMessage(text) {
  busy = true;
  send.disabled = true;
  addTurn("user", text);
  const working = addWorkingCard();
  let coachBody = null;
  let raw = "";
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
        if (evt.type === "step") {
          working.addStep(evt.label);
        } else if (evt.type === "text") {
          if (!coachBody) { working.finish(); coachBody = addTurn("coach", ""); }
          raw += evt.text;
          coachBody.innerHTML = marked.parse(raw);
          messages.scrollTop = messages.scrollHeight;
        }
      }
    }
  } catch (err) {
    if (!coachBody) { working.finish(); coachBody = addTurn("coach", ""); }
    raw += (raw ? "\n\n" : "") + `⚠️ ${err.message}`;
    coachBody.innerHTML = marked.parse(raw);
  } finally {
    working.finish();
    busy = false;
    send.disabled = false;
    input.focus();
    loadChatList();
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

// ---------- chat history drawer + multi-chat ----------
const drawer = $("chat-drawer");
const drawerScrim = $("drawer-scrim");
const chatHistory = $("chat-history");

function relTime(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  const wks = Math.round(days / 7);
  return `${wks}w ago`;
}

function openDrawer() {
  loadChatList();
  drawerScrim.hidden = false;
  requestAnimationFrame(() => { drawerScrim.classList.add("open"); drawer.classList.add("open"); });
  drawer.setAttribute("aria-hidden", "false");
}
function closeDrawer() {
  drawerScrim.classList.remove("open");
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  setTimeout(() => { drawerScrim.hidden = true; }, 240);
}

async function loadChatList() {
  if (!chatHistory) return;
  try {
    const resp = await fetch("/api/chats?limit=50");
    if (!resp.ok) return;
    const data = await resp.json();
    renderChatList(data.chats || []);
  } catch (_) { /* ignore */ }
}

function renderChatList(chats) {
  if (!chats.length) {
    chatHistory.innerHTML = `<div class="chat-hist-empty">No chats yet.</div>`;
    return;
  }
  chatHistory.innerHTML = "";
  chats.forEach((c) => {
    const item = document.createElement("div");
    item.className = "chat-hist-item" + (c.id === sessionId ? " active" : "");
    item.innerHTML =
      `<div class="chat-hist-main">` +
      `<div class="chat-hist-title">${esc(c.title || "New chat")}</div>` +
      `<div class="chat-hist-time">${esc(relTime(c.updated_at))}</div>` +
      `</div>` +
      `<button type="button" class="chat-hist-del" aria-label="Delete chat">×</button>`;
    item.querySelector(".chat-hist-main").addEventListener("click", () => openChat(c.id));
    item.querySelector(".chat-hist-del").addEventListener("click", (e) => {
      e.stopPropagation();
      deleteChat(c.id);
    });
    chatHistory.appendChild(item);
  });
}

async function openChat(id) {
  if (id !== sessionId) {
    sessionId = id;
    localStorage.setItem("coach_session", sessionId);
    await loadChatMessages(id);
  }
  closeDrawer();
}

async function loadChatMessages(id) {
  messages.innerHTML = "";
  try {
    const resp = await fetch(`/api/chats/${id}/messages`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const msgs = data.messages || [];
    if (!msgs.length) { showEmptyState(); return; }
    for (const m of msgs) {
      addTurn(m.role === "user" ? "user" : "coach", m.content, m.created_at);
    }
  } catch (_) {
    showEmptyState();
  }
}

function startNewChat() {
  sessionId = newId();
  localStorage.setItem("coach_session", sessionId);
  messages.innerHTML = "";
  showEmptyState();
  closeDrawer();
  switchView("chat");
  input.focus();
}

async function deleteChat(id) {
  try {
    const resp = await fetch(`/api/chats/${id}`, { method: "DELETE" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  } catch (_) { /* ignore */ }
  if (id === sessionId) startNewChat();
  loadChatList();
}

$("menu-toggle").addEventListener("click", openDrawer);
$("drawer-close").addEventListener("click", closeDrawer);
drawerScrim.addEventListener("click", closeDrawer);
$("new-chat").addEventListener("click", startNewChat);
$("drawer-new-chat").addEventListener("click", startNewChat);

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
const focusText = $("focus-text");
const focusEdit = $("focus-edit");
const focusForm = $("focus-form");
const focusInput = $("focus-input");
const focusCancel = $("focus-cancel");
const focusStatusEl = $("focus-status");
const readinessHero = $("readiness-hero");
const goalProgressEl = $("goal-progress");
let pushPublicKey = null;
let serviceWorkerReady = null;
let cachedActions = [];
let _focusRegenPoll = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function setActionStatus(text) {
  if (actionStatus) actionStatus.textContent = text || "";
}
function setFocusStatus(text) {
  if (focusStatusEl) focusStatusEl.textContent = text || "";
}

function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}
function fmtDue(iso) {
  if (!iso) return "";
  return new Date(iso + "T00:00:00").toLocaleDateString([], { month: "short", day: "numeric" });
}

// ---- focus / coaching goal ----

function renderFocusCard(profile) {
  if (!focusText) return;
  focusText.textContent = profile.focus_raw || "Not set";
  if (focusInput) focusInput.value = profile.focus_raw || "";
}

function startFocusRegenPoll() {
  if (_focusRegenPoll) return;
  setFocusStatus("Updating your coaching… regenerating reports (this takes a few minutes)");
  let _pollCount = 0;
  const MAX_POLLS = 60; // 15 min at 15 s each
  _focusRegenPoll = setInterval(async () => {
    _pollCount++;
    if (_pollCount > MAX_POLLS) {
      clearInterval(_focusRegenPoll);
      _focusRegenPoll = null;
      setFocusStatus("Report regeneration timed out — try refreshing the page.");
      return;
    }
    try {
      const resp = await fetch("/api/focus");
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.regenerating) {
        clearInterval(_focusRegenPoll);
        _focusRegenPoll = null;
        setFocusStatus("");
        // Reload everything so the new reports are visible
        loadReadinessHero();
        loadReports();
        loadPlan();
      }
    } catch (_) { /* ignore */ }
  }, 15000); // poll every 15 s — multi-agent generation takes several minutes
}

async function loadFocus() {
  try {
    const resp = await fetch("/api/focus");
    if (resp.status === 401) { location.href = "/login"; return; }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const profile = await resp.json();
    renderFocusCard(profile);
    if (profile.regenerating) startFocusRegenPoll();
  } catch (err) {
    setFocusStatus(`Could not load focus: ${err.message}`);
  }
}

if (focusEdit) {
  focusEdit.addEventListener("click", () => {
    focusForm.hidden = false;
    focusEdit.hidden = true;
    focusInput.focus();
  });
}
if (focusCancel) {
  focusCancel.addEventListener("click", () => {
    focusForm.hidden = true;
    focusEdit.hidden = false;
    setFocusStatus("");
  });
}
if (focusForm) {
  focusForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const raw = focusInput.value.trim();
    if (!raw) return;
    const btn = focusForm.querySelector("button[type='submit']");
    btn.disabled = true;
    btn.textContent = "Saving…";
    try {
      const resp = await fetch("/api/focus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ focus_raw: raw }),
      });
      if (resp.status === 401) { location.href = "/login"; return; }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const profile = await resp.json();
      renderFocusCard(profile);
      focusForm.hidden = true;
      focusEdit.hidden = false;
      if (profile.regenerating) startFocusRegenPoll();
    } catch (err) {
      setFocusStatus(`Save failed: ${err.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = "Save & update coaching";
    }
  });
}

// ---- readiness verdict hero ----

function parseVerdict(content) {
  const lines = (content || "").split(/\r?\n/);
  for (const line of lines) {
    const m = line.trim().match(/^verdict:\s*(.+)$/i);
    if (m) {
      const rest = m[1].replace(/\*\*/g, "").trim();
      const parts = rest.split(/\s*[—–-]{1,2}\s*/);
      return { verdict: parts[0].trim(), detail: parts.slice(1).join(" — ").trim() };
    }
  }
  return null;
}

function verdictLevel(v) {
  if (/rest/i.test(v)) return "rest";
  if (/easy|light|caution/i.test(v)) return "easy";
  return "train";
}

async function loadReadinessHero() {
  if (!readinessHero) return;
  try {
    const resp = await fetch("/api/reports?kind=readiness&limit=1");
    if (!resp.ok) { readinessHero.hidden = true; return; }
    const d = await resp.json();
    const r = d.reports && d.reports[0];
    if (!r) { readinessHero.hidden = true; return; }
    const v = parseVerdict(r.content);
    if (!v) { readinessHero.hidden = true; return; }
    const lvl = verdictLevel(v.verdict);
    readinessHero.className = `verdict-card verdict-${lvl}`;
    readinessHero.hidden = false;
    readinessHero.innerHTML =
      `<span class="verdict-badge">${esc(v.verdict)}</span>` +
      `<span class="verdict-detail">${esc(v.detail)}</span>` +
      `<span class="verdict-date">${fmtDate(r.created_at)}</span>`;
    readinessHero.onclick = () => {
      // switch to readiness tab in the archive
      reportKind = "readiness";
      document.querySelectorAll(".segmented button").forEach((b) => {
        b.classList.toggle("active", b.dataset.kind === "readiness");
      });
      loadReports();
      const block = document.querySelector(".reports-block");
      if (block) block.scrollIntoView({ behavior: "smooth" });
    };
  } catch (_) {
    readinessHero.hidden = true;
  }
}

// ---- weekly goal progress ----

const WEEKLY_METRICS = {
  weekly_strength_sessions: (s) => s.liftSessions,
  weekly_active_days: (s) => s.activeDays,
  weekly_cardio_distance: (s) => Math.round(s.km * 10) / 10,
  weekly_strength_volume: (s) => s.tonnage,
};

function fmtMetricVal(v, unit) {
  if (unit === "kg" && v >= 1000) return (v / 1000).toFixed(1) + "k";
  if (unit === "km") return v.toFixed(1);
  return Math.round(v).toString();
}

let _weekSummary = null;

async function getWeekSummary() {
  if (!window.CoachData) return null;
  await window.CoachData.ready;
  const { start, end } = window.CoachData.currentWeekRange();
  _weekSummary = window.CoachData.summarize(start, end);
  return _weekSummary;
}

function metricCurrent(metric) {
  if (!_weekSummary || !WEEKLY_METRICS[metric]) return null;
  return WEEKLY_METRICS[metric](_weekSummary);
}

async function renderGoalProgress() {
  if (!goalProgressEl) return;
  const sum = await getWeekSummary();
  if (!sum || !window.CoachData) { goalProgressEl.innerHTML = ""; return; }
  const goals = (window.CoachData.goals() || []).filter(
    (g) => WEEKLY_METRICS[g.key] && g.enabled && g.target_value != null
  );
  if (!goals.length) { goalProgressEl.innerHTML = ""; return; }
  goalProgressEl.innerHTML = goals.map((g) => {
    const cur = WEEKLY_METRICS[g.key](sum);
    const target = g.target_value;
    const pct = Math.max(0, Math.min(1, target ? cur / target : 0));
    const met = cur >= target;
    return `<div class="goal-prog${met ? " met" : ""}">
      <div class="goal-prog-top">
        <span class="goal-prog-label">${esc(g.label)}</span>
        <span class="goal-prog-val">${fmtMetricVal(cur, g.unit)} / ${fmtMetricVal(target, g.unit)} ${esc(g.unit)}</span>
      </div>
      <div class="goal-prog-bar"><span style="width:${(pct * 100).toFixed(1)}%"></span></div>
    </div>`;
  }).join("");
}

// ---- action items ----

function renderActions(actions) {
  if (!actionsList) return;
  cachedActions = actions || [];
  const open = cachedActions.filter((a) => a.status !== "done");
  const done = cachedActions.filter((a) => a.status === "done").slice(0, 5);
  if (!open.length && !done.length) {
    actionsList.innerHTML = `<div class="action-empty">No actions for this week yet.</div>`;
    return;
  }
  const progressChip = (a) => {
    if (!a.metric || !WEEKLY_METRICS[a.metric] || _weekSummary === null) return "";
    const cur = WEEKLY_METRICS[a.metric](_weekSummary);
    const target = a.target_value;
    if (target == null) return "";
    const met = cur >= target;
    const unit = (window.CoachData?.goals() || []).find((g) => g.key === a.metric)?.unit || "";
    return `<span class="action-chip${met ? " met" : ""}">${fmtMetricVal(cur, unit)}/${fmtMetricVal(target, unit)}</span>`;
  };
  const row = (a) => `
    <div class="action-row${a.status === "done" ? " done" : ""}${a.auto ? " auto" : ""}" data-id="${a.id}">
      <label>
        <input type="checkbox" data-action-toggle="${a.id}" ${a.status === "done" ? "checked" : ""} />
        <span>${esc(a.title)}${progressChip(a)}</span>
      </label>
      <div class="action-meta">
        ${a.due_date && !a.week_start ? `<span>${fmtDue(a.due_date)}</span>` : ""}
        <button type="button" aria-label="Delete action" data-action-delete="${a.id}">×</button>
      </div>
    </div>`;
  actionsList.innerHTML = [
    open.map(row).join(""),
    done.length ? `<div class="actions-done-label">Done</div>${done.map(row).join("")}` : "",
  ].join("");
  actionsList.querySelectorAll("[data-action-toggle]").forEach((input) => {
    input.addEventListener("change", async () => {
      await updateAction(input.dataset.actionToggle, { status: input.checked ? "done" : "open" });
    });
  });
  actionsList.querySelectorAll("[data-action-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      await deleteAction(button.dataset.actionDelete);
    });
  });
}

async function loadPlan() {
  // Fetch this-week's actions and goal progress in parallel
  await Promise.all([
    loadActions(),
    renderGoalProgress(),
  ]);
}

async function loadActions() {
  if (!actionsList) return;
  try {
    const resp = await fetch("/api/actions?week=current&limit=100");
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

if (actionForm) {
  actionForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = actionTitle.value.trim();
    if (!title) return;
    const btn = actionForm.querySelector("button[type='submit']");
    btn.disabled = true;
    try {
      await createAction({ title, due_date: actionDue.value || null });
      actionTitle.value = "";
      actionDue.value = "";
      setActionStatus("");
      await loadPlan();
    } catch (err) {
      setActionStatus(`Add failed: ${err.message}`);
    } finally {
      btn.disabled = false;
    }
  });
}

if (importActions) {
  importActions.addEventListener("click", async () => {
    importActions.disabled = true;
    const label = importActions.textContent;
    importActions.textContent = "Importing…";
    setActionStatus("");
    try {
      const resp = await fetch("/api/actions/import-latest", { method: "POST" });
      if (resp.status === 401) { location.href = "/login"; return; }
      if (resp.status === 404) { setActionStatus("No weekly review yet — generate one first."); return; }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setActionStatus(data.count ? `Added ${data.count} actions from latest review` : "No new actions found");
      await loadPlan();
    } catch (err) {
      setActionStatus(`Import failed: ${err.message}`);
    } finally {
      importActions.disabled = false;
      importActions.textContent = label;
    }
  });
}

// ---- report archive ----

document.querySelectorAll(".segmented button").forEach((b) =>
  b.addEventListener("click", () => {
    reportKind = b.dataset.kind;
    document.querySelectorAll(".segmented button").forEach((x) =>
      x.classList.toggle("active", x === b)
    );
    loadReports();
  })
);

function renderReports(reports) {
  if (!reports.length) {
    reportsList.innerHTML = `<div class="empty">No ${reportKind === "weekly" ? "weekly" : "daily readiness"} reports yet. Generate one below.</div>`;
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
    // Refresh hero and plan in case readiness/weekly was just generated
    if (reportKind === "readiness") loadReadinessHero();
    if (reportKind === "weekly") loadPlan();
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

// ---------- coach memory (Reviews tab) ----------
const memoryList = $("memory-list");
const memoryForm = $("memory-form");
const memoryInput = $("memory-input");
const memoryStatus = $("memory-status");

function setMemoryStatus(text) {
  if (memoryStatus) memoryStatus.textContent = text || "";
}

function renderMemories(items) {
  if (!memoryList) return;
  if (!items.length) {
    memoryList.innerHTML = `<div class="memory-empty">Nothing saved yet. Add a fact, or just tell your coach in chat.</div>`;
    return;
  }
  memoryList.innerHTML = "";
  items.forEach((m) => {
    const row = document.createElement("div");
    row.className = "memory-row" + (m.source === "manual" ? " manual" : "");
    row.innerHTML =
      `<div class="memory-text">${esc(m.content)}` +
      `<span class="memory-src">${m.source === "chat" ? "From chat" : "Added by you"} · ${esc(fmtDate(m.created_at))}</span></div>` +
      `<button type="button" class="memory-del" aria-label="Forget">×</button>`;
    row.querySelector(".memory-del").addEventListener("click", () => deleteMemory(m.id));
    memoryList.appendChild(row);
  });
}

async function loadMemories() {
  if (!memoryList) return;
  try {
    const resp = await fetch("/api/memories");
    if (resp.status === 401) { location.href = "/login"; return; }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    renderMemories(data.memories || []);
  } catch (err) {
    setMemoryStatus(`Could not load memory: ${err.message}`);
  }
}

async function deleteMemory(id) {
  try {
    const resp = await fetch(`/api/memories/${id}`, { method: "DELETE" });
    if (resp.status === 401) { location.href = "/login"; return; }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    await loadMemories();
  } catch (err) {
    setMemoryStatus(`Delete failed: ${err.message}`);
  }
}

if (memoryForm) {
  memoryForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const content = memoryInput.value.trim();
    if (!content) return;
    const btn = memoryForm.querySelector("button[type='submit']");
    btn.disabled = true;
    setMemoryStatus("");
    try {
      const resp = await fetch("/api/memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (resp.status === 401) { location.href = "/login"; return; }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      memoryInput.value = "";
      await loadMemories();
    } catch (err) {
      setMemoryStatus(`Save failed: ${err.message}`);
    } finally {
      btn.disabled = false;
    }
  });
}

// ---------- boot ----------
loadChatMessages(sessionId);
const initialView = VIEWS.has(location.hash.slice(1)) ? location.hash.slice(1) : "chat";
switchView(initialView);
syncData({ silent: true });
initPushNotifications();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => ensureServiceWorker());
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    window.location.reload();
  });
}
