"""categorize_new_brands.py — Bulk-categorize the 2,262 newly-imported products.

For each of the 8 new brands, applies a brand-level category default
(simple but useful — products show up in the right mega-menu bucket).
Where description keywords narrow the bucket, applies more-specific
sub-category links.

Also creates a new "Emergency and Warning Lighting" category under
Truck Accessories > Automotive Lighting (user-named "low hanging fruit").
Maxxima warning lights + ECCO lightbars/beacons get routed there.

Idempotent — uses ON CONFLICT DO NOTHING on the product_category junction.

Run with DATABASE_URL pointing at the target DB:
    DATABASE_URL=postgresql://postgres:titan2026@localhost:5433/titan_web \\
        python app/scripts/categorize_new_brands.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("categorize")


# Default brand → category(ies) routing.  Each tuple: (category_id, is_primary).
# We pre-resolve existing cat ids the user can browse:
#   367 = Utility Truck Equipment > Snow Plows and Accessories
#   366 = Utility Truck Equipment > Salt Spreaders and Accessories
#   102 = Truck Accessories > Exterior > Snow Plows and Accessories
#    71 = Van Equipment > Van Shelving
#    65 = Truck Accessories > Cargo Management > Ladder Racks
#    69 = Truck Accessories > Cargo Management > Truck and Van Racks
#    31 = Truck Accessories > Automotive Lighting > LED Auxiliary Lights
#    27 = Truck Accessories > Automotive Lighting > HID Auxiliary and Off-Road Lights
#    36 = Truck Accessories > Automotive Lighting > LED Work Lights
#   371 = Utility Truck Equipment > Truck Dump Beds and Accessories
#    20 = Utility Truck Equipment (root)
DEFAULT_PRIMARY = {
    "WEST": 367,
    "MYP":  367,
    "SNOW": 367,
    "BUY":  20,    # generic Utility Truck Equipment root
    "MAXX": None,  # filled in below via new Emergency cat
    "KAR":  71,    # Van Shelving (primary use)
    "BAJA": 31,    # LED Auxiliary Lights
    "KNP":  371,
}

# Additional category links per brand (cross-listings, non-primary).
EXTRA_CROSSLINKS = {
    "WEST": [102],          # also Exterior > Snow Plows
    "MYP":  [102],
    "SNOW": [102, 366],     # SaltDogg → also Salt Spreaders
    "KAR":  [65, 69],       # also Ladder Racks + Truck/Van Racks
    "BAJA": [27, 36],       # also Off-Road + Work Lights
    "MAXX": [36],           # also Work Lights (Maxxima has work-light line)
}

# Keyword-based sub-categorization within Maxxima (overrides default primary):
MAXX_KEYWORD_TO_CAT = {
    # → Emergency Lighting (created below; cat_id resolved at runtime)
    "warning": "EMERGENCY",
    "lightbar": "EMERGENCY",
    "beacon": "EMERGENCY",
    "strobe": "EMERGENCY",
    "minibar": "EMERGENCY",
    "microbar": "EMERGENCY",
    "directional": "EMERGENCY",
    "amber": "EMERGENCY",
    # → Work Lights (id 36)
    "work light": 36,
    "flood": 36,
    "spot": 36,
}


async def get_or_create_emergency_lighting_cat(conn: asyncpg.Connection) -> int:
    """Create Truck Accessories > Automotive Lighting > Emergency and Warning Lighting.

    Parent cat id 2 = Truck Accessories > Automotive Lighting.
    """
    existing = await conn.fetchval(
        "SELECT id FROM category WHERE full_path = $1",
        "Truck Accessories > Automotive Lighting > Emergency and Warning Lighting",
    )
    if existing:
        log.info("Emergency Lighting category already exists: id=%d", existing)
        return existing

    new_id = await conn.fetchval(
        """
        INSERT INTO category (name, slug, parent_id, full_path, depth,
                              description, sort_order, is_featured, is_active,
                              created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
        RETURNING id
        """,
        "Emergency and Warning Lighting",
        "automotive-lighting/emergency-and-warning-lighting",
        2,        # parent: Truck Accessories > Automotive Lighting
        "Truck Accessories > Automotive Lighting > Emergency and Warning Lighting",
        2,        # depth
        "Warning lightbars, beacons, strobes, and directional lights for emergency, "
        "utility, and work-truck applications.  Includes Maxxima, ECCO, Code 3, and "
        "Federal Signal warning equipment.",
        100,      # sort early
        True,     # featured (user called this out as priority)
        True,
    )
    log.info("Created Emergency Lighting category: id=%d", new_id)
    return new_id


async def link_product_to_cat(conn: asyncpg.Connection, product_id: int,
                              category_id: int, is_primary: bool) -> bool:
    """Returns True if a NEW link was made; False if already existed."""
    result = await conn.execute(
        """
        INSERT INTO product_category (product_id, category_id, is_primary,
                                      created_at, updated_at)
        VALUES ($1, $2, $3, NOW(), NOW())
        ON CONFLICT (product_id, category_id) DO NOTHING
        """,
        product_id, category_id, is_primary,
    )
    return result.endswith(" 1")


async def categorize_brand(conn: asyncpg.Connection, brand_id: int, brand_name: str,
                           prod_code: str, emergency_cat_id: int) -> tuple[int, int]:
    """Apply category links for all products of this brand.

    Returns (n_primary_added, n_extra_added).
    """
    products = await conn.fetch(
        "SELECT id, name, COALESCE(extended_description, '') AS ext "
        "FROM product WHERE brand_id = $1",
        brand_id,
    )
    if not products:
        log.info("  no products for %s", brand_name)
        return 0, 0

    primary_added = 0
    extra_added = 0

    default_primary = DEFAULT_PRIMARY.get(prod_code)
    if prod_code == "MAXX":
        # Most Maxxima products are general lighting; warning/beacon/lightbar
        # subset is emergency.  Default primary = Emergency Lighting (since
        # Titan owner flagged this as the priority bucket), else Work Lights.
        default_primary = emergency_cat_id
    extras = EXTRA_CROSSLINKS.get(prod_code, [])

    for p in products:
        pid = p["id"]
        haystack = f"{p['name']} {p['ext']}".lower()

        # Brand-specific keyword routing (only Maxxima for now)
        per_product_primary = default_primary
        per_product_extras = list(extras)

        if prod_code == "MAXX":
            # Default = Emergency.  If description is clearly work-light-flavored,
            # demote Emergency to extra and promote Work Lights to primary.
            if any(kw in haystack for kw in ["work light", "flood", "spot", "led work"]):
                per_product_primary = 36  # Work Lights
                per_product_extras = [emergency_cat_id]
            elif not any(kw in haystack for kw in [
                "warning", "lightbar", "beacon", "strobe", "minibar", "microbar",
                "directional", "amber", "stt", "stop turn tail", "marker",
            ]):
                # Likely just general lighting/wiring — keep Emergency anyway
                # so it shows up in the priority bucket the owner cares about.
                pass

        if per_product_primary is not None:
            if await link_product_to_cat(conn, pid, per_product_primary, True):
                primary_added += 1

        for extra in per_product_extras:
            if extra == per_product_primary:
                continue
            if await link_product_to_cat(conn, pid, extra, False):
                extra_added += 1

    log.info("  %s: %d primary + %d extra links added", brand_name, primary_added, extra_added)
    return primary_added, extra_added


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        emergency_cat_id = await get_or_create_emergency_lighting_cat(conn)

        brands = await conn.fetch(
            "SELECT id, name, prod_code FROM brand "
            "WHERE prod_code IN ('WEST','MYP','SNOW','BUY','MAXX','KAR','BAJA','KNP') "
            "ORDER BY name"
        )
        log.info("Categorizing %d brands…", len(brands))

        total_p, total_e = 0, 0
        for b in brands:
            log.info("===== %s (id=%d, prod_code=%s) =====", b["name"], b["id"], b["prod_code"])
            p, e = await categorize_brand(conn, b["id"], b["name"], b["prod_code"], emergency_cat_id)
            total_p += p
            total_e += e

        log.info("=" * 60)
        log.info("TOTAL: %d primary + %d extra category links added", total_p, total_e)
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
