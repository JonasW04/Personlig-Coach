/* ============================================================
   stats.js — refreshed Stats dashboard
   3 layout variations + shared builders. Exposes window.CoachStats
   ============================================================ */
(function () {
  "use strict";
  const D = () => window.CoachData;
  const CC = () => window.CoachCharts;

  const state = {
    rangeKey: "3m",
    customStart: null,
    customEnd: null,
    layout: "snapshot", // snapshot | split | activity
  };
  let uid = 0;
  const nid = (p) => `${p}-${++uid}`;

  // ---------- formatters ----------
  const nf = (n, dp = 0) => (n == null || isNaN(n)) ? "--" : Number(n).toLocaleString(undefined, { maximumFractionDigits: dp, minimumFractionDigits: dp >= 1 && n % 1 !== 0 ? dp : 0 });
  const hrs = (min) => (min / 60);
  function kFmt(v) {
    if (v == null) return "--";
    if (Math.abs(v) >= 1000) return (v / 1000).toFixed(Math.abs(v) >= 10000 ? 0 : 1) + "k";
    return String(Math.round(v));
  }
  function deltaPct(cur, prev) {
    if (prev == null || prev === 0) return null;
    return Math.round(((cur - prev) / prev) * 100);
  }
  function deltaHtml(d) {
    if (d == null) return "";
    if (d === 0) return `<span class="delta" style="color:var(--faint)">±0%</span>`;
    const up = d > 0;
    return `<span class="delta ${up ? "up" : "down"}">${up ? "▲" : "▼"} ${Math.abs(d)}%</span>`;
  }

  // ---------- range ----------
  function resolveRange() {
    if (state.rangeKey === "custom" && state.customStart && state.customEnd) {
      const a = state.customStart <= state.customEnd ? state.customStart : state.customEnd;
      const b = state.customStart <= state.customEnd ? state.customEnd : state.customStart;
      return { start: a, end: b };
    }
    return D().rangeBounds(state.rangeKey);
  }
  function prevRange(r) {
    const span = D().daysBetween(r.start, r.end);
    const prevEnd = D().iso(D().addDays(D().parse(r.start), -1));
    const prevStart = D().iso(D().addDays(D().parse(prevEnd), -span));
    return { start: prevStart, end: prevEnd };
  }
  function rangeLabel(r) {
    const f = (iso) => new Date(iso + "T00:00:00").toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
    return `${f(r.start)} – ${f(r.end)}`;
  }

  // ---------- metric card ----------
  function metric({ label, value, unit, meta, accent, dot, delta }) {
    const acc = accent ? ` accent-${accent}` : "";
    const dotHtml = dot ? `<span class="m-dot" style="background:${dot}"></span>` : "";
    const unitHtml = unit ? `<span class="unit">${unit}</span>` : "";
    const metaHtml = meta || delta != null
      ? `<div class="m-meta">${deltaHtml(delta)}<span>${meta || ""}</span></div>` : "";
    return `<div class="metric${acc}">
      <div class="m-top">${dotHtml}<span class="m-label">${label}</span></div>
      <div class="m-value">${value}${unitHtml}</div>
      ${metaHtml}
    </div>`;
  }

  function metricsFor(s, prev, set) {
    const C = CC().THEME;
    const all = {
      active:  metric({ label: "Active days", value: nf(s.activeDays), meta: `of ${s.totalDays} days`, accent: "good", delta: deltaPct(s.activeDays, prev.activeDays) }),
      streak:  metric({ label: "Current streak", value: nf(s.streak), unit: "days", meta: "consecutive", accent: "warn" }),
      sets:    metric({ label: "Sets completed", value: nf(s.sets), accent: "strength", delta: deltaPct(s.sets, prev.sets) }),
      shours:  metric({ label: "Strength time", value: nf(hrs(s.strengthMin), 1), unit: "h", accent: "strength", delta: deltaPct(s.strengthMin, prev.strengthMin) }),
      chours:  metric({ label: "Cardio time", value: nf(hrs(s.cardioMin), 1), unit: "h", accent: "cardio", delta: deltaPct(s.cardioMin, prev.cardioMin) }),
      tonnage: metric({ label: "Volume lifted", value: kFmt(s.tonnage), unit: "kg", accent: "strength", delta: deltaPct(s.tonnage, prev.tonnage) }),
      km:      metric({ label: "Cardio distance", value: nf(s.km, 1), unit: "km", accent: "cardio", delta: deltaPct(s.km, prev.km) }),
      sessions:metric({ label: "Sessions", value: nf(s.liftSessions + s.cardioSessions), meta: `${s.liftSessions} lift · ${s.cardioSessions} cardio` }),
    };
    return set.map((k) => all[k]).join("");
  }

  // ---------- shared chart builders ----------
  function trainingTimeChart(canvas, ser) {
    const C = CC().THEME;
    const labels = ser.points.map((p) => CC().fmtLabel(p.key, ser.daily));
    CC().mount(canvas, {
      type: "bar",
      data: { labels, datasets: [
        CC().barDataset("Strength", ser.points.map((p) => +(p.strengthMin / 60).toFixed(1)), C.strength, { stack: "t", radius: 3 }),
        CC().barDataset("Cardio", ser.points.map((p) => +(p.cardioMin / 60).toFixed(1)), C.cardio, { stack: "t", radius: 5 }),
      ] },
      options: CC().options({ y: { stacked: true, ticks: { callback: (v) => v + "h" } }, x: { stacked: true } }),
    });
  }
  function volumeChart(canvas, ser) {
    const C = CC().THEME;
    const labels = ser.points.map((p) => CC().fmtLabel(p.key, ser.daily));
    CC().mount(canvas, {
      type: "bar",
      data: { labels, datasets: [CC().barDataset("Volume", ser.points.map((p) => p.tonnage), C.strength, { radius: 5 })] },
      options: CC().options({ y: { ticks: { callback: kFmt } } }),
    });
  }
  function distanceChart(canvas, ser) {
    const C = CC().THEME;
    const labels = ser.points.map((p) => CC().fmtLabel(p.key, ser.daily));
    CC().mount(canvas, {
      type: "bar",
      data: { labels, datasets: [CC().barDataset("Distance", ser.points.map((p) => +p.km.toFixed(1)), C.cardio, { radius: 5 })] },
      options: CC().options({ y: { ticks: { callback: (v) => v + " km" } } }),
    });
  }

  // ---------- legend helper ----------
  function legendHtml(items) {
    return `<div class="legend">` + items.map((i) => `<span class="lg"><span class="sw" style="background:${i.c}"></span>${i.l}</span>`).join("") + `</div>`;
  }

  // ---------- exercise panel ----------
  function buildExercisePanel(mountEl, range, opts = {}) {
    const C = CC().THEME;
    const list = D().exerciseList();
    const def = opts.default && list.includes(opts.default) ? opts.default : (list[0] || null);
    const repsId = nid("ex-reps"), volId = nid("ex-vol"), selId = nid("ex-sel"), statId = nid("ex-stat");
    mountEl.innerHTML = `
      <div class="panel-head ex-head">
        <div>
          <h3>Per-exercise progress</h3>
          <div class="sub">Reps & volume per session</div>
        </div>
        <div class="ex-select-wrap">
          <select class="ex-select" id="${selId}">
            ${list.map((n) => `<option value="${n}"${n === def ? " selected" : ""}>${n}</option>`).join("")}
          </select>
        </div>
      </div>
      <div class="ex-stats" id="${statId}"></div>
      <div class="ex-charts">
        <div>
          ${legendHtml([{ c: C.strength, l: "Volume (kg)" }])}
          <div class="chart-frame" style="margin-top:8px"><canvas id="${volId}"></canvas></div>
        </div>
        <div>
          ${legendHtml([{ c: C.good, l: "Total reps" }])}
          <div class="chart-frame" style="margin-top:8px"><canvas id="${repsId}"></canvas></div>
        </div>
      </div>`;

    function update(name) {
      const pts = D().exerciseSeries(name, range.start, range.end);
      const statEl = mountEl.querySelector("#" + statId);
      if (!pts.length) {
        statEl.innerHTML = `<div class="ex-stat"><div class="l">No ${name} sessions in this range</div></div>`;
        CC().mount(mountEl.querySelector("#" + volId), { type: "bar", data: { labels: [], datasets: [] }, options: CC().options() });
        CC().mount(mountEl.querySelector("#" + repsId), { type: "bar", data: { labels: [], datasets: [] }, options: CC().options() });
        return;
      }
      const last = pts[pts.length - 1];
      const totalVol = pts.reduce((a, p) => a + p.volume, 0);
      const totalReps = pts.reduce((a, p) => a + p.reps, 0);
      const bestE1rm = Math.max(...pts.map((p) => p.e1rm));
      statEl.innerHTML = `
        <div class="ex-stat"><div class="v">${pts.length}</div><div class="l">Sessions</div></div>
        <div class="ex-stat"><div class="v">${kFmt(totalVol)}<span class="unit">kg</span></div><div class="l">Total volume</div></div>
        <div class="ex-stat"><div class="v">${nf(totalReps)}</div><div class="l">Total reps</div></div>
        <div class="ex-stat"><div class="v">${nf(last.topWeight, 1)}<span class="unit">kg</span></div><div class="l">Top set (latest)</div></div>
        <div class="ex-stat"><div class="v">${nf(bestE1rm)}<span class="unit">kg</span></div><div class="l">Best est. 1RM</div></div>`;
      const labels = pts.map((p) => CC().fmtLabel(p.date, true));
      CC().mount(mountEl.querySelector("#" + volId), {
        type: "bar",
        data: { labels, datasets: [CC().barDataset("Volume", pts.map((p) => p.volume), C.strength, { radius: 4 })] },
        options: CC().options({ y: { ticks: { callback: kFmt } }, xTicks: 8 }),
      });
      CC().mount(mountEl.querySelector("#" + repsId), {
        type: "line",
        data: { labels, datasets: [CC().lineDataset("Reps", pts.map((p) => p.reps), C.good, true)] },
        options: CC().options({ xTicks: 8 }),
      });
    }
    mountEl.querySelector("#" + selId).addEventListener("change", (e) => update(e.target.value));
    update(def);
  }

  // ---------- LAYOUT A: SNAPSHOT ----------
  function layoutSnapshot(root, ctx) {
    const { s, ser, range } = ctx;
    const C = CC().THEME;
    const ttId = nid("tt"), volId = nid("vol"), distId = nid("dist");
    root.innerHTML = `
      <div class="metric-grid">${metricsFor(s, ctx.prev, ["active", "streak", "sets", "sessions", "shours", "chours", "tonnage", "km"])}</div>

      <div class="section-title"><h3>Trends</h3><div class="rule"></div></div>
      <div class="panel">
        <div class="panel-head">
          <div><h3>Training time</h3><div class="sub">Hours per ${ser.daily ? "day" : "week"}, strength + cardio</div></div>
          ${legendHtml([{ c: C.strength, l: "Strength" }, { c: C.cardio, l: "Cardio" }])}
        </div>
        <div class="chart-frame tall"><canvas id="${ttId}"></canvas></div>
      </div>
      <div class="charts-2">
        <div class="panel">
          <div class="panel-head"><div><h3>Strength volume</h3><div class="sub">Total kg lifted per ${ser.daily ? "day" : "week"}</div></div><span class="unit">kg</span></div>
          <div class="chart-frame"><canvas id="${volId}"></canvas></div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><h3>Cardio distance</h3><div class="sub">Distance per ${ser.daily ? "day" : "week"}</div></div><span class="unit">km</span></div>
          <div class="chart-frame"><canvas id="${distId}"></canvas></div>
        </div>
      </div>

      <div class="section-title"><h3>Exercises</h3><div class="rule"></div></div>
      <div class="panel" id="ex-panel-a"></div>

      <div class="section-title"><h3>Activity</h3><div class="rule"></div></div>
      <div class="panel"><div id="cal-a"></div></div>`;

    trainingTimeChart(root.querySelector("#" + ttId), ser);
    volumeChart(root.querySelector("#" + volId), ser);
    distanceChart(root.querySelector("#" + distId), ser);
    buildExercisePanel(root.querySelector("#ex-panel-a"), range, { default: "Bench Press" });
    window.CoachCalendar.create(root.querySelector("#cal-a"), { defaultMode: "month", range }).render();
  }

  const LAYOUTS = { snapshot: layoutSnapshot };

  // ---------- render ----------
  function render() {
    const content = document.getElementById("stats-content");
    if (!content) return;
    CC().base();
    CC().destroyAll();
    const range = resolveRange();
    const s = D().summarize(range.start, range.end);
    const prev = D().summarize(...Object.values(prevRange(range)));
    const ser = D().series(range.start, range.end);
    const sub = document.getElementById("stats-range-label");
    if (sub) sub.textContent = rangeLabel(range);
    (LAYOUTS[state.layout] || layoutSnapshot)(content, { s, prev, ser, range });
  }

  // ---------- controls wiring ----------
  function initControls() {
    const chips = document.getElementById("range-chips");
    const custom = document.getElementById("range-custom");
    const inStart = document.getElementById("custom-start");
    const inEnd = document.getElementById("custom-end");

    chips.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
      chips.querySelectorAll(".chip").forEach((x) => x.classList.toggle("active", x === c));
      state.rangeKey = c.dataset.range;
      if (state.rangeKey === "custom") {
        custom.style.display = "flex";
        if (!state.customStart) {
          const r = D().rangeBounds("3m");
          state.customStart = r.start; state.customEnd = r.end;
          inStart.value = r.start; inEnd.value = r.end;
        }
      } else {
        custom.style.display = "none";
      }
      render();
    }));

    [inStart, inEnd].forEach((inp) => inp.addEventListener("change", () => {
      state.customStart = inStart.value; state.customEnd = inEnd.value;
      state.rangeKey = "custom";
      if (state.customStart && state.customEnd) render();
    }));
    inStart.min = D().firstDate; inStart.max = D().lastDate;
    inEnd.min = D().firstDate; inEnd.max = D().lastDate;
  }

  function setLayout(name) {
    if (!LAYOUTS[name]) return;
    state.layout = name;
    render();
  }
  function setRange(key) {
    const chips = document.getElementById("range-chips");
    const target = chips && chips.querySelector(`.chip[data-range="${key}"]`);
    if (target) target.click();
  }

  let started = false;
  function init() {
    if (started) return;
    started = true;
    initControls();
    render();
  }

  window.CoachStats = { init, render, setLayout, setRange, state };
})();
