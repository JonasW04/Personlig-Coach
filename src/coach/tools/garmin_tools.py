"""Garmin health/recovery read tools over the local DB.

These let the coach reason about recovery and readiness: sleep, HRV, Body
Battery, stress, Garmin's own training-readiness score, training status/load and
VO2max. The dashboard shows a curated subset; these tools expose the full set
(and a raw-payload escape hatch) so the coach can ground advice in more than
what's on screen.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select

from coach.db import SessionLocal
from coach.models import GarminDaily
from coach.tools.specs import ToolSpec, object_schema


def _round(value, ndigits=1):
    return round(value, ndigits) if value is not None else None


def _hm(seconds) -> str | None:
    if seconds is None:
        return None
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h}h{m:02d}m"


def _snapshot(m: GarminDaily) -> dict:
    return {
        "date": m.day.isoformat(),
        "training_readiness": m.training_readiness_score,
        "training_readiness_level": m.training_readiness_level,
        "training_readiness_feedback": m.training_readiness_feedback,
        "training_status": m.training_status,
        "acute_load": _round(m.acute_load),
        "chronic_load": _round(m.chronic_load),
        "acwr": _round(m.acwr, 2),
        "acwr_status": m.acwr_status,
        "vo2max": _round(m.vo2max),
        "vo2max_cycling": _round(m.vo2max_cycling),
        "fitness_age": _round(m.fitness_age, 0),
        "sleep": _hm(m.sleep_seconds),
        "sleep_score": _round(m.sleep_score, 0),
        "deep_sleep": _hm(m.deep_sleep_seconds),
        "rem_sleep": _hm(m.rem_sleep_seconds),
        "light_sleep": _hm(m.light_sleep_seconds),
        "awake": _hm(m.awake_seconds),
        "avg_spo2": _round(m.avg_spo2),
        "avg_respiration": _round(m.avg_respiration),
        "hrv_last_night": _round(m.hrv_last_night_avg),
        "hrv_weekly_avg": _round(m.hrv_weekly_avg),
        "hrv_status": m.hrv_status,
        "hrv_baseline": [
            _round(m.hrv_baseline_low),
            _round(m.hrv_baseline_high),
        ]
        if (m.hrv_baseline_low or m.hrv_baseline_high)
        else None,
        "body_battery_high": m.body_battery_high,
        "body_battery_low": m.body_battery_low,
        "body_battery_charged": m.body_battery_charged,
        "body_battery_drained": m.body_battery_drained,
        "avg_stress": _round(m.avg_stress, 0),
        "max_stress": _round(m.max_stress, 0),
        "resting_hr": m.resting_hr,
        "resting_hr_7d_avg": m.resting_hr_7d_avg,
        "avg_sleep_respiration": _round(m.avg_sleep_respiration, 0),
        "avg_sleep_spo2": _round(m.avg_sleep_spo2, 0),
        "steps": m.steps,
        "calories_total": m.calories_total,
        "calories_active": m.calories_active,
        "intensity_minutes": {
            "moderate": m.intensity_minutes_moderate,
            "vigorous": m.intensity_minutes_vigorous,
        },
    }


def _trend_row(m: GarminDaily) -> dict:
    return {
        "date": m.day.isoformat(),
        "training_readiness": m.training_readiness_score,
        "sleep_hours": _round(m.sleep_seconds / 3600) if m.sleep_seconds else None,
        "sleep_score": _round(m.sleep_score, 0),
        "hrv": _round(m.hrv_last_night_avg),
        "hrv_status": m.hrv_status,
        "body_battery_high": m.body_battery_high,
        "body_battery_low": m.body_battery_low,
        "avg_stress": _round(m.avg_stress, 0),
        "resting_hr": m.resting_hr,
        "acute_load": _round(m.acute_load),
        "chronic_load": _round(m.chronic_load),
        "acwr": _round(m.acwr, 2),
        "vo2max": _round(m.vo2max),
        "training_status": m.training_status,
    }


async def latest_health(args) -> dict:
    with SessionLocal() as s:
        m = s.execute(
            select(GarminDaily).order_by(GarminDaily.day.desc()).limit(1)
        ).scalars().first()
    if m is None:
        return {"error": "No Garmin data yet. Authorize with `coach-garmin-auth` and sync."}
    return _snapshot(m)


async def health_trend(args) -> dict:
    days = min(int(args.get("days") or 14), 120)
    since = date.today() - timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(
            select(GarminDaily)
            .where(GarminDaily.day >= since)
            .order_by(GarminDaily.day.asc())
        ).scalars().all()
    if not rows:
        return {"error": "No Garmin data in range. Authorize and sync first."}
    return {"days": [_trend_row(m) for m in rows]}


async def health_raw(args) -> dict:
    """Full untouched Garmin payload for a single day — use only when the curated
    fields aren't enough (digging into sleep stages timelines, stress arrays, etc.)."""
    day_str = args.get("date")
    with SessionLocal() as s:
        if day_str:
            m = s.get(GarminDaily, date.fromisoformat(day_str))
        else:
            m = s.execute(
                select(GarminDaily).order_by(GarminDaily.day.desc()).limit(1)
            ).scalars().first()
    if m is None or not m.raw_json:
        return {"error": "No raw Garmin data for that day."}
    try:
        return {"date": m.day.isoformat(), "raw": json.loads(m.raw_json)}
    except json.JSONDecodeError:
        return {"error": "Stored raw payload is unreadable."}


GARMIN_TOOLS = [
    ToolSpec(
        name="latest_health",
        description=(
            "Most recent day of Garmin recovery data: training-readiness score, "
            "training status & acute load, sleep (duration, stages, score), HRV "
            "(value, status, baseline), Body Battery, stress, resting HR, VO2max, "
            "steps and intensity minutes. Use for 'how recovered am I / what should "
            "I do today' questions."
        ),
        parameters=object_schema(),
        handler=latest_health,
        step_label="Checking your recovery data",
    ),
    ToolSpec(
        name="health_trend",
        description=(
            "Daily Garmin recovery metrics over the last N days (readiness, sleep "
            "hours & score, HRV + status, Body Battery, stress, resting HR, acute "
            "load, training status), oldest first. Use to spot recovery trends, "
            "accumulating fatigue, or whether load is trending up."
        ),
        parameters=object_schema(
            {"days": {"type": "integer", "minimum": 1, "maximum": 120}},
        ),
        handler=health_trend,
        step_label="Checking your recovery data",
    ),
    ToolSpec(
        name="health_raw",
        description=(
            "Full raw Garmin payload for one day (defaults to latest). Only needed "
            "for detail the other tools don't expose. Optional `date` (YYYY-MM-DD)."
        ),
        parameters=object_schema(
            {"date": {"type": "string", "description": "YYYY-MM-DD"}},
        ),
        handler=health_raw,
        step_label="Checking your recovery data",
    ),
]

GARMIN_TOOL_NAMES = [tool.name for tool in GARMIN_TOOLS]
