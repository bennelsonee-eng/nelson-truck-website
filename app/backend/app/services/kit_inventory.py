"""Derive a kit's sellable stock from its component inventory and materialize it
onto the package product's `product_inventory` rows.

A kit can be assembled at a warehouse only if EVERY linked component is stocked
there in the required quantity, so per-warehouse kit stock is
    min over linked components of floor(component_on_hand_at_wh / qty_needed)
and if any required component is absent at that warehouse it yields 0 there.
Total kit stock = sum across warehouses. (This single-location assembly model is
why a kit can read 0 even when each part exists *somewhere* — the parts have to
be co-located to build one. Switch to a combine-warehouses total if Titan
transfers stock to assemble.)

Unlinked components (part not in our catalog) can't be tracked and are skipped
for the math; the admin UI flags them so pricing/stock aren't silently wrong.

Package products are virtual bundles the ERP never stocks directly (0 inventory
rows of their own), so we own their product_inventory rows outright — delete +
re-insert is safe and idempotent.
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import math
from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Kit, KitComponent, ProductInventory

log = logging.getLogger(__name__)

# Channel order must match the kit avail_* flags + search ALL_CHANNELS.
_CHANNELS = ("retail", "wholesale", "dealer", "municipality")


def kit_window_open(available_from, available_until, today: datetime.date | None = None) -> bool:
    """Inclusive date-window check. Null bounds = open-ended."""
    today = today or datetime.date.today()
    if available_from and today < available_from:
        return False
    if available_until and today > available_until:
        return False
    return True


def kit_enabled_channels(*, is_active, available_from, available_until,
                         avail_retail, avail_wholesale, avail_dealer, avail_municipality,
                         today: datetime.date | None = None) -> list[str]:
    """The channels a kit is live for RIGHT NOW. Empty when inactive or outside
    its availability window — which hides the package everywhere (search +
    PDP), reusing the channel-hide path. Used by the search doc builder + PDP."""
    if not is_active or not kit_window_open(available_from, available_until, today):
        return []
    flags = (avail_retail, avail_wholesale, avail_dealer, avail_municipality)
    return [c for c, ok in zip(_CHANNELS, flags) if ok]


async def recompute_kit_stock(db: AsyncSession, kit: Kit, *, materialize: bool = True) -> dict:
    """Recompute one kit's stock from components. Returns a summary dict.

    materialize=True writes the derived per-warehouse stock onto the package
    product's product_inventory rows (caller commits). materialize=False is a
    pure read — safe inside a GET to show an always-fresh number.
    `kit.components` must be loaded.
    """
    summary = {"total_on_hand": 0, "by_warehouse": [], "limiting_part": None, "unlinked": 0}
    if not kit.product_id:
        return summary

    comps = list(kit.components)
    linked = [(c.product_id, c.quantity, c.part_number) for c in comps
              if c.product_id and (c.quantity or 0) > 0]
    summary["unlinked"] = sum(1 for c in comps if not c.product_id)

    pids = [pid for pid, _, _ in linked]
    rows = []
    if pids:
        rows = (await db.execute(
            select(ProductInventory.product_id, ProductInventory.warehouse_id,
                   ProductInventory.on_hand, ProductInventory.available)
            .where(ProductInventory.product_id.in_(pids))
        )).all()

    onhand: dict[int, dict[int, int]] = defaultdict(dict)
    avail: dict[int, dict[int, int]] = defaultdict(dict)
    warehouses: set[int] = set()
    for r in rows:
        warehouses.add(r.warehouse_id)
        onhand[r.product_id][r.warehouse_id] = r.on_hand or 0
        avail[r.product_id][r.warehouse_id] = (
            r.available if r.available is not None else r.on_hand) or 0

    by_wh: list[tuple[int, int, int]] = []
    for wh in sorted(warehouses):
        if not linked:
            kqty = kav = 0
        else:
            kqty = min(math.floor(onhand[pid].get(wh, 0) / qty) for pid, qty, _ in linked)
            kav = min(math.floor(avail[pid].get(wh, 0) / qty) for pid, qty, _ in linked)
        by_wh.append((wh, max(kqty, 0), max(kav, 0)))

    # Identify the globally limiting part (smallest floor(total_onhand/qty)).
    if linked:
        totals = {}
        for pid, qty, pn in linked:
            t = sum(onhand[pid].values())
            totals[pn] = math.floor(t / qty)
        summary["limiting_part"] = min(totals, key=totals.get) if totals else None

    # Materialize: own the package product's inventory rows.
    if materialize:
        await db.execute(delete(ProductInventory).where(
            ProductInventory.product_id == kit.product_id))
        for wh, kqty, kav in by_wh:
            db.add(ProductInventory(
                product_id=kit.product_id, warehouse_id=wh, on_hand=kqty, available=kav))

    summary["total_on_hand"] = sum(k for _, k, _ in by_wh)
    summary["by_warehouse"] = [{"warehouse_id": wh, "on_hand": k, "available": a}
                               for wh, k, a in by_wh]
    return summary


async def recompute_all_kits(db: AsyncSession) -> dict:
    """Bulk recompute every kit. Commits once at the end. Returns counts."""
    from sqlalchemy.orm import selectinload
    kits = (await db.execute(
        select(Kit).options(selectinload(Kit.components))
    )).scalars().all()
    n_in_stock = 0
    for kit in kits:
        s = await recompute_kit_stock(db, kit)
        if s["total_on_hand"] > 0:
            n_in_stock += 1
    await db.commit()
    return {"kits": len(kits), "in_stock": n_in_stock}


async def recompute_and_reindex_kits(db: AsyncSession) -> dict:
    """Recompute every kit's stock AND re-index the kit products so the search
    grid's in-stock state follows component inventory. Returns counts."""
    result = await recompute_all_kits(db)
    pids = [pid for (pid,) in (await db.execute(
        select(Kit.product_id).where(Kit.product_id.is_not(None))
    )).all()]
    if pids:
        from app.services.search import index_products  # lazy: avoid import cycle
        result["reindexed"] = await index_products(db, pids)
    return result


async def run_kit_stock_loop(interval_seconds: int = 900):
    """Background loop: keep kit stock in lockstep with component inventory.

    Wired from `main.py` lifespan. Owns its own engine/sessionmaker (like the
    FACS heartbeat) so it doesn't tangle with request-scoped `get_db()`. Runs
    every `interval_seconds` (default 15 min) — whenever component inventory
    changes by any means, derived kit stock + the search index catch up within
    one interval.
    """
    from app.config import get_settings
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False, future=True)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    log.info("Kit-stock loop started (interval=%ds)", interval_seconds)
    try:
        while True:
            try:
                async with Session() as db:
                    r = await recompute_and_reindex_kits(db)
                log.info("[kit-stock] recomputed %d kits (%d in stock, %d reindexed)",
                         r.get("kits", 0), r.get("in_stock", 0), r.get("reindexed", 0))
            except Exception:
                log.exception("[kit-stock] tick failed; will retry next interval")
            await asyncio.sleep(interval_seconds)
    finally:
        await engine.dispose()
