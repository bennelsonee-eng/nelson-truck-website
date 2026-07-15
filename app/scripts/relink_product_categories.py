"""relink_product_categories.py — idempotent product→category relinker.

Run this after every catalog feed/import. It assigns a category to any
product that currently has NONE, using the live pcdb_part_type mapping —
so newly-imported SKUs flow into the taxonomy without a human running a
one-off script. It is the durable counterpart to the manual fix scripts.

Design (safe by construction):
  * Only touches products with ZERO product_category rows. Existing
    placements (including every manual override from issues #13/#14) are
    never moved or duplicated.
  * Category resolution matches the LEAF by name + its PARENT by name
    (c.name = sub_category_name AND parent.name = category_name), which is
    robust to the 2-level/3-level full_path inconsistency in the tree.
  * Reproduces the Shocks-and-Struts level-4 classifier (Coilover Kits /
    Struts / Shocks) so new shock SKUs land in the right child, not the
    parent. Coilover → Strut → Shock order is enforced via NOT EXISTS.
  * ON CONFLICT DO NOTHING — re-running on an already-placed catalog is a
    no-op (0 inserts), which is the idempotency contract.

Because the PACE scrapers now skip category_locked part types
(add_pcdb_category_lock.sql), the mapping this reads stays correct across
re-scrapes, so new products keep filing into the manual taxonomy.

Run:
    DATABASE_URL=postgresql://postgres:titan2026@localhost:5433/titan_web \\
        python app/scripts/relink_product_categories.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import asyncpg

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("relink")

SHOCKS_PARENT = "Truck Accessories > Suspension > Shocks and Struts"
COILOVER_FP = SHOCKS_PARENT + " > Coilover Kits"
STRUTS_FP = SHOCKS_PARENT + " > Struts"
SHOCKS_FP = SHOCKS_PARENT + " > Shocks"

# 1) Standard part-type → leaf-category links, for UNLINKED products only.
#    Excludes the Shocks-and-Struts subtree (handled by the classifier below).
SQL_STANDARD = """
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT DISTINCT pp.product_id, c.id, FALSE, now(), now()
FROM pace_part pp
JOIN pcdb_part_type pt   ON pt.id = pp.part_terminology_id
JOIN category c          ON c.name = pt.sub_category_name AND c.is_active
JOIN category parent     ON parent.id = c.parent_id AND parent.name = pt.category_name
WHERE pp.product_id IS NOT NULL
  AND pt.category_name IS NOT NULL AND pt.sub_category_name IS NOT NULL
  AND NOT (pt.category_name = 'Suspension' AND pt.sub_category_name = 'Shocks and Struts')
  AND NOT EXISTS (SELECT 1 FROM product_category x WHERE x.product_id = pp.product_id)
ON CONFLICT DO NOTHING;
"""

# 2) Shocks-and-Struts level-4 classifier, for UNLINKED products only.
#    Run coilover → strut → shock; each step's NOT EXISTS(any link) skips
#    products the prior step just linked, so every product lands once.
def _sql_l4(target_fp: str, predicate: str) -> str:
    return f"""
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT DISTINCT pp.product_id, (SELECT id FROM category WHERE full_path = $1), FALSE, now(), now()
FROM pace_part pp
JOIN pcdb_part_type pt ON pt.id = pp.part_terminology_id
WHERE pt.category_name = 'Suspension' AND pt.sub_category_name = 'Shocks and Struts'
  AND pp.product_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM product_category x WHERE x.product_id = pp.product_id)
  AND ({predicate})
ON CONFLICT DO NOTHING;
"""

P_COILOVER = (
    "pp.part_terminology_id = 15174 "
    "OR EXISTS (SELECT 1 FROM product p WHERE p.id = pp.product_id AND p.name ~* 'coil.?over') "
    "OR EXISTS (SELECT 1 FROM product_attribute pa WHERE pa.product_id = pp.product_id "
    "AND lower(pa.attribute_key) = 'series' AND pa.attribute_value ~* 'coil.?over')"
)
P_STRUT = (
    "EXISTS (SELECT 1 FROM product p WHERE p.id = pp.product_id AND p.name ~* 'strut') "
    "OR EXISTS (SELECT 1 FROM product_attribute pa WHERE pa.product_id = pp.product_id "
    "AND lower(pa.attribute_key) = 'series' AND pa.attribute_value ~* 'strut')"
)
P_SHOCK = "TRUE"


async def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        log.error("Set DATABASE_URL (e.g. postgresql://postgres:titan2026@localhost:5433/titan_web)")
        sys.exit(1)
    conn = await asyncpg.connect(url)
    try:
        before = await conn.fetchval(
            "SELECT count(*) FROM product p "
            "WHERE NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id) "
            "AND EXISTS (SELECT 1 FROM pace_part pp WHERE pp.product_id = p.id)")
        log.info("Unlinked products with a pace_part: %d", before)

        n_std = _count(await conn.execute(SQL_STANDARD))
        log.info("Standard part-type links inserted: %d", n_std)

        n_co = _count(await conn.execute(_sql_l4(COILOVER_FP, P_COILOVER), COILOVER_FP))
        n_st = _count(await conn.execute(_sql_l4(STRUTS_FP, P_STRUT), STRUTS_FP))
        n_sh = _count(await conn.execute(_sql_l4(SHOCKS_FP, P_SHOCK), SHOCKS_FP))
        log.info("Shocks-and-Struts L4 links — Coilover %d, Struts %d, Shocks %d", n_co, n_st, n_sh)

        still = await conn.fetchval(
            "SELECT count(*) FROM product p "
            "WHERE NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id) "
            "AND EXISTS (SELECT 1 FROM pace_part pp "
            "JOIN pcdb_part_type pt ON pt.id = pp.part_terminology_id "
            "WHERE pp.product_id = p.id AND pt.category_name IS NOT NULL)")
        log.info("Total inserted: %d. Mappable products still unlinked: %d",
                 n_std + n_co + n_st + n_sh, still or 0)
        log.info("Reminder: reindex Typesense after this so search matches browse.")
    finally:
        await conn.close()


def _count(status: str) -> int:
    # asyncpg returns e.g. "INSERT 0 42"; the last token is the row count.
    try:
        return int(status.split()[-1])
    except (ValueError, IndexError):
        return 0


if __name__ == "__main__":
    asyncio.run(main())
