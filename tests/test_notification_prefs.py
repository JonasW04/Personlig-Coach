import os
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach import notification_prefs
from coach.models import NotificationPref
from coach.web import app as web_app


class TestNotificationPrefs(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        NotificationPref.__table__.create(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)
        self.session_patch = patch.object(
            notification_prefs, "SessionLocal", self.session_factory
        )
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    async def test_defaults_preserve_renderer_order_and_put_persists_by_key(self):
        response = await web_app.get_notification_prefs()
        self.assertEqual(
            ["dailyPlan", "recoveryAlerts", "planDrift", "weeklyReview", "quietHours"],
            [item["key"] for item in response["prefs"]],
        )

        updated = await web_app.update_notification_pref(
            web_app.NotificationPrefUpdate(key="weeklyReview", enabled=False)
        )

        self.assertFalse(updated["prefs"][3]["enabled"])
        with self.session_factory() as session:
            row = session.get(NotificationPref, "weeklyReview")
        self.assertFalse(row.enabled)
        self.assertFalse(notification_prefs.is_enabled("weeklyReview"))


if __name__ == "__main__":
    unittest.main()
