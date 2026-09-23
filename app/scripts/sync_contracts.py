"""Refresh contract pricing from the legacy MySQL `contracts_copy` (company='nelson').

Run after the contracts file has been loaded into MySQL. From app/backend with
the venv:

    PYTHONPATH=/home/titan/nelson-truck-website/app/backend \
      /home/titan/nelson-truck-website/app/backend/.venv/bin/python \
      -m scripts.sync_contracts --dry-run      # counts only, writes nothing
      -m scripts.sync_contracts                # replace the synced rows

Safe to re-run: every run rebuilds the rows it owns (and the ones the July 2026
one-off import left), keeping a copy in _bak_contract_sync. Contract rows added
in the app are left alone. See app/backend/app/services/contract_sync.py.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.config import get_settings
from app.database import async_session
from app.services.contract_sync import sync_contracts


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="read and report, write nothing")
    ap.add_argument("--max-rows", type=int, default=None, help="stop after N source rows (testing)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = get_settings()
    async with async_session() as db:
        result = await sync_contracts(db, settings, dry_run=args.dry_run, max_rows=args.max_rows)
    print(result.summary())
    if result.unknown_customers:
        sample = sorted(result.unknown_customers)[:10]
        print(f"customers in the contracts file that the website doesn't have yet (first {len(sample)}): "
              + ", ".join(sample))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
