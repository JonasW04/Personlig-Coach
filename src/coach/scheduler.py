"""In-process scheduler for the always-on web service: nightly sync, daily readiness,
weekly review. Enable with RUN_SCHEDULER=true (and set SCHEDULER_TIMEZONE).

This is an alternative to OS cron / separate Railway cron services — one process does
everything. Times are in SCHEDULER_TIMEZONE.
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from coach import reports
from coach.config import settings
from coach.sync import main as sync_main

log = logging.getLogger("coach.scheduler")


async def _sync_job() -> None:
    log.info("scheduled sync starting")
    await asyncio.to_thread(sync_main)
    log.info("scheduled sync done")


async def _readiness_job() -> None:
    log.info("scheduled readiness starting")
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
    sched.add_job(_readiness_job, CronTrigger(hour=6, minute=0, timezone=tz), id="readiness")
    sched.add_job(
        _review_job, CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=tz), id="weekly"
    )
    return sched
