"""import_buyers_parts_master.py - Load Buyers + SnowDogg parts master CSVs.

The legacy TigerTech/Nelson ERP exports per-brand parts master files into
app/data/mysql_dumps/. Currently `product` table only holds the ~590 BUY/SNOW
SKUs that have moved in inventory recently (loaded via the TTE/NTE inv-day
linker). The actual parts master is much larger:

  buy_parts_master.csv  : 12,057 unique BUY part numbers
  snow_parts_master.csv :  1,871 unique SNOW part numbers
  ------                  -----------
  total                  : 13,928

Most of those are not currently in `product` because they haven't had recent
inventory activity. Owner ask 2026-05-22 — load them all into `product` so
the Buyers PDP scraper has the full universe to enrich.

Strategy:
  * Look up Brand by prod_code ('BUY', 'SNOW') — must already exist in DB.
  * For each CSV row build SKU = f"{prod_code}-{parts_num}".
  * If SKU exists in `product`:
      - default: skip (don't touch curated data)
      - --update-existing: fill NULL columns only, never overwrite
  * If SKU does not exist: insert a new Product with:
      - sku, brand_id, name = description (capped 500), prod_code
      - tte_ourparts_num = ourparts_num (for the inv linker to find later)
      - dimensions + weight from CSV
      - is_for_sale = (status == 'A') unless --all-active
      - is_hidden = TRUE by default (so 13k new rows don't flood the catalog)
        Use --visible to override, or run a post-curation pass to unhide
        products that got rich data from the scraper.
  * Commit per --commit-batch rows (default 500) so a wedge doesn't lose
    everything. Per-batch failures are logged but don't abort the run.
  * Skips rows where parts_num or description is empty.

Run from app/ with the backend venv:
    backend/.venv/bin/python -m scripts.import_buyers_parts_master --dry-run
    backend/.venv/bin/python -m scripts.import_buyers_parts_master --limit 50
    backend/.venv/bin/python -m scripts.import_buyers_parts_master
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import select  # noqa: E402

from app.database import async_session, engine  # noqa: E402
engine.echo = False
engine.sync_engine.echo = False

from app.models import Brand, Product  # noqa: E402


log = logging.getLogger("import_buyers_parts_master")

DEFAULT_BUY_CSV = APP_DIR / "data" / "mysql_dumps" / "buy_parts_master.csv"
DEFAULT_SNOW_CSV = APP_DIR / "data" / "mysql_dumps" / "snow_parts_master.csv"


def _decimal_or_none(s: str | None) -> Decimal | None:
    """Parse a positive decimal string. Empty, '0', '0.00' → None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d if d > 0 else None


async def _lookup_brand(db, prod_code: str) -> Brand | None:
    """Find the Brand whose AAIA code matches the CSV prod_code.

    Brand.aaia_code holds the same value the parts-master CSV puts in its
    prod_code column ('BUY' for Buyers Products, 'SNOW' for Buyers SnowDogg
    on this DB). prod_code lives on Product, not Brand.
    """
    return (await db.execute(
        select(Brand).where(Brand.aaia_code == prod_code)
    )).scalar_one_or_none()


