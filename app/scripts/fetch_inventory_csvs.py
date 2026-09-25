"""fetch_inventory_csvs.py — pull tte_inv_days + nte_inv_days from the MySQL
bridge into THIS site's own app/data/mysql_dumps/.

link_nelson_inventory.py (the nelson-inventory-sync timer) reads these CSVs.
Until 2026-09-21 that folder on nelson-prod was a symlink into the Titan repo,
kept fresh by Titan's own inventory job running on nelson-prod. Titan now runs
only on titan-prod, so the Nelson site fetches its own copy: same bridge, same
atomic replace + header check as sync_inventory.py, without Titan's loader.

Runs as ExecStartPre of nelson-inventory-sync.service, so a failed fetch fails
the unit (and alerts) instead of silently reloading yesterday's stock.

Manual run:  .venv/bin/python ../scripts/fetch_inventory_csvs.py   (from app/backend)
"""
from __future__ import annotations

import asyncio
import sys

from sync_inventory import (APP_DIR, DUMPS_DIR, INV_TABLES, MASTER_TABLES, fetch_csv,
                            fetch_csv_paged, log, warn_if_masters_stale)


def _env_value(path, key: str) -> str:
    """Settings read .env from the working directory. This job runs in
    app/backend, but the ERP's DSN lives in app/.env (where the nightly
    website sync runs), so read it from there rather than copy a database
    credential into a second file."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


async def main() -> int:
    from app.config import get_settings
    settings = get_settings()
    if not (settings.titan_bridge_url and settings.titan_bridge_token):
        log.error("titan_bridge_url / titan_bridge_token not configured")
        return 1
    if DUMPS_DIR.is_symlink():
        # Writing through the link would feed another site's folder again.
        log.error("%s is a symlink (-> %s); make it a real folder first",
                  DUMPS_DIR, DUMPS_DIR.resolve())
        return 1
    DUMPS_DIR.mkdir(parents=True, exist_ok=True)
    for table, fname in INV_TABLES.items():
        try:
            await fetch_csv(settings.titan_bridge_url, settings.titan_bridge_token,
                            table, DUMPS_DIR / fname)
        except Exception:
            log.exception("fetch %s failed (prior CSV kept)", table)
            return 1
    # The parts masters decide whether an inventory row can be matched at all,
    # so they are refreshed here too, in pages (see fetch_csv_paged).
    for table, fname in MASTER_TABLES.items():
        try:
            await fetch_csv_paged(settings.titan_bridge_url, settings.titan_bridge_token,
                                  table, DUMPS_DIR / fname)
        except Exception:
            log.exception("fetch %s failed (prior CSV kept)", table)
            return 1
    # Fetching a master says nothing about whether the legacy side still
    # rebuilds it; warn (without failing) when one has gone stale.
    await warn_if_masters_stale(settings.titan_bridge_url, settings.titan_bridge_token)
    await refresh_unit_onhand()
    return 0


async def refresh_unit_onhand() -> None:
    """Mirror Nelson's on-hand rows into erp_onhand for the trucks-for-sale
    admin (part-number checks, "in stock but not listed", cost and age).
    Never fails the unit: the stock upsert that follows matters more."""
    try:
        from app.database import async_session, engine
        from app.services.unit_listings import refresh_erp_onhand
        # The shared engine echoes SQL; with 8,000-odd rows inserted every 15
        # minutes that would balloon the timer log (sync_inventory does the same).
        engine.echo = False
        engine.sync_engine.echo = False
        async with async_session() as db:
            n = await refresh_erp_onhand(db, DUMPS_DIR / "nte_inv_days.csv",
                                         DUMPS_DIR / "nte_parts_master.csv")
        log.info("erp_onhand: %d on-hand rows mirrored for the unit listings", n)
    except Exception:
        log.exception("erp_onhand refresh failed (skipped)")
    # The ERP's open orders and quotes on those units: a write-up is only a
    # sale with money down, or an account customer's valid PO (Ben, 2026-09-25).
    try:
        from app.config import get_settings
        from app.database import async_session
        from app.services.unit_listings import refresh_unit_orders
        dsn = getattr(get_settings(), "erp_database_url", "") or _env_value(APP_DIR / ".env", "ERP_DATABASE_URL")
        if not dsn:
            log.warning("erp_unit_order: no ERP_DATABASE_URL -- ERP quotes/sales not refreshed")
        else:
            async with async_session() as db:
                n = await refresh_unit_orders(db, dsn)
            log.info("erp_unit_order: %d open orders/quotes on units mirrored", n)
    except Exception:
        log.exception("erp_unit_order refresh failed (skipped)")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
