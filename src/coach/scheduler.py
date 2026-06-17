"""In-process scheduler for the always-on web service: nightly sync, daily readiness,
weekly review. Enable with RUN_SCHEDULER=true (and set SCHEDULER_TIMEZONE).

This is an alternative to OS cron / separate Railway cron services — one process does
everything. Times are in SCHEDULER_TIMEZONE.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from coach import reports
from coach.config import settings
from coach.db import SessionLocal
from coach.integrations import garmin
from coach.models import GarminDaily, Report
from coach.sync import main as sync_main

log = logging.getLogger("coach.scheduler")
readiness_lock = asyncio.Lock()


async def _sync_job() -> None:
    log.info("scheduled sync starting")
    await asyncio.to_thread(sync_main)
    log.info("scheduled sync done")


def _scheduler_tz() -> ZoneInfo:
    return ZoneInfo(settings.scheduler_timezone)


def _now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def _has_sleep_data_for_date(day) -> bool:
    with SessionLocal() as s:
        row = s.get(GarminDaily, day)
        if row is None:
            return False
        if row.sleep_score is not None:
            return True
        return any(
            value is not None and value > 0
            for value in (
                row.sleep_seconds,
                row.deep_sleep_seconds,
                row.light_sleep_seconds,
                row.rem_sleep_seconds,
            )
        )


def _has_today_readiness_report(day, tz: ZoneInfo) -> bool:
    """Avoid duplicate scheduled readiness reports for one local day."""
    with SessionLocal() as s:
        rows = (
            s.execute(
                select(Report)
                .where(Report.kind == "readiness")
                .order_by(Report.created_at.desc())
                .limit(10)
            )
            .scalars()
            .all()
        )
    for row in rows:
        created = row.created_at
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created.astimezone(tz).date() == day:
            return True
    return False


def _sync_for_morning_readiness() -> int:
    """Refresh Garmin's recent health window so finalized sleep can arrive."""
    if not garmin.is_authorized():
        log.info("Garmin is not authorized; morning readiness will wait until cutoff")
        return 0
    days = max(1, int(settings.readiness_garmin_sync_days))
    return garmin.sync(days=days)


async def _readiness_job() -> None:
    """Generate readiness after sleep arrives, or at the configured cutoff."""
    if readiness_lock.locked():
        log.info("scheduled readiness skipped because another run is active")
        return

    async with readiness_lock:
        tz = _scheduler_tz()
        now = _now(tz)
        day = now.date()
        if await asyncio.to_thread(_has_today_readiness_report, day, tz):
            log.info("scheduled readiness skipped; today's report already exists")
            return

        log.info("morning readiness check starting")
        try:
            stored = await asyncio.to_thread(_sync_for_morning_readiness)
            log.info("morning readiness Garmin sync stored %s days", stored)
        except Exception:  # noqa: BLE001 - cutoff still sends a report later
            log.exception("morning readiness Garmin sync failed")

        sleep_ready = await asyncio.to_thread(_has_sleep_data_for_date, day)
        cutoff_reached = _now(tz).hour >= int(settings.readiness_cutoff_hour)
        if not sleep_ready and not cutoff_reached:
            log.info(
                "morning readiness waiting for sleep data until %02d:00",
                settings.readiness_cutoff_hour,
            )
            return

        reason = "sleep data is available" if sleep_ready else "cutoff reached"
        log.info("scheduled readiness generating because %s", reason)
        await reports.generate_and_store("readiness")
        log.info("scheduled readiness done")


async def _review_job() -> None:
    log.info("scheduled weekly review starting")
    await reports.generate_and_store("weekly")
    log.info("scheduled weekly review done")


def build_scheduler() -> AsyncIOScheduler:
    tz = settings.scheduler_timezone
    sched = AsyncIOScheduler(timezone=tz)
    sched.add_job(_sync_job, CronTrigger(hour=3, minute=0, timezone=tz), id="sync")
    start_hour = max(0, min(23, int(settings.readiness_start_hour)))
    cutoff_hour = max(0, min(23, int(settings.readiness_cutoff_hour)))
    poll_minutes = max(5, min(60, int(settings.readiness_poll_minutes)))
    if start_hour < cutoff_hour:
        sched.add_job(
            _readiness_job,
            CronTrigger(
                hour=f"{start_hour}-{cutoff_hour - 1}",
                minute=f"*/{poll_minutes}",
                timezone=tz,
            ),
            id="readiness-watch",
        )
    sched.add_job(
        _readiness_job,
        CronTrigger(hour=cutoff_hour, minute=0, timezone=tz),
        id="readiness-cutoff",
    )
    sched.add_job(
        _review_job, CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=tz), id="weekly"
    )
    # TODO(Step 3 follow-up): dailyPlan and planDrift producers should call
    # notify.send(..., preference_key=<key>) once plan/drift events are defined.
    # TODO(Step 6 follow-up): a rules-triggered recoveryAlerts producer should call
    # notify.send(..., preference_key="recoveryAlerts", urgent=True).
    return sched
