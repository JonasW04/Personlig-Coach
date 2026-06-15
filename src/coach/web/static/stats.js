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
    bodyCompositionMode: "mass", // mass | percent
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

  function fmtShortDate(iso) {
    if (!iso) return "";
    return new Date(iso + "T00:00:00").toLocaleDateString([], { month: "short", day: "numeric" });
  }
  function goalValue(goal) {
    const week = D().currentWeekRange();
    const weekSummary = D().summarize(week.start, week.end);
    const latestBody = D().latestBody(D().firstDate, D().lastDate);
    if (goal.metric === "weekly_strength_sessions") return weekSummary.liftSessions;
    if (goal.metric === "weekly_active_days") return weekSummary.activeDays;
    if (goal.metric === "weekly_cardio_distance") return weekSummary.km;
    if (goal.metric === "weekly_strength_volume") return weekSummary.tonnage;
    if (goal.metric === "body_weight") return latestBody ? latestBody.weight_kg : null;
    if (goal.metric === "body_fat") return latestBody ? latestBody.fat_ratio_pct : null;
    return null;
  }
  // Earliest recorded reading for a body metric — the starting point a
  // "toward" goal measures progress from (so gaining and losing both work).
  function goalBaseline(goal) {
    const field = goal.metric === "body_weight" ? "weight_kg"
      : goal.metric === "body_fat" ? "fat_ratio_pct" : null;
    if (!field) return null;
    const rows = D().bodySlice(D().firstDate, D().lastDate);
    for (const r of rows) if (r[field] != null) return r[field];
    return null;
  }
  function goalTarget(key) {
    const goal = D().goals().find((g) => g.key === key && g.enabled && g.target_value != null);
    return goal ? Number(goal.target_value) : null;
  }
  function fmtGoalValue(value, unit) {
    if (value == null || isNaN(value)) return "--";
    // Volume targets are large (tens of thousands of kg) — render them compactly
    // (20k) the way the metric cards do, while body weight stays e.g. 85.0.
    const str = unit === "kg" && Math.abs(value) >= 1000
      ? kFmt(value)
      : nf(value, unit === "kg" || unit === "%" ? 1 : 0);
    return `${str}${unit ? `<span class="unit">${unit}</span>` : ""}`;
  }
  function goalStatus(goal, current, baseline) {
    const target = goal.target_value;
    if (target == null || current == null) return { pct: 0, label: "Set target", state: "unset" };
    if (goal.direction === "at_most") {
      const diff = current - target;
      return {
        pct: Math.max(0, Math.min(1, target / Math.max(current, target))),
        label: diff <= 0 ? "On target" : `${nf(diff, 1)}${goal.unit} over`,
        state: diff <= 0 ? "good" : "warn",
      };
    }
    if (goal.direction === "toward") {
      // Bidirectional target: the bar is full ONLY when current === target.
      // Being either under or over the target shortens it, scaled by how far
      // the starting baseline sat from the target (a fixed window if unknown).
      const diff = current - target;
      const floor = goal.unit === "%" ? 2 : 4;
      const span = Math.max(baseline != null ? Math.abs(baseline - target) : floor, floor);
      const pct = Math.max(0, Math.min(1, 1 - Math.abs(diff) / span));
      const tol = goal.unit === "%" ? 0.2 : 0.3;
      const onTarget = Math.abs(diff) <= tol;
      return {
        pct,
        label: onTarget
          ? "On target"
          : `${nf(Math.abs(diff), 1)}${goal.unit} ${diff > 0 ? "above" : "below"} target`,
        state: onTarget ? "good" : "neutral",
      };
    }
    const pct = target ? current / target : 0;
    return {
      pct: Math.max(0, Math.min(1, pct)),
      label: current >= target ? "Done" : `${nf(Math.max(0, target - current), goal.unit === "kg" ? 1 : 0)}${goal.unit} left`,
      state: current >= target ? "good" : "neutral",
    };
  }

  function buildGoalsSection() {
    const goals = D().goals().filter((g) => g.enabled);
    const allGoals = D().goals();
    if (!allGoals.length) return { html: "", mount() {} };
    const cards = goals.map((goal) => {
      const current = goalValue(goal);
      const status = goalStatus(goal, current, goalBaseline(goal));
      const target = goal.target_value == null ? "Set target" : fmtGoalValue(goal.target_value, goal.unit);
      return `<div class="goal-card ${status.state}">
        <div class="goal-top"><span>${goal.label}</span><span>${goal.scope}</span></div>
        <div class="goal-main">${fmtGoalValue(current, goal.unit)}</div>
        <div class="goal-sub"><span>Target ${target}</span><span>${status.label}</span></div>
        <div class="goal-track"><i style="width:${Math.round(status.pct * 100)}%"></i></div>
      </div>`;
    }).join("");
    const rows = allGoals.map((goal) => `
      <label class="goal-edit-row">
        <input type="checkbox" data-goal-enabled="${goal.key}" ${goal.enabled ? "checked" : ""} />
        <span>${goal.label}</span>
        <input type="text" inputmode="decimal" data-goal-target="${goal.key}" value="${goal.target_value == null ? "" : goal.target_value}" placeholder="Target" />
        <em>${goal.unit}</em>
      </label>`).join("");
    return {
      html: `
        <div class="panel goals-panel" data-goals-panel>
          <div class="panel-head">
            <div><h3>Goals & targets</h3><div class="sub">Weekly training targets and body targets</div></div>
            <button class="secondary" type="button" data-goals-edit>Edit targets</button>
          </div>
          <div class="goal-grid">${cards || `<div class="empty-block">No active goals.</div>`}</div>
          <form class="goals-editor" data-goals-editor hidden>
            ${rows}
            <div class="goals-editor-actions">
              <button class="secondary" type="button" data-goals-cancel>Cancel</button>
              <button class="primary" type="submit">Save targets</button>
            </div>
          </form>
        </div>`,
      mount(root) {
        const panel = root.querySelector("[data-goals-panel]");
        if (!panel) return;
        const editor = panel.querySelector("[data-goals-editor]");
        const editButton = panel.querySelector("[data-goals-edit]");
        function syncEditor() {
          for (const goal of D().goals()) {
            const input = editor.querySelector(`[data-goal-target="${goal.key}"]`);
            if (input) input.value = goal.target_value == null ? "" : goal.target_value;
            const enabled = editor.querySelector(`[data-goal-enabled="${goal.key}"]`);
            if (enabled) enabled.checked = !!goal.enabled;
          }
        }
        function closeEditor() {
          editor.hidden = true;
          editButton.hidden = false;
        }
        editButton.addEventListener("click", () => {
          syncEditor();
          editor.hidden = false;
          editButton.hidden = true;
        });
        panel.querySelector("[data-goals-cancel]").addEventListener("click", () => {
          closeEditor();
        });
        editor.addEventListener("submit", async (e) => {
          e.preventDefault();
          const payload = D().goals().map((goal) => {
            const input = editor.querySelector(`[data-goal-target="${goal.key}"]`);
            const enabled = editor.querySelector(`[data-goal-enabled="${goal.key}"]`);
            const raw = input.value.trim();
            const target = raw === "" ? null : Number(raw.replace(",", "."));
            return { key: goal.key, enabled: !!enabled.checked, target_value: Number.isFinite(target) ? target : null };
          });
          const save = editor.querySelector("button[type='submit']");
          const label = save.textContent;
          save.disabled = true;
          save.textContent = "Saving…";
          try {
            const resp = await fetch("/api/goals", {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ goals: payload }),
            });
            if (resp.status === 401) { location.href = "/login"; return; }
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            D().setGoals(data.goals);
            render();
          } catch (err) {
            const meta = document.getElementById("stats-meta");
            if (meta) meta.textContent = `Goal save failed: ${err.message}`;
          } finally {
            save.disabled = false;
            save.textContent = label;
          }
        });
      },
    };
  }

  function buildProgressionSection(range) {
    const prev = prevRange(range);
    const prs = D().personalRecords(range.start, range.end).slice(0, 6);
    const curMuscles = D().muscleVolume(range.start, range.end);
    const prevMuscles = new Map(D().muscleVolume(prev.start, prev.end).map((m) => [m.group, m]));
    const shownMuscles = curMuscles.filter((m) => m.group !== "Other" || m.sets > 0);
    const maxSets = Math.max(1, ...shownMuscles.map((m) => m.sets));
    const prRows = prs.length ? prs.map((pr) => {
      const set = pr.bestSet ? `${nf(pr.bestSet.weight, 1)}kg × ${pr.bestSet.reps}` : "Best set";
      return `<div class="pr-row">
        <div><strong>${pr.exercise}</strong><span>${fmtShortDate(pr.date)} · ${set}</span></div>
        <div class="pr-value">${nf(pr.e1rm)}<span>kg</span><em>+${nf(pr.delta)}</em></div>
      </div>`;
    }).join("") : `<div class="empty-block compact">No new PRs in this range.</div>`;
    const muscleRows = shownMuscles.map((m) => {
      const prior = prevMuscles.get(m.group)?.sets || 0;
      const delta = m.sets - prior;
      const width = Math.round((m.sets / maxSets) * 100);
      return `<div class="muscle-row">
        <div class="muscle-line"><strong>${m.group}</strong><span>${nf(m.sets)} sets ${delta === 0 ? "±0" : delta > 0 ? `+${delta}` : delta}</span></div>
        <div class="muscle-track"><i style="width:${width}%"></i></div>
      </div>`;
    }).join("");
    return `
      <div class="section-title"><h3>Progression</h3><div class="rule"></div></div>
      <div class="progress-grid">
        <div class="panel">
          <div class="panel-head">
            <div><h3>PRs & highlights</h3><div class="sub">Estimated 1RM records in this range</div></div>
          </div>
          <div class="pr-list">${prRows}</div>
        </div>
        <div class="panel">
          <div class="panel-head">
            <div><h3>Muscle volume</h3><div class="sub">Working sets by primary muscle group</div></div>
            <span class="unit">sets</span>
          </div>
          <div class="muscle-list">${muscleRows}</div>
        </div>
      </div>`;
  }

  // ---------- shared chart builders ----------
  function targetDataset(label, value, count, color, yAxisID = "y") {
    return {
      label,
      data: Array.from({ length: count }, () => value),
      type: "line",
      yAxisID,
      borderColor: color,
      borderWidth: 1.8,
      borderDash: [6, 5],
      stack: "target",
      spanGaps: true,
      clip: false,
      pointRadius: 0,
      pointHoverRadius: 0,
      tension: 0,
      fill: false,
      backgroundColor: "transparent",
    };
  }
  function trainingTimeChart(canvas, ser) {
    const C = CC().THEME;
    const labels = ser.points.map((p) => CC().fmtLabel(p.key, ser.daily));
    const datasets = [
      CC().barDataset("Cardio", ser.points.map((p) => +(p.cardioMin / 60).toFixed(1)), C.cardio, { stack: "t", radius: 3 }),
      CC().barDataset("Strength", ser.points.map((p) => +(p.strengthMin / 60).toFixed(1)), C.strength, { stack: "t", radius: 5 }),
    ];
    CC().mount(canvas, {
      type: "bar",
      data: { labels, datasets },
      options: CC().options({ y: { stacked: true, ticks: { callback: (v) => v + "h" } }, x: { stacked: true } }),
    });
  }
  function volumeChart(canvas, ser) {
    const C = CC().THEME;
    const labels = ser.points.map((p) => CC().fmtLabel(p.key, ser.daily));
    const datasets = [CC().barDataset("Volume", ser.points.map((p) => p.tonnage), C.strength, { radius: 5 })];
    const volTarget = goalTarget("weekly_strength_volume");
    if (volTarget != null) {
      // Weekly target → per-bucket pace when the series is bucketed by day.
      const perBucket = ser.daily ? volTarget / 7 : volTarget;
      datasets.push(targetDataset(ser.daily ? "Volume target pace" : "Volume target", Math.round(perBucket), ser.points.length, "#e0a23b"));
    }
    CC().mount(canvas, {
      type: "bar",
      data: { labels, datasets },
      options: CC().options({ y: { ticks: { callback: kFmt } } }),
    });
  }
  function distanceChart(canvas, ser) {
    const C = CC().THEME;
    const labels = ser.points.map((p) => CC().fmtLabel(p.key, ser.daily));
    const datasets = [CC().barDataset("Distance", ser.points.map((p) => +p.km.toFixed(1)), C.cardio, { radius: 5 })];
    const distTarget = goalTarget("weekly_cardio_distance");
    if (distTarget != null) {
      const perBucket = ser.daily ? distTarget / 7 : distTarget;
      datasets.push(targetDataset(ser.daily ? "Distance target pace" : "Distance target", +perBucket.toFixed(1), ser.points.length, "#e0a23b"));
    }
    CC().mount(canvas, {
      type: "bar",
      data: { labels, datasets },
      options: CC().options({ y: { ticks: { callback: (v) => v + " km" } } }),
    });
  }
  function signed(v, unit, dp = 1) {
    if (v == null || isNaN(v)) return "--";
    const n = Number(v);
    const sign = n > 0 ? "+" : "";
    return `${sign}${nf(n, dp)}${unit ? `<span class="unit">${unit}</span>` : ""}`;
  }
  function bodyDate(iso) {
    if (!iso) return "";
    return new Date(iso + "T00:00:00").toLocaleDateString([], { month: "short", day: "numeric" });
  }
  function bodyDelta(rows, key) {
    const pts = rows.filter((r) => r[key] != null);
    if (pts.length < 2) return null;
    return pts[pts.length - 1][key] - pts[0][key];
  }
  function bodyMin(rows, key) {
    const values = rows.map((r) => r[key]).filter((v) => v != null);
    return values.length ? Math.min(...values) : null;
  }
  function bodyWeightChart(canvas, ser) {
    const C = CC().THEME;
    const pts = ser.points;
    const datasets = [CC().lineDataset("Weight", pts.map((p) => p.weight_kg), C.strength, true)];
    const weightTarget = goalTarget("body_weight");
    if (weightTarget != null) {
      datasets.push(targetDataset("Target", weightTarget, pts.length, "#e0a23b"));
    }
    const weightValues = pts.map((p) => p.weight_kg).filter((v) => v != null);
    if (weightTarget != null) weightValues.push(weightTarget);
    const weightPad = weightValues.length ? Math.max(0.4, (Math.max(...weightValues) - Math.min(...weightValues)) * 0.2) : 1;
    CC().mount(canvas, {
      type: "line",
      data: {
        labels: pts.map((p) => CC().fmtLabel(p.key, ser.daily)),
        datasets,
      },
      options: CC().options({
        beginAtZero: false,
        xTicks: 7,
        y: {
          suggestedMin: weightValues.length ? Math.min(...weightValues) - weightPad : undefined,
          suggestedMax: weightValues.length ? Math.max(...weightValues) + weightPad : undefined,
          ticks: { callback: (v) => v + " kg" },
        },
      }),
    });
  }
  function bodyCompositionItems(mode) {
    const C = CC().THEME;
    const items = mode === "percent"
      ? [{ c: C.cardio, l: "Body fat %" }]
      : [{ c: C.good, l: "Muscle" }, { c: "#e0a23b", l: "Fat mass" }];
    if (mode === "percent" && goalTarget("body_fat") != null) items.push({ c: "#f2c46d", l: "Target" });
    return items;
  }
  function bodyCompositionSubtitle(mode) {
    return mode === "percent" ? "Body fat percentage trend" : "Muscle and fat mass trend";
  }
  function bodyCompositionChart(canvas, ser, mode = state.bodyCompositionMode) {
    const C = CC().THEME;
    const pts = ser.points;
    const labels = pts.map((p) => CC().fmtLabel(p.key, ser.daily));
    const datasets = [];
    let values = [];
    let tickUnit = "kg";

    if (mode === "percent") {
      const fatTarget = goalTarget("body_fat");
      datasets.push(CC().lineDataset("Body fat %", pts.map((p) => p.fat_ratio_pct), C.cardio, false));
      if (fatTarget != null) datasets.push(targetDataset("Target", fatTarget, pts.length, "#f2c46d"));
      values = pts.map((p) => p.fat_ratio_pct).filter((v) => v != null);
      if (fatTarget != null) values.push(fatTarget);
      tickUnit = "%";
    } else {
      datasets.push(
        CC().lineDataset("Muscle", pts.map((p) => p.muscle_mass_kg), C.good, false),
        CC().lineDataset("Fat mass", pts.map((p) => p.fat_mass_kg), "#e0a23b", false),
      );
      values = pts.flatMap((p) => [p.muscle_mass_kg, p.fat_mass_kg]).filter((v) => v != null);
    }

    const pad = values.length ? Math.max(tickUnit === "%" ? 0.5 : 0.8, (Math.max(...values) - Math.min(...values)) * 0.22) : 1;
    CC().mount(canvas, {
      type: "line",
      data: {
        labels,
        datasets,
      },
      options: CC().options({
        beginAtZero: false,
        xTicks: 7,
        y: {
          suggestedMin: values.length ? Math.min(...values) - pad : undefined,
          suggestedMax: values.length ? Math.max(...values) + pad : undefined,
          ticks: { callback: (v) => tickUnit === "%" ? v + "%" : v + " kg" },
        },
      }),
    });
  }

  function buildBodySection(range) {
    const C = CC().THEME;
    const rows = D().bodySlice(range.start, range.end);
    const ser = D().bodySeries(range.start, range.end);
    const latest = rows.length ? rows[rows.length - 1] : null;
    const weightId = nid("body-weight");
    const compId = nid("body-comp");
    if (!latest) {
      return {
        html: `
          <div class="section-title"><h3>Body</h3><div class="rule"></div></div>
          <div class="panel"><div class="empty-block">No body measurements in this range.</div></div>`,
        mount() {},
      };
    }

    const weightChange = bodyDelta(rows, "weight_kg");
    const fatChange = bodyDelta(rows, "fat_ratio_pct");
    const weightTarget = goalTarget("body_weight");
    const weightLegend = weightTarget != null
      ? legendHtml([{ c: C.strength, l: "Weight" }, { c: "#e0a23b", l: "Target" }])
      : `<span class="unit">kg</span>`;
    const mode = state.bodyCompositionMode;
    const compositionLegend = legendHtml(bodyCompositionItems(mode));
    const compLegendId = nid("body-comp-legend");
    const compSubId = nid("body-comp-sub");
    return {
      html: `
        <div class="section-title"><h3>Body</h3><div class="rule"></div></div>
        <div class="body-grid">
          <div class="panel body-panel">
            <div class="panel-head">
              <div><h3>Body weight</h3><div class="sub">Latest ${bodyDate(latest.date)} · ${rows.length} measurements</div></div>
              ${weightLegend}
            </div>
            <div class="body-metrics">
              <div class="body-stat"><div class="v">${nf(latest.weight_kg, 1)}<span class="unit">kg</span></div><div class="l">Latest</div></div>
              <div class="body-stat"><div class="v">${signed(weightChange, "kg", 1)}</div><div class="l">Range change</div></div>
              <div class="body-stat"><div class="v">${nf(bodyMin(rows, "weight_kg"), 1)}<span class="unit">kg</span></div><div class="l">Range low</div></div>
            </div>
            <div class="chart-frame body-chart"><canvas id="${weightId}"></canvas></div>
          </div>
          <div class="panel body-panel">
            <div class="panel-head">
              <div><h3>Body composition</h3><div class="sub" id="${compSubId}">${bodyCompositionSubtitle(mode)}</div></div>
              <div class="body-chart-tools">
                <div class="chart-tabs" role="group" aria-label="Body composition chart mode">
                  <button type="button" class="${mode === "mass" ? "active" : ""}" data-body-comp-mode="mass">kg</button>
                  <button type="button" class="${mode === "percent" ? "active" : ""}" data-body-comp-mode="percent">%</button>
                </div>
                <div id="${compLegendId}">${compositionLegend}</div>
              </div>
            </div>
            <div class="body-metrics">
              <div class="body-stat"><div class="v">${nf(latest.fat_ratio_pct, 1)}<span class="unit">%</span></div><div class="l">Body fat</div></div>
              <div class="body-stat"><div class="v">${nf(latest.muscle_mass_kg, 1)}<span class="unit">kg</span></div><div class="l">Muscle mass</div></div>
              <div class="body-stat"><div class="v">${signed(fatChange, "%", 1)}</div><div class="l">Fat % change</div></div>
            </div>
            <div class="chart-frame body-chart"><canvas id="${compId}"></canvas></div>
          </div>
        </div>`,
      mount(root) {
        bodyWeightChart(root.querySelector("#" + weightId), ser);
        const compCanvas = root.querySelector("#" + compId);
        const compLegend = root.querySelector("#" + compLegendId);
        const compSub = root.querySelector("#" + compSubId);
        const buttons = root.querySelectorAll("[data-body-comp-mode]");
        function renderComposition(mode) {
          state.bodyCompositionMode = mode;
          buttons.forEach((button) => button.classList.toggle("active", button.dataset.bodyCompMode === mode));
          if (compLegend) compLegend.innerHTML = legendHtml(bodyCompositionItems(mode));
          if (compSub) compSub.textContent = bodyCompositionSubtitle(mode);
          bodyCompositionChart(compCanvas, ser, mode);
        }
        buttons.forEach((button) => {
          button.addEventListener("click", () => renderComposition(button.dataset.bodyCompMode));
        });
        renderComposition(state.bodyCompositionMode);
      },
    };
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
          <div class="sub">Reps & volume over time</div>
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
      const trend = D().exerciseTrend(name, range.start, range.end);
      const trendLabels = trend.points.map((p) => CC().fmtLabel(p.key, trend.daily));
      const statEl = mountEl.querySelector("#" + statId);
      if (!pts.length) {
        statEl.innerHTML = `<div class="ex-stat"><div class="l">No ${name} sessions in this range</div></div>`;
        CC().mount(mountEl.querySelector("#" + volId), {
          type: "bar",
          data: { labels: trendLabels, datasets: [CC().barDataset("Volume", trend.points.map((p) => p.volume), C.strength, { radius: 4 })] },
          options: CC().options({ y: { ticks: { callback: kFmt } }, xTicks: 8 }),
        });
        CC().mount(mountEl.querySelector("#" + repsId), {
          type: "line",
          data: { labels: trendLabels, datasets: [CC().lineDataset("Reps", trend.points.map((p) => p.reps), C.good, true)] },
          options: CC().options({ xTicks: 8 }),
        });
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
      CC().mount(mountEl.querySelector("#" + volId), {
        type: "bar",
        data: { labels: trendLabels, datasets: [CC().barDataset("Volume", trend.points.map((p) => p.volume), C.strength, { radius: 4 })] },
        options: CC().options({ y: { ticks: { callback: kFmt } }, xTicks: 8 }),
      });
      CC().mount(mountEl.querySelector("#" + repsId), {
        type: "line",
        data: { labels: trendLabels, datasets: [CC().lineDataset("Reps", trend.points.map((p) => p.reps), C.good, true)] },
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
    const goalsSection = buildGoalsSection();
    const bodySection = buildBodySection(range);
    const timeLegend = [{ c: C.cardio, l: "Cardio" }, { c: C.strength, l: "Strength" }];
    const volLegend = goalTarget("weekly_strength_volume") != null
      ? legendHtml([{ c: C.strength, l: "Volume" }, { c: "#e0a23b", l: "Target" }])
      : `<span class="unit">kg</span>`;
    const distLegend = goalTarget("weekly_cardio_distance") != null
      ? legendHtml([{ c: C.cardio, l: "Distance" }, { c: "#e0a23b", l: "Target" }])
      : `<span class="unit">km</span>`;
    root.innerHTML = `
      <div class="metric-grid">${metricsFor(s, ctx.prev, ["active", "streak", "sets", "sessions", "shours", "chours", "tonnage", "km"])}</div>

      ${goalsSection.html}

      <div class="section-title"><h3>Trends</h3><div class="rule"></div></div>
      <div class="panel">
        <div class="panel-head">
          <div><h3>Training time</h3><div class="sub">Hours per ${ser.daily ? "day" : "week"}, strength + cardio</div></div>
          ${legendHtml(timeLegend)}
        </div>
        <div class="chart-frame tall"><canvas id="${ttId}"></canvas></div>
      </div>
      <div class="charts-2">
        <div class="panel">
          <div class="panel-head"><div><h3>Strength volume</h3><div class="sub">Total kg lifted per ${ser.daily ? "day" : "week"}</div></div>${volLegend}</div>
          <div class="chart-frame"><canvas id="${volId}"></canvas></div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><h3>Cardio distance</h3><div class="sub">Distance per ${ser.daily ? "day" : "week"}</div></div>${distLegend}</div>
          <div class="chart-frame"><canvas id="${distId}"></canvas></div>
        </div>
      </div>

      ${buildProgressionSection(range)}

      <div class="section-title"><h3>Exercises</h3><div class="rule"></div></div>
      <div class="panel" id="ex-panel-a"></div>

      <div class="section-title"><h3>Activity</h3><div class="rule"></div></div>
      <div class="panel"><div id="cal-a"></div></div>

      ${bodySection.html}`;

    trainingTimeChart(root.querySelector("#" + ttId), ser);
    volumeChart(root.querySelector("#" + volId), ser);
    distanceChart(root.querySelector("#" + distId), ser);
    goalsSection.mount(root);
    buildExercisePanel(root.querySelector("#ex-panel-a"), range, { default: "Bench Press" });
    window.CoachCalendar.create(root.querySelector("#cal-a"), { defaultMode: "month", range }).render();
    bodySection.mount(root);
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
