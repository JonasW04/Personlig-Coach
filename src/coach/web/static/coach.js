// App core: nav chrome, router, interactions, live wiring (chat + sync + reviews).
(() => {
  const S = window.SCREENS, I = window.ICONS, $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // ----- views & navigation model
  const VIEWS = {
    today: { tab: "today", render: S.today },
    plan: { tab: "plan", sub: "plan", render: S.plan },
    builder: { tab: "plan", sub: "plan", render: S.builder },
    blocks: { tab: "plan", sub: "plan", render: S.blocks },
    actual: { tab: "activity", render: S.actual, after: wireActual },
    goals: { tab: "health", sub: "health", render: S.goals },
    rules: { tab: "health", sub: "health", render: S.rules },
    memory: { tab: "chat", sub: "settings", render: S.memory },
    notifications: { tab: null, sub: "settings", render: S.notifications },
    reviews: { tab: "reviews", render: renderReviews, after: loadReviews },
    chat: { tab: "chat", render: S.chat, after: wireChat },
  };
  const TABS = [
    ["today", "Today", "sun"], ["plan", "Plan", "calendar"], ["activity", "Activity", "activity"],
    ["health", "Health", "heart"], ["reviews", "Reviews", "file"], ["chat", "Chat", "message"],
  ];
  const TAB_DEFAULT = { today: "today", plan: "plan", activity: "actual", health: "goals", reviews: "reviews", chat: "chat" };
  const SUBNAV = {
    plan: [["plan", "Week"], ["builder", "Workout"], ["blocks", "Blocks"]],
    health: [["goals", "Body Mode"], ["rules", "Recovery Rules"]],
    settings: [["notifications", "Notifications"], ["rules", "Recovery Rules"], ["memory", "Coach Memory"]],
  };

  let current = "today";

  function renderAppbar() {
    const tabs = TABS.map(([k, label, icon]) =>
      `<button data-action="tab" data-tab="${k}" class="${VIEWS[current].tab === k ? "active" : ""}">${I[icon](17)} ${label}</button>`).join("");
    $("#appbar").innerHTML = `
      <div class="brand">
        <div class="logo">C</div>
        <h1 class="title">Coach</h1>
      </div>
      <div class="toptabs">${tabs}</div>
      <div class="appbar-actions">
        <button class="iconbtn" data-action="tab" data-tab="reviews" title="Reviews">${I.file(19)}</button>
        <button class="iconbtn" data-action="settings" title="Settings">${I.gear(19)}</button>
      </div>`;
  }

  function renderTabbar() {
    $("#tabbar").innerHTML = TABS.map(([k, label, icon]) =>
      `<button data-action="tab" data-tab="${k}" class="${VIEWS[current].tab === k ? "active" : ""}">${I[icon](21)}<span>${label}</span></button>`).join("");
  }

  function subnavHtml(group, view) {
    return `<div class="segmented" style="margin-bottom:16px">${SUBNAV[group].map(([v, label]) =>
      `<button class="${v === view ? "active" : ""}" data-action="nav" data-view="${v}">${esc(label)}</button>`).join("")}</div>`;
  }

  function nav(view) {
    if (!VIEWS[view]) return;
    current = view;
    const cfg = VIEWS[view];
    document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
    const el = $("#screen-" + view);
    let html = cfg.render();
    if (cfg.sub) {
      // inject subnav right after the screen-inner header area
      html = html.replace('<div class="screen-inner">', `<div class="screen-inner">${subnavHtml(cfg.sub, view)}`);
    }
    el.innerHTML = html;
    el.classList.add("active");
    $("#scroll").scrollTop = 0;
    renderAppbar();
    renderTabbar();
    if (cfg.after) cfg.after(el);
  }

  // ----- global delegated actions
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-action]");
    if (!t) return;
    const a = t.dataset.action;
    switch (a) {
      case "tab": return nav(TAB_DEFAULT[t.dataset.tab] || t.dataset.tab);
      case "nav": return nav(t.dataset.view);
      case "settings": return nav("notifications");
      case "back": return nav(VIEWS[current].tab ? TAB_DEFAULT[VIEWS[current].tab] : "today");
      case "view-workout": return nav("builder");
      case "open-hevy": return openExternal("https://hevy.com/", "Opening Hevy…");
      case "open-garmin": return openExternal("https://connect.garmin.com/", "Opening Garmin Connect…");
      case "copy-workout": return copyWorkout();
      case "sync": return runSync();
      case "replan-today": return toast("Re-planning today…");
      case "regenerate-week": return toast("Regenerating week…");
      case "new-block": return toast("New block — coming soon");
      case "swap-exercise": return toast("Pick a replacement exercise");
      case "open-day": return nav("actual");
      case "nudge-action": return toast(t.textContent.trim());
      case "toggle-rule": return toggleRule(t);
      case "toggle-pref": return togglePref(t);
      case "set-mode": return setMode(t);
      case "add-rule": return toast("Add a rule — coming soon");
      case "add-chip": return toast("Add a memory — tell Coach in chat");
      case "remove-chip": return t.closest(".chip")?.remove();
    }
  });

  // ----- interactions
  function toggleRule(btn) {
    const i = +btn.dataset.idx;
    STATE.recoveryRules[i].enabled = !STATE.recoveryRules[i].enabled;
    btn.classList.toggle("on", STATE.recoveryRules[i].enabled);
  }
  function togglePref(btn) {
    const i = +btn.dataset.idx;
    STATE.notificationPrefs[i].enabled = !STATE.notificationPrefs[i].enabled;
    btn.classList.toggle("on", STATE.notificationPrefs[i].enabled);
  }
  function setMode(btn) {
    STATE.bodyMode.mode = btn.dataset.mode;
    nav("goals");
  }

  function wireActual(root) {
    const fill = (n) => { const d = $("#pa-detail", root); if (d) d.innerHTML = S.paDetailHtml(n); };
    fill(STATE.planVsActual.selectedDay);
    root.querySelectorAll("[data-day]").forEach((cell) => {
      if (+cell.dataset.day === STATE.planVsActual.selectedDay && cell.classList.contains("calcell") && !cell.classList.contains("today")) {
        cell.style.outline = "2px solid #eef1f6"; cell.style.outlineOffset = "2px";
      }
    });
    root.addEventListener("click", (e) => {
      const cell = e.target.closest("[data-day]");
      if (!cell) return;
      const grid = cell.closest("[data-cal-grid]");
      if (grid) grid.querySelectorAll("[data-day]").forEach((c) => { c.style.outline = "none"; c.style.outlineOffset = "0"; });
      cell.style.outline = "2px solid #eef1f6"; cell.style.outlineOffset = "2px";
      STATE.planVsActual.selectedDay = +cell.dataset.day;
      fill(+cell.dataset.day);
    });
  }

  // ----- external links (deep-link targets; confirm-free, just opens a tab)
  function openExternal(url, msg) { toast(msg); window.open(url, "_blank", "noopener"); }
  function copyWorkout() {
    const b = STATE.builder;
    const text = `${b.title}\n` + b.exercises.map((e) => `${e.name} — ${e.scheme || ""}`).join("\n");
    navigator.clipboard?.writeText(text).then(() => toast("Workout copied")).catch(() => toast("Copy failed"));
  }

  // ----- live sync
  let syncing = false;
  async function runSync() {
    if (syncing) return toast("Sync already running");
    syncing = true; toast("Syncing latest…");
    try {
      const r = await fetch("/api/sync", { method: "POST" });
      const j = await r.json();
      toast(j.running ? "Sync already running" : "Sync complete");
    } catch { toast("Sync failed"); }
    finally { syncing = false; }
  }

  // ----- toast
  let toastT;
  function toast(msg) {
    const el = $("#toast"); el.textContent = msg; el.classList.add("show");
    clearTimeout(toastT); toastT = setTimeout(() => el.classList.remove("show"), 1900);
  }

  // ----- Reviews (live /api/reports + generate)
  let reviewKind = "readiness";
  function renderReviews() {
    return `<div class="screen-inner">
      <div class="sectionhead"><div><p class="eyebrow">Reviews</p><h2 class="screen-title">Coach reports</h2></div></div>
      <div class="segmented" style="margin-bottom:14px">
        <button class="${reviewKind === "readiness" ? "active" : ""}" data-action="rev-kind" data-kind="readiness">Daily readiness</button>
        <button class="${reviewKind === "weekly" ? "active" : ""}" data-action="rev-kind" data-kind="weekly">Weekly review</button>
      </div>
      <div class="row" style="margin-bottom:14px"><button class="btn btn-primary" data-action="rev-generate">Generate now</button></div>
      <div id="reviews-list" class="stack"><div class="muted">Loading…</div></div>
    </div>`;
  }
  async function loadReviews(root) {
    root.addEventListener("click", async (e) => {
      const t = e.target.closest("[data-action]");
      if (!t) return;
      if (t.dataset.action === "rev-kind") { reviewKind = t.dataset.kind; nav("reviews"); }
      if (t.dataset.action === "rev-generate") {
        toast("Generating…");
        try { await fetch("/api/reports/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: reviewKind }) }); nav("reviews"); }
        catch { toast("Generation failed"); }
      }
    });
    try {
      const r = await fetch(`/api/reports?kind=${reviewKind}&limit=20`);
      const j = await r.json();
      const list = $("#reviews-list", root);
      if (!j.reports || !j.reports.length) { list.innerHTML = `<div class="card muted">No ${reviewKind} reports yet. Generate one above.</div>`; return; }
      list.innerHTML = j.reports.map((rep) => {
        const dt = rep.created_at ? new Date(rep.created_at).toLocaleString() : "";
        const body = window.marked ? marked.parse(rep.content || "") : esc(rep.content || "");
        return `<div class="card"><p class="label-mono" style="margin-bottom:8px">${esc(dt)}</p><div class="sec" style="font-size:13px;line-height:1.55">${body}</div></div>`;
      }).join("");
    } catch { const list = $("#reviews-list", root); if (list) list.innerHTML = `<div class="card muted">Could not load reports.</div>`; }
  }

  // ----- Chat (live /api/chat streaming ndjson)
  function chatSession() {
    let id = localStorage.getItem("coach.sid");
    if (!id) { id = "web-" + Math.random().toString(36).slice(2, 10); localStorage.setItem("coach.sid", id); }
    return id;
  }
  function wireChat(root) {
    const msgs = $("#chat-msgs", root), form = $("#composer", root), input = $("#chat-input", root);
    const sid = chatSession();
    const add = (role, text) => { const d = document.createElement("div"); d.className = "msg " + role; d.innerHTML = role === "assistant" && window.marked ? marked.parse(text) : esc(text); msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight; return d; };
    // load history
    fetch(`/api/chats/${sid}/messages`).then((r) => r.json()).then((j) => {
      (j.messages || []).forEach((m) => add(m.role, m.content));
      if (!j.messages || !j.messages.length) add("assistant", "Morning. Ask me anything about today's plan, your recovery, or this week.");
    }).catch(() => add("assistant", "Morning. Ask me anything about today's plan, your recovery, or this week."));

    input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim(); if (!text) return;
      input.value = ""; input.style.height = "auto";
      add("user", text);
      const out = add("assistant", "");
      let acc = "";
      try {
        const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: text, session_id: sid }) });
        const reader = r.body.getReader(), dec = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read(); if (done) break;
          buf += dec.decode(value, { stream: true });
          let nl;
          while ((nl = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
            if (!line) continue;
            const ev = JSON.parse(line);
            if (ev.type === "text") { acc += ev.text; out.innerHTML = window.marked ? marked.parse(acc) : esc(acc); }
            else if (ev.type === "step") { out.insertAdjacentHTML("beforebegin", `<div class="chat-step">${esc(ev.label)}</div>`); }
            msgs.scrollTop = msgs.scrollHeight;
          }
        }
      } catch { out.textContent = "Connection error. Try again."; }
    });
  }

  // boot
  renderAppbar(); renderTabbar(); nav("today");
})();
