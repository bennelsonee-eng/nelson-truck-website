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

from sync_inventory import (DUMPS_DIR, INV_TABLES, MASTER_TABLES, fetch_csv,
                            fetch_csv_paged, log, warn_if_masters_stale)


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
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
