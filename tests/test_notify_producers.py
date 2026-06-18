import json
import os
import sys
import unittest
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach import notify_producers
from coach.models import PlanDay, RecoveryRule


def _plan_day(kind, title, payload, day=date(2026, 6, 18)):
    return PlanDay(date=day, kind=kind, title=title, payload_json=json.dumps(payload))


class TestDailyPlan(unittest.TestCase):
    @patch("coach.notify_producers.notify.send", return_value=["email:me"])
    @patch("coach.notify_producers._plan_day")
    def test_strength_day_lists_exercises(self, mock_day, mock_send):
        mock_day.return_value = _plan_day(
            "strength",
            "Lower A",
            {"exercises": [{"name": "Back Squat"}, {"name": "RDL"}]},
        )
        used = notify_producers.send_daily_plan(date(2026, 6, 18))
        self.assertEqual(used, ["email:me"])
        subject, body = mock_send.call_args.args
        self.assertEqual(mock_send.call_args.kwargs["preference_key"], "dailyPlan")
        self.assertIn("Lower A", subject)
        self.assertIn("Back Squat", body)
        self.assertIn("RDL", body)

    @patch("coach.notify_producers.notify.send")
    @patch("coach.notify_producers._plan_day", return_value=None)
    def test_no_planned_day_sends_nothing(self, mock_day, mock_send):
        self.assertEqual(notify_producers.send_daily_plan(date(2026, 6, 18)), [])
        mock_send.assert_not_called()

    @patch("coach.notify_producers.notify.send", return_value=[])
    @patch("coach.notify_producers._plan_day")
    def test_cardio_day_includes_metrics(self, mock_day, mock_send):
        mock_day.return_value = _plan_day(
            "cardio",
            "Z2 Run",
            {"duration_minutes": 45, "distance_km": 8, "zone": "Zone 2"},
        )
        notify_producers.send_daily_plan(date(2026, 6, 18))
        _, body = mock_send.call_args.args
        self.assertIn("45 min", body)
        self.assertIn("8 km", body)
        self.assertIn("Garmin", body)


class TestRecoveryAlerts(unittest.TestCase):
    def _rule(self):
        return RecoveryRule(
            id=1,
            label="Low readiness",
            description="Readiness is low.",
            condition_json=json.dumps({"metric": "training_readiness", "op": "<", "value": 50}),
            action="rest",
            enabled=True,
            order_index=0,
        )

    @patch("coach.notify_producers.notify.send", return_value=["web_push:1"])
    @patch("coach.notify_producers._enabled_rules")
    def test_triggered_rule_sends_urgent(self, mock_rules, mock_send):
        mock_rules.return_value = [self._rule()]
        used = notify_producers.check_recovery_alerts({"training_readiness": 40})
        self.assertEqual(used, ["web_push:1"])
        self.assertTrue(mock_send.call_args.kwargs["urgent"])
        self.assertEqual(mock_send.call_args.kwargs["preference_key"], "recoveryAlerts")
        _, body = mock_send.call_args.args
        self.assertIn("Low readiness", body)

    @patch("coach.notify_producers.notify.send")
    @patch("coach.notify_producers._enabled_rules")
    def test_untriggered_rule_sends_nothing(self, mock_rules, mock_send):
        mock_rules.return_value = [self._rule()]
        self.assertEqual(notify_producers.check_recovery_alerts({"training_readiness": 80}), [])
        mock_send.assert_not_called()

    @patch("coach.notify_producers.notify.send")
    @patch("coach.notify_producers._enabled_rules")
    def test_no_health_day_sends_nothing(self, mock_rules, mock_send):
        self.assertEqual(notify_producers.check_recovery_alerts(None), [])
        mock_send.assert_not_called()
        mock_rules.assert_not_called()


class TestPlanDrift(unittest.TestCase):
    @patch("coach.notify_producers.notify.send", return_value=["email:me"])
    @patch("coach.notify_producers.stats")
    @patch("coach.notify_producers._plan_day")
    def test_missed_strength_day_alerts(self, mock_day, mock_stats, mock_send):
        target = date(2026, 6, 17)
        mock_day.return_value = _plan_day("strength", "Lower A", {}, day=target)
        mock_stats.activity.return_value = {"days": []}
        used = notify_producers.check_plan_drift(target)
        self.assertEqual(used, ["email:me"])
        self.assertEqual(mock_send.call_args.kwargs["preference_key"], "planDrift")
        _, body = mock_send.call_args.args
        self.assertIn("wasn't completed", body)

    @patch("coach.notify_producers.notify.send")
    @patch("coach.notify_producers.stats")
    @patch("coach.notify_producers._plan_day")
    def test_completed_day_is_silent(self, mock_day, mock_stats, mock_send):
        target = date(2026, 6, 17)
        mock_day.return_value = _plan_day("strength", "Lower A", {}, day=target)
        mock_stats.activity.return_value = {
            "days": [{"date": target.isoformat(), "strength": {"minutes": 60}, "cardio": None}]
        }
        self.assertEqual(notify_producers.check_plan_drift(target), [])
        mock_send.assert_not_called()

    @patch("coach.notify_producers.notify.send", return_value=["email:me"])
    @patch("coach.notify_producers.stats")
    @patch("coach.notify_producers._plan_day")
    def test_replaced_day_alerts(self, mock_day, mock_stats, mock_send):
        target = date(2026, 6, 17)
        mock_day.return_value = _plan_day("strength", "Lower A", {}, day=target)
        mock_stats.activity.return_value = {
            "days": [{"date": target.isoformat(), "strength": None, "cardio": {"km": 5}}]
        }
        notify_producers.check_plan_drift(target)
        _, body = mock_send.call_args.args
        self.assertIn("different session", body)

    @patch("coach.notify_producers.notify.send")
    @patch("coach.notify_producers.stats")
    @patch("coach.notify_producers._plan_day", return_value=None)
    def test_no_plan_for_day_is_silent(self, mock_day, mock_stats, mock_send):
        self.assertEqual(notify_producers.check_plan_drift(date(2026, 6, 17)), [])
        mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
