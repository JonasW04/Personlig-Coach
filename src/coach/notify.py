"""Notification dispatch. Fans a report out to every configured channel (email, Notion).

Email is over SMTP (STARTTLS); for Gmail create an App Password
(https://myaccount.google.com/apppasswords) and use it as SMTP_PASSWORD.
Notion config + setup lives in coach.integrations.notion.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from coach.config import settings
from coach.integrations import notion


def email_configured() -> bool:
    return bool(settings.smtp_host and settings.email_from and settings.email_to)


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
    return used


def send(subject: str, body: str) -> list[str]:
    """Deliver to every configured channel. Returns the channels used."""
    used: list[str] = []
    if email_configured():
        send_email(subject, body)
        used.append(f"email:{settings.email_to}")
    if notion.notion_configured():
        notion.create_page(subject, body)
        used.append("notion")
    return used
