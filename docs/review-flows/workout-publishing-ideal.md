# Ideal workout publishing flow

Weekly and daily reviews share one publishing pipeline. It turns active plan sessions
into complete, date-named workouts in Hevy and Garmin and safely updates them after a
replan.

```mermaid
flowchart TD
    start["Weekly or daily review activates a plan"] --> diff["Compare active sessions with their<br/>last successfully published versions"]
    diff --> next{"Next added, changed, moved,<br/>or removed session"}

    next --> name["Build canonical name:<br/>YYYY-MM-DD · Workout title"]
    name --> kind{"Session kind and change"}

    kind -->|New or changed strength| strength["Materialize the generated exercise prescription<br/>and map it to Hevy's exercise-template catalog"]
    strength --> strengthValid["Validate template matches, sets, reps,<br/>loads or RPE, rest, and progression"]
    strengthValid --> hevyExisting{"Coach-owned Hevy routine ID exists?"}
    hevyExisting -->|No| hevyCreate["Create a new Hevy routine"]
    hevyExisting -->|Yes| hevyUpdate["Update the existing Hevy routine<br/>including its date-named title"]

    kind -->|New or changed cardio| cardio["Materialize a structured Garmin workout:<br/>sport, steps, duration or distance,<br/>zones, pace, power, and recovery"]
    cardio --> garminExisting{"Coach-owned Garmin workout ID exists?"}
    garminExisting -->|No| garminCreate["Upload the workout and schedule it<br/>on the planned date"]
    garminExisting -->|Yes| garminReplace["Replace the old workout and schedule<br/>the new version on the planned date"]

    kind -->|Moved| moved{"Moved session kind?"}
    moved -->|Strength| strength
    moved -->|Cardio| cardio

    kind -->|Removed or changed to rest| cleanup["Delete, archive, or unschedule<br/>the Coach-owned remote artifact"]

    hevyCreate --> saved
    hevyUpdate --> saved
    garminCreate --> saved
    garminReplace --> saved
    cleanup --> saved["Store remote ID, payload hash,<br/>published version, and delivery status"]

    saved --> success{"Delivery succeeded?"}
    success -->|No| retry["Mark delivery pending or failed<br/>and retry without rolling back the local plan"]
    retry --> kind
    success -->|Yes| more{"More changed sessions?"}
    more -->|Yes| next
    more -->|No| done["Plan delivery complete"]
```

## Publishing contract

- Strength planning is exercise-first, not routine-first. The planner may create a new
  combination of supported exercises whenever that is better than reusing an existing
  Hevy routine. Existing user-owned routines are never overwritten.
- Exercise choice considers the training goal, movement balance, recent performance,
  fatigue, available equipment, progression, and the Hevy exercise templates that can
  actually be published. If the preferred exercise is unavailable, validation selects an
  appropriate supported alternative rather than silently fuzzy-matching a poor one.
- Cardio workouts are structured prescriptions, not titles plus duration. Garmin receives
  the relevant warm-up, work, recovery, and cool-down steps with supported intensity
  targets.
- Remote workout names use `YYYY-MM-DD · <title>` based on the session's local planned
  date. Moving a workout changes both its name and Garmin schedule.
- Coach stores remote ownership, IDs, a payload hash, and a published version per planned
  session. These fields make retries idempotent and prevent duplicate routines/workouts.
- Local review and plan generation do not roll back when a remote service is unavailable.
  Delivery remains visible as pending or failed and retries independently.
