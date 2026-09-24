"""Mirror the ERP's customer and supplier master data into the website database.

Fills `cus190_erp` and `sup190_erp` from the ERP Postgres (the data that lands
nightly as the CUS190 and SUP190 feeds). Both databases run on nelson-prod, so
this is a local hop — no CSV, no MySQL, no bridge.

Run from app/ with the backend venv:

    PYTHONPATH=/home/titan/nelson-truck-website/app/backend \
      backend/.venv/bin/python -m scripts.sync_erp_feeds [--dry-run]

Needs ERP_DATABASE_URL in app/.env (the ERP's own DSN). Read-only on the ERP
side: it only SELECTs. Each run replaces the mirror rows and stamps synced_at,
so re-running is safe and gaps disappear.

The website's own `customer` table is NOT touched here — it carries logins and
order history. Use these tables as the reference copy to fill it from.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import asyncpg

from app.config import get_settings
from app.database import async_session
from sqlalchemy import text

log = logging.getLogger(__name__)

CUSTOMER_COLUMNS = [
    "customer_number", "erp_id", "name", "contact", "address1", "address2", "city", "state", "zip",
    "phone", "fax", "email", "terms", "tax_code", "tax_exempt", "status", "price_type",
    "bill_to_customer", "po_required", "sales_rep", "territory", "location_code",
    "default_warehouse", "credit_limit", "start_date",
]
SUPPLIER_COLUMNS = [
    "supplier_code", "erp_id", "name", "contact", "address1", "address2", "city", "state", "zip",
    "phone", "fax", "email", "terms", "status", "prod_code", "alpha_code", "supplier_type",
    "supplier_class", "payment_type", "po_required", "ship_via", "min_order_amount",
    "min_prepaid_amount",
]
CUSTOMER_QUERY = """
    select customer_number, id as erp_id, name, contact, address1, address2, city, state, zip,
           phone, fax, email, terms, tax_code, tax_exempt, status, price_type,
           bill_to_customer, po_required, sales_rep, territory, location_code,
           default_warehouse, credit_limit, start_date
    from customers
    where coalesce(customer_number, '') <> ''
"""
SUPPLIER_QUERY = """
    select supplier_code, id as erp_id, name, contact, address1, address2, city, state, zip,
           phone, fax, email, terms, status, prod_code, alpha_code, supplier_type,
           supplier_class, payment_type, po_required, ship_via, min_order_amount,
           min_prepaid_amount
    from vendors
    where coalesce(supplier_code, '') <> ''
"""


def _erp_dsn(settings) -> str:
    dsn = getattr(settings, "erp_database_url", "") or ""
    if not dsn:
        raise SystemExit("ERP_DATABASE_URL is not set in app/.env — add the ERP's DSN and re-run")
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


async def _mirror(db, erp, *, table: str, key: str, columns: list[str], query: str, dry_run: bool) -> tuple[int, int]:
    rows = await erp.fetch(query)
    if dry_run:
        return len(rows), 0
    before = (await db.execute(text(f"select count(*) from {table}"))).scalar_one()
    await db.execute(text(f"truncate {table}"))
    placeholders = ", ".join(f":{c}" for c in columns)
    stmt = text(f"insert into {table} ({', '.join(columns)}) values ({placeholders})")
    batch: list[dict] = []
    for r in rows:
        batch.append({c: r[c] for c in columns})
        if len(batch) >= 1000:
            await db.execute(stmt, batch)
            batch = []
    if batch:
        await db.execute(stmt, batch)
    return len(rows), before


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="count what the ERP has, write nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = get_settings()
    erp = await asyncpg.connect(_erp_dsn(settings))
    try:
        async with async_session() as db:
            cus, cus_before = await _mirror(db, erp, table="cus190_erp", key="customer_number",
                                            columns=CUSTOMER_COLUMNS, query=CUSTOMER_QUERY, dry_run=args.dry_run)
            sup, sup_before = await _mirror(db, erp, table="sup190_erp", key="supplier_code",
                                            columns=SUPPLIER_COLUMNS, query=SUPPLIER_QUERY, dry_run=args.dry_run)
            if not args.dry_run:
                await db.commit()
        tail = " (dry run — nothing written)" if args.dry_run else ""
        print(f"cus190_erp: {cus} customers (was {cus_before}){tail}")
        print(f"sup190_erp: {sup} suppliers (was {sup_before}){tail}")
    finally:
        await erp.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
