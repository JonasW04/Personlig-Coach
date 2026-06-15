"""Sync entrypoint. Pulls Hevy + Strava + Withings into Postgres. Run via `coach-sync`.

Schedule on the VPS with cron, e.g. nightly:
    0 3 * * * cd /opt/coach && .venv/bin/coach-sync >> /var/log/coach-sync.log 2>&1
"""
from coach.config import settings
from coach.db import SessionLocal, init_db
from coach.integrations import hevy, strava, withings
from coach.models import OAuthToken


def run() -> dict:
    """Pull fresh data from configured providers and return a small summary."""
    init_db()
    results = []

    if settings.hevy_api_key:
        count = hevy.sync()
        results.append({
            "source": "hevy",
            "status": "synced",
            "count": count,
            "message": f"Synced {count} Hevy workouts.",
        })
    else:
        results.append({
            "source": "hevy",
            "status": "skipped",
            "count": 0,
            "message": "Skipping Hevy (HEVY_API_KEY not set).",
        })

    with SessionLocal() as s:
        strava_authorized = s.get(OAuthToken, "strava") is not None
    if strava_authorized:
        count = strava.sync()
        results.append({
            "source": "strava",
            "status": "synced",
            "count": count,
            "message": f"Synced {count} new Strava activities.",
        })
    else:
        results.append({
            "source": "strava",
            "status": "skipped",
            "count": 0,
            "message": "Skipping Strava (not authorized — run `coach-strava-auth`).",
        })

    with SessionLocal() as s:
        withings_authorized = s.get(OAuthToken, "withings") is not None
    if withings_authorized:
        count = withings.sync()
        results.append({
            "source": "withings",
            "status": "synced",
            "count": count,
            "message": f"Synced {count} Withings measurement groups.",
        })
    else:
        results.append({
            "source": "withings",
            "status": "skipped",
            "count": 0,
            "message": "Skipping Withings (not authorized — run `coach-withings-auth`).",
        })

    return {"results": results}


def main() -> None:
    for result in run()["results"]:
        print(result["message"])


if __name__ == "__main__":
    main()
