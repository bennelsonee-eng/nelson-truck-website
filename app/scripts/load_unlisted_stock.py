"""load_unlisted_stock.py — give in-stock ERP parts a product page, hidden first.

Input is a reviewed JSON list (one object per part) built from the ERP parts
master plus a naming/category pass:

    {"ourparts": "JERR4017000739", "prod_code": "JERR", "parts_num": "4017000739",
     "name": "...", "description": "...", "extended": "...", "category_id": 9002,
     "freight": false, "call_to_order": false, "p1".."p5": "36.43", "weight"/"length"/"width"/"height": "2.00",
     "product_id": 300765   # only for an existing hidden page being cleaned up}

What it does (one transaction; dry run unless --apply):
  1. brand rows for the lines that have none (or a brand row without codes),
  2. the Towing & Recovery component categories (ids 9001-9008 in the input),
  3. products loaded HIDDEN (base_hidden) and tagged in admin_notes with the
     batch name, P1-P5 prices (a zero is stored as NULL — a $0.00 tier would
     be charged to a logged-in customer), one primary category,
  4. for existing hidden pages: the new name and a category if they have none.

    --publish BATCH   un-hides every product tagged with BATCH, re-resolves
                      visibility and re-indexes search. Run the stock linker
                      after (or wait for its 15-minute timer).

Run on the server from app/backend:
    .venv/bin/python ../scripts/load_unlisted_stock.py /tmp/approved.json --batch unlisted-2026-09-25 [--apply]
    .venv/bin/python ../scripts/load_unlisted_stock.py --publish unlisted-2026-09-25 [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import asyncpg

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
_BACKEND_DIR = APP_DIR / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("load_unlisted")

# ERP prod code -> brand row.  "existing" rows only get their codes filled in.
BRANDS = {
    "JERR":   {"name": "Jerr-Dan",         "aaia": "JERR",   "slug": "jerr-dan",        "web": "https://www.jerr-dan.com"},
    "COL":    {"name": "Collins",          "aaia": "COL",    "slug": "collins",         "web": "https://www.collinsdollies.com"},
    "CMF":    {"name": "CM Truck Beds",    "aaia": "CMF",    "slug": "cm-truck-beds",   "web": "https://www.cmtruckbeds.com"},
    "RGY":    {"name": "Rugby",            "aaia": "RGY",    "slug": "rugby",           "web": "https://www.rugbymfg.com"},
    "PROTEC": {"name": "Protech",          "aaia": "PROTEC", "slug": "protech",         "web": "https://www.protechpro.com"},
    "BAWER":  {"name": "Bawer",            "aaia": "BAWER",  "slug": "bawer",           "web": "https://www.bawer.com"},
    "HRP":    {"name": "Towing Supplies",  "aaia": "HRP",    "slug": "towing-supplies", "web": None},
    "SNG":    {"name": "Switch-N-Go",      "aaia": "SNG",    "slug": "switch-n-go",     "web": "https://www.switchngo.com"},
}
# Lines whose parts live under another line's brand row (see the linker's
# PROD_CODE_ALIASES): Meyer spreaders (MYS) are sold as Meyer Products (MYP).
ALIASES = {"MYS": "MYP"}

TOWING = {
    9001: ("Wrecker & Carrier Bodies",       "towing-recovery-wrecker-carrier-bodies"),
    9002: ("Wheel Lifts & Underlifts",       "towing-recovery-wheel-lifts-underlifts"),
    9003: ("Tow Dollies",                    "towing-recovery-tow-dollies"),
    9004: ("Slings, Chains & Rigging",       "towing-recovery-slings-chains-rigging"),
    9005: ("Towing Hydraulics & Cylinders",  "towing-recovery-hydraulics-cylinders"),
    9006: ("Towing Controls & Electrical",   "towing-recovery-controls-electrical"),
    9007: ("Towing Lighting",                "towing-recovery-lighting"),
    9008: ("Parts, Hardware & Accessories",  "towing-recovery-parts-hardware-accessories"),
}
TOWING_PARENT_ID = 468   # Truck Equipment > Towing & Recovery


def money(v) -> Decimal | None:
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, AttributeError, TypeError):
        return None
    return d if d > 0 else None


def dim(v) -> Decimal | None:
    d = money(v)
    return d if d is not None and d < 100000 else None


def derive_sku(aaia: str, prod_code: str, parts_num: str, ourparts: str) -> str:
    pn = (parts_num or "").strip().upper()
    if not any(ch.isdigit() for ch in pn):        # blank, or "NOT SOLD THIS WAY"
        pn = ourparts[len(prod_code):] if ourparts.upper().startswith(prod_code) else ourparts
    return f"{aaia}-{pn.strip('-')}"[:64]


async def ensure_brands(conn, codes: set[str]) -> dict[str, dict]:
    """prod code -> {"id", "aaia"} for every line in the batch."""
    out: dict[str, dict] = {}
    for r in await conn.fetch("SELECT id, name, prod_code, aaia_code FROM brand "
                              "WHERE coalesce(prod_code,'') <> ''"):
        out[r["prod_code"].upper()] = {"id": r["id"], "aaia": (r["aaia_code"] or r["prod_code"]).upper()}
    for alias, target in ALIASES.items():
        if target in out:
            out.setdefault(alias, out[target])
    for pc in sorted(codes - out.keys()):
        cfg = BRANDS.get(pc)
        if not cfg:
            raise SystemExit(f"No brand configured for prod code {pc}")
        row = await conn.fetchrow("SELECT id, prod_code FROM brand WHERE name = $1", cfg["name"])
        if row:
            await conn.execute("UPDATE brand SET prod_code=$1, aaia_code=$2, updated_at=NOW() WHERE id=$3",
                               pc, cfg["aaia"], row["id"])
            log.info("brand %s (id %d): set prod_code/aaia %s", cfg["name"], row["id"], pc)
            bid = row["id"]
        else:
            bid = await conn.fetchval(
                # Inactive until --publish: the A-Z brands page lists every
                # active brand, even one with nothing live yet.
                "INSERT INTO brand (name, slug, aaia_code, prod_code, website_url, is_featured, "
                "sort_order, is_active) VALUES ($1,$2,$3,$4,$5,FALSE,1000,FALSE) RETURNING id",
                cfg["name"], cfg["slug"], cfg["aaia"], pc, cfg["web"])
            log.info("brand %s: created id %d", cfg["name"], bid)
        out[pc] = {"id": bid, "aaia": cfg["aaia"]}
    return out


async def ensure_towing_categories(conn) -> dict[int, int]:
    parent = await conn.fetchrow("SELECT id, full_path, depth FROM category WHERE id=$1", TOWING_PARENT_ID)
    out = {}
    for i, (key, (name, slug)) in enumerate(TOWING.items()):
        cid = await conn.fetchval("SELECT id FROM category WHERE slug=$1", slug)
        if cid is None:
            cid = await conn.fetchval(
                "INSERT INTO category (name, slug, parent_id, full_path, depth, sort_order, "
                "is_featured, is_active) VALUES ($1,$2,$3,$4,$5,$6,FALSE,TRUE) RETURNING id",
                name, slug, parent["id"], f'{parent["full_path"]} > {name}', parent["depth"] + 1, i * 10)
            log.info("category %s: created id %d", name, cid)
        out[key] = cid
    return out


async def load(conn, rows: list[dict], batch: str) -> None:
    brands = await ensure_brands(conn, {r["prod_code"] for r in rows if not r.get("product_id")})
    towing = await ensure_towing_categories(conn)
    tag = f"[{batch}]"
    created = renamed = existed = 0
    for r in rows:
        cat = towing.get(r["category_id"], r["category_id"])
        if r.get("product_id"):                       # existing hidden page: tidy only
            await conn.execute(
                "UPDATE product SET name=$1, admin_notes=concat_ws(E'\\n', admin_notes, $2::text), "
                "updated_at=NOW() WHERE id=$3", r["name"], tag, r["product_id"])
            if cat and not await conn.fetchval("SELECT 1 FROM product_category WHERE product_id=$1", r["product_id"]):
                await conn.execute("INSERT INTO product_category (product_id, category_id, is_primary) "
                                   "VALUES ($1,$2,TRUE)", r["product_id"], cat)
            renamed += 1
            continue
        pc = r["prod_code"]
        b = brands[pc]
        sku = derive_sku(b["aaia"], pc, r.get("parts_num", ""), r["ourparts"])
        if await conn.fetchval("SELECT 1 FROM product WHERE upper(sku)=upper($1)", sku):
            existed += 1                              # the linker reaches it now
            continue
        freight = bool(r.get("freight"))
        # Complete units (bodies, hoists, spreaders, liftgates) follow the truck
        # body rule: Call to Order with both branch numbers, and both
        # companies' stock shown (product.show_all_branch_stock).
        unit = bool(r.get("call_to_order"))
        cta = "CALL_TO_ORDER" if unit else "QUOTE_SHIPPING" if freight else "ADD_TO_CART"
        pid = await conn.fetchval(
            "INSERT INTO product (sku, brand_id, prod_code, name, description, extended_description, "
            "tte_ourparts_num, weight_lb, length_in, width_in, height_in, cta_mode, requires_shipping, "
            "taxable, own_box, ship_quote, free_ground, shipping_mode, base_shipping_mode, "
            "base_hidden, is_hidden, is_hidden_retail, is_hidden_wholesale, is_hidden_dealer, "
            "is_hidden_municipality, is_for_sale, login_required, saleprice_hidden, admin_notes, "
            "show_all_branch_stock) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::cta_mode,TRUE,TRUE,FALSE,$13,0,$14,$14,"
            "TRUE,TRUE,TRUE,TRUE,TRUE,TRUE,TRUE,FALSE,FALSE,$15,$16) RETURNING id",
            sku, b["id"], pc, r["name"], r.get("description") or r["name"], r.get("extended") or None,
            r["ourparts"], dim(r.get("weight")), dim(r.get("length")), dim(r.get("width")), dim(r.get("height")),
            cta, freight and not unit, "truck_freight" if freight else "ship", tag, unit)
        prices = [money(r.get(k)) for k in ("p1", "p2", "p3", "p4", "p5")]
        if any(prices):
            await conn.execute(
                "INSERT INTO product_price (product_id, suggested_retail_price, retail_price, jobber_price, "
                "dealer_price, cost, last_synced_at) VALUES ($1,$2,$3,$4,$5,$6,NOW())", pid, *prices)
        if cat:
            await conn.execute("INSERT INTO product_category (product_id, category_id, is_primary) "
                               "VALUES ($1,$2,TRUE)", pid, cat)
        created += 1
    log.info("created %d hidden products, tidied %d hidden pages, %d already had a page (sku exists)",
             created, renamed, existed)


async def publish(conn, batch: str, apply: bool) -> None:
    tag = f"[{batch}]"
    ids = [r["id"] for r in await conn.fetch(
        "SELECT id FROM product WHERE admin_notes LIKE '%' || $1 || '%' AND base_hidden", tag)]
    log.info("%d products tagged %s are hidden", len(ids), tag)
    if not apply or not ids:
        return
    # Committed before the resolver runs: it reads through its own session.
    await conn.execute("UPDATE product SET base_hidden=FALSE, updated_at=NOW() WHERE id = ANY($1::int[])", ids)
    await conn.execute("UPDATE brand SET is_active=TRUE, updated_at=NOW() WHERE NOT is_active AND id IN "
                       "(SELECT brand_id FROM product WHERE id = ANY($1::int[]))", ids)
    from app.database import async_session
    from app.services.catalog_visibility import resolve_effective
    from app.services.search import index_products
    async with async_session() as session:
        await resolve_effective(session)
        n = await index_products(session, ids)
    log.info("published %d; re-indexed %d", len(ids), n)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", nargs="?", help="reviewed JSON list")
    ap.add_argument("--batch", help="tag written to admin_notes, e.g. unlisted-2026-09-25")
    ap.add_argument("--publish", metavar="BATCH")
    ap.add_argument("--apply", action="store_true", help="commit (default: dry run, rolled back)")
    a = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        if a.publish:
            await publish(conn, a.publish, a.apply)
            return
        rows = json.load(open(a.input, encoding="utf-8"))
        tr = conn.transaction()
        await tr.start()
        try:
            await load(conn, rows, a.batch)
        except BaseException:
            await tr.rollback()
            raise
        if a.apply:
            await tr.commit()
            log.info("COMMITTED")
        else:
            await tr.rollback()
            log.info("dry run — rolled back (add --apply)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
