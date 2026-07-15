"""FACS pickup heartbeat poller.

Runs periodically in the background.  Lists files in the FACS dropbox; any
fulfillment in `PUSHED` state whose file is NO LONGER present in the dropbox
flips to `PICKED_UP` (FACS grabbed it).

Conversely, if a `PUSHED` file is still in the dropbox after the configured
`facs_pickup_lag_alert_minutes` threshold, we log a warning so admin can
investigate.

Pure helper `compute_pickup_actions` is split out for unit-testability.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import FACSPushStatus, OrderFulfillment
from app.services.facs_pusher import list_dropbox_files


__all__ = [
    "PickupAction",
    "compute_pickup_actions",
    "run_heartbeat_once",
    "run_heartbeat_loop",
]


log = logging.getLogger(__name__)


@dataclass
class PickupAction:
    fulfillment_id: int
    kind: str               # "mark_picked_up" | "warn_lag"
    file_name: str
    age_minutes: int | None = None


@dataclass
class HeartbeatTick:
    actions: list[PickupAction] = field(default_factory=list)
    files_in_dropbox: int = 0
    pushed_fulfillments_checked: int = 0


@dataclass(frozen=True)
class _PushedFulfillmentLike:
    """Slim view of an OrderFulfillment row for the pure planner."""

    id: int
    file_name: str
    pushed_at: datetime | None


def compute_pickup_actions(
    *,
    pushed_fulfillments: list[_PushedFulfillmentLike],
    dropbox_files: set[str],
    now: datetime,
    lag_alert_minutes: int,
) -> list[PickupAction]:
    """Pure: walk pushed fulfillments and decide what to do.

    For each fulfillment in PUSHED state:
      * file no longer in dropbox → mark PICKED_UP.
      * file still in dropbox AND pushed > lag_alert_minutes ago → warn.
    """
    out: list[PickupAction] = []
    for f in pushed_fulfillments:
        if f.file_name not in dropbox_files:
            out.append(PickupAction(fulfillment_id=f.id, kind="mark_picked_up", file_name=f.file_name))
            continue
        if f.pushed_at is None:
            continue
        age = now - (f.pushed_at if f.pushed_at.tzinfo else f.pushed_at.replace(tzinfo=timezone.utc))
        age_min = int(age.total_seconds() / 60)
        if age_min > lag_alert_minutes:
            out.append(PickupAction(
                fulfillment_id=f.id, kind="warn_lag",
                file_name=f.file_name, age_minutes=age_min,
            ))
    return out


async def run_heartbeat_once(db: AsyncSession) -> HeartbeatTick:
    """Run one tick of the heartbeat against the DB + dropbox.  Returns stats."""
    settings = get_settings()
    files = set(await list_dropbox_files())

    rows = (await db.execute(
        select(OrderFulfillment).where(OrderFulfillment.push_status == FACSPushStatus.PUSHED)
    )).scalars().all()
    pushed_views = [
        _PushedFulfillmentLike(id=r.id, file_name=r.file_name, pushed_at=r.pushed_at)
        for r in rows
    ]
    actions = compute_pickup_actions(
        pushed_fulfillments=pushed_views,
        dropbox_files=files,
        now=datetime.now(timezone.utc),
        lag_alert_minutes=settings.facs_pickup_lag_alert_minutes,
    )

    rows_by_id = {r.id: r for r in rows}
    now = datetime.now(timezone.utc)
    for action in actions:
        row = rows_by_id.get(action.fulfillment_id)
        if row is None:
            continue
        if action.kind == "mark_picked_up":
            row.push_status = FACSPushStatus.PICKED_UP
            row.picked_up_at = now
            log.info("[facs.heartbeat] %s picked up", action.file_name)
        elif action.kind == "warn_lag":
            log.warning("[facs.heartbeat] %s sitting in dropbox for %d min (threshold %d)",
                        action.file_name, action.age_minutes, settings.facs_pickup_lag_alert_minutes)
    if actions:
        await db.commit()

    return HeartbeatTick(actions=actions, files_in_dropbox=len(files), pushed_fulfillments_checked=len(rows))


async def run_heartbeat_loop(interval_seconds: int = 300):
    """Run the heartbeat forever, every `interval_seconds`.

    Wired from `main.py` lifespan.  Owns its own engine + sessionmaker so the
    FastAPI request-scoped `get_db()` doesn't get tangled up here.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    log.info("FACS heartbeat loop started (interval=%ds)", interval_seconds)
    try:
        while True:
            try:
                async with Session() as db:
                    tick = await run_heartbeat_once(db)
                if tick.actions:
                    log.info("[facs.heartbeat] tick: %d actions (%d files in dropbox, %d pushed checked)",
                             len(tick.actions), tick.files_in_dropbox, tick.pushed_fulfillments_checked)
            except Exception:
                log.exception("[facs.heartbeat] tick failed; will retry next interval")
            await asyncio.sleep(interval_seconds)
    finally:
        await engine.dispose()
