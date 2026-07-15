"""Initial data import — populates the new Titan website DB from production CSVs.

Run from `app/backend/` directory with venv activated:

    python -m scripts.import_initial_data --all
    python -m scripts.import_initial_data --warehouses --brands --customers
    python -m scripts.import_initial_data --products --prices
    python -m scripts.import_initial_data --inventory --contracts
    python -m scripts.import_initial_data --reset --all   # truncate first

Each section is idempotent (re-runs are safe — uses UPSERT) and logs progress.

Sections (run in this order — later depend on earlier):
  1. warehouses    — seed 4 warehouses (Spokane=10, Boise=19, Portland=1, Nelson=0)
  2. brands        — dci_codes (132 rows) → Brand
  3. customers     — distinct cust_ids from contracts_copy → Customer (jobber tier default)
  4. products      — nte_parts_master (filter to Titan-relevant) → Product
  5. prices        — nte_parts_master P1-P5 → ProductPrice
  6. inventory     — tte_inv_days + nte_inv_days → ProductInventory
  7. contracts     — contracts_copy (Titan only, ~605K) → Contract
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Iterator

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Force UTF-8 stdout for emoji/special chars in logs on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# Increase CSV field-size limit (descriptions can be large)
_max = sys.maxsize
while True:
    try:
        csv.field_size_limit(_max)
        break
    except OverflowError:
        _max = int(_max / 10)
        if _max < 1_000_000:
            csv.field_size_limit(1_000_000)
            break


# Add backend/ to path so `app.*` imports work when running as a script
SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent  # app/
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.database import async_session, engine  # noqa: E402
# Force-disable SQL echo (engine was created with echo=settings.debug which is True in dev)
engine.echo = False
engine.sync_engine.echo = False
from app.models import (  # noqa: E402
    Brand,
    Contract,
    Customer,
    CustomerTier,
    Product,
    ProductInventory,
    ProductPrice,
    Warehouse,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("import")

# Quiet down SQLAlchemy's verbose echo (debug=True in config.py would spam every SQL statement)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)


DATA_DIR = APP_DIR / "data"
DUMPS_DIR = DATA_DIR / "mysql_dumps"
WSM_DIR = DATA_DIR / "wsm_export"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def parse_decimal(s: Any) -> Decimal | None:
    """Parse decimal, returning None on empty/invalid."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    s = s.replace("$", "").replace(",", "")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def parse_int(s: Any) -> int | None:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def parse_date(s: Any) -> date | None:
    if s is None:
        return None
    s = str(s).strip()
    if not s or s in ("0000-00-00", "0000-00-00 00:00:00"):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def slugify(s: str) -> str:
    """Lowercase, alphanumeric + hyphens. Best-effort."""
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s or "unnamed"


def chunked(iterable: Iterable, size: int) -> Iterator[list]:
    """Yield successive chunks of `size` items from iterable."""
    chunk: list = []
    for item in iterable:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


# --------------------------------------------------------------------------- #
# 1. Seed warehouses
# --------------------------------------------------------------------------- #


_WAREHOUSE_KEYS = ("code", "name", "short_name", "is_active", "emits_own_facs_file",
                   "facs_route_label", "ship_via_default", "address1", "city", "state", "zip", "phone")


def _wh(**kwargs) -> dict:
    """Build a warehouse dict with all keys present (None when not specified)."""
    return {k: kwargs.get(k) for k in _WAREHOUSE_KEYS}


WAREHOUSE_SEED: list[dict] = [
    _wh(code=10, name="Spokane HQ", short_name="SPO",
        is_active=True, emits_own_facs_file=True, facs_route_label="SPO",
        ship_via_default="MM/DD PPD",
        address1="605 N. Fancher Rd.", city="Spokane", state="WA", zip="99212",
        phone="509-534-5010"),
    _wh(code=19, name="Boise", short_name="BOISE",
        is_active=True, emits_own_facs_file=True, facs_route_label="BOISE",
        ship_via_default="MM/DD PPD",
        address1="1445 W Commerce Ave.", city="Boise", state="ID", zip="83705",
        phone="800-346-1704"),
    _wh(code=1, name="Portland (rolls into NELSON file)", short_name="PORTLAND",
        is_active=True, emits_own_facs_file=False, facs_route_label="NELSON",
        ship_via_default="PAL"),
    _wh(code=0, name="Nelson Truck Equipment (Kent + Portland combined)", short_name="NELSON",
        is_active=True, emits_own_facs_file=True, facs_route_label="NELSON",
        ship_via_default="PAL"),
]


