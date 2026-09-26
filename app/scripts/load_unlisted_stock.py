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

Every change is written to `_load_batch_log`, so a batch can be checked,
sampled and undone as a unit:

    --check BATCH     the publish gate: every product has a name that isn't
                      shouting, a price (or is Call to Order) that isn't below
                      cost, a category, no duplicate SKU or brand, its stock
                      linked when the ERP shows Portland/Kent on hand, and only
                      photos served from our own /static. Exit 1 on a failure.
    --sample N BATCH  N pages spread across the batch's lines, as site URLs
                      (staff logins can open hidden pages).
    --publish BATCH   runs --check, refuses on any failure not named in
                      --allow, then un-hides the batch, activates its brands,
                      re-resolves visibility and re-indexes search.
    --rollback BATCH  deletes the batch's new products, restores tidied names
                      and brand codes, removes brands/categories it created.

Run on the server from app/backend (settings are read from app/.env):
    .venv/bin/python ../scripts/load_unlisted_stock.py /tmp/approved.json --batch unlisted-2026-09-25 [--apply]
    .venv/bin/python ../scripts/load_unlisted_stock.py --check unlisted-2026-09-25
    .venv/bin/python ../scripts/load_unlisted_stock.py --sample 10 unlisted-2026-09-25
    .venv/bin/python ../scripts/load_unlisted_stock.py --publish unlisted-2026-09-25 [--apply]
    .venv/bin/python ../scripts/load_unlisted_stock.py --rollback unlisted-2026-09-25 [--apply]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
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
SITE_URL = "https://nelsontruckequipment.com"
STATIC_DIR = _BACKEND_DIR / "static"
LOG_TABLE = "_load_batch_log"
PUBLIC_WAREHOUSES = (1, 2)   # Portland, Kent: the stock this site sells from


def load_app_env() -> None:
    """Read app/.env the way the systemd units do (EnvironmentFile), so a run
    from a shell has the same DATABASE_URL and search key. On 2026-09-26 a
    publish run with only DATABASE_URL exported un-hid 885 products but got
    401 from Typesense; the next stock sync re-indexed them."""
    path = APP_DIR / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


async def ensure_log(conn) -> None:
    await conn.execute(
        f"CREATE TABLE IF NOT EXISTS {LOG_TABLE} (id serial PRIMARY KEY, batch text NOT NULL, "
        "kind text NOT NULL, ref_id int NOT NULL, old jsonb, created_at timestamptz NOT NULL DEFAULT now())")


async def note(conn, batch: str, kind: str, ref_id: int, old: dict | None = None) -> None:
    await conn.execute(f"INSERT INTO {LOG_TABLE} (batch, kind, ref_id, old) VALUES ($1,$2,$3,$4::jsonb)",
                       batch, kind, ref_id, json.dumps(old) if old is not None else None)


async def logged(conn, batch: str, *kinds: str) -> list[int]:
    return [r["ref_id"] for r in await conn.fetch(
        f"SELECT ref_id FROM {LOG_TABLE} WHERE batch=$1 AND kind = ANY($2::text[]) ORDER BY id",
        batch, list(kinds))]


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


async def ensure_brands(conn, codes: set[str], batch: str) -> dict[str, dict]:
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
        row = await conn.fetchrow("SELECT id, prod_code, aaia_code FROM brand WHERE name = $1", cfg["name"])
        if row:
            await note(conn, batch, "brand_codes", row["id"],
                       {"prod_code": row["prod_code"], "aaia_code": row["aaia_code"]})
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
            await note(conn, batch, "brand_created", bid)
            log.info("brand %s: created id %d", cfg["name"], bid)
        out[pc] = {"id": bid, "aaia": cfg["aaia"]}
    return out


