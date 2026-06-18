"""Generate, validate, and persist weekly training plans."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from coach import body_mode, focus, rules
from coach.agents.gemini import run_once
from coach.config import settings
from coach.db import SessionLocal
from coach.models import PlanDay, RecoveryRule, TrainingBlock
from coach.web import stats

log = logging.getLogger("coach.plan")


class PlanGenerationError(ValueError):
    pass


class GeneratedSet(BaseModel):
    set: str = Field(min_length=1, max_length=20)
    type: Literal["warmup", "normal", "failure", "dropset"] = "normal"
    weight_kg: float | None = Field(default=None, ge=0)
    reps: int | None = Field(default=None, ge=1, le=1000)
    rpe: float | None = Field(default=None, ge=6, le=10)

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type(cls, value):
        # The model sometimes returns null or a synonym; fall back to a normal set.
        return value if value in {"warmup", "normal", "failure", "dropset"} else "normal"


class GeneratedProgression(BaseModel):
    kind: Literal["up", "hold"]
    text: str = Field(min_length=1, max_length=300)

    @field_validator("kind", mode="before")
    @classmethod
    def _coerce_kind(cls, value):
        return value if value in {"up", "hold"} else "hold"


class GeneratedExercise(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scheme: str = Field(min_length=1, max_length=100)
    expanded: bool = False
    sets: list[GeneratedSet]
    rest_seconds: int | None = Field(default=None, ge=0, le=900)
    notes: str = Field(default="", max_length=1000)
    progression: GeneratedProgression | None = None
    alternatives: str = Field(default="", max_length=500)


class GeneratedTarget(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=100)


class GeneratedDay(BaseModel):
    date: date
    kind: Literal["strength", "cardio", "rest"]
    title: str = Field(min_length=1, max_length=200)
    exercises: list[GeneratedExercise] = Field(default_factory=list)
    duration_minutes: int | None = Field(default=None, ge=1, le=300)
    distance_km: float | None = Field(default=None, ge=0, le=500)
    zone: str | None = Field(default=None, max_length=100)
    cardio_type: Literal["running", "cycling", "walking", "cardio"] = "cardio"
    notes: str = Field(default="", max_length=2000)
    targets: list[GeneratedTarget] = Field(default_factory=list)

    @field_validator("cardio_type", mode="before")
    @classmethod
    def _coerce_cardio_type(cls, value):
        # Irrelevant on strength/rest days: the model often sends null or echoes
        # the "running|cycling|walking|cardio" placeholder. Normalise to "cardio".
        return value if value in {"running", "cycling", "walking", "cardio"} else "cardio"


class GeneratedWeek(BaseModel):
    days: list[GeneratedDay]


def week_start_for(day: date | None = None) -> date:
    day = day or date.today()
    return day - timedelta(days=day.weekday())


def _extract_week(raw: str, week_start: date) -> GeneratedWeek:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        log.warning(
            "plan generation returned no JSON object (%d chars): %r",
            len(raw),
            raw[:500],
        )
        if not raw.strip():
            raise PlanGenerationError(
                "Coach returned an empty response — it likely ran out of token "
                "budget while reasoning. Try again."
            )
        raise PlanGenerationError("Coach did not return a JSON plan")
    try:
        week = GeneratedWeek.model_validate_json(raw[start : end + 1])
    except (ValidationError, ValueError) as exc:
        log.warning(
            "plan generation failed validation: %s | json: %r",
            exc,
            raw[start : end + 1][:1000],
        )
        raise PlanGenerationError("Coach returned an invalid plan") from exc

    expected = {week_start + timedelta(days=offset) for offset in range(7)}
    actual = [item.date for item in week.days]
    if len(actual) != 7 or len(set(actual)) != 7 or set(actual) != expected:
        raise PlanGenerationError("Plan must contain each day of the requested week exactly once")
    for item in week.days:
        item.title = item.title.strip()
        if item.kind == "strength" and not item.exercises:
            raise PlanGenerationError("Strength sessions require at least one exercise")
        for exercise in item.exercises:
            exercise.name = exercise.name.strip()
            exercise.scheme = exercise.scheme.strip()
            if not exercise.sets:
                raise PlanGenerationError("Strength exercises require at least one set")
    return week


def _payload(item: GeneratedDay) -> dict:
    payload = item.model_dump(
        mode="json",
        exclude={"date", "kind", "title"},
        exclude_none=True,
    )
    if item.kind != "cardio":
        payload.pop("cardio_type", None)
    return payload


def _persist(
    week: GeneratedWeek, replace_from: date, block_id: int | None = None
) -> list[PlanDay]:
    week_end = max(item.date for item in week.days)
    rows = [item for item in week.days if item.date >= replace_from]
    with SessionLocal() as session:
        existing = session.execute(
            select(PlanDay).where(
                PlanDay.date >= replace_from,
                PlanDay.date <= week_end,
            )
        ).scalars().all()
        for row in existing:
            session.delete(row)
        for item in rows:
            session.add(
                PlanDay(
                    date=item.date,
                    kind=item.kind,
                    title=item.title,
                    status="planned",
                    payload_json=json.dumps(_payload(item)),
                    block_id=block_id,
                )
            )
        session.commit()
    return get_week(week_start_for(replace_from))


def get_week(week_start: date) -> list[PlanDay]:
    week_end = week_start + timedelta(days=6)
    with SessionLocal() as session:
        return list(
            session.execute(
                select(PlanDay)
                .where(PlanDay.date >= week_start, PlanDay.date <= week_end)
                .order_by(PlanDay.date)
            ).scalars()
        )


def plan_day_json(day: PlanDay) -> dict:
    try:
        payload = json.loads(day.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": day.id,
        "date": day.date.isoformat(),
        "weekday": day.date.strftime("%A"),
        "kind": day.kind,
        "title": day.title,
        "delivery": "Hevy" if day.kind == "strength" else "Garmin" if day.kind == "cardio" else "—",
        "status": day.status,
        "hevy_routine_id": day.hevy_routine_id,
        "garmin_workout_id": day.garmin_workout_id,
        "payload_json": payload,
        "block_id": day.block_id,
        "created_at": day.created_at.isoformat() if day.created_at else None,
        "updated_at": day.updated_at.isoformat() if day.updated_at else None,
    }


def _active_block_context(for_date: date) -> dict | None:
    with SessionLocal() as session:
        block = session.execute(
            select(TrainingBlock).where(TrainingBlock.active.is_(True))
        ).scalars().first()
    if block is None:
        return None
    try:
        phases = json.loads(block.phases_json or "[]")
    except json.JSONDecodeError:
        phases = []
    week = max(1, min(len(phases), ((for_date - block.start_date).days // 7) + 1))
    phase = next((item for item in phases if item.get("week") == week), None)
    return {
        "id": block.id,
        "name": block.name,
        "goal": block.goal,
        "week": week,
        "total_weeks": len(phases),
        "phase": phase,
        "focus": block.focus,
        "deload": block.deload,
    }


def _recovery_rules_context(health_day: dict | None) -> dict:
    with SessionLocal() as session:
        rows = list(
            session.execute(
                select(RecoveryRule)
                .where(RecoveryRule.enabled.is_(True))
                .order_by(RecoveryRule.order_index)
            ).scalars()
        )
    triggered_ids = {row.id for row in rules.evaluate(rows, health_day)}
    return {
        "guardrails": [
            {
                "label": row.label,
                "description": row.description,
                "condition": rules.condition(row),
                "action": row.action,
                "triggered": row.id in triggered_ids,
            }
            for row in rows
        ]
    }


def _prompt(week_start: date, block_context: dict | None = None) -> str:
    week_end = week_start + timedelta(days=6)
    history_start = week_start - timedelta(days=28)
    health_days = stats.health().get("days", [])
    recent = stats.activity(history_start.isoformat(), (week_start - timedelta(days=1)).isoformat())
    latest_health = health_days[-1] if health_days else None
    context = {
        "focus": focus.current_directive(),
        "latest_recovery": latest_health,
        "recent_training": recent.get("days", []),
        "active_training_block": block_context,
        "recovery_rules": _recovery_rules_context(latest_health),
        "body_mode": body_mode.get_body_mode(),
    }
    return f"""Create a seven-day training plan for {week_start.isoformat()} through {week_end.isoformat()}.