async def import_warehouses(db: AsyncSession) -> int:
    log.info("Seeding warehouses…")
    stmt = pg_insert(Warehouse).values(WAREHOUSE_SEED)
    stmt = stmt.on_conflict_do_update(
        index_elements=["code"],
        set_={
            k: stmt.excluded[k]
            for k in WAREHOUSE_SEED[0].keys()
            if k != "code"
        },
    )
    await db.execute(stmt)
    await db.commit()
    log.info("  Warehouses upserted: %d", len(WAREHOUSE_SEED))
    return len(WAREHOUSE_SEED)


# --------------------------------------------------------------------------- #
# 2. Brands (from dci_codes)
# --------------------------------------------------------------------------- #


async def import_brands(db: AsyncSession) -> int:
    f = DUMPS_DIR / "dci_codes.csv"
    if not f.exists():
        log.error("Missing %s", f)
        return 0

    log.info("Importing brands from %s…", f.name)
    rows: list[dict] = []
    seen_slugs: set[str] = set()
    seen_names: set[str] = set()

    with f.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for r in reader:
            name = (r.get("manu_title") or "").strip()
            prod_code = (r.get("prod_code") or "").strip()
            aaia_code = (r.get("aaia_code") or "").strip()
            if not name:
                continue

            base_slug = slugify(name)
            slug = base_slug
            i = 2
            while slug in seen_slugs:
                slug = f"{base_slug}-{i}"
                i += 1
            seen_slugs.add(slug)

            # Dedupe on name (different prod_code rows can share manu_title)
            # but we want one Brand row per unique name. Use name as key.
            if name in seen_names:
                continue
            seen_names.add(name)

            rows.append({
                "name": name,
                "slug": slug,
                "legacy_wsm_prefix": aaia_code or None,  # AAIA is what WSM STOCKID uses
                "is_featured": False,  # admin marks featured later (per DI-030 — top ~38 brands)
                "sort_order": 1000,
                "is_active": True,
            })

    if not rows:
        log.warning("  No brands to import.")
        return 0

    stmt = pg_insert(Brand).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["name"],
        set_={"legacy_wsm_prefix": stmt.excluded.legacy_wsm_prefix},
    )
    await db.execute(stmt)
    await db.commit()
    log.info("  Brands upserted: %d", len(rows))
    return len(rows)


# --------------------------------------------------------------------------- #
# 3. Customers (extracted from contracts_copy)
# --------------------------------------------------------------------------- #


async def import_customers(db: AsyncSession) -> int:
    f = DUMPS_DIR / "contracts_copy.csv"
    if not f.exists():
        log.error("Missing %s", f)
        return 0

    log.info("Extracting unique Nelson customer numbers from %s…", f.name)
    cust_ids: set[str] = set()

    with f.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for r in reader:
            company = (r.get("company") or "").strip().lower()
            if company != "nelson":
                continue
            cid = (r.get("cust_id") or "").strip()
            if cid:
                cust_ids.add(cid)

    log.info("  Unique Nelson customer numbers: %d", len(cust_ids))
    if not cust_ids:
        return 0

    rows = [
        {
            "customer_number": cid,
            "tier": CustomerTier.JOBBER,  # default — admin tags real tier later
            "name": f"Customer {cid}",     # placeholder — real name from a separate import later
            "is_active": True,
            "is_tax_exempt": False,
        }
        for cid in sorted(cust_ids)
    ]

    # Add the anonymous-retail sentinel (per addendum 003).
    # Nelson's website-sales sentinel is customer "9" (Titan's was "106415").
    # Its company='nelson' contracts define the website retail price book. Must
    # match RETAIL_SENTINEL_CUSTOMER_NUMBER in services/pricing_service.py.
    NELSON_RETAIL_SENTINEL = "9"
    if NELSON_RETAIL_SENTINEL not in cust_ids:
        rows.append({
            "customer_number": NELSON_RETAIL_SENTINEL,
            "tier": CustomerTier.RETAIL,
            "name": "Anonymous Retail (sentinel for FACS web orders)",
            "is_active": True,
            "is_tax_exempt": False,
        })

    inserted = 0
    for chunk in chunked(rows, 500):
        stmt = pg_insert(Customer).values(chunk)
        stmt = stmt.on_conflict_do_nothing(index_elements=["customer_number"])
        result = await db.execute(stmt)
        await db.commit()
        inserted += result.rowcount or 0

    log.info("  Customers upserted: %d (newly inserted: %d)", len(rows), inserted)
    return len(rows)


