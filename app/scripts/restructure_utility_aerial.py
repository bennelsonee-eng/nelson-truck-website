"""restructure_utility_aerial.py — Fix the Utility/Aerial department.

Owner ask 2026-05-14: "Utility/Aerial department was populated with a
bunch of items that do not belong.  This will primarily be for
Dur-a-lift products."

The previous categorization pass routed snow plows, salt spreaders, and
Knapheide truck parts INTO Utility Truck Equipment subcategories, which
front-end mega menu surfaces under "Utility & Aerial".  This script:

1. Creates three new top-level Truck Equipment subcategories:
      Truck Equipment > Snow Plows
      Truck Equipment > Salt Spreaders and Hoppers
      Truck Equipment > Aerial Lifts and Bucket Trucks
2. Re-routes existing snow plow products (cat 367) → new Snow Plows cat.
3. Re-routes SaltDogg / SaltSpreader products (cat 366 + name-matched
   under BUY/SNOW brands) → new Salt Spreaders cat.
4. Removes the catch-all BUY → Utility-Truck-Equipment-root (cat 20)
   primary link.  BUY products keep their other category links.
5. Imports the 22-product Dur-a-Lift catalog (scraped from
   dur-a-lift.com by scrape_duralift_catalog.py) as a new brand under
   the new Aerial Lifts cat, with cta_mode=QUOTE_SHIPPING (these are
   bucket trucks — quote-only big-ticket items, like the Truck Bodies
   import on 2026-05-12).

Idempotent — ON CONFLICT DO NOTHING / safe to re-run.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

import asyncpg


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("restructure")


DURALIFT_JSON = (Path(__file__).resolve().parent.parent / "data" / "mysql_dumps" / "duralift_catalog.json")

# Existing category IDs we're moving products out of.
UTIL_SNOW_PLOWS_OLD = 367   # Utility Truck Equipment > Snow Plows and Accessories
UTIL_SALT_SPREADERS_OLD = 366  # Utility Truck Equipment > Salt Spreaders and Accessories
UTIL_DUMP_BEDS_OLD = 371   # Utility Truck Equipment > Truck Dump Beds and Accessories
UTIL_ROOT = 20             # Utility Truck Equipment

# Truck Equipment root for the new categories.  Resolved at runtime by
# full_path lookup since this varies in dev data.
TRUCK_EQUIPMENT_PATH = "Truck Equipment"


async def ensure_category(conn: asyncpg.Connection, *, name: str, parent_id: int,
                          parent_full_path: str, slug_suffix: str,
                          description: str) -> int:
    full_path = f"{parent_full_path} > {name}"
    existing = await conn.fetchval(
        "SELECT id FROM category WHERE full_path = $1", full_path
    )
    if existing:
        log.info("Category exists: %s (id=%d)", full_path, existing)
        return existing
    parent_depth = (await conn.fetchval(
        "SELECT depth FROM category WHERE id = $1", parent_id
    )) or 0
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
    log.info("Created category: %s (id=%d)", full_path, new_id)
    return new_id


async def move_links(conn: asyncpg.Connection, from_cat: int, to_cat: int,
                     where_extra: str = "") -> int:
    """INSERT a link to to_cat for each product currently linked to from_cat,
    then DELETE the from_cat link.  Returns count of products moved."""
    moved = await conn.fetchval(
        f"""
        WITH src AS (
            SELECT pc.product_id FROM product_category pc
            JOIN product p ON p.id = pc.product_id
            WHERE pc.category_id = $1 {where_extra}
        ),
        ins AS (
            INSERT INTO product_category (product_id, category_id, is_primary,
                                          created_at, updated_at)
            SELECT product_id, $2, TRUE, NOW(), NOW() FROM src
            ON CONFLICT (product_id, category_id) DO NOTHING
            RETURNING product_id
        ),
        del AS (
            DELETE FROM product_category pc
            USING src WHERE pc.category_id = $1 AND pc.product_id = src.product_id
            RETURNING pc.product_id
        )
        SELECT COUNT(*) FROM (SELECT product_id FROM ins UNION SELECT product_id FROM del) x
        """,
        from_cat, to_cat,
    )
    return int(moved or 0)


def parse_size_from_main(text: str) -> dict[str, str]:
    """Pull a few high-signal specs out of the scraped marketing text."""
    out: dict[str, str] = {}
    for label, regex in [
        ("working_height", r"[Ww]orking height\s*[:\-]?\s*([0-9'\"\\.\s\-]+)"),
        ("side_reach", r"[Ss]ide reach\s*[:\-]?\s*([0-9'\"\\.\s\-]+)"),
        ("platform_capacity", r"[Pp]latform capacity[^:]*[:\-]\s*([0-9#a-z\s]+)"),
        ("approx_weight", r"[Aa]pprox[^:]*weight\s*[:\-]?\s*([0-9#a-z\s]+)"),
    ]:
        m = re.search(regex, text)
        if m:
            out[label] = m.group(1).strip()[:60]
    return out


async def import_duralift(conn: asyncpg.Connection, aerial_cat_id: int) -> int:
    if not DURALIFT_JSON.exists():
        log.warning("Missing %s — skipping Dur-a-Lift import", DURALIFT_JSON)
        return 0

    # Brand row
    brand_id = await conn.fetchval(
        "SELECT id FROM brand WHERE name = 'Dur-A-Lift'"
    )
    if brand_id is None:
        brand_id = await conn.fetchval(
            """
            INSERT INTO brand (name, slug, aaia_code, prod_code, website_url,
                               is_featured, sort_order, is_active,
                               description,
                               created_at, updated_at)
            VALUES ('Dur-A-Lift', 'dur-a-lift', 'DURA', NULL,
                    'https://dur-a-lift.com', TRUE, 50, TRUE,
                    $1,
                    NOW(), NOW())
            RETURNING id
            """,
            "Dur-A-Lift Inc. builds insulated aerial lift platforms, bucket "
            "trucks, and material-handling units used by utility crews, "
            "telecom contractors, urban forestry, and DOT public-works "
            "fleets across North America.  Models range from the compact "
            "DCP cable-placer to the DLT2-60 (DP) long-reach with 60' "
            "working height.",
        )
        log.info("Created Dur-A-Lift brand (id=%d)", brand_id)
    else:
        log.info("Dur-A-Lift brand already exists (id=%d)", brand_id)

    catalog = json.loads(DURALIFT_JSON.read_text(encoding="utf-8"))
    inserted = 0
    updated = 0
    for entry in catalog:
        slug = entry["slug"]
        # SKU uses brand prefix to stay consistent with the v2 linker's
        # naming convention.  No TigerTech inventory match expected (these
        # are quote-only big-ticket items shipped from Dur-A-Lift direct).
        sku = f"DURA-{slug.upper()}"[:64]
        name = entry["name"][:500]
        # Description: og_description as 1-liner; main_text as extended
        short = entry["og_description"] or entry["main_text"][:200] or name
        extended = entry["main_text"]
        existed = await conn.fetchval("SELECT id FROM product WHERE sku = $1", sku)
        if existed:
            await conn.execute(
                """
                UPDATE product SET brand_id = $1, name = $2,
                    description = $3, extended_description = $4,
                    cta_mode = 'QUOTE_SHIPPING', is_for_sale = TRUE,
                    is_hidden = FALSE, updated_at = NOW()
                WHERE id = $5
                """,
                brand_id, name, short, extended, existed,
            )
            pid = existed
            updated += 1
        else:
            pid = await conn.fetchval(
                """
                INSERT INTO product (sku, brand_id, name, description,
                    extended_description, cta_mode, requires_shipping,
                    taxable, own_box, ship_quote, free_ground,
                    is_hidden, is_for_sale, login_required, saleprice_hidden,
                    legacy_wsm_url, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'QUOTE_SHIPPING', TRUE,
                    TRUE, FALSE, TRUE, 0, FALSE, TRUE, FALSE, FALSE,
                    $6, NOW(), NOW())
                RETURNING id
                """,
                sku, brand_id, name, short, extended, entry["url"],
            )
            inserted += 1

        # Category link
        await conn.execute(
            """
            INSERT INTO product_category (product_id, category_id, is_primary,
                                          created_at, updated_at)
            VALUES ($1, $2, TRUE, NOW(), NOW())
            ON CONFLICT (product_id, category_id) DO NOTHING
            """,
            pid, aerial_cat_id,
        )

        # Images — top 3 only
        for idx, img_url in enumerate(entry.get("images", [])[:3]):
            await conn.execute(
                """
                INSERT INTO product_image (product_id, url, alt_text,
                    sort_order, is_primary, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, NOW(), NOW())
                ON CONFLICT DO NOTHING
                """,
                pid, img_url, name[:200], idx, idx == 0,
            )

    log.info("Dur-A-Lift import: inserted=%d, updated=%d (of %d catalog entries)",
             inserted, updated, len(catalog))
    return inserted + updated


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        te = await conn.fetchrow(
            "SELECT id, full_path, depth FROM category WHERE full_path = $1",
            TRUCK_EQUIPMENT_PATH,
        )
        if not te:
            log.error("'%s' not found", TRUCK_EQUIPMENT_PATH)
            return
        log.info("Truck Equipment root: id=%d", te["id"])

        # 1) Create the three new categories under Truck Equipment
        snow_cat = await ensure_category(
            conn, name="Snow Plows", parent_id=te["id"],
            parent_full_path=TRUCK_EQUIPMENT_PATH, slug_suffix="snow-plows",
            description=(
                "Complete snow plow assemblies, mounts, harnesses, lift "
                "frames, moldboards, lights, and replacement parts for the "
                "Western, Meyer Products, and Buyers SnowDogg snow plow "
                "lines.  Year-Make-Model fit guidance lives on the "
                "configurator (in development)."
            ),
        )
        salt_cat = await ensure_category(
            conn, name="Salt Spreaders and Hoppers", parent_id=te["id"],
            parent_full_path=TRUCK_EQUIPMENT_PATH, slug_suffix="salt-spreaders-and-hoppers",
            description=(
                "Hopper-style and tailgate salt spreaders, controllers, "
                "deflectors, and replacement parts for the SaltDogg line "
                "(from Buyers Products) plus competitors stocked at Titan."
            ),
        )
        aerial_cat = await ensure_category(
            conn, name="Aerial Lifts and Bucket Trucks", parent_id=te["id"],
            parent_full_path=TRUCK_EQUIPMENT_PATH, slug_suffix="aerial-lifts-and-bucket-trucks",
            description=(
                "Insulated and material-handling aerial lift platforms and "
                "bucket trucks for utility, telecom, urban forestry, and "
                "public-works applications.  Featuring the full Dur-A-Lift "
                "lineup from DCP cable placers through DLT2-60 long-reach."
            ),
        )

        # 2) Move snow plow products from Utility cat 367 → new Snow Plows cat
        moved = await move_links(conn, UTIL_SNOW_PLOWS_OLD, snow_cat)
        log.info("Moved snow-plow product_category links: %d", moved)

        # 3) Move salt spreader products from Utility cat 366 → new Salt cat
        moved_salt = await move_links(conn, UTIL_SALT_SPREADERS_OLD, salt_cat)
        log.info("Moved salt-spreader product_category links: %d", moved_salt)

        # Additional pass: name-match any SaltDogg / SaltSpreader-named
        # products in BUY or SNOW brands not already linked to salt_cat.
        salt_extra = await conn.execute(
            """
            INSERT INTO product_category (product_id, category_id, is_primary,
                                          created_at, updated_at)
            SELECT p.id, $1, TRUE, NOW(), NOW()
            FROM product p JOIN brand b ON b.id = p.brand_id
            WHERE b.prod_code IN ('BUY', 'SNOW')
              AND (p.name ILIKE '%SaltDogg%'
                   OR p.name ILIKE '%SALT DOGG%'
                   OR p.name ILIKE '%hopper%spread%'
                   OR p.name ILIKE '%tailgate%spread%'
                   OR p.name ILIKE '%spread%control%')
            ON CONFLICT (product_id, category_id) DO NOTHING
            """,
            salt_cat,
        )
        log.info("Name-matched SaltDogg/spreader products: %s", salt_extra)

        # 4) Remove the catch-all BUY → Utility-root link.  These BUY
        # products keep other category links if present.
        del_buy = await conn.execute(
            """
            DELETE FROM product_category pc
            USING product p, brand b
            WHERE pc.product_id = p.id AND p.brand_id = b.id
              AND b.prod_code = 'BUY'
              AND pc.category_id = $1
            """,
            UTIL_ROOT,
        )
        log.info("Removed BUY-product Utility-root links: %s", del_buy)

        # 5) Knapheide: move from Utility > Truck Dump Beds → Truck Equipment > Truck Bodies
        tbod = await conn.fetchval(
            "SELECT id FROM category WHERE full_path = 'Truck Equipment > Truck Bodies'"
        )
        if tbod:
            moved_knp = await conn.execute(
                """
                WITH src AS (
                    SELECT pc.product_id FROM product_category pc
                    JOIN product p ON p.id = pc.product_id
                    JOIN brand b ON b.id = p.brand_id
                    WHERE pc.category_id = $1 AND b.prod_code = 'KNP'
                )
                INSERT INTO product_category (product_id, category_id,
                    is_primary, created_at, updated_at)
                SELECT product_id, $2, FALSE, NOW(), NOW() FROM src
                ON CONFLICT (product_id, category_id) DO NOTHING
                """,
                UTIL_DUMP_BEDS_OLD, tbod,
            )
            log.info("KNP cross-listed to Truck Bodies: %s", moved_knp)

        # 6) Import Dur-A-Lift catalog into the new aerial cat
        await import_duralift(conn, aerial_cat)

        log.info("=" * 60)
        log.info("Done.  Next: re-run reindex_typesense.py and ship App.tsx mega-menu updates.")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