async def ensure_towing_categories(conn, batch: str) -> dict[int, int]:
    parent = await conn.fetchrow("SELECT id, full_path, depth FROM category WHERE id=$1", TOWING_PARENT_ID)
    out = {}
    for i, (key, (name, slug)) in enumerate(TOWING.items()):
        cid = await conn.fetchval("SELECT id FROM category WHERE slug=$1", slug)
        if cid is None:
            cid = await conn.fetchval(
                "INSERT INTO category (name, slug, parent_id, full_path, depth, sort_order, "
                "is_featured, is_active) VALUES ($1,$2,$3,$4,$5,$6,FALSE,TRUE) RETURNING id",
                name, slug, parent["id"], f'{parent["full_path"]} > {name}', parent["depth"] + 1, i * 10)
            await note(conn, batch, "category_created", cid)
            log.info("category %s: created id %d", name, cid)
        out[key] = cid
    return out


async def load(conn, rows: list[dict], batch: str) -> None:
    await ensure_log(conn)
    brands = await ensure_brands(conn, {r["prod_code"] for r in rows if not r.get("product_id")}, batch)
    towing = await ensure_towing_categories(conn, batch)
    tag = f"[{batch}]"
    created = renamed = existed = 0
    for r in rows:
        cat = towing.get(r["category_id"], r["category_id"])
        if r.get("product_id"):                       # existing hidden page: tidy only
            prev = await conn.fetchrow("SELECT name, admin_notes FROM product WHERE id=$1", r["product_id"])
            await note(conn, batch, "product_tidied", r["product_id"], dict(prev))
            await conn.execute(
                "UPDATE product SET name=$1, admin_notes=concat_ws(E'\\n', admin_notes, $2::text), "
                "updated_at=NOW() WHERE id=$3", r["name"], tag, r["product_id"])
            if cat and not await conn.fetchval("SELECT 1 FROM product_category WHERE product_id=$1", r["product_id"]):
                await conn.execute("INSERT INTO product_category (product_id, category_id, is_primary) "
                                   "VALUES ($1,$2,TRUE)", r["product_id"], cat)
                await note(conn, batch, "category_linked", r["product_id"], {"category_id": cat})
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
        await note(conn, batch, "product_created", pid)
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


CHECKS = {
    "name": "name is blank, over 120 characters or ALL CAPS",
    "price": "no price and not Call to Order",
    "below_cost": "list price below cost",
    "category": "no category",
    "duplicate_sku": "SKU exists more than once",
    "duplicate_brand": "brand name or prod code shared with another brand",
    "stock": "ERP shows Portland/Kent stock but the page has none (wait for the 15-minute sync)",
    "photo": "photo not served from our own /static, or the file is missing",
    "not_hidden": "already visible before publish",
}


