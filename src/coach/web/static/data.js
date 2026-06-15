/* ============================================================
   data.js — live training data + derivations
   Fetches per-day activity from /api/stats and exposes window.CoachData.
   The derivation shapes mirror the design prototype so stats.js / calendar.js
   stay unchanged; only the data source is real.
   ============================================================ */
(function () {
  "use strict";

  // ---- date helpers ----
  const DAY = 86400000;
  function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
  const TODAY = startOfDay(new Date());
  function iso(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function parse(s) { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); }
  function addDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function daysBetween(a, b) { return Math.round((parse(b) - parse(a)) / DAY); }

  // ---- live state, populated by load() ----
  let DB = [];
  let BODY = [];
  let firstDate = iso(TODAY);
  let lastDate = iso(TODAY);

  // Enrich a raw API day with the aggregates the UI derivations expect.
  function enrich(day) {
    const entry = { date: day.date, dow: parse(day.date).getDay(), strength: null, cardio: null };
    if (day.strength) {
      const exercises = day.strength.exercises || [];
      let sets = 0, tonnage = 0;
      for (const ex of exercises) {
        for (const st of ex.sets) {
          sets += 1;
          tonnage += (st.reps || 0) * (st.weight || 0);
        }
      }
      entry.strength = {
        exercises,
        minutes: day.strength.minutes || 0,
        sets,
        tonnage: Math.round(tonnage),
      };
    }
    if (day.cardio) {
      entry.cardio = { type: day.cardio.type, minutes: day.cardio.minutes || 0, km: day.cardio.km || 0 };
    }
    return entry;
  }

  async function load() {
    const resp = await fetch("/api/stats");
    if (resp.status === 401) { location.href = "/login"; return; }
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const json = await resp.json();
    DB = (json.days || []).map(enrich).sort((a, b) => (a.date < b.date ? -1 : 1));
    BODY = (json.body || []).sort((a, b) => (a.date < b.date ? -1 : 1));
    firstDate = [DB[0]?.date, BODY[0]?.date].filter(Boolean).sort()[0] || iso(TODAY);
    lastDate = iso(TODAY);
    api.DB = DB;
    api.BODY = BODY;
    api.firstDate = firstDate;
    api.lastDate = lastDate;
  }

  // ---- derivations ----
  function inRange(d, start, end) { return d >= start && d <= end; }

  function rangeBounds(key) {
    const end = iso(TODAY);
    let start;
    switch (key) {
      case "7d":  start = iso(addDays(TODAY, -6)); break;
      case "4w":  start = iso(addDays(TODAY, -27)); break;
      case "3m":  start = iso(addDays(TODAY, -90)); break;
      case "6m":  start = iso(addDays(TODAY, -181)); break;
      case "ytd": start = iso(new Date(TODAY.getFullYear(), 0, 1)); break;
      case "all": start = firstDate; break;
      default:    start = iso(addDays(TODAY, -90));
    }
    return { start, end };
  }

  function slice(start, end) { return DB.filter((d) => inRange(d.date, start, end)); }
  function bodySlice(start, end) { return BODY.filter((d) => inRange(d.date, start, end)); }
  function latestBody(start, end) {
    const rows = bodySlice(start, end);
    return rows.length ? rows[rows.length - 1] : null;
  }

  function summarize(start, end) {
    const rows = slice(start, end);
    let sets = 0, strengthMin = 0, cardioMin = 0, tonnage = 0, km = 0;
    let strengthDays = 0, cardioDays = 0, bothDays = 0, activeDays = 0;
    let liftSessions = 0, cardioSessions = 0;
    for (const d of rows) {
      const hasS = !!d.strength, hasC = !!d.cardio;
      if (hasS) { sets += d.strength.sets; strengthMin += d.strength.minutes; tonnage += d.strength.tonnage; liftSessions++; }
      if (hasC) { cardioMin += d.cardio.minutes; km += d.cardio.km; cardioSessions++; }
      if (hasS && hasC) bothDays++;
      else if (hasS) strengthDays++;
      else if (hasC) cardioDays++;
      if (hasS || hasC) activeDays++;
    }
    return {
      sets, strengthHours: strengthMin / 60, cardioHours: cardioMin / 60,
      strengthMin, cardioMin, tonnage, km,
      strengthDays, cardioDays, bothDays, activeDays,
      liftSessions, cardioSessions,
      totalDays: daysBetween(start, end) + 1,
      streak: currentStreak(end),
    };
  }

  // consecutive active days counting back from `end` (inclusive)
  function currentStreak(end) {
    const map = new Map(DB.map((d) => [d.date, d]));
    let streak = 0;
    let cur = parse(end);
    for (;;) {
      const e = map.get(iso(cur));
      if (e && (e.strength || e.cardio)) { streak++; cur = addDays(cur, -1); }
      else break;
    }
    return streak;
  }

  // adaptive time series: daily if span <= 35 days, else weekly buckets
  function series(start, end) {
    const span = daysBetween(start, end) + 1;
    const daily = span <= 35;
    const rows = slice(start, end);
    const buckets = new Map();
    const order = [];
    function keyFor(dateStr) {
      if (daily) return dateStr;
      const d = parse(dateStr);
      const off = (d.getDay() + 6) % 7;
      return iso(addDays(d, -off));
    }
    for (const d of rows) {
      const k = keyFor(d.date);
      if (!buckets.has(k)) { buckets.set(k, { key: k, tonnage: 0, km: 0, strengthMin: 0, cardioMin: 0, sets: 0 }); order.push(k); }
      const b = buckets.get(k);
      if (d.strength) { b.tonnage += d.strength.tonnage; b.strengthMin += d.strength.minutes; b.sets += d.strength.sets; }
      if (d.cardio) { b.km += d.cardio.km; b.cardioMin += d.cardio.minutes; }
    }
    return { daily, points: order.map((k) => buckets.get(k)) };
  }

  // exercises seen in the data, most frequent first
  function exerciseList() {
    const counts = new Map();
    for (const d of DB) {
      if (!d.strength) continue;
      for (const ex of d.strength.exercises) counts.set(ex.name, (counts.get(ex.name) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map((e) => e[0]);
  }

  // per-session metrics for one exercise within range
  function exerciseSeries(name, start, end) {
    const rows = slice(start, end);
    const pts = [];
    for (const d of rows) {
      if (!d.strength) continue;
      const ex = d.strength.exercises.find((e) => e.name === name);
      if (!ex) continue;
      let volume = 0, reps = 0, top = 0, e1rm = 0;
      for (const s of ex.sets) {
        const w = s.weight || 0;
        volume += s.reps * w;
        reps += s.reps;
        if (w > top) top = w;
        const est = w * (1 + s.reps / 30);
        if (est > e1rm) e1rm = est;
      }
      pts.push({ date: d.date, volume: Math.round(volume), reps, topWeight: top, e1rm: Math.round(e1rm) });
    }
    return pts;
  }

  // day type for calendar: 'none' | 'strength' | 'cardio' | 'both'
  function dayType(entry) {
    if (!entry) return "none";
    const s = !!entry.strength, c = !!entry.cardio;
    if (s && c) return "both";
    if (s) return "strength";
    if (c) return "cardio";
    return "none";
  }

  function dayMap() { return new Map(DB.map((d) => [d.date, d])); }

  // month grid: array of weeks, each 7 cells {date, inMonth, type, entry}
  function calendarMonth(year, month) {
    const map = dayMap();
    const first = new Date(year, month, 1);
    const startOffset = (first.getDay() + 6) % 7; // Monday-first
    const gridStart = addDays(first, -startOffset);
    const weeks = [];
    let cur = new Date(gridStart);
    for (let w = 0; w < 6; w++) {
      const row = [];
      for (let i = 0; i < 7; i++) {
        const ds = iso(cur);
        const entry = map.get(ds);
        row.push({
          date: ds, day: cur.getDate(), inMonth: cur.getMonth() === month,
          isFuture: cur > TODAY, type: dayType(entry), entry,
        });
        cur = addDays(cur, 1);
      }
      weeks.push(row);
      if (cur.getMonth() !== month && w >= 4) break;
    }
    return weeks;
  }

  // heatmap: columns of weeks (Mon-top) spanning [start,end]
  function heatmap(start, end) {
    const map = dayMap();
    const s = parse(start);
    const startOffset = (s.getDay() + 6) % 7;
    const gridStart = addDays(s, -startOffset);
    const cols = [];
    let cur = new Date(gridStart);
    const last = parse(end);
    while (cur <= last) {
      const col = { weekStart: iso(cur), days: [] };
      for (let i = 0; i < 7; i++) {
        const ds = iso(cur);
        const entry = map.get(ds);
        const before = parse(ds) < parse(start);
        const future = cur > TODAY;
        col.days.push({
          date: ds, type: future || before ? "none" : dayType(entry),
          minutes: entry ? ((entry.strength ? entry.strength.minutes : 0) + (entry.cardio ? entry.cardio.minutes : 0)) : 0,
          muted: before, future,
        });
        cur = addDays(cur, 1);
      }
      cols.push(col);
    }
    return cols;
  }

  function monthsAvailable() {
    const fd = parse(firstDate);
    const out = [];
    let cur = new Date(fd.getFullYear(), fd.getMonth(), 1);
    while (cur <= TODAY) { out.push({ year: cur.getFullYear(), month: cur.getMonth() }); cur = new Date(cur.getFullYear(), cur.getMonth() + 1, 1); }
    return out;
  }

  const api = {
    DB, BODY, TODAY, iso, parse, addDays, daysBetween,
    rangeBounds, summarize, series, exerciseList, exerciseSeries,
    bodySlice, latestBody,
    calendarMonth, heatmap, dayType, monthsAvailable,
    firstDate, lastDate,
    load,
    reload: load,
  };
  api.ready = load();

  window.CoachData = api;
})();
