// ---------- session id (per device) ----------
let sessionId = localStorage.getItem("coach_session");
if (!sessionId) {
  sessionId = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now());
  localStorage.setItem("coach_session", sessionId);
}

const $ = (id) => document.getElementById(id);

// ---------- tab navigation ----------
const TITLES = { chat: "Coach", stats: "Dashboard", reports: "Reviews" };
let currentView = "chat";
let statsLoaded = false;

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
const charts = {};

function chartBase() {
  Chart.defaults.color = MUTED;
  Chart.defaults.font.family = "-apple-system, system-ui, sans-serif";
}
function axes(extra = {}) {
  return {
    x: { grid: { color: GRID }, ticks: { maxRotation: 0, autoSkip: true } },
    y: { grid: { color: GRID }, ...extra },
  };
}
function draw(key, cfg) {
  if (charts[key]) charts[key].destroy();
  charts[key] = new Chart($(`chart-${key}`), cfg);
}
function card(value, label) {
  return `<div class="card"><div class="value">${value}</div><div class="label">${label}</div></div>`;
}

async function loadStats() {
  const resp = await fetch("/api/stats?weeks=12");
  if (resp.status === 401) { location.href = "/login"; return; }
  const d = await resp.json();
  statsLoaded = true;
  chartBase();

  const s = d.summary;
  $("summary-cards").innerHTML =
    card(s.latest_weight_kg != null ? s.latest_weight_kg + " kg" : "—", "Latest weight") +
    card(s.latest_fat_pct != null ? s.latest_fat_pct + "%" : "—", "Body fat") +
    card(s.training_days_7d, "Training days (7d)") +
    card(s.cardio_km_7d + " km", "Cardio (7d)") +
    card(s.tonnage_7d_kg.toLocaleString(), "Tonnage 7d (kg)") +
    card(s.lift_sessions_7d, "Lift sessions (7d)");

  const hasData = d.body.length || d.strength_weekly.length || d.cardio_weekly.length;
  $("stats-empty").hidden = !!hasData;

  draw("weight", {
    type: "line",
    data: {
      labels: d.body.map((r) => r.date),
      datasets: [{ data: d.body.map((r) => r.weight_kg), borderColor: ACCENT,
        backgroundColor: "transparent", tension: 0.3, spanGaps: true, pointRadius: 0 }],
    },
    options: { plugins: { legend: { display: false } }, scales: axes() },
  });

  draw("body", {
    type: "line",
    data: {
      labels: d.body.map((r) => r.date),
      datasets: [
        { label: "Muscle", data: d.body.map((r) => r.muscle_mass_kg), borderColor: "#46c98b",
          backgroundColor: "transparent", tension: 0.3, spanGaps: true, pointRadius: 0 },
        { label: "Fat", data: d.body.map((r) => r.fat_mass_kg), borderColor: "#e0a23b",
          backgroundColor: "transparent", tension: 0.3, spanGaps: true, pointRadius: 0 },
      ],
    },
    options: { plugins: { legend: { labels: { boxWidth: 12 } } }, scales: axes() },
  });

  draw("tonnage", {
    type: "bar",
    data: {
      labels: d.strength_weekly.map((r) => r.week),
      datasets: [{ data: d.strength_weekly.map((r) => r.tonnage_kg), backgroundColor: ACCENT }],
    },
    options: { plugins: { legend: { display: false } }, scales: axes({ beginAtZero: true }) },
  });

  draw("cardio", {
    type: "bar",
    data: {
      labels: d.cardio_weekly.map((r) => r.week),
      datasets: [{ data: d.cardio_weekly.map((r) => r.distance_km), backgroundColor: "#46c98b" }],
    },
    options: { plugins: { legend: { display: false } }, scales: axes({ beginAtZero: true }) },
  });
}

// ---------- reports ----------
let reportKind = "readiness";
const reportsList = $("reports-list");
const generateBtn = $("generate");

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

// ---------- boot ----------
showEmptyState();
switchView("chat");

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js"));
}
