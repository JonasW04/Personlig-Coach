"""Strength-data read tools over the local DB.

These never call the Hevy API directly (the sync job does that) so the agent is
fast and rate-limit-safe. Add Strava/Withings tool modules the same way later.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from coach.db import SessionLocal
from coach.models import Exercise, SetEntry, Workout
from coach.tools.specs import ToolSpec, object_schema


async def recent_workouts(args) -> dict:
    limit = min(int(args.get("limit") or 10), 30)
    with SessionLocal() as s:
        rows = s.execute(
            select(Workout).order_by(Workout.start_time.desc()).limit(limit)
        ).scalars().all()
        out = [
            {
                "id": w.id,
                "title": w.title,
                "date": w.start_time,
                "exercises": [e.title for e in w.exercises],
            }
            for w in rows
        ]
    return out


async def exercise_progression(args) -> dict:
    name = (args.get("exercise") or "").strip()
    weeks = min(int(args.get("weeks") or 26), 104)
    since = datetime.utcnow() - timedelta(weeks=weeks)
    with SessionLocal() as s:
        rows = s.execute(
            select(Workout.start_time, SetEntry.weight_kg, SetEntry.reps, Exercise.title)
            .join(Exercise, Exercise.workout_id == Workout.id)
            .join(SetEntry, SetEntry.exercise_id == Exercise.id)
            .where(func.lower(Exercise.title).like(f"%{name.lower()}%"))
            .where(Workout.start_time >= since)
            .where(SetEntry.set_type != "warmup")
            .order_by(Workout.start_time.asc())
        ).all()

    # Best set per session by estimated 1RM (Epley).
    by_session: dict = {}
    for dt, weight, reps, title in rows:
        if weight is None or reps is None:
            continue
        e1rm = round(weight * (1 + reps / 30), 1)
        key = dt.date().isoformat() if dt else "unknown"
        cur = by_session.get(key)
        if cur is None or e1rm > cur["est_1rm"]:
            by_session[key] = {
                "date": key,
                "exercise": title,
                "weight_kg": weight,
                "reps": reps,
                "est_1rm": e1rm,
            }
    # Keep the most recent 52 sessions so a long history can't flood context.
    points = sorted(by_session.values(), key=lambda r: r["date"])[-52:]
    return points


async def weekly_volume(args) -> dict:
    weeks = min(int(args.get("weeks") or 8), 104)
    since = datetime.utcnow() - timedelta(weeks=weeks)
    with SessionLocal() as s:
        rows = s.execute(
            select(Workout.start_time, SetEntry.weight_kg, SetEntry.reps)
            .join(Exercise, Exercise.workout_id == Workout.id)
            .join(SetEntry, SetEntry.exercise_id == Exercise.id)
            .where(Workout.start_time >= since)
            .where(SetEntry.set_type != "warmup")
        ).all()

    agg: dict = {}
    for dt, weight, reps in rows:
        if dt is None:
            continue
        iso = dt.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        bucket = agg.setdefault(key, {"week": key, "sets": 0, "tonnage_kg": 0.0})
        bucket["sets"] += 1
        if weight and reps:
            bucket["tonnage_kg"] += weight * reps
    return sorted(agg.values(), key=lambda r: r["week"])


HEVY_TOOLS = [
    ToolSpec(
        name="recent_workouts",
        description="List the user's most recent strength workouts with date, title and exercise count.",
        parameters=object_schema(
            {"limit": {"type": "integer", "minimum": 1, "maximum": 30}},
        ),
        handler=recent_workouts,
        step_label="Reading your strength data",
    ),
    ToolSpec(
        name="exercise_progression",
        description=(
            "Per-session best working set for one exercise over time, for tracking "
            "progressive overload. Match is case-insensitive substring on exercise "
            "title, e.g. 'bench press'."
        ),
        parameters=object_schema(
            {
                "exercise": {"type": "string"},
                "weeks": {"type": "integer", "minimum": 1, "maximum": 104},
            },
            required=["exercise"],
        ),
        handler=exercise_progression,
        step_label="Reading your strength data",
    ),
    ToolSpec(
        name="weekly_volume",
        description="Total working-set count and tonnage (sum of weight*reps) per ISO week over the last N weeks.",
        parameters=object_schema(
            {"weeks": {"type": "integer", "minimum": 1, "maximum": 104}},
        ),
        handler=weekly_volume,
        step_label="Reading your strength data",
    ),
]

HEVY_TOOL_NAMES = [tool.name for tool in HEVY_TOOLS]
