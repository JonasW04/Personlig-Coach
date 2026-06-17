// Spec state from the handoff's "State Management" section. Values copied
// verbatim from the prototype where the spec calls for it (esp. planVsActual._days).
// Screens render from this until the corresponding backend endpoints land.
window.STATE = {
  today: {
    dateLine: "WED · JUN 17 · 06:32",
    readiness: 72,
    verdict: "TRAIN",          // TRAIN (green) | EASY (amber) | REST (violet)
    planned: { type: "STRENGTH", name: "Pull · Hypertrophy", detail: "5 exercises · ~50 min · RPE 7–8", hevyStatus: "ready" },
    sleep: { value: "7h 18m", meta: "Score 81 · good" },
    hrv: { value: "58 ms", meta: "Balanced · 7-day" },
    bodyBattery: { value: "76", meta: "Charged" },
    restingHr: { value: "48 bpm", meta: "−2 vs base" },
    acwr: 1.08,
    acwrPct: 54,
    recent: [
      { day: "Mon", name: "Push · Strength", meta: "Hevy · 52 min", done: true, accent: "strength" },
      { day: "Tue", name: "Zone 2 · 8.2 km", meta: "Garmin · 44 min", done: true, accent: "cardio" },
      { day: "Wed", name: "Pull · Hyp", meta: "Today", today: true, accent: "strength" },
    ],
    warning: "Cardio + push back-to-back nudged load up. Keep this session under 55 min and stop pulls at RPE 8.",
  },

  weekPlan: {
    header: "WEEK 3 OF 6 · HYPERTROPHY BLOCK",
    range: "Jun 15 – Jun 21",
    summary: "4 active days · 3 strength · 15 km cardio · 2 rest",
    tiles: [
      { value: "4", label: "Active days" },
      { value: "85%", label: "Adherence" },
      { value: "15 km", label: "Cardio" },
    ],
    days: [
      { day: "Mon", name: "Push", accent: "strength", exercises: ["Bench", "OHP", "Dips"], delivery: "Logged from Hevy", deliveryColor: "green", status: "COMPLETED", statusKind: "completed", dot: "green" },
      { day: "Tue", name: "Zone 2", accent: "cardio", exercises: ["8.2 km easy"], delivery: "Logged from Garmin", deliveryColor: "green", status: "COMPLETED", statusKind: "completed", dot: "green" },
      { day: "Wed", name: "Pull", accent: "strength", today: true, exercises: ["Deadlift", "Row", "Pull-ups", "Curl"], delivery: "Ready in Hevy", deliveryColor: "green", status: "PLANNED", statusKind: "planned", dot: "blue" },
      { day: "Thu", name: "Legs", accent: "strength", exercises: ["Squat", "RDL", "Leg curl"], delivery: "Needs review in Hevy", deliveryColor: "amber", warn: "Needs ≥60 readiness", status: "PLANNED", statusKind: "planned", dot: "amber" },
      { day: "Fri", name: "Zone 2", accent: "cardio", exercises: ["Run · 35 min"], delivery: "Scheduled in Garmin", deliveryColor: "green", was: "Upper", status: "REPLACED", statusKind: "replaced", dot: "amber" },
      { day: "Sat", name: "Upper", accent: "strength", exercises: ["Incline", "Row", "Lateral"], delivery: "Created in Hevy", deliveryColor: "green", status: "PLANNED", statusKind: "planned", dot: "blue" },
      { day: "Sun", name: "Rest", accent: "rest", rest: true, exercises: [], delivery: "", status: "REST DAY", statusKind: "rest", dot: "violet" },
    ],
  },

  builder: {
    title: "Pull · Hypertrophy",
    crumb: ["Plan", "Wed Jun 17", "Pull Hypertrophy"],
    synced: "synced 2m ago",
    summary: "5 exercises · ~50 min",
    exercises: [
      {
        name: "Deadlift", expanded: true, scheme: "3×5 · RPE 8",
        sets: [
          { set: "W1", weight: "60", reps: "5", rpe: "—", kind: "warm" },
          { set: "W2", weight: "100", reps: "3", rpe: "—", kind: "warm" },
          { set: "1", weight: "140", reps: "5", rpe: "7", kind: "work" },
          { set: "2", weight: "140", reps: "5", rpe: "8", kind: "work" },
          { set: "3", weight: "140", reps: "5", rpe: "8", kind: "work" },
        ],
        progression: { kind: "up", text: "↑ Progression: +2.5 kg" },
        alternatives: "Alternatives: Trap-bar DL · Rack pull",
      },
      {
        name: "Barbell Row", expanded: true, scheme: "3×8 · RPE 8",
        sets: [
          { set: "W1", weight: "40", reps: "8", rpe: "—", kind: "warm" },
          { set: "1", weight: "80", reps: "8", rpe: "7", kind: "work" },
          { set: "2", weight: "80", reps: "8", rpe: "8", kind: "work" },
          { set: "3", weight: "80", reps: "8", rpe: "8", kind: "work" },
        ],
        progression: { kind: "hold", text: "→ Hold" },
        alternatives: "Alternatives: Pendlay row · Chest-supported row",
      },
      { name: "Lat Pulldown", expanded: false, scheme: "3×10 · RPE 8 · +5 kg" },
      { name: "Face Pull", expanded: false, scheme: "3×15 · RPE 8" },
      { name: "Hammer Curl", expanded: false, scheme: "3×12 · RPE 9" },
    ],
    notes: "Brace hard on deadlifts and keep the bar close. We're holding rows to bank recovery for Thursday's legs.",
    targets: [
      { label: "Working sets", value: "17" },
      { label: "Tonnage", value: "8,240 kg" },
      { label: "Duration", value: "48–55 min" },
      { label: "Emphasis", value: "Back / biceps" },
    ],
  },

  planVsActual: {
    adherence: 85,
    selectedDay: 11,
    monthLabel: "June 2026",
    // Calendar cell layout: weeks of (n, name, status, today?) — null = empty
    weeks: [
      [{ n: 1, nm: "Push", s: "green" }, { n: 2, nm: "Z2", s: "green" }, { n: 3, nm: "Pull", s: "green" }, { n: 4, nm: "Legs", s: "orange", tag: "missed" }, { n: 5, nm: "Upper", s: "green" }, null, null],
      [{ n: 8, nm: "Push", s: "green" }, { n: 9, nm: "Z2", s: "green" }, { n: 10, nm: "Pull", s: "green" }, { n: 11, nm: "Legs", s: "orange", tag: "missed" }, { n: 12, nm: "10k", s: "amber", tag: "replaced" }, { n: 13, nm: "Upper", s: "green" }, null],
      [{ n: 15, nm: "Push", s: "green" }, { n: 16, nm: "Z2", s: "green" }, { n: 17, nm: "Pull", s: "today", tag: "today" }, null, null, null, null],
    ],
    days: {
      1:  { date: "Monday, Jun 1", planned: "Push · Strength", actual: "Push · 50 min", ac: "#46c98b", diff: "On plan — all working sets logged.", impact: "Clean start to the block. Fully recovered.", status: "ON PLAN", color: "#46c98b" },
      2:  { date: "Tuesday, Jun 2", planned: "Zone 2 · 40 min", actual: "8.0 km · 41 min", ac: "#46c98b", diff: "On plan — easy pace held under 145 bpm.", impact: "Aerobic base work, minimal fatigue cost.", status: "ON PLAN", color: "#46c98b" },
      3:  { date: "Wednesday, Jun 3", planned: "Pull · Hypertrophy", actual: "Pull · 48 min", ac: "#46c98b", diff: "On plan.", impact: "Recovery stable, no flags.", status: "ON PLAN", color: "#46c98b" },
      4:  { date: "Thursday, Jun 4", planned: "Legs · Strength", actual: "No session", ac: "#ff6b4a", diff: "Skipped — travel day, nothing synced.", impact: "First missed legs of the block. Tolerable; weekly volume still on target.", status: "MISSED", color: "#ff6b4a" },
      5:  { date: "Friday, Jun 5", planned: "Upper · Hypertrophy", actual: "Upper · 55 min", ac: "#46c98b", diff: "On plan — picked up some leg-adjacent accessory volume.", impact: "Compensated lightly for missed legs.", status: "ON PLAN", color: "#46c98b" },
      8:  { date: "Monday, Jun 8", planned: "Push · Strength", actual: "Push · 52 min", ac: "#46c98b", diff: "On plan — bench +2.5 kg cleared.", impact: "Good readiness, progression on track.", status: "ON PLAN", color: "#46c98b" },
      9:  { date: "Tuesday, Jun 9", planned: "Zone 2 · 40 min", actual: "8.2 km · 44 min", ac: "#46c98b", diff: "On plan.", impact: "Low-cost aerobic work.", status: "ON PLAN", color: "#46c98b" },
      10: { date: "Wednesday, Jun 10", planned: "Pull · Hypertrophy", actual: "Pull · 49 min", ac: "#46c98b", diff: "On plan.", impact: "No recovery flags.", status: "ON PLAN", color: "#46c98b" },
      11: { date: "Thursday, Jun 11", planned: "Legs · Strength", actual: "No session", ac: "#ff6b4a", diff: "Skipped — no session logged. Second missed legs in 8 days.", impact: "Quads & hams under-stimulated this week. Coach moved Legs to Thu Jun 18 and protected both rest days.", status: "MISSED", color: "#ff6b4a" },
      12: { date: "Friday, Jun 12", planned: "Zone 2 · 35 min easy", actual: "10.2 km run · 52 min", ac: "#e0a23b", diff: "Ran harder & longer than prescribed: +17 min, avg HR 162 (Zone 4).", impact: "Acute load spiked, pushing ACWR up. Saturday's upper was trimmed by 2 sets.", status: "REPLACED", color: "#e0a23b" },
      13: { date: "Saturday, Jun 13", planned: "Upper · Hypertrophy", actual: "Upper · 46 min (−2 sets)", ac: "#46c98b", diff: "Completed, auto-trimmed after Friday's hard run.", impact: "Volume reduced to keep load in range. Smart adjustment.", status: "ON PLAN", color: "#46c98b" },
      15: { date: "Monday, Jun 15", planned: "Push · Strength", actual: "Push · 52 min", ac: "#46c98b", diff: "On plan.", impact: "Strong session, recovery high.", status: "ON PLAN", color: "#46c98b" },
      16: { date: "Tuesday, Jun 16", planned: "Zone 2 · 40 min", actual: "8.2 km · 44 min", ac: "#46c98b", diff: "On plan.", impact: "Nudged load slightly with Monday push.", status: "ON PLAN", color: "#46c98b" },
      17: { date: "Wednesday, Jun 17 · Today", planned: "Pull · Hypertrophy", actual: "Not started yet", ac: "#9aa3b4", diff: "Session scheduled for today.", impact: "Readiness 72 — cleared to train as planned.", status: "PLANNED", color: "#4f8cff" },
    },
  },

  trainingBlock: {
    name: "Hypertrophy — Summer Cut",
    sub: "6-week block · Jun 1 – Jul 12 · paired with Cut body mode",
    weekIndex: 3, weekCount: 6,
    phases: [
      { wk: "W1", phase: "Accumulate", state: "done", sets: 18 },
      { wk: "W2", phase: "Accumulate", state: "done", sets: 20 },
      { wk: "W3", phase: "Intensify", state: "current", sets: 22 },
      { wk: "W4", phase: "Intensify", state: "planned", sets: 24 },
      { wk: "W5", phase: "Peak", state: "planned", sets: 24 },
      { wk: "W6", phase: "Deload", state: "deload", sets: 12 },
    ],
    focus: "Push intensity on compounds while holding total volume. RPE targets climb to 8–9 on top sets.",
    deload: "Deload in 3 weeks — volume drops ~50%, intensity held. A planned recovery week to consolidate gains.",
  },

  recoveryRules: [
    { label: "No heavy legs under 60 readiness", description: "Skip or swap heavy lower-body work on low-recovery days.", enabled: true, threshold: 60 },
    { label: "Avoid hard running within 24h of heavy squats", description: "Protects legs from compounding fatigue.", enabled: true },
    { label: "Minimum 2 rest days per week", description: "Guarantees recovery headroom across the week.", enabled: true },
    { label: "Prefer strength before cardio", description: "Order sessions to protect lifting quality.", enabled: true },
    { label: "Keep weekday workouts under 60 minutes", description: "Caps session length on busy days.", enabled: false },
  ],

  notificationPrefs: [
    { key: "dailyPlan", label: "Daily plan", description: "Morning nudge with today's session.", enabled: true },
    { key: "recoveryAlerts", label: "Recovery alerts", description: "When readiness drops below your guardrails.", enabled: true },
    { key: "planDrift", label: "Plan drift", description: "When you miss or change a planned session.", enabled: true },
    { key: "weeklyReview", label: "Weekly review", description: "When your weekly review is ready.", enabled: true },
    { key: "quietHours", label: "Quiet hours 21:00–06:00", description: "Hold non-urgent nudges overnight.", enabled: false },
  ],
  pushNotifications: {
    available: false,
    subscribed: false,
    publicKey: null,
    hint: "Checking browser push support…",
  },

  nudges: [
    { kind: "coach", title: "Today: Upper Pull, 45–60 min", body: "Ready in Hevy", color: "blue", actions: [] },
    { kind: "alert", title: "Recovery Alert", body: "Readiness low — swap to Zone 2 or rest.", color: "amber", actions: ["Swap to Z2", "Rest day"] },
    { kind: "drift", title: "Plan Drift", body: "You missed legs. Re-plan the rest of the week?", color: "orange", actions: ["Re-plan week", "Dismiss"] },
    { kind: "review", title: "Weekly Review", body: "Your weekly review is ready.", color: "green", actions: [] },
  ],

  coachMemory: {
    injuries: ["Right shoulder — avoid heavy OHP", "Lower back — sensitive to deficit deads"],
    schedule: ["Train mornings", "Busy Thursdays", "≤ 5 sessions / wk"],
    equipment: ["Full barbell gym", "Home: DBs + bands"],
    prefers: ["Free weights", "Pull-ups"],
    dislikes: ["Burpees", "Leg press"],
    targetEvent: { title: "Half marathon", meta: "Oct 5 · 16 weeks out" },
    bodyGoal: { title: "Cut to 13% BF", meta: "Hold strength · −0.4 kg/wk" },
  },

  bodyMode: {
    mode: "cut", // cut | bulk | recomp | perf
    weekIndex: 3, weekCount: 8,
    descriptor: "Keep strength volume high. Cap hard cardio if recovery drops below 60.",
    modes: [
      { key: "cut", label: "Cut" },
      { key: "bulk", label: "Bulk" },
      { key: "recomp", label: "Recomp" },
      { key: "perf", label: "Perf" },
    ],
    weight: { value: "78.4 kg", delta: "−1.6 kg", trend: [80.0, 79.6, 79.3, 79.0, 78.8, 78.6, 78.4], color: "var(--rest)" },
    bodyFat: { value: "15.2 %", delta: "−0.9 pt", trend: [16.1, 15.9, 15.7, 15.6, 15.4, 15.3, 15.2], color: "var(--train)" },
    weeklyTargets: [
      { label: "Active days", value: 3, target: 4, unit: "", accent: "train" },
      { label: "Strength", value: 1, target: 3, unit: "", accent: "strength" },
      { label: "Cardio", value: 8.2, target: 15, unit: " km", accent: "cardio" },
    ],
    bias: "Suggested bias: protein 1.9 g/kg, keep steps ≥ 9k, one extra strength session this week.",
  },
};
