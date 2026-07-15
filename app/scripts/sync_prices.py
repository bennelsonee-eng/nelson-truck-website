"""Sync P1-P5 prices from MySQL nte_parts_master into the local product_price table.

Run from `app/backend/` directory with venv activated (and PYTHONPATH set to
the backend dir so the `scripts` package resolves):

    PYTHONPATH=/home/titan/titan-truck-website/app/backend \
      /home/titan/titan-truck-website/app/backend/.venv/bin/python \
      -m scripts.sync_prices [--limit N]

Pulls every row from nte_parts_master via the read-only PHP bridge, matches
by SKU (= ourparts_num) against existing Products, and upserts ProductPrice
rows. Non-destructive: products and brands are not touched.

Bridge config (already defaulted in app/.env — TITAN_BRIDGE_URL +
TITAN_BRIDGE_TOKEN).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config import get_settings
from app.database import async_session
from app.services.price_sync import sync_prices_from_nte_parts_master


async def main() -> int:
    parser = argparse.ArgumentParser(description="Sync nte_parts_master prices → product_price")
    parser.add_argument("--limit", type=int, default=None, help="Cap total rows fetched")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    # Suppress SQLAlchemy engine spam during the bulk write phase
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    settings = get_settings()
    async with async_session() as db:
        result = await sync_prices_from_nte_parts_master(db, settings, limit=args.limit)

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
