import os
import sys
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach import reports
from coach.models import ActionItem, PlanDay, Report


class TestReportWorkflows(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Report.__table__.create(self.engine)
        ActionItem.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self.session_patch = patch.object(reports, "SessionLocal", self.sessions)
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    async def test_weekly_review_builds_following_week_and_stores_its_actions(self):
        review_day = date(2026, 6, 21)
        days = [PlanDay(date=date(2026, 6, 22), kind="rest", title="Rest")]
        delivered = [
            PlanDay(
                date=date(2026, 6, 22),
                kind="rest",
                title="Rest",
                delivery_status="not_applicable",
            )
        ]
        with (
            patch.object(reports, "generate", new=AsyncMock(return_value="Weekly review")),
            patch.object(
                reports,
                "extract_actions",
                new=AsyncMock(
                    return_value=[
                        {"title": "Lift three times", "metric": "weekly_strength_sessions", "target": 3}
                    ]
                ),
            ),
            patch.object(
                reports.plan, "generate_week", new=AsyncMock(return_value=days)
            ) as generate_week,
            patch.object(
                reports.workout_delivery, "publish_days", return_value=delivered
            ) as publish,
            patch.object(reports.notify, "send", return_value=[]),
        ):
            report = await reports.generate_and_store("weekly", for_date=review_day)

        self.assertEqual(date(2026, 6, 22), report.plan_week_start)
        self.assertEqual("complete", report.workflow_status)
        self.assertEqual(date(2026, 6, 22), generate_week.await_args.args[0])
        self.assertIn("Weekly review", generate_week.await_args.kwargs["review_context"]["weekly_review"])
        publish.assert_called_once_with(days)
        with self.sessions() as session:
            action = session.execute(select(ActionItem)).scalars().one()
        self.assertEqual(date(2026, 6, 22), action.week_start)
        self.assertEqual(date(2026, 6, 28), action.due_date)

    async def test_daily_review_stores_score_replans_and_publishes(self):
        review_day = date(2026, 6, 19)
        days = [PlanDay(date=review_day, kind="rest", title="Rest")]
        delivered = [
            PlanDay(
                date=review_day,
                kind="rest",
                title="Rest",
                delivery_status="not_applicable",
            )
        ]
        with (
            patch.object(
                reports.stats,
                "health",
                return_value={
                    "days": [
                        {
                            "sleep_score": 90,
                            "hrv_status": "balanced",
                            "body_battery_high": 80,
                            "resting_hr": 50,
                            "resting_hr_7d_avg": 52,
                            "acwr": 1.0,
                        }
                    ]
                },
            ),
            patch.object(reports, "generate", new=AsyncMock(return_value="Verdict: Train")) as generate,
            patch.object(
                reports.plan, "replan_from", new=AsyncMock(return_value=days)
            ) as replan,
            patch.object(reports.workout_delivery, "publish_days", return_value=delivered),
            patch.object(reports.notify, "send", return_value=[]),
        ):
            report = await reports.generate_and_store("readiness", for_date=review_day)

        self.assertEqual(review_day, report.review_date)
        self.assertGreater(report.readiness_score, 70)
        self.assertEqual(review_day, replan.await_args.args[0])
        self.assertEqual(
            report.readiness_score,
            replan.await_args.kwargs["review_context"]["readiness_score"],
        )
        self.assertIn(
            f"{report.readiness_score}/100",
            generate.await_args.kwargs["prompt_context"],
        )


if __name__ == "__main__":
    unittest.main()
