"""reindex_typesense.py — rebuild the Typesense `products` collection.

Run this after any bulk inventory change (e.g. link_tte_inventory.py) so
the catalog grid's in-stock filter reflects reality.

Usage (from app/backend/):
    .venv/bin/python ../scripts/reindex_typesense.py
    .venv/bin/python ../scripts/reindex_typesense.py --drop   # full rebuild
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("reindex")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


async def main(drop_first: bool) -> None:
    from app.database import async_session, engine  # type: ignore
    engine.echo = False
    engine.sync_engine.echo = False
    from app.services.search import reindex_all_products  # type: ignore
    from app.services.kit_inventory import recompute_all_kits  # type: ignore

    log.info("Reindexing Typesense (drop_first=%s)…", drop_first)
    async with async_session() as db:
        # Refresh derived kit stock from component inventory first, so the
        # rebuilt index reflects current package availability.
        try:
            ks = await recompute_all_kits(db)
            log.info("Recomputed kit stock: %s", ks)
        except Exception:
            log.exception("Kit-stock recompute failed; continuing with reindex")
        n = await reindex_all_products(db, drop_first=drop_first)
    log.info("Indexed %d documents.", n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--drop", action="store_true",
                    help="Drop the collection first (full rebuild).  Without this, "
                         "documents are upserted in place.")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main(drop_first=args.drop))
