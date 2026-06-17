import json
import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach import plan
from coach.models import CoachProfile, PlanDay, RecoveryRule, TrainingBlock


WEEK_START = date(2026, 6, 15)


def generated_week(prefix: str = "New") -> str:
    kinds = ["strength", "cardio", "strength", "rest", "strength", "cardio", "rest"]
    days = []
    for offset, kind in enumerate(kinds):
        exercises = []
        if kind == "strength":
            exercises = [
                {
                    "name": "Squat",
                    "scheme": "3×8 · RPE 8",
                    "expanded": True,
                    "sets": [
                        {
                            "set": "1",
                            "type": "normal",
                            "weight_kg": 100,
                            "reps": 8,
                            "rpe": 8,
                        }
                    ],
                    "rest_seconds": 120,
                    "notes": "Controlled reps",
                    "progression": {"kind": "hold", "text": "Hold load"},
                    "alternatives": "Hack squat",
                }
            ]
        days.append(
            {
                "date": (WEEK_START + timedelta(days=offset)).isoformat(),
                "kind": kind,
                "title": f"{prefix} {kind.title()}",
                "exercises": exercises,
                "duration_minutes": 40 if kind != "rest" else None,
                "distance_km": 6 if kind == "cardio" else None,
                "zone": "Zone 2" if kind == "cardio" else None,
            }
        )
        if kind == "cardio":
            days[-1]["cardio_type"] = "running"
    return json.dumps({"days": days})


class TestPlanEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        TrainingBlock.__table__.create(self.engine)
        RecoveryRule.__table__.create(self.engine)
        CoachProfile.__table__.create(self.engine)
        PlanDay.__table__.create(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine, future=True, expire_on_commit=False
        )
        self.session_patch = patch.object(plan, "SessionLocal", self.session_factory)
        self.body_mode_session_patch = patch.object(
            plan.body_mode, "SessionLocal", self.session_factory
        )
        self.session_patch.start()
        self.body_mode_session_patch.start()

    def tearDown(self):
        self.body_mode_session_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()

    def add_day(self, day: date, title: str) -> None:
        with self.session_factory() as session:
            session.add(
                PlanDay(
                    date=day,
                    kind="strength",
                    title=title,
                    status="planned",
                    payload_json='{"exercises":["Squat"]}',
                )
            )
            session.commit()

    async def test_generate_validates_and_persists_all_seven_days(self):
        with (
            patch.object(plan, "_prompt", return_value="prompt"),
            patch.object(plan, "run_once", new=AsyncMock(return_value=generated_week())),
        ):
            rows = await plan.generate_week(WEEK_START)

        self.assertEqual(7, len(rows))
        self.assertEqual(WEEK_START, rows[0].date)
        self.assertEqual("New Strength", rows[0].title)
        self.assertEqual("Squat", json.loads(rows[0].payload_json)["exercises"][0]["name"])
        self.assertEqual("running", json.loads(rows[1].payload_json)["cardio_type"])

    async def test_replan_preserves_days_before_from_date(self):
        self.add_day(WEEK_START, "Original Monday")
        self.add_day(WEEK_START + timedelta(days=1), "Original Tuesday")
        with (
            patch.object(plan, "_prompt", return_value="prompt"),
            patch.object(plan, "run_once", new=AsyncMock(return_value=generated_week())),
        ):
            rows = await plan.replan_from(WEEK_START + timedelta(days=2))

        self.assertEqual(7, len(rows))
        self.assertEqual("Original Monday", rows[0].title)
        self.assertEqual("Original Tuesday", rows[1].title)
        self.assertEqual("New Strength", rows[2].title)

    async def test_invalid_generation_does_not_replace_existing_plan(self):
        self.add_day(WEEK_START, "Keep me")
        invalid = json.loads(generated_week())
        invalid["days"].pop()
        with (
            patch.object(plan, "_prompt", return_value="prompt"),
            patch.object(
                plan,
                "run_once",
                new=AsyncMock(return_value=json.dumps(invalid)),
            ),
        ):
            with self.assertRaises(plan.PlanGenerationError):
                await plan.generate_week(WEEK_START)

        with self.session_factory() as session:
            rows = session.execute(select(PlanDay)).scalars().all()
        self.assertEqual(["Keep me"], [row.title for row in rows])

    async def test_active_block_guides_plan_and_links_generated_days(self):
        with self.session_factory() as session:
            block = TrainingBlock(
                name="Summer strength",
                goal="strength",
                start_date=WEEK_START,
                end_date=WEEK_START + timedelta(weeks=6) - timedelta(days=1),
                phases_json=json.dumps(
                    [{"week": i, "label": "Intensify", "sets": 16 + i} for i in range(1, 7)]
                ),
                focus="Crisp compounds.",
                deload="Absorb the work.",
                active=True,
            )
            session.add(block)
            session.add_all(
                [
                    RecoveryRule(
                        label="Strength before cardio",
                        description="Protect lifting quality.",
                        condition_json=None,
                        action="cap_intensity",
                        enabled=True,
                        order_index=0,
                    ),
                    RecoveryRule(
                        label="Low readiness",
                        description="Swap hard work for Zone 2.",
                        condition_json=json.dumps(
                            {"metric": "training_readiness", "op": "<", "value": 60}
                        ),
                        action="swap_to_zone2",
                        enabled=True,
                        order_index=1,
                    ),
                ]
            )
            session.commit()
            block_id = block.id

        with (
            patch.object(plan.stats, "health", return_value={"days": [{"training_readiness": 42}]}),
            patch.object(plan.stats, "activity", return_value={"days": []}),
            patch.object(plan.focus, "current_directive", return_value="Build strength."),
            patch.object(plan, "run_once", new=AsyncMock(return_value=generated_week())) as run,
        ):
            rows = await plan.generate_week(WEEK_START)

        self.assertTrue(all(row.block_id == block_id for row in rows))
        prompt = run.await_args.args[0]
        self.assertIn('"active_training_block"', prompt)
        self.assertIn('"sets": 17', prompt)
        self.assertIn('"label": "Strength before cardio"', prompt)
        self.assertIn('"label": "Low readiness"', prompt)
        self.assertIn('"triggered": true', prompt)
        self.assertIn('"body_mode": {"mode": "cut"', prompt)
