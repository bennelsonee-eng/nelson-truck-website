"""Sync Titan customers from MySQL tte_cus190 into the local Postgres customer table.

Run from `app/backend/` directory with venv activated:

    python -m scripts.sync_customers --dry-run --limit 50   # safe preview
    python -m scripts.sync_customers --limit 1000           # write 1000 rows
    python -m scripts.sync_customers                        # full sync

Required env (in app/.env or shell):
    TITAN_MYSQL_HOST=<host>
    TITAN_MYSQL_PORT=3306          (default)
    TITAN_MYSQL_USER=<user>
    TITAN_MYSQL_PASS=<pass>
    TITAN_MYSQL_DB=<schema name>   (e.g. nelsontruck1)

See app/backend/app/services/customer_sync.py for the column mapping
(COLUMN_MAP / TteCus190Columns) — edit there if Titan's actual columns
differ from the FACS conventions assumed by default.

Idempotent: matches by Customer.customer_number and updates in place.
Primary BILLING + SHIPPING addresses are replaced on each sync; any
non-primary addresses (jobber-added) are preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config import get_settings
from app.database import async_session
from app.services.customer_sync import sync_customers_from_tte_cus190


async def main() -> int:
    parser = argparse.ArgumentParser(description="Sync tte_cus190 → local customer table")
    parser.add_argument("--dry-run", action="store_true", help="Read + report; don't write")
    parser.add_argument("--limit", type=int, default=None, help="Cap rows fetched from MySQL")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    settings = get_settings()

    async with async_session() as db:
        result = await sync_customers_from_tte_cus190(
            db, settings, dry_run=args.dry_run, limit=args.limit,
        )

    print()
    print(result.summary())
    if result.errors:
        print()
        print("Errors:")
        for e in result.errors[:30]:
            print(f"  - {e}")
        if len(result.errors) > 30:
            print(f"  ... and {len(result.errors) - 30} more")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
