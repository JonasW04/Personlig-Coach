# Ideal weekly review flow

The weekly review should close the completed week and directly prepare the next one. It
should be observable, repeatable, automatic, and safe to regenerate.

```mermaid
flowchart TD
    subgraph Triggers
        scheduled["Scheduled Sunday review"]
        manual["User selects Generate or Regenerate"]
    end

    scheduled --> request["Create weekly-review request"]
    manual --> request

    request --> run["Create ReviewRun<br/>queued status + run ID"]
    run --> duplicate{"Review already running or complete<br/>for this completed week?"}
    duplicate -->|Yes, normal request| existing["Return the existing run/report"]
    duplicate -->|No, or force regenerate| lock["Acquire one review lock<br/>for the completed week"]
    lock --> snapshot["Freeze an input snapshot<br/>from the latest locally available data"]

    snapshot --> inputs["Completed week + prior-week baselines<br/>current coaching context, plan vs actual,<br/>and previous actions"]
    inputs --> metrics["Compute deterministic metrics and comparisons"]

    metrics --> model["Ask the coach model for a structured ReviewPackage"]
    model --> draft["Summary, scorecard, insights, actions,<br/>and complete strength/cardio workout prescriptions"]
    draft --> valid{"Schema, exercise selection, workout,<br/>and plan guardrail checks pass?"}
    valid -->|No| repair["Repair or retry with validation feedback"]
    repair --> retries{"Retry budget remaining?"}
    retries -->|Yes| model
    retries -->|No| failed["Mark run failed with an actionable reason<br/>keep the previous review and plan unchanged"]
    valid -->|Yes| persist["Atomically save the report and actions<br/>and activate next week's plan"]

    persist --> history["Show report, actions, active plan,<br/>and workout-delivery status in the UI"]
    persist --> publish["Auto-publish every strength and cardio session<br/>using the shared workout-publishing flow"]
    publish --> pushed{"All workouts delivered?"}
    pushed -->|No| pending["Keep the plan active, record delivery errors,<br/>and retry failed workouts"]
    pending --> publish
    pushed -->|Yes| ready["Mark ReviewRun complete"]
    ready --> delivery["Queue notification delivery"]

    delivery --> quiet{"Quiet hours or temporary<br/>channel failure?"}
    quiet -->|Yes| delay["Delay and retry delivery"]
    delay --> delivery
    quiet -->|No| channels["Send web push, email, and/or Notion<br/>according to preferences"]
```

## Proposed behavior

- A Sunday review covers the Monday–Sunday week that just ended. Its actions and plan
  target the following Monday–Sunday week.
- Deterministic code calculates totals, trends, plan adherence, and completed prior
  actions. The model interprets those facts instead of discovering every number itself.
- Model output uses one validated package containing the review, actions, and next-week
  plan rather than free-form text followed by separate extraction and planning calls.
- Every strength session contains a newly generated exercise prescription with exercises,
  sets, reps, loads or effort targets, rest, and progression notes. Selection is based on
  the athlete's needs and the available Hevy exercise-template catalog; it is not limited
  to routines the athlete already has saved.
- Every cardio session contains a complete Garmin-compatible workout prescription,
  including sport, duration or distance, intensity targets, and structured steps where
  relevant.
- A regeneration creates a new version. It does not silently delete completed or edited
  actions from an earlier version.
- Recommendations become editable actions for the next week and automatically generate
  the active weekly plan. The user can still adjust or regenerate it afterward.
- The report, actions, and active plan are committed together before remote publishing.
  A generation failure leaves the previous successful review and plan untouched; a
  publishing failure leaves the new local plan active and records a retryable delivery
  error.
- After the plan is activated, strength sessions are automatically created or updated as
  Hevy routines and cardio sessions are automatically created and scheduled in Garmin.
  Each remote name starts with its local scheduled date, for example
  `2026-06-22 · Lower Strength`.
- Remote workout delivery is idempotent and retryable. A regeneration updates or replaces
  Coach-owned remote workouts instead of creating duplicates.
- Quiet hours delay notifications rather than dropping them.

## Confirmed decisions

- A successful weekly review automatically generates and activates the following week's
  plan without an approval step.
- The first implementation uses the latest data already available in the local database;
  it does not add source-freshness checks or synchronization orchestration.
- Only the schedule and an explicit user action trigger generation. Focus and
  training-block changes do not regenerate or mark the review stale.

Workout delivery is detailed in [Ideal workout publishing](./workout-publishing-ideal.md).
