"""Withings API client: OAuth token management + body-measurement sync.

Scale-only setup: we pull weight and body composition (fat %, fat/muscle/bone
mass, hydration). Sleep/HR types are intentionally omitted.

Create an app at https://developer.withings.com/ and register the callback URL
exactly as `http://localhost:8722/callback`. Run `coach-withings-auth` once.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from coach.config import settings
from coach.db import SessionLocal
from coach.models import BodyMeasurement, OAuthToken

PROVIDER = "withings"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"
AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"

# Withings measure type -> our column name.
MEASTYPES = {
    1: "weight_kg",
    5: "fat_free_mass_kg",
    6: "fat_ratio",
    8: "fat_mass_kg",
    76: "muscle_mass_kg",
    77: "hydration_kg",
    88: "bone_mass_kg",
}


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


def _post(url: str, data: dict) -> dict:
    resp = httpx.post(url, data=data, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != 0:
        raise RuntimeError(f"Withings API error: {payload}")
    return payload["body"]


def exchange_code(code: str, redirect_uri: str) -> dict:
    return _post(
        TOKEN_URL,
        {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": settings.withings_client_id,
            "client_secret": settings.withings_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )


def _refresh(refresh_token: str) -> dict:
    return _post(
        TOKEN_URL,
        {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": settings.withings_client_id,
            "client_secret": settings.withings_client_secret,
            "refresh_token": refresh_token,
        },
    )


def get_access_token() -> str:
    with SessionLocal() as s:
        row = s.get(OAuthToken, PROVIDER)
    if row is None:
        raise RuntimeError("Withings not authorized yet. Run `coach-withings-auth`.")

    if row.expires_at - 60 > int(time.time()):
        return row.access_token

    body = _refresh(row.refresh_token)
    expires_at = int(time.time()) + int(body["expires_in"])
    save_tokens(body["access_token"], body["refresh_token"], expires_at)
    return body["access_token"]


def fetch_measure_groups() -> list[dict]:
    token = get_access_token()
    body = _post(
        MEASURE_URL,
        {
            "action": "getmeas",
            "access_token": token,
            "meastypes": ",".join(str(t) for t in MEASTYPES),
            "category": 1,  # real measures (not user objectives)
        },
    )
    return body.get("measuregrps", [])


def upsert_group(session, grp: dict) -> None:
    row = session.get(BodyMeasurement, grp["grpid"])
    if row is None:
        row = BodyMeasurement(grpid=grp["grpid"])
        session.add(row)
    row.measured_at = datetime.fromtimestamp(grp["date"], tz=timezone.utc)
    for m in grp.get("measures", []):
        col = MEASTYPES.get(m["type"])
        if col:
            setattr(row, col, m["value"] * (10 ** m["unit"]))


def sync() -> int:
    groups = fetch_measure_groups()
    with SessionLocal() as s:
        for grp in groups:
            upsert_group(s, grp)
        s.commit()
    return len(groups)
