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
from coach.models import Activity, Exercise, Workout


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

    return {"days": [days[k] for k in sorted(days)]}
