"""Persisted body-composition mode and deterministic coaching copy."""
from __future__ import annotations

from datetime import date, datetime, timezone

from coach.db import SessionLocal
from coach.focus import DEFAULT_DIRECTIVE, DEFAULT_FOCUS_RAW
from coach.models import CoachProfile


MODE_SPECS = {
    "cut": {
        "label": "Cut",
        "descriptor": "Keep strength volume high. Cap hard cardio if recovery drops below 60.",
        "bias": "Suggested bias: protein 1.9 g/kg, keep steps ≥ 9k, one extra strength session this week.",
    },
    "bulk": {
        "label": "Bulk",
        "descriptor": "Push progressive overload. Eat in a surplus; keep cardio easy and minimal.",
        "bias": "Suggested bias: protein 1.8 g/kg, slight surplus, prioritize compound progression.",
    },
    "recomp": {
        "label": "Recomp",
        "descriptor": "Hold weight steady. Maintain volume, recover well, let composition shift.",
        "bias": "Suggested bias: protein 2.0 g/kg, maintenance calories, consistent sleep + steps.",
    },
    "perf": {
        "label": "Perf",
        "descriptor": "Train for output. Periodize intensity, fuel around sessions, protect recovery.",
        "bias": "Suggested bias: fuel workouts, protein 1.8 g/kg, hold ACWR in the sweet spot.",
    },
}
DEFAULT_MODE = "cut"
DEFAULT_WEEK_COUNT = 8


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _state(row: CoachProfile | None, today: date) -> dict:
    mode = row.body_mode if row and row.body_mode in MODE_SPECS else DEFAULT_MODE
    started_at = row.body_mode_started_at if row else None
    week_count = row.body_mode_week_count if row and row.body_mode_week_count else DEFAULT_WEEK_COUNT
    week_count = max(1, week_count)
    week_index = 1
    if started_at is not None:
        week_index = max(1, min(week_count, ((today - started_at.date()).days // 7) + 1))
    spec = MODE_SPECS[mode]
    return {
        "mode": mode,
        "modes": [{"key": key, "label": value["label"]} for key, value in MODE_SPECS.items()],
        "weekIndex": week_index,
        "weekCount": week_count,
        "descriptor": spec["descriptor"],
        "bias": spec["bias"],
    }


def get_body_mode(today: date | None = None) -> dict:
    with SessionLocal() as session:
        row = session.get(CoachProfile, 1)
    return _state(row, today or date.today())


def set_body_mode(mode: str, now: datetime | None = None) -> dict:
    if mode not in MODE_SPECS:
        raise ValueError(f"Unknown body mode: {mode}")
    changed_at = now or _utcnow()
    with SessionLocal() as session:
        row = session.get(CoachProfile, 1)
        if row is None:
            row = CoachProfile(
                id=1,
                focus_raw=DEFAULT_FOCUS_RAW,
                directive=DEFAULT_DIRECTIVE,
            )
            session.add(row)
        row.body_mode = mode
        row.body_mode_started_at = changed_at
        row.body_mode_week_count = row.body_mode_week_count or DEFAULT_WEEK_COUNT
        session.commit()
        session.refresh(row)
        return _state(row, changed_at.date())
