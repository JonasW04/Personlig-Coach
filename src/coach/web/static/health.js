/* ============================================================
   health.js — Garmin recovery & readiness dashboard
   Snapshot cards + recovery trend charts + coach health insight.
   Exposes window.CoachHealth
   ============================================================ */
(function () {
  "use strict";
  const CC = () => window.CoachCharts;

  const RANGES = { "14d": 14, "30d": 30, "90d": 90 };
  const state = { rangeKey: "30d" };
  let uid = 0;
  const nid = (p) => `h-${p}-${++uid}`;

  let allDays = [];
  let loaded = false;
  let loadError = null;

  // ---------- formatters ----------
  const nf = (n, dp = 0) =>
    n == null || isNaN(n)
      ? "--"
      : Number(n).toLocaleString(undefined, { maximumFractionDigits: dp, minimumFractionDigits: 0 });

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }

  function fmtSleep(hours) {
    if (hours == null || isNaN(hours)) return "--";
    const h = Math.floor(hours);
    const m = Math.round((hours - h) * 60);
    return `${h}h ${m.toString().padStart(2, "0")}m`;
  }

  function fmtDate(iso) {
    if (!iso) return "";
    return new Date(iso + "T00:00:00").toLocaleDateString([], { month: "short", day: "numeric" });
  }

  // Garmin status keys like "PRODUCTIVE_2" → "Productive".
  function prettyStatus(s) {
    if (!s) return "--";
    return String(s)
      .split("_")
      .filter((w) => !/^\d+$/.test(w))
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(" ");
  }

  // ---------- data ----------
  async function fetchData() {
    loadError = null;
    try {
      const resp = await fetch("/api/health");
      if (resp.status === 401) { location.href = "/login"; return; }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      allDays = data.days || [];
      loaded = true;
    } catch (err) {
      loadError = err.message;
      loaded = true;
    }
  }

  function rangedDays() {
    const n = RANGES[state.rangeKey] || 30;
    return allDays.slice(-n);
  }

  // Latest day that has a non-null value for `key` (snapshot is robust to gaps).
  function latest(key) {
    for (let i = allDays.length - 1; i >= 0; i--) {
      if (allDays[i][key] != null) return allDays[i];
    }
    return null;
  }
  function latestVal(key) {
    const d = latest(key);
    return d ? d[key] : null;
  }

  // ---------- metric card (matches stats.js .metric markup) ----------
  function metric({ label, value, unit, meta, accent, dot }) {
    const acc = accent ? ` accent-${accent}` : "";
    const dotHtml = dot ? `<span class="m-dot" style="background:${dot}"></span>` : "";
    const unitHtml = unit ? `<span class="unit">${unit}</span>` : "";
    const metaHtml = meta ? `<div class="m-meta"><span>${meta}</span></div>` : "";
    return `<div class="metric${acc}">
      <div class="m-top">${dotHtml}<span class="m-label">${esc(label)}</span></div>
      <div class="m-value">${value}${unitHtml}</div>
      ${metaHtml}
    </div>`;
  }

  // Garmin level words → metric accent colour.
  function levelAccent(level) {
    const l = String(level || "").toUpperCase();
    if (/HIGH|READY|GOOD|BALANCED|PRODUCTIVE|PEAKING/.test(l)) return "good";
    if (/MODERATE|MEDIUM|MAINTAINING|RECOVERY/.test(l)) return "warn";
    if (/LOW|POOR|UNPRODUCTIVE|STRAINED|OVERREACHING|DETRAINING/.test(l)) return "cardio";
    return null;
  }

  function snapshotCards() {
    const tr = latest("training_readiness");
    const sleep = latest("sleep_hours");
    const hrv = latest("hrv");
    const bb = latest("body_battery_high");
    const cards = [];

    // Training readiness
    if (tr) {
      const lvl = tr.training_readiness_level;
      cards.push(metric({
        label: "Training readiness",
        value: nf(tr.training_readiness),
        accent: levelAccent(lvl) || "good",
        meta: lvl ? esc(lvl) : "",
      }));
    }

    // Body Battery
    if (bb) {
      cards.push(metric({
        label: "Body Battery",
        value: nf(bb.body_battery_high),
        accent: "good",
        meta: bb.body_battery_low != null ? `low ${nf(bb.body_battery_low)}` : "",
      }));
    }

    // Sleep
    if (sleep) {
      const bits = [];
      if (sleep.sleep_score != null) bits.push(`score ${nf(sleep.sleep_score)}`);
      if (sleep.deep_sleep_hours != null) bits.push(`deep ${fmtSleep(sleep.deep_sleep_hours)}`);
      cards.push(metric({
        label: "Sleep last night",
        value: fmtSleep(sleep.sleep_hours),
        accent: "strength",
        meta: bits.join(" · "),
      }));
    }

    // HRV
    if (hrv) {
      let meta = hrv.hrv_status ? esc(hrv.hrv_status) : "";
      if (hrv.hrv_baseline_low != null && hrv.hrv_baseline_high != null) {
        meta += `${meta ? " · " : ""}base ${nf(hrv.hrv_baseline_low)}–${nf(hrv.hrv_baseline_high)}`;
      }
      cards.push(metric({
        label: "HRV (overnight)",
        value: nf(hrv.hrv),
        unit: "ms",
        accent: levelAccent(hrv.hrv_status) || "good",
        meta,
      }));
    }

    // VO2max
    const vo2d = latest("vo2max");
    if (vo2d != null) {
      const fa = vo2d.fitness_age;
      cards.push(metric({
        label: "VO₂max",
        value: nf(vo2d.vo2max, 1),
        accent: "cardio",
        meta: fa != null ? `fitness age ${nf(fa)}` : "",
      }));
    }

    // Resting HR (with 7-day baseline if present)
    const rhrd = latest("resting_hr");
    if (rhrd != null) {
      const avg7 = rhrd.resting_hr_7d_avg;
      cards.push(metric({
        label: "Resting HR",
        value: nf(rhrd.resting_hr),
        unit: "bpm",
        accent: "cardio",
        meta: avg7 != null ? `7-day avg ${nf(avg7)}` : "",
      }));
    }

    // Training status / load + ACWR
    const ts = latest("training_status");
    if (ts && ts.training_status) {
      const bits = [];
      if (ts.acute_load != null) bits.push(`acute ${nf(ts.acute_load)}`);
      if (ts.acwr != null) bits.push(`ACWR ${nf(ts.acwr, 2)}`);
      cards.push(metric({
        label: "Training status",
        value: `<span style="font-size:18px">${esc(prettyStatus(ts.training_status))}</span>`,
        accent: levelAccent(ts.training_status),
        meta: bits.join(" · "),
      }));
    }

    // ACWR (acute:chronic workload ratio) — sweet spot ~0.8-1.3
    const acwrd = latest("acwr");
    if (acwrd != null && acwrd.acwr != null) {
      cards.push(metric({
        label: "Load ratio (ACWR)",
        value: nf(acwrd.acwr, 2),
        accent: levelAccent(acwrd.acwr_status) || "good",
        meta: acwrd.acwr_status ? prettyStatus(acwrd.acwr_status) : "",
      }));
    }

    // Overnight breathing rate
    const resp = latestVal("respiration");
    if (resp != null) {
      cards.push(metric({ label: "Sleep respiration", value: nf(resp), unit: "br/min", accent: "strength" }));
    }

    // Overnight blood oxygen
    const spo2 = latestVal("spo2");
    if (spo2 != null) {
      cards.push(metric({ label: "Sleep SpO₂", value: nf(spo2), unit: "%", accent: "good" }));
    }

    // Avg stress
    const stress = latestVal("avg_stress");
    if (stress != null) {
      cards.push(metric({ label: "Avg stress", value: nf(stress), accent: "warn" }));
    }

    return cards.join("");
  }

  // ---------- trend charts ----------
  function legendHtml(items) {
    return `<div class="legend">` +
      items.map((i) => `<span class="lg"><span class="sw" style="background:${i.c}"></span>${i.l}</span>`).join("") +
      `</div>`;
  }

  function lineChart(canvas, days, key, color, opts = {}) {
    if (!canvas) return;
    const labels = days.map((d) => CC().fmtLabel(d.date, true));
    const data = days.map((d) => d[key]);
    CC().mount(canvas, {
      type: "line",
      data: { labels, datasets: [CC().lineDataset(opts.label || key, data, color, opts.fill !== false)] },
      options: CC().options({ beginAtZero: opts.beginAtZero === true, xTicks: 7, y: opts.y || {} }),
    });
  }

  // Acute load (filled) vs chronic baseline (dashed line).
  function loadChart(canvas, days) {
    if (!canvas) return;
    const C = CC().THEME;
    const labels = days.map((d) => CC().fmtLabel(d.date, true));
    const datasets = [CC().lineDataset("Acute load", days.map((d) => d.acute_load), C.strength, true)];
    if (days.some((d) => d.chronic_load != null)) {
      datasets.push({
        label: "Chronic load", data: days.map((d) => d.chronic_load),
        borderColor: CC().alpha(C.muted, 0.8), borderWidth: 1.5, borderDash: [5, 4],
        tension: 0.3, spanGaps: true, pointRadius: 0, pointHoverRadius: 0,
        fill: false, backgroundColor: "transparent",
      });
    }
    CC().mount(canvas, {
      type: "line",
      data: { labels, datasets },
      options: CC().options({ beginAtZero: true, xTicks: 7 }),
    });
  }

  function hrvChart(canvas, days) {
    if (!canvas) return;
    const C = CC().THEME;
    const labels = days.map((d) => CC().fmtLabel(d.date, true));
    const datasets = [CC().lineDataset("HRV", days.map((d) => d.hrv), C.good, true)];
    const hasBaseline = days.some((d) => d.hrv_baseline_low != null);
    if (hasBaseline) {
      const dashed = (label, vals, col) => ({
        label, data: vals, borderColor: CC().alpha(col, 0.6), borderWidth: 1.5,
        borderDash: [5, 4], tension: 0, spanGaps: true, pointRadius: 0,
        pointHoverRadius: 0, fill: false, backgroundColor: "transparent",
      });
      datasets.push(dashed("Baseline low", days.map((d) => d.hrv_baseline_low), C.muted));
      datasets.push(dashed("Baseline high", days.map((d) => d.hrv_baseline_high), C.muted));
    }
    CC().mount(canvas, {
      type: "line",
      data: { labels, datasets },
      options: CC().options({ beginAtZero: false, xTicks: 7, y: { ticks: { callback: (v) => v + " ms" } } }),
    });
  }

  function sleepChart(canvas, days) {
    if (!canvas) return;
    const C = CC().THEME;
    const labels = days.map((d) => CC().fmtLabel(d.date, true));
    const r1 = (v) => (v == null ? null : +Number(v).toFixed(2));
    const datasets = [
      CC().barDataset("Deep", days.map((d) => r1(d.deep_sleep_hours)), C.strength, { stack: "s", radius: 0 }),
      CC().barDataset("REM", days.map((d) => r1(d.rem_sleep_hours)), C.cardio, { stack: "s", radius: 0 }),
      CC().barDataset("Light", days.map((d) => r1(d.light_sleep_hours)), C.muted, { stack: "s", radius: 4 }),
    ];
    CC().mount(canvas, {
      type: "bar",
      data: { labels, datasets },
      options: CC().options({ y: { stacked: true, ticks: { callback: (v) => v + "h" } }, x: { stacked: true }, xTicks: 7 }),
    });
  }

  // ---------- coach health insight (report kind=health) ----------
  function wireInsight(root) {
    const body = root.querySelector("#health-insight-body");
    const btn = root.querySelector("[data-health-generate]");
    if (!body || !btn) return;

    async function load() {
      try {
        const resp = await fetch("/api/reports?kind=health&limit=1");
        if (!resp.ok) return;
        const d = await resp.json();
        const r = d.reports && d.reports[0];
        if (!r) {
          body.innerHTML = `<div class="empty-block compact">No health read yet. Generate one.</div>`;
          return;
        }
        const when = new Date(r.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
        body.innerHTML = `<div class="report-when">${esc(when)}</div>` +
          `<div class="report-md">${window.marked ? marked.parse(r.content || "") : esc(r.content)}</div>`;
      } catch (_) { /* ignore */ }
    }

    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const label = btn.textContent;
      btn.textContent = "Generating… (~1 min)";
      try {
        const resp = await fetch("/api/reports/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "health" }),
        });
        if (resp.status === 401) { location.href = "/login"; return; }
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        await load();
      } catch (err) {
        body.innerHTML = `<div class="empty-block compact">Failed: ${esc(err.message)}</div>`;
      } finally {
        btn.disabled = false;
        btn.textContent = label;
      }
    });

    load();
  }

  // ---------- render ----------
  function rangeLabel(days) {
    if (!days.length) return "No data yet";
    return `${fmtDate(days[0].date)} – ${fmtDate(days[days.length - 1].date)} · ${days.length} days`;
  }

  function render() {
    const content = document.getElementById("health-content");
    if (!content) return;
    CC().base();
    CC().destroyAll();

    const sub = document.getElementById("health-range-label");

    if (loadError) {
      if (sub) sub.textContent = "—";
      content.innerHTML = `<div class="empty-block">Couldn't load health data: ${esc(loadError)}</div>`;
      return;
    }
    if (!allDays.length) {
      if (sub) sub.textContent = "No data yet";
      content.innerHTML = `<div class="empty-block">No Garmin data yet. Connect Garmin (run <code>coach-garmin-auth</code>) and Sync to see recovery, sleep, HRV and training readiness here.</div>`;
      return;
    }

    const days = rangedDays();
    if (sub) sub.textContent = rangeLabel(days);
    const C = CC().THEME;

    const loadId = nid("load"), sleepId = nid("sleep"), hrvId = nid("hrv");
    const bbId = nid("bb"), rhrId = nid("rhr"), stressId = nid("stress");
    const vo2Id = nid("vo2"), acwrId = nid("acwr"), respId = nid("resp"), spo2Id = nid("spo2");

    const hasVo2 = days.some((d) => d.vo2max != null);
    const hasAcwr = days.some((d) => d.acwr != null);
    const hasResp = days.some((d) => d.respiration != null);
    const hasSpo2 = days.some((d) => d.spo2 != null);

    content.innerHTML = `
      <div class="panel">
        <div class="panel-head">
          <div><h3>Coach health read</h3><div class="sub">Recovery &amp; readiness from your Garmin data</div></div>
          <button class="secondary" type="button" data-health-generate>Generate</button>
        </div>
        <div id="health-insight-body" class="health-insight"><div class="empty-block compact">Loading…</div></div>
      </div>

      <div class="section-title"><h3>Now</h3><div class="rule"></div></div>
      <div class="metric-grid">${snapshotCards()}</div>

      <div class="section-title"><h3>Recovery trends</h3><div class="rule"></div></div>
      <div class="panel">
        <div class="panel-head"><div><h3>Training load</h3><div class="sub">Acute vs. chronic (baseline) load per day</div></div>${legendHtml([{ c: C.strength, l: "Acute load" }, { c: C.muted, l: "Chronic load" }])}</div>
        <div class="chart-frame tall"><canvas id="${loadId}"></canvas></div>
      </div>
      <div class="charts-2">
        ${hasAcwr ? `<div class="panel">
          <div class="panel-head"><div><h3>Load ratio (ACWR)</h3><div class="sub">Acute:chronic — sweet spot 0.8–1.3</div></div>${legendHtml([{ c: C.cardio, l: "ACWR" }])}</div>
          <div class="chart-frame"><canvas id="${acwrId}"></canvas></div>
        </div>` : ""}
        ${hasVo2 ? `<div class="panel">
          <div class="panel-head"><div><h3>VO₂max</h3><div class="sub">Aerobic fitness estimate</div></div>${legendHtml([{ c: C.cardio, l: "VO₂max" }])}</div>
          <div class="chart-frame"><canvas id="${vo2Id}"></canvas></div>
        </div>` : ""}
        <div class="panel">
          <div class="panel-head"><div><h3>Sleep</h3><div class="sub">Stages per night</div></div>${legendHtml([{ c: C.strength, l: "Deep" }, { c: C.cardio, l: "REM" }, { c: C.muted, l: "Light" }])}</div>
          <div class="chart-frame"><canvas id="${sleepId}"></canvas></div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><h3>HRV</h3><div class="sub">Overnight average vs. baseline</div></div>${legendHtml([{ c: C.good, l: "HRV" }, { c: C.muted, l: "Baseline" }])}</div>
          <div class="chart-frame"><canvas id="${hrvId}"></canvas></div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><h3>Body Battery</h3><div class="sub">Daily high</div></div>${legendHtml([{ c: C.good, l: "Body Battery" }])}</div>
          <div class="chart-frame"><canvas id="${bbId}"></canvas></div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><h3>Resting HR</h3><div class="sub">Beats per minute</div></div>${legendHtml([{ c: C.cardio, l: "Resting HR" }])}</div>
          <div class="chart-frame"><canvas id="${rhrId}"></canvas></div>
        </div>
        ${hasResp ? `<div class="panel">
          <div class="panel-head"><div><h3>Sleep respiration</h3><div class="sub">Overnight breaths per minute</div></div>${legendHtml([{ c: C.strength, l: "Respiration" }])}</div>
          <div class="chart-frame"><canvas id="${respId}"></canvas></div>
        </div>` : ""}
        ${hasSpo2 ? `<div class="panel">
          <div class="panel-head"><div><h3>Sleep SpO₂</h3><div class="sub">Overnight blood oxygen</div></div>${legendHtml([{ c: C.good, l: "SpO₂" }])}</div>
          <div class="chart-frame"><canvas id="${spo2Id}"></canvas></div>
        </div>` : ""}
        <div class="panel">
          <div class="panel-head"><div><h3>Stress</h3><div class="sub">Average daily stress</div></div>${legendHtml([{ c: "#e0a23b", l: "Stress" }])}</div>
          <div class="chart-frame"><canvas id="${stressId}"></canvas></div>
        </div>
      </div>`;

    loadChart(content.querySelector("#" + loadId), days);
    if (hasAcwr) lineChart(content.querySelector("#" + acwrId), days, "acwr", C.cardio, { label: "ACWR", beginAtZero: true });
    if (hasVo2) lineChart(content.querySelector("#" + vo2Id), days, "vo2max", C.cardio, { label: "VO₂max", fill: false, beginAtZero: false });
    sleepChart(content.querySelector("#" + sleepId), days);
    hrvChart(content.querySelector("#" + hrvId), days);
    lineChart(content.querySelector("#" + bbId), days, "body_battery_high", C.good, { label: "Body Battery", beginAtZero: true });
    lineChart(content.querySelector("#" + rhrId), days, "resting_hr", C.cardio, { label: "Resting HR", fill: false, beginAtZero: false });
    if (hasResp) lineChart(content.querySelector("#" + respId), days, "respiration", C.strength, { label: "Respiration", fill: false, beginAtZero: false });
    if (hasSpo2) lineChart(content.querySelector("#" + spo2Id), days, "spo2", C.good, { label: "SpO₂", fill: false, beginAtZero: false });
    lineChart(content.querySelector("#" + stressId), days, "avg_stress", "#e0a23b", { label: "Stress", beginAtZero: true });

    wireInsight(content);
  }

  // ---------- controls ----------
  function initControls() {
    const chips = document.getElementById("health-range-chips");
    if (!chips) return;
    chips.querySelectorAll(".chip").forEach((c) =>
      c.addEventListener("click", () => {
        chips.querySelectorAll(".chip").forEach((x) => x.classList.toggle("active", x === c));
        state.rangeKey = c.dataset.range;
        render();
      })
    );
  }

  async function reload() {
    await fetchData();
    render();
  }

  let started = false;
  async function init() {
    if (started) return;
    started = true;
    initControls();
    const content = document.getElementById("health-content");
    if (content) content.innerHTML = `<div class="empty-block">Loading…</div>`;
    await fetchData();
    render();
  }

  window.CoachHealth = { init, render, reload, state };
})();
