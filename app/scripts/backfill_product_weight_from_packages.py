"""Backfill product.weight_lb from product_package rows we already have.

UPC can't be backfilled from existing tables — PIES ItemLevelGTIN isn't
stored anywhere in the DB until the importer re-runs. The fixed importer
in import_pace_brand.py will pick it up on the next full re-import.

This script handles WEIGHT only: every product whose weight_lb is null
gets the smallest-positive per-package weight from product_package as
its representative each-weight. Prefer rows with quantity_of_eaches=1
when present.

Owner ask 2026-05-17 (I2).

Run from app/ with the backend venv:
    cd /home/titan/titan-truck-website/app
    backend/.venv/bin/python -m scripts.backfill_product_weight_from_packages
    backend/.venv/bin/python -m scripts.backfill_product_weight_from_packages --dry-run
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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import select, update  # noqa: E402

from app.database import async_session, engine  # noqa: E402
engine.echo = False
engine.sync_engine.echo = False

from app.models import Product, ProductPackage  # noqa: E402


log = logging.getLogger("backfill_product_weight")


async def run(*, dry_run: bool) -> int:
    async with async_session() as db:
        # Pull products missing a weight that have at least one product_package.
        rows = (await db.execute(
            select(Product.id, ProductPackage.weight_lb, ProductPackage.quantity_of_eaches)
            .join(ProductPackage, ProductPackage.product_id == Product.id)
            .where(Product.weight_lb.is_(None))
            .where(ProductPackage.weight_lb.is_not(None))
            .where(ProductPackage.weight_lb > 0)
        )).all()

        # Group by product_id: pick best weight per the same rule the importer uses
        per_product: dict[int, tuple[object | None, int | None]] = {}
        for pid, w, qe in rows:
            cur = per_product.get(pid)
            if cur is None:
                per_product[pid] = (w, qe)
                continue
            cw, cqe = cur
            # Prefer per-each (qe == 1) outright; otherwise lowest weight.
            if qe == 1 and (cqe or 0) != 1:
                per_product[pid] = (w, qe)
            elif (cqe or 0) != 1 and cw is not None and w is not None and w < cw:
                per_product[pid] = (w, qe)

        log.info("Found weight candidates for %d products missing weight_lb", len(per_product))

        updated = 0
        for pid, (w, qe) in per_product.items():
            if w is None:
                continue
            if dry_run:
                updated += 1
                if updated <= 10:
                    log.info("  [dry-run] product %d → %s lb (qe=%s)", pid, w, qe)
                continue
            await db.execute(
                update(Product).where(Product.id == pid).values(weight_lb=w)
            )
            updated += 1
            if updated % 1000 == 0:
                log.info("  …%d updated", updated)
                await db.commit()
        if not dry_run:
            await db.commit()
        log.info("Done: %d products updated.", updated)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
