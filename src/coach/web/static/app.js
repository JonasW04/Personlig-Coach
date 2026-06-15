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
let statsLoaded = false;
let syncPromise = null;

function switchView(view) {
  currentView = view;
  for (const s of document.querySelectorAll(".view")) s.hidden = s.id !== `view-${view}`;
  for (const b of document.querySelectorAll("#tabbar button")) {
    b.classList.toggle("active", b.dataset.view === view);
  }
  $("title").textContent = TITLES[view];
  if (view === "stats" && !statsLoaded) loadStats();
  if (view === "reports") loadReports();
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
    el.textContent = "Ask about your training, recovery, or progress.";
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

// ---------- stats ----------
const GRID = "#272d39";
const MUTED = "#9aa3b2";
const ACCENT = "#4f8cff";
const PANEL = "#171a21";
const TEXT = "#e7eaf0";
const STATS_WINDOW_WEEKS = 12;
const charts = {};
const syncButton = $("sync-data");
let statsMetaText = "Loading stats...";
let syncStatusText = "";

function chartBase() {
  Chart.defaults.color = MUTED;
  Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  Chart.defaults.borderColor = GRID;
}
function axes(extra = {}) {
  return {
    x: {
      grid: { display: false },
      border: { color: GRID },
      ticks: { color: MUTED, maxRotation: 0, autoSkip: true },
    },
    y: {
      grid: { color: GRID },
      border: { color: GRID },
      ticks: { color: MUTED },
      ...extra,
    },
  };
}
function chartOptions({ legend = false, y = {} } = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        display: legend,
        labels: { color: MUTED, boxWidth: 10, boxHeight: 10, usePointStyle: true },
      },
      tooltip: {
        backgroundColor: PANEL,
        borderColor: GRID,
        borderWidth: 1,
        titleColor: TEXT,
        bodyColor: TEXT,
        displayColors: true,
      },
    },
    scales: axes(y),
  };
}
function draw(key, cfg) {
  if (charts[key]) charts[key].destroy();
  charts[key] = new Chart($(`chart-${key}`), cfg);
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}
function formatNumber(value, options = {}) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString(undefined, options);
}
function formatUnit(value, unit, options = {}) {
  const formatted = formatNumber(value, options);
  return formatted === "--" ? formatted : `${formatted} ${unit}`;
}
function fmtShortDate(iso) {
  if (!iso) return "";
  return new Date(`${iso}T00:00:00`).toLocaleDateString([], { month: "short", day: "numeric" });
}
function card(value, label, meta, tone = "") {
  const toneClass = tone ? ` card-${tone}` : "";
  return (
    `<article class="card${toneClass}">` +
    `<div class="label">${escapeHtml(label)}</div>` +
    `<div class="value">${escapeHtml(value)}</div>` +
    `<div class="meta">${escapeHtml(meta)}</div>` +
    `</article>`
  );
}
function updateStatsMeta() {
  const text = [statsMetaText, syncStatusText].filter(Boolean).join(" | ");
  $("stats-meta").textContent = text || "Waiting for synced data";
}
function renderStatsMeta(summary, hasData) {
  const parts = [];
  if (summary.latest_weigh_in) parts.push(`Last weigh-in ${fmtShortDate(summary.latest_weigh_in)}`);
  if (hasData) parts.push(`${STATS_WINDOW_WEEKS} weeks synced`);
  statsMetaText = parts.join(" | ") || "Waiting for synced data";
  updateStatsMeta();
}
function setSyncStatus(text) {
  syncStatusText = text;
  updateStatsMeta();
}
function syncSummary(data) {
  if (data.running) return data.message || "Sync already running.";
  const results = data.results || [];
  const synced = results.filter((r) => r.status === "synced");
  if (!synced.length) return "Sync complete";
  return `Updated ${synced.map((r) => r.source).join(", ")}`;
}
async function syncData({ silent = false } = {}) {
  if (syncPromise) return syncPromise;

  const label = syncButton.textContent;
  syncButton.disabled = true;
  syncButton.textContent = "Syncing...";
  setSyncStatus(silent ? "Updating in background..." : "Syncing data...");

  syncPromise = (async () => {
    try {
      const resp = await fetch("/api/sync", { method: "POST" });
      if (resp.status === 401) { location.href = "/login"; return; }
      const data = await resp.json();
      if (!resp.ok && resp.status !== 202) throw new Error(data.detail || `HTTP ${resp.status}`);

      setSyncStatus(syncSummary(data));
      if (resp.status !== 202 && currentView === "stats") await loadStats();
    } catch (err) {
      if (currentView === "stats" || !silent) {
        setSyncStatus(`Sync failed: ${err.message}`);
      } else {
        setSyncStatus("");
      }
    } finally {
      syncButton.disabled = false;
      syncButton.textContent = label;
      syncPromise = null;
    }
  })();

  return syncPromise;
}

