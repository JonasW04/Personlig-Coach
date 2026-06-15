"""Body-composition read tools over the local DB (Withings), exposed as an MCP server."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from claude_agent_sdk import create_sdk_mcp_server, tool
from sqlalchemy import select

from coach.db import SessionLocal
from coach.models import BodyMeasurement


def _text(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, default=str)}]}


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


@tool(
    "latest_body_metrics",
    "Most recent weigh-in: weight and full body composition (fat %, fat/muscle/bone mass).",
    {},
)
async def latest_body_metrics(args) -> dict:
    with SessionLocal() as s:
        m = s.execute(
            select(BodyMeasurement).order_by(BodyMeasurement.measured_at.desc()).limit(1)
        ).scalars().first()
    if m is None:
        return _text({"error": "No body measurements yet. Run a sync after authorizing Withings."})
    return _text(_row(m))


@tool(
    "weight_trend",
    "Weight (and fat %) for each weigh-in over the last N days, oldest first, for trend analysis.",
    {"days": int},
)
async def weight_trend(args) -> dict:
    days = int(args.get("days") or 90)
    since = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(
            select(BodyMeasurement)
            .where(BodyMeasurement.measured_at >= since)
            .order_by(BodyMeasurement.measured_at.asc())
        ).scalars().all()
    out = [
        {
            "date": m.measured_at,
            "weight_kg": round(m.weight_kg, 2) if m.weight_kg is not None else None,
            "fat_ratio_pct": round(m.fat_ratio, 2) if m.fat_ratio is not None else None,
        }
        for m in rows
    ]
    return _text(out)


@tool(
    "body_comp_trend",
    "Full body-composition history over the last N days (weight, fat %, fat/muscle/bone mass), "
    "oldest first. Use to track lean-mass and fat changes during a bulk or cut.",
    {"days": int},
)
async def body_comp_trend(args) -> dict:
    days = int(args.get("days") or 90)
    since = datetime.utcnow() - timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(
            select(BodyMeasurement)
            .where(BodyMeasurement.measured_at >= since)
            .order_by(BodyMeasurement.measured_at.asc())
        ).scalars().all()
    return _text([_row(m) for m in rows])


withings_server = create_sdk_mcp_server(
    name="withings",
    version="0.1.0",
    tools=[latest_body_metrics, weight_trend, body_comp_trend],
)

WITHINGS_TOOL_NAMES = [
    "mcp__withings__latest_body_metrics",
    "mcp__withings__weight_trend",
    "mcp__withings__body_comp_trend",
]
