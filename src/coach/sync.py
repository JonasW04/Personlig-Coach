"""Sync entrypoint. Pulls Hevy + Strava + Withings into Postgres. Run via `coach-sync`.

Schedule on the VPS with cron, e.g. nightly:
    0 3 * * * cd /opt/coach && .venv/bin/coach-sync >> /var/log/coach-sync.log 2>&1
"""
from coach.config import settings
from coach.db import init_db
from coach.integrations import hevy, strava, withings
from coach.models import OAuthToken
from coach.db import SessionLocal


def main() -> None:
    init_db()

    if settings.hevy_api_key:
        count = hevy.sync()
        print(f"Synced {count} Hevy workouts.")
    else:
        print("Skipping Hevy (HEVY_API_KEY not set).")

    with SessionLocal() as s:
        strava_authorized = s.get(OAuthToken, "strava") is not None
    if strava_authorized:
        count = strava.sync()
        print(f"Synced {count} new Strava activities.")
    else:
        print("Skipping Strava (not authorized — run `coach-strava-auth`).")

    with SessionLocal() as s:
        withings_authorized = s.get(OAuthToken, "withings") is not None
    if withings_authorized:
        count = withings.sync()
        print(f"Synced {count} Withings measurement groups.")
    else:
        print("Skipping Withings (not authorized — run `coach-withings-auth`).")


if __name__ == "__main__":
    main()
