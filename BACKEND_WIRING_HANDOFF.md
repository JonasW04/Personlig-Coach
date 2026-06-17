# Coach — Backend Wiring Handoff

**Audience:** an engineer/model picking up the Coach app after the V2 UI redesign.
**Goal:** wire the new 9-screen PWA to live backend data, screen by screen.
**Date:** 2026-06-17

---

## 0. Read this first — the product constraint

Coach is a **planner / adapter, NOT a workout tracker**. This is a hard product rule and it shapes every decision below:

- No "Start session", rest timers, set check-off, or in-app logging.
- The athlete trains and logs in **Hevy** (strength) and **Garmin Connect** (cardio).
- Coach's job: generate a weekly plan → push strength routines into Hevy via API → schedule cardio in Garmin → sync completed work back → compare planned vs actual → adapt.
- Primary CTAs on workout screens **deep-link out** to Hevy/Garmin; they do not run a workout in-app.

When wiring any screen, keep the action buttons as deep-links + plan adjustments. Do not add tracking UI.

---

## 1. Architecture map

**Backend:** Python FastAPI, `src/coach/web/app.py`. SQLAlchemy models in `src/coach/models.py`. SQLite/Postgres via `src/coach/db.py` (`SessionLocal`, `init_db`). Auth is a single signed session cookie (password gate); every `/api/*` route requires it (`require_auth` middleware) and returns 401 otherwise.

