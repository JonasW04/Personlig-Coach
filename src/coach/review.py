"""Automated weekly review. Run via `coach-review`.

Runs the coordinator on the review model to produce a full training review across
strength, cardio and body composition. Persisted to the DB and sent to notify channels.
Schedule weekly on the VPS after the nightly sync, e.g. Sunday evening:
    0 18 * * 0 cd /opt/coach && .venv/bin/coach-review >> /var/log/coach-review.log 2>&1
"""
from __future__ import annotations

import asyncio

from coach import reports
from coach.notify import channels_configured


def main() -> None:
    report = asyncio.run(reports.generate_and_store("weekly"))
    print(report.content)
    used = channels_configured()
    print(f"\n[saved to DB; sent via {', '.join(used) or 'no channels — printed only'}]")


if __name__ == "__main__":
    main()
