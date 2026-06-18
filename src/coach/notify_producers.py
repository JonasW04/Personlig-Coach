"""Event producers that turn plan/recovery state into notifications.

Each producer builds human-readable copy from existing data and hands it to
``notify.send`` with the matching preference key, so the user's notification
preferences (and quiet hours) gate delivery. Producers are deliberately
idempotent-by-schedule: the scheduler fires each one once per local day, and
the plan-drift check looks back at a single fully-synced day, so no session is
reported more than once.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from coach import notify, rules
from coach.config import settings
from coach.db import SessionLocal
from coach.models import PlanDay, RecoveryRule
from coach.web import stats

log = logging.getLogger("coach.notify_producers")


def _local_today() -> date:
    return datetime.now(ZoneInfo(settings.scheduler_timezone)).date()


def _plan_day(day: date) -> PlanDay | None:
    with SessionLocal() as session:
        return session.execute(
            select(PlanDay).where(PlanDay.date == day)
        ).scalars().first()


def _payload(day: PlanDay) -> dict:
    try:
        data = json.loads(day.payload_json or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------- daily plan
def _daily_plan_body(day: PlanDay) -> str:
    payload = _payload(day)
    weekday = day.date.strftime("%A")
    lines = [f"{weekday} · {day.title}"]
    if day.kind == "strength":
        exercises = payload.get("exercises") or []
        names = [str(ex.get("name")) for ex in exercises if isinstance(ex, dict) and ex.get("name")]
        if names:
            lines.append(f"{len(names)} exercises: " + ", ".join(names[:6]) + ("…" if len(names) > 6 else ""))
        lines.append("Push the routine to Hevy from Coach when you're ready to train.")
    elif day.kind == "cardio":
        bits = []
        if payload.get("duration_minutes"):
            bits.append(f"{payload['duration_minutes']} min")
        if payload.get("distance_km"):
            bits.append(f"{payload['distance_km']} km")
        if payload.get("zone"):
            bits.append(str(payload["zone"]))
        if bits:
            lines.append(" · ".join(bits))
        lines.append("Schedule it to your Garmin from Coach.")
    else:
        lines.append("Rest day — keep steps up and recover well.")
    return "\n".join(lines)


def send_daily_plan(today: date | None = None) -> list[str]:
    """Morning nudge with today's planned session. Returns channels used."""
    today = today or _local_today()
    day = _plan_day(today)
    if day is None:
        log.info("daily plan: no planned session for %s", today.isoformat())
        return []
    subject = f"Today · {day.title}"
    used = notify.send(subject, _daily_plan_body(day), preference_key="dailyPlan")
    if used:
        log.info("daily plan notification sent via %s", used)
    return used


# ----------------------------------------------------------------- recovery alerts
def _latest_health_day() -> dict | None:
    days = stats.health().get("days", [])
    return days[-1] if days else None


def _enabled_rules() -> list[RecoveryRule]:
    with SessionLocal() as session:
        return list(
            session.execute(
                select(RecoveryRule)
                .where(RecoveryRule.enabled.is_(True))
                .order_by(RecoveryRule.order_index)
            ).scalars()
        )


_LATEST_HEALTH = object()


def check_recovery_alerts(health_day: dict | None | object = _LATEST_HEALTH) -> list[str]:
    """Alert when enabled recovery guardrails are triggered by today's recovery."""
    if health_day is _LATEST_HEALTH:
        health_day = _latest_health_day()
    if not health_day:
        return []
    triggered = rules.evaluate(_enabled_rules(), health_day)
    if not triggered:
        return []
    count = len(triggered)
    subject = f"Recovery alert · {count} guardrail{'s' if count > 1 else ''} triggered"
    body = "\n".join(rules.message(rule) for rule in triggered)
    used = notify.send(subject, body, preference_key="recoveryAlerts", urgent=True)
    if used:
        log.info("recovery alert notification sent via %s", used)
    return used


# --------------------------------------------------------------------- plan drift
def _drift_status(day: PlanDay, actual: dict | None) -> str:
    """Mirror the Plan-vs-Actual screen: ON PLAN / MISSED / REPLACED for a past day."""
    actual = actual or {}
    has_actual = bool(actual.get("strength") or actual.get("cardio"))
    if day.kind == "rest":
        return "REPLACED" if has_actual else "ON PLAN"
    if actual.get(day.kind):
        return "ON PLAN"
    return "REPLACED" if has_actual else "MISSED"


def check_plan_drift(target: date | None = None) -> list[str]:
    """Report when the previous day's planned session was missed or swapped.

    Defaults to *yesterday*, which the nightly sync has fully reconciled, so each
    day is evaluated exactly once and never re-alerted.
    """
    target = target or (_local_today() - timedelta(days=1))
    day = _plan_day(target)
    if day is None:
        return []
    iso = target.isoformat()
    actual_days = {d["date"]: d for d in stats.activity(iso, iso).get("days", [])}
    status = _drift_status(day, actual_days.get(iso))
    if status == "ON PLAN":
        return []
    weekday = target.strftime("%A")
    if status == "MISSED":
        detail = f"Planned {day.title} wasn't completed."
    else:
        detail = f"A different session replaced the planned {day.title}."
    subject = f"Plan drift · {weekday}"
    body = (
        f"{detail}\nYour next re-plan can account for the change — open Coach to "
        f"re-plan from today if you want to adjust."
    )
    used = notify.send(subject, body, preference_key="planDrift")
    if used:
        log.info("plan drift notification sent via %s", used)
    return used


# ------------------------------------------------------------------------------ cli
def main() -> None:
    """``coach-notify`` — run a producer (or a test ping) from the command line."""
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Fire a Coach notification now.")
    parser.add_argument(
        "kind",
        nargs="?",
        default="ping",
        choices=["ping", "daily-plan", "recovery", "drift"],
        help="Which notification to send (default: ping).",
    )
    args = parser.parse_args()

    if args.kind == "ping":
        used = notify.send(
            "Coach test notification", "If you can read this, delivery works."
        )
    elif args.kind == "daily-plan":
        used = send_daily_plan()
    elif args.kind == "recovery":
        used = check_recovery_alerts()
    else:
        used = check_plan_drift()

    print(f"channels used: {used or '(none — nothing sent)'}")
    print(f"channels configured: {notify.channels_configured() or '(none configured)'}")
