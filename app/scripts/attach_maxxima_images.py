"""attach_maxxima_images.py — Insert ProductImage rows for Maxxima products.

Reads app/data/mysql_dumps/maxxima_catalog.json (the 910-product scrape
of maxxima.com category pages, enriched with primary image URLs by
extract_maxxima_images.py).

For each scraped product whose sku matches a Titan product (`MAXX-{sku}`),
upserts a single primary ProductImage row pointing at the maxxima.com URL.
Cross-domain image hosting is fine per the Phase 1 image-strategy
decision (DI-029 in OPERATIONS_NOTES.md) — same approach we use for
nelsontruck.com WSM-legacy product images today.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("attach_imgs")

CATALOG = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps" / "maxxima_catalog.json"


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        if not CATALOG.exists():
            log.error("Missing %s", CATALOG)
            return

        scrape = json.loads(CATALOG.read_text(encoding="utf-8"))
        scrape_by_sku: dict[str, dict] = {}
        for p in scrape:
            scrape_by_sku[(p.get("sku") or "").upper()] = p
        log.info("Maxxima scrape entries: %d", len(scrape_by_sku))

        # Resolve every Maxxima product on Titan (brand_id known)
        brand_id = await conn.fetchval(
            "SELECT id FROM brand WHERE prod_code = 'MAXX'"
        )
        if not brand_id:
            log.error("Maxxima brand row not found — run import_brand_catalog.py first")
            return

        products = await conn.fetch(
            "SELECT id, sku FROM product WHERE brand_id = $1", brand_id
        )
        log.info("Maxxima products on Titan: %d", len(products))

        inserted = 0
        skipped_no_match = 0
        skipped_existing = 0
        for prod in products:
            pid = prod["id"]
            sku = prod["sku"]  # MAXX-{parts_num}
            # The MAXX- prefix matches the scrape's `sku` field exactly
            scrape_sku = sku.replace("MAXX-", "", 1).upper()
            scrape_entry = scrape_by_sku.get(scrape_sku)
            if not scrape_entry:
                # Some Maxxima parts_num have dashes; the scrape SKU might too.
                # Try alternate forms.
                alt = scrape_sku.replace("-", "")
                scrape_entry = scrape_by_sku.get(alt)
            if not scrape_entry or not scrape_entry.get("image_url"):
                skipped_no_match += 1
                continue

            existing = await conn.fetchval(
                "SELECT 1 FROM product_image WHERE product_id = $1 AND url = $2",
                pid, scrape_entry["image_url"],
            )
            if existing:
                skipped_existing += 1
                continue

            await conn.execute(
                "INSERT INTO product_image (product_id, url, alt_text, sort_order, "
                "is_primary, created_at, updated_at) "
                "VALUES ($1, $2, $3, 0, TRUE, NOW(), NOW())",
                pid, scrape_entry["image_url"], scrape_entry.get("description_text", "")[:200] or sku,
            )
            inserted += 1

        log.info("Done: inserted=%d, skipped_no_match=%d, skipped_existing=%d",
                 inserted, skipped_no_match, skipped_existing)
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
