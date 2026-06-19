"""Generate, validate, and persist weekly training plans."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select

from coach import body_mode, focus, rules
from coach.config import settings
from coach.integrations import hevy
from coach.llm import TruncatedCompletion, complete
from coach.db import SessionLocal
from coach.models import PlanDay, RecoveryRule
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


class GeneratedCardioStep(BaseModel):
    kind: Literal["warmup", "work", "recovery", "cooldown"]
    duration_minutes: int = Field(ge=1, le=180)
    target: str | None = Field(default=None, max_length=100)
    notes: str = Field(default="", max_length=500)


class GeneratedDay(BaseModel):
    date: date
    kind: Literal["strength", "cardio", "rest"]
    title: str = Field(min_length=1, max_length=200)
    exercises: list[GeneratedExercise] = Field(default_factory=list)
    duration_minutes: int | None = Field(default=None, ge=1, le=300)
    distance_km: float | None = Field(default=None, ge=0, le=500)
    zone: str | None = Field(default=None, max_length=100)
    cardio_type: Literal["running", "cycling", "walking", "cardio"] = "cardio"
    steps: list[GeneratedCardioStep] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)
    targets: list[GeneratedTarget] = Field(default_factory=list)

    @field_validator("cardio_type", mode="before")
    @classmethod
    def _coerce_cardio_type(cls, value):
        # Irrelevant on strength/rest days: the model often sends null or echoes
        # the "running|cycling|walking|cardio" placeholder. Normalise to "cardio".
        return value if value in {"running", "cycling", "walking", "cardio"} else "cardio"

    @field_validator("zone", mode="before")
    @classmethod
    def _coerce_zone(cls, value):
        # The model sometimes returns a bare HR-zone number; render it as text.
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return f"Zone {int(value)}"
        return str(value)

    @field_validator("duration_minutes", mode="before")
    @classmethod
    def _coerce_duration(cls, value):
        # Rest days often come back as 0; treat sub-minute durations as unset and
        # clamp the upper bound so an over-long estimate still validates.
        if value is None:
            return None
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return None
        return None if minutes < 1 else min(minutes, 300)


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
        if item.kind == "cardio" and not item.steps:
            raise PlanGenerationError("Cardio sessions require structured workout steps")
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


def _persist(week: GeneratedWeek, replace_from: date) -> list[PlanDay]:
    week_end = max(item.date for item in week.days)
    rows = [item for item in week.days if item.date >= replace_from]
    with SessionLocal() as session:
        existing = session.execute(
            select(PlanDay).where(
                PlanDay.date >= replace_from,
                PlanDay.date <= week_end,
            )
        ).scalars().all()
        existing_by_date = {row.date: row for row in existing}
        for item in rows:
            payload_json = json.dumps(_payload(item), sort_keys=True)
            row = existing_by_date.get(item.date)
            if row is None:
                session.add(PlanDay(
                    date=item.date,
                    kind=item.kind,
                    title=item.title,
                    status="planned",
                    delivery_status="not_applicable" if item.kind == "rest" else "pending",
                    payload_json=payload_json,
                ))
                continue

            changed = (
                row.kind != item.kind
                or row.title != item.title
                or row.payload_json != payload_json
            )
            row.kind = item.kind
            row.title = item.title
            row.payload_json = payload_json
            if changed:
                row.status = "planned"
                row.delivery_status = "not_applicable" if item.kind == "rest" else "pending"
                row.delivery_error = None
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
        "delivery_status": day.delivery_status,
        "delivery_error": day.delivery_error,
        "published_at": day.published_at.isoformat() if day.published_at else None,
        "payload_json": payload,
        "created_at": day.created_at.isoformat() if day.created_at else None,
        "updated_at": day.updated_at.isoformat() if day.updated_at else None,
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


def _exercise_catalog() -> list[dict]:
    """Return a compact Hevy catalog for exact, publishable exercise selection."""
    try:
        templates = hevy.fetch_exercise_templates()
    except Exception:  # noqa: BLE001 - planning still works when Hevy is unavailable
        log.info("Hevy exercise catalog unavailable during planning", exc_info=True)
        return []
    return [
        {"id": str(item["id"]), "title": str(item["title"])}
        for item in templates
        if item.get("id") and item.get("title")
    ]


def _prompt(
    week_start: date,
    review_context: dict | None = None,
    exercise_catalog: list[dict] | None = None,
    planning_from: date | None = None,
) -> str:
    week_end = week_start + timedelta(days=6)
    history_start = week_start - timedelta(days=28)
    planning_from = planning_from or week_start
    history_end = planning_from - timedelta(days=1)
    health_days = stats.health().get("days", [])
    recent = stats.activity(history_start.isoformat(), history_end.isoformat())
    latest_health = dict(health_days[-1]) if health_days else None
    calculated_score = (review_context or {}).get("readiness_score")
    if latest_health is not None and calculated_score is not None:
        latest_health["garmin_training_readiness"] = latest_health.get(
            "training_readiness"
        )
        latest_health["training_readiness"] = calculated_score
    preserved = [
        plan_day_json(day)
        for day in get_week(week_start)
        if day.date < planning_from
    ]
    context = {
        "focus": focus.current_directive(),
        "latest_recovery": latest_health,
        "recent_training": recent.get("days", []),
        "recovery_rules": _recovery_rules_context(latest_health),
        "body_mode": body_mode.get_body_mode(),
        "review_context": review_context,
        "available_hevy_exercises": (exercise_catalog or [])[:500],
        "planning_from": planning_from.isoformat(),
        "preserved_completed_days": preserved,
    }
    return f"""Create a seven-day training plan for {week_start.isoformat()} through {week_end.isoformat()}.
