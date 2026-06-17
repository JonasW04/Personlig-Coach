import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach.models import TrainingBlock
from coach.web import app as web_app


class TestTrainingBlocks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        TrainingBlock.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self.session_patch = patch.object(web_app, "SessionLocal", self.session_factory)
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    async def test_create_generates_renderer_shape_and_deactivates_previous(self):
        first = await web_app.create_block(
            web_app.BlockCreate(
                name="First", goal="hypertrophy", start_date=date(2026, 6, 1), weeks=4
            )
        )
        first_id = first["blocks"][0]["id"]
        response = await web_app.create_block(
            web_app.BlockCreate(
                name="Strength block", goal="strength", start_date=date.today(), weeks=6
            )
        )

        self.assertEqual("Strength block", response["active"]["name"])
        self.assertEqual(
            {"name", "sub", "weekIndex", "weekCount", "focus", "deload", "phases"},
            set(response["active"]),
        )
        self.assertEqual(6, len(response["active"]["phases"]))
        self.assertEqual("deload", response["active"]["phases"][-1]["state"])
        self.assertFalse(next(row for row in response["blocks"] if row["id"] == first_id)["active"])

    async def test_patch_rebuilds_phases_and_can_activate_block(self):
        await web_app.create_block(
            web_app.BlockCreate(
                name="Block", goal="general", start_date=date.today(), weeks=6
            )
        )
        with self.session_factory() as session:
            block = session.execute(select(TrainingBlock)).scalars().one()
            block_id = block.id

        response = await web_app.update_block(
            block_id,
            web_app.BlockUpdate(weeks=4, include_deload=False, focus="Updated focus."),
        )

        self.assertEqual(4, response["active"]["weekCount"])
        self.assertEqual("Updated focus.", response["active"]["focus"])
        self.assertNotEqual("deload", response["active"]["phases"][-1]["state"])
        self.assertEqual("No deload week is scheduled in this block.", response["active"]["deload"])
        with self.session_factory() as session:
            saved = session.get(TrainingBlock, block_id)
        self.assertEqual(22, json.loads(saved.phases_json)[-1]["sets"])


if __name__ == "__main__":
    unittest.main()