**Frontend:** vanilla PWA in `src/coach/web/static/`:
- `index.html` — shell: appbar, 11 `<section class="screen">` mounts, bottom tabbar, toast.
- `coach.css` — full design system (tokens, primitives, responsive at 880px breakpoint).
- `coach.data.js` — `window.STATE`: **static spec data** for every screen (this is what we're replacing with live data).
- `coach.icons.js` — `window.ICONS` inline SVG.
- `coach.screens.js` — `window.SCREENS`: pure functions returning HTML strings from `STATE`.
- `coach.js` — app core: `VIEWS` router config, `nav(view)`, delegated `data-action` click handler, live wiring for chat/sync/reviews.

**Integrations (`src/coach/integrations/`):** strava, withings, garmin, hevy, notion (+ `_auth` helpers). **Important:** `hevy.py` and `garmin.py` are currently **read-only** (they sync completed data IN). Pushing routines/schedules OUT does not exist yet.

**Agent:** Gemini coordinator (`src/coach/agents/gemini.py`) with tools in `src/coach/tools/`. Reports generated in `src/coach/reports.py` (`generate_and_store(kind)`), readiness in `readiness.py`, review in `review.py`.

---

## 2. Status: live vs static, per screen

| Screen | View id | Current data | Status |
|---|---|---|---|
| Today | `today` | `STATE.today` (static) | **Static** — but live source EXISTS (`/api/health`) |
| Weekly Plan | `plan` | `STATE.weekPlan` (static) | **Static** — needs new plan engine |
| Workout Builder | `builder` | `STATE.builder` (static) | **Static** — needs plan engine + Hevy push |
| Plan vs Actual | `actual` | `STATE.planVsActual` (static) | **Static** — needs plan engine + `/api/stats` |
| Training Blocks | `blocks` | `STATE.trainingBlock` (static) | **Static** — needs new blocks model |
| Recovery Rules | `rules` | `STATE.recoveryRules` (static) | **Static** — needs new rules model |
| Coach Memory | `memory` | `STATE.coachMemory` (static) | **Static** — `/api/memories` exists but shape differs (see §4.7) |
| Goals & Body Mode | `goals` | `STATE.bodyMode` (static) | **Partly live** — `/api/goals` exists; body mode is new |
| Notifications | `notifications` | `STATE.notificationPrefs`, `STATE.nudges` (static) | **Static** — `/api/push/*` exists; prefs persistence is new |
| Reviews | `reviews` | `/api/reports` | **LIVE** ✅ |
| Chat | `chat` | `/api/chat` streaming | **LIVE** ✅ |

Two screens are already fully wired (Reviews, Chat). The other nine read from `coach.data.js`.

---

## 3. Existing API surface (reuse these)

All under `/api`, all auth-gated, defined in `app.py`:

- `POST /api/sync` → runs `coach.sync.run()`; returns `{running, ...}`. **Already wired** to the Sync buttons via `runSync()` in `coach.js:152`.
- `GET /api/health?start&end` → `{days:[...]}` Garmin recovery rows. Each day has: `training_readiness`, `training_readiness_level/feedback`, `training_status`, `acute_load`, `chronic_load`, `acwr`, `acwr_status`, `sleep_hours`, `sleep_score`, `hrv`, `hrv_status`, `body_battery_high/low`, `avg_stress`, `resting_hr`, `steps`, etc. (see `web/stats.py:_health_day`). **This is the Today screen's data source.**
- `GET /api/stats?start&end` → `{days:[...], body:[...], goals:[...]}`. Activity per day (`strength:{minutes,exercises}`, `cardio:{type,minutes,km}`) + body measurements + goals. **This is Plan-vs-Actual's "actual" source.**
- `GET/PUT /api/goals` → fixed metric goals (keys in `DEFAULT_GOALS`, `app.py:159`). **Goals screen's data source.**
- `GET /api/reports?kind&limit`, `POST /api/reports/generate {kind: readiness|weekly|health}` → reports. **Reviews, wired.**
- `GET/POST/DELETE /api/memories` → flat list of free-text coach memories. See §4.7 for the shape mismatch.
- `GET/POST /api/focus` → single training directive (`focus_raw` → generated `directive`). Drives report/agent tone.
- `GET/POST /api/actions` (+ PATCH/DELETE) → checkable action items, optionally linked to goals.
- `GET/POST /api/push/config|subscribe|unsubscribe` → Web Push (VAPID).
- `POST /api/chat` (ndjson stream), `GET /api/chats`, `GET /api/chats/{sid}/messages`. **Chat, wired.**

---

## 4. Per-screen wiring plan

For each screen: **(a)** what backend to build, **(b)** the JSON contract, **(c)** the frontend change. Frontend changes follow one pattern: replace the `STATE.x` read in `coach.screens.js` with data fetched in the view's `after:` hook (add one to `VIEWS` in `coach.js`, mirror how `reviews`/`chat` do it), render a loading state first, then re-render.

### 4.1 Today  — *quickest win, do first*

The Today screen shows readiness score, verdict (TRAIN/EASY/REST), sleep/HRV/body-battery/resting-HR, ACWR, a recent-days strip, and a warning. **All of this already exists in `/api/health`.**

- **(a) Backend:** none new. Optionally add `GET /api/today` that bundles: latest `/api/health` day + today's planned workout (once the plan engine exists) + the latest readiness report snippet. For now, call `/api/health` (signature is `start`/`end` only — there is NO `limit` param) and take the most-recent day client-side via `days.at(-1)` (the array is oldest-first).
- **Scope note:** `today.planned` needs the plan engine and `today.recent` is workout data from `/api/stats`, NOT `/api/health`. For this step, wire ONLY the recovery fields below and leave `planned` + `recent` on their static fallback.
- **(b) Contract:** use `_health_day` shape above. Map: `readiness=training_readiness`, verdict from `training_readiness_level` (or threshold the score), `sleep=sleep_hours/sleep_score`, `hrv/hrv_status`, `bodyBattery=body_battery_high`, `restingHr=resting_hr`, `acwr/acwr_status`. The "warning" line = a readiness rule hit (see Recovery Rules §4.6) or `acwr_status != OPTIMAL`.
- **(c) Frontend:** add `today: { tab:"today", render: S.today, after: wireToday }` to `VIEWS`; `wireToday` fetches `/api/health`, maps to the shape `SCREENS.today` expects, stores in `STATE.today`, re-renders. Keep static fallback if the fetch fails.

### 4.2 Weekly Plan + 4.3 Workout Builder + 4.4 Plan vs Actual — *the plan engine (biggest piece)*

These three share one new subsystem: **a weekly plan stored in the DB and generated by the coach.**

- **(a) Backend — new:**
  - **Model** `PlanDay` (or `PlannedSession`): `id`, `date`, `kind` (`strength|cardio|rest`), `title`, `status` (`planned|ready_in_hevy|scheduled|done|missed|replaced`), `hevy_routine_id` (nullable), `garmin_workout_id` (nullable), `payload_json` (exercises/sets/scheme for strength; type/duration/zone for cardio), `block_id` FK (→ §4.5), `created_at/updated_at`.
  - **Plan engine** `src/coach/plan.py`: `generate_week(week_start) -> list[PlanDay]` using the coordinator agent + current focus + recovery state + training block phase. This is an LLM call that emits structured sessions (reuse the report/agent infra; emit JSON, validate, persist).
  - **Endpoints:**
    - `GET /api/plan?week=current` → `{week_start, days:[PlanDay...]}`.
    - `POST /api/plan/generate {week_start}` → regenerate (the "Regenerate week" button).
    - `POST /api/plan/replan {from_date}` → re-plan remaining days (the "Re-plan from today" / "Re-plan" buttons).
    - `GET /api/plan/day/{date}` → one session with full `payload_json` (Workout Builder).
  - **Hevy push** (`src/coach/integrations/hevy.py`, new functions): Hevy API has `POST /v1/routines` and `PUT /v1/routines/{id}`. Add `create_routine(payload)` / `update_routine(id, payload)` mapping a strength `PlanDay.payload_json` → Hevy routine schema (exercise_template_id, sets with weight/reps/rpe/type). Wire `POST /api/plan/day/{date}/push-hevy` → creates/updates the routine, stores `hevy_routine_id`, sets status `ready_in_hevy`. The Builder's "Open in Hevy" deep-links to `https://hevy.com/routine/{hevy_routine_id}` (replace the current static `https://hevy.com/`).
    - Note: matching exercises to Hevy `exercise_template_id` needs a lookup. Hevy exposes `GET /v1/exercise_templates`. Cache these and fuzzy-match by name, or maintain a mapping table.
  - **Garmin scheduling** (`src/coach/integrations/garmin.py`, new): Garmin is an **unofficial API** (`garminconnect` lib). Pushing a structured workout + scheduling it onto a date is supported by some lib versions (`add_workout`, `schedule_workout`) but is fragile. Treat as best-effort: `POST /api/plan/day/{date}/schedule-garmin`. If it proves unreliable, fall back to a deep-link to Garmin Connect's calendar and let the user add it. **Validate the lib's capability before promising this.** A Garmin workout needs a sport type, so cardio `PlanDay.payload_json` must carry a `cardio_type` enum (`running | cycling | walking | cardio`, default `cardio`) — without it the backend can only create an ambiguous generic workout. The "Schedule in Garmin" CTA on cardio day cards calls the endpoint and falls back to the deep-link. **All of this requires the Step 3 plan engine + `PlanDay` to exist first — do not add `cardio_type` to a plan structure that isn't there yet.**
- **(b) Contracts:**
  - Weekly Plan card per day: `{date, weekday, kind, title, delivery: "Hevy"|"Garmin"|"—", status}`. Maps to `SCREENS.plan` day cards (status dot colors already keyed via `DOTCOL`).
  - Builder: `{title, crumb, synced, summary, exercises:[{name, scheme, expanded, sets:[{set,weight,reps,rpe,kind}], progression:{kind,text}, alternatives}], notes, targets:[{label,value}]}`. This matches `STATE.builder` exactly — generate it from `PlanDay.payload_json`.
  - Plan vs Actual: planned side = `PlanDay`; actual side = `/api/stats` activity days. Compute adherence = % of planned sessions with a matching actual within the date. Per-day: `{date, status: ON PLAN|MISSED|REPLACED|PLANNED, planned, actual}`.
- **(c) Frontend:** add `after:` hooks to `plan`, `builder`, `actual` views; fetch and map into the existing `STATE` shapes (the renderers already expect these shapes, so minimal renderer changes). Replace `replan-today`/`regenerate-week`/`open-hevy`/`open-garmin` toast stubs in `coach.js:88-93` with real fetches + deep-links.

### 4.5 Training Blocks

- **(a) Backend — new:** model `TrainingBlock`: `id`, `name`, `goal` (hypertrophy/strength/…), `start_date`, `end_date`, `body_mode` (links to §4.8), `phases_json` (`[{week, label, sets_per_mg, status}]`) or a child `BlockWeek` table, `active` bool. Endpoints `GET /api/blocks`, `POST /api/blocks` ("New block"), `PATCH /api/blocks/{id}`. The plan engine (§4.2) should read the active block to bias weekly volume/intensity.
- **(b) Contract — the renderer (`blocks()` in coach.screens.js) is the source of truth; its EXACT shape is:** `{name, sub, weekIndex, weekCount, focus, deload, phases:[{wk, phase, sets, state}]}` where `state ∈ {done, current, planned, deload}`, `sub` is the subtitle line (date range + goal), `focus`/`deload` are coaching prose, `wk` is the week label ("W1"), `phase` is the phase name ("Accumulate"), `sets` is sets-per-muscle-group (number). `pct` is derived from `weekIndex/weekCount`. Map your backend model into THESE field names, not the approximation that was previously here.
- **(c) Frontend:** `after:` hook on `blocks`; replace `new-block` toast (`coach.js:94`).

### 4.6 Recovery Rules

User-defined guardrails (e.g. "if readiness < 40, swap to Zone 2") that gate the plan and produce Today's warnings.

- **(a) Backend — new:** model `RecoveryRule`: `id`, `condition_json` (`{metric, op, value}` e.g. `{metric:"training_readiness", op:"<", value:40}`), `action` (text or structured: `swap_to_zone2|rest|reduce_volume`), `enabled`, `order_index`. Endpoints `GET/POST/PATCH/DELETE /api/rules`. A `rules.evaluate(health_day) -> [triggered]` helper feeds Today's warning and the plan/replan engine.
- **(b) Contract — the `rules()` renderer requires `[{label, description, enabled, threshold?}]`** (`threshold` = a 0–100 gauge marker position, optional). So store `label` + `description` as columns (prose, not derivable). `condition_json` (`{metric, op, value}`) is **NULLABLE** — many real rules are structural/scheduling guardrails with no single-day numeric trigger (e.g. "Minimum 2 rest days per week", "Prefer strength before cardio"); these have no condition and no threshold. Derive `threshold` from `condition_json.value` ONLY when a condition exists AND the metric has a 0–100 scale: readiness/sleep_score/body_battery/avg_stress → value directly; acwr (0–2) → `value/2*100`; hrv/resting_hr have no natural 0–100 scale → `threshold = null` (renderer hides the bar). Supported metrics initially = those present in `_health_day`: `training_readiness, acwr, sleep_score, hrv, body_battery_high, resting_hr, avg_stress`. Operators: `<, <=, >, >=`. Evaluation (`triggered`) considers ONLY condition-bearing rules against the latest health day.
- **(c) Frontend:** `togglePref`/`toggleRule` in `coach.js:108` currently only flip local state. Make `toggleRule` PATCH `/api/rules/{id}`. Replace `add-rule` toast (`coach.js:101`).

### 4.7 Coach Memory — *note the shape mismatch*

- **Existing:** `GET/POST/DELETE /api/memories` returns a **flat list** of free-text facts (`CoachMemory` model: `content`, `source`). Injected into the agent + reports.
- **Screen expects:** **categorized** chips — `STATE.coachMemory = {injuries:[], schedule:[], equipment:[], prefers:[], dislikes:[], targetEvent, bodyGoal}`.
- **(a) Two options:**
  1. *Minimal:* keep the flat store; add a `category` column to `CoachMemory` (default `"note"`); have the POST accept `{content, category}`; group by category in the response. Frontend maps groups → chip sections.
  2. *Keep flat + derive:* render all memories under one "Coach Memory" section and drop the fixed categories. Less faithful to the design but zero migration.
- **Recommendation:** option 1 — add `category`, it's a one-column migration and preserves the design. The chip "× remove" → `DELETE /api/memories/{id}`; "+ add" → either inline POST or (per current copy) "tell Coach in chat".
- **(c) Frontend:** `remove-chip` (`coach.js:103`) currently just removes the DOM node — wire it to DELETE. `add-chip` (`coach.js:102`) → POST or chat deep-link.

### 4.8 Goals & Body Mode

- **Existing:** `/api/goals` (fixed metric goals) is live and ready to wire.
- **Body Mode is new.** The `goals()` renderer is data-driven: it renders whatever modes are in `g.modes` and crashes if `g.mode` isn't one of them. The shipped prototype's canonical set is **`cut | bulk | recomp | perf`** (NOT "Cut/Maintain/Bulk" — that was an earlier approximation; `recomp` covers the maintain role). `setMode` (`coach.js:118`) only flips local state. Each mode owns a deterministic `descriptor` + `bias` string (a backend `MODE_SPECS` lookup, mirroring the `DEFAULT_GOALS` pattern — no LLM), so the plan engine and the screen share the same copy. Changing mode starts a NEW body-mode period: store `mode` + `mode_started_at` + `week_count` (default 8) and DERIVE `weekIndex = weeks_since(mode_started_at)+1` (clamped) rather than storing a mutable counter — so a mode switch naturally resets progress to week 1.
- **(a) Backend — new:** either extend `CoachProfile` (singleton) with `body_mode` + `body_targets_json`, or a small `BodyMode` table. Endpoint `GET/PUT /api/body-mode`. The plan engine reads it (a cut biases toward maintenance volume + cardio). Weight/bodyfat trends come from `/api/stats` `body[]`.
- **(c) Frontend:** wire `goals` view to `/api/goals` + `/api/body-mode`; make `setMode` PUT then re-render.

### 4.9 Notifications & Nudges

- **Existing:** `/api/push/*` (subscribe/unsubscribe/config) is live. The lock-screen mock + nudges are presentational.
- **(a) Backend — new:** model `NotificationPref` storing the renderer's five keys VERBATIM (they're UI-owned identifiers — don't invent a snake_case parallel): `dailyPlan, recoveryAlerts, planDrift, weeklyReview, quietHours`, each with `enabled`. Endpoints `GET/PUT /api/notification-prefs`, returned in that order.
- **Gating model:** report GENERATION stays unconditional (reports are persisted artifacts visible in Reviews regardless of prefs). Prefs gate DELIVERY only — `scheduler.py`/`notify.py` check the pref before calling `notify.send()`. What's actually wireable NOW: (1) `weeklyReview` → gate the existing weekly-review push; (2) `quietHours` → a delivery-time suppression check inside `notify.send()` for non-urgent sends. The rest are TODOs tied to other steps: `recoveryAlerts` needs the Step 6 rules-triggered producer; `dailyPlan` + `planDrift` need the Step 3 plan engine + drift detection. **Persist all five prefs now; leave clearly-marked TODOs (not fake stubs) where the missing producers will call `notify.send()`.**
- **Master push toggle:** the per-pref toggles are inert without an actual browser subscription, so add ONE master "Push notifications" row above them that drives the service-worker + VAPID subscribe/unsubscribe via the existing `/api/push/subscribe|unsubscribe`. Only enable it when `/api/push/config` returns `enabled:true`; otherwise show it disabled with a hint. (The guide pre-blessed this — it's not scope creep.)
- "Nudges" = derived from current state (low readiness, missed legs, review ready) — can be a `GET /api/nudges` computed endpoint or folded into `/api/today`. Depends on Steps 3/6; keep static until then.
- **(c) Frontend:** `togglePref` (`coach.js:113`) → PUT `/api/notification-prefs`. Hook the actual subscribe flow (service worker + VAPID) to the master toggle.

---

## 5. New data models summary

Add to `src/coach/models.py` (and `init_db` picks them up; if using Alembic, add migrations):

1. `PlanDay` / `PlannedSession` — the weekly plan (§4.2). **Core.**
2. `TrainingBlock` (+ optional `BlockWeek`) — periodization (§4.5).
3. `RecoveryRule` — structured guardrails (§4.6).
4. `CoachMemory.category` column — categorized memory (§4.7).
5. Body mode: column on `CoachProfile` or new `BodyMode` table (§4.8).
6. `NotificationPref` — push toggles (§4.9).

New integration code:
- `hevy.create_routine` / `update_routine` + exercise-template matching (§4.2). **Core.**
- `garmin` workout push/schedule — best-effort, validate first (§4.2).

---

## 6. Recommended sequencing

1. **Today → `/api/health`** (no backend work; immediate realism). *§4.1*
2. **Goals → `/api/goals`** + **Coach Memory → `/api/memories`** (endpoints exist; small frontend wiring + memory `category` migration). *§4.7, §4.8*
3. **Plan engine MVP**: `PlanDay` model + `GET /api/plan` + `generate_week` + wire Weekly Plan and Plan-vs-Actual (actual from `/api/stats`). Hold Hevy push for the next step. *§4.2–4.4*
4. **Hevy routine push**: `create/update_routine` + exercise-template matching + Builder "Open in Hevy" real deep-link. *§4.2*
5. **Training Blocks** + feed block phase into the plan engine. *§4.5*
6. **Recovery Rules** (structured) + feed into Today warning and replan. *§4.6*
7. **Body Mode** + feed into plan engine. *§4.8*
8. **Notification prefs** + scheduler gating; **Garmin scheduling** last (riskiest). *§4.9, §4.2*

Each step is independently shippable and leaves the app working (static fallback stays until each screen is wired).

---

## 7. Frontend wiring recipe (apply per screen)

1. In `coach.js`, add an `after:` hook to the screen's `VIEWS` entry (model: `reviews`/`chat`).
2. The hook fetches the endpoint, maps the JSON into the exact `STATE.<screen>` shape the renderer in `coach.screens.js` already expects, then calls `nav(view)` again or patches the DOM. Keep the static `STATE` as the fallback on fetch failure.
3. Replace the relevant `data-action` stub in the delegated handler (`coach.js:82-104`) with a real `fetch`. Current stubs to replace: `replan-today`, `regenerate-week`, `new-block`, `swap-exercise`, `add-rule`, `add-chip`, `remove-chip`, and the `toggle-rule`/`toggle-pref`/`set-mode` local-only togglers.
4. Deep-links: `open-hevy`/`open-garmin` (`coach.js:88-89`) must use the real `hevy_routine_id` / Garmin URL once the plan engine stores them.

---

## 8. Dev environment notes

- Backend run: `coach-web` (uvicorn, port 8000). Local Postgres on **port 5433**. Install with `pip install .` (NOT `-e` — there's a provenance/.pth bug on this machine).
- The static preview server (`.claude/launch.json`, port 4178, `python3.12 -m http.server`) serves **only static files** — `/api/*` returns 404 there, so Reviews shows "Could not load reports" and Chat won't stream. **Test live wiring against the real `coach-web` server, not the static preview.**
- Deploy: Railway, single web service + Postgres, custom Dockerfile (the SDK shells out to the Node `claude` CLI).

---

## 9. Gotchas

- **Don't break the planner-not-tracker rule** (§0). No tracking UI.
- The renderers in `coach.screens.js` are **pure string functions** keyed to specific `STATE` shapes. Match the shape exactly or update the renderer — don't half-map.
- `nav(view)` injects the subnav via a `String.replace('<div class="screen-inner">', ...)`. Keep that wrapper as the first element of every screen's HTML.
- Memory/focus changes call `chat_sessions.close_all()` so live chat clients rebuild with new context — preserve that pattern when adding plan/block/rule context to the agent.
- Garmin is an **unofficial** API; scheduling may break on Garmin's side. Make it best-effort with a deep-link fallback.
- Auth: every new `/api/*` route is auto-protected by `require_auth`; no extra work, but remember it returns 401 (not a redirect) for API paths.