Use the supplied focus, body mode, active training-block phase, recovery guardrails, latest recovery state, and recent completed training.
Bias weekly volume and intensity toward the block phase and its sets-per-muscle-group target. Coach is a planner,
not a workout tracker: produce planned sessions only and do not add logging or timer instructions. Respect every
enabled recovery guardrail; apply the structured action when a numeric guardrail is triggered. Apply the body mode's
descriptor and suggested bias when choosing training volume, cardio demand, and recovery trade-offs.

CONTEXT:
{json.dumps(context, default=str)}

Return ONLY one JSON object. Field values shown as <…> below are placeholders describing the
allowed value — replace each with a real value; never output the placeholder text or the "a|b|c" lists verbatim:
{{"days":[{{"date":"YYYY-MM-DD","kind":"<exactly one of: strength, cardio, rest>","title":"short title",
"exercises":[{{"name":"Barbell Squat","scheme":"3×8 · RPE 8","expanded":true,
"sets":[{{"set":"1","type":"normal","weight_kg":100,"reps":8,"rpe":8}}],
"rest_seconds":120,"notes":"Controlled eccentric","progression":{{"kind":"hold","text":"Hold load"}},
"alternatives":"Hack squat · Leg press"}}],"duration_minutes":50,"distance_km":null,
"zone":null,"cardio_type":"<exactly one of: running, cycling, walking, cardio>","notes":"Session coaching notes",
"targets":[{{"label":"Duration","value":"45–55 min"}}]}}]}}

Include every date exactly once. Strength days require structured exercises and at least one prescribed
set per exercise. Valid set types are warmup, normal, failure, and dropset. RPE must be 6–10 when present.
Use an empty exercises array for cardio and rest. cardio_type must always be exactly one of running, cycling,
walking, or cardio (use "cardio" on strength and rest days). Use cardio only when the session is not
specifically running, cycling, or walking. Use null (not a placeholder string) for any other irrelevant field.
"""


async def _generate(week_start: date, block_context: dict | None = None) -> GeneratedWeek:
    try:
        raw = await run_once(
            _prompt(week_start, block_context),
            max_tokens=settings.coach_plan_max_tokens,
        )
    except Exception as exc:
        raise PlanGenerationError("Coach could not generate a plan") from exc
    return _extract_week(raw, week_start)


async def generate_week(week_start: date) -> list[PlanDay]:
    week_start = week_start_for(week_start)
    block_context = _active_block_context(week_start)
    generated = await _generate(week_start, block_context)
    return _persist(generated, week_start, block_context["id"] if block_context else None)


async def replan_from(from_date: date) -> list[PlanDay]:
    week_start = week_start_for(from_date)
    block_context = _active_block_context(week_start)
    generated = await _generate(week_start, block_context)
    return _persist(generated, from_date, block_context["id"] if block_context else None)
