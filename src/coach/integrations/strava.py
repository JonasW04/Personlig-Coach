"""Strava API client: OAuth token management + activity sync into Postgres.

Create an API app at https://www.strava.com/settings/api (set the
"Authorization Callback Domain" to `localhost`). Run `coach-strava-auth` once to
authorize; tokens are stored in the oauth_tokens table and refreshed as needed.

Rate limits: 200 req/15min, 2000/day. We page activities and sync incrementally.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, select

from coach.config import settings
from coach.db import SessionLocal
from coach.models import Activity, OAuthToken

PROVIDER = "strava"
TOKEN_URL = "https://www.strava.com/oauth/token"
API_URL = "https://www.strava.com/api/v3"


def save_tokens(access_token: str, refresh_token: str, expires_at: int) -> None:
    with SessionLocal() as s:
        row = s.get(OAuthToken, PROVIDER)
        if row is None:
            row = OAuthToken(provider=PROVIDER)
            s.add(row)
        row.access_token = access_token
        row.refresh_token = refresh_token
        row.expires_at = expires_at
        s.commit()


def _refresh(refresh_token: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_access_token() -> str:
    """Return a valid access token, refreshing (and persisting) if expired."""
    with SessionLocal() as s:
        row = s.get(OAuthToken, PROVIDER)
    if row is None:
        raise RuntimeError("Strava not authorized yet. Run `coach-strava-auth`.")

    if row.expires_at - 60 > int(time.time()):
        return row.access_token

    data = _refresh(row.refresh_token)
    save_tokens(data["access_token"], data["refresh_token"], data["expires_at"])
    return data["access_token"]


def fetch_activities(after: int | None = None, max_pages: int = 20) -> list[dict]:
    """Page through GET /athlete/activities (newest first within each page)."""
    token = get_access_token()
    out: list[dict] = []
    with httpx.Client(
        base_url=API_URL, headers={"Authorization": f"Bearer {token}"}, timeout=30
    ) as c:
        for page in range(1, max_pages + 1):
            params = {"per_page": 100, "page": page}
            if after:
                params["after"] = after
            resp = c.get("/athlete/activities", params=params)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            out.extend(batch)
    return out


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def upsert_activity(session, a: dict) -> None:
    aid = a["id"]
    session.execute(delete(Activity).where(Activity.id == aid))
    session.flush()
    session.add(
        Activity(
            id=aid,
            name=a.get("name"),
            sport_type=a.get("sport_type") or a.get("type"),
            start_time=_parse_dt(a.get("start_date")),
            distance_m=a.get("distance"),
            moving_time_s=a.get("moving_time"),
            elapsed_time_s=a.get("elapsed_time"),
            elevation_gain_m=a.get("total_elevation_gain"),
            average_speed_ms=a.get("average_speed"),
            average_hr=a.get("average_heartrate"),
            max_hr=a.get("max_heartrate"),
            average_watts=a.get("average_watts"),
            suffer_score=a.get("suffer_score"),
        )
    )


def sync(full: bool = False) -> int:
    """Incremental by default: only fetch activities newer than the latest stored."""
    after = None
    if not full:
        with SessionLocal() as s:
            latest = s.scalar(select(Activity.start_time).order_by(Activity.start_time.desc()))
        if latest:
            after = int(latest.replace(tzinfo=latest.tzinfo or timezone.utc).timestamp())

    activities = fetch_activities(after=after)
    with SessionLocal() as s:
        for a in activities:
            upsert_activity(s, a)
        s.commit()
    return len(activities)
