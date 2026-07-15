"""import_deweze_catalog.py — Import the 293-kit Deweze clutch pump catalog.

Run AFTER:
  1. scrape_deweze_catalog.py      → produces deweze_kits.json
  2. download_deweze_schematics.py → produces app/data/stage_deweze/{pdfs,images}/
  3. The staging dir has been uploaded to Hetzner via scp -r:
       scp -r app/data/stage_deweze/* titan@hetzner:/home/titan/titan-truck-
            website/app/backend/static/brand_images/DEW/

Side effects:
  * UPSERTs brand "DewEze" (aaia_code=DEW, prod_code=DEW, supplier=Harper
    Industries).  Brand DEW already has 14 parts in tte_parts_master so
    this aligns the website brand row with the TigerTech side.
  * Creates category "Truck Equipment > Hydraulic Pump Kits" (if missing).
  * For each of the 293 kit records:
       sku                  = DEW-{kit_number}
       name                 = "DewEze {kit_number} — {make} {engine}
                               {year_range} ({pump_type})"
       description          = 1-line spec (pump_type, belt, clutch_config)
       extended_description = full kit details + notes
       cta_mode             = ADD_TO_CART
       primary image_url    = /static/brand_images/DEW/images/{kit}.png
                              (the page-1 schematic — owner-flagged as
                              crucial for these products)
       legacy_wsm_url       = the S3 PDF (so the product page can link
                              the full Installation Manual download)
  * Categorizes each into the new Hydraulic Pump Kits cat.

Owner ask: "downloading pictures of schematics for this line is crucial
for it to see on the website."
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

import asyncpg


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("deweze")

DATA = Path(__file__).resolve().parent.parent / "data" / "mysql_dumps"
KITS_JSON = DATA / "deweze_kits.json"

TRUCK_EQUIPMENT_PATH = "Truck Equipment"


async def ensure_brand(conn: asyncpg.Connection) -> int:
    existing = await conn.fetchval("SELECT id FROM brand WHERE name = 'DewEze'")
    if existing:
        await conn.execute(
            """
            UPDATE brand SET aaia_code = 'DEW', prod_code = 'DEW',
                website_url = 'https://www.deweze.com',
                slug = 'deweze', is_active = TRUE,
                description = $1, updated_at = NOW() WHERE id = $2
            """,
            "DewEze (Harper Industries) builds engine-driven PTO clutch pump "
            "kits for heavy trucks — converting any pickup or commercial chassis "
            "into a hydraulic-driven utility platform.  Used for hay handling "
            "BaleBeds, BeefCake feeders, flatbeds, and aftermarket utility "
            "upfits.  Per-truck installation schematics included for 293+ "
            "vehicle applications.",
            existing,
        )
        log.info("DewEze brand exists (id=%d) — updated codes", existing)
        return existing
    new_id = await conn.fetchval(
        """
        INSERT INTO brand (name, slug, aaia_code, prod_code, website_url,
                           is_featured, sort_order, is_active, description,
                           created_at, updated_at)
        VALUES ('DewEze', 'deweze', 'DEW', 'DEW', 'https://www.deweze.com',
                FALSE, 200, TRUE, $1, NOW(), NOW())
        RETURNING id
        """,
        "DewEze (Harper Industries) builds engine-driven PTO clutch pump "
        "kits for heavy trucks.  Per-truck installation schematics included "
        "for 293+ vehicle applications.",
    )
    log.info("Created DewEze brand (id=%d)", new_id)
    return new_id


async def ensure_category(conn: asyncpg.Connection) -> int:
    path = f"{TRUCK_EQUIPMENT_PATH} > Hydraulic Pump Kits"
    existing = await conn.fetchval(
        "SELECT id FROM category WHERE full_path = $1", path,
    )
    if existing:
        return existing
    parent = await conn.fetchrow(
        "SELECT id, depth FROM category WHERE full_path = $1",
        TRUCK_EQUIPMENT_PATH,
    )
    if not parent:
        raise RuntimeError(f"Missing parent: {TRUCK_EQUIPMENT_PATH}")
    new_id = await conn.fetchval(
        """
        INSERT INTO category (name, slug, parent_id, full_path, depth,
                              description, sort_order, is_featured, is_active,
                              created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, 110, FALSE, TRUE, NOW(), NOW())
        RETURNING id
        """,
        "Hydraulic Pump Kits",
        "hydraulic-pump-kits",
        parent["id"], path, parent["depth"] + 1,
        "DewEze engine-driven PTO clutch pump kits and accessories for "
        "trucks, vans, and commercial chassis.  Includes per-truck "
        "installation schematics covering 293+ vehicle applications, plus "
        "the full A Pump Parker 315 / PH14, AA Pump Parker 505, and "
        "Turolla/Sauer high-pressure pump lines.",
    )
    log.info("Created category: %s (id=%d)", path, new_id)
    return new_id


def build_name(kit: dict) -> str:
    parts = [f"DewEze #{kit['number']}"]
    make = kit.get("make") or ""
    engine = kit.get("engine_or_model") or ""
    sy = kit.get("engine_start_year")
    ey = kit.get("engine_end_year")
    yrs = ""
    if sy and ey:
        yrs = f"{sy}-{ey}" if sy != ey else f"{sy}"
    if make:
        parts.append(f"— {make}")
    if engine:
        parts.append(engine[:60])
    if yrs:
        parts.append(f"({yrs})")
    pt = kit.get("pump_type_short") or ""
    if pt:
        parts.append(f"[{pt} pump]")
    return " ".join(parts)[:500]


def build_description(kit: dict) -> tuple[str, str]:
    pieces = []
    if kit.get("pump_type_name"):
        pieces.append(f"Pump: {kit['pump_type_name']}")
    if kit.get("pump_port"):
        pieces.append(f"Port: {kit['pump_port']}")
    if kit.get("clutch_configuration"):
        pieces.append(f"Clutch: {kit['clutch_configuration']}")
    if kit.get("belt"):
        pieces.append(f"Belt: {kit['belt']}")
    short = ". ".join(pieces)
    short = short[:500] if short else f"DewEze installation kit #{kit['number']}"

    long_parts = [short]
    eng_bits = []
    if kit.get("engine_size"):
        eng_bits.append(kit["engine_size"])
    if kit.get("engine_fuel"):
        eng_bits.append(kit["engine_fuel"])
    if eng_bits:
        long_parts.append("Engine: " + " · ".join(eng_bits))
    if kit.get("obsolete"):
        long_parts.append("⚠ OBSOLETE kit — discontinued; check with Titan sales for current replacement.")
    long_parts.append(
        "Includes complete installation hardware and per-truck schematic. "
        "Refer to the Installation Manual PDF (linked below) for step-by-step "
        "fitment, torque specs, and belt routing."
    )
    extended = "\n\n".join(long_parts)[:8000]
    return short, extended


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        brand_id = await ensure_brand(conn)
        cat_id = await ensure_category(conn)

        data = json.loads(KITS_JSON.read_text(encoding="utf-8"))
        kits = data["kits"]
        log.info("Importing %d kits…", len(kits))

        inserted = updated = 0
        for kit in kits:
            num = kit["number"]
            sku = f"DEW-{num}"[:64]
            name = build_name(kit)
            short, extended = build_description(kit)
            pdf_url = kit["manual"]
            png_url = f"/static/brand_images/DEW/images/{num}.png"

            existing = await conn.fetchval("SELECT id FROM product WHERE sku = $1", sku)
            if existing:
                await conn.execute(
                    """
                    UPDATE product SET brand_id = $1, prod_code = 'DEW',
                        name = $2, description = $3, extended_description = $4,
                        cta_mode = 'ADD_TO_CART', is_for_sale = TRUE,
                        is_hidden = FALSE, legacy_wsm_url = $5,
                        updated_at = NOW()
                    WHERE id = $6
                    """,
                    brand_id, name, short, extended, pdf_url, existing,
                )
                pid = existing
                updated += 1
            else:
                pid = await conn.fetchval(
                    """
                    INSERT INTO product (sku, brand_id, prod_code, name,
                        description, extended_description, legacy_wsm_url,
                        cta_mode, requires_shipping, taxable, own_box,
                        ship_quote, free_ground, is_hidden, is_for_sale,
                        login_required, saleprice_hidden,
                        created_at, updated_at)
                    VALUES ($1, $2, 'DEW', $3, $4, $5, $6,
                        'ADD_TO_CART', TRUE, TRUE, FALSE,
                        FALSE, 0, FALSE, TRUE, FALSE, FALSE,
                        NOW(), NOW())
                    RETURNING id
                    """,
                    sku, brand_id, name, short, extended, pdf_url,
                )
                inserted += 1

            # Categorize
            await conn.execute(
                """
                INSERT INTO product_category (product_id, category_id,
                    is_primary, created_at, updated_at)
                VALUES ($1, $2, TRUE, NOW(), NOW())
                ON CONFLICT (product_id, category_id) DO NOTHING
                """,
                pid, cat_id,
            )

            # Primary image — the page-1 schematic.  Static path; the file
            # is uploaded separately via scp to /static/brand_images/DEW/images/.
            await conn.execute(
                """
                INSERT INTO product_image (product_id, url, alt_text,
                    sort_order, is_primary, created_at, updated_at)
                VALUES ($1, $2, $3, 0, TRUE, NOW(), NOW())
                ON CONFLICT DO NOTHING
                """,
                pid, png_url, f"DewEze {num} installation schematic",
            )

        log.info("Done.  inserted=%d, updated=%d (total %d)",
                 inserted, updated, len(kits))
        log.info("Brand id=%d, Category id=%d", brand_id, cat_id)
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
