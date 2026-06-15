/* ============================================================
   charts.js — Chart.js config + theme + builders
   Exposes window.CoachCharts
   ============================================================ */
(function () {
  "use strict";

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const THEME = {
    strength: "#4f8cff",
    cardio: "#ff6b4a",
    good: "#46c98b",
    grid: "#222834",
    gridSoft: "rgba(255,255,255,0.05)",
    muted: "#9aa3b4",
    faint: "#646d7e",
    surface: "#14181f",
    text: "#eef1f6",
  };
  function refreshTheme() {
    THEME.strength = css("--strength") || THEME.strength;
    THEME.cardio = css("--cardio") || THEME.cardio;
    THEME.good = css("--good") || THEME.good;
    THEME.grid = css("--line") || THEME.grid;
    THEME.muted = css("--muted") || THEME.muted;
    THEME.surface = css("--surface") || THEME.surface;
    THEME.text = css("--text") || THEME.text;
  }

  function base() {
    refreshTheme();
    Chart.defaults.color = THEME.muted;
    Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.borderColor = THEME.grid;
  }

  function alpha(hex, a) {
    const h = hex.replace("#", "");
    const n = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
    const r = parseInt(n.slice(0, 2), 16), g = parseInt(n.slice(2, 4), 16), b = parseInt(n.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  function fmtLabel(key, daily) {
    const d = new Date(key + "T00:00:00");
    if (daily) return d.toLocaleDateString([], { month: "short", day: "numeric" });
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function gradient(ctx, area, color, a1, a2) {
    if (!area) return alpha(color, a1);
    const g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, alpha(color, a1));
    g.addColorStop(1, alpha(color, a2));
    return g;
  }

  const tooltip = () => ({
    backgroundColor: "#11151c",
    borderColor: THEME.grid,
    borderWidth: 1,
    titleColor: THEME.text,
    bodyColor: THEME.text,
    padding: 10,
    cornerRadius: 8,
    displayColors: true,
    boxPadding: 4,
    usePointStyle: true,
  });

  function scales(opts = {}) {
    return {
      x: {
        grid: { display: false },
        border: { color: THEME.grid },
        ticks: { color: THEME.faint, maxRotation: 0, autoSkip: true, maxTicksLimit: opts.xTicks || 7, padding: 6 },
        ...(opts.x || {}),
      },
      y: {
        grid: { color: THEME.gridSoft, drawTicks: false },
        border: { display: false },
        ticks: { color: THEME.faint, padding: 8, maxTicksLimit: 6 },
        beginAtZero: opts.beginAtZero !== false,
        ...(opts.y || {}),
      },
    };
  }

  function options(opts = {}) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 450, easing: "easeOutCubic" },
      interaction: { mode: "index", intersect: false },
      layout: { padding: { top: 6, right: 4, left: 0, bottom: 0 } },
      plugins: {
        legend: { display: false },
        tooltip: { ...tooltip(), ...(opts.tooltip || {}) },
      },
      scales: scales(opts),
    };
  }

  // registry to manage/destroy charts
  const registry = new Map();
  function mount(canvas, config) {
    if (!canvas) return null;
    const id = canvas.id || canvas.dataset.cid;
    if (id && registry.has(id)) { registry.get(id).destroy(); registry.delete(id); }
    const chart = new Chart(canvas, config);
    if (id) registry.set(id, chart);
    return chart;
  }
  function destroyAll() {
    for (const c of registry.values()) c.destroy();
    registry.clear();
  }

  // ---- builders ----
  function lineDataset(label, data, color, fill) {
    return {
      label, data, borderColor: color, borderWidth: 2.2,
      tension: 0.34, spanGaps: true, pointRadius: 0, pointHoverRadius: 5,
      pointHoverBackgroundColor: color, pointHoverBorderColor: "#fff", pointHoverBorderWidth: 1.5,
      fill: fill ? { target: "origin" } : false,
      backgroundColor: fill
        ? (c) => gradient(c.chart.ctx, c.chart.chartArea, color, 0.26, 0.01)
        : "transparent",
    };
  }
  function barDataset(label, data, color, opts = {}) {
    return {
      label, data, backgroundColor: opts.bg || alpha(color, 0.85),
      hoverBackgroundColor: color, borderRadius: opts.radius == null ? 6 : opts.radius,
      borderSkipped: false, barPercentage: opts.bp || 0.72, categoryPercentage: opts.cp || 0.78,
      stack: opts.stack,
    };
  }

  window.CoachCharts = {
    THEME, base, refreshTheme, alpha, fmtLabel, gradient,
    options, scales, tooltip, mount, destroyAll, lineDataset, barDataset,
  };
})();