# --------------------------------------------------------------------------- #
# 4. Products (from nte_parts_master, with prices in same pass)
# --------------------------------------------------------------------------- #


SKIP_PRODUCT_PLACEHOLDERS = {"#", "number", "Number"}


async def import_products_and_prices(db: AsyncSession) -> tuple[int, int]:
    """Imports Products + ProductPrices in one pass over nte_parts_master.

    Filters out placeholder rows (ourparts_num = "#" or "Number"), inactive
    parts (status = "Z" or similar), and parts with no brand mapping.

    Brand FK resolved via legacy_wsm_prefix → Brand.legacy_wsm_prefix lookup
    (built once in memory at start).
    """
    f = DUMPS_DIR / "nte_parts_master.csv"
    if not f.exists():
        log.error("Missing %s", f)
        return 0, 0

    # Build brand lookup: prod_code (dci_code in our notation) → brand_id
    # We need to look at the dci_codes file to map nte_parts_master.prod_code → Brand
    log.info("Loading brand → id map from dci_codes…")
    dci_path = DUMPS_DIR / "dci_codes.csv"
    if not dci_path.exists():
        log.error("Need dci_codes.csv first (run --brands)")
        return 0, 0

    # dci_codes maps: prod_code (Titan internal, like "YAK") → manu_title (brand name)
    prod_code_to_brand_name: dict[str, str] = {}
    with dci_path.open("r", encoding="utf-8-sig", newline="") as dp:
        for r in csv.DictReader(dp):
            pc = (r.get("prod_code") or "").strip()
            mn = (r.get("manu_title") or "").strip()
            if pc and mn and pc not in prod_code_to_brand_name:
                prod_code_to_brand_name[pc] = mn

    # Load brands from DB → brand_name → brand_id
    result = await db.execute(select(Brand.id, Brand.name))
    brand_name_to_id = {name: bid for (bid, name) in result.all()}
    log.info("  %d prod_code mappings × %d brands in DB", len(prod_code_to_brand_name), len(brand_name_to_id))

    # Read parts master
    log.info("Reading nte_parts_master…")
    products: list[dict] = []
    prices: list[dict] = []
    skipped_placeholder = 0
    skipped_no_brand = 0
    skipped_inactive = 0

    with f.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for r in reader:
            ours = (r.get("ourparts_num") or "").strip()
            if not ours or ours in SKIP_PRODUCT_PLACEHOLDERS:
                skipped_placeholder += 1
                continue

            prod_code = (r.get("prod_code") or "").strip()
            status = (r.get("status") or "").strip().upper()
            if status in ("Z", "D"):  # Z = "Zone-out" / inactive, D = deleted (guess)
                skipped_inactive += 1
                continue

            brand_name = prod_code_to_brand_name.get(prod_code)
            brand_id = brand_name_to_id.get(brand_name) if brand_name else None
            if brand_id is None:
                skipped_no_brand += 1
                continue

            # Description from parts master is short — full content comes from WSM later
            desc = (r.get("description") or "").strip() or None
            extra = (r.get("extra_desc") or "").strip() or None

            products.append({
                "sku": ours,                  # use ourparts_num as our internal SKU
                "legacy_wsm_stockid": None,    # filled in later from WSM CSV
                "legacy_wsm_dealerid": None,
                "brand_id": brand_id,
                "prod_code": prod_code or None,  # for contract brand-match (YAK, WES, TECH, etc.)
                "name": (desc or extra or ours)[:500],
                "description": desc,
                "extended_description": extra,
                "weight_lb": parse_decimal(r.get("weight")),
                "length_in": parse_decimal(r.get("length")),
                "width_in": parse_decimal(r.get("width")),
                "height_in": parse_decimal(r.get("height")),
                "is_hidden": False,
                "is_for_sale": True,
                "free_ground": 0,
            })

            # Tier prices (P1-P5) → ProductPrice
            prices.append({
                "_sku_for_lookup": ours,  # we'll resolve to product_id after products load
                "suggested_retail_price": parse_decimal(r.get("P1")),
                "retail_price": parse_decimal(r.get("P2")),
                "jobber_price": parse_decimal(r.get("P3")),
                "dealer_price": parse_decimal(r.get("P4")),
                "cost": parse_decimal(r.get("P5")),
            })

    log.info(
        "  Parsed %d candidate products. Skipped: placeholders=%d, inactive=%d, no_brand=%d",
        len(products), skipped_placeholder, skipped_inactive, skipped_no_brand,
    )

    # Dedupe by sku — nte_parts_master can have multiple rows per ourparts_num.
    # Keep the LAST occurrence (typically the most recent / authoritative).
    by_sku: dict[str, dict] = {}
    for p in products:
        by_sku[p["sku"]] = p
    products = list(by_sku.values())
    log.info("  After sku dedup: %d unique products", len(products))

    # Same dedupe for prices (keyed by their lookup sku)
    prices_by_sku: dict[str, dict] = {}
    for p in prices:
        prices_by_sku[p["_sku_for_lookup"]] = p
    prices = list(prices_by_sku.values())
    log.info("  After price dedup: %d unique price rows", len(prices))

    # Bulk insert products
    log.info("Inserting products in chunks…")
    inserted = 0
    for chunk in chunked(products, 1000):
        stmt = pg_insert(Product).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sku"],
            set_={
                "brand_id": stmt.excluded.brand_id,
                "prod_code": stmt.excluded.prod_code,
                "name": stmt.excluded.name,
                "description": stmt.excluded.description,
                "extended_description": stmt.excluded.extended_description,
                "weight_lb": stmt.excluded.weight_lb,
                "length_in": stmt.excluded.length_in,
                "width_in": stmt.excluded.width_in,
                "height_in": stmt.excluded.height_in,
            },
        )
        await db.execute(stmt)
        await db.commit()
        inserted += len(chunk)
        if inserted % 10000 == 0:
            log.info("  …%d products inserted", inserted)

    log.info("  Products upserted: %d", inserted)

    # Now resolve sku → product_id for prices, then insert
    log.info("Building sku → product_id map for prices…")
    result = await db.execute(select(Product.id, Product.sku))
    sku_to_pid = {sku: pid for (pid, sku) in result.all()}

    price_rows: list[dict] = []
    for p in prices:
        sku = p.pop("_sku_for_lookup")
        pid = sku_to_pid.get(sku)
        if pid is None:
            continue
        # Skip if all tier columns are empty
        if not any(p[k] is not None for k in ("suggested_retail_price", "retail_price", "jobber_price", "dealer_price", "cost")):
            continue
        p["product_id"] = pid
        price_rows.append(p)

    log.info("Inserting prices in chunks…")
    inserted_prices = 0
    for chunk in chunked(price_rows, 1000):
        stmt = pg_insert(ProductPrice).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["product_id"],
            set_={
                "suggested_retail_price": stmt.excluded.suggested_retail_price,
                "retail_price": stmt.excluded.retail_price,
                "jobber_price": stmt.excluded.jobber_price,
                "dealer_price": stmt.excluded.dealer_price,
                "cost": stmt.excluded.cost,
            },
        )
        await db.execute(stmt)
        await db.commit()
        inserted_prices += len(chunk)
        if inserted_prices % 10000 == 0:
            log.info("  …%d prices inserted", inserted_prices)

    log.info("  Prices upserted: %d", inserted_prices)
    return inserted, inserted_prices


