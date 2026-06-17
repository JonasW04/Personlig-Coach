"""Notification dispatch. Fans a report out to every configured channel (email, Notion).

Email is over SMTP (STARTTLS); for Gmail create an App Password
(https://myaccount.google.com/apppasswords) and use it as SMTP_PASSWORD.
Notion config + setup lives in coach.integrations.notion.
"""
from __future__ import annotations

import json
import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from coach import notification_prefs
from coach.config import settings
from coach.db import SessionLocal
from coach.integrations import notion
from coach.models import PushSubscription

log = logging.getLogger("coach.notify")


def email_configured() -> bool:
    return bool(settings.smtp_host and settings.email_from and settings.email_to)


def web_push_configured() -> bool:
    return bool(
        settings.web_push_vapid_public_key
        and settings.web_push_vapid_private_key
        and settings.web_push_vapid_subject
    )


def send_email(subject: str, body: str) -> None:
    if not email_configured():
        raise RuntimeError(
            "Email not configured. Set SMTP_HOST, EMAIL_FROM and EMAIL_TO in .env."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = settings.email_to
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


def channels_configured() -> list[str]:
    """Names of the channels that will receive notifications."""
    used: list[str] = []
    if email_configured():
        used.append("email")
    if notion.notion_configured():
        used.append("notion")
    if web_push_configured():
        used.append("web push")
    return used


def _push_body(body: str) -> str:
    for line in body.splitlines():
        line = line.strip(" -*#\t")
        if line:
            return line[:180]
    return "Open Coach to read the latest report."


def send_web_push(subject: str, body: str) -> int:
    """Send a report notification to every saved browser subscription."""
    if not web_push_configured():
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        log.warning("pywebpush is not installed; skipping web push notifications")
        return 0

    payload = json.dumps({
        "title": subject,
        "body": _push_body(body),
        "url": "/#reports",
        "tag": "coach-report",
    })
    sent = 0
    with SessionLocal() as s:
        subscriptions = s.query(PushSubscription).all()
        for sub in subscriptions:
            subscription_info = {
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            }
            try:
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=settings.web_push_vapid_private_key,
                    vapid_claims={"sub": settings.web_push_vapid_subject},
                    ttl=60 * 60 * 24,
                )
                sent += 1
            except WebPushException as exc:
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                if status_code in {404, 410}:
                    s.delete(sub)
                    log.info("removed expired web push subscription")
                else:
                    log.warning("web push notification failed: %s", exc)
        s.commit()
    return sent


def _quiet_hours_active(now: datetime | None = None) -> bool:
    local_now = now or datetime.now(ZoneInfo(settings.scheduler_timezone))
    return local_now.hour >= 21 or local_now.hour < 6


def send(
    subject: str,
    body: str,
    preference_key: str | None = None,
    *,
    urgent: bool = False,
) -> list[str]:
    """Deliver to configured channels when its preference permits delivery."""
    if preference_key and not notification_prefs.is_enabled(preference_key):
        log.info("notification delivery disabled by preference %s", preference_key)
        return []
    if (
        not urgent
        and notification_prefs.is_enabled("quietHours")
        and _quiet_hours_active()
    ):
        log.info("non-urgent notification held during quiet hours")
        return []
    used: list[str] = []
    if email_configured():
        send_email(subject, body)
        used.append(f"email:{settings.email_to}")
    if notion.notion_configured():
        notion.create_page(subject, body)
        used.append("notion")
    push_count = send_web_push(subject, body)
    if push_count:
        used.append(f"web_push:{push_count}")
    return used
