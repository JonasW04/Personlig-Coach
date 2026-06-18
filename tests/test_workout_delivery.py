import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach import workout_delivery
from coach.models import PlanDay, TrainingBlock


class TestWorkoutDelivery(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        TrainingBlock.__table__.create(self.engine)
        PlanDay.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self.session_patch = patch.object(workout_delivery, "SessionLocal", self.sessions)
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    def add_day(self, kind: str, *, remote_id: str | None = None) -> date:
        planned_date = date(2026, 6, 19)
        payload = (
            {
                "exercises": [
                    {
                        "name": "Squat (Barbell)",
                        "sets": [{"type": "normal", "weight_kg": 100, "reps": 5}],
                    }
                ]
            }
            if kind == "strength"
            else {
                "cardio_type": "running",
                "duration_minutes": 30,
                "steps": [{"kind": "work", "duration_minutes": 30}],
            }
        )
        with self.sessions() as session:
            session.add(
                PlanDay(
                    date=planned_date,
                    kind=kind,
                    title="Quality session",
                    status="planned",
                    delivery_status="pending",
                    hevy_routine_id=remote_id if kind == "strength" else None,
                    garmin_workout_id=remote_id if kind == "cardio" else None,
                    payload_json=json.dumps(payload),
                )
            )
            session.commit()
        return planned_date

    def saved(self) -> PlanDay:
        with self.sessions() as session:
            row = session.execute(select(PlanDay)).scalars().one()
            session.expunge(row)
            return row

    def test_strength_is_date_named_and_idempotent(self):
        planned_date = self.add_day("strength")
        with patch.object(
            workout_delivery.hevy, "push_routine", return_value="routine-1"
        ) as push:
            workout_delivery.publish_day(planned_date)
            workout_delivery.publish_day(planned_date)

        push.assert_called_once()
        self.assertEqual("2026-06-19 · Quality session", push.call_args.args[0])
        self.assertEqual("routine-1", self.saved().hevy_routine_id)
        self.assertEqual("delivered", self.saved().delivery_status)

    def test_changed_cardio_replaces_old_workout_and_schedules_new_one(self):
        planned_date = self.add_day("cardio", remote_id="old-321")
        with (
            patch.object(workout_delivery.garmin, "delete_cardio_workout") as delete,
            patch.object(
                workout_delivery.garmin,
                "schedule_cardio_workout",
                return_value="new-654",
            ) as schedule,
        ):
            workout_delivery.publish_day(planned_date)

        delete.assert_called_once_with("old-321")
        self.assertEqual("2026-06-19 · Quality session", schedule.call_args.args[0])
        self.assertEqual(planned_date, schedule.call_args.args[2])
        self.assertEqual("new-654", self.saved().garmin_workout_id)

    def test_delivery_failure_is_recorded_for_retry(self):
        planned_date = self.add_day("strength")
        with patch.object(
            workout_delivery.hevy, "push_routine", side_effect=RuntimeError("offline")
        ):
            row = workout_delivery.publish_day(planned_date)

        self.assertEqual("failed", row.delivery_status)
        self.assertIn("offline", row.delivery_error)

    def test_failed_strength_delivery_adopts_created_routine_before_retry(self):
        planned_date = self.add_day("strength")
        with self.sessions() as session:
            row = session.execute(select(PlanDay)).scalars().one()
            row.delivery_status = "failed"
            row.delivery_error = "Hevy response did not include a routine id"
            session.commit()

        with (
            patch.object(
                workout_delivery.hevy,
                "find_routine_id_by_title",
                return_value="existing-created-id",
            ) as find,
            patch.object(
                workout_delivery.hevy,
                "push_routine",
                return_value="existing-created-id",
            ) as push,
        ):
            workout_delivery.publish_day(planned_date)

        title = "2026-06-19 · Quality session"
        find.assert_called_once_with(title)
        push.assert_called_once_with(title, unittest.mock.ANY, "existing-created-id")
        self.assertEqual("existing-created-id", self.saved().hevy_routine_id)
        self.assertEqual("delivered", self.saved().delivery_status)


if __name__ == "__main__":
    unittest.main()
