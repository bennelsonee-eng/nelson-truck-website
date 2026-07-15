"""import_brand_catalog.py — End-to-end brand + product import.

For each brand we want on the Titan website but don't yet have:
  1. UPSERT brand row (set aaia_code + prod_code so the v2 inventory
     linker can match SKUs)
  2. INSERT product rows for every in-stock SKU (TTE + NTE wh 10/1/2):
       sku                  = '{aaia_code}-{parts_num}' (matches linker)
       name                 = parts_master description (or extra_desc combined)
       brand_id             = the inserted brand
       prod_code            = TigerTech code
       description          = parts_master.description (short)
       extended_description = Nelson ERP LLM-enriched description if richer,
                              else Maxxima.com scraped description (for MAXX),
                              else parts_master.extra_desc
       cta_mode             = ADD_TO_CART
       is_for_sale          = TRUE
       weight_lb / dims     = from parts_master
       tte_ourparts_num     = TTE ourparts_num (so re-linking is instant)
  3. UPSERT product_price row from P1-P5
  4. BUY↔SNOW dedup: skip BUY rows whose parts_num is already imported
     under SNOW (per the dedup rule documented in the snow plow design)

After running, re-run scripts/link_titan_inventory_v2.py + reindex_typesense.py.

Usage:
    DATABASE_URL=postgresql://postgres:titan2026@HOST:5433/titan_web \\
        python app/scripts/import_brand_catalog.py
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import re
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

import asyncpg


SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
DUMPS = APP_DIR / "data" / "mysql_dumps"

# Brands we are bringing online tonight.  Order matters because of BUY/SNOW
# dedup — SNOW imports first so when BUY hits the same parts_num, we skip it.
BRANDS: list[dict] = [
    # SnowDogg first (snow-related products preferred under SNOW per dedup rule)
    {"prod_code": "SNOW", "name": "Buyers SnowDogg",     "aaia_code": "SNOW",
     "slug": "buyers-snowdogg",   "website": "https://www.buyersproducts.com"},
    {"prod_code": "WEST", "name": "Western",             "aaia_code": "WEST",
     "slug": "western",           "website": "https://westernplows.com"},
    {"prod_code": "MYP",  "name": "Meyer Products",      "aaia_code": "MYP",
     "slug": "meyer-products",    "website": "https://www.meyerproducts.com"},
    {"prod_code": "BUY",  "name": "Buyers Products",     "aaia_code": "BUY",
     "slug": "buyers-products",   "website": "https://www.buyersproducts.com"},
    {"prod_code": "MAXX", "name": "Maxxima",             "aaia_code": "MAXX",
     "slug": "maxxima",           "website": "https://maxxima.com"},
    {"prod_code": "KAR",  "name": "Kargo Master",        "aaia_code": "KAR",
     "slug": "kargo-master",      "website": "https://kargo-master.com"},
    {"prod_code": "BAJA", "name": "Baja Designs",        "aaia_code": "BAJA",
     "slug": "baja-designs",      "website": "https://www.bajadesigns.com"},
    # KNP already has a brand row (id 78); we'll UPDATE in place
    {"prod_code": "KNP",  "name": "Knapheide",           "aaia_code": "KNP",
     "slug": "knapheide",         "website": "https://www.knapheide.com",
     "update_existing_name": "Knapheide"},
    # Emergency-lighting flagships (user 2026-05-14: "Main emergency lighting
    # companies are Federal Signal and Ecco Lighting").  ECCO Electronics
    # Controls Co. is supplier 501 on Nelson side (the ECCO Safety Group
    # parent — covers both the ECCO and Code 3 brands).
    {"prod_code": "ECCO", "name": "ECCO Safety Group",   "aaia_code": "ECCO",
     "slug": "ecco-safety-group", "website": "https://www.eccoesg.com"},
    {"prod_code": "FED",  "name": "Federal Signal",      "aaia_code": "FED",
     "slug": "federal-signal",    "website": "https://www.fedsig.com"},
    # Dur-A-Lift — brand row already exists (id=90) from the dur-a-lift.com
    # marketing-page scrape; this pass adds the actual stocked replacement
    # parts catalog (38 parts_master rows, ~64 in-stock SKUs across TTE/NTE).
    {"prod_code": "DRL",  "name": "Dur-A-Lift",          "aaia_code": "DRL",
     "slug": "dur-a-lift",        "website": "https://dur-a-lift.com"},
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("import_brand")

TARGET_WAREHOUSES = {10, 1, 2}


def D(v):
    if v in (None, "", "0", "0.00", "0.0"):
        return None
    try:
        d = Decimal(v)
        return d if d.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def parse_int(v):
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def load_master(prod_code: str) -> dict[str, dict]:
    path = DUMPS / f"{prod_code.lower()}_parts_master.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        for r in csv.DictReader(fp):
            ou = (r.get("ourparts_num") or "").strip()
            if not ou or ou == "#":
                continue
            out[ou] = {
                "parts_num": (r.get("parts_num") or "").strip(),
                "description": (r.get("description") or "").strip(),
                "extra_desc": (r.get("extra_desc") or "").strip(),
                "p1": D(r.get("P1")), "p2": D(r.get("P2")), "p3": D(r.get("P3")),
                "p4": D(r.get("P4")), "p5": D(r.get("P5")),
                "weight": D(r.get("weight")),
                "length": D(r.get("length")), "width": D(r.get("width")),
                "height": D(r.get("height")),
                "location": (r.get("location") or "").strip(),
                "status": (r.get("status") or "").strip(),
            }
    return out


def load_inv_combined(prod_code: str) -> dict[str, dict]:
    inv: dict[str, dict] = defaultdict(lambda: {"on_hand": 0, "warehouses": set()})
    for fname in (f"{prod_code.lower()}_tte_inv.csv", f"{prod_code.lower()}_nte_inv.csv"):
        path = DUMPS / fname
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as fp:
            for r in csv.DictReader(fp):
                ou = (r.get("ourparts_num") or "").strip()
                if not ou:
                    continue
                try:
                    oh = int(float(r.get("onhand") or 0))
                    wh = int(r.get("warehouse") or 0)
                except ValueError:
                    continue
                if wh not in TARGET_WAREHOUSES:
                    continue
                inv[ou]["on_hand"] += oh
                inv[ou]["warehouses"].add(wh)
    return dict(inv)


def load_nelson_descriptions() -> dict[str, dict]:
    """ourparts_num → {description, extra_desc, extended_description}."""
    path = DUMPS / "nelson_erp_brand_descriptions.csv"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        for r in csv.DictReader(fp):
            ou = (r.get("ourparts_num") or "").strip()
            if not ou:
                continue
            out[ou] = {
                "description": (r.get("description") or "").strip(),
                "extra_desc": (r.get("extra_desc") or "").strip(),
                "extended_description": (r.get("extended_description") or "").strip(),
            }
    return out


def load_maxxima_scrape() -> dict[str, str]:
    """sku (uppercase) → enriched description text."""
    path = DUMPS / "maxxima_catalog.json"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for p in json.loads(path.read_text(encoding="utf-8")):
        sku = (p.get("sku") or "").upper()
        if sku:
            out[sku] = p.get("description_text", "")
    return out


def best_description(prod_code: str, ourparts_num: str, parts_num: str,
                     master_desc: str, master_extra: str,
                     nelson_data: dict, maxxima_scrape: dict) -> tuple[str, str]:
    """Pick the best short + extended descriptions from all sources.

    Returns (short_name, extended_text).
      short_name : 1-line product name (max ~200 chars)
      extended_text : longer marketing copy (or empty)
    """
    nelson = nelson_data.get(ourparts_num) or {}
    nelson_short = nelson.get("description") or ""
    nelson_extra = nelson.get("extra_desc") or ""
    nelson_extended = nelson.get("extended_description") or ""

    # Maxxima scrape lookup is by parts_num (the manufacturer SKU)
    maxxima = maxxima_scrape.get((parts_num or "").upper(), "") if prod_code == "MAXX" else ""

    # Short name: prefer Nelson ERP if it's richer than master, else use master
    short = nelson_short if len(nelson_short) > len(master_desc) else master_desc
    if not short:
        short = master_extra or master_desc or f"{prod_code} Part {parts_num}"
    short = short[:500]  # product.name is varchar(500)

    # Extended: Maxxima scrape wins (deepest content), then Nelson extended,
    # then Nelson short (if not already used as name), else master extra.
    extended = ""
    if maxxima and len(maxxima) > 100:
        extended = maxxima
    elif nelson_extended and len(nelson_extended) > 100:
        extended = nelson_extended
    elif nelson_short and nelson_short != short:
        extended = nelson_short
    elif master_extra and master_extra != short:
        extended = master_extra

    return short, extended[:8000]  # cap at 8K to keep DB rows sane


def derive_sku(prod_code: str, aaia_code: str, parts_num: str, ourparts_num: str) -> str:
    """Build the website SKU using the same convention the v2 linker expects.

    The linker tries: '{aaia}-{parts_num}', '{aaia}{parts_num}', '{parts_num}'.
    We use the dashed form as canonical.
    """
    pn = (parts_num or "").strip()
    if not pn:
        # Fall back to stripping the prod_code prefix from ourparts_num
        ou = (ourparts_num or "").strip()
        pn = ou[len(prod_code):] if ou.upper().startswith(prod_code.upper()) else ou
    return f"{aaia_code}-{pn}"[:64]


async def upsert_brand(conn: asyncpg.Connection, brand: dict) -> int:
    """Returns the brand_id, INSERT-or-UPDATE-by-name."""
    row = await conn.fetchrow("SELECT id FROM brand WHERE name = $1", brand["name"])
    if row:
        await conn.execute(
            "UPDATE brand SET aaia_code = $1, prod_code = $2, website_url = $3, "
            "slug = $4, is_active = TRUE, updated_at = NOW() WHERE id = $5",
            brand["aaia_code"], brand["prod_code"], brand["website"],
            brand["slug"], row["id"],
        )
        return row["id"]
    new_id = await conn.fetchval(
        "INSERT INTO brand (name, slug, aaia_code, prod_code, website_url, "
        "is_featured, sort_order, is_active, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, FALSE, 1000, TRUE, NOW(), NOW()) "
        "RETURNING id",
        brand["name"], brand["slug"], brand["aaia_code"], brand["prod_code"], brand["website"],
    )
    return new_id


async def upsert_product(conn: asyncpg.Connection, *,
                         sku: str, brand_id: int, name: str, prod_code: str,
                         description: str, extended: str, tte_ourparts: str,
                         weight: Decimal | None,
                         length: Decimal | None, width: Decimal | None, height: Decimal | None,
                         ) -> int | None:
    """Returns product_id; INSERT or UPDATE existing-by-SKU."""
    existing = await conn.fetchval("SELECT id FROM product WHERE sku = $1", sku)
    if existing:
        # Update richer fields where ours are better
        await conn.execute(
            "UPDATE product SET brand_id = $1, prod_code = $2, name = $3, "
            "description = COALESCE(NULLIF(description, ''), $4), "
            "extended_description = COALESCE(NULLIF(extended_description, ''), $5), "
            "tte_ourparts_num = COALESCE(tte_ourparts_num, $6), "
            "weight_lb = COALESCE(weight_lb, $7), "
            "length_in = COALESCE(length_in, $8), "
            "width_in = COALESCE(width_in, $9), "
            "height_in = COALESCE(height_in, $10), "
            "is_for_sale = TRUE, is_hidden = FALSE, updated_at = NOW() WHERE id = $11",
            brand_id, prod_code, name, description, extended, tte_ourparts,
            weight, length, width, height, existing,
        )
        return existing
    new_id = await conn.fetchval(
        "INSERT INTO product (sku, brand_id, prod_code, name, description, "
        "extended_description, tte_ourparts_num, weight_lb, length_in, width_in, height_in, "
        "cta_mode, requires_shipping, taxable, own_box, ship_quote, free_ground, "
        "is_hidden, is_for_sale, login_required, saleprice_hidden, "
        "created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, "
        "'ADD_TO_CART', TRUE, TRUE, FALSE, FALSE, 0, "
        "FALSE, TRUE, FALSE, FALSE, NOW(), NOW()) "
        "RETURNING id",
        sku, brand_id, prod_code, name, description, extended, tte_ourparts,
        weight, length, width, height,
    )
    return new_id


async def upsert_price(conn: asyncpg.Connection, product_id: int,
                       p1: Decimal | None, p2: Decimal | None, p3: Decimal | None,
                       p4: Decimal | None, p5: Decimal | None) -> None:
    if not any(v is not None for v in (p1, p2, p3, p4, p5)):
        return
    await conn.execute(
        "INSERT INTO product_price (product_id, suggested_retail_price, retail_price, "
        "jobber_price, dealer_price, cost, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW()) "
        "ON CONFLICT (product_id) DO UPDATE SET "
        "suggested_retail_price = EXCLUDED.suggested_retail_price, "
        "retail_price = EXCLUDED.retail_price, "
        "jobber_price = EXCLUDED.jobber_price, "
        "dealer_price = EXCLUDED.dealer_price, "
        "cost = EXCLUDED.cost, updated_at = NOW()",
        product_id, p1, p2, p3, p4, p5,
    )


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:titan2026@localhost:5433/titan_web")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    log.info("Connecting: %s", dsn.split("@")[-1])
    conn = await asyncpg.connect(dsn)
    try:
        nelson = load_nelson_descriptions()
        log.info("Nelson ERP descriptions loaded: %d", len(nelson))
        maxxima_scrape = load_maxxima_scrape()
        log.info("Maxxima scrape entries: %d", len(maxxima_scrape))

        # BUY/SNOW dedup: track parts_num already imported under SNOW (which runs first)
        snow_parts_nums: set[str] = set()

        total_inserted = 0
        total_updated = 0
        for brand in BRANDS:
            prod_code = brand["prod_code"]
            log.info("===== %s (%s) =====", brand["name"], prod_code)
            brand_id = await upsert_brand(conn, brand)
            log.info("  brand_id=%d", brand_id)

            master = load_master(prod_code)
            inv = load_inv_combined(prod_code)
            log.info("  parts_master rows: %d, in-stock parts: %d", len(master), len(inv))

            inserted = 0
            updated = 0
            skipped_dedup = 0
            skipped_no_match = 0
            for ou, inv_data in inv.items():
                if inv_data["on_hand"] <= 0:
                    continue
                m = master.get(ou)
                if m is None:
                    skipped_no_match += 1
                    continue
                parts_num = m["parts_num"]
                if not parts_num:
                    skipped_no_match += 1
                    continue

                # BUY/SNOW dedup
                if prod_code == "BUY" and parts_num.upper() in snow_parts_nums:
                    skipped_dedup += 1
                    continue

                sku = derive_sku(prod_code, brand["aaia_code"], parts_num, ou)
                short, extended = best_description(
                    prod_code, ou, parts_num,
                    m["description"], m["extra_desc"], nelson, maxxima_scrape,
                )

                existed = await conn.fetchval("SELECT 1 FROM product WHERE sku = $1", sku)
                pid = await upsert_product(
                    conn, sku=sku, brand_id=brand_id, name=short, prod_code=prod_code,
                    description=short, extended=extended, tte_ourparts=ou,
                    weight=m["weight"], length=m["length"], width=m["width"], height=m["height"],
                )
                if pid is None:
                    continue
                await upsert_price(conn, pid, m["p1"], m["p2"], m["p3"], m["p4"], m["p5"])

                if existed:
                    updated += 1
                else:
                    inserted += 1

                if prod_code == "SNOW":
                    snow_parts_nums.add(parts_num.upper())

            log.info("  inserted=%d updated=%d dedup_skip=%d no_master=%d",
                     inserted, updated, skipped_dedup, skipped_no_match)
            total_inserted += inserted
            total_updated += updated

        log.info("=" * 60)
        log.info("TOTAL: inserted=%d, updated=%d", total_inserted, total_updated)
        log.info("Next: re-run scripts/link_titan_inventory_v2.py to attach inventory")
        log.info("Next: re-run scripts/reindex_typesense.py to surface in catalog")
    finally:
        await conn.close()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    asyncio.run(main())
