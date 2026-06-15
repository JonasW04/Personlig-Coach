/* ============================================================
   calendar.js — activity calendar (month grid + heatmap)
   Exposes window.CoachCalendar.create(container, opts)
   ============================================================ */
(function () {
  "use strict";
  const D = () => window.CoachData;
  const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  const MONTH_SHORT = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const DOW = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

  function fmtFull(iso) {
    return new Date(iso + "T00:00:00").toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  }
  function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }

  function create(container, opts = {}) {
    const data = D();
    const last = data.parse(data.lastDate);
    const state = {
      mode: opts.defaultMode || "month",
      year: last.getFullYear(),
      month: last.getMonth(),
      range: opts.range || null, // for heatmap {start,end}
      hero: !!opts.hero,
    };

    function render() {
      container.innerHTML = "";
      const head = el(`
        <div class="cal-head">
          <div class="cal-nav"></div>
          <div class="cal-toggle">
            <button data-m="month">Month</button>
            <button data-m="heatmap">Heatmap</button>
          </div>
        </div>`);
      const nav = head.querySelector(".cal-nav");
      head.querySelectorAll(".cal-toggle button").forEach((b) => {
        b.classList.toggle("active", b.dataset.m === state.mode);
        b.addEventListener("click", () => { state.mode = b.dataset.m; render(); });
      });

      if (state.mode === "month") {
        nav.appendChild(el(`<button data-nav="-1" aria-label="Previous month">‹</button>`));
        nav.appendChild(el(`<span class="label">${MONTHS[state.month]} ${state.year}</span>`));
        nav.appendChild(el(`<button data-nav="1" aria-label="Next month">›</button>`));
        nav.querySelectorAll("[data-nav]").forEach((b) =>
          b.addEventListener("click", () => step(Number(b.dataset.nav))));
      } else {
        nav.appendChild(el(`<span class="label" style="min-width:auto;text-align:left">Activity over time</span>`));
      }
      container.appendChild(head);

      if (state.mode === "month") renderMonth();
      else renderHeatmap();

      container.appendChild(legend());
      const detail = el(`<div class="day-detail" id="${detailId}"></div>`);
      container.appendChild(detail);
    }

    const detailId = "dd-" + Math.random().toString(36).slice(2, 7);

    function step(dir) {
      let m = state.month + dir, y = state.year;
      if (m < 0) { m = 11; y--; } else if (m > 11) { m = 0; y++; }
      const first = data.parse(data.firstDate), lastD = data.parse(data.lastDate);
      const candidate = new Date(y, m, 1);
      if (candidate < new Date(first.getFullYear(), first.getMonth(), 1)) return;
      if (candidate > new Date(lastD.getFullYear(), lastD.getMonth(), 1)) return;
      state.month = m; state.year = y; render();
    }

    function renderMonth() {
      const weeks = data.calendarMonth(state.year, state.month);
      const grid = el(`<div class="cal-grid"></div>`);
      DOW.forEach((d) => grid.appendChild(el(`<div class="cal-dow">${d}</div>`)));
      const todayIso = data.iso(data.TODAY);
      weeks.forEach((row) => row.forEach((c) => {
        const cls = ["cal-cell"];
        if (!c.inMonth) cls.push("out");
        if (c.isFuture) cls.push("future");
        if (c.date === todayIso) cls.push("today");
        if (c.type !== "none") cls.push("t-" + c.type);
        const active = c.type !== "none" && c.inMonth;
        const marks = c.type === "both"
          ? `<div class="marks"><i class="s"></i><i class="c"></i></div>`
          : c.type === "strength" ? `<div class="marks"><i class="s"></i></div>`
          : c.type === "cardio" ? `<div class="marks"><i class="c"></i></div>` : "";
        const cell = el(`<div class="${cls.join(" ")}" data-active="${active ? 1 : 0}" data-date="${c.date}">${c.inMonth ? c.day : ""}${marks}</div>`);
        if (active) cell.addEventListener("click", () => showDetail(c.date, c.entry));
        grid.appendChild(cell);
      }));
      container.appendChild(grid);
    }

    function renderHeatmap() {
      const range = state.range || data.rangeBounds("6m");
      const cols = data.heatmap(range.start, range.end);
      const wrap = el(`<div class="heatmap-wrap"></div>`);
      // month labels
      const monthRow = el(`<div class="hm-months"></div>`);
      let lastMonth = -1;
      cols.forEach((col) => {
        const m = new Date(col.weekStart + "T00:00:00").getMonth();
        const label = m !== lastMonth ? MONTH_SHORT[m] : "";
        lastMonth = m;
        monthRow.appendChild(el(`<div class="hm-m" style="width:15px">${label}</div>`));
      });
      const hm = el(`<div class="heatmap"></div>`);
      const todayIso = data.iso(data.TODAY);
      cols.forEach((col) => {
        const c = el(`<div class="hm-col"></div>`);
        col.days.forEach((d) => {
          const cls = ["hm-cell"];
          if (d.muted) cls.push("muted");
          else if (d.future) cls.push("future");
          else if (d.type !== "none") cls.push("t-" + d.type);
          const cell = el(`<div class="${cls.join(" ")}" data-date="${d.date}" title="${fmtFull(d.date)}"></div>`);
          if (d.type !== "none" && !d.muted && !d.future) {
            cell.style.cursor = "pointer";
            const entry = data.DB.find((x) => x.date === d.date);
            cell.addEventListener("click", () => showDetail(d.date, entry));
          }
          c.appendChild(cell);
        });
        hm.appendChild(c);
      });
      wrap.appendChild(monthRow);
      wrap.appendChild(hm);
      container.appendChild(wrap);
    }

    function legend() {
      return el(`
        <div class="cal-legend">
          <div class="cl"><span class="sw s"></span> Strength</div>
          <div class="cl"><span class="sw c"></span> Cardio</div>
          <div class="cl"><span class="sw b"></span> Both</div>
        </div>`);
    }

    function showDetail(date, entry) {
      const dd = container.querySelector("#" + detailId);
      if (!dd) return;
      let rows = "";
      if (entry && entry.strength) {
        const s = entry.strength;
        const exNames = s.exercises.map((e) => e.name).join(", ");
        rows += `<div class="dd-row s"><span class="pill">Strength</span><span class="txt">${s.sets} sets · ${Math.round(s.tonnage).toLocaleString()} kg · ${s.minutes} min</span></div>
          <div class="dd-row" style="margin-top:6px"><span class="txt" style="font-size:12px;color:var(--faint)">${exNames}</span></div>`;
      }
      if (entry && entry.cardio) {
        const c = entry.cardio;
        rows += `<div class="dd-row c"><span class="pill">Cardio</span><span class="txt">${c.type} · ${c.km} km · ${c.minutes} min</span></div>`;
      }
      if (!rows) rows = `<div class="dd-empty">Rest day — no activity logged.</div>`;
      dd.innerHTML = `
        <div class="dd-head">
          <span class="dd-date">${fmtFull(date)}</span>
          <button class="dd-close" aria-label="Close">✕</button>
        </div>${rows}`;
      dd.classList.add("show");
      dd.querySelector(".dd-close").addEventListener("click", () => dd.classList.remove("show"));
    }

    return { render, state };
  }

  window.CoachCalendar = { create };
})();