async function loadStats() {
  const resp = await fetch(`/api/stats?weeks=${STATS_WINDOW_WEEKS}`);
  if (resp.status === 401) { location.href = "/login"; return; }
  const d = await resp.json();
  statsLoaded = true;
  chartBase();

  const s = d.summary || {};
  const body = d.body || [];
  const strengthWeekly = d.strength_weekly || [];
  const cardioWeekly = d.cardio_weekly || [];
  const hasData = body.length || strengthWeekly.length || cardioWeekly.length;
  renderStatsMeta(s, hasData);

  $("summary-cards").innerHTML = [
    card(
      s.latest_weight_kg != null ? `${formatNumber(s.latest_weight_kg, { maximumFractionDigits: 1 })} kg` : "--",
      "Latest weight",
      s.latest_weigh_in ? `Logged ${fmtShortDate(s.latest_weigh_in)}` : "No weigh-in yet",
      "primary"
    ),
    card(
      s.latest_fat_pct != null ? `${formatNumber(s.latest_fat_pct, { maximumFractionDigits: 1 })}%` : "--",
      "Body fat",
      "Current estimate",
      "amber"
    ),
    card(
      formatNumber(s.training_days_7d),
      "Training days",
      "Past 7 days",
      "green"
    ),
    card(
      formatUnit(s.cardio_km_7d, "km", { maximumFractionDigits: 1 }),
      "Cardio",
      "Past 7 days",
      "green"
    ),
    card(
      formatUnit(s.tonnage_7d_kg, "kg"),
      "Tonnage",
      "Past 7 days",
      "primary"
    ),
    card(
      formatNumber(s.lift_sessions_7d),
      "Lift sessions",
      "Past 7 days"
    ),
  ].join("");

  $("stats-empty").hidden = !!hasData;

  draw("weight", {
    type: "line",
    data: {
      labels: body.map((r) => r.date),
      datasets: [{
        data: body.map((r) => r.weight_kg),
        borderColor: ACCENT,
        backgroundColor: "rgba(79, 140, 255, 0.14)",
        tension: 0.3,
        spanGaps: true,
        pointRadius: 0,
        pointHoverRadius: 4,
        fill: true,
      }],
    },
    options: chartOptions(),
  });

  draw("body", {
    type: "line",
    data: {
      labels: body.map((r) => r.date),
      datasets: [
        {
          label: "Muscle",
          data: body.map((r) => r.muscle_mass_kg),
          borderColor: "#46c98b",
          backgroundColor: "transparent",
          tension: 0.3,
          spanGaps: true,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
        {
          label: "Fat",
          data: body.map((r) => r.fat_mass_kg),
          borderColor: "#e0a23b",
          backgroundColor: "transparent",
          tension: 0.3,
          spanGaps: true,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
      ],
    },
    options: chartOptions({ legend: true }),
  });

  draw("tonnage", {
    type: "bar",
    data: {
      labels: strengthWeekly.map((r) => r.week),
      datasets: [{
        data: strengthWeekly.map((r) => r.tonnage_kg),
        backgroundColor: ACCENT,
        borderRadius: 5,
        barPercentage: 0.72,
        categoryPercentage: 0.74,
      }],
    },
    options: chartOptions({ y: { beginAtZero: true } }),
  });

  draw("cardio", {
    type: "bar",
    data: {
      labels: cardioWeekly.map((r) => r.week),
      datasets: [{
        data: cardioWeekly.map((r) => r.distance_km),
        backgroundColor: "#46c98b",
        borderRadius: 5,
        barPercentage: 0.72,
        categoryPercentage: 0.74,
      }],
    },
    options: chartOptions({ y: { beginAtZero: true } }),
  });
}

syncButton.addEventListener("click", () => syncData());

// ---------- reports ----------
let reportKind = "readiness";
const reportsList = $("reports-list");
const generateBtn = $("generate");
const pushToggle = $("push-toggle");
const pushStatus = $("push-status");
let pushPublicKey = null;
let serviceWorkerReady = null;

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
