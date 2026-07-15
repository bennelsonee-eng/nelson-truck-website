"""recategorize_maxxima_and_add_lighting.py

User feedback 2026-05-14: "Main emergency lighting companies are Federal
Signal and Ecco Lighting with Maxxima starting to develop new product,
but they were mainly known for DOT lighting."

Two actions this script performs:

  1. Create a new "DOT and Trailer Lighting" category under
     Truck Accessories > Automotive Lighting (parent id 2) for the
     stop/turn/tail, marker, clearance, backup, license-plate, and
     turn-signal Maxxima products that don't belong in Emergency
     Lighting.

  2. Replace Maxxima's flat "Emergency + Work Lights" categorization
     with category routing driven by the per-product Maxxima category
     slug from the scrape (maxxima_catalog.json).  Only true
     warning/beacon/strobe/lightbar/microbar products stay under
     Emergency Lighting.

  3. Update the Emergency Lighting category description to reflect that
     ECCO and Federal Signal are the flagship brands, with Maxxima
     featured as their emerging warning line on top of their core DOT
     lighting position.

Categories used (Truck Accessories > Automotive Lighting subtree):
  ID  Path
  ---
  24  Fog Lights
  30  Interior Lighting
  31  LED Auxiliary Lights
  32  LED Headlight Conversion Kits
  34  LED Replacement Bulbs
  36  LED Work Lights
  37  Light Brackets and Mounts
  42  Miscellaneous Lighting
  43  Replacement Bulbs
  44  Replacement Headlights
  45  Replacement Tail lights
  49  Wiring Harnesses and Switches
  403 Emergency and Warning Lighting (existing, will be cleaned up)
  NEW DOT and Trailer Lighting (created by this script)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("recat")

CATALOG = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps" / "maxxima_catalog.json"
ARROW = " > "

# Maxxima scrape slug -> Titan category-id list (first is primary)
# IDs are pre-resolved from the live Titan category tree (see file header).
# "DOT" placeholder is replaced with the new DOT/Trailer category id at runtime.
EMERGENCY = "EMERGENCY"   # resolved to 403
DOT = "DOT"               # resolved after creation

SLUG_TO_CATS: dict[str, list] = {
    # ----- True emergency / warning -----
    "warning-safety.asp":              [EMERGENCY],
    "surface-mount-warning":           [EMERGENCY],
    "4-inch-6-inch-flashing-warning":  [EMERGENCY],
    "beacons":                         [EMERGENCY],
    "traffic-directors":               [EMERGENCY],

    # ----- DOT / trailer lighting -----
    "stop-tail-turn-clearance-marker.asp": [DOT, 45],     # also Repl Tail Lights
    "clearance-marker.asp":            [DOT],
    "amber-turn-signals.asp":          [DOT],
    "back-up.asp":                     [DOT],
    "6-inch-round-stop-turn-tail.asp": [DOT, 45],
    "4-inch-round-stop-turn-tail.asp": [DOT, 45],
    "other-stop-turn-tail.asp":        [DOT, 45],
    "license-lights.asp":              [DOT],
    "aux-stop-aux-turn.asp":           [DOT],
    "hybrid-stt-bu-all-in-one.asp":    [DOT],
    "back-up-alarms":                  [DOT],
    "maxxheat-heated-stop-turn-tail.asp": [DOT, 45],
    "drl-daytime-running-lights.asp":  [DOT],

    # ----- Interior / dome / cargo -----
    "interior-lights.asp":             [30],     # Interior Lighting
    "overhead-dome-lights.asp":        [30],

    # ----- Work / forward lighting -----
    "work-lights.asp":                 [36],     # LED Work Lights
    "maxxheat-heated-let-work-lights.asp": [36],
    "forward-lighting.asp":            [44],     # Replacement Headlights
    "led-headlights.asp":              [32],     # LED Headlight Conv
    "maxxheat-heated-led-headlights.asp": [32],
    "snow-plow-headlights.asp":        [44],
    "fog-lights.asp":                  [24],

    # ----- Strip / accent / outdoor -----
    "flexibile-strip-lights.asp":      [42],     # Misc Lighting
    "rigid-linear-strip-lights.asp":   [42],
    "recessed-lighting":               [42],
    "outdoor-lights":                  [42],
    "light-fixtures":                  [42],

    # ----- Bulbs / accessories -----
    "light-bulbs":                     [43],     # Replacement Bulbs
    "mounting-brackets-and-bezels.asp": [37],    # Light Brackets and Mounts
    "mounting-grommets.asp":           [37],
    "electrical.asp":                  [49],     # Wiring Harnesses and Switches
    "electrical-connectors.asp":       [49],
    "flashers-and-modules.asp":        [49],

    # ----- Skip (promotional, not products) -----
    "display-and-promotional-material.asp": [],
}


async def ensure_dot_category(conn: asyncpg.Connection) -> int:
    """Create Truck Accessories > Automotive Lighting > DOT and Trailer Lighting."""
    existing = await conn.fetchval(
        "SELECT id FROM category WHERE full_path = $1",
        "Truck Accessories > Automotive Lighting > DOT and Trailer Lighting",
    )
    if existing:
        log.info("DOT category already exists: id=%d", existing)
        return existing
    new_id = await conn.fetchval(
        """
        INSERT INTO category (name, slug, parent_id, full_path, depth,
                              description, sort_order, is_featured, is_active,
                              created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
        RETURNING id
        """,
        "DOT and Trailer Lighting",
        "automotive-lighting/dot-and-trailer-lighting",
        2,
        "Truck Accessories > Automotive Lighting > DOT and Trailer Lighting",
        2,
        "Federally-compliant stop/turn/tail, marker, clearance, license, "
        "back-up, and daytime-running lights for trucks, trailers, RVs, "
        "and commercial vehicles.  Includes Maxxima's flagship DOT line, "
        "plus the DOT subset of ECCO and Federal Signal catalogs.",
        110,
        False,
        True,
    )
    log.info("Created DOT category: id=%d", new_id)
    return new_id


async def update_emergency_description(conn: asyncpg.Connection, dot_cat_id: int) -> None:
    """Refresh the Emergency Lighting cat description to reflect ECCO+Federal Signal flagship."""
    await conn.execute(
        """
        UPDATE category SET description = $1, updated_at = NOW()
        WHERE id = 403
        """,
        "Warning lightbars, beacons, strobes, microbars, surface-mount warning "
        "heads, and traffic-director arrow boards for emergency, utility, "
        "first-response, and work-truck applications.  Flagship brands: "
        "ECCO Safety Group (lightbars, beacons, the Code 3 line) and "
        "Federal Signal (purpose-built emergency).  Maxxima is also featured "
        "here for their emerging warning-light line on top of their core "
        "DOT-lighting position (Maxxima DOT products live under "
        "Truck Accessories > Automotive Lighting > DOT and Trailer Lighting).",
    )


async def recategorize_maxxima(conn: asyncpg.Connection, dot_cat_id: int) -> None:
    """Replace Maxxima's existing category links with slug-driven routing."""
    if not CATALOG.exists():
        log.warning("missing %s — keeping existing categorization", CATALOG)
        return
    scrape = json.loads(CATALOG.read_text(encoding="utf-8"))

    # Build sku → primary_cat_id + extras
    def resolve(target_list):
        return [
            (dot_cat_id if t == DOT else (403 if t == EMERGENCY else t))
            for t in target_list
        ]

    sku_to_cats: dict[str, list[int]] = {}
    for p in scrape:
        sku = (p.get("sku") or "").upper()
        if not sku:
            continue
        cats: list[int] = []
        for slug in p.get("categories", []):
            cats.extend(resolve(SLUG_TO_CATS.get(slug, [])))
        # Dedupe preserving order
        seen = set()
        unique = []
        for c in cats:
            if c not in seen:
                seen.add(c)
                unique.append(c)
        sku_to_cats[sku] = unique

    # Load every Maxxima product on the Titan side
    brand_id = await conn.fetchval("SELECT id FROM brand WHERE prod_code = 'MAXX'")
    if not brand_id:
        log.warning("Maxxima brand row missing")
        return
    products = await conn.fetch(
        "SELECT id, sku FROM product WHERE brand_id = $1", brand_id
    )
    log.info("Maxxima products on Titan: %d", len(products))

    # Clear existing category links so we re-set them clean
    deleted = await conn.execute(
        "DELETE FROM product_category WHERE product_id IN "
        "(SELECT id FROM product WHERE brand_id = $1)",
        brand_id,
    )
    log.info("Cleared old Maxxima category links: %s", deleted)

    inserted = 0
    fallback = 0
    no_cat = 0
    for p in products:
        pid = p["id"]
        sku = p["sku"].replace("MAXX-", "", 1).upper()
        cats = sku_to_cats.get(sku) or sku_to_cats.get(sku.replace("-", ""))
        if not cats:
            # Fallback: Misc Lighting (42) — better than orphaned
            cats = [42]
            fallback += 1
        for idx, cat_id in enumerate(cats):
            await conn.execute(
                """
                INSERT INTO product_category (product_id, category_id, is_primary,
                                              created_at, updated_at)
                VALUES ($1, $2, $3, NOW(), NOW())
                ON CONFLICT (product_id, category_id) DO NOTHING
                """,
                pid, cat_id, idx == 0,
            )
            inserted += 1

    log.info("Maxxima recategorized: %d category links inserted, %d products "
             "fell back to Miscellaneous Lighting (no slug match)",
             inserted, fallback)


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        dot_cat_id = await ensure_dot_category(conn)
        await update_emergency_description(conn, dot_cat_id)
        await recategorize_maxxima(conn, dot_cat_id)
        log.info("Done.")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
