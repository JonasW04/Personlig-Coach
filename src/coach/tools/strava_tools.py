"""Cardio read tools over the local DB (Strava activities)."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from coach.db import SessionLocal
from coach.models import Activity
from coach.tools.specs import ToolSpec, object_schema


def _pace_min_per_km(distance_m, moving_s):
    if not distance_m or not moving_s:
        return None
    km = distance_m / 1000
    if km == 0:
        return None
    sec_per_km = moving_s / km
    return round(sec_per_km / 60, 2)


async def recent_activities(args) -> dict:
    limit = min(int(args.get("limit") or 10), 30)
    with SessionLocal() as s:
        rows = s.execute(
            select(Activity).order_by(Activity.start_time.desc()).limit(limit)
        ).scalars().all()
        out = [
            {
                "id": a.id,
                "name": a.name,
                "sport": a.sport_type,
                "date": a.start_time,
                "distance_km": round((a.distance_m or 0) / 1000, 2),
                "duration_min": round((a.moving_time_s or 0) / 60, 1),
                "avg_hr": a.average_hr,
                "pace_min_per_km": _pace_min_per_km(a.distance_m, a.moving_time_s),
                "elevation_gain_m": a.elevation_gain_m,
            }
            for a in rows
        ]
    return out


async def weekly_cardio_summary(args) -> dict:
    weeks = min(int(args.get("weeks") or 8), 104)
    since = datetime.utcnow() - timedelta(weeks=weeks)
    with SessionLocal() as s:
        rows = s.execute(
            select(Activity).where(Activity.start_time >= since)
        ).scalars().all()

    agg: dict = {}
    for a in rows:
        if a.start_time is None:
            continue
        iso = a.start_time.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        b = agg.setdefault(
            key, {"week": key, "sessions": 0, "distance_km": 0.0, "minutes": 0.0, "relative_effort": 0.0}
        )
        b["sessions"] += 1
        b["distance_km"] += round((a.distance_m or 0) / 1000, 2)
        b["minutes"] += round((a.moving_time_s or 0) / 60, 1)
        b["relative_effort"] += a.suffer_score or 0
    return sorted(agg.values(), key=lambda r: r["week"])


STRAVA_TOOLS = [
    ToolSpec(
        name="recent_activities",
        description="List recent cardio activities with sport, date, distance (km), duration and avg HR.",
        parameters=object_schema(
            {"limit": {"type": "integer", "minimum": 1, "maximum": 30}},
        ),
        handler=recent_activities,
        step_label="Reading your cardio data",
    ),
    ToolSpec(
        name="weekly_cardio_summary",
        description=(
            "Per ISO week over the last N weeks: number of sessions, total distance "
            "(km), total moving time (min), and total relative effort (suffer score)."
        ),
        parameters=object_schema(
            {"weeks": {"type": "integer", "minimum": 1, "maximum": 104}},
        ),
        handler=weekly_cardio_summary,
        step_label="Reading your cardio data",
    ),
]

STRAVA_TOOL_NAMES = [tool.name for tool in STRAVA_TOOLS]
