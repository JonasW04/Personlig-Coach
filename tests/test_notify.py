import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure src/ is in the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach.notify import (
    email_configured,
    web_push_configured,
    send_email,
    channels_configured,
    _push_body,
    send_web_push,
    send,
)
from coach.models import PushSubscription


# Define a WebPushException class for mocking
class MockWebPushException(Exception):
    def __init__(self, message=None, response=None):
        super().__init__(message)
        self.response = response


class TestNotification(unittest.TestCase):
    def setUp(self):
        self.preference_patch = patch(
            "coach.notify.notification_prefs.is_enabled", return_value=False
        )
        self.preference_enabled = self.preference_patch.start()

    def tearDown(self):
        self.preference_patch.stop()

    @patch("coach.notify.settings")
    def test_email_configured(self, mock_settings):
        # All set
        mock_settings.smtp_host = "smtp.example.com"
        mock_settings.email_from = "from@example.com"
        mock_settings.email_to = "to@example.com"
        self.assertTrue(email_configured())

        # One missing
        mock_settings.smtp_host = ""
        self.assertFalse(email_configured())

    @patch("coach.notify.settings")
    def test_web_push_configured(self, mock_settings):
        # All set
        mock_settings.web_push_vapid_public_key = "pubkey"
        mock_settings.web_push_vapid_private_key = "privkey"
        mock_settings.web_push_vapid_subject = "mailto:me@example.com"
        self.assertTrue(web_push_configured())

        # One missing
        mock_settings.web_push_vapid_private_key = ""
        self.assertFalse(web_push_configured())

    @patch("coach.notify.email_configured")
    @patch("coach.notify.notion.notion_configured")
    @patch("coach.notify.web_push_configured")
    def test_channels_configured(self, mock_web_push, mock_notion, mock_email):
        # All enabled
        mock_email.return_value = True
        mock_notion.return_value = True
        mock_web_push.return_value = True
        self.assertEqual(channels_configured(), ["email", "notion", "web push"])

        # Some enabled
        mock_email.return_value = False
        mock_notion.return_value = True
        mock_web_push.return_value = False
        self.assertEqual(channels_configured(), ["notion"])

        # None enabled
        mock_notion.return_value = False
        self.assertEqual(channels_configured(), [])

    def test_push_body_extraction(self):
        # Empty/whitespace test
        self.assertEqual(_push_body(""), "Open Coach to read the latest report.")
        self.assertEqual(_push_body("\n\n"), "Open Coach to read the latest report.")
        self.assertEqual(_push_body(" -*#\t"), "Open Coach to read the latest report.")

        # Basic stripping test
        self.assertEqual(_push_body("Hello world"), "Hello world")
        self.assertEqual(_push_body("  - Hello world  "), "Hello world")
        self.assertEqual(_push_body("### Hello world"), "Hello world")

        # Multi-line extraction
        body = "\n\n  * First line\nSecond line"
        self.assertEqual(_push_body(body), "First line")

        # Truncation test
        long_line = "a" * 200
        self.assertEqual(_push_body(long_line), "a" * 180)

    @patch("coach.notify.email_configured", return_value=False)
    def test_send_email_not_configured(self, mock_configured):
        with self.assertRaises(RuntimeError):
            send_email("Subject", "Body")

    @patch("coach.notify.smtplib.SMTP")
    @patch("coach.notify.settings")
    @patch("coach.notify.email_configured", return_value=True)
    def test_send_email_success(self, mock_configured, mock_settings, mock_smtp_class):
        mock_settings.smtp_host = "smtp.example.com"
        mock_settings.smtp_port = 587
        mock_settings.smtp_user = "user@example.com"
        mock_settings.smtp_password = "password"
        mock_settings.email_from = "from@example.com"
        mock_settings.email_to = "to@example.com"

        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp

        send_email("Test Subject", "Test Body")

        # Verify SMTP connection params
        mock_smtp_class.assert_called_once_with("smtp.example.com", 587, timeout=30)
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("user@example.com", "password")

        # Verify message content
        mock_smtp.send_message.assert_called_once()
        sent_msg = mock_smtp.send_message.call_args[0][0]
        self.assertEqual(sent_msg["Subject"], "Test Subject")
        self.assertEqual(sent_msg["From"], "from@example.com")
        self.assertEqual(sent_msg["To"], "to@example.com")
        self.assertEqual(sent_msg.get_content().strip(), "Test Body")

    @patch("coach.notify.smtplib.SMTP")
    @patch("coach.notify.settings")
    @patch("coach.notify.email_configured", return_value=True)
    def test_send_email_no_login(self, mock_configured, mock_settings, mock_smtp_class):
        mock_settings.smtp_host = "smtp.example.com"
        mock_settings.smtp_port = 587
        mock_settings.smtp_user = ""
        mock_settings.smtp_password = ""
        mock_settings.email_from = "from@example.com"
        mock_settings.email_to = "to@example.com"

        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp

        send_email("Test Subject", "Test Body")

        mock_smtp.login.assert_not_called()
        mock_smtp.send_message.assert_called_once()

    @patch("coach.notify.web_push_configured", return_value=False)
    def test_send_web_push_not_configured(self, mock_configured):
        self.assertEqual(send_web_push("Subject", "Body"), 0)

    @patch("coach.notify.web_push_configured", return_value=True)
    def test_send_web_push_no_pywebpush_installed(self, mock_configured):
        with patch.dict(sys.modules, {"pywebpush": None}):
            self.assertEqual(send_web_push("Subject", "Body"), 0)

    # Mock the dynamic import of pywebpush
    mock_webpush_func = MagicMock()

    @patch.dict(
        sys.modules,
        {
            "pywebpush": MagicMock(
                WebPushException=MockWebPushException, webpush=mock_webpush_func
            )
        },
    )
    @patch("coach.notify.web_push_configured", return_value=True)
    @patch("coach.notify.SessionLocal")
    @patch("coach.notify.settings")
    def test_send_web_push_success(
        self, mock_settings, mock_session_local, mock_configured
    ):
        self.mock_webpush_func.reset_mock()
        self.mock_webpush_func.side_effect = None
        mock_settings.web_push_vapid_private_key = "private_key"
        mock_settings.web_push_vapid_subject = "mailto:subject"

        # Mock push subscriptions
        sub1 = PushSubscription(endpoint="https://example.com/sub1", p256dh="k1", auth="a1")
        sub2 = PushSubscription(endpoint="https://example.com/sub2", p256dh="k2", auth="a2")

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = [sub1, sub2]
        mock_session_local.return_value.__enter__.return_value = mock_session

        count = send_web_push("Test Subject", "Test Body")

        self.assertEqual(count, 2)
        self.assertEqual(self.mock_webpush_func.call_count, 2)

        expected_payload = {
            "title": "Test Subject",
            "body": "Test Body",
            "url": "/#reports",
            "tag": "coach-report",
        }
        first_call = self.mock_webpush_func.call_args_list[0]
        self.assertEqual(
            first_call.kwargs["subscription_info"],
            {"endpoint": "https://example.com/sub1", "keys": {"p256dh": "k1", "auth": "a1"}},
        )
        self.assertEqual(json.loads(first_call.kwargs["data"]), expected_payload)
        self.assertEqual(first_call.kwargs["vapid_private_key"], "private_key")
        self.assertEqual(first_call.kwargs["vapid_claims"], {"sub": "mailto:subject"})

        mock_session.commit.assert_called_once()
        mock_session.delete.assert_not_called()

    @patch.dict(
        sys.modules,
        {
            "pywebpush": MagicMock(
                WebPushException=MockWebPushException, webpush=mock_webpush_func
            )
        },
    )
    @patch("coach.notify.web_push_configured", return_value=True)
    @patch("coach.notify.SessionLocal")
    @patch("coach.notify.settings")
    def test_send_web_push_expired_subscriptions(
        self, mock_settings, mock_session_local, mock_configured
    ):
        self.mock_webpush_func.reset_mock()
        mock_settings.web_push_vapid_private_key = "private_key"
        mock_settings.web_push_vapid_subject = "mailto:subject"

        sub1 = PushSubscription(endpoint="https://example.com/sub1", p256dh="k1", auth="a1")
        sub2 = PushSubscription(endpoint="https://example.com/sub2", p256dh="k2", auth="a2")

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = [sub1, sub2]
        mock_session_local.return_value.__enter__.return_value = mock_session

        # First call fails with 410, second succeeds
        mock_response = MagicMock()
        mock_response.status_code = 410

        def side_effect(*args, **kwargs):
            if kwargs["subscription_info"]["endpoint"] == "https://example.com/sub1":
                raise MockWebPushException("Expired", response=mock_response)
            return None

        self.mock_webpush_func.side_effect = side_effect

        count = send_web_push("Test Subject", "Test Body")

        # Only one subscription succeeded
        self.assertEqual(count, 1)

        # Expired subscription must be deleted, second must not
        mock_session.delete.assert_called_once_with(sub1)
        mock_session.commit.assert_called_once()

    @patch.dict(
        sys.modules,
        {
            "pywebpush": MagicMock(
                WebPushException=MockWebPushException, webpush=mock_webpush_func
            )
        },
    )
    @patch("coach.notify.web_push_configured", return_value=True)
    @patch("coach.notify.SessionLocal")
    @patch("coach.notify.settings")
    def test_send_web_push_other_errors(
        self, mock_settings, mock_session_local, mock_configured
    ):
        self.mock_webpush_func.reset_mock()
        mock_settings.web_push_vapid_private_key = "private_key"
        mock_settings.web_push_vapid_subject = "mailto:subject"

        sub = PushSubscription(endpoint="https://example.com/sub", p256dh="k", auth="a")

        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = [sub]
        mock_session_local.return_value.__enter__.return_value = mock_session

        # Webpush raises a 500 error
        mock_response = MagicMock()
        mock_response.status_code = 500
        self.mock_webpush_func.side_effect = MockWebPushException(
            "Server error", response=mock_response
        )

        count = send_web_push("Test Subject", "Test Body")

        self.assertEqual(count, 0)
        # Should not delete the subscription
        mock_session.delete.assert_not_called()
        mock_session.commit.assert_called_once()

    @patch("coach.notify.email_configured")
    @patch("coach.notify.send_email")
    @patch("coach.notify.notion")
    @patch("coach.notify.send_web_push")
    @patch("coach.notify.settings")
    def test_send_all_configured(
        self,
        mock_settings,
        mock_send_web_push,
        mock_notion,
        mock_send_email,
        mock_email_configured,
    ):
        mock_email_configured.return_value = True
        mock_notion.notion_configured.return_value = True
        mock_send_web_push.return_value = 2
        mock_settings.email_to = "user@example.com"

        channels = send("Subject", "Body")

        mock_send_email.assert_called_once_with("Subject", "Body")
        mock_notion.create_page.assert_called_once_with("Subject", "Body")
        mock_send_web_push.assert_called_once_with("Subject", "Body")

        self.assertEqual(channels, ["email:user@example.com", "notion", "web_push:2"])

    @patch("coach.notify.email_configured")
    @patch("coach.notify.send_email")
    @patch("coach.notify.notion")
    @patch("coach.notify.send_web_push")
    def test_send_none_configured(
        self, mock_send_web_push, mock_notion, mock_send_email, mock_email_configured
    ):
        mock_email_configured.return_value = False
        mock_notion.notion_configured.return_value = False
        mock_send_web_push.return_value = 0

        channels = send("Subject", "Body")

        mock_send_email.assert_not_called()
        mock_notion.create_page.assert_not_called()
        mock_send_web_push.assert_called_once_with("Subject", "Body")

        self.assertEqual(channels, [])

    @patch("coach.notify.send_email")
    @patch("coach.notify.email_configured", return_value=True)
    def test_preference_can_suppress_delivery(self, mock_configured, mock_send_email):
        self.preference_enabled.return_value = False

        channels = send("Weekly", "Body", preference_key="weeklyReview")

        self.assertEqual([], channels)
        mock_send_email.assert_not_called()

    @patch("coach.notify.send_email")
    @patch("coach.notify.email_configured", return_value=True)
    @patch("coach.notify._quiet_hours_active", return_value=True)
    def test_quiet_hours_suppress_only_non_urgent_delivery(
        self, mock_quiet, mock_configured, mock_send_email
    ):
        self.preference_enabled.side_effect = lambda key: key == "quietHours"

        self.assertEqual([], send("Routine", "Body"))
        mock_send_email.assert_not_called()
        send("Urgent", "Body", urgent=True)

        mock_send_email.assert_called_once_with("Urgent", "Body")