# --------------------------------------------------------------------------- #
# 5. Inventory (from tte_inv_days + nte_inv_days)
# --------------------------------------------------------------------------- #


async def import_inventory(db: AsyncSession) -> int:
    """Loads per-product, per-warehouse on-hand from the *_inv_days tables."""
    log.info("Building sku → product_id and warehouse-code → id maps…")
    result = await db.execute(select(Product.id, Product.sku))
    sku_to_pid = {sku: pid for (pid, sku) in result.all()}
    result = await db.execute(select(Warehouse.id, Warehouse.code))
    wh_code_to_id = {code: wid for (wid, code) in result.all()}
    log.info("  %d products, %d warehouses", len(sku_to_pid), len(wh_code_to_id))

    total = 0
    now = datetime.now(timezone.utc)
    for fname in ("tte_inv_days.csv", "nte_inv_days.csv"):
        f = DUMPS_DIR / fname
        if not f.exists():
            log.warning("Missing %s — skipping", f)
            continue

        log.info("Importing %s…", fname)
        rows: list[dict] = []
        skipped = 0
        with f.open("r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            for r in reader:
                sku = (r.get("ourparts_num") or "").strip()
                wh_code = parse_int(r.get("warehouse"))
                if not sku or wh_code is None:
                    skipped += 1
                    continue
                pid = sku_to_pid.get(sku)
                wid = wh_code_to_id.get(wh_code)
                if pid is None or wid is None:
                    skipped += 1
                    continue
                rows.append({
                    "product_id": pid,
                    "warehouse_id": wid,
                    "on_hand": parse_int(r.get("onhand")) or 0,
                    "last_synced_at": now,
                })

        # Dedupe by (product_id, warehouse_id) — keep last (most recent / authoritative)
        by_pw: dict[tuple[int, int], dict] = {}
        for r in rows:
            by_pw[(r["product_id"], r["warehouse_id"])] = r
        rows = list(by_pw.values())
        log.info("  Parsed %d unique (product, warehouse) pairs (skipped %d unmappable)", len(rows), skipped)

        for chunk in chunked(rows, 1000):
            stmt = pg_insert(ProductInventory).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["product_id", "warehouse_id"],
                set_={
                    "on_hand": stmt.excluded.on_hand,
                    "last_synced_at": stmt.excluded.last_synced_at,
                },
            )
            await db.execute(stmt)
            await db.commit()
            total += len(chunk)

    log.info("  Inventory rows upserted: %d", total)
    return total


