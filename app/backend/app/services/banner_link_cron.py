"""Nightly banner-link health loop.

Sleeps until ~3am PT each night, then validates every banner slide's
click-through link (see banner_link_checker). Broken links are flagged on the
row and auto-hidden from the storefront; recovered links are auto-restored.
Failures log + back off; the loop keeps running.

3am PT is after the overnight inventory refresh, so a "resolves to 0 products"
check reflects the morning's catalog.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from app.database import async_session as async_session_factory
from app.services.banner_link_checker import check_all_banner_links

log = logging.getLogger(__name__)

# ~3am PT — 10:00 UTC (3am PDT) / 2am PST. A fixed UTC hour is good enough.
TARGET_UTC_HOUR = 10


def _seconds_until_next_run(now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    target = now.replace(hour=TARGET_UTC_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_daily_loop() -> None:
    """Sleep until next 3am PT, run the link sweep, repeat. Cancelled by the
    FastAPI lifespan on shutdown."""
    if os.environ.get("BANNER_LINK_CHECK_DISABLED"):
        log.info("Banner link check loop disabled via BANNER_LINK_CHECK_DISABLED env")
        return
    log.info("Banner link check loop started — first run in %.0f sec", _seconds_until_next_run())
    while True:
        try:
            await asyncio.sleep(_seconds_until_next_run())
        except asyncio.CancelledError:
            return
        try:
            async with async_session_factory() as db:
                summary = await check_all_banner_links(db)
            log.info(
                "Banner link check: total=%d ok=%d broken=%d unknown=%d auto_hidden=%d restored=%d",
                summary.total, summary.ok, summary.broken, summary.unknown,
                summary.auto_hidden, summary.restored,
            )
            for b in summary.broken_details[:10]:
                log.warning("  broken banner link [%s]: %s -> %s", b["id"], b["link_url"], b["error"])
        except Exception as e:
            log.exception("Banner link check run crashed: %s", e)
            await asyncio.sleep(60)  # don't kill the loop on a single failure
