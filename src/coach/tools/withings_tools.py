"""Body-composition read tools over the local DB (Withings)."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from coach.db import SessionLocal
from coach.models import BodyMeasurement
from coach.tools.specs import ToolSpec, object_schema


def _weekly(rows, fields: list[str]) -> list[dict]:
    """Bin weigh-ins by ISO week and average each field, oldest first.

    Weigh-ins are noisy and can be daily, so a weekly mean is both better signal
    and a hard bound on how much lands in the model's context.
    """
    buckets: dict = {}
    for m in rows:
        if m.measured_at is None:
            continue
        iso = m.measured_at.isocalendar()
        key = f"{iso.year}-W{iso.week:02d}"
        b = buckets.setdefault(key, {f: [] for f in fields})
        for f in fields:
            v = getattr(m, f)
            if v is not None:
                b[f].append(v)
    out = []
    for key in sorted(buckets):
        agg: dict = {"week": key}
        for f in fields:
            vals = buckets[key][f]
            agg[f] = round(sum(vals) / len(vals), 2) if vals else None
        out.append(agg)
    return out


def _row(m: BodyMeasurement) -> dict:
    return {
        "date": m.measured_at,
        "weight_kg": round(m.weight_kg, 2) if m.weight_kg is not None else None,
        "fat_ratio_pct": round(m.fat_ratio, 2) if m.fat_ratio is not None else None,
        "fat_mass_kg": round(m.fat_mass_kg, 2) if m.fat_mass_kg is not None else None,
        "fat_free_mass_kg": round(m.fat_free_mass_kg, 2) if m.fat_free_mass_kg is not None else None,
        "muscle_mass_kg": round(m.muscle_mass_kg, 2) if m.muscle_mass_kg is not None else None,
        "bone_mass_kg": round(m.bone_mass_kg, 2) if m.bone_mass_kg is not None else None,
        "hydration_kg": round(m.hydration_kg, 2) if m.hydration_kg is not None else None,
    }


async def latest_body_metrics(args) -> dict:
    with SessionLocal() as s:
        m = s.execute(
            select(BodyMeasurement).order_by(BodyMeasurement.measured_at.desc()).limit(1)
        ).scalars().first()
    if m is None:
        return {"error": "No body measurements yet. Run a sync after authorizing Withings."}
    return _row(m)


async def weight_trend(args) -> dict:
    days = min(int(args.get("days") or 90), 730)
    since = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(
            select(BodyMeasurement)
            .where(BodyMeasurement.measured_at >= since)
            .order_by(BodyMeasurement.measured_at.asc())
        ).scalars().all()
    return _weekly(rows, ["weight_kg", "fat_ratio"])


async def body_comp_trend(args) -> dict:
    days = min(int(args.get("days") or 90), 730)
    since = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(
            select(BodyMeasurement)
            .where(BodyMeasurement.measured_at >= since)
            .order_by(BodyMeasurement.measured_at.asc())
        ).scalars().all()
    return _weekly(rows, ["weight_kg", "fat_ratio", "fat_mass_kg", "muscle_mass_kg", "bone_mass_kg"])


WITHINGS_TOOLS = [
    ToolSpec(
        name="latest_body_metrics",
        description="Most recent weigh-in: weight and full body composition (fat %, fat/muscle/bone mass).",
        parameters=object_schema(),
        handler=latest_body_metrics,
        step_label="Reading your body data",
    ),
    ToolSpec(
        name="weight_trend",
        description=(
            "Weekly-averaged weight and fat ratio over the last N days, oldest "
            "first. Weigh-ins are averaged per ISO week to smooth daily noise."
        ),
        parameters=object_schema(
            {"days": {"type": "integer", "minimum": 1, "maximum": 730}},
        ),
        handler=weight_trend,
        step_label="Reading your body data",
    ),
    ToolSpec(
        name="body_comp_trend",
        description=(
            "Weekly-averaged body composition over the last N days (weight_kg, "
            "fat_ratio %, fat_mass_kg, muscle_mass_kg, bone_mass_kg), oldest first. "
            "Use to track lean-mass and fat changes during a bulk or cut."
        ),
        parameters=object_schema(
            {"days": {"type": "integer", "minimum": 1, "maximum": 730}},
        ),
        handler=body_comp_trend,
        step_label="Reading your body data",
    ),
]

WITHINGS_TOOL_NAMES = [tool.name for tool in WITHINGS_TOOLS]
