"""sync_inventory.py — pull fresh TTE+NTE inventory from the Titan MySQL bridge
into the website's Postgres, then reconcile kit stock + the search index.

Closes the gap where the legacy ERP keeps MySQL `tte_inv_days` fresh every ~15
min but nothing carried that into the website's Postgres `product_inventory`
(it had been frozen since launch).

Runs on the `titan-inventory-sync` 15-min systemd timer. Steps:
  1. Fetch `tte_inv_days` + `nte_inv_days` from the read-only PHP bridge
     (settings.titan_bridge_url, token-auth — same source customer_sync uses),
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
