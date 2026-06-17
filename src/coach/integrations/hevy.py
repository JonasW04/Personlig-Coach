"""Hevy API client + sync into Postgres.

Hevy API (Pro-only). Key: https://hevy.com/settings?developer
Docs: https://api.hevyapp.com/docs/  (schema is not guaranteed stable)
"""
from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
import time
import unicodedata

import httpx

from coach.config import settings
from coach.db import SessionLocal
from coach.models import Exercise, SetEntry, Workout

BASE_URL = "https://api.hevyapp.com/v1"
PAGE_SIZE = 10  # Hevy caps workouts page size at 10
TEMPLATE_PAGE_SIZE = 100
TEMPLATE_CACHE_SECONDS = 15 * 60
_template_cache: tuple[float, list[dict]] | None = None


class HevyConfigurationError(RuntimeError):
    pass


class HevyRoutineError(ValueError):
    pass


def _client() -> httpx.Client:
    if not settings.hevy_api_key:
        raise HevyConfigurationError("HEVY_API_KEY is not configured")
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


def clear_template_cache() -> None:
    global _template_cache
    _template_cache = None


def fetch_exercise_templates(*, force: bool = False) -> list[dict]:
    """Fetch and briefly cache all exercise templates available to the account."""
    global _template_cache
    now = time.monotonic()
    if not force and _template_cache and now - _template_cache[0] < TEMPLATE_CACHE_SECONDS:
        return list(_template_cache[1])

    out: list[dict] = []
    with _client() as client:
        page = 1
        while True:
            response = client.get(
                "/exercise_templates",
                params={"page": page, "pageSize": TEMPLATE_PAGE_SIZE},
            )
            response.raise_for_status()
            data = response.json()
            out.extend(data.get("exercise_templates", []))
            if page >= data.get("page_count", page):
                break
            page += 1
    _template_cache = (now, out)
    return list(out)


def _normalise_exercise_name(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    words = ["".join(ch for ch in word.lower() if ch.isalnum()) for word in plain.split()]
    return " ".join(sorted(word for word in words if word))


def match_exercise_template(
    name: str,
    templates: list[dict],
    *,
    cutoff: float = 0.75,
) -> dict:
    wanted = _normalise_exercise_name(name)
    candidates = [
        (template, _normalise_exercise_name(str(template.get("title", ""))))
        for template in templates
        if template.get("id") and template.get("title")
    ]
    for template, normalised in candidates:
        if normalised == wanted:
            return template
    if not candidates:
        raise HevyRoutineError(f'No Hevy exercise template matched "{name}"')
    best, score = max(
        ((template, SequenceMatcher(None, wanted, normalised).ratio()) for template, normalised in candidates),
        key=lambda item: item[1],
    )
    if score < cutoff:
        raise HevyRoutineError(f'No Hevy exercise template matched "{name}"')
    return best


def build_routine_payload(title: str, payload: dict) -> dict:
    """Map a structured strength PlanDay payload to Hevy's routine schema."""
    exercises = payload.get("exercises")
    if not isinstance(exercises, list) or not exercises:
        raise HevyRoutineError("Strength plan has no exercises")
    templates = fetch_exercise_templates()
    routine_exercises = []
    for exercise in exercises:
        if not isinstance(exercise, dict):
            raise HevyRoutineError("Strength exercise is missing its set prescription")
        name = str(exercise.get("name", "")).strip()
        template = match_exercise_template(name, templates)
        sets = exercise.get("sets")
        if not isinstance(sets, list) or not sets:
            raise HevyRoutineError(f'Exercise "{name}" has no prescribed sets')
        mapped_sets = []
        for item in sets:
            set_type = item.get("type", "normal")
            if set_type not in {"warmup", "normal", "failure", "dropset"}:
                raise HevyRoutineError(f'Exercise "{name}" has an invalid set type')
            mapped_sets.append(
                {
                    "type": set_type,
                    "weight_kg": item.get("weight_kg"),
                    "reps": item.get("reps"),
                }
            )
        routine_exercises.append(
            {
                "exercise_template_id": template["id"],
                "superset_id": None,
                "rest_seconds": exercise.get("rest_seconds"),
                "notes": exercise.get("notes") or None,
                "sets": mapped_sets,
            }
        )
    return {
        "title": title,
        "folder_id": None,
        "notes": payload.get("notes") or "",
        "exercises": routine_exercises,
    }


def create_routine(payload: dict) -> dict:
    with _client() as client:
        response = client.post("/routines", json={"routine": payload})
        response.raise_for_status()
        return response.json()


def update_routine(routine_id: str, payload: dict) -> dict:
    update_payload = {key: value for key, value in payload.items() if key != "folder_id"}
    with _client() as client:
        response = client.put(f"/routines/{routine_id}", json={"routine": update_payload})
        response.raise_for_status()
        return response.json()


def push_routine(title: str, payload: dict, routine_id: str | None = None) -> str:
    routine_payload = build_routine_payload(title, payload)
    result = update_routine(routine_id, routine_payload) if routine_id else create_routine(routine_payload)
    routine = result.get("routine", result)
    saved_id = routine.get("id") if isinstance(routine, dict) else None
    if not saved_id:
        raise HevyRoutineError("Hevy response did not include a routine id")
    return str(saved_id)


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