# --------------------------------------------------------------------------- #
# 6. Contracts (from contracts_copy, Nelson only, ~113K)
# --------------------------------------------------------------------------- #


async def import_contracts(db: AsyncSession) -> int:
    f = DUMPS_DIR / "contracts_copy.csv"
    if not f.exists():
        log.error("Missing %s", f)
        return 0

    log.info("Building customer_number → id map…")
    result = await db.execute(select(Customer.id, Customer.customer_number))
    cn_to_id = {cn: cid for (cid, cn) in result.all()}
    log.info("  %d customers in DB", len(cn_to_id))

    log.info("Importing contracts (Nelson only)…")
    rows: list[dict] = []
    skipped_company = 0
    skipped_no_customer = 0

    with f.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for r in reader:
            company = (r.get("company") or "").strip().lower()
            if company != "nelson":
                skipped_company += 1
                continue
            cid_raw = (r.get("cust_id") or "").strip()
            customer_id = cn_to_id.get(cid_raw)
            if customer_id is None:
                skipped_no_customer += 1
                continue
            contract_name = (r.get("contract") or "").strip() or "default"
            brand = (r.get("prod_code") or "").strip() or None
            group_code = (r.get("group_code") or "").strip() or None
            if group_code == "0":
                group_code = None  # 0 is wildcard/null
            part_number = (r.get("ourparts_num") or "").strip() or None
            priority = parse_int(r.get("priority")) or 100
            min_qty = parse_int(r.get("min_quantity")) or 0
            formula = (r.get("discount") or "").strip()
            if not formula:
                continue  # skip rows with no formula
            exp = parse_date(r.get("exp_date"))

            rows.append({
                "name": f"contract-{contract_name}",
                "customer_id": customer_id,
                "brand": brand,
                "group_code": group_code,
                "part_number": part_number,
                "priority": priority,
                "min_quantity": min_qty,
                "pricing_formula": formula,
                "expiration_date": exp,
                "is_active": True,
            })

    log.info(
        "  Parsed %d Titan contract rules. Skipped: non-titan=%d, no_customer=%d",
        len(rows), skipped_company, skipped_no_customer,
    )

    if not rows:
        return 0

    log.info("Inserting contracts in chunks…")
    inserted = 0
    for chunk in chunked(rows, 2000):
        stmt = pg_insert(Contract).values(chunk)
        # No good unique key for contracts (could re-import with same data) —
        # for now, just insert and rely on a TRUNCATE in --reset for re-runs
        await db.execute(stmt)
        await db.commit()
        inserted += len(chunk)
        if inserted % 50000 == 0:
            log.info("  …%d contracts inserted", inserted)

    log.info("  Contracts inserted: %d", inserted)
    return inserted


