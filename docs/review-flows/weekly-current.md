# Current weekly review generation

```mermaid
flowchart TD
    subgraph Triggers
        scheduler["Scheduler: Sunday at 18:00"]
        ui["Reviews UI: Generate now"]
        cli["CLI: coach-review"]
        focus["Athlete focus changes"]

        ui --> api["POST /api/reports/generate<br/>kind: weekly"]
        focus --> background["Background report regeneration"]
    end

    scheduler --> generate["reports.generate_and_store('weekly')"]
    api --> generate
    cli --> generate
    background --> generate

    generate --> prompt["Load the weekly-review prompt<br/>and configured review model"]
    prompt --> coordinator["Create coach coordinator<br/>with current focus and saved memories"]

    coordinator --> toolLoop{"Does the model need data?"}
    toolLoop -->|Yes| tools["Run local read tools"]
    tools --> hevy["Hevy strength history"]
    tools --> strava["Strava cardio history"]
    tools --> garmin["Garmin recovery and load"]
    tools --> withings["Withings body trends"]
    hevy --> localDb[("Already-synced local database")]
    strava --> localDb
    garmin --> localDb
    withings --> localDb
    localDb --> toolResults["Return tool results to the model"]
    toolResults --> toolLoop
    toolLoop -->|No| review["Synthesize weekly review text<br/>ending with an Action plan"]

    review --> modelOk{"Usable model response?"}
    modelOk -->|No| error["Raise ReportGenerationError<br/>API responds 502; other callers log or fail"]
    modelOk -->|Yes| save["Insert weekly report into reports table"]

    save --> extract["Use a lightweight model to extract<br/>3–6 structured action items"]
    extract --> actionsOk{"Actions parsed?"}
    actionsOk -->|Yes| replace["Replace this week's auto-generated actions<br/>and link them to the saved report"]
    actionsOk -->|No| keep["Keep the saved report<br/>and leave existing actions unchanged"]

    replace --> notify["Attempt notification delivery"]
    keep --> notify
    notify --> allowed{"weeklyReview enabled<br/>and outside quiet hours?"}
    allowed -->|No| persisted["Stop delivery<br/>report and actions remain saved"]
    allowed -->|Yes| channels["Send to configured channels:<br/>email, Notion, and/or web push"]

    channels --> available["Review is available in report history"]
    persisted --> available
```

The data-source tools query Coach's local database, so the review reflects the latest completed sync. Generating a review does not itself fetch fresh data from the external services.
