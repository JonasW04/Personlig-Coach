"""Hevy API client + sync into Postgres.

Hevy API (Pro-only). Key: https://hevy.com/settings?developer
Docs: https://api.hevyapp.com/docs/  (schema is not guaranteed stable)
"""
from __future__ import annotations

from datetime import datetime

import httpx

from coach.config import settings
from coach.db import SessionLocal
from coach.models import Exercise, SetEntry, Workout

BASE_URL = "https://api.hevyapp.com/v1"
PAGE_SIZE = 10  # Hevy caps workouts page size at 10


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"api-key": settings.hevy_api_key, "accept": "application/json"},
        timeout=30,
    )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch_workouts(max_pages: int | None = None) -> list[dict]:
    """Page through GET /workouts. Returns raw workout dicts (newest first)."""
    out: list[dict] = []
    with _client() as c:
        page = 1
        while True:
            resp = c.get("/workouts", params={"page": page, "pageSize": PAGE_SIZE})
            resp.raise_for_status()
            data = resp.json()
            workouts = data.get("workouts", [])
            out.extend(workouts)
            page_count = data.get("page_count", page)
            if page >= page_count or (max_pages and page >= max_pages):
                break
            page += 1
    return out


def upsert_workout(session, w: dict) -> None:
    """Replace a workout and its children with the fetched version."""
    wid = w["id"]
    # Delete via the ORM object so the delete-orphan cascade removes child
    # exercises/sets (a bulk DELETE would hit the FK constraint instead).
    existing = session.get(Workout, wid)
    if existing is not None:
        session.delete(existing)
        session.flush()

    workout = Workout(
        id=wid,
        title=w.get("title"),
        start_time=_parse_dt(w.get("start_time")),
        end_time=_parse_dt(w.get("end_time")),
    )
    for ei, ex in enumerate(w.get("exercises", [])):
        exercise = Exercise(
            template_id=ex.get("exercise_template_id"),
            title=ex.get("title", "Unknown"),
            order_index=ei,
        )
        for si, s in enumerate(ex.get("sets", [])):
            exercise.sets.append(
                SetEntry(
                    set_type=s.get("type"),
                    weight_kg=s.get("weight_kg"),
                    reps=s.get("reps"),
                    distance_m=s.get("distance_meters"),
                    duration_s=s.get("duration_seconds"),
                    rpe=s.get("rpe"),
                    order_index=si,
                )
            )
        workout.exercises.append(exercise)
    session.add(workout)


def sync(max_pages: int | None = None) -> int:
    """Pull workouts from Hevy into the DB. Returns count synced."""
    workouts = fetch_workouts(max_pages=max_pages)
    with SessionLocal() as session:
        for w in workouts:
            upsert_workout(session, w)
        session.commit()
    return len(workouts)
