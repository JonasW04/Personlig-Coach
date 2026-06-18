import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach.integrations import hevy
from coach.models import PlanDay, TrainingBlock
from coach.web import app as web_app


def strength_payload() -> dict:
    return {
        "duration_minutes": 50,
        "notes": "Keep two reps in reserve.",
        "exercises": [
            {
                "name": "Barbell Squat",
                "scheme": "3×8 · RPE 8",
                "sets": [
                    {"set": "W1", "type": "warmup", "weight_kg": 60, "reps": 8, "rpe": None},
                    {"set": "1", "type": "normal", "weight_kg": 100, "reps": 8, "rpe": 8},
                ],
                "rest_seconds": 120,
                "notes": "Controlled eccentric.",
            }
        ],
    }


class TestHevyRoutineMapping(unittest.TestCase):
    def setUp(self):
        hevy.clear_template_cache()

    def test_matches_normalised_and_fuzzy_exercise_names(self):
        templates = [
            {"id": "squat", "title": "Squat (Barbell)"},
            {"id": "bench", "title": "Bench Press"},
        ]
        self.assertEqual(
            "squat",
            hevy.match_exercise_template("Barbell Squat", templates)["id"],
        )
        self.assertEqual(
            "bench",
            hevy.match_exercise_template("Bench Pres", templates)["id"],
        )
        with self.assertRaises(hevy.HevyRoutineError):
            hevy.match_exercise_template("Cable Woodchop", templates)

    def test_builds_hevy_payload_without_builder_only_rpe(self):
        with patch.object(
            hevy,
            "fetch_exercise_templates",
            return_value=[{"id": "squat", "title": "Squat (Barbell)"}],
        ):
            routine = hevy.build_routine_payload("Legs", strength_payload())

        self.assertEqual("squat", routine["exercises"][0]["exercise_template_id"])
        self.assertEqual("warmup", routine["exercises"][0]["sets"][0]["type"])
        self.assertNotIn("rpe", routine["exercises"][0]["sets"][1])
        self.assertEqual("Keep two reps in reserve.", routine["notes"])

    def test_fetches_all_template_pages_and_caches_result(self):
        pages = []

        def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params["page"])
            pages.append(page)
            return httpx.Response(
                200,
                json={
                    "page_count": 2,
                    "exercise_templates": [{"id": str(page), "title": f"Exercise {page}"}],
                },
            )

        def client():
            return httpx.Client(
                base_url=hevy.BASE_URL,
                transport=httpx.MockTransport(handler),
            )

        with patch.object(hevy, "_client", side_effect=client):
            first = hevy.fetch_exercise_templates()
            second = hevy.fetch_exercise_templates()

        self.assertEqual([1, 2], pages)
        self.assertEqual(first, second)

    def test_create_and_update_use_hevy_routine_envelopes(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append((request.method, request.url.path, json.loads(request.content)))
            return httpx.Response(201 if request.method == "POST" else 200, json={"id": "routine-1"})

        def client():
            return httpx.Client(
                base_url=hevy.BASE_URL,
                transport=httpx.MockTransport(handler),
            )

        payload = {"title": "Legs", "folder_id": None, "notes": "", "exercises": []}
        with patch.object(hevy, "_client", side_effect=client):
            hevy.create_routine(payload)
            hevy.update_routine("routine-1", payload)

        self.assertEqual(("POST", "/v1/routines"), requests[0][:2])
        self.assertIsNone(requests[0][2]["routine"]["folder_id"])
        self.assertEqual(("PUT", "/v1/routines/routine-1"), requests[1][:2])
        self.assertNotIn("folder_id", requests[1][2]["routine"])

    def test_push_creates_new_routines_and_updates_existing_ones(self):
        mapped = {"title": "Legs", "folder_id": None, "notes": "", "exercises": []}
        with (
            patch.object(hevy, "build_routine_payload", return_value=mapped),
            patch.object(hevy, "create_routine", return_value={"id": "new-id"}) as create,
            patch.object(hevy, "update_routine", return_value={"id": "existing-id"}) as update,
        ):
            self.assertEqual("new-id", hevy.push_routine("Legs", strength_payload()))
            self.assertEqual(
                "existing-id",
                hevy.push_routine("Legs", strength_payload(), "existing-id"),
            )

        create.assert_called_once_with(mapped)
        update.assert_called_once_with("existing-id", mapped)


class TestPushHevyEndpoint(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TrainingBlock.__table__.create(self.engine)
        PlanDay.__table__.create(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            future=True,
            expire_on_commit=False,
        )
        self.session_patch = patch.object(web_app, "SessionLocal", self.session_factory)
        self.delivery_session_patch = patch.object(
            web_app.workout_delivery, "SessionLocal", self.session_factory
        )
        self.session_patch.start()
        self.delivery_session_patch.start()
        with self.session_factory() as session:
            session.add(
                PlanDay(
                    date=date(2026, 6, 17),
                    kind="strength",
                    title="Legs",
                    status="planned",
                    payload_json=json.dumps(strength_payload()),
                )
            )
            session.commit()

    def tearDown(self):
        self.delivery_session_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()

    async def test_push_persists_routine_id_and_ready_status(self):
        with patch.object(hevy, "push_routine", return_value="routine-1") as push:
            response = await web_app.push_plan_day_to_hevy(date(2026, 6, 17))

        self.assertEqual("routine-1", response["hevy_routine_id"])
        self.assertEqual("ready_in_hevy", response["status"])
        push.assert_called_once()
        with self.session_factory() as session:
            saved = session.execute(select(PlanDay)).scalars().one()
        self.assertEqual("routine-1", saved.hevy_routine_id)
        self.assertEqual("ready_in_hevy", saved.status)
