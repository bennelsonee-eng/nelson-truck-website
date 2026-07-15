"""WinterWatch daily alert loop.

Sleeps until 7am PT each morning, then runs the alert sweep once.  Failures
log + back off; the loop keeps running.

Why 7am PT specifically:
  - PT covers both Spokane HQ and Boise customers (their shops open ~7-8am)
  - Inbox first-thing means contractors see the alert before they leave the
    yard, so they can grab the plow on the way out
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from app.database import async_session as async_session_factory
from app.services.weather_alert_service import run_daily_alerts


log = logging.getLogger(__name__)

# 7am Pacific Time (UTC-8 standard, UTC-7 daylight).  Using a fixed UTC hour
# is good-enough; we don't need precise DST handling for an alert email.
TARGET_UTC_HOUR = 14   # 14:00 UTC ≈ 7am PT (DST) / 6am PT (standard)


def _seconds_until_next_run(now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    target = now.replace(hour=TARGET_UTC_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_daily_loop() -> None:
    """Sleep until next 7am PT, run the alert sweep, repeat.  Cancelled by
    the FastAPI lifespan on shutdown."""
    if os.environ.get("WINTERWATCH_DISABLED"):
        log.info("WinterWatch loop disabled via WINTERWATCH_DISABLED env")
        return
    log.info("WinterWatch daily loop started — first run in %.0f sec", _seconds_until_next_run())
    while True:
        try:
            await asyncio.sleep(_seconds_until_next_run())
        except asyncio.CancelledError:
            return
        try:
            async with async_session_factory() as db:
                summary = await run_daily_alerts(db)
                await db.commit()
            log.info(
                "WinterWatch daily run: checked=%d snow_detected=%d sent=%d errors=%d",
                summary.checked, summary.snow_detected, summary.sent, len(summary.errors),
            )
            for e in summary.errors[:5]:
                log.warning("  alert error: %s", e)
        except Exception as e:
            log.exception("WinterWatch daily run crashed: %s", e)
            # Don't kill the loop on a single failure
            await asyncio.sleep(60)
