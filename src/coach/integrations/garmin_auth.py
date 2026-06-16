"""One-time Garmin Connect authorization. Run: `coach-garmin-auth`.

Garmin has no official API. This does a single full login (username/password,
plus an MFA code if your account uses 2FA), then stores the resulting garth
session token in the DB. Every subsequent `coach-sync` reuses that token instead
of logging in again — which is the key to staying off Garmin's rate-limit /
lockout radar on the unofficial endpoints.

Run this locally. If the prod DB is remote (e.g. Railway), point DATABASE_URL at
its public URL first so the token lands in the database the prod service reads
(same pattern as Strava/Withings auth).
"""
from __future__ import annotations

import getpass

from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from coach.config import settings
from coach.db import init_db
from coach.integrations.garmin import login_with_credentials, save_token


def _prompt_mfa() -> str:
    return input("Garmin MFA code (check your email/authenticator): ").strip()


def main() -> None:
    init_db()

    email = settings.garmin_email or input("Garmin email: ").strip()
    password = settings.garmin_password or getpass.getpass("Garmin password: ")
    if not email or not password:
        raise SystemExit("Garmin email and password are required.")

    print("Logging in to Garmin Connect (one-time)...")
    try:
        blob = login_with_credentials(email, password, prompt_mfa=_prompt_mfa)
    except GarminConnectTooManyRequestsError:
        raise SystemExit(
            "Garmin rate-limited this login. Wait ~15-60 min before retrying — "
            "repeated logins make this worse."
        )
    except GarminConnectAuthenticationError as exc:
        raise SystemExit(f"Garmin authentication failed: {exc}")

    save_token(blob)
    print("Garmin authorized. Session token saved to the DB.")
    print("Now run `coach-sync` to pull your health data.")


if __name__ == "__main__":
    main()
