"""ingest_truck_bodies_from_titan.py — pull the Truck Bodies catalog
from titantruck.com's Solr index and seed our DB with:
  - 5 new brands (Knapheide, CM Truck Beds, Rugby, EZ Dumper, Morgan Truck Body)
  - 1 new parent category "Truck Bodies" under Truck Equipment
  - 6 subcategories under Truck Bodies (Flatbeds, Service/Utility, Dump,
    Stake, Van/Box, Body Hoists)
  - 66 products (one per Solr product_series group)

Data source: https://www.titantruck.com/solr/ttdev/select  (titantruck.com
is owned by Titan; this script migrates Titan's own product catalog
into the replacement website's DB.)

Run order:
  python -m httpx        # smoke check
  python app/scripts/ingest_truck_bodies_from_titan.py --dry-run  # preview
  python app/scripts/ingest_truck_bodies_from_titan.py            # apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import asyncpg

DEFAULT_DB = os.environ.get(
    "DATABASE_URL_PSYCOPG",
    "postgresql://postgres:nelson2026@localhost:5432/titan_web",
)
SOLR_JSON = Path(__file__).resolve().parents[2] / "discovery" / "crawl_truck_bodies" / "solr_raw.json"
IMAGE_BASE = "https://www.titantruck.com/images"
SERIES_BASE = "https://www.titantruck.com/series-"  # series-{id}.html

# ---------------------------------------------------------------------
# Classifier — maps a series title to one of 6 subcategory names.
# Order matters: more-specific patterns first.
# ---------------------------------------------------------------------
SUBCAT_RULES = [
    ("Body Hoists", ["hoist"]),
    ("Dump Bodies", ["dump", "dumper", "rancher", "tailgate keeper", "tarp kit"]),
    ("Van / Box Bodies", ["box truck", "dry freight", "mini-mover", "van body"]),
    ("Service / Utility Bodies", [
        "service body", "utility body", "mechanic's", "mechanic body",
        "kuv", "tradesmen", "welder body", "enclosed service",
        "fliptop", "low pro service", "low profile",
    ]),
    ("Stake Bodies", [
        "contractor", "stake", "concrete", "landscape", "landscaper",
        "forestry", "saw body", "gin pole", "drop side", "fixed side",
    ]),
    ("Flatbeds", [
        "platform", "flat deck", "flatbed", "hauler", "skirted",
        "hay squeeze", "gooseneck", "line body", "bobtail",
        "cargo-hauler", "value-master", "heavy-hauler",
        "conventional line",
    ]),
]


def classify(title: str) -> str:
    t = title.lower()
    for cat_name, keywords in SUBCAT_RULES:
        for kw in keywords:
            if kw in t:
                return cat_name
    return "Flatbeds"  # safest default for unclassified bodies


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:80] or "x"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Show counts but don't write")
    ap.add_argument("--db", default=DEFAULT_DB, help="Postgres URL (psycopg-style)")
    args = ap.parse_args()

    if not SOLR_JSON.exists():
        print(f"ERR: solr dump not found at {SOLR_JSON}")
        sys.exit(1)

    d = json.loads(SOLR_JSON.read_text(encoding="utf-8"))
    groups = d["grouped"]["product_series"]["groups"]
    print(f"Parsed {len(groups)} product-series groups from Solr dump.")

    # Resolve each series to one row + classify
    series_rows: list[dict] = []
    subcat_counts: dict[str, int] = {}
    brands_seen = set()
    for g in groups:
        first = g["doclist"]["docs"][0]
        brand = first.get("brand", "?")
        series_id = first.get("product_series")
        series_title = first.get("product_series_title") or first.get("title") or "?"
        # Strip the "Brand | " prefix from titles where present so the
        # product name reads cleanly under a Brand row.
        clean_name = re.sub(rf"^{re.escape(brand)}\s*\|\s*", "", series_title)
        material = first.get("material")
        if isinstance(material, list):
            material = "/".join(material)
        elif material is None:
            material = ""
        img_filename = first.get("product_series_image") or (
            first.get("image", [None])[0] if isinstance(first.get("image"), list) else first.get("image")
        )
        image_url = f"{IMAGE_BASE}/{img_filename}" if img_filename else None
        url = f"{SERIES_BASE}{series_id}.html" if series_id else None
        subcat = classify(series_title)
        subcat_counts[subcat] = subcat_counts.get(subcat, 0) + 1
        brands_seen.add(brand)

        # SKU on our side: BRAND_PREFIX + series id  (e.g. KNP-S15781)
        prefix = {
            "Knapheide": "KNP",
            "CM Truck Beds": "CMT",
            "Rugby": "RUG",
            "EZ Dumper": "EZD",
            "Morgan Truck Body": "MOR",
        }.get(brand, "TTE")
        sku = f"{prefix}-S{series_id}"
        prod_code = f"S{series_id}"
        series_rows.append(
            dict(
                brand=brand,
                sku=sku,
                prod_code=prod_code,
                name=clean_name,
                material=material,
                image_url=image_url,
                url_legacy=url,
                subcat=subcat,
            )
        )

    print("Distribution:")
    for k in ("Flatbeds", "Service / Utility Bodies", "Dump Bodies",
              "Stake Bodies", "Van / Box Bodies", "Body Hoists"):
        print(f"  {k:<30} {subcat_counts.get(k, 0):>3}")
    print(f"Brands needed: {sorted(brands_seen)}")

    if args.dry_run:
        print("\n(dry run) — no DB changes.")
        return

    # ---------------- Apply to DB ----------------
    conn = await asyncpg.connect(args.db)
    try:
        async with conn.transaction():
            # 1. Truck Equipment parent must exist
            te_id = await conn.fetchval(
                "SELECT id FROM category WHERE name = 'Truck Equipment' AND parent_id IS NULL"
            )
            if te_id is None:
                raise RuntimeError("Truck Equipment top-level category not found")
            print(f"  Truck Equipment cat: id={te_id}")

            # 2. Truck Bodies parent (under Truck Equipment)
            tb_id = await conn.fetchval(
                """
                INSERT INTO category (name, slug, parent_id, depth, full_path,
                                      sort_order, is_featured, is_active,
                                      created_at, updated_at)
                VALUES ('Truck Bodies', 'truck-bodies', $1, 1,
                        'Truck Equipment > Truck Bodies',
                        100, FALSE, TRUE, NOW(), NOW())
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                te_id,
            )
            if tb_id is None:
                tb_id = await conn.fetchval(
                    "SELECT id FROM category WHERE name = 'Truck Bodies' AND parent_id = $1",
                    te_id,
                )
            print(f"  Truck Bodies cat:   id={tb_id}")

            # 3. 6 subcategories
            subcat_names = [
                "Flatbeds", "Service / Utility Bodies", "Dump Bodies",
                "Stake Bodies", "Van / Box Bodies", "Body Hoists",
            ]
            subcat_id_by_name = {}
            for idx, name in enumerate(subcat_names):
                slug = slugify(name)
                full_path = f"Truck Equipment > Truck Bodies > {name}"
                row_id = await conn.fetchval(
                    """
                    INSERT INTO category (name, slug, parent_id, depth, full_path,
                                          sort_order, is_featured, is_active,
                                          created_at, updated_at)
                    VALUES ($1, $2, $3, 2, $4, $5, FALSE, TRUE, NOW(), NOW())
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """,
                    name, slug, tb_id, full_path, (idx + 1) * 10,
                )
                if row_id is None:
                    row_id = await conn.fetchval(
                        "SELECT id FROM category WHERE name = $1 AND parent_id = $2",
                        name, tb_id,
                    )
                subcat_id_by_name[name] = row_id
                print(f"    subcat: {name:<28} id={row_id}")

            # 4. Brands (upsert by name)
            brand_id_by_name: dict[str, int] = {}
            for brand in sorted(brands_seen):
                slug = slugify(brand)
                row_id = await conn.fetchval(
                    """
                    INSERT INTO brand (name, slug, is_active, is_featured,
                                       sort_order, created_at, updated_at)
                    VALUES ($1, $2, TRUE, FALSE, 100, NOW(), NOW())
                    ON CONFLICT (slug) DO UPDATE SET is_active = TRUE
                    RETURNING id
                    """,
                    brand, slug,
                )
                brand_id_by_name[brand] = row_id
                print(f"  brand: {brand:<25} id={row_id}")

            # 5. Products
            print(f"\nInserting {len(series_rows)} products...")
            inserted = 0
            for r in series_rows:
                bid = brand_id_by_name[r["brand"]]
                # Insert/update product
                pid = await conn.fetchval(
                    """
                    INSERT INTO product (brand_id, sku, name, prod_code,
                                         cta_mode, requires_shipping, taxable,
                                         own_box, ship_quote, free_ground,
                                         is_for_sale, is_hidden, login_required,
                                         saleprice_hidden,
                                         created_at, updated_at)
                    VALUES ($1, $2, $3, $4,
                            'QUOTE_SHIPPING', TRUE, TRUE,
                            FALSE, TRUE, 0,
                            TRUE, FALSE, FALSE,
                            FALSE,
                            NOW(), NOW())
                    ON CONFLICT (sku) DO UPDATE SET
                        name = EXCLUDED.name,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    bid, r["sku"], r["name"], r["prod_code"],
                )
                # Tag with subcategory
                await conn.execute(
                    """
                    INSERT INTO product_category (product_id, category_id, is_primary,
                                                  created_at, updated_at)
                    VALUES ($1, $2, TRUE, NOW(), NOW())
                    ON CONFLICT (product_id, category_id) DO NOTHING
                    """,
                    pid, subcat_id_by_name[r["subcat"]],
                )
                # Attach primary image if we have one
                if r["image_url"]:
                    await conn.execute(
                        """
                        INSERT INTO product_image (product_id, url, is_primary,
                                                   sort_order, created_at, updated_at)
                        VALUES ($1, $2, TRUE, 0, NOW(), NOW())
                        ON CONFLICT DO NOTHING
                        """,
                        pid, r["image_url"],
                    )
                inserted += 1
            print(f"  inserted/updated {inserted} products")

        # Verification (outside the txn so we see committed state)
        cnt = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT p.id)
            FROM product p
            JOIN product_category pc ON pc.product_id = p.id
            JOIN category c ON c.id = pc.category_id
            WHERE c.full_path LIKE 'Truck Equipment > Truck Bodies > %'
            """
        )
        print(f"\nFinal: {cnt} products sit under Truck Equipment > Truck Bodies > ...")
        # Per-subcat counts
        rows = await conn.fetch(
            """
            SELECT c.full_path, COUNT(DISTINCT pc.product_id) AS n
            FROM category c
            LEFT JOIN product_category pc ON pc.category_id = c.id
            WHERE c.full_path LIKE 'Truck Equipment > Truck Bodies%'
            GROUP BY c.full_path ORDER BY c.full_path
            """
        )
        for r in rows:
            print(f"  {r['n']:>3}  {r['full_path']}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
