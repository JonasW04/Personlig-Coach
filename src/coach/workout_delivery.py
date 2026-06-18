"""Idempotent delivery of active plan sessions to Hevy and Garmin."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timezone

from sqlalchemy import or_, select

from coach.db import SessionLocal
from coach.integrations import garmin, hevy
from coach.models import PlanDay

log = logging.getLogger("coach.workout_delivery")


def delivery_title(day: PlanDay) -> str:
    return f"{day.date.isoformat()} · {day.title}"


def payload_hash(day: PlanDay) -> str:
    body = json.dumps(
        {
            "date": day.date.isoformat(),
            "kind": day.kind,
            "title": delivery_title(day),
            "payload": json.loads(day.payload_json or "{}"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()


def _load(planned_date: date) -> PlanDay | None:
    with SessionLocal() as session:
        row = session.execute(
            select(PlanDay).where(PlanDay.date == planned_date)
        ).scalars().first()
        if row is not None:
            session.expunge(row)
        return row


def _update(planned_date: date, **values) -> PlanDay | None:
    with SessionLocal() as session:
        row = session.execute(
            select(PlanDay).where(PlanDay.date == planned_date)
        ).scalars().first()
        if row is None:
            return None
        for key, value in values.items():
            setattr(row, key, value)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def _delete_hevy(day: PlanDay) -> None:
    if not day.hevy_routine_id:
        return
    hevy.delete_routine(day.hevy_routine_id)
    _update(day.date, hevy_routine_id=None)
    day.hevy_routine_id = None


def _delete_garmin(day: PlanDay) -> None:
    if not day.garmin_workout_id:
        return
    garmin.delete_cardio_workout(day.garmin_workout_id)
    _update(day.date, garmin_workout_id=None)
    day.garmin_workout_id = None


def publish_day(planned_date: date) -> PlanDay | None:
    """Publish one PlanDay; failures are recorded and returned, not raised."""
    day = _load(planned_date)
    if day is None:
        return None
    try:
        fingerprint = payload_hash(day)
        relevant_id = (
            day.hevy_routine_id if day.kind == "strength"
            else day.garmin_workout_id if day.kind == "cardio"
            else None
        )
        obsolete_id = (
            day.garmin_workout_id if day.kind == "strength"
            else day.hevy_routine_id if day.kind == "cardio"
            else day.hevy_routine_id or day.garmin_workout_id
        )
        if (
            day.published_payload_hash == fingerprint
            and day.delivery_status == "delivered"
            and relevant_id
            and not obsolete_id
        ):
            return day

        payload = json.loads(day.payload_json or "{}")
        if day.kind == "strength":
            _delete_garmin(day)
            existing_id = day.hevy_routine_id
            if not existing_id and day.delivery_status == "failed":
                existing_id = hevy.find_routine_id_by_title(delivery_title(day))
            routine_id = hevy.push_routine(
                delivery_title(day), payload, existing_id
            )
            _update(day.date, hevy_routine_id=routine_id)
            day.hevy_routine_id = routine_id
            status = "ready_in_hevy"
        elif day.kind == "cardio":
            _delete_hevy(day)
            # Garmin has no reliable workout update call. Delete the old
            # Coach-owned artifact first, then upload and schedule its replacement.
            _delete_garmin(day)
            workout_id = garmin.schedule_cardio_workout(
                delivery_title(day), payload, day.date
            )
            _update(day.date, garmin_workout_id=workout_id)
            day.garmin_workout_id = workout_id
            status = "scheduled"
        else:
            _delete_hevy(day)
            _delete_garmin(day)
            return _update(
                day.date,
                status="rest",
                delivery_status="not_applicable",
                delivery_error=None,
                published_payload_hash=fingerprint,
                published_at=datetime.now(timezone.utc),
            )

        return _update(
            day.date,
            status=status,
            delivery_status="delivered",
            delivery_error=None,
            published_payload_hash=fingerprint,
            published_at=datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001 - delivery retries need the exact failure
        log.exception("workout delivery failed for %s", planned_date)
        return _update(
            planned_date,
            delivery_status="failed",
            delivery_error=str(exc)[:1000],
        )


def publish_days(days: list[PlanDay]) -> list[PlanDay]:
    return [row for day in days if (row := publish_day(day.date)) is not None]


def retry_pending(today: date | None = None) -> list[PlanDay]:
    """Retry failed/pending sessions and cleanup-bearing rest days."""
    today = today or date.today()
    with SessionLocal() as session:
        dates = list(
            session.execute(
                select(PlanDay.date)
                .where(
                    PlanDay.date >= today,
                    or_(
                        PlanDay.delivery_status.in_(["pending", "failed"]),
                        PlanDay.hevy_routine_id.is_not(None),
                        PlanDay.garmin_workout_id.is_not(None),
                    )
                )
                .order_by(PlanDay.date)
            ).scalars()
        )
    return [row for planned_date in dates if (row := publish_day(planned_date)) is not None]