async def check(conn, batch: str, *, before_publish: bool = True) -> dict[str, list[str]]:
    """The publish gate. Returns {check: [sku (name) ...]} for every failure."""
    created = await logged(conn, batch, "product_created")
    ids = created + await logged(conn, batch, "product_tidied")
    fail: dict[str, list[str]] = defaultdict(list)
    if not ids:
        log.warning("batch %s has no products", batch)
        return fail
    rows = await conn.fetch("""
        SELECT p.id, p.sku, p.name, p.cta_mode::text AS cta, p.base_hidden, p.tte_ourparts_num,
               b.name AS brand,
               pp.suggested_retail_price AS msrp, pp.retail_price AS list, pp.jobber_price AS jobber,
               pp.cost,
               (SELECT count(*) FROM product_category pc WHERE pc.product_id = p.id) AS cats,
               (SELECT count(*) FROM product q WHERE upper(q.sku) = upper(p.sku)) AS sku_n,
               (SELECT count(*) FROM brand b2 WHERE b2.id <> b.id AND (lower(b2.name) = lower(b.name)
                    OR upper(coalesce(b2.prod_code, '')) = upper(coalesce(b.prod_code, '-')))) AS brand_dupes,
               (SELECT coalesce(sum(i.on_hand), 0) FROM product_inventory i WHERE i.product_id = p.id) AS on_site,
               (SELECT coalesce(sum(e.onhand), 0) FROM erp_onhand e WHERE e.part_number = p.tte_ourparts_num
                    AND e.warehouse = ANY($2::int[])) AS in_erp
        FROM product p JOIN brand b ON b.id = p.brand_id
        LEFT JOIN product_price pp ON pp.product_id = p.id
        WHERE p.id = ANY($1::int[])""", ids, list(PUBLIC_WAREHOUSES))
    created_set = set(created)
    for r in rows:
        tag = f'{r["sku"]} ({(r["name"] or "")[:50]})'
        name = r["name"] or ""
        letters = [c for c in name if c.isalpha()]
        if not name.strip() or len(name) > 120 or (len(letters) >= 4 and name == name.upper()):
            fail["name"].append(tag)
        if r["cta"] != "CALL_TO_ORDER" and not any((v or 0) > 0 for v in (r["list"], r["msrp"], r["jobber"])):
            fail["price"].append(tag)
        if r["list"] and r["cost"] and r["list"] < r["cost"]:
            fail["below_cost"].append(f'{tag} list {r["list"]} < cost {r["cost"]}')
        if not r["cats"]:
            fail["category"].append(tag)
        if r["sku_n"] > 1:
            fail["duplicate_sku"].append(tag)
        if r["brand_dupes"]:
            fail["duplicate_brand"].append(f'{tag} brand {r["brand"]}')
        if r["in_erp"] > 0 and r["on_site"] <= 0:
            fail["stock"].append(f'{tag} ERP on hand {r["in_erp"]}')
        if before_publish and r["id"] in created_set and not r["base_hidden"]:
            fail["not_hidden"].append(tag)
    for img in await conn.fetch("SELECT i.url, p.sku FROM product_image i JOIN product p ON p.id = i.product_id "
                                "WHERE i.product_id = ANY($1::int[])", ids):
        url = img["url"] or ""
        if not url.startswith("/static/") or not (STATIC_DIR / url[len("/static/"):]).is_file():
            fail["photo"].append(f'{img["sku"]} {url[:80]}')
    log.info("check %s: %d products (%d new, %d tidied)", batch, len(rows), len(created), len(ids) - len(created))
    for key, desc in CHECKS.items():
        bad = fail.get(key, [])
        log.info("  %-15s %s  %s", key, "OK  " if not bad else f"FAIL {len(bad)}", desc)
        for b in bad[:8]:
            log.info("      %s", b)
    return fail


async def sample(conn, batch: str, n: int) -> None:
    """n pages spread across the batch's lines, including a Call to Order unit
    and a tidied page when the batch has them."""
    rows = await conn.fetch(f"""
        SELECT p.id, p.sku, p.name, b.name AS brand, p.cta_mode::text AS cta, l.kind
        FROM {LOG_TABLE} l JOIN product p ON p.id = l.ref_id JOIN brand b ON b.id = p.brand_id
        WHERE l.batch = $1 AND l.kind IN ('product_created', 'product_tidied')
        ORDER BY random()""", batch)
    picks: dict[int, object] = {}
    for want in (lambda r: r["cta"] == "CALL_TO_ORDER", lambda r: r["kind"] == "product_tidied"):
        hit = next((r for r in rows if want(r)), None)
        if hit:
            picks[hit["id"]] = hit
    by_brand: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["kind"] == "product_created" and r["id"] not in picks:
            by_brand[r["brand"]].append(r)
    order = sorted(by_brand, key=lambda k: -len(by_brand[k]))
    while len(picks) < n and any(by_brand.values()):
        for brand in order:
            if by_brand[brand] and len(picks) < n:
                r = by_brand[brand].pop()
                picks[r["id"]] = r
    for r in list(picks.values())[:n]:
        extra = (" [Call to Order]" if r["cta"] == "CALL_TO_ORDER" else "") + \
                (" [was a hidden page]" if r["kind"] == "product_tidied" else "")
        print(f'{SITE_URL}/product/{r["sku"]}\t{r["brand"]}\t{r["name"]}{extra}')


