"""Combined health/fitness statistics from the local DB.

Plain query functions (no agent/LLM) that power the dashboard: strength volume,
cardio load and body composition, plus a few headline summary cards. All timestamps
are returned as ISO strings via the caller's JSON encoder.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from coach.db import SessionLocal
from coach.models import Activity, BodyMeasurement, Exercise, SetEntry, Workout


def _iso_week(dt: datetime) -> str:
    c = dt.isocalendar()
    return f"{c.year}-W{c.week:02d}"


def _strength_weekly(weeks: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    with SessionLocal() as s:
        rows = s.execute(
            select(Workout.start_time, SetEntry.weight_kg, SetEntry.reps)
            .join(Exercise, Exercise.workout_id == Workout.id)
            .join(SetEntry, SetEntry.exercise_id == Exercise.id)
            .where(Workout.start_time >= since)
            .where(SetEntry.set_type != "warmup")
        ).all()
    agg: dict[str, dict] = {}
    for dt, weight, reps in rows:
        if dt is None:
            continue
        b = agg.setdefault(_iso_week(dt), {"week": _iso_week(dt), "sets": 0, "tonnage_kg": 0.0})
        b["sets"] += 1
        if weight and reps:
            b["tonnage_kg"] += weight * reps
    for b in agg.values():
        b["tonnage_kg"] = round(b["tonnage_kg"])
    return sorted(agg.values(), key=lambda r: r["week"])


def _cardio_weekly(weeks: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(weeks=weeks)
    with SessionLocal() as s:
        rows = s.execute(
            select(Activity).where(Activity.start_time >= since)
        ).scalars().all()
    agg: dict[str, dict] = {}
    for a in rows:
        if a.start_time is None:
            continue
        k = _iso_week(a.start_time)
        b = agg.setdefault(
            k, {"week": k, "sessions": 0, "distance_km": 0.0, "minutes": 0.0, "relative_effort": 0.0}
        )
        b["sessions"] += 1
        b["distance_km"] += (a.distance_m or 0) / 1000
        b["minutes"] += (a.moving_time_s or 0) / 60
        b["relative_effort"] += a.suffer_score or 0
    for b in agg.values():
        b["distance_km"] = round(b["distance_km"], 1)
        b["minutes"] = round(b["minutes"])
        b["relative_effort"] = round(b["relative_effort"])
    return sorted(agg.values(), key=lambda r: r["week"])


def _body_series(days: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(
            select(BodyMeasurement)
            .where(BodyMeasurement.measured_at >= since)
            .order_by(BodyMeasurement.measured_at.asc())
        ).scalars().all()
    return [
        {
            "date": m.measured_at.date().isoformat() if m.measured_at else None,
            "weight_kg": round(m.weight_kg, 2) if m.weight_kg is not None else None,
            "fat_ratio_pct": round(m.fat_ratio, 2) if m.fat_ratio is not None else None,
            "muscle_mass_kg": round(m.muscle_mass_kg, 2) if m.muscle_mass_kg is not None else None,
            "fat_mass_kg": round(m.fat_mass_kg, 2) if m.fat_mass_kg is not None else None,
        }
        for m in rows
    ]


def _summary() -> dict:
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    with SessionLocal() as s:
        latest_body = s.execute(
            select(BodyMeasurement).order_by(BodyMeasurement.measured_at.desc()).limit(1)
        ).scalars().first()

        lift_days = s.execute(
            select(Workout.start_time).where(Workout.start_time >= week_ago)
        ).scalars().all()

        tonnage_rows = s.execute(
            select(SetEntry.weight_kg, SetEntry.reps)
            .join(Exercise, Exercise.id == SetEntry.exercise_id)
            .join(Workout, Workout.id == Exercise.workout_id)
            .where(Workout.start_time >= week_ago)
            .where(SetEntry.set_type != "warmup")
        ).all()

        cardio = s.execute(
            select(Activity).where(Activity.start_time >= week_ago)
        ).scalars().all()

    tonnage = round(sum((w or 0) * (r or 0) for w, r in tonnage_rows))
    cardio_km = round(sum((a.distance_m or 0) / 1000 for a in cardio), 1)
    train_days = len({d.date() for d in lift_days if d} | {a.start_time.date() for a in cardio if a.start_time})

    return {
        "latest_weight_kg": round(latest_body.weight_kg, 1)
        if latest_body and latest_body.weight_kg is not None
        else None,
        "latest_fat_pct": round(latest_body.fat_ratio, 1)
        if latest_body and latest_body.fat_ratio is not None
        else None,
        "latest_weigh_in": latest_body.measured_at.date().isoformat()
        if latest_body and latest_body.measured_at
        else None,
        "lift_sessions_7d": len(lift_days),
        "tonnage_7d_kg": tonnage,
        "cardio_km_7d": cardio_km,
        "training_days_7d": train_days,
    }


def dashboard(weeks: int = 12) -> dict:
    return {
        "summary": _summary(),
        "strength_weekly": _strength_weekly(weeks),
        "cardio_weekly": _cardio_weekly(weeks),
        "body": _body_series(weeks * 7),
    }
