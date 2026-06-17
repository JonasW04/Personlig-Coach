import os
import sys
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach import body_mode
from coach.models import CoachProfile
from coach.web import app as web_app


class TestBodyMode(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        CoachProfile.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self.session_patch = patch.object(body_mode, "SessionLocal", self.session_factory)
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    def test_mode_copy_and_week_index_are_derived_from_start_date(self):
        changed_at = datetime(2026, 6, 1, 9, tzinfo=timezone.utc)
        body_mode.set_body_mode("recomp", changed_at)

        state = body_mode.get_body_mode(date(2026, 6, 17))

        self.assertEqual("recomp", state["mode"])
        self.assertEqual(3, state["weekIndex"])
        self.assertEqual(8, state["weekCount"])
        self.assertEqual(
            "Hold weight steady. Maintain volume, recover well, let composition shift.",
            state["descriptor"],
        )
        self.assertEqual(["cut", "bulk", "recomp", "perf"], [item["key"] for item in state["modes"]])

    async def test_get_and_put_return_renderer_payload_and_reset_to_week_one(self):
        default = await web_app.get_body_mode()
        self.assertEqual("cut", default["mode"])

        with patch.object(
            body_mode,
            "_utcnow",
            return_value=datetime(2026, 6, 17, 12, tzinfo=timezone.utc),
        ):
            updated = await web_app.update_body_mode(web_app.BodyModeUpdate(mode="perf"))

        self.assertEqual("perf", updated["mode"])
        self.assertEqual(1, updated["weekIndex"])
        self.assertIn("Train for output", updated["descriptor"])
        with self.session_factory() as session:
            saved = session.get(CoachProfile, 1)
        self.assertEqual("perf", saved.body_mode)
        self.assertEqual(8, saved.body_mode_week_count)


if __name__ == "__main__":
    unittest.main()
