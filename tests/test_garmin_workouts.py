import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach.integrations import garmin
from coach.models import PlanDay
from coach.web import app as web_app


class TestGarminWorkoutMapping(unittest.TestCase):
    def test_uploads_typed_running_workout_then_schedules_it(self):
        client = MagicMock()
        client.upload_running_workout.return_value = {"workoutId": 321}
        payload = {
            "cardio_type": "running",
            "duration_minutes": 45,
            "distance_km": 8.2,
            "zone": "Zone 2",
            "steps": [
                {"kind": "warmup", "duration_minutes": 5, "target": "Easy"},
                {"kind": "work", "duration_minutes": 35, "target": "Zone 2"},
                {"kind": "cooldown", "duration_minutes": 5, "target": "Easy"},
            ],
        }
        with (
            patch.object(garmin, "_client_from_token", return_value=client),
            patch.object(garmin, "_dump_token", return_value="token"),
            patch.object(garmin, "save_token") as save_token,
        ):
            workout_id = garmin.schedule_cardio_workout(
                "Easy run", payload, date(2026, 6, 19)
            )

        self.assertEqual("321", workout_id)
        workout = client.upload_running_workout.call_args.args[0]
        self.assertEqual("running", workout.sportType["sportTypeKey"])
        self.assertEqual(2700, workout.estimatedDurationInSecs)
        self.assertEqual(3, len(workout.workoutSegments[0].workoutSteps))
        self.assertIn("Zone 2", workout.description)
        client.schedule_workout.assert_called_once_with(321, "2026-06-19")
        save_token.assert_called_once_with("token")

    def test_rejects_cardio_without_duration(self):
        with self.assertRaises(garmin.GarminWorkoutPayloadError):
            garmin._cardio_workout("Run", {"cardio_type": "running"})


class TestGarminScheduleEndpoint(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        PlanDay.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self.session_patch = patch.object(web_app, "SessionLocal", self.session_factory)
        self.delivery_session_patch = patch.object(
            web_app.workout_delivery, "SessionLocal", self.session_factory
        )
        self.session_patch.start()
        self.delivery_session_patch.start()

    def tearDown(self):
        self.delivery_session_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()

    async def test_endpoint_persists_garmin_id_and_scheduled_status(self):
        planned_date = date(2026, 6, 19)
        with self.session_factory() as session:
            session.add(
                PlanDay(
                    date=planned_date,
                    kind="cardio",
                    title="Easy run",
                    status="planned",
                    payload_json=json.dumps(
                        {"cardio_type": "running", "duration_minutes": 45}
                    ),
                )
            )
            session.commit()

        with patch.object(
            web_app.workout_delivery.garmin,
            "schedule_cardio_workout",
            return_value="321",
        ) as schedule:
            response = await web_app.schedule_plan_day_in_garmin(planned_date)

        self.assertEqual("321", response["garmin_workout_id"])
        self.assertEqual("scheduled", response["status"])
        schedule.assert_called_once()


if __name__ == "__main__":
    unittest.main()
