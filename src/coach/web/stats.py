"""Per-day training activity for the dashboard.

Plain query functions (no agent/LLM) that feed the redesigned Stats page. The
endpoint returns one row per active day with per-exercise sets and per-day cardio;
all aggregation (sets, tonnage, hours, streaks, calendar colours, per-exercise
charts) is derived client-side in ``static/data.js``.
"""
from __future__ import annotations

from datetime import date as _date

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from coach.db import SessionLocal
from coach.models import Activity, BodyMeasurement, Exercise, GarminDaily, Workout


def _bounds(start: str | None, end: str | None) -> tuple[_date | None, _date | None]:
    return (
        _date.fromisoformat(start) if start else None,
        _date.fromisoformat(end) if end else None,
    )


def activity(start: str | None = None, end: str | None = None) -> dict:
    """Return ``{"days": [...]}`` — one entry per active day in the (optional) range.

    Each day: ``{date, strength|None, cardio|None}`` where strength is
    ``{minutes, exercises:[{name, sets:[{reps, weight}]}]}`` and cardio is
    ``{type, minutes, km}``. Rest days are omitted.
    """
    start_d, end_d = _bounds(start, end)
    days: dict[str, dict] = {}

    def _entry(d: _date) -> dict | None:
        if (start_d and d < start_d) or (end_d and d > end_d):
            return None
        key = d.isoformat()
        return days.setdefault(key, {"date": key, "strength": None, "cardio": None})

    with SessionLocal() as s:
        workouts = s.execute(
            select(Workout)
            .options(selectinload(Workout.exercises).selectinload(Exercise.sets))
            .order_by(Workout.start_time.asc())
        ).scalars().all()

        for w in workouts:
            if w.start_time is None:
                continue
            entry = _entry(w.start_time.date())
            if entry is None:
                continue
            exercises = []
            for ex in sorted(w.exercises, key=lambda e: e.order_index):
                sets = [
                    {"reps": st.reps, "weight": st.weight_kg or 0}
                    for st in sorted(ex.sets, key=lambda x: x.order_index)
                    if (st.set_type or "") != "warmup" and st.reps
                ]
                if sets:
                    exercises.append({"name": ex.title, "sets": sets})
            if not exercises:
                continue
            minutes = 0
            if w.start_time and w.end_time:
                minutes = round((w.end_time - w.start_time).total_seconds() / 60)
            cur = entry["strength"]
            if cur is None:
                entry["strength"] = {"minutes": minutes, "exercises": exercises}
            else:
                cur["minutes"] += minutes
                cur["exercises"].extend(exercises)

        activities = s.execute(
            select(Activity).order_by(Activity.start_time.asc())
        ).scalars().all()

        for a in activities:
            if a.start_time is None:
                continue
            entry = _entry(a.start_time.date())
            if entry is None:
                continue
            minutes = round((a.moving_time_s or 0) / 60)
            km = round((a.distance_m or 0) / 1000, 2)
            cur = entry["cardio"]
            if cur is None:
                entry["cardio"] = {"type": a.sport_type or "Cardio", "minutes": minutes, "km": km}
            else:
                cur["minutes"] += minutes
                cur["km"] = round(cur["km"] + km, 2)

        body_rows = s.execute(
            select(BodyMeasurement).order_by(BodyMeasurement.measured_at.asc())
        ).scalars().all()

    body = []
    for m in body_rows:
        if m.measured_at is None:
            continue
        measured_on = m.measured_at.date()
        if (start_d and measured_on < start_d) or (end_d and measured_on > end_d):
            continue
        body.append({
            "date": measured_on.isoformat(),
            "weight_kg": round(m.weight_kg, 2) if m.weight_kg is not None else None,
            "fat_ratio_pct": round(m.fat_ratio, 2) if m.fat_ratio is not None else None,
            "fat_mass_kg": round(m.fat_mass_kg, 2) if m.fat_mass_kg is not None else None,
            "fat_free_mass_kg": round(m.fat_free_mass_kg, 2)
            if m.fat_free_mass_kg is not None else None,
            "muscle_mass_kg": round(m.muscle_mass_kg, 2)
            if m.muscle_mass_kg is not None else None,
        })

    return {"days": [days[k] for k in sorted(days)], "body": body}


def _round(value, ndigits=1):
    return round(value, ndigits) if value is not None else None


def _health_day(m: GarminDaily) -> dict:
    return {
        "date": m.day.isoformat(),
        "training_readiness": m.training_readiness_score,
        "training_readiness_level": m.training_readiness_level,
        "training_readiness_feedback": m.training_readiness_feedback,
        "training_status": m.training_status,
        "acute_load": _round(m.acute_load),
        "vo2max": _round(m.vo2max),
        "sleep_hours": _round(m.sleep_seconds / 3600) if m.sleep_seconds else None,
        "sleep_score": _round(m.sleep_score, 0),
        "deep_sleep_hours": _round(m.deep_sleep_seconds / 3600) if m.deep_sleep_seconds else None,
        "rem_sleep_hours": _round(m.rem_sleep_seconds / 3600) if m.rem_sleep_seconds else None,
        "light_sleep_hours": _round(m.light_sleep_seconds / 3600) if m.light_sleep_seconds else None,
        "hrv": _round(m.hrv_last_night_avg),
        "hrv_status": m.hrv_status,
        "hrv_baseline_low": _round(m.hrv_baseline_low),
        "hrv_baseline_high": _round(m.hrv_baseline_high),
        "body_battery_high": m.body_battery_high,
        "body_battery_low": m.body_battery_low,
        "avg_stress": _round(m.avg_stress, 0),
        "resting_hr": m.resting_hr,
        "steps": m.steps,
        "intensity_moderate": m.intensity_minutes_moderate,
        "intensity_vigorous": m.intensity_minutes_vigorous,
    }


def health(start: str | None = None, end: str | None = None) -> dict:
    """Return ``{"days": [...]}`` of Garmin recovery data, oldest first.

    One entry per synced day, ordered for trend charts; the latest entry doubles
    as the dashboard's current-state snapshot.
    """
    start_d, end_d = _bounds(start, end)
    with SessionLocal() as s:
        q = select(GarminDaily).order_by(GarminDaily.day.asc())
        if start_d:
            q = q.where(GarminDaily.day >= start_d)
        if end_d:
            q = q.where(GarminDaily.day <= end_d)
        rows = s.execute(q).scalars().all()
    return {"days": [_health_day(m) for m in rows]}
