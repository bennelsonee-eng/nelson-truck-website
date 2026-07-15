"""Price sync — pulls P1-P5 from MySQL nte_parts_master via the read-only PHP
bridge and upserts ProductPrice rows for any matching Product in our DB.

Why this exists: the original import_initial_data filter drops nte_parts_master
rows whose prod_code doesn't map to a known brand. That filter was great for
the initial product import but kept ~98% of the catalog's parts master rows
from contributing pricing. This script is non-destructive — it only writes
to product_price, leaving products and brands untouched.

SKU translation (per investigation 2026-05-17):

  nte_parts_master.prod_code   (Titan internal: TECH, RCS, MAG, BUY, …)
       │
       ▼
  dci_codes.prod_code           one Titan code → one or more dci_codes
       │
       ▼
  dci_codes.aaia_code           the AAIA brand identifier (BHTJ, RCS, FBHB, …)
       │
       ▼
  brand.aaia_code               looks up brand_id
       │
  product.sku = '{aaia_code}-{nte_parts_master.parts_num}'
                  (e.g. "TECH" rows become "BHTJ-{parts_num}" SKUs)

So for each nte_parts_master row we look up the aaia_code(s) for its
prod_code (a prod_code can map to several brand variants — e.g. MAG → FBHB
covers Magnaflow CARB/49-state/Performance), then try each
'{aaia_code}-{parts_num}' against our products until we find a match.

Source row count: ~423,344 (per DESCRIBE on 2026-05-17). We page through in
50,000-row chunks (the bridge's hard cap per request).

Skips a row when ALL of P1..P5 are zero or null — those records carry no
price information.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Brand, Product, ProductPrice


log = logging.getLogger(__name__)


SOURCE_TABLE = "nte_parts_master"
PAGE_SIZE = 50_000  # bridge's MAX_ROWS cap


@dataclass
class PriceSyncResult:
    rows_fetched: int = 0
    matched_existing_product: int = 0
    skipped_all_zero: int = 0
    skipped_no_product: int = 0
    skipped_no_aaia_for_prod_code: int = 0
    upserted: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"nte_parts_master price sync: fetched={self.rows_fetched} "
            f"matched_product={self.matched_existing_product} "
            f"upserted={self.upserted} "
            f"skipped_no_product={self.skipped_no_product} "
            f"skipped_no_aaia_for_prod_code={self.skipped_no_aaia_for_prod_code} "
            f"skipped_all_zero={self.skipped_all_zero} "
            f"errors={len(self.errors)}"
        )


def _parse_money(v: Any) -> Decimal | None:
    """Parse a P-tier value into Decimal, treating '0' and '0.00' as None.

    nte_parts_master uses 0 as the sentinel for "no price set" since the
    column is NOT NULL with default '0.00'. A literal $0 price doesn't
    occur in the real catalog.
    """
    if v in (None, "", "0", "0.00"):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if d == Decimal("0"):
        return None
    return d


async def _fetch_page(client: httpx.AsyncClient, settings: Settings, offset: int) -> list[dict[str, Any]]:
    """One paginated SELECT against the bridge, ordered by ourparts_num for
    stable pagination."""
    sql = (
        "SELECT ourparts_num, parts_num, prod_code, P1, P2, P3, P4, P5 "
        f"FROM {SOURCE_TABLE} ORDER BY ourparts_num "
        f"LIMIT {PAGE_SIZE} OFFSET {offset}"
    )
    r = await client.get(
        settings.titan_bridge_url,
        params={
            "token": settings.titan_bridge_token,
            "query": sql,
            "format": "json",
            "limit": PAGE_SIZE,
        },
    )
    r.raise_for_status()
    return r.json().get("rows", [])


async def _fetch_dci_rows(
    client: httpx.AsyncClient, settings: Settings
) -> list[dict[str, Any]]:
    """Pull all dci_codes rows (small table — ~132 rows)."""
    r = await client.get(
        settings.titan_bridge_url,
        params={
            "token": settings.titan_bridge_token,
            "table": "dci_codes",
            "format": "json",
        },
    )
    r.raise_for_status()
    return r.json().get("rows", [])


def _normalize_brand_name(s: str) -> str:
    """Lowercase + strip; squash multiple whitespace to one space."""
    return " ".join((s or "").lower().split())


async def sync_prices_from_nte_parts_master(
    db: AsyncSession,
    settings: Settings,
    *,
    limit: int | None = None,
    chunk_upsert: int = 2000,
) -> PriceSyncResult:
    """Pull every priced row from nte_parts_master → upsert into product_price
    for matching products. Skips rows where the SKU isn't in our products
    table (a product import re-run is the right tool for that gap).
    """
    result = PriceSyncResult()

    if not (settings.titan_bridge_url and settings.titan_bridge_token):
        result.errors.append("titan_bridge_url / titan_bridge_token not set")
        return result

    # Load sku → product_id once. ~300k entries; trivial memory.
    log.info("Loading existing product SKU map…")
    sku_rows = (await db.execute(select(Product.id, Product.sku))).all()
    sku_to_pid: dict[str, int] = {sku: pid for (pid, sku) in sku_rows}
    log.info("  %d products in local DB", len(sku_to_pid))

    # Load brand_name → aaia_code from local brand table. Normalize so
    # "Rough Country" matches "rough country" matches " ROUGH  COUNTRY ".
    log.info("Loading local brand name → aaia_code map…")
    brand_rows = (await db.execute(select(Brand.name, Brand.aaia_code))).all()
    brandname_to_aaia: dict[str, list[str]] = {}
    for name, aaia in brand_rows:
        if not name or not aaia:
            continue
        key = _normalize_brand_name(name)
        bucket = brandname_to_aaia.setdefault(key, [])
        if aaia not in bucket:
            bucket.append(aaia)
    log.info("  %d brand-name → aaia mappings", len(brandname_to_aaia))

    pending: list[dict[str, Any]] = []
    seen_pids: set[int] = set()  # dedupe within this run; ProductPrice is 1:1 with Product
    offset = 0
    cap = limit if limit is not None else float("inf")

    async with httpx.AsyncClient(timeout=180, verify=True) as client:
        log.info("Loading dci_codes…")
        dci_rows = await _fetch_dci_rows(client, settings)
        log.info("  %d dci rows", len(dci_rows))

        # Build prod_code → candidate aaia_codes by combining BOTH paths:
        #   1. dci.aaia_code directly (works when both sides agree on aaia)
        #   2. dci.manu_title → local brand by name → local brand.aaia_code
        #      (works when dci's aaia and our brand's aaia disagree, e.g.
        #       Rough Country: dci=RCS / our brand=DHTP)
        # Either or both can hit; we try every candidate per row before
        # giving up.
        prod_code_to_aaia_candidates: dict[str, list[str]] = {}
        prod_codes_seen: set[str] = set()
        for row in dci_rows:
            pc = (row.get("prod_code") or "").strip()
            if not pc:
                continue
            prod_codes_seen.add(pc)
            bucket = prod_code_to_aaia_candidates.setdefault(pc, [])

            # Path 1: dci's own aaia
            dci_aaia = (row.get("aaia_code") or "").strip()
            if dci_aaia and dci_aaia not in bucket:
                bucket.append(dci_aaia)

            # Path 2: brand-name match → our aaia
            mt = (row.get("manu_title") or "").strip()
            for aaia in brandname_to_aaia.get(_normalize_brand_name(mt), []):
                if aaia not in bucket:
                    bucket.append(aaia)

        log.info("  %d prod_codes total; %d resolved to at least one aaia candidate",
                 len(prod_codes_seen), len(prod_code_to_aaia_candidates))

        while result.rows_fetched < cap:
            page = await _fetch_page(client, settings, offset)
            if not page:
                break
            result.rows_fetched += len(page)

            for row in page:
                parts_num = (row.get("parts_num") or "").strip()
                prod_code = (row.get("prod_code") or "").strip()
                if not parts_num or not prod_code:
                    continue

                p1 = _parse_money(row.get("P1"))
                p2 = _parse_money(row.get("P2"))
                p3 = _parse_money(row.get("P3"))
                p4 = _parse_money(row.get("P4"))
                p5 = _parse_money(row.get("P5"))
                if all(v is None for v in (p1, p2, p3, p4, p5)):
                    result.skipped_all_zero += 1
                    continue

                aaia_codes = prod_code_to_aaia_candidates.get(prod_code)
                if not aaia_codes:
                    result.skipped_no_aaia_for_prod_code += 1
                    continue

                # Try each candidate aaia_code; first match wins.
                pid: int | None = None
                for aaia in aaia_codes:
                    candidate_sku = f"{aaia}-{parts_num}"
                    pid = sku_to_pid.get(candidate_sku)
                    if pid is not None:
                        break

                if pid is None:
                    result.skipped_no_product += 1
                    continue

                if pid in seen_pids:
                    continue
                seen_pids.add(pid)
                result.matched_existing_product += 1

                pending.append({
                    "product_id": pid,
                    "suggested_retail_price": p1,
                    "retail_price": p2,
                    "jobber_price": p3,
                    "dealer_price": p4,
                    "cost": p5,
                })

                if len(pending) >= chunk_upsert:
                    await _upsert_chunk(db, pending, result)
                    pending = []

            offset += len(page)
            if len(page) < PAGE_SIZE:
                # last page
                break

    if pending:
        await _upsert_chunk(db, pending, result)

    # Keep the persisted resolved-retail (the catalog price-sort key) in step
    # with the prices we just changed, so "Price high→low" keeps matching the
    # displayed price. Best-effort: a failure here must never fail the price
    # sync. Scoped to the SKUs this run actually touched.
    try:
        from app.services.pricing_service import recompute_resolved_retail
        n = await recompute_resolved_retail(db, list(seen_pids))
        log.info("recomputed resolved_retail for %d products", n)
    except Exception:
        log.exception("resolved_retail recompute after price sync failed")

    log.info(result.summary())
    return result


async def _upsert_chunk(
    db: AsyncSession,
    rows: list[dict[str, Any]],
    result: PriceSyncResult,
) -> None:
    """Bulk upsert into product_price keyed on product_id. ProductPrice has a
    one-to-one with Product via product_id (enforced by the initial-schema
    unique index)."""
    if not rows:
        return
    stmt = pg_insert(ProductPrice).values(rows)
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
    try:
        await db.execute(stmt)
        await db.commit()
        result.upserted += len(rows)
        if result.upserted % 10_000 == 0:
            log.info("  …%d prices upserted", result.upserted)
    except Exception as e:
        await db.rollback()
        result.errors.append(f"upsert chunk failed: {e}")
        log.exception("upsert failed")
