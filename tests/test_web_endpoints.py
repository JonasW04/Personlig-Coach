"""HTTP-layer tests for the FastAPI app.

These exercise routing, auth gating, request validation, status-code/error
mapping, the plan-generation lock, and response shapes — the layer the unit
tests below it can't reach. The service layer and DB are mocked so the tests
stay hermetic (no Postgres, no LLM). The TestClient is intentionally NOT used as
a context manager, so the DB-initializing lifespan never runs.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from fastapi.testclient import TestClient

from coach.web import app as appmod


def _client(authed: bool = True) -> TestClient:
    appmod.settings.app_username = "me"
    appmod.settings.app_password = "secret"
    client = TestClient(appmod.app)
    if authed:
        resp = client.post(
            "/login",
            data={"username": "me", "password": "secret"},
            follow_redirects=False,
        )
        assert resp.status_code == 302, resp.status_code
    return client


class TestAuthGating(unittest.TestCase):
    def test_api_requires_auth(self):
        client = _client(authed=False)
        self.assertEqual(client.get("/api/me").status_code, 401)
        self.assertEqual(client.get("/api/body-mode").status_code, 401)

    def test_healthz_is_public(self):
        client = _client(authed=False)
        resp = client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"ok": True})

    def test_login_then_me(self):
        client = _client()
        resp = client.get("/api/me")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"username": "me"})


class TestBodyMode(unittest.TestCase):
    @patch("coach.web.app.body_mode.get_body_mode")
    def test_get_body_mode(self, mock_get):
        mock_get.return_value = {"mode": "cut", "weekIndex": 2}
        resp = _client().get("/api/body-mode")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["mode"], "cut")

    @patch("coach.web.app.body_mode.set_body_mode")
    def test_put_body_mode_valid(self, mock_set):
        mock_set.return_value = {"mode": "bulk"}
        resp = _client().put("/api/body-mode", json={"mode": "bulk"})
        self.assertEqual(resp.status_code, 200)
        mock_set.assert_called_once_with("bulk")

    def test_put_body_mode_invalid_returns_422(self):
        resp = _client().put("/api/body-mode", json={"mode": "shred"})
        self.assertEqual(resp.status_code, 422)


class TestPlanEndpoints(unittest.TestCase):
    @patch("coach.web.app.plan.generate_week")
    def test_generate_maps_failure_to_502(self, mock_gen):
        async def _raise(_week):
            raise appmod.plan.PlanGenerationError("Coach could not generate a plan")

        mock_gen.side_effect = _raise
        resp = _client().post("/api/plan/generate", json={"week_start": "2026-06-15"})
        self.assertEqual(resp.status_code, 502)
        self.assertIn("generate", resp.json()["detail"].lower())

    @patch("coach.web.app.plan.generate_week")
    def test_generate_success_returns_week(self, mock_gen):
        async def _ok(_week):
            return []

        mock_gen.side_effect = _ok
        resp = _client().post("/api/plan/generate", json={"week_start": "2026-06-15"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["days"], [])

    def test_generate_validation_error(self):
        resp = _client().post("/api/plan/generate", json={})
        self.assertEqual(resp.status_code, 422)

    def test_generate_busy_returns_202(self):
        busy = MagicMock()
        busy.locked.return_value = True
        with patch("coach.web.app.plan_lock", busy):
            resp = _client().post("/api/plan/generate", json={"week_start": "2026-06-15"})
        self.assertEqual(resp.status_code, 202)
        self.assertTrue(resp.json()["running"])

    @patch("coach.web.app.SessionLocal")
    def test_get_plan_day_missing_returns_404(self, mock_session):
        session = MagicMock()
        session.execute.return_value.scalars.return_value.first.return_value = None
        mock_session.return_value.__enter__.return_value = session
        resp = _client().get("/api/plan/day/2026-06-18")
        self.assertEqual(resp.status_code, 404)


class TestReportEndpoints(unittest.TestCase):
    def test_report_json_exposes_daily_score_and_workflow_status(self):
        from datetime import date

        report = appmod.Report(
            id=1,
            kind="readiness",
            content="Verdict: Train",
            review_date=date(2026, 6, 18),
            readiness_score=82,
            workflow_status="complete",
        )
        payload = appmod._report_json(report)
        self.assertEqual(82, payload["readiness_score"])
        self.assertEqual("2026-06-18", payload["review_date"])
        self.assertEqual("complete", payload["workflow_status"])

    @patch("coach.reports.generate_and_store")
    def test_generate_maps_model_failure_to_502(self, mock_gen):
        from coach import reports

        async def _raise(_kind):
            raise reports.ReportGenerationError("the model may be busy")

        mock_gen.side_effect = _raise
        resp = _client().post("/api/reports/generate", json={"kind": "readiness"})
        self.assertEqual(resp.status_code, 502)
        self.assertIn("busy", resp.json()["detail"].lower())

    def test_generate_invalid_kind_returns_400(self):
        resp = _client().post("/api/reports/generate", json={"kind": "bogus"})
        self.assertEqual(resp.status_code, 400)


class TestRulesValidation(unittest.TestCase):
    def test_invalid_action_returns_422(self):
        resp = _client().post(
            "/api/rules",
            json={"label": "x", "description": "y", "action": "explode"},
        )
        self.assertEqual(resp.status_code, 422)


class TestNotifications(unittest.TestCase):
    @patch("coach.notify.channels_configured", return_value=["email"])
    @patch("coach.notify.send", return_value=["email:me"])
    def test_ping_sends_and_reports_channels(self, mock_send, mock_conf):
        resp = _client().post("/api/notifications/test", json={"kind": "ping"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["channels"], ["email:me"])
        mock_send.assert_called_once()

    @patch("coach.notify.channels_configured", return_value=[])
    @patch("coach.notify_producers.send_daily_plan", return_value=[])
    def test_producer_kind_runs_producer(self, mock_producer, mock_conf):
        resp = _client().post("/api/notifications/test", json={"kind": "dailyPlan"})
        self.assertEqual(resp.status_code, 200)
        mock_producer.assert_called_once()

    def test_invalid_kind_returns_422(self):
        resp = _client().post("/api/notifications/test", json={"kind": "bogus"})
        self.assertEqual(resp.status_code, 422)

    @patch("coach.web.app.notification_prefs.list_preferences")
    def test_get_prefs(self, mock_list):
        mock_list.return_value = [{"key": "dailyPlan", "enabled": True}]
        resp = _client().get("/api/notification-prefs")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["prefs"][0]["key"], "dailyPlan")


class TestSchedulerStatus(unittest.TestCase):
    def test_status_shape(self):
        resp = _client().get("/api/scheduler/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("enabled", body)
        self.assertIn("jobs", body)
        self.assertIsInstance(body["jobs"], list)


if __name__ == "__main__":
    unittest.main()
