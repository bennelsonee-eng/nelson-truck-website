"""Fill the website's `customer` table from the ERP customer mirror.

Reads `cus190_erp` (see scripts/sync_erp_feeds.py, which fills it from the ERP
Postgres) and upserts `customer` + `customer_address`. Run sync_erp_feeds first
so the mirror is current; this script reads it and nothing else.

Run from app/ with the backend venv:

    PYTHONPATH=/home/titan/nelson-truck-website/app/backend \
      backend/.venv/bin/python -m scripts.sync_customers [--dry-run] [--limit N]

Idempotent: matched on `customer_number` (unique index), so a second run is a
no-op. Customers absent from the mirror are never touched — 388 of them came
from the contracts file and have no ERP record, and deleting them would take
their contract pricing with them.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.database import async_session
from app.services.customer_sync import sync_customers_from_erp_mirror


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync cus190_erp -> the website customer table")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read and report; write nothing")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap rows read from the mirror (for a quick look)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    async with async_session() as db:
        result = await sync_customers_from_erp_mirror(
            db, dry_run=args.dry_run, limit=args.limit,
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
