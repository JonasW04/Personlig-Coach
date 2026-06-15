"""Daily readiness check. Run via `coach-readiness`.

A light morning brief (Sonnet) on the last few days of training and body data: whether
to train today and what to prioritize. Persisted to the DB and sent to notify channels.
Schedule daily on the VPS after the nightly sync, e.g. 06:00:
    0 6 * * * cd /opt/coach && .venv/bin/coach-readiness >> /var/log/coach-readiness.log 2>&1
"""
from __future__ import annotations

import asyncio

from coach import reports
from coach.notify import channels_configured


def main() -> None:
    report = asyncio.run(reports.generate_and_store("readiness"))
    print(report.content)
    used = channels_configured()
    print(f"\n[saved to DB; sent via {', '.join(used) or 'no channels — printed only'}]")


if __name__ == "__main__":
    main()