async def rollback(conn, batch: str) -> None:
    created = await logged(conn, batch, "product_created")
    await conn.execute("DELETE FROM product WHERE id = ANY($1::int[])", created)
    for r in await conn.fetch(f"SELECT ref_id, old FROM {LOG_TABLE} WHERE batch=$1 AND kind='product_tidied'", batch):
        old = json.loads(r["old"])
        await conn.execute("UPDATE product SET name=$1, admin_notes=$2, updated_at=NOW() WHERE id=$3",
                           old["name"], old["admin_notes"], r["ref_id"])
    for r in await conn.fetch(f"SELECT ref_id, old FROM {LOG_TABLE} WHERE batch=$1 AND kind='category_linked'", batch):
        await conn.execute("DELETE FROM product_category WHERE product_id=$1 AND category_id=$2",
                           r["ref_id"], json.loads(r["old"])["category_id"])
    for r in await conn.fetch(f"SELECT ref_id, old FROM {LOG_TABLE} WHERE batch=$1 AND kind='brand_codes'", batch):
        old = json.loads(r["old"])
        await conn.execute("UPDATE brand SET prod_code=$1, aaia_code=$2, updated_at=NOW() WHERE id=$3",
                           old["prod_code"], old["aaia_code"], r["ref_id"])
    gone_b = await conn.fetch("DELETE FROM brand WHERE id = ANY($1::int[]) AND NOT EXISTS "
                              "(SELECT 1 FROM product WHERE product.brand_id = brand.id) RETURNING id",
                              await logged(conn, batch, "brand_created"))
    gone_c = await conn.fetch("DELETE FROM category WHERE id = ANY($1::int[]) AND NOT EXISTS "
                              "(SELECT 1 FROM product_category pc WHERE pc.category_id = category.id) RETURNING id",
                              await logged(conn, batch, "category_created"))
    await conn.execute(f"DELETE FROM {LOG_TABLE} WHERE batch=$1", batch)
    log.info("rollback %s: deleted %d products, %d brands, %d categories; restored tidied names",
             batch, len(created), len(gone_b), len(gone_c))


async def publish(conn, batch: str, apply: bool, allow: set[str]) -> bool:
    fail = await check(conn, batch)
    blocking = [k for k, v in fail.items() if v and k not in allow]
    if blocking:
        log.error("NOT publishing %s: %s failed (fix them, or name them in --allow)", batch, ", ".join(blocking))
        return False
    ids = (await logged(conn, batch, "product_created")) + (await logged(conn, batch, "product_tidied"))
    ids = [r["id"] for r in await conn.fetch(
        "SELECT id FROM product WHERE id = ANY($1::int[]) AND base_hidden", ids)]
    log.info("%d products in %s are hidden and ready", len(ids), batch)
    if not apply or not ids:
        return True
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
    return True


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", nargs="?", help="reviewed JSON list")
    ap.add_argument("--batch", help="tag written to admin_notes, e.g. unlisted-2026-09-25")
    ap.add_argument("--publish", metavar="BATCH")
    ap.add_argument("--check", metavar="BATCH")
    ap.add_argument("--sample", nargs=2, metavar=("N", "BATCH"))
    ap.add_argument("--rollback", metavar="BATCH")
    ap.add_argument("--allow", default="", help="comma-separated checks --publish may pass over")
    ap.add_argument("--apply", action="store_true", help="commit (default: dry run, rolled back)")
    a = ap.parse_args()
    load_app_env()
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://", 1)
    conn = await asyncpg.connect(dsn)
    try:
        await ensure_log(conn)
        if a.check:
            failed = any(v for v in (await check(conn, a.check)).values())
            raise SystemExit(1 if failed else 0)
        if a.sample:
            await sample(conn, a.sample[1], int(a.sample[0]))
            return
        if a.publish:
            ok = await publish(conn, a.publish, a.apply, {x.strip() for x in a.allow.split(",") if x.strip()})
            raise SystemExit(0 if ok else 1)
        if a.rollback:
            tr = conn.transaction()
            await tr.start()
            try:
                await rollback(conn, a.rollback)
            except BaseException:
                await tr.rollback()
                raise
            if a.apply:
                await tr.commit()
                log.info("COMMITTED")
            else:
                await tr.rollback()
                log.info("dry run — rolled back (add --apply)")
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
