"""sync_inventory.py — pull fresh TTE+NTE inventory from the Titan MySQL bridge
into the website's Postgres, then reconcile kit stock + the search index.

Closes the gap where the legacy ERP keeps MySQL `tte_inv_days` fresh every ~15
min but nothing carried that into the website's Postgres `product_inventory`
(it had been frozen since launch).

Runs on the `titan-inventory-sync` 15-min systemd timer. Steps:
  1. Fetch `tte_inv_days` + `nte_inv_days` from the read-only PHP bridge
     (settings.titan_bridge_url, token-auth — same source contract_sync uses),
     writing them where link_titan_inventory_v2 expects (atomic replace, so a
     mid-fetch failure never leaves a truncated CSV).
  2. Run link_titan_inventory_v2 in INVENTORY-ONLY mode (write_prices=False) so
     manually-set / kit prices are never clobbered. That loader upserts
     product_inventory, recomputes kit stock, and re-indexes changed products.

Manual run:  .venv/bin/python ../scripts/sync_inventory.py   (from app/backend)
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR / "backend"
DUMPS_DIR = APP_DIR / "data" / "mysql_dumps"
for _p in (str(BACKEND_DIR), str(SCRIPT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sync_inventory")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

# Bridge table -> destination CSV (the names link_titan_inventory_v2 reads).
INV_TABLES = {
    "tte_inv_days": "tte_inv_days.csv",
    "nte_inv_days": "nte_inv_days.csv",
}

# The linker looks every inventory row up in the parts master; a part missing
# from these means its stock is dropped ("no_master"). They were a stale
# snapshot until 2026-09-24 — 331,201 of 441,088 rows, which is why every
# Tommy Gate liftgate on the site read "not in stock" with one on the floor.
# Fetched in pages because a single bridge response tops out around 331k rows.
MASTER_TABLES = {
    "tte_parts_master": "tte_parts_master.csv",
    "nte_parts_master": "nte_parts_master.csv",
}
# The bridge caps one query at 50k rows, so ask for less than that.
MASTER_PAGE = 25_000


# A parts master that stops rebuilding is invisible: stock keeps flowing from
# nte_inv_days, but every part added since the last rebuild is dropped as
# "no_master" and reads as out of stock. Nelson's nte_parts_master sat frozen
# from 2026-09-21 to 2026-09-24 without anything noticing, because the upstream
# feed that rebuilds it (nte-ims200-daily.csv) is not one of the ten
# {company}-{report}-erp.csv files check_daily_feeds.py watches. These rebuild
# about 05:45 daily, so a day of grace on top of that is plenty.
MASTER_STALE_AFTER_HOURS = 36


async def warn_if_masters_stale(url: str, token: str,
                                hours: int = MASTER_STALE_AFTER_HOURS) -> list[str]:
    """Log a WARNING for every parts master the legacy MySQL has not rebuilt
    recently. Returns the names found stale.

    Deliberately advisory, never fatal: a stale master still matches far more
    inventory than no master at all, and failing the 15-minute unit over it
    would stop the stock upsert entirely, which is the worse outcome.
    """
    names = ", ".join(f"'{t}'" for t in MASTER_TABLES)
    # Age is computed by MySQL against its own NOW(), not ours: this box runs
    # UTC and the legacy host does not, and a fixed 7-hour skew against a
    # daily rebuild is enough to invent a staleness warning.
    q = ("SELECT TABLE_NAME, UPDATE_TIME, "
         "TIMESTAMPDIFF(HOUR, UPDATE_TIME, NOW()) AS age_hours "
         "FROM information_schema.TABLES "
         "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN (" + names + ")")
    try:
        async with httpx.AsyncClient(timeout=60, verify=True) as client:
            r = await client.get(url, params={"token": token, "query": q,
                                              "format": "json"})
            r.raise_for_status()
            rows = r.json().get("rows", [])
    except Exception:
        # Never let the freshness probe be the thing that breaks the sync.
        log.exception("parts-master freshness check failed (skipped)")
        return []

    stale: list[str] = []
    for row in rows:
        table = row.get("TABLE_NAME") or "?"
        stamp = row.get("UPDATE_TIME")
        if not stamp:
            log.warning("%s: no UPDATE_TIME reported, cannot judge freshness", table)
            continue
        try:
            age = int(row["age_hours"])
        except (KeyError, TypeError, ValueError):
            log.warning("%s: no usable age for UPDATE_TIME %r", table, stamp)
            continue
        if age > hours:
            stale.append(table)
            log.warning("%s has not rebuilt in %dh (last %s) - parts added since "
                        "then are dropped as no_master and read as out of stock. "
                        "Check that its upstream feed is still being delivered.",
                        table, age, stamp)
        else:
            log.info("%s rebuilt %dh ago (%s)", table, age, stamp)
    return stale


async def fetch_csv(url: str, token: str, table: str, dest: Path) -> int:
    """Fetch one inventory table as CSV and atomically replace `dest`.
    Validates the expected header so a bridge error page never overwrites a
    good CSV. Returns bytes written."""
    params = {"token": token, "table": table, "format": "csv"}
    async with httpx.AsyncClient(timeout=180, verify=True) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        body = r.content
    if b"ourparts_num" not in body[:300].lower():
        raise RuntimeError(
            f"{table}: response missing expected header ({len(body)}B): {body[:160]!r}")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(dest)  # atomic swap
    log.info("fetched %s -> %s (%d bytes)", table, dest.name, len(body))
    return len(body)


async def fetch_csv_paged(url: str, token: str, table: str, dest: Path,
                          page: int = MASTER_PAGE) -> int:
    """Fetch a whole table as CSV in pages, then atomically replace `dest`.

    The bridge caps one response; paging with LIMIT/OFFSET gets every row.
    The header comes back on each page, so only the first one is kept.
    """
    parts: list[bytes] = []
    offset = 0
    async with httpx.AsyncClient(timeout=300, verify=True) as client:
        while True:
            q = f"SELECT * FROM {table} LIMIT {page} OFFSET {offset}"
            r = await client.get(url, params={"token": token, "query": q, "format": "csv"})
            r.raise_for_status()
            body = r.content
            if b"ourparts_num" not in body[:300].lower():
                raise RuntimeError(
                    f"{table}: response missing expected header ({len(body)}B): {body[:160]!r}")
            lines = body.splitlines(keepends=True)
            rows = lines if offset == 0 else lines[1:]
            if not rows or (offset and len(rows) == 0):
                break
            parts.extend(rows)
            fetched = len(lines) - 1
            offset += page
            if fetched < page:   # short page = last page
                break
            if offset > 2_000_000:  # guard against a bridge that ignores OFFSET
                log.warning("%s: stopping at %d rows", table, offset)
                break
    blob = b"".join(parts)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(dest)
    log.info("fetched %s -> %s (%d rows, %d bytes)", table, dest.name,
             max(len(parts) - 1, 0), len(blob))
    return len(blob)


async def main() -> None:
    from app.config import get_settings
    settings = get_settings()
    if not (settings.titan_bridge_url and settings.titan_bridge_token):
        log.error("titan_bridge_url / titan_bridge_token not configured — aborting")
        sys.exit(1)

    # Silence SQLAlchemy statement echo on the shared engine (the post-load
    # reindex queries a 5k-element IN list; with echo on the timer log balloons).
    try:
        from app.database import engine
        engine.echo = False
        engine.sync_engine.echo = False
    except Exception:
        pass

    # 1) Pull fresh inventory CSVs. Abort (keep prior CSVs) if any fetch fails
    #    so we never run the loader against a half-updated dataset.
    for table, fname in INV_TABLES.items():
        try:
            await fetch_csv(settings.titan_bridge_url, settings.titan_bridge_token,
                            table, DUMPS_DIR / fname)
        except Exception:
            log.exception("fetch %s failed — aborting this run (prior CSV kept)", table)
            sys.exit(1)

    # 2) Load into Postgres (inventory only — never clobber manual/kit prices).
    #    The loader recomputes kit stock + re-indexes changed products at the end.
    import link_titan_inventory_v2 as linker
    await linker.main(dry_run=False, seed_wh=False, write_prices=False)
    log.info("inventory sync complete")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
