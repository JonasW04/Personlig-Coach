// App core: nav chrome, router, interactions, live wiring (chat + sync + reviews).
(() => {
  const S = window.SCREENS, I = window.ICONS, $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const todayStaticJson = JSON.stringify(window.STATE.today);
  const weekPlanStaticJson = JSON.stringify(window.STATE.weekPlan);
  const rulesStaticJson = JSON.stringify(window.STATE.recoveryRules);
  const bodyModeStaticJson = JSON.stringify(window.STATE.bodyMode);
  const notificationPrefsStaticJson = JSON.stringify(window.STATE.notificationPrefs);
  const pushNotificationsStaticJson = JSON.stringify(window.STATE.pushNotifications);
  let memoryIds = {};
  let pushRegistration = null;

  // ----- views & navigation model
  const VIEWS = {
    today: { tab: "today", render: S.today, after: wireToday },
    plan: { tab: "plan", sub: "plan", render: S.plan, after: wirePlan },
    builder: { tab: "plan", sub: "plan", render: S.builder, after: wireBuilder },
    actual: { tab: "activity", render: S.actual, after: wireActual },
    goals: { tab: "health", sub: "health", render: S.goals, after: wireGoals },
    rules: { tab: "health", sub: "health", render: S.rules, after: wireRules },
    memory: { tab: "chat", sub: "settings", render: S.memory, after: wireMemory },
    notifications: { tab: null, sub: "settings", render: S.notifications, after: wireNotifications },
    reviews: { tab: "reviews", render: renderReviews, after: loadReviews, prerender: true },
    chat: { tab: "chat", render: S.chat, after: wireChat, prerender: true },
  };
  const TABS = [
    ["today", "Today", "sun"], ["plan", "Plan", "calendar"], ["activity", "Activity", "activity"],
    ["health", "Health", "heart"], ["reviews", "Reviews", "file"], ["chat", "Chat", "message"],
  ];
  const TAB_DEFAULT = { today: "today", plan: "plan", activity: "actual", health: "goals", reviews: "reviews", chat: "chat" };
  const SUBNAV = {
    plan: [["plan", "Week"], ["builder", "Workout"]],
    health: [["goals", "Body Mode"], ["rules", "Recovery Rules"]],
    settings: [["notifications", "Notifications"], ["rules", "Recovery Rules"], ["memory", "Coach Memory"]],
  };

  let current = "today";
  let requestedBuilderDate = null; // set when opening the workout view for a specific day

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
    let html;
    if (cfg.prerender) {
      // reviews/chat only patch sub-elements of their template in cfg.after, so
      // the template must be rendered up front.
      html = cfg.render();
      if (cfg.sub) html = html.replace('<div class="screen-inner">', `<div class="screen-inner">${subnavHtml(cfg.sub, view)}`);
    } else {
      // Self-loading views render their own Loading + content (and empty/error
      // states) in cfg.after. Show a neutral shell so a stale or empty STATE
      // never flashes fake data — or throws and leaves a blank screen.
      html = `<div class="screen-inner">${cfg.sub ? subnavHtml(cfg.sub, view) : ""}<div class="muted">Loading…</div></div>`;
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
      case "open-hevy": return openHevy();
      case "open-garmin": return openExternal("https://connect.garmin.com/modern/calendar", "Opening Garmin Connect…");
      case "schedule-garmin": return scheduleGarmin(t);
      case "copy-workout": return copyWorkout();
      case "sync": return runSync();
      case "rev-kind": reviewKind = t.dataset.kind; return nav("reviews");
      case "rev-generate": return generateReview();
      case "chat-new": return chatStartNew();
      case "chat-open": return chatOpen(t.dataset.cid);
      case "chat-delete": e.stopPropagation(); return chatDelete(t.dataset.cid);
      case "chat-toggle-history": return $("#chat-sidebar")?.classList.toggle("open");
      case "replan-today": return replanToday();
      case "regenerate-week": return regenerateWeek();
      case "open-day": {
        const pa = STATE.planVsActual;
        const day = pa && pa.days[pa.selectedDay];
        if (day && day.kind === "strength") { requestedBuilderDate = day.date; return nav("builder"); }
        return nav("plan");
      }
      case "nudge-action": return toast(t.textContent.trim());
      case "toggle-rule": return toggleRule(t);
      case "toggle-pref": return togglePref(t);
      case "toggle-push": return togglePush();
      case "set-mode": return setMode(t);
      case "add-rule": return openRuleModal();
      case "close-rule-modal": return closeRuleModal();
      case "add-chip": return addMemory(t);
      case "remove-chip": return removeMemory(t);
    }
  });

  // ----- interactions
  async function toggleRule(btn) {
    const i = +btn.dataset.idx;
    const rule = STATE.recoveryRules[i];
    if (!rule || rule.id == null) return toast("Could not update this rule");
    try {
      const response = await fetch(`/api/rules/${rule.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !rule.enabled }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      nav("rules");
    } catch {
      toast("Could not update rule");
    }
  }
  async function togglePref(btn) {
    const i = +btn.dataset.idx;
    const pref = STATE.notificationPrefs[i];
    if (!pref) return toast("Could not update preference");
    try {
      const response = await fetch("/api/notification-prefs", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: pref.key, enabled: !pref.enabled }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      nav("notifications");
    } catch {
      toast("Could not update preference");
    }
  }

  function pushSupported() {
    return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  }

  function vapidKey(value) {
    const padding = "=".repeat((4 - value.length % 4) % 4);
    const raw = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
  }

  async function ensurePushRegistration() {
    await navigator.serviceWorker.register("/sw.js");
    return navigator.serviceWorker.ready;
  }

  async function wireNotifications(root) {
    const render = () => {
      root.innerHTML = S.notifications().replace('<div class="screen-inner">', `<div class="screen-inner">${subnavHtml("settings", "notifications")}`);
    };
    STATE.notificationPrefs = JSON.parse(notificationPrefsStaticJson);
    STATE.pushNotifications = JSON.parse(pushNotificationsStaticJson);
    root.innerHTML = `<div class="screen-inner"><div class="muted">Loading…</div></div>`;
    const getJson = async (path) => {
      try {
        const response = await fetch(path);
        return response.ok ? await response.json() : null;
      } catch {
        return null;
      }
    };
    const [prefsData, config] = await Promise.all([
      getJson("/api/notification-prefs"),
      getJson("/api/push/config"),
    ]);
    const keys = ["dailyPlan", "recoveryAlerts", "planDrift", "weeklyReview", "quietHours"];
    if (Array.isArray(prefsData?.prefs) && keys.every((key, i) => prefsData.prefs[i]?.key === key)) {
      STATE.notificationPrefs = prefsData.prefs;
    }
    if (!config?.enabled) {
      STATE.pushNotifications.hint = "Web Push is not configured on this server.";
      return render();
    }
    if (!pushSupported()) {
      STATE.pushNotifications.hint = "Push is not supported in this browser.";
      return render();
    }
    if (Notification.permission === "denied") {
      STATE.pushNotifications.hint = "Notifications are blocked in browser settings.";
      return render();
    }
    try {
      pushRegistration = await ensurePushRegistration();
      const subscription = await pushRegistration.pushManager.getSubscription();
      STATE.pushNotifications = {
        available: true,
        subscribed: Boolean(subscription),
        publicKey: config.public_key,
        hint: subscription
          ? "This browser receives enabled Coach notifications."
          : "Enable notifications for this browser.",
      };
    } catch {
      STATE.pushNotifications.hint = "Could not initialize browser push.";
    }
    render();
  }

  async function togglePush() {
    const push = STATE.pushNotifications;
    if (!push.available || !push.publicKey) return;
    try {
      pushRegistration ||= await ensurePushRegistration();
      const existing = await pushRegistration.pushManager.getSubscription();
      if (existing) {
        const response = await fetch("/api/push/unsubscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: existing.endpoint }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await existing.unsubscribe();
      } else {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") throw new Error("Permission not granted");
        const subscription = await pushRegistration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: vapidKey(push.publicKey),
        });
        const response = await fetch("/api/push/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(subscription.toJSON()),
        });
        if (!response.ok) {
          await subscription.unsubscribe();
          throw new Error(`HTTP ${response.status}`);
        }
      }
      nav("notifications");
    } catch {
      toast("Could not update push notifications");
    }
  }
  async function setMode(btn) {
    const mode = btn.dataset.mode;
    if (!STATE.bodyMode.modes.some((item) => item.key === mode) || mode === STATE.bodyMode.mode) return;
    try {
      const response = await fetch("/api/body-mode", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      nav("goals");
    } catch {
      toast("Could not update body mode");
    }
  }

  async function wireRules(root) {
    const render = () => {
      root.innerHTML = S.rules().replace('<div class="screen-inner">', `<div class="screen-inner">${subnavHtml("health", "rules")}`);
    };
    const fallback = () => { STATE.recoveryRules = JSON.parse(rulesStaticJson); render(); };
    root.innerHTML = `<div class="screen-inner"><div class="muted">Loading…</div></div>`;
    try {
      const response = await fetch("/api/rules");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.rules)) return fallback();
      STATE.recoveryRules = data.rules;
      render();
    } catch {
      fallback();
    }
  }

  function openRuleModal() {
    const dialog = $("#rule-modal");
    if (!dialog) return toast("Rule editor is updating — reload once");
    $("#rule-form-status").textContent = "";
    dialog.showModal();
  }

  function closeRuleModal() {
    const dialog = $("#rule-modal");
    if (dialog.open) dialog.close();
  }

  async function wireGoals(root) {
    const current = JSON.parse(bodyModeStaticJson);
    const render = () => {
      root.innerHTML = S.goals().replace('<div class="screen-inner">', `<div class="screen-inner">${subnavHtml("health", "goals")}`);
    };
    root.innerHTML = `<div class="screen-inner"><div class="muted">Loading…</div></div>`;
    const fetchJson = async (path) => {
      try {
        const response = await fetch(path);
        if (!response.ok) return null;
        return await response.json();
      } catch {
        return null;
      }
    };
    const [goalsData, modeData, statsData] = await Promise.all([
      fetchJson("/api/goals"),
      fetchJson("/api/body-mode"),
      fetchJson("/api/stats"),
    ]);

    if (modeData && Array.isArray(modeData.modes) && modeData.modes.some((item) => item.key === modeData.mode)) {
      current.mode = modeData.mode;
      current.modes = modeData.modes;
      current.weekIndex = modeData.weekIndex ?? current.weekIndex;
      current.weekCount = modeData.weekCount ?? current.weekCount;
      current.descriptor = modeData.descriptor ?? current.descriptor;
      current.bias = modeData.bias ?? current.bias;
    }

    const targets = Object.fromEntries(current.weeklyTargets.map((target) => [target.label, target]));
    const targetByGoal = {
      weekly_active_days: targets["Active days"],
      weekly_strength_sessions: targets.Strength,
      weekly_cardio_distance: targets.Cardio,
    };
    for (const goal of goalsData?.goals || []) {
      if (goal.enabled && goal.target_value != null && targetByGoal[goal.key]) {
        targetByGoal[goal.key].target = goal.target_value;
      }
    }

    if (Array.isArray(statsData?.days) && statsData.days.length) {
      const weekStart = currentWeekStartIso();
      const today = localIso();
      const week = statsData.days.filter((day) => day.date >= weekStart && day.date <= today);
      targetByGoal.weekly_active_days.value = week.filter((day) => day.strength || day.cardio).length;
      targetByGoal.weekly_strength_sessions.value = week.filter((day) => day.strength).length;
      targetByGoal.weekly_cardio_distance.value = Math.round(
        week.reduce((total, day) => total + (day.cardio?.km || 0), 0) * 10,
      ) / 10;
    }

    if (Array.isArray(statsData?.body) && statsData.body.length) {
      const mapTrend = (key, unit, digits, fallback) => {
        const points = statsData.body.map((row) => row[key]).filter((value) => value != null).slice(-7);
        if (!points.length) return fallback;
        const latest = points.at(-1);
        const delta = latest - points[0];
        const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
        return {
          ...fallback,
          value: `${latest.toFixed(digits)} ${unit}`,
          delta: `${sign}${Math.abs(delta).toFixed(digits)} ${unit === "%" ? "pt" : unit}`,
          trend: points,
        };
      };
      current.weight = mapTrend("weight_kg", "kg", 1, current.weight);
      current.bodyFat = mapTrend("fat_ratio_pct", "%", 1, current.bodyFat);
    }
    STATE.bodyMode = current;
    render();
  }

  const MEMORY_KNOWN_CATS = ["injuries", "schedule", "equipment", "prefers", "dislikes"];
  const MEMORY_EVENT_CATS = ["target_event", "event"];
  async function wireMemory(root) {
    const render = () => {
      root.innerHTML = S.memory().replace('<div class="screen-inner">', `<div class="screen-inner">${subnavHtml("settings", "memory")}`);
    };
    // Build the screen model purely from live backend data — never fall back to
    // seeded/fake content. memoryIds maps category -> [backend id per chip] so
    // deletes hit the right row.
    const build = (groups, error) => {
      memoryIds = {};
      const known = {};
      for (const cat of MEMORY_KNOWN_CATS) {
        const rows = Array.isArray(groups[cat]) ? groups[cat] : [];
        known[cat] = rows.map((r) => r.content);
        memoryIds[cat] = rows.map((r) => r.id);
      }
      const eventCat = MEMORY_EVENT_CATS.find((c) => Array.isArray(groups[c]) && groups[c].length);
      let targetEvent = null;
      if (eventCat) {
        const rows = groups[eventCat];
        memoryIds[eventCat] = rows.map((r) => r.id);
        targetEvent = { content: rows[rows.length - 1].content, category: eventCat, id: rows[rows.length - 1].id };
      }
      const handled = new Set([...MEMORY_KNOWN_CATS, ...MEMORY_EVENT_CATS]);
      const extra = [];
      for (const cat of Object.keys(groups)) {
        if (handled.has(cat)) continue;
        const rows = Array.isArray(groups[cat]) ? groups[cat] : [];
        if (!rows.length) continue;
        extra.push({ category: cat, items: rows.map((r) => r.content) });
        memoryIds[cat] = rows.map((r) => r.id);
      }
      STATE.coachMemory = { known, extra, targetEvent, error };
      render();
    };
    root.innerHTML = `<div class="screen-inner"><div class="muted">Loading…</div></div>`;
    try {
      const response = await fetch("/api/memories");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      build(data.groups || {});
    } catch (e) {
      build({}, String(e && e.message || "Check your connection."));
    }
  }

  async function addMemory(btn) {
    const category = btn.dataset.category;
    if (btn.dataset.editing) return;
    btn.dataset.editing = "1";
    const input = document.createElement("input");
    input.className = "chip chip-add-input";
    input.placeholder = "Type, then Enter";
    btn.replaceWith(input);
    input.focus();
    let done = false;
    const finish = async (save) => {
      if (done) return; done = true;
      const content = input.value.trim();
      if (!save || !content) return nav("memory");
      try {
        const r = await fetch("/api/memories", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content, category }) });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      } catch { toast("Could not add memory"); }
      nav("memory");
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); finish(true); }
      else if (e.key === "Escape") { e.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true));
  }

  async function removeMemory(btn) {
    const id = memoryIds[btn.dataset.category]?.[+btn.dataset.idx];
    if (id == null) return toast("Could not remove this memory");
    try {
      const response = await fetch(`/api/memories/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      nav("memory");
    } catch {
      toast("Could not remove memory");
    }
  }

  function mapTodayPlanned(day) {
    if (!day) return null;
    const payload = day.payload_json || {};
    if (day.kind === "rest") {
      return { type: "REST", name: day.title || "Rest day", detail: "Recovery — no training scheduled", status: "rest", kind: "rest" };
    }
    if (day.kind === "cardio") {
      const detail = [payload.zone, payload.distance_km == null ? null : `${payload.distance_km} km`, payload.duration_minutes == null ? null : `${payload.duration_minutes} min`].filter(Boolean).join(" · ") || "Cardio";
      return { type: "CARDIO", name: day.title, detail, status: day.garmin_workout_id ? "ready" : day.status === "done" ? "done" : "planned", kind: "cardio" };
    }
    const count = (payload.exercises || []).length;
    const detail = [count ? `${count} exercise${count === 1 ? "" : "s"}` : null, payload.duration_minutes == null ? null : `~${payload.duration_minutes} min`].filter(Boolean).join(" · ") || "Strength session";
    return { type: "STRENGTH", name: day.title, detail, status: day.hevy_routine_id ? "ready" : day.status === "done" ? "done" : "planned", kind: "strength" };
  }

  function mapRecentSession(entry, todayIso) {
    let name = "Session", meta = "", accent = "strength";
    if (entry.strength) {
      accent = "strength"; name = "Strength";
      meta = [`${entry.strength.exercises.length} exercise${entry.strength.exercises.length === 1 ? "" : "s"}`, entry.strength.minutes ? `${entry.strength.minutes} min` : null].filter(Boolean).join(" · ");
    } else if (entry.cardio) {
      accent = "cardio"; name = entry.cardio.type || "Cardio";
      meta = [entry.cardio.km ? `${entry.cardio.km} km` : null, entry.cardio.minutes ? `${entry.cardio.minutes} min` : null].filter(Boolean).join(" · ");
    }
    return { day: planDate(entry.date).toLocaleDateString(undefined, { weekday: "short" }), name, meta, accent, today: entry.date === todayIso };
  }

  async function wireToday(root) {
    const errorState = () => {
      root.innerHTML = `<div class="screen-inner">
        <div class="card" style="text-align:center;padding:32px 18px">
          <p class="screen-title" style="margin-bottom:6px">Couldn't load today</p>
          <p class="muted">Something went wrong reaching the server. Check your connection and try again.</p>
        </div>
      </div>`;
    };
    root.innerHTML = `<div class="screen-inner"><div class="muted">Loading…</div></div>`;
    const todayIso = localIso();
    try {
      const recentStart = localIso(new Date(Date.now() - 6 * 86400000));
      const [healthResponse, rulesResponse, planResponse, statsResponse, readinessResponse] = await Promise.all([
        fetch("/api/health"),
        fetch("/api/rules").catch(() => null),
        fetch("/api/plan?week=current").catch(() => null),
        fetch(`/api/stats?start=${encodeURIComponent(recentStart)}&end=${encodeURIComponent(todayIso)}`).catch(() => null),
        fetch("/api/reports?kind=readiness&limit=1").catch(() => null),
      ]);
      if (!healthResponse.ok) throw new Error(`HTTP ${healthResponse.status}`);
      const health = ((await healthResponse.json()).days || []).at(-1) || null;

      let warning = "";
      if (rulesResponse?.ok) warning = (await rulesResponse.json()).warning || "";

      let planned = null;
      if (planResponse?.ok) {
        const planData = await planResponse.json();
        planned = mapTodayPlanned((planData.days || []).find((day) => day.date === todayIso));
      }

      let recent = [];
      if (statsResponse?.ok) {
        recent = ((await statsResponse.json()).days || []).slice(-3).map((entry) => mapRecentSession(entry, todayIso));
      }

      const sleepMinutes = health?.sleep_hours == null ? null : Math.round(health.sleep_hours * 60);
      const sleepBand = health?.sleep_score >= 80 ? "good" : health?.sleep_score >= 60 ? "fair" : "low";
      const restingDiff = health?.resting_hr == null || health?.resting_hr_7d_avg == null
        ? ""
        : `${health.resting_hr - health.resting_hr_7d_avg > 0 ? "+" : health.resting_hr - health.resting_hr_7d_avg < 0 ? "−" : ""}${Math.abs(health.resting_hr - health.resting_hr_7d_avg)} vs base`;
      let readiness = null;
      if (readinessResponse?.ok) {
        const latest = ((await readinessResponse.json()).reports || [])[0] || null;
        if (latest?.review_date === todayIso) readiness = latest.readiness_score ?? null;
      }

      STATE.today = {
        dateLine: new Date().toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }).toUpperCase(),
        readiness,
        verdict: readiness == null ? null : readiness >= 66 ? "TRAIN" : readiness >= 40 ? "EASY" : "REST",
        planned,
        recent,
        sleep: {
          value: sleepMinutes == null ? "—" : `${Math.floor(sleepMinutes / 60)}h ${sleepMinutes % 60}m`,
          meta: health?.sleep_score == null ? "" : `Score ${health.sleep_score} · ${sleepBand}`,
        },
        hrv: {
          value: health?.hrv == null ? "—" : `${health.hrv} ms`,
          meta: health?.hrv_status == null ? "" : `${health.hrv_status} · 7-day`,
        },
        bodyBattery: {
          value: health?.body_battery_high == null ? "—" : String(health.body_battery_high),
          meta: health?.body_battery_high == null ? "" : "Charged",
        },
        restingHr: {
          value: health?.resting_hr == null ? "—" : `${health.resting_hr} bpm`,
          meta: restingDiff,
        },
        acwr: health?.acwr ?? null,
        warning,
      };
      root.innerHTML = S.today();
    } catch {
      errorState();
    }
  }

  function localIso(day = new Date()) {
    const year = day.getFullYear();
    const month = String(day.getMonth() + 1).padStart(2, "0");
    const date = String(day.getDate()).padStart(2, "0");
    return `${year}-${month}-${date}`;
  }

  function currentWeekStartIso() {
    const day = new Date();
    day.setHours(12, 0, 0, 0);
    day.setDate(day.getDate() - ((day.getDay() + 6) % 7));
    return localIso(day);
  }

  function planDate(value) { return new Date(`${value}T12:00:00`); }
  function shortDate(value) { return planDate(value).toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
  function longDate(value) { return planDate(value).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" }); }

  function planExercises(day) {
    const payload = day.payload_json || {};
    if (day.kind === "strength") return (payload.exercises || []).map((item) => typeof item === "string" ? item : item.name).filter(Boolean);
    if (day.kind === "cardio") {
      const bits = [payload.zone, payload.distance_km == null ? null : `${payload.distance_km} km`, payload.duration_minutes == null ? null : `${payload.duration_minutes} min`];
      return [bits.filter(Boolean).join(" · ") || "Cardio"];
    }
    return [];
  }

  function mapWeeklyPlan(data) {
    const rows = data.days;
    const strength = rows.filter((day) => day.kind === "strength").length;
    const cardio = rows.filter((day) => day.kind === "cardio").length;
    const rest = rows.filter((day) => day.kind === "rest").length;
    const statusMap = {
      planned: ["PLANNED", "planned", "blue"],
      ready_in_hevy: ["READY IN HEVY", "ready", "green"],
      scheduled: ["SCHEDULED", "ready", "green"],
      done: ["COMPLETED", "completed", "green"],
      missed: ["MISSED", "missed", "orange"],
      replaced: ["REPLACED", "replaced", "amber"],
    };
    const start = rows[0].date, end = rows.at(-1).date;
    return {
      weekStart: data.week_start,
      header: "WEEKLY PLAN",
      range: `${shortDate(start)} – ${shortDate(end)}`,
      summary: `${rows.length - rest} active days · ${strength} strength · ${cardio} cardio · ${rest} rest`,
      tiles: [
        { value: String(rows.length - rest), label: "Active days" },
        { value: String(strength), label: "Strength" },
        { value: String(cardio), label: "Cardio" },
      ],
      days: rows.map((day) => {
        const [status, statusKind, dot] = day.kind === "rest" ? ["REST DAY", "rest", "violet"] : (statusMap[day.status] || statusMap.planned);
        const deliveryFailed = day.delivery_status === "failed";
        const deliveryPending = day.delivery_status === "pending";
        const delivery = day.kind === "rest"
          ? ""
          : deliveryFailed
            ? `Delivery failed${day.delivery_error ? ` · ${day.delivery_error}` : ""}`
            : deliveryPending
              ? `Publishing to ${day.delivery}…`
              : day.delivery;
        return {
          date: day.date,
          day: day.weekday.slice(0, 3),
          name: day.title,
          accent: day.kind,
          exercises: planExercises(day),
          delivery,
          deliveryColor: deliveryFailed ? "orange" : deliveryPending ? "amber" : day.status === "missed" ? "orange" : day.status === "replaced" ? "amber" : "green",
          status,
          statusKind,
          dot,
          rest: day.kind === "rest",
          today: day.date === localIso(),
          garminWorkoutId: day.garmin_workout_id,
        };
      }),
    };
  }

  async function wirePlan(root) {
    const render = () => {
      root.innerHTML = S.plan().replace('<div class="screen-inner">', `<div class="screen-inner">${subnavHtml("plan", "plan")}`);
    };
    // Honest empty/error states — never show fabricated sample data, which looks
    // like a real (but wrong) plan with stale dates and exercises.
    const placeholder = (title, body, showGenerate) => {
      STATE.weekPlan = { weekStart: currentWeekStartIso() };
      root.innerHTML = `<div class="screen-inner">${subnavHtml("plan", "plan")}
        <div id="plan-status" class="gen-status"></div>
        <div class="card" style="text-align:center;padding:32px 18px">
          <p class="screen-title" style="margin-bottom:6px">${esc(title)}</p>
          <p class="muted" style="margin-bottom:${showGenerate ? "16px" : "0"}">${esc(body)}</p>
          ${showGenerate ? `<button class="btn btn-primary" data-action="regenerate-week">Generate week</button>` : ""}
        </div>
      </div>`;
    };
    root.innerHTML = `<div class="screen-inner"><div class="muted">Loading…</div></div>`;
    try {
      const response = await fetch("/api/plan?week=current");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.days) || !data.days.length) {
        return placeholder("No plan for this week yet", "Generate a seven-day training plan from your focus, recovery, and recent training.", true);
      }
      STATE.weekPlan = mapWeeklyPlan(data);
      render();
    } catch {
      placeholder("Couldn't load your plan", "Something went wrong reaching the server. Check your connection and try again.", false);
    }
  }

  function mapBuilder(day) {
    const payload = day.payload_json || {};
    const exercises = (payload.exercises || []).map((exercise, exerciseIndex) => ({
      name: exercise.name,
      scheme: exercise.scheme,
      expanded: exercise.expanded ?? exerciseIndex < 2,
      sets: (exercise.sets || []).map((item, setIndex) => ({
        set: item.set || String(setIndex + 1),
        weight: item.weight_kg ?? "—",
        reps: item.reps ?? "—",
        rpe: item.rpe ?? "—",
        kind: item.type === "warmup" ? "warm" : "work",
      })),
      progression: exercise.progression || null,
      alternatives: exercise.alternatives || "",
    }));
    const workingSets = exercises.reduce((total, exercise) => total + exercise.sets.filter((item) => item.kind === "work").length, 0);
    const targets = Array.isArray(payload.targets) && payload.targets.length
      ? payload.targets
      : [
          { label: "Working sets", value: String(workingSets) },
          { label: "Duration", value: payload.duration_minutes ? `${payload.duration_minutes} min` : "—" },
        ];
    return {
      live: true,
      planDate: day.date,
      hevyRoutineId: day.hevy_routine_id,
      title: day.title,
      crumb: ["Plan", longDate(day.date), day.title],
      synced: day.hevy_routine_id ? "ready" : "not pushed yet",
      summary: `${exercises.length} exercises${payload.duration_minutes ? ` · ~${payload.duration_minutes} min` : ""}`,
      exercises,
      notes: payload.notes || "",
      targets: targets.map((target) => ({ label: target.label, value: String(target.value) })),
    };
  }

  async function wireBuilder(root) {
    const render = () => {
      root.innerHTML = S.builder().replace('<div class="screen-inner">', `<div class="screen-inner">${subnavHtml("plan", "builder")}`);
    };
    // Honest empty/error states — never show fabricated sample data, which looks
    // like a real (but wrong) workout with stale exercises and weights.
    const placeholder = (title, body, showGenerate) => {
      root.innerHTML = `<div class="screen-inner">${subnavHtml("plan", "builder")}
        <div class="card" style="text-align:center;padding:32px 18px">
          <p class="screen-title" style="margin-bottom:6px">${esc(title)}</p>
          <p class="muted" style="margin-bottom:${showGenerate ? "16px" : "0"}">${esc(body)}</p>
          ${showGenerate ? `<button class="btn btn-primary" data-action="regenerate-week">Generate week</button>` : ""}
        </div>
      </div>`;
    };
    root.innerHTML = `<div class="screen-inner"><div class="muted">Loading…</div></div>`;
    try {
      const planResponse = await fetch("/api/plan?week=current");
      if (!planResponse.ok) throw new Error(`HTTP ${planResponse.status}`);
      const planData = await planResponse.json();
      const strength = (planData.days || []).filter((day) => day.kind === "strength");
      const selected = (requestedBuilderDate && strength.find((day) => day.date === requestedBuilderDate))
        || strength.find((day) => day.date === localIso())
        || strength.find((day) => day.date > localIso())
        || strength[0];
      requestedBuilderDate = null;
      if (!selected) {
        return placeholder("No workout to show yet", "Generate a seven-day training plan and your next strength workout will appear here.", true);
      }
      const response = await fetch(`/api/plan/day/${encodeURIComponent(selected.date)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      STATE.builder = mapBuilder(await response.json());
      render();
    } catch {
      placeholder("Couldn't load your workout", "Something went wrong reaching the server. Check your connection and try again.", false);
    }
  }

  async function openHevy() {
    const builder = STATE.builder;
    if (!builder.live || !builder.planDate) return openExternal("https://hevy.com/", "Opening Hevy…");
    toast(builder.hevyRoutineId ? "Updating Hevy routine…" : "Pushing to Hevy…");
    try {
      const response = await fetch(`/api/plan/day/${encodeURIComponent(builder.planDate)}/push-hevy`, { method: "POST" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const day = await response.json();
      if (!day.hevy_routine_id) throw new Error("Missing routine id");
      STATE.builder.hevyRoutineId = day.hevy_routine_id;
      STATE.builder.synced = "ready";
      openExternal(`https://hevy.com/routine/${encodeURIComponent(day.hevy_routine_id)}`, "Opening Hevy…");
      nav("builder");
    } catch {
      toast("Could not push routine to Hevy");
    }
  }

  async function scheduleGarmin(btn) {
    const calendarUrl = "https://connect.garmin.com/modern/calendar";
    if (btn.dataset.scheduled === "true") {
      return openExternal(calendarUrl, "Opening Garmin Connect…");
    }
    toast("Scheduling in Garmin…");
    try {
      const response = await fetch(
        `/api/plan/day/${encodeURIComponent(btn.dataset.date)}/schedule-garmin`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      toast("Scheduled in Garmin");
      nav("plan");
    } catch {
      toast("Could not schedule — opening Garmin Connect…");
      window.open(calendarUrl, "_blank", "noopener");
    }
  }

  function actualText(day) {
    const parts = [];
    if (day.strength) parts.push(`${day.strength.title || "Strength"} · ${day.strength.minutes || 0} min`);
    if (day.cardio) parts.push(`${day.cardio.type || "Cardio"} · ${day.cardio.km || 0} km · ${day.cardio.minutes || 0} min`);
    return parts.join(" + ") || "No session";
  }

  function plannedText(day) {
    const detail = planExercises(day)[0];
    return detail ? `${day.title} · ${detail}` : day.title;
  }

  // A planned session counts as completed only when the matching-kind actual
  // reaches a reasonable fraction of the planned volume. Doing a much shorter
  // session (e.g. a 1.5 km jog instead of a planned 7.5 km run) is not "on plan".
  function sessionMatches(day, actual) {
    const payload = day.payload_json || {};
    const done = actual[day.kind];
    if (!done) return false;
    const ratios = [];
    if (payload.duration_minutes) ratios.push((done.minutes || 0) / payload.duration_minutes);
    if (day.kind === "cardio" && payload.distance_km) ratios.push((done.km || 0) / payload.distance_km);
    if (!ratios.length) return true; // no planned target to compare against
    return ratios.every((r) => r >= 0.75);
  }

  function mapPlanVsActual(planData, statsData) {
    const actualByDate = Object.fromEntries((statsData.days || []).map((day) => [day.date, day]));
    const today = localIso();
    const details = {};
    const eligible = [];
    const calendarDays = planData.days.map((day) => {
      const actual = actualByDate[day.date] || { strength: null, cardio: null };
      const hasActual = Boolean(actual.strength || actual.cardio);
      const matching = day.kind !== "rest" && sessionMatches(day, actual);
      let status;
      if (day.kind === "rest") status = hasActual ? "REPLACED" : day.date <= today ? "ON PLAN" : "PLANNED";
      else if (matching) status = "ON PLAN";
      else if (hasActual) status = "REPLACED";
      else status = day.date < today ? "MISSED" : "PLANNED";
      if (day.kind !== "rest" && day.date <= today) eligible.push(status);

      const color = { "ON PLAN": "#46c98b", MISSED: "#ff6b4a", REPLACED: "#e0a23b", PLANNED: "#4f8cff" }[status];
      const diff = { "ON PLAN": "Completed as planned.", MISSED: "No matching session synced.", REPLACED: "A different session was synced.", PLANNED: "Session is still planned." }[status];
      const impact = { "ON PLAN": "Plan and completed work are aligned.", MISSED: "The next re-plan can account for the missed work.", REPLACED: "The next re-plan can account for the changed load.", PLANNED: "No recovery impact yet." }[status];
      details[day.date] = {
        date: longDate(day.date),
        day: planDate(day.date).getDate(),
        kind: day.kind,
        planned: plannedText(day),
        actual: actualText(actual),
        ac: color,
        diff,
        impact,
        status,
        color,
      };
      return {
        key: day.date,
        n: planDate(day.date).getDate(),
        nm: day.title,
        s: { "ON PLAN": "green", MISSED: "orange", REPLACED: "amber", PLANNED: "blue" }[status],
        tag: day.date === today ? "today" : status === "MISSED" ? "missed" : status === "REPLACED" ? "replaced" : "",
      };
    });
    const start = planData.days[0].date, end = planData.days.at(-1).date;
    return {
      adherence: eligible.length ? Math.round(eligible.filter((status) => status === "ON PLAN").length / eligible.length * 100) : 0,
      selectedDay: details[today] ? today : planData.days[0].date,
      monthLabel: `${shortDate(start)} – ${shortDate(end)}, ${planDate(end).getFullYear()}`,
      weeks: [calendarDays],
      days: details,
    };
  }

  function bindActual(root) {
    const fill = (n) => root.querySelectorAll("[data-pa-detail]").forEach((panel) => { panel.innerHTML = S.paDetailHtml(n); });
    fill(STATE.planVsActual.selectedDay);
    root.querySelectorAll("[data-day]").forEach((cell) => {
      if (cell.dataset.day === String(STATE.planVsActual.selectedDay) && cell.classList.contains("calcell") && !cell.classList.contains("today")) {
        cell.style.outline = "2px solid #eef1f6"; cell.style.outlineOffset = "2px";
      }
    });
    root.addEventListener("click", (e) => {
      const cell = e.target.closest("[data-day]");
      if (!cell) return;
      const grid = cell.closest("[data-cal-grid]");
      if (grid) grid.querySelectorAll("[data-day]").forEach((c) => { c.style.outline = "none"; c.style.outlineOffset = "0"; });
      cell.style.outline = "2px solid #eef1f6"; cell.style.outlineOffset = "2px";
      STATE.planVsActual.selectedDay = cell.dataset.day;
      fill(cell.dataset.day);
    });
  }

  async function wireActual(root) {
    const render = () => { root.innerHTML = S.actual(); bindActual(root); };
    // Honest empty/error states — never show fabricated sample data, which looks
    // like a real (but wrong) comparison with stale dates and exercises.
    const placeholder = (title, body, showGenerate) => {
      root.innerHTML = `<div class="screen-inner">${subnavHtml("plan", "actual")}
        <div class="card" style="text-align:center;padding:32px 18px">
          <p class="screen-title" style="margin-bottom:6px">${esc(title)}</p>
          <p class="muted" style="margin-bottom:${showGenerate ? "16px" : "0"}">${esc(body)}</p>
          ${showGenerate ? `<button class="btn btn-primary" data-action="regenerate-week">Generate week</button>` : ""}
        </div>
      </div>`;
    };
    root.innerHTML = `<div class="screen-inner"><div class="muted">Loading…</div></div>`;
    try {
      const planResponse = await fetch("/api/plan?week=current");
      if (!planResponse.ok) throw new Error(`HTTP ${planResponse.status}`);
      const planData = await planResponse.json();
      if (!Array.isArray(planData.days) || !planData.days.length) {
        return placeholder("No plan to compare yet", "Generate a seven-day training plan to compare it against what you actually trained.", true);
      }
      const end = planData.days.at(-1).date;
      const statsResponse = await fetch(`/api/stats?start=${encodeURIComponent(planData.week_start)}&end=${encodeURIComponent(end)}`);
      if (!statsResponse.ok) throw new Error(`HTTP ${statsResponse.status}`);
      STATE.planVsActual = mapPlanVsActual(planData, await statsResponse.json());
      render();
    } catch {
      placeholder("Couldn't load your plan", "Something went wrong reaching the server. Check your connection and try again.", false);
    }
  }

  function updatePlan(path, body, pending) {
    return runGeneration({
      statusId: "plan-status",
      working: pending,
      run: () => fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      onDone: () => nav("plan"),
    });
  }

  function regenerateWeek() {
    return updatePlan("/api/plan/generate", { week_start: STATE.weekPlan.weekStart || currentWeekStartIso() }, "Regenerating week…");
  }

  function replanToday() {
    return updatePlan("/api/plan/replan", { from_date: localIso() }, "Re-planning from today…");
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

  // ----- LLM generation feedback (shared by reviews + plan generate buttons)
  // One model call at a time: it's the same rate-limited backend, and a single
  // busy flag prevents the duplicate-request storms we used to see.
  let genBusy = false;
  async function runGeneration({ statusId, working, run, onDone }) {
    if (genBusy) { toast("Already working — hang tight"); return; }
    genBusy = true;
    const started = Date.now();
    const status = statusId ? document.getElementById(statusId) : null;
    let tick;
    const paint = (cls, html) => { if (status) { status.className = "gen-status " + cls; status.innerHTML = html; } };
    if (status) {
      paint("is-busy", `<span class="spinner"></span><span>${esc(working)} <b id="gen-elapsed">0s</b></span>`);
      tick = setInterval(() => { const e = document.getElementById("gen-elapsed"); if (e) e.textContent = Math.round((Date.now() - started) / 1000) + "s"; }, 1000);
    } else {
      toast(working);
    }
    try {
      const r = await run();
      if (r.status === 202) { paint("is-busy", `<span class="spinner"></span><span>Already generating — hang tight…</span>`); toast("Already running"); return; }
      if (!r.ok) {
        let msg = "Generation failed. Please try again.";
        try { const j = await r.json(); if (j && j.detail) msg = j.detail; } catch {}
        paint("is-error", `<span>⚠ ${esc(msg)}</span>`);
        toast("Generation failed");
        return;
      }
      paint("is-ok", `<span>✓ Done</span>`);
      toast("Done");
      if (onDone) onDone();
    } catch {
      paint("is-error", `<span>⚠ Network error — check your connection and try again.</span>`);
      toast("Generation failed");
    } finally {
      clearInterval(tick);
      genBusy = false;
    }
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
      <div class="row" style="margin-bottom:14px"><button id="rev-generate-btn" class="btn btn-primary" data-action="rev-generate">Generate now</button></div>
      <div id="reviews-status" class="gen-status"></div>
      <div id="reviews-list" class="stack"><div class="muted">Loading…</div></div>
    </div>`;
  }
  function generateReview() {
    const btn = document.getElementById("rev-generate-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Generating…"; }
    return runGeneration({
      statusId: "reviews-status",
      working: `Generating ${reviewKind === "weekly" ? "weekly review" : "readiness brief"}…`,
      run: () => fetch("/api/reports/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: reviewKind }) }),
      onDone: () => nav("reviews"),
    }).finally(() => { const b = document.getElementById("rev-generate-btn"); if (b) { b.disabled = false; b.textContent = "Generate now"; } });
  }
  async function loadReviews(root) {
    try {
      const r = await fetch(`/api/reports?kind=${reviewKind}&limit=20`);
      const j = await r.json();
      const list = $("#reviews-list", root);
      if (!j.reports || !j.reports.length) { list.innerHTML = `<div class="card muted">No ${reviewKind} reports yet. Generate one above.</div>`; return; }
      const item = (rep, i) => {
        const d = rep.created_at ? new Date(rep.created_at) : null;
        const dt = d ? d.toLocaleString() : "";
        const rel = i === 0 ? "Most recent" : (d ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : `#${i + 1}`);
        const body = window.marked ? marked.parse(rep.content || "") : esc(rep.content || "");
        return `<details class="review-item card"${i === 0 ? " open" : ""}>
          <summary class="review-summary">
            <span class="review-label">${esc(rel)}</span>
            <span class="label-mono review-date">${esc(dt)}</span>
            ${I.chevronLeft(16)}
          </summary>
          <div class="sec review-body" style="font-size:13px;line-height:1.55">${body}</div>
        </details>`;
      };
      list.innerHTML = j.reports.map(item).join("");
    } catch { const list = $("#reviews-list", root); if (list) list.innerHTML = `<div class="card muted">Could not load reports.</div>`; }
  }

  // ----- Chat (live /api/chat streaming ndjson, multi-conversation)
  // activeChatId is page-session state, not persisted: a reload starts a fresh
  // chat, but navigating around within a session keeps the chat you were using.
  let activeChatId = null;
  const CHAT_GREETING = "Morning. Ask me anything about today's plan, your recovery, or this week.";
  const chatNewId = () => "web-" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
  const chatAdd = (msgs, role, text) => {
    const d = document.createElement("div");
    d.className = "msg " + role;
    d.innerHTML = role === "assistant" && window.marked ? marked.parse(text) : esc(text);
    msgs.appendChild(d); msgs.scrollTop = msgs.scrollHeight; return d;
  };
  function chatRelTime(iso) {
    if (!iso) return "";
    const d = new Date(iso), now = new Date(), diff = (now - d) / 1000;
    if (diff < 60) return "now";
    if (diff < 3600) return Math.floor(diff / 60) + "m";
    if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function chatRenderGreeting() {
    const msgs = $("#chat-msgs"); if (!msgs) return;
    msgs.innerHTML = ""; chatAdd(msgs, "assistant", CHAT_GREETING);
  }
  async function chatLoadMessages(id) {
    const msgs = $("#chat-msgs"); if (!msgs) return;
    msgs.innerHTML = "";
    try {
      const j = await (await fetch(`/api/chats/${id}/messages`)).json();
      const list = j.messages || [];
      if (!list.length) chatAdd(msgs, "assistant", CHAT_GREETING);
      else list.forEach((m) => chatAdd(msgs, m.role, m.content));
    } catch { chatAdd(msgs, "assistant", CHAT_GREETING); }
  }
  async function chatLoadHistory() {
    const el = $("#chat-history"); if (!el) return;
    try {
      const j = await (await fetch("/api/chats?limit=50")).json();
      const chats = j.chats || [];
      if (!chats.length) { el.innerHTML = `<div class="muted chat-history-empty">No past chats yet.</div>`; return; }
      el.innerHTML = chats.map((c) => `
        <div class="chat-history-item ${c.id === activeChatId ? "active" : ""}" data-action="chat-open" data-cid="${esc(c.id)}">
          <div class="chat-history-meta">
            <span class="chat-history-title">${esc(c.title || "New chat")}</span>
            <span class="chat-history-time">${esc(chatRelTime(c.updated_at))}</span>
          </div>
          <button class="chat-history-del" data-action="chat-delete" data-cid="${esc(c.id)}" aria-label="Delete chat">${I.trash(14)}</button>
        </div>`).join("");
    } catch { el.innerHTML = `<div class="muted chat-history-empty">Couldn't load chats.</div>`; }
  }
  function chatStartNew() {
    activeChatId = null;
    chatRenderGreeting();
    chatLoadHistory();
    $("#chat-sidebar")?.classList.remove("open");
    $("#chat-input")?.focus();
  }
  function chatOpen(id) {
    if (!id) return;
    activeChatId = id;
    chatLoadMessages(id);
    chatLoadHistory();
    $("#chat-sidebar")?.classList.remove("open");
  }
  async function chatDelete(id) {
    try { await fetch(`/api/chats/${id}`, { method: "DELETE" }); } catch {}
    if (id === activeChatId) chatStartNew();
    else chatLoadHistory();
  }
  function wireChat(root) {
    const form = $("#composer", root), input = $("#chat-input", root);
    if (activeChatId) chatLoadMessages(activeChatId); else chatRenderGreeting();
    chatLoadHistory();

    input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 140) + "px"; });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = input.value.trim(); if (!text) return;
      input.value = ""; input.style.height = "auto";
      if (!activeChatId) activeChatId = chatNewId();
      const sid = activeChatId;
      const msgs = $("#chat-msgs", root);
      chatAdd(msgs, "user", text);
      const out = chatAdd(msgs, "assistant", "");
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
      chatLoadHistory();
    });
  }

  // boot
  const ruleMetric = $("#rule-metric");
  const syncRuleCondition = () => {
    if (!ruleMetric) return;
    const disabled = !ruleMetric?.value;
    $("#rule-operator").disabled = disabled;
    $("#rule-value").disabled = disabled;
    $("#rule-value").required = !disabled;
  };
  if (ruleMetric) {
    ruleMetric.addEventListener("change", syncRuleCondition);
    syncRuleCondition();
  }
  const ruleForm = $("#rule-form");
  if (ruleForm) ruleForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector('button[type="submit"]');
    const status = $("#rule-form-status");
    const metric = form.elements.metric.value;
    submit.disabled = true;
    status.textContent = "Creating rule…";
    try {
      const response = await fetch("/api/rules", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: form.elements.label.value.trim(),
          description: form.elements.description.value.trim(),
          condition: metric ? {
            metric,
            op: form.elements.operator.value,
            value: Number(form.elements.value.value),
          } : null,
          action: form.elements.action.value,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      closeRuleModal();
      form.reset();
      syncRuleCondition();
      nav("rules");
    } catch {
      status.textContent = "Could not create rule.";
    } finally {
      submit.disabled = false;
    }
  });
  renderAppbar(); renderTabbar(); nav("today");
})();
