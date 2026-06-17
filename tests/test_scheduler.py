import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from coach import scheduler


class TestMorningReadinessScheduler(unittest.IsolatedAsyncioTestCase):
    async def test_waits_before_cutoff_when_sleep_is_missing(self):
        now = datetime(2026, 6, 17, 7, 0, tzinfo=timezone.utc)
        with (
            patch("coach.scheduler._scheduler_tz", return_value=timezone.utc),
            patch("coach.scheduler._now", return_value=now),
            patch("coach.scheduler._has_today_readiness_report", return_value=False),
            patch("coach.scheduler._sync_for_morning_readiness") as sync,
            patch("coach.scheduler._has_sleep_data_for_date", return_value=False),
            patch(
                "coach.scheduler.reports.generate_and_store",
                new_callable=AsyncMock,
            ) as generate,
        ):
            await scheduler._readiness_job()

        sync.assert_called_once()
        generate.assert_not_called()

    async def test_generates_before_cutoff_when_sleep_is_present(self):
        now = datetime(2026, 6, 17, 8, 30, tzinfo=timezone.utc)
        with (
            patch("coach.scheduler._scheduler_tz", return_value=timezone.utc),
            patch("coach.scheduler._now", return_value=now),
            patch("coach.scheduler._has_today_readiness_report", return_value=False),
            patch("coach.scheduler._sync_for_morning_readiness"),
            patch("coach.scheduler._has_sleep_data_for_date", return_value=True),
            patch(
                "coach.scheduler.reports.generate_and_store",
                new_callable=AsyncMock,
            ) as generate,
        ):
            await scheduler._readiness_job()

        generate.assert_awaited_once_with("readiness")

    async def test_generates_at_cutoff_even_without_sleep(self):
        now = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)
        with (
            patch("coach.scheduler._scheduler_tz", return_value=timezone.utc),
            patch("coach.scheduler._now", return_value=now),
            patch("coach.scheduler._has_today_readiness_report", return_value=False),
            patch("coach.scheduler._sync_for_morning_readiness"),
            patch("coach.scheduler._has_sleep_data_for_date", return_value=False),
            patch(
                "coach.scheduler.reports.generate_and_store",
                new_callable=AsyncMock,
            ) as generate,
        ):
            await scheduler._readiness_job()

        generate.assert_awaited_once_with("readiness")

    async def test_skips_when_today_readiness_already_exists(self):
        now = datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc)
        with (
            patch("coach.scheduler._scheduler_tz", return_value=timezone.utc),
            patch("coach.scheduler._now", return_value=now),
            patch("coach.scheduler._has_today_readiness_report", return_value=True),
            patch("coach.scheduler._sync_for_morning_readiness") as sync,
            patch(
                "coach.scheduler.reports.generate_and_store",
                new_callable=AsyncMock,
            ) as generate,
        ):
            await scheduler._readiness_job()

        sync.assert_not_called()
        generate.assert_not_called()
