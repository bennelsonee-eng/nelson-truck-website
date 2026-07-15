"""reclassify_kargomaster.py — fix the bulk-import miscategorization of the
Kargo Master brand.

Background
----------
All 129 Kargo Master products were imported with IDENTICAL category mappings
regardless of what each product actually is:
  * PRIMARY     = "Van Equipment > Van Shelving"   (all 129)
  * cross-list  = "Truck Accessories > Cargo Management > Ladder Racks"  (all)
  * cross-list  = "Truck Accessories > Cargo Management > Truck and Van Racks"

So the Ladder Racks page showed the whole brand dumped in (racks + partitions
+ shelving + floor mats + filing systems), and Van Shelving was wrong for most
of them. Owner-approved 2026-06-09: reclassify each product by its actual type
into the correct PRIMARY category and drop the indiscriminate cross-lists.

Target taxonomy (per product type):
  Ladder Racks (Truck Accessories > Cargo Management > Ladder Racks)
      truck/ladder/cargo racks, Pro II/III & Pro Rack systems, crossbars,
      side channels, window guards, drop-down ladder racks, rack mount kits,
      rack ratchet straps/brackets. PRIMARY here + cross-listed to
      "Truck and Van Racks".
  Cab Partitions and Dividers (Van Equipment)   steel/perforated/composite
      partitions + partition wing kits.
  Van Shelving (Van Equipment)                  shelves, cabinets, drawers,
      bins, lockers, filing systems, hooks, dividers.
  Van Accessories (Van Equipment)               floor mats, grab handles,
      bed rails, window screens.

Classification matches the product-type LEAD (first 50 chars of the name) —
these names are AI-generated sentences, so matching the whole string pulls in
incidental keywords ("...with integrated bed rails...") from deep in the
description. A second pass will clean up the names themselves.

Idempotent: rewrites each product's membership in the 5 managed categories to
the computed target set (delete-managed + insert-desired in one txn), so a
re-run lands on the same state. A backup CSV of the prior rows is written
first for reversibility.

Usage
-----
    python app/scripts/reclassify_kargomaster.py            # dry run
    python app/scripts/reclassify_kargomaster.py --apply    # commit

DSN comes from $DATABASE_URL (the +asyncpg prefix is stripped), falling back
to the dev default (which on titan-prod is the live titan_web).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("km_reclassify")

BRAND = "Kargo Master"

# Category full_paths involved (all must already exist).
LADDER = "Truck Accessories > Cargo Management > Ladder Racks"
TRUCKVAN = "Truck Accessories > Cargo Management > Truck and Van Racks"
CABPART = "Van Equipment > Cab Partitions and Dividers"
SHELVING = "Van Equipment > Van Shelving"
VANACC = "Van Equipment > Van Accessories"

# Desired membership per bucket: list of (category_full_path, is_primary).
DESIRED: dict[str, list[tuple[str, bool]]] = {
    "Ladder Racks": [(LADDER, True), (TRUCKVAN, False)],
    "Cab Partitions": [(CABPART, True)],
    "Van Shelving": [(SHELVING, True)],
    "Van Accessories": [(VANACC, True)],
}

# Products whose generic lead doesn't reveal the type — pinned by SKU.
OVERRIDE = {
    "KAR-31170": "Ladder Racks",  # "Heavy-duty mounting bracket ... emergency lights to Kargo Master racks"
}


def classify(sku: str, name: str) -> str:
    if sku in OVERRIDE:
        return OVERRIDE[sku]
    n = name[:50].lower()  # match the product-type lead, not the AI description body
    has = lambda *ws: any(w in n for w in ws)
    if has("partition", "wing kit"):
        return "Cab Partitions"
    if has("shelf", "shelving", "cabinet", "locker", "drawer", "storage bin",
           "bin holder", "standing bin", "reel holder", "filing", "j-hook",
           "swivel", "hook -", "bottle restraint", "divider", "floor angle",
           "three-tier", "folding shelf", "door kit"):
        return "Van Shelving"
    if has("floor mat", "vantred", "grab handle", "bed rail", "window screen"):
        return "Van Accessories"
    if has("rack", "crossbar", "cross bar", "side channel", "pro ii", "pro iii",
           "pro rack", "window guard", "drop-down", "drop down", "ladder",
           "hoop", "leg & bar", "leg and bar", "leg and crossbar",
           "leg & crossbar", "leg exten", "roller bar", "rail mounting",
           "mount kit", "mounting kit", "removable bar", "deflector",
           "tri-knob", "retractable", "ratchet"):
        return "Ladder Racks"
    # Should not happen (verified 0 leftover); default to keeping it in Ladder
    # Racks rather than dropping it from the catalog.
    log.warning("Unclassified %s: %s — defaulting to Ladder Racks", sku, name[:60])
    return "Ladder Racks"


def resolve_dsn() -> str:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    return dsn


async def main(apply: bool) -> None:
    conn = await asyncpg.connect(resolve_dsn())
    try:
        # Resolve the 5 managed category ids by full_path.
        paths = [LADDER, TRUCKVAN, CABPART, SHELVING, VANACC]
        id_by_path: dict[str, int] = {}
        for p in paths:
            cid = await conn.fetchval("SELECT id FROM category WHERE full_path = $1", p)
            if cid is None:
                log.error("Category not found: %s — aborting.", p)
                return
            id_by_path[p] = cid
        managed_ids = sorted(set(id_by_path.values()))

        # Fetch the brand's products.
        prods = await conn.fetch(
            """
            SELECT p.id, p.sku, p.name
            FROM product p JOIN brand b ON b.id = p.brand_id
            WHERE b.name = $1
            ORDER BY p.name
            """,
            BRAND,
        )
        log.info("%s: %d products", BRAND, len(prods))

        counts: Counter = Counter()
        plan: list[tuple[int, list[tuple[int, bool]]]] = []  # (product_id, [(cat_id, is_primary)])
        for r in prods:
            bucket = classify(r["sku"], r["name"])
            counts[bucket] += 1
            desired = [(id_by_path[fp], prim) for fp, prim in DESIRED[bucket]]
            plan.append((r["id"], desired))

        for bucket in ("Ladder Racks", "Cab Partitions", "Van Shelving", "Van Accessories"):
            dest = ", ".join(f"{id_by_path[fp]}{'*' if prim else ''}" for fp, prim in DESIRED[bucket])
            log.info("  %4d  ->  %-16s (cat ids: %s; * = primary)", counts.get(bucket, 0), bucket, dest)

        if not apply:
            log.info("DRY RUN — no changes written. Re-run with --apply to commit.")
            return

        # Backup current managed-category rows for these products.
        pids = [r["id"] for r in prods]
        cur_rows = await conn.fetch(
            """
            SELECT product_id, category_id, is_primary
            FROM product_category
            WHERE product_id = ANY($1::int[]) AND category_id = ANY($2::int[])
            ORDER BY product_id, category_id
            """,
            pids, managed_ids,
        )
        backups_dir = Path(__file__).resolve().parents[2] / "backups" / "kargomaster_reclassify"
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backups_dir / f"kargomaster_membership_{stamp}.csv"
        with backup_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["product_id", "category_id", "is_primary"])
            for row in cur_rows:
                w.writerow([row["product_id"], row["category_id"], row["is_primary"]])
        log.info("Backup written: %s (%d prior rows)", backup_path, len(cur_rows))

        # Apply: rewrite managed-category membership deterministically.
        async with conn.transaction():
            for pid, desired in plan:
                await conn.execute(
                    "DELETE FROM product_category WHERE product_id = $1 AND category_id = ANY($2::int[])",
                    pid, managed_ids,
                )
                for cat_id, is_primary in desired:
                    await conn.execute(
                        """
                        INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
                        VALUES ($1, $2, $3, NOW(), NOW())
                        """,
                        pid, cat_id, is_primary,
                    )
        log.info("Applied. Rewrote managed-category membership for %d products.", len(plan))
        log.info("Reindex Typesense if search category facets need to reflect this.")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Reclassify Kargo Master products by product type.")
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry run).")
    args = ap.parse_args()
    asyncio.run(main(args.apply))
