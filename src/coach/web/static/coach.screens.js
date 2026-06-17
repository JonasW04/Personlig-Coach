// Screen renderers. Each returns an HTML string built from window.STATE.
// Interactions are wired by coach.js via delegated data-action handlers.
window.SCREENS = (() => {
  const I = window.ICONS;
  const ACC = { strength: "var(--strength)", cardio: "var(--cardio)", rest: "var(--rest)" };
  const ACC_LIGHT = { strength: "var(--strength-lighter)", cardio: "var(--cardio-lighter)", rest: "var(--rest-light)" };
  const DOTCOL = { green: "var(--train)", blue: "var(--strength)", amber: "var(--easy)", violet: "var(--rest)" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const pillClass = { green: "pill-green", amber: "pill-amber", orange: "pill-orange", blue: "pill-blue", violet: "pill-violet", muted: "pill-muted" };
  const pill = (color, text, dot) =>
    `<span class="pill ${pillClass[color] || "pill-muted"}">${dot ? '<span class="dot"></span>' : ""}${esc(text)}</span>`;

  const head = (eyebrow, title, right = "", rightClass = "") =>
    `<div class="sectionhead"><div><p class="eyebrow">${esc(eyebrow)}</p>${title ? `<h2 class="screen-title">${esc(title)}</h2>` : ""}</div>${right ? `<div class="row wrap ${rightClass}">${right}</div>` : ""}</div>`;

  const crumb = (parts) => `<div class="crumb desktop-only">/ ${parts.map((p, i) => i === parts.length - 1 ? `<b>${esc(p)}</b>` : esc(p)).join(" / ")}</div>`;

  // tiny sparkline from values
  function spark(values, color) {
    const w = 100, h = 34, min = Math.min(...values), max = Math.max(...values), span = (max - min) || 1;
    const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / span) * (h - 6) - 3}`).join(" ");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  }

  // ------------------------------------------------------------------- Today
  function today() {
    const t = STATE.today;
    const verdictColor = { TRAIN: "var(--train)", EASY: "var(--easy)", REST: "var(--rest)" }[t.verdict] || "var(--train)";
    const signal = (label, value, meta) =>
      `<div class="tile"><p class="label-mono">${esc(label)}</p><div class="big" style="font-size:20px;margin-top:4px">${esc(value)}</div><div class="muted" style="font-size:11.5px">${esc(meta)}</div></div>`;
    const recent = t.recent.map((r) => `
      <div class="tile ${r.today ? "" : ""}" style="${r.today ? "border-color:rgba(79,140,255,.5);background:rgba(79,140,255,.06)" : ""}">
        <div class="between">
          <div><span class="label-mono">${esc(r.day)}</span>
          <div style="font-weight:700;color:${ACC_LIGHT[r.accent]}">${esc(r.name)}</div>
          <div class="muted" style="font-size:11.5px">${esc(r.meta)}</div></div>
          ${r.done ? `<span style="color:var(--train)">${I.check(18)}</span>` : pill("blue", "TODAY", true)}
        </div>
      </div>`).join("");

    const heroLeft = `
      <div style="display:flex;flex-direction:column;justify-content:center;padding-right:16px">
        <p class="label-mono">READINESS</p>
        <div class="hero-num" style="color:${verdictColor}">${t.readiness}</div>
        <div class="label-mono" style="color:${verdictColor};font-size:13px;letter-spacing:0.16em;margin-top:4px">${esc(t.verdict)}</div>
      </div>`;
    const heroRight = `
      <div style="display:flex;flex-direction:column;gap:8px;flex:1;min-width:0">
        <div class="between"><p class="label-mono">PLANNED · ${esc(t.planned.type)}</p>${pill("green", "READY IN HEVY", true)}</div>
        <div style="font-size:18px;font-weight:760;letter-spacing:-0.02em">${esc(t.planned.name)}</div>
        <div class="muted" style="font-size:12px">${esc(t.planned.detail)}</div>
      </div>`;

    const heroCard = `
      <div class="card" style="border-radius:var(--r-hero);padding:18px">
        <div style="display:flex;align-items:stretch">
          ${heroLeft}<div class="vrule"></div><div style="padding-left:16px;flex:1;display:flex">${heroRight}</div>
        </div>
        <div class="row wrap" style="margin-top:16px">
          <button class="btn btn-primary" data-action="view-workout">View workout</button>
          <button class="btn btn-secondary" data-action="open-hevy">Open Hevy</button>
          <button class="btn btn-outline" data-action="replan-today">Re-plan today</button>
        </div>
        <div class="row" style="margin-top:6px">
          <button class="btn-text" data-action="copy-workout">${I.copy(15)} Copy workout</button>
          <button class="btn-text" data-action="sync">${I.refresh(15)} Sync latest</button>
        </div>
      </div>`;

    const signals = `<div class="grid2">
      ${signal("SLEEP", t.sleep.value, t.sleep.meta)}
      ${signal("HRV", t.hrv.value, t.hrv.meta)}
      ${signal("BODY BATTERY", t.bodyBattery.value, t.bodyBattery.meta)}
      ${signal("RESTING HR", t.restingHr.value, t.restingHr.meta)}
    </div>`;

    const acwr = `
      <div class="card">
        <div class="between"><p class="label-mono">ACWR · ACUTE:CHRONIC LOAD</p><span class="big" style="font-size:20px;color:var(--train)">${t.acwr}</span></div>
        <div class="gradient-bar" style="margin-top:14px"><div class="marker" style="left:${t.acwrPct}%"></div></div>
        <div class="between" style="margin-top:8px"><span class="muted" style="font-size:10px">0.8</span><span class="label-mono" style="color:var(--train)">SWEET SPOT</span><span class="muted" style="font-size:10px">1.5</span></div>
      </div>`;

    const recentCard = `<div class="card"><p class="label-mono" style="margin-bottom:11px">RECENT · LAST 3 DAYS</p><div class="stack">${recent}</div></div>`;
    const warning = `<div class="warn">${esc(t.warning)}</div>`;

    return `<div class="screen-inner">
      ${head("Good morning", null, "")}
      <div class="muted" style="font-family:var(--mono);font-weight:800;letter-spacing:0.14em;font-size:10.5px;margin:-6px 0 14px">${esc(t.dateLine)}</div>
      <div class="cols c-1_5">
        <div class="stack">${heroCard}${recentCard}${warning}</div>
        <div class="stack">${signals}${acwr}</div>
      </div>
    </div>`;
  }

  // ------------------------------------------------------------------- Weekly Plan
  function plan() {
    const p = STATE.weekPlan;
    const tiles = p.tiles.map((t) => `<div class="tile" style="text-align:center"><div class="big">${esc(t.value)}</div><div class="label-mono" style="margin-top:4px">${esc(t.label)}</div></div>`).join("");
    const statusPill = (d) => {
      const map = { completed: ["green", true], planned: [d.dot === "amber" ? "amber" : "blue", true], replaced: ["amber", false], rest: ["violet", false] };
      const [c, dot] = map[d.statusKind] || ["muted", false];
      const icon = d.statusKind === "completed" ? "✓ " : d.statusKind === "replaced" ? "↻ " : d.statusKind === "planned" ? "● " : "☾ ";
      return pill(c, icon + d.status, false);
    };
    const dayCard = (d) => `
      <div class="daycol ${d.today ? "today" : ""} ${d.rest ? "rest" : ""}">
        <div class="between"><span class="label-mono">${esc(d.day)}</span><span class="dot" style="background:${DOTCOL[d.dot] || "var(--train)"}"></span></div>
        <div style="font-weight:760;font-size:15px;color:${ACC_LIGHT[d.accent]}">${esc(d.name)}${d.was ? ` <span class="muted" style="font-size:11px;text-decoration:line-through">was: ${esc(d.was)}</span>` : ""}</div>
        ${d.rest ? `<div class="muted" style="flex:1;display:flex;align-items:center;justify-content:center;font-size:22px">☾</div>` :
          `<div class="muted" style="font-size:11.5px;flex:1">${d.exercises.map((e) => esc(e)).join(" · ")}</div>`}
        ${d.warn ? `<div style="color:var(--easy);font-size:11px">⚠ ${esc(d.warn)}</div>` : ""}
        ${d.delivery ? `<div class="delivery" style="color:var(--${d.deliveryColor === "amber" ? "easy" : d.deliveryColor === "orange" ? "cardio" : "train"})">${esc(d.delivery)}</div>` : ""}
        <div style="margin-top:auto">${statusPill(d)}</div>
      </div>`;

    return `<div class="screen-inner">
      ${head(p.header, "Weekly Plan",
        `<button class="btn btn-secondary" data-action="regenerate-week">${I.refresh(15)} Regenerate week</button>
         <button class="btn btn-outline" data-action="replan-today">Re-plan from today</button>`)}
      <div class="muted" style="margin:-6px 0 4px;font-weight:700">${esc(p.range)}</div>
      <div class="muted" style="font-size:12px;margin-bottom:16px">${esc(p.summary)}</div>
      <div class="grid3 mobile-only" style="margin-bottom:14px">${tiles}</div>
      <div class="weekgrid desktop-only">${p.days.map(dayCard).join("")}</div>
      <div class="weeklist mobile-only">${p.days.map(dayCard).join("")}</div>
    </div>`;
  }

  // ------------------------------------------------------------------- Workout Builder
  function builder() {
    const b = STATE.builder;
    const setRows = (ex) => `
      <table class="settable">
        <thead><tr><th>SET</th><th>WEIGHT</th><th>REPS</th><th>RPE</th></tr></thead>
        <tbody>${ex.sets.map((s) => `<tr class="${s.kind}"><td>${esc(s.set)}</td><td>${esc(s.weight)} kg</td><td>${esc(s.reps)}</td><td>${esc(s.rpe)}</td></tr>`).join("")}</tbody>
      </table>`;
    const progression = (pr) => pr ? `<div class="${pr.kind === "up" ? "note-green" : "warn"}" style="margin-top:10px;font-size:12px">${esc(pr.text)}</div>` : "";
    const exCard = (ex) => ex.expanded ? `
      <div class="card">
        <div class="between"><div style="font-weight:760;font-size:15px">${esc(ex.name)}</div><span class="pill pill-blue">${esc(ex.scheme)}</span></div>
        <div style="margin-top:10px">${setRows(ex)}</div>
        ${progression(ex.progression)}
        ${ex.alternatives ? `<div class="muted" style="font-size:11.5px;margin-top:9px">${esc(ex.alternatives)}</div>` : ""}
      </div>` : `
      <div class="tile between"><div style="font-weight:700">${esc(ex.name)}</div><span class="muted" style="font-size:12px">${esc(ex.scheme)}</span></div>`;

    const right = `<div class="stack">
      <div class="card"><p class="label-mono">COACH NOTES</p><div class="sec" style="margin-top:8px;font-size:12.5px;line-height:1.5">${esc(b.notes)}</div></div>
      <div class="card"><p class="label-mono" style="margin-bottom:10px">SESSION TARGETS</p>
        <div class="stack">${b.targets.map((t) => `<div class="between"><span class="muted" style="font-size:12px">${esc(t.label)}</span><span style="font-weight:700">${esc(t.value)}</span></div>`).join("")}</div></div>
      <div class="note-green"><p class="label-mono" style="color:var(--train)">PROGRESSION ENGINE</p><div style="margin-top:6px;font-size:12.5px">Deadlift cleared last week at RPE 8 — adding +2.5 kg. Rows held to bank recovery for Thursday's legs.</div></div>
      <button class="btn btn-outline btn-block" data-action="swap-exercise">Swap an exercise ${I.arrowRight(15)}</button>
    </div>`;

    return `<div class="screen-inner">
      ${crumb(b.crumb)}
      <button class="backchev mobile-only" data-action="back">${I.chevronLeft(20)} Plan</button>
      ${head("Workout · Ready in Hevy", b.title,
        `<span class="pill pill-green"><span class="dot"></span>Ready in Hevy · ${esc(b.synced)}</span>
         <button class="btn-text" data-action="copy-workout">${I.copy(15)} Copy workout</button>
         <button class="btn btn-primary" data-action="open-hevy">Open in Hevy</button>`, "desktop-only")}
      <div class="row wrap mobile-only" style="margin:-4px 0 14px">
        <span class="pill pill-green"><span class="dot"></span>Ready in Hevy · ${esc(b.synced)}</span>
        <button class="btn btn-primary" data-action="open-hevy">Open in Hevy</button>
        <button class="btn-text" data-action="copy-workout">${I.copy(15)} Copy</button>
        <button class="btn-text" data-action="sync">${I.refresh(15)} Sync latest</button>
        <button class="btn-text" data-action="replan-today">Re-plan</button>
      </div>
      <div class="muted" style="font-size:12px;margin-bottom:12px">${esc(b.summary)} · <span class="pill pill-blue" style="vertical-align:middle">STRENGTH</span></div>
      <div class="cols c-1_55">
        <div class="stack">${b.exercises.map(exCard).join("")}</div>
        ${right}
      </div>
    </div>`;
  }

  // ------------------------------------------------------------------- Plan vs Actual
  function actual() {
    const pa = STATE.planVsActual;
    const weekdays = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
    const cell = (c) => {
      if (!c) return `<div class="calcell empty"></div>`;
      const cls = c.s === "today" ? "today" : c.s;
      return `<div class="calcell click ${cls}" data-day="${c.n}"><span class="n">${c.n}</span><span class="nm">${esc(c.nm)}</span>${c.tag ? `<span class="tag">${esc(c.tag)}</span>` : ""}</div>`;
    };
    const calendar = `
      <div class="card desktop-only" data-cal-grid>
        <div class="between" style="margin-bottom:12px"><p class="label-mono">${esc(pa.monthLabel)}</p><span class="pill pill-green">ADHERENCE ${pa.adherence}%</span></div>
        <div class="calgrid">${weekdays.map((d) => `<div class="calhead">${d}</div>`).join("")}</div>
        <div class="calgrid" style="margin-top:6px">${pa.weeks.map((w) => w.map(cell).join("")).join("")}</div>
      </div>`;

    const detail = `<div class="card" id="pa-detail"></div>`;

    // mobile: 5-day mini strip + featured + list
    const stripDays = [11, 12, 13, 15, 16, 17];
    const strip = `<div class="row mobile-only" style="overflow-x:auto;gap:8px;margin-bottom:12px">${stripDays.map((n) => {
      const d = pa.days[n]; const sc = { "ON PLAN": "green", MISSED: "orange", REPLACED: "amber", PLANNED: "blue" }[d.status];
      return `<button class="calcell click ${n === pa.selectedDay ? "today" : sc}" data-day="${n}" style="min-width:62px;flex:0 0 auto"><span class="n">${n}</span><span class="nm">${esc(d.planned.split(" ")[0])}</span></button>`;
    }).join("")}</div>`;

    const mobileList = [12, 10].map((n) => {
      const d = pa.days[n]; const sc = { "ON PLAN": "green", MISSED: "orange", REPLACED: "amber", PLANNED: "blue" }[d.status];
      return `<div class="tile"><div class="between"><span class="label-mono">${esc(d.date)}</span>${pill(sc, d.status)}</div><div class="muted" style="font-size:12px;margin-top:6px">Planned ${esc(d.planned)} · Actual ${esc(d.actual)}</div></div>`;
    }).join("");

    return `<div class="screen-inner">
      ${head("Plan vs Actual", "This block",
        `<span class="pill pill-green">ADHERENCE ${pa.adherence}%</span>
         <button class="btn-text" data-action="sync">${I.refresh(15)} Sync latest</button>`)}
      ${strip}
      <div class="cols c-1_4">
        <div class="stack">${calendar}<div class="mobile-only stack">${detail}${mobileList}</div></div>
        <div class="desktop-only">${detail}</div>
      </div>
    </div>`;
  }

  // render detail panel content (also called on day-select)
  function paDetailHtml(n) {
    const d = STATE.planVsActual.days[n] || STATE.planVsActual.days[11];
    const sc = { "ON PLAN": "green", MISSED: "orange", REPLACED: "amber", PLANNED: "blue" }[d.status] || "muted";
    return `
      <div class="between"><div style="font-weight:760;font-size:15px">${esc(d.date)}</div>${pill(sc, d.status)}</div>
      <div class="grid2" style="margin-top:14px">
        <div class="tile"><p class="label-mono">PLANNED</p><div style="margin-top:6px;font-weight:700">${esc(d.planned)}</div></div>
        <div class="tile"><p class="label-mono">ACTUAL</p><div style="margin-top:6px;font-weight:700;color:${d.ac}">${esc(d.actual)}</div></div>
      </div>
      <div style="margin-top:14px"><p class="label-mono">DIFFERENCE</p><div class="sec" style="margin-top:6px;font-size:12.5px;line-height:1.5">${esc(d.diff)}</div></div>
      <div class="note-violet" style="margin-top:14px"><p class="label-mono" style="color:var(--rest-light)">RECOVERY IMPACT</p><div style="margin-top:6px;font-size:12.5px;line-height:1.5">${esc(d.impact)}</div></div>
      <button class="btn btn-outline btn-block" style="margin-top:14px" data-action="open-day">Open full day ${window.ICONS.arrowRight(15)}</button>`;
  }

  // ------------------------------------------------------------------- Training Blocks
  function blocks() {
    const b = STATE.trainingBlock;
    const pct = Math.round((b.weekIndex / b.weekCount) * 100);
    const stateStyle = {
      done: "border-color:rgba(70,201,139,.3);background:rgba(70,201,139,.07)",
      current: "border-color:rgba(79,140,255,.6);background:rgba(79,140,255,.08);box-shadow:0 0 0 3px rgba(79,140,255,.1)",
      planned: "opacity:.55",
      deload: "border-style:dashed;border-color:var(--rest);background:rgba(155,140,255,.06)",
    };
    const stateTag = { done: pill("green", "✓ DONE"), current: pill("blue", "CURRENT", true), planned: pill("muted", "PLANNED"), deload: pill("violet", "DELOAD") };
    const timeline = b.phases.map((p) => `
      <div class="tile" style="${stateStyle[p.state]};text-align:center">
        <div class="label-mono">${esc(p.wk)}</div>
        <div style="font-weight:700;margin:6px 0;font-size:13px;color:${p.state === "current" ? "var(--strength-lighter)" : p.state === "deload" ? "var(--rest-light)" : "var(--text-primary)"}">${esc(p.phase)}</div>
        <div class="muted" style="font-size:11px;margin-bottom:8px">${p.sets} sets/mg</div>
        ${stateTag[p.state]}
      </div>`).join("");

    const maxSets = Math.max(...b.phases.map((p) => p.sets));
    const chart = `<div class="vbars" style="margin-top:22px">${b.phases.map((p) => `<div class="vb ${p.state === "current" ? "hi" : ""} ${p.state === "deload" ? "violet" : ""}" style="height:${(p.sets / maxSets) * 100}%"><span>${p.sets}</span></div>`).join("")}</div>
      <div class="row" style="margin-top:6px">${b.phases.map((p) => `<div class="label-mono" style="flex:1;text-align:center">${esc(p.wk)}</div>`).join("")}</div>`;

    const hero = `
      <div class="card" style="border-radius:var(--r-hero);background:linear-gradient(140deg,rgba(79,140,255,.14),var(--surface-1))">
        <div class="between"><span class="pill pill-blue">CURRENT BLOCK</span><span class="pill pill-green"><span class="dot live"></span>Active</span></div>
        <h2 class="screen-title" style="margin-top:12px">${esc(b.name)}</h2>
        <div class="muted" style="font-size:12px;margin-top:4px">${esc(b.sub)}</div>
        <div class="between" style="margin-top:14px"><span class="label-mono">WEEK ${b.weekIndex} / ${b.weekCount}</span><span class="sec" style="font-weight:700">${pct}% complete</span></div>
        <div class="bar" style="margin-top:8px"><i style="width:${pct}%"></i></div>
      </div>`;

    return `<div class="screen-inner">
      ${head("Training Blocks", "Periodization", `<button class="btn btn-secondary" data-action="new-block">${I.plus(15)} New block</button>`)}
      ${hero}
      <div class="grid3 desktop-only" style="grid-template-columns:repeat(6,1fr);margin-top:16px">${timeline}</div>
      <div class="stack mobile-only" style="margin-top:16px">${timeline}</div>
      <div class="cols c-1_3" style="margin-top:16px">
        <div class="card"><p class="label-mono">PLANNED WEEKLY VOLUME · SETS/MUSCLE GROUP</p>${chart}</div>
        <div class="stack">
          <div class="card"><p class="label-mono">THIS WEEK'S FOCUS</p><div class="sec" style="margin-top:8px;font-size:12.5px;line-height:1.5">${esc(b.focus)}</div></div>
          <div class="note-violet"><p class="label-mono" style="color:var(--rest-light)">DELOAD IN 3 WEEKS</p><div style="margin-top:6px;font-size:12.5px;line-height:1.5">${esc(b.deload)}</div></div>
        </div>
      </div>
    </div>`;
  }

  // ------------------------------------------------------------------- Recovery Rules
  function rules() {
    const card = (r, i) => `
      <div class="card">
        <div class="between">
          <div style="flex:1;padding-right:12px">
            <div style="font-weight:700;font-size:14px">${esc(r.label)}</div>
            <div class="muted" style="font-size:12px;margin-top:3px">${esc(r.description)}</div>
            ${r.threshold ? `<div class="gradient-bar" style="margin-top:11px;max-width:260px"><div class="marker" style="left:${r.threshold}%"></div></div>` : ""}
          </div>
          <button class="toggle ${r.enabled ? "on" : ""}" data-action="toggle-rule" data-idx="${i}" aria-label="Toggle rule"><span class="knob"></span></button>
        </div>
      </div>`;
    return `<div class="screen-inner">
      ${crumb(["Settings", "Recovery Rules"])}
      <button class="backchev mobile-only" data-action="back">${window.ICONS.chevronLeft(20)} Settings</button>
      ${head("Recovery Rules", "Guardrails")}
      <div class="stack">${STATE.recoveryRules.map(card).join("")}
        <button class="tile chip-add" style="border-style:dashed;text-align:center;color:var(--text-muted);font-weight:700" data-action="add-rule">+ Add a rule</button>
      </div>
    </div>`;
  }

  // ------------------------------------------------------------------- Coach Memory
  function memory() {
    const m = STATE.coachMemory;
    const grp = (label, items, chipClass = "chip", strike = false) => `
      <div class="card">
        <p class="label-mono" style="margin-bottom:11px">${esc(label)}</p>
        <div class="row wrap" style="gap:8px">
          ${items.map((it) => `<span class="chip ${chipClass} ${strike ? "chip-strike" : ""}"><span class="t">${esc(it)}</span><span class="x" data-action="remove-chip">×</span></span>`).join("")}
          <span class="chip chip-add" data-action="add-chip">+ add</span>
        </div>
      </div>`;
    return `<div class="screen-inner">
      ${crumb(["Profile", "Coach Memory"])}
      <button class="backchev mobile-only" data-action="back">${window.ICONS.chevronLeft(20)} Profile</button>
      ${head("Coach Memory", "What Coach plans around")}
      <div class="stack">
        ${grp("INJURIES", m.injuries, "chip-orange")}
        ${grp("SCHEDULE", m.schedule)}
        ${grp("EQUIPMENT", m.equipment)}
        <div class="cols" style="grid-template-columns:1fr 1fr;gap:13px">
          ${grp("PREFERS", m.prefers, "chip-green")}
          ${grp("DISLIKES", m.dislikes, "", true)}
        </div>
        <div class="grid2">
          <div class="card"><p class="label-mono">TARGET EVENT</p><div style="font-weight:760;font-size:15px;margin-top:8px">${esc(m.targetEvent.title)}</div><div class="muted" style="font-size:12px">${esc(m.targetEvent.meta)}</div></div>
          <div class="card"><p class="label-mono">BODY GOAL</p><div style="font-weight:760;font-size:15px;margin-top:8px">${esc(m.bodyGoal.title)}</div><div class="muted" style="font-size:12px">${esc(m.bodyGoal.meta)}</div></div>
        </div>
      </div>
    </div>`;
  }

  // ------------------------------------------------------------------- Goals & Body Mode
  function goals() {
    const g = STATE.bodyMode;
    const seg = g.modes.map((m) => `<button class="${m.key === g.mode ? "active" : ""}" data-action="set-mode" data-mode="${m.key}">${esc(m.label)}</button>`).join("");
    const hero = `
      <div class="card" style="border-radius:var(--r-hero);background:linear-gradient(140deg,rgba(155,140,255,.16),var(--surface-1))">
        <div class="between"><span class="pill pill-violet">BODY MODE</span><span class="label-mono">WEEK ${g.weekIndex} / ${g.weekCount}</span></div>
        <div class="hero-num" style="font-size:44px;color:var(--rest-light);margin-top:10px">${esc(g.modes.find((m) => m.key === g.mode).label)}</div>
        <div class="sec" style="font-size:12.5px;margin-top:6px;line-height:1.5">${esc(g.descriptor)}</div>
        <div class="segmented" style="margin-top:14px">${seg}</div>
      </div>`;
    const target = (t) => {
      const pct = Math.min(100, (t.value / t.target) * 100);
      const col = { train: "var(--train)", strength: "var(--strength)", cardio: "var(--cardio)" }[t.accent];
      return `<div><div class="between"><span class="sec" style="font-size:12px">${esc(t.label)}</span><span class="muted" style="font-size:12px">${t.value}/${t.target}${esc(t.unit)}</span></div>
        <div class="bar" style="margin-top:6px"><i style="width:${pct}%;background:${col}"></i></div></div>`;
    };
    const targets = `<div class="card"><p class="label-mono" style="margin-bottom:12px">WEEKLY TARGETS</p><div class="stack">${g.weeklyTargets.map(target).join("")}</div></div>`;
    const bias = `<div class="note-blue">${esc(g.bias)}</div>`;
    const trend = (label, t) => `<div class="card"><div class="between"><div><p class="label-mono">${esc(label)}</p><div class="big" style="font-size:22px;margin-top:4px">${esc(t.value)}</div></div><span class="pill ${label === "BODYWEIGHT" ? "pill-violet" : "pill-green"}">${esc(t.delta)}</span></div><div style="margin-top:10px">${spark(t.trend, t.color)}</div></div>`;
    const eventCards = `<div class="grid2">
      <div class="card"><p class="label-mono">TARGET EVENT</p><div style="font-weight:760;font-size:15px;margin-top:8px">${esc(STATE.coachMemory.targetEvent.title)}</div><div class="muted" style="font-size:12px">${esc(STATE.coachMemory.targetEvent.meta)}</div></div>
      <div class="card"><p class="label-mono">BODY GOAL</p><div style="font-weight:760;font-size:15px;margin-top:8px">${esc(STATE.coachMemory.bodyGoal.title)}</div><div class="muted" style="font-size:12px">${esc(STATE.coachMemory.bodyGoal.meta)}</div></div>
    </div>`;

    return `<div class="screen-inner">
      ${head("Goals & Body Mode", "Coaching mode")}
      <div class="cols c1-125">
        <div class="stack">${hero}${targets}${bias}</div>
        <div class="stack">${trend("BODYWEIGHT", g.weight)}${trend("BODY FAT", g.bodyFat)}${eventCards}</div>
      </div>
    </div>`;
  }

  // ------------------------------------------------------------------- Notifications
  function notifications() {
    const colorClass = { blue: "note-blue", amber: "warn", orange: "note-violet", green: "note-green" };
    const nudge = (n) => `
      <div class="${n.color === "orange" ? "" : ""}" style="${n.color === "orange" ? "border:1px solid rgba(255,107,74,.3);background:rgba(255,107,74,.08);color:var(--cardio-lighter)" : ""};border-radius:var(--r-card);padding:14px" class2="">
        <div class="${colorClass[n.color] || ""}" style="border:0;padding:0;background:transparent">
          <div style="font-weight:700;font-size:13.5px">${esc(n.title)}</div>
          <div style="font-size:12.5px;margin-top:4px;opacity:.9">${esc(n.body)}</div>
          ${n.actions.length ? `<div class="row" style="margin-top:11px">${n.actions.map((a) => `<button class="btn btn-secondary" data-action="nudge-action" style="padding:8px 13px">${esc(a)}</button>`).join("")}</div>` : ""}
        </div>
      </div>`;
    // Use proper colored containers
    const nudgeFeed = STATE.nudges.map((n) => {
      const cls = colorClass[n.color] || "card";
      return `<div class="${cls}">
        <div style="font-weight:700;font-size:13.5px">${esc(n.title)}</div>
        <div style="font-size:12.5px;margin-top:4px;opacity:.92">${esc(n.body)}</div>
        ${n.actions.length ? `<div class="row" style="margin-top:11px">${n.actions.map((a) => `<button class="btn btn-secondary" data-action="nudge-action" style="padding:8px 13px">${esc(a)}</button>`).join("")}</div>` : ""}
      </div>`;
    }).join("");

    const prefs = STATE.notificationPrefs.map((p, i) => `
      <div class="between" style="padding:11px 0;border-bottom:1px solid var(--hairline)">
        <div style="padding-right:12px"><div style="font-weight:700;font-size:13.5px">${esc(p.label)}</div><div class="muted" style="font-size:11.5px">${esc(p.description)}</div></div>
        <button class="toggle ${p.enabled ? "on" : ""}" data-action="toggle-pref" data-idx="${i}" aria-label="Toggle"><span class="knob"></span></button>
      </div>`).join("");

    // mobile lock screen
    const lock = `
      <div class="lockscreen mobile-only">
        <div class="lock-clock"><div class="t num">6:32</div><div class="d">Wednesday, June 17</div></div>
        ${STATE.nudges.map((n) => `<div class="notif"><div style="font-weight:700;font-size:13px">${esc(n.title)}</div><div class="muted" style="font-size:12px;margin-top:3px">${esc(n.body)}</div></div>`).join("")}
      </div>`;

    return `<div class="screen-inner">
      ${crumb(["Settings", "Notifications"])}
      <button class="backchev mobile-only" data-action="back">${window.ICONS.chevronLeft(20)} Settings</button>
      ${head("Notifications & Nudges", "Stay on plan")}
      ${lock}
      <div class="cols c-1_3 desktop-only">
        <div class="stack">${nudgeFeed}</div>
        <div class="card"><p class="label-mono" style="margin-bottom:6px">PREFERENCES</p>${prefs}</div>
      </div>
      <div class="card mobile-only" style="margin-top:14px"><p class="label-mono" style="margin-bottom:6px">PREFERENCES</p>${prefs}</div>
    </div>`;
  }

  // ------------------------------------------------------------------- Chat
  function chat() {
    return `
      <div class="chat-msgs" id="chat-msgs"></div>
      <form class="composer" id="composer">
        <textarea id="chat-input" rows="1" placeholder="Ask your coach…" autocomplete="off"></textarea>
        <button type="submit" aria-label="Send">➤</button>
      </form>`;
  }

  return { today, plan, builder, actual, paDetailHtml, blocks, rules, memory, goals, notifications, chat };
})();
