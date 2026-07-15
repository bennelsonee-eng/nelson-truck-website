"""import_duralift_landings.py — Apply the rich landing-page data to Titan.

Reads duralift_landings.json (produced by scrape_duralift_landings.py)
and:

1) Updates the existing 22 product card_copy + hero_image with the
   richer landing-page versions (better-sized card thumbs + cleaner
   marketing copy).

2) Inserts 3 new products that the sitemap missed but appear on the
   /products/category/tracked-lifts/ landing page:
     tracked-lift-dpm-52du
     tracked-lift-dpm2-52du
     tracked-lift-dpm2-52du-2

3) Creates 4 sub-categories under Aerial Lifts and Bucket Trucks
   (matching Dur-A-Lift's own taxonomy):
     Articulated Aerial Lifts
     Telescopic Bucket Trucks
     Telescopic Bucket Vans
     Tracked Aerial Lifts
   And cross-lists each product to the sub-cat(s) it appears under on
   dur-a-lift.com (mirrors their drill-down structure exactly).

4) Updates the Aerial Lifts and Bucket Trucks parent category's
   description with the marketing intro paragraph from the master
   /products/category/products/ landing.

5) Updates each sub-category's description with its specific intro.

The custom landing-page React component picks up all of this and
renders the Dur-A-Lift-style hero + grid layout.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import asyncpg


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("dal_lp")

DATA = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps"
LANDINGS_JSON = DATA / "duralift_landings.json"

# Sub-category configuration — name + slug + intro key + parent
SUBCAT_CONFIG = {
    "articulated": {
        "name": "Articulated Aerial Lifts",
        "slug_suffix": "articulated-aerial-lifts",
    },
    "telescopic_trucks": {
        "name": "Telescopic Bucket Trucks",
        "slug_suffix": "telescopic-bucket-trucks",
    },
    "telescopic_van": {
        "name": "Telescopic Bucket Vans",
        "slug_suffix": "telescopic-bucket-vans",
    },
    "tracked": {
        "name": "Tracked Aerial Lifts",
        "slug_suffix": "tracked-aerial-lifts",
    },
}


async def ensure_subcategory(conn: asyncpg.Connection, parent_id: int, parent_path: str,
                             parent_depth: int, name: str, slug_suffix: str,
                             description: str) -> int:
    full_path = f"{parent_path} > {name}"
    existing = await conn.fetchval(
        "SELECT id FROM category WHERE full_path = $1", full_path
    )
    if existing:
        await conn.execute(
            "UPDATE category SET description = $1, updated_at = NOW() WHERE id = $2",
            description, existing,
        )
        return existing
    new_id = await conn.fetchval(
        """
        INSERT INTO category (name, slug, parent_id, full_path, depth,
                              description, sort_order, is_featured, is_active,
                              created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, 100, FALSE, TRUE, NOW(), NOW())
        RETURNING id
        """,
        name, slug_suffix, parent_id, full_path, parent_depth + 1, description,
    )
    log.info("Created subcategory: %s (id=%d)", full_path, new_id)
    return new_id


def build_kit_name(slug: str, card_name: str) -> str:
    return card_name


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        data = json.loads(LANDINGS_JSON.read_text(encoding="utf-8"))
        landings = data["landings"]
        products = data["products_by_slug"]

        # 1) Update the Aerial Lifts and Bucket Trucks parent category
        all_intro = (landings.get("all_products") or {}).get("intro_text", "")
        parent_row = await conn.fetchrow(
            "SELECT id, full_path, depth FROM category WHERE full_path = "
            "'Truck Equipment > Aerial Lifts and Bucket Trucks'"
        )
        if not parent_row:
            log.error("Missing Aerial Lifts and Bucket Trucks category — run "
                      "restructure_utility_aerial.py first")
            return
        parent_id = parent_row["id"]
        await conn.execute(
            """
            UPDATE category SET
                description = $1,
                curated_image_url = $2,
                updated_at = NOW()
            WHERE id = $3
            """,
            all_intro or None,
            "https://dur-a-lift.com/wp-content/uploads/2021/07/dlt2-60-bucket-truck-w.png",
            parent_id,
        )
        log.info("Updated parent cat %d intro (%d chars)", parent_id, len(all_intro))

        # 2) Create / update sub-categories
        subcat_id_by_key: dict[str, int] = {}
        for key, cfg in SUBCAT_CONFIG.items():
            intro = (landings.get(key) or {}).get("intro_text", "")
            sub_id = await ensure_subcategory(
                conn,
                parent_id=parent_id,
                parent_path=parent_row["full_path"],
                parent_depth=parent_row["depth"],
                name=cfg["name"],
                slug_suffix=cfg["slug_suffix"],
                description=intro,
            )
            subcat_id_by_key[key] = sub_id

        # 3) Find brand id
        brand_id = await conn.fetchval(
            "SELECT id FROM brand WHERE name = 'Dur-A-Lift'"
        )
        if not brand_id:
            log.error("Dur-A-Lift brand missing")
            return

        # 4) Walk every scraped product
        upserts = inserts = imgs_updated = links = 0
        for slug, p in products.items():
            sku = f"DRL-{slug.upper()}"[:64]
            name = p["name"]
            card_copy = (p.get("card_copy") or "").strip()
            hero = (p.get("hero_image") or "").strip()
            appears_in = p.get("appears_in", [])

            # Insert if missing (the 3 tracked-lift-* are new)
            pid = await conn.fetchval("SELECT id FROM product WHERE sku = $1", sku)
            if pid is None:
                # New product
                pid = await conn.fetchval(
                    """
                    INSERT INTO product (sku, brand_id, name, description,
                        legacy_wsm_url, cta_mode, requires_shipping, taxable,
                        own_box, ship_quote, free_ground, is_hidden, is_for_sale,
                        login_required, saleprice_hidden, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, 'QUOTE_SHIPPING', TRUE, TRUE,
                        FALSE, TRUE, 0, FALSE, TRUE, FALSE, FALSE, NOW(), NOW())
                    RETURNING id
                    """,
                    sku, brand_id, name[:500], card_copy[:500] or name,
                    f"https://dur-a-lift.com/products/{slug}/",
                )
                inserts += 1
                log.info("INSERT %s — %s", sku, name)
            else:
                # Update description if the card has richer copy
                if card_copy and len(card_copy) > 30:
                    await conn.execute(
                        "UPDATE product SET description = $1, updated_at = NOW() WHERE id = $2",
                        card_copy[:500], pid,
                    )
                    upserts += 1

            # Replace the primary image with the landing-page card image
            # (these are properly-sized 400-1024px web thumbs; existing
            # primary may be a giant 1500px file or the og:image variant).
            if hero:
                # If a primary image already exists, swap its URL; else insert
                existing_primary = await conn.fetchval(
                    "SELECT id FROM product_image WHERE product_id = $1 AND is_primary = TRUE",
                    pid,
                )
                if existing_primary:
                    await conn.execute(
                        "UPDATE product_image SET url = $1, alt_text = $2, updated_at = NOW() "
                        "WHERE id = $3",
                        hero, name[:200], existing_primary,
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO product_image (product_id, url, alt_text,
                            sort_order, is_primary, created_at, updated_at)
                        VALUES ($1, $2, $3, 0, TRUE, NOW(), NOW())
                        ON CONFLICT DO NOTHING
                        """,
                        pid, hero, name[:200],
                    )
                imgs_updated += 1

            # Cross-link to each sub-cat the product appears under on dur-a-lift.com
            for key in appears_in:
                if key == "all_products":
                    # Already in the parent
                    await conn.execute(
                        """
                        INSERT INTO product_category (product_id, category_id, is_primary,
                            created_at, updated_at)
                        VALUES ($1, $2, TRUE, NOW(), NOW())
                        ON CONFLICT (product_id, category_id) DO NOTHING
                        """,
                        pid, parent_id,
                    )
                    continue
                sub_id = subcat_id_by_key.get(key)
                if sub_id:
                    await conn.execute(
                        """
                        INSERT INTO product_category (product_id, category_id, is_primary,
                            created_at, updated_at)
                        VALUES ($1, $2, FALSE, NOW(), NOW())
                        ON CONFLICT (product_id, category_id) DO NOTHING
                        """,
                        pid, sub_id,
                    )
                    links += 1

        log.info("Done.  inserts=%d updates=%d images_set=%d subcat_links=%d",
                 inserts, upserts, imgs_updated, links)
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
