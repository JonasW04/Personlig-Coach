"""Strength-data read tools over the local DB, exposed as an in-process MCP server.

These never call the Hevy API directly (the sync job does that) so the agent is
fast and rate-limit-safe. Add Strava/Withings tool modules the same way later.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from claude_agent_sdk import create_sdk_mcp_server, tool
from sqlalchemy import func, select

from coach.db import SessionLocal
from coach.models import Exercise, SetEntry, Workout, BodyMeasurement


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


@tool(
    "recent_workouts",
    "List the user's most recent strength workouts with date, title and exercise count.",
    {"limit": int},
)
async def recent_workouts(args) -> dict:
    limit = int(args.get("limit") or 10)
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
    return _text(out)


@tool(
    "exercise_progression",
    "Per-session best working set for one exercise over time (for tracking progressive overload). "
    "Match is case-insensitive substring on exercise title, e.g. 'bench press'.",
    {"exercise": str, "weeks": int},
)
async def exercise_progression(args) -> dict:
    name = (args.get("exercise") or "").strip()
    weeks = int(args.get("weeks") or 26)
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

        bws = s.execute(
            select(BodyMeasurement.measured_at, BodyMeasurement.weight_kg)
            .where(BodyMeasurement.weight_kg.is_not(None))
        ).all()

    def get_closest_weight(target_dt: datetime) -> float:
        if not bws:
            return 0.0
        closest = min(bws, key=lambda x: abs((x[0] - target_dt).total_seconds()))
        return closest[1]

    # Best set per session by estimated 1RM (Epley).
    by_session: dict = {}
    for dt, weight, reps, title in rows:
        if reps is None:
            continue
            
        if weight is None or weight == 0.0:
            weight = get_closest_weight(dt)
            
        if weight is None or weight == 0.0:
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
    return _text(sorted(by_session.values(), key=lambda r: r["date"]))


@tool(
    "weekly_volume",
    "Total working-set count and tonnage (sum of weight*reps) per ISO week over the last N weeks.",
    {"weeks": int},
)
async def weekly_volume(args) -> dict:
    weeks = int(args.get("weeks") or 8)
    since = datetime.utcnow() - timedelta(weeks=weeks)
    with SessionLocal() as s:
        rows = s.execute(
            select(Workout.start_time, SetEntry.weight_kg, SetEntry.reps)
            .join(Exercise, Exercise.workout_id == Workout.id)
            .join(SetEntry, SetEntry.exercise_id == Exercise.id)
            .where(Workout.start_time >= since)
            .where(SetEntry.set_type != "warmup")
        ).all()

        bws = s.execute(
            select(BodyMeasurement.measured_at, BodyMeasurement.weight_kg)
            .where(BodyMeasurement.weight_kg.is_not(None))
        ).all()

    def get_closest_weight(target_dt: datetime) -> float:
        if not bws:
            return 0.0
        # If target_dt is naive, and measured_at is aware (or vice-versa), total_seconds() will crash.
        # But both should be timezone-aware according to models.py DateTime(timezone=True).
        closest = min(bws, key=lambda x: abs((x[0] - target_dt).total_seconds()))
        return closest[1]

    agg: dict = {}
    for dt, weight, reps in rows:
        if dt is None:
            continue
        iso = dt.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        bucket = agg.setdefault(key, {"week": key, "sets": 0, "tonnage_kg": 0.0})
        bucket["sets"] += 1
        
        if weight is None or weight == 0.0:
            weight = get_closest_weight(dt)

        if weight and reps:
            bucket["tonnage_kg"] += weight * reps
    return _text(sorted(agg.values(), key=lambda r: r["week"]))


hevy_server = create_sdk_mcp_server(
    name="hevy",
    version="0.1.0",
    tools=[recent_workouts, exercise_progression, weekly_volume],
)

HEVY_TOOL_NAMES = [
    "mcp__hevy__recent_workouts",
    "mcp__hevy__exercise_progression",
    "mcp__hevy__weekly_volume",
]
