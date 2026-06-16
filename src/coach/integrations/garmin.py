"""Garmin Connect client + health-data sync into Postgres.

Garmin has **no official API**. We use the community `garminconnect` library
(which wraps Garmin's mobile SSO via garth). To keep this robust and avoid
account lockouts on the unofficial endpoints, the design is deliberately gentle:

- **Log in once, reuse the session.** `coach-garmin-auth` does a full
  username/password (+ MFA) login a single time, then dumps the garth session
  token to the DB (provider ``garmin`` in ``oauth_tokens``). Every sync restores
  that token instead of re-authenticating, so we never hammer the SSO endpoint
  (the thing most likely to rate-limit or trigger a lockout). The library
  auto-refreshes the short-lived OAuth2 token from the long-lived OAuth1 token,
  and we persist the refreshed blob back after each sync.
- **Sync a small, fixed window** (last ~10 days) on a slow cadence (nightly),
  with a short pause between days, rather than back-filling everything.
- **Fail soft per metric.** A missing day or a single endpoint hiccup returns
  empty data for that field instead of aborting the whole sync.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)

from coach.config import settings
from coach.db import SessionLocal
from coach.models import GarminDaily, OAuthToken

log = logging.getLogger("coach.integrations.garmin")

PROVIDER = "garmin"
DEFAULT_SYNC_DAYS = 10
# Be a polite client of an unofficial API: small gap between per-day fetches.
_REQUEST_PAUSE_S = 0.4


# --------------------------------------------------------------------------- tokens
def save_token(blob: str) -> None:
    """Persist the garth session token blob (provider 'garmin').

    Reuses the OAuthToken table: the whole serialized session lives in
    ``access_token``; the other columns are unused for Garmin.
    """
    with SessionLocal() as s:
        row = s.get(OAuthToken, PROVIDER)
        if row is None:
            row = OAuthToken(provider=PROVIDER, refresh_token="", expires_at=0)
            s.add(row)
        row.access_token = blob
        row.refresh_token = ""
        row.expires_at = 0
        s.commit()


def load_token() -> str | None:
    with SessionLocal() as s:
        row = s.get(OAuthToken, PROVIDER)
        return row.access_token if row else None


def is_authorized() -> bool:
    return bool(load_token())


def login_with_credentials(
    email: str, password: str, prompt_mfa: Callable[[], str] | None = None
) -> str:
    """Full credential login (one-time). Returns the session token blob to store.

    ``prompt_mfa`` is called to obtain a 2FA code if the account requires it.
    """
    client = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
    client.login()
    return client.garth.dumps() if hasattr(client, "garth") else client.client.dumps()


def _client_from_token() -> Garmin:
    """Build a logged-in client from the stored session token (no SSO login)."""
    blob = load_token()
    if not blob:
        raise GarminConnectAuthenticationError(
            "Garmin not authorized yet. Run `coach-garmin-auth`."
        )
    client = Garmin()
    # A blob >512 chars is treated as token data (not a path) by .login().
    client.login(tokenstore=blob)
    return client


def _dump_token(client: Garmin) -> str:
    return client.garth.dumps() if hasattr(client, "garth") else client.client.dumps()


# ------------------------------------------------------------------------- fetching
def _safe(fn: Callable[..., Any], *args: Any) -> Any:
    """Call a garminconnect getter, swallowing per-metric failures.

    A day with no data (or a transient endpoint error) shouldn't abort the sync.
    Rate-limit errors are re-raised so the caller can back off.
    """
    try:
        return fn(*args)
    except GarminConnectTooManyRequestsError:
        raise
    except Exception as exc:  # noqa: BLE001 - one missing metric is non-fatal
        log.debug("garmin getter %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    n = _num(value)
    return int(round(n)) if n is not None else None


def fetch_day(client: Garmin, day: date) -> dict[str, Any]:
    """Fetch and normalize one day of health data into a flat dict + raw payload."""
    cdate = day.isoformat()
    sleep = _safe(client.get_sleep_data, cdate) or {}
    hrv = _safe(client.get_hrv_data, cdate) or {}
    readiness = _safe(client.get_training_readiness, cdate) or []
    status = _safe(client.get_training_status, cdate) or {}
    max_metrics = _safe(client.get_max_metrics, cdate) or []
    summary = _safe(client.get_user_summary, cdate) or {}
    stress = _safe(client.get_all_day_stress, cdate) or {}
    respiration = _safe(client.get_respiration_data, cdate) or {}
    spo2 = _safe(client.get_spo2_data, cdate) or {}
    fitnessage = _safe(client.get_fitnessage_data, cdate) or {}

    raw = {
        "sleep": sleep,
        "hrv": hrv,
        "training_readiness": readiness,
        "training_status": status,
        "max_metrics": max_metrics,
        "user_summary": summary,
        "stress": stress,
        "respiration": respiration,
        "spo2": spo2,
        "fitnessage": fitnessage,
    }

    out: dict[str, Any] = {"day": day}

    # ---- sleep
    dto = (sleep or {}).get("dailySleepDTO") or {}
    out["sleep_seconds"] = _int(dto.get("sleepTimeSeconds"))
    out["deep_sleep_seconds"] = _int(dto.get("deepSleepSeconds"))
    out["light_sleep_seconds"] = _int(dto.get("lightSleepSeconds"))
    out["rem_sleep_seconds"] = _int(dto.get("remSleepSeconds"))
    out["awake_seconds"] = _int(dto.get("awakeSleepSeconds"))
    scores = (dto.get("sleepScores") or {}).get("overall") or {}
    out["sleep_score"] = _num(scores.get("value"))
    out["avg_spo2"] = _num((sleep or {}).get("avgOvernightSpO2") or dto.get("averageSpO2Value"))
    out["avg_respiration"] = _num(
        (sleep or {}).get("avgOvernightRespiration") or dto.get("averageRespirationValue")
    )

    # ---- hrv
    hrv_summary = (hrv or {}).get("hrvSummary") or {}
    out["hrv_last_night_avg"] = _num(hrv_summary.get("lastNightAvg"))
    out["hrv_weekly_avg"] = _num(hrv_summary.get("weeklyAvg"))
    out["hrv_status"] = hrv_summary.get("status")
    baseline = hrv_summary.get("baseline") or {}
    out["hrv_baseline_low"] = _num(baseline.get("lowUpper") or baseline.get("balancedLow"))
    out["hrv_baseline_high"] = _num(baseline.get("balancedUpper") or baseline.get("markerValue"))

    # ---- training readiness (list, take the most recent entry)
    tr = readiness[0] if isinstance(readiness, list) and readiness else {}
    out["training_readiness_score"] = _int(tr.get("score"))
    out["training_readiness_level"] = tr.get("level")
    out["training_readiness_feedback"] = tr.get("feedbackShort") or tr.get("feedbackLong")

    # ---- training status + acute/chronic load + ACWR
    out["training_status"] = None
    out["acute_load"] = None
    out["chronic_load"] = None
    out["acwr"] = None
    out["acwr_status"] = None
    latest = (status or {}).get("mostRecentTrainingStatus") or {}
    map_ = latest.get("latestTrainingStatusData") or {}
    if isinstance(map_, dict) and map_:
        first = next(iter(map_.values()), {}) or {}
        # Garmin's localized feedback phrase ("PRODUCTIVE_2") is the real status;
        # the numeric code is a fallback when the phrase is missing.
        out["training_status"] = _clean_status_phrase(
            first.get("trainingStatusFeedbackPhrase")
        ) or _status_word(first.get("trainingStatus"))
        load = first.get("acuteTrainingLoadDTO") or {}
        out["acute_load"] = _num(load.get("dailyTrainingLoadAcute"))
        out["chronic_load"] = _num(load.get("dailyTrainingLoadChronic"))
        out["acwr"] = _num(load.get("dailyAcuteChronicWorkloadRatio"))
        out["acwr_status"] = load.get("acwrStatus")

    # ---- vo2max (FR255 reports it under training status, not max_metrics)
    out["vo2max"] = None
    out["vo2max_cycling"] = None
    vo2 = (status or {}).get("mostRecentVO2Max") or {}
    generic = vo2.get("generic") or {}
    cycling = vo2.get("cycling") or {}
    out["vo2max"] = _num(generic.get("vo2MaxValue") or generic.get("vo2MaxPreciseValue"))
    out["vo2max_cycling"] = _num(cycling.get("vo2MaxValue"))
    # Fallback to max_metrics for watches that populate it.
    if out["vo2max"] is None:
        mm = max_metrics[0] if isinstance(max_metrics, list) and max_metrics else {}
        out["vo2max"] = _num(((mm or {}).get("generic") or {}).get("vo2MaxValue"))

    # ---- daily activity / cardio (user summary is the richest aggregate)
    out["resting_hr"] = _int(
        summary.get("restingHeartRate") or dto.get("restingHeartRate")
    )
    out["steps"] = _int(summary.get("totalSteps"))
    out["calories_total"] = _int(summary.get("totalKilocalories"))
    out["calories_active"] = _int(summary.get("activeKilocalories"))
    out["intensity_minutes_moderate"] = _int(summary.get("moderateIntensityMinutes"))
    out["intensity_minutes_vigorous"] = _int(summary.get("vigorousIntensityMinutes"))

    # ---- body battery (from summary) + stress
    out["body_battery_high"] = _int(summary.get("bodyBatteryHighestValue"))
    out["body_battery_low"] = _int(summary.get("bodyBatteryLowestValue"))
    out["body_battery_charged"] = _int(summary.get("bodyBatteryChargedValue"))
    out["body_battery_drained"] = _int(summary.get("bodyBatteryDrainedValue"))
    out["avg_stress"] = _num(summary.get("averageStressLevel") or stress.get("avgStressLevel"))
    out["max_stress"] = _num(summary.get("maxStressLevel") or stress.get("maxStressLevel"))

    # ---- 7-day resting HR baseline (smoother trend than the single-day value)
    out["resting_hr_7d_avg"] = _int(summary.get("lastSevenDaysAvgRestingHeartRate"))

    # ---- overnight respiration (breaths/min)
    out["avg_sleep_respiration"] = _num(
        respiration.get("avgSleepRespirationValue")
        or dto.get("averageRespirationValue")
        or summary.get("avgWakingRespirationValue")
    )

    # ---- overnight blood oxygen (%)
    out["avg_sleep_spo2"] = _num(
        spo2.get("avgSleepSpO2")
        or spo2.get("averageSpO2")
        or summary.get("averageSpo2")
    )

    # ---- fitness age
    out["fitness_age"] = _num(fitnessage.get("fitnessAge"))

    out["raw_json"] = json.dumps(raw, default=str)
    return out


def _status_word(code: Any) -> str | None:
    mapping = {
        0: "No status",
        1: "Detraining",
        2: "Unproductive",
        3: "Maintaining",
        4: "Productive",
        5: "Peaking",
        6: "Overreaching",
        7: "Recovery",
    }
    try:
        return mapping.get(int(code))
    except (TypeError, ValueError):
        return None


def _clean_status_phrase(phrase: Any) -> str | None:
    """Turn a Garmin feedback key like 'PRODUCTIVE_2' into a readable 'Productive'."""
    if not isinstance(phrase, str) or not phrase:
        return None
    words = [w for w in phrase.split("_") if not w.isdigit()]
    cleaned = " ".join(w.capitalize() for w in words)
    return cleaned or None


def _has_signal(row: dict[str, Any]) -> bool:
    """True if the day carries at least one real metric (skip empty days)."""
    keys = (
        "sleep_seconds",
        "hrv_last_night_avg",
        "training_readiness_score",
        "resting_hr",
        "steps",
        "body_battery_high",
    )
    return any(row.get(k) is not None for k in keys)


# --------------------------------------------------------------------------- upsert
def upsert_day(session, row: dict[str, Any]) -> None:
    existing = session.get(GarminDaily, row["day"])
    if existing is None:
        existing = GarminDaily(day=row["day"])
        session.add(existing)
    for key, value in row.items():
        if key == "day":
            continue
        setattr(existing, key, value)


def sync(days: int = DEFAULT_SYNC_DAYS) -> int:
    """Pull the last ``days`` of Garmin health data into the DB. Returns days stored.

    Restores the stored session token (no SSO login), fetches a small recent
    window day-by-day, and persists the possibly-refreshed token back afterwards.
    """
    client = _client_from_token()
    today = datetime.now(timezone.utc).date()
    stored = 0
    with SessionLocal() as s:
        for offset in range(days):
            day = today - timedelta(days=offset)
            row = fetch_day(client, day)
            if _has_signal(row):
                upsert_day(s, row)
                stored += 1
            time.sleep(_REQUEST_PAUSE_S)
        s.commit()

    # Persist the (possibly auto-refreshed) token so the next run stays logged in.
    try:
        save_token(_dump_token(client))
    except Exception:  # noqa: BLE001 - refresh persistence is best-effort
        log.debug("could not persist refreshed garmin token", exc_info=True)

    return stored