# --------------------------------------------------------------------------- #
# Reset (truncate) — for clean re-runs during dev
# --------------------------------------------------------------------------- #


async def reset_tables(db: AsyncSession, sections: set[str]) -> None:
    """TRUNCATE selected tables. CASCADE handles FK dependencies."""
    table_map = {
        "warehouses": "warehouse",
        "brands": "brand",
        "customers": '"customer"',     # quoted: reserved word in PG
        "products": "product",
        "prices": "product_price",
        "inventory": "product_inventory",
        "contracts": "contract",
    }
    # Map section to its target tables
    targets: list[str] = []
    if "warehouses" in sections:
        targets.append(table_map["warehouses"])
    if "brands" in sections:
        targets.append(table_map["brands"])
    if "customers" in sections:
        targets.append(table_map["customers"])
    if "products" in sections:
        targets.append(table_map["products"])
    if "prices" in sections:
        targets.append(table_map["prices"])
    if "inventory" in sections:
        targets.append(table_map["inventory"])
    if "contracts" in sections:
        targets.append(table_map["contracts"])

    if not targets:
        return

    log.warning("RESET: TRUNCATE %s", ", ".join(targets))
    await db.execute(text(f"TRUNCATE {', '.join(targets)} CASCADE"))
    await db.commit()


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


SECTIONS = ["warehouses", "brands", "customers", "products", "prices", "inventory", "contracts"]


async def main_async(args: argparse.Namespace) -> None:
    sections: set[str] = set()
    if args.all:
        sections = set(SECTIONS)
    else:
        for s in SECTIONS:
            if getattr(args, s, False):
                sections.add(s)

    if not sections:
        log.error("No sections selected. Use --all or one of: %s", ", ".join(f"--{s}" for s in SECTIONS))
        return

    log.info("=" * 70)
    log.info("Selected sections: %s", ", ".join(sorted(sections)))
    log.info("Reset (truncate) first: %s", args.reset)
    log.info("=" * 70)

    async with async_session() as db:
        if args.reset:
            await reset_tables(db, sections)

        t0 = time.time()
        if "warehouses" in sections:
            await import_warehouses(db)
        if "brands" in sections:
            await import_brands(db)
        if "customers" in sections:
            await import_customers(db)
        if "products" in sections or "prices" in sections:
            await import_products_and_prices(db)
        if "inventory" in sections:
            await import_inventory(db)
        if "contracts" in sections:
            await import_contracts(db)

        elapsed = time.time() - t0
        log.info("=" * 70)
        log.info("Done in %.1f sec", elapsed)
        log.info("=" * 70)

    await engine.dispose()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--all", action="store_true", help="Run all sections in order")
    for s in SECTIONS:
        p.add_argument(f"--{s}", action="store_true", help=f"Run {s} importer")
    p.add_argument("--reset", action="store_true",
                   help="TRUNCATE selected sections' tables before importing (destructive)")
    args = p.parse_args()
    asyncio.run(main_async(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
