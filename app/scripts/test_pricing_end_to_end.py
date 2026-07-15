"""End-to-end pricing test: pick real (customer, product, qty), resolve via engine.

Picks a few sample customer/product combinations from the imported data and runs
the pricing engine against them. Prints input + resolution for each.

Run from app/backend/ with venv:
    python -m scripts.test_pricing_end_to_end
"""

from __future__ import annotations

import asyncio
import logging
import sys
from decimal import Decimal
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import select, text  # noqa: E402

from app.database import async_session, engine  # noqa: E402
engine.echo = False
engine.sync_engine.echo = False

from app.models import Brand, Contract, Customer, Product, ProductPrice  # noqa: E402
from app.services.pricing_engine import (  # noqa: E402
    AgingDiscountConfig,
    AgingDiscountTier,
    ContractRule,
    ResolutionStatus,
    resolve_price,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


async def get_tier_prices(db, product_id: int) -> dict[int, Decimal | None]:
    """Build the P1-P5 tier prices for a product from ProductPrice."""
    result = await db.execute(select(ProductPrice).where(ProductPrice.product_id == product_id))
    pp = result.scalar_one_or_none()
    if pp is None:
        return {}
    return {
        1: pp.suggested_retail_price,
        2: pp.retail_price,
        3: pp.jobber_price,
        4: pp.dealer_price,
        5: pp.cost,
    }


async def get_matching_contracts(
    db, customer_id: int, brand: str | None, group_code: str | None, part_number: str
) -> list[ContractRule]:
    """Pull contract rows matching this customer + product scope.

    The engine does its own final filter, but we pre-narrow the query
    for performance (605K total rows).
    """
    # Match customer + (brand-wildcard OR brand match) + (part-wildcard OR part match)
    stmt = select(Contract).where(Contract.customer_id == customer_id)
    if brand is not None:
        stmt = stmt.where((Contract.brand.is_(None)) | (Contract.brand == brand))
    stmt = stmt.where((Contract.part_number.is_(None)) | (Contract.part_number == part_number))
    result = await db.execute(stmt)
    db_rules = result.scalars().all()
    return [
        ContractRule(
            contract_id=r.id,
            contract_name=r.name,
            customer_id=str(customer_id),
            brand=r.brand,
            group_code=r.group_code,
            part_number=r.part_number,
            priority=r.priority,
            min_quantity=r.min_quantity,
            pricing_formula=r.pricing_formula,
            expiration_date=r.expiration_date,
        )
        for r in db_rules
    ]


async def find_test_cases(db, n: int = 5) -> list[dict]:
    """Find a few real customer × product pairs that have an actual contract match.

    Joins contract → product on brand=prod_code so we get cases where the
    pricing engine can actually fire a contract resolution (not just MAP-clamp).
    """
    sql = """
    SELECT DISTINCT ON (c.customer_id, p.prod_code)
           c.customer_id, c.brand AS contract_brand, c.priority, c.pricing_formula,
           cust.customer_number, cust.name AS customer_name,
           p.id AS product_id, p.sku, p.name AS product_name, p.prod_code,
           b.name AS brand_name,
           pp.suggested_retail_price AS p1, pp.retail_price AS p2,
           pp.jobber_price AS p3, pp.dealer_price AS p4, pp.cost AS p5
    FROM contract c
    JOIN customer cust ON cust.id = c.customer_id
    JOIN product p ON p.prod_code = c.brand
    JOIN brand b ON b.id = p.brand_id
    JOIN product_price pp ON pp.product_id = p.id
    WHERE pp.cost IS NOT NULL AND pp.cost > 0
      AND pp.jobber_price IS NOT NULL AND pp.jobber_price > 0
      AND c.brand IN ('YAK', 'WES', 'CURT', 'WARN', 'TECH', 'GOR', 'BUSH', 'HUS')
      AND c.priority < 10
    ORDER BY c.customer_id, p.prod_code, c.priority ASC
    LIMIT :n
    """
    result = await db.execute(text(sql), {"n": n})
    rows = result.mappings().all()
    return [dict(r) for r in rows]


async def main_async():
    async with async_session() as db:
        # First, summarize what's in the DB
        log.info("=" * 70)
        log.info("DB SUMMARY")
        log.info("=" * 70)
        for table, model in [
            ("brand", Brand),
            ("customer", Customer),
            ("product", Product),
            ("product_price", ProductPrice),
            ("contract", Contract),
        ]:
            r = await db.execute(text(f"SELECT count(*) FROM {table}"))
            log.info(f"  {table:20} {r.scalar():>10,}")
        log.info("")

        # Find some test cases
        log.info("=" * 70)
        log.info("FINDING TEST CASES")
        log.info("=" * 70)
        cases = await find_test_cases(db, n=5)
        log.info(f"Found {len(cases)} candidate (customer, product) combos")
        log.info("")

        if not cases:
            log.warning("No test cases found — need products with non-zero cost (P5) and matching contracts")
            return

        # Run the pricing engine on each
        log.info("=" * 70)
        log.info("END-TO-END PRICING RESOLUTIONS")
        log.info("=" * 70)

        # Sample aging-discount config for testing (FS-080)
        aging_cfg = AgingDiscountConfig(enabled=False)  # disabled by default

        for i, case in enumerate(cases, 1):
            log.info(f"\n--- Test case {i} ---")
            log.info(f"  Customer #{case['customer_number']} (id={case['customer_id']})")
            log.info(f"  Product:  {case['sku']}  — {case['product_name'][:60]}")
            log.info(f"  Brand:    {case['brand_name']}  (prod_code={case['prod_code']})")
            log.info(f"  Tier prices: P1={case['p1']} P2={case['p2']} P3={case['p3']} P4={case['p4']} P5={case['p5']}")

            tiers = {1: case["p1"], 2: case["p2"], 3: case["p3"], 4: case["p4"], 5: case["p5"]}

            rules = await get_matching_contracts(
                db,
                customer_id=case["customer_id"],
                brand=case["prod_code"],
                group_code=None,
                part_number=case["sku"],
            )
            log.info(f"  Contract rules pre-loaded: {len(rules)}")

            # Run resolution
            result = resolve_price(
                customer_id=str(case["customer_id"]),
                product_part_number=case["sku"],
                product_brand_code=case["prod_code"],
                product_group_code=None,
                qty=1,
                tier_prices=tiers,
                matching_rules=rules,
                tier_default_price=tiers.get(3),  # P3 (Jobber) as default tier price
                map_price=tiers.get(1),  # P1 as MAP floor
                aging_config=aging_cfg,
            )

            log.info(f"  → STATUS: {result.status.value}")
            log.info(f"  → PRICE:  ${result.price}")
            if result.contract_used:
                log.info(f"  → Contract used: id={result.contract_used.contract_id} priority={result.contract_used.priority} formula={result.contract_used.pricing_formula!r}")
            if result.notes:
                for note in result.notes:
                    log.info(f"     note: {note}")

        log.info("")
        log.info("=" * 70)
        log.info("DONE")
        log.info("=" * 70)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main_async())
