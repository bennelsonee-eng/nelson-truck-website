"""Sync USD prices from AAM PIES zips into product_price for products that
nte_parts_master didn't already cover.

Run from `app/backend/` directory:

    PYTHONPATH=/path/to/app/backend \\
      /path/to/app/backend/.venv/bin/python \\
      -m scripts.sync_pies_prices --dir /path/to/aam_pies_zips [--limit-files N]

PIES zips are named `AAM_<aaia>_PIES_<timestamp>.zip`. We pull USD pricing
(RMP/LST/MAP for MSRP, JBR for jobber, WD for dealer) and ONLY insert price
rows for products that don't already have one — nte_parts_master is the
authority for products it covers.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.database import async_session
from app.services.pies_price_sync import sync_prices_from_pies_dir


async def main() -> int:
    parser = argparse.ArgumentParser(description="Sync PIES → product_price (gap fill)")
    parser.add_argument("--dir", type=Path, required=True, help="Directory containing AAM_*_PIES_*.zip files")
    parser.add_argument("--limit-files", type=int, default=None, help="Process only the first N zips (alphabetical)")
    parser.add_argument("--pattern", type=str, default="AAM_*_PIES_*.zip", help="Glob for PIES zips")
    parser.add_argument(
        "--fill-null-tiers",
        action="store_true",
        help="On rows that already exist, UPDATE only the tier columns that are currently NULL. "
             "Use this to backfill cost/dealer after fixing extraction logic for new PriceType variants.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    # SQLAlchemy engine logs add a lot of noise during bulk insert chunks
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    if not args.dir.exists():
        print(f"Directory not found: {args.dir}", file=sys.stderr)
        return 1

    async with async_session() as db:
        result = await sync_prices_from_pies_dir(
            db,
            args.dir,
            limit_files=args.limit_files,
            file_pattern=args.pattern,
            fill_null_tiers=args.fill_null_tiers,
        )

    print()
    print(result.summary())
    if result.errors:
        print("\nErrors:")
        for e in result.errors[:30]:
            print(f"  - {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