async def _process_csv(
    db,
    csv_path: Path,
    prod_code: str,
    brand: Brand,
    *,
    dry_run: bool,
    limit: int | None,
    commit_batch: int,
    update_existing: bool,
    include_inactive: bool,
    hide_new: bool,
    all_active: bool,
) -> dict:
    """Process one parts-master CSV. Returns aggregated counts."""
    counts = {
        "new": 0, "existing_skipped": 0, "existing_updated": 0,
        "inactive_skipped": 0, "row_skipped": 0, "commit_failures": 0,
    }
    processed = 0
    batch_since_commit = 0

    with open(csv_path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if limit is not None and processed >= limit:
                break
            processed += 1

            parts_num = (row.get("parts_num") or "").strip()
            description = (row.get("description") or "").strip()
            if not parts_num or not description:
                counts["row_skipped"] += 1
                continue

            status = (row.get("status") or "").strip().upper()
            if not include_inactive and status and status != "A":
                counts["inactive_skipped"] += 1
                continue

            sku = f"{prod_code}-{parts_num}"

            existing = (await db.execute(
                select(Product).where(Product.sku == sku)
            )).scalar_one_or_none()

            ourparts_num = (row.get("ourparts_num") or "").strip() or None
            extra_desc = (row.get("extra_desc") or "").strip() or None
            weight = _decimal_or_none(row.get("weight"))
            length = _decimal_or_none(row.get("length"))
            width  = _decimal_or_none(row.get("width"))
            height = _decimal_or_none(row.get("height"))

            if existing is not None:
                if not update_existing:
                    counts["existing_skipped"] += 1
                    continue
                # Fill NULL columns only — never overwrite curated data.
                changed = False
                if not existing.tte_ourparts_num and ourparts_num:
                    existing.tte_ourparts_num = ourparts_num
                    changed = True
                if existing.weight_lb is None and weight is not None:
                    existing.weight_lb = weight
                    changed = True
                if existing.length_in is None and length is not None:
                    existing.length_in = length
                    changed = True
                if existing.width_in is None and width is not None:
                    existing.width_in = width
                    changed = True
                if existing.height_in is None and height is not None:
                    existing.height_in = height
                    changed = True
                if not existing.description and extra_desc:
                    existing.description = extra_desc
                    changed = True
                if changed:
                    counts["existing_updated"] += 1
                    if not dry_run:
                        batch_since_commit += 1
                else:
                    counts["existing_skipped"] += 1
            else:
                # New product
                counts["new"] += 1
                if not dry_run:
                    is_for_sale = True if all_active else (status == "A" or not status)
                    db.add(Product(
                        sku=sku,
                        brand_id=brand.id,
                        name=description[:500],
                        prod_code=prod_code,
                        tte_ourparts_num=ourparts_num,
                        description=extra_desc,
                        weight_lb=weight,
                        length_in=length,
                        width_in=width,
                        height_in=height,
                        is_for_sale=is_for_sale,
                        is_hidden=hide_new,
                    ))
                    batch_since_commit += 1

            if not dry_run and batch_since_commit >= commit_batch:
                try:
                    await db.commit()
                    log.info(
                        "  committed batch (%d writes)  processed=%d  new=%d  updated=%d  skipped=%d",
                        batch_since_commit, processed,
                        counts["new"], counts["existing_updated"],
                        counts["existing_skipped"] + counts["inactive_skipped"] + counts["row_skipped"],
                    )
                    batch_since_commit = 0
                except Exception as e:
                    counts["commit_failures"] += 1
                    log.warning("  commit failed at row %d: %s — rollback + continue", processed, e)
                    await db.rollback()
                    batch_since_commit = 0

        # Final commit
        if not dry_run and batch_since_commit > 0:
            try:
                await db.commit()
                log.info("  final commit (%d writes)", batch_since_commit)
            except Exception as e:
                counts["commit_failures"] += 1
                log.warning("  final commit failed: %s", e)
                await db.rollback()

    log.info(
        "%s done: new=%d  existing_skipped=%d  existing_updated=%d  inactive_skipped=%d  row_skipped=%d  commit_failures=%d",
        prod_code, counts["new"], counts["existing_skipped"],
        counts["existing_updated"], counts["inactive_skipped"],
        counts["row_skipped"], counts["commit_failures"],
    )
    return counts


async def run(args) -> int:
    async with async_session() as db:
        buy_brand = await _lookup_brand(db, "BUY")
        snow_brand = await _lookup_brand(db, "SNOW")
        if not args.no_buy and buy_brand is None:
            log.error("Brand with prod_code='BUY' not found in DB. Aborting.")
            return 1
        if not args.no_snow and snow_brand is None:
            log.error("Brand with prod_code='SNOW' not found in DB. Aborting.")
            return 1

        if not args.no_buy:
            log.info("=== Processing BUY parts master: %s ===", args.buy_csv)
            await _process_csv(
                db, Path(args.buy_csv), "BUY", buy_brand,
                dry_run=args.dry_run, limit=args.limit,
                commit_batch=args.commit_batch,
                update_existing=args.update_existing,
                include_inactive=args.include_inactive,
                hide_new=not args.visible,
                all_active=args.all_active,
            )

        if not args.no_snow:
            log.info("=== Processing SNOW parts master: %s ===", args.snow_csv)
            await _process_csv(
                db, Path(args.snow_csv), "SNOW", snow_brand,
                dry_run=args.dry_run, limit=args.limit,
                commit_batch=args.commit_batch,
                update_existing=args.update_existing,
                include_inactive=args.include_inactive,
                hide_new=not args.visible,
                all_active=args.all_active,
            )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--buy-csv", default=str(DEFAULT_BUY_CSV),
                        help="Path to buy_parts_master.csv")
    parser.add_argument("--snow-csv", default=str(DEFAULT_SNOW_CSV),
                        help="Path to snow_parts_master.csv")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report counts without writing")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N rows per CSV (for testing)")
    parser.add_argument("--commit-batch", type=int, default=500,
                        help="Commit every N writes (default: 500)")
    parser.add_argument("--update-existing", action="store_true",
                        help="For existing SKUs, fill NULL columns only "
                             "(default: skip existing entirely)")
    parser.add_argument("--include-inactive", action="store_true",
                        help="Import rows with status != 'A' (default: skip)")
    parser.add_argument("--visible", action="store_true",
                        help="Insert new products with is_hidden=false "
                             "(default: hidden, curate later)")
    parser.add_argument("--all-active", action="store_true",
                        help="Set is_for_sale=true on all new products "
                             "regardless of CSV status field")
    parser.add_argument("--no-buy", action="store_true",
                        help="Skip the buy_parts_master.csv pass")
    parser.add_argument("--no-snow", action="store_true",
                        help="Skip the snow_parts_master.csv pass")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