Use the supplied focus, body mode, recovery guardrails, latest recovery state, and recent completed training.
Coach is a planner,
not a workout tracker: produce planned sessions only and do not add logging or timer instructions. Respect every
enabled recovery guardrail; apply the structured action when a numeric guardrail is triggered. Apply the body mode's
descriptor and suggested bias when choosing training volume, cardio demand, and recovery trade-offs.
Design every strength workout exercise-by-exercise for this athlete; do not copy or limit the plan to
previously saved routines. Prefer exact titles from available_hevy_exercises so every chosen movement can
be published to Hevy. Select movements for the goal, movement balance, recent performance, fatigue,
equipment implied by the catalog, and progression. Cardio sessions must be structured Garmin workouts,
including warm-up, work, recovery (when relevant), and cool-down steps rather than only a title and duration.
When planning_from is after Monday, treat preserved_completed_days as immutable history. Rebalance only planning_from
through Sunday while still returning all seven dates in the JSON contract.

CONTEXT:
{json.dumps(context, default=str)}

Return ONLY one JSON object. Field values shown as <…> below are placeholders describing the
allowed value — replace each with a real value; never output the placeholder text or the "a|b|c" lists verbatim:
{{"days":[{{"date":"YYYY-MM-DD","kind":"<exactly one of: strength, cardio, rest>","title":"short title",
"exercises":[{{"name":"Barbell Squat","scheme":"3×8 · RPE 8","expanded":true,
"sets":[{{"set":"1","type":"normal","weight_kg":100,"reps":8,"rpe":8}}],
"rest_seconds":120,"notes":"Controlled eccentric","progression":{{"kind":"hold","text":"Hold load"}},
"alternatives":"Hack squat · Leg press"}}],"duration_minutes":50,"distance_km":null,
"zone":null,"cardio_type":"<exactly one of: running, cycling, walking, cardio>",
"steps":[{{"kind":"<warmup|work|recovery|cooldown>","duration_minutes":10,"target":"Zone 2","notes":"Easy"}}],
"notes":"Session coaching notes",
"targets":[{{"label":"Duration","value":"45–55 min"}}]}}]}}

Include every date exactly once. Strength days require structured exercises and at least one prescribed
set per exercise. Valid set types are warmup, normal, failure, and dropset. RPE must be 6–10 when present.
Use an empty exercises array for cardio and rest. Cardio days require at least one structured step; use an empty
steps array for strength and rest. cardio_type must always be exactly one of running, cycling,
walking, or cardio (use "cardio" on strength and rest days). Use cardio only when the session is not
specifically running, cycling, or walking. Use null (not a placeholder string) for any other irrelevant field.
"""


async def _generate(
    week_start: date,
    review_context: dict | None = None,
    planning_from: date | None = None,
) -> GeneratedWeek:
    # Plan generation is a self-contained JSON transform: the prompt embeds all
    # context, so use the tool-less completion path rather than the full coach
    # agent. The agent's system prompt and tool specs would burn input context
    # and tempt the model to spend its shared reasoning+output budget on tool
    # deliberation, truncating the large JSON plan.
    try:
        exercise_catalog = _exercise_catalog()
        raw = await complete(
            _prompt(
                week_start,
                review_context,
                exercise_catalog,
                planning_from,
            ),
            model=settings.coach_model,
            max_tokens=settings.coach_plan_max_tokens,
            raise_on_truncation=True,
        )
    except TruncatedCompletion as exc:
        raise PlanGenerationError(
            "Coach ran out of token budget before finishing the plan. Try again."
        ) from exc
    except Exception as exc:
        raise PlanGenerationError("Coach could not generate a plan") from exc
    week = _extract_week(raw, week_start)
    if exercise_catalog:
        for day in week.days:
            for exercise in day.exercises:
                try:
                    exercise.name = str(
                        hevy.match_exercise_template(exercise.name, exercise_catalog)["title"]
                    )
                except hevy.HevyRoutineError as exc:
                    raise PlanGenerationError(str(exc)) from exc
    return week


async def generate_week(
    week_start: date, *, review_context: dict | None = None
) -> list[PlanDay]:
    week_start = week_start_for(week_start)
    generated = await _generate(
        week_start, review_context, planning_from=week_start
    )
    return _persist(generated, week_start)


async def replan_from(
    from_date: date, *, review_context: dict | None = None
) -> list[PlanDay]:
    week_start = week_start_for(from_date)
    generated = await _generate(
        week_start, review_context, planning_from=from_date
    )
    return _persist(generated, from_date)
