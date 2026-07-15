"""PIES price sync — extracts USD pricing from AAM PIES zip feeds and fills
in product_price rows / tier columns the nte_parts_master sync didn't cover.

Source: `AAM_<aaia>_PIES_<timestamp>.zip` files (one zip per brand). Each zip
contains a single PIES 7.2 XML file with `<Item>` blocks; each Item has an
optional `<Prices>` section with `<Pricing PriceType="…">` entries.

PIES price-type mapping (per Auto Care PIES 7.2, plus brand-specific variants
observed in real feeds like WeatherTech's BHTJ data):

  RMP, LST          — Retail Maintenance Price / List (MSRP / Suggested Retail)
  RET               — Retail (walk-in counter price)
  JBR               — Jobber price
  WD, WD1, WD2, …   — Warehouse Distributor (AAM cost paid by Titan).
                      The "WD1" / "WD2" / "WDA" suffix is the volume tier
                      (1 = lowest, biggest discount). We pick the cheapest.
  MAP               — Minimum Advertised Price (fallback for MSRP slot)
  USR               — User-specific (per-customer; we don't have a hook)

We map:
  RMP / LST            → suggested_retail_price  (also acts as MAP floor in
                                                  our pricing engine)
  MAP (no RMP/LST)     → suggested_retail_price  (fallback)
  RET                  → retail_price
  JBR                  → jobber_price
  cheapest WD/WD[0-9]+ → dealer_price AND cost   (the AAM cost — what Titan
                                                  pays for the part)

Two modes:
  * Insert mode (default) — only inserts a fresh ProductPrice row for
    products that currently have no row. nte_parts_master stays authoritative
    for products it covers.
  * Refill mode (`fill_null_tiers=True`) — when a row already exists, UPDATE
    only the columns that are currently NULL. Used to backfill cost/dealer
    on previously-PIES-inserted rows that missed WD1 because the original
    sync only matched bare "WD".

Streaming: PIES XML can be 450 MB+ unzipped. xml.etree.ElementTree.iterparse
walks one Item at a time and clears the tree as it goes, so memory stays
flat regardless of file size.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator
from xml.etree.ElementTree import iterparse

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ProductPrice


# Matches WD, WD1, WD2, ..., WDA, WDB, ... — all "warehouse distributor"
# pricing tiers. Lower numeric suffix = larger volume / cheaper price.
_WD_RE = re.compile(r"^WD[0-9A-Z]?$")


log = logging.getLogger(__name__)


PIES_NS = "http://www.autocare.org"


@dataclass
class PiesPriceSyncResult:
    files_processed: int = 0
    files_skipped_no_items: int = 0
    items_seen: int = 0
    items_with_usd_prices: int = 0
    items_matched_existing_product: int = 0
    items_with_existing_price_row_skipped: int = 0
    items_no_matching_product: int = 0
    inserted: int = 0
    tier_columns_filled: int = 0  # in fill_null_tiers mode
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"PIES price sync: files={self.files_processed} "
            f"items={self.items_seen} usd_priced={self.items_with_usd_prices} "
            f"matched={self.items_matched_existing_product} "
            f"inserted={self.inserted} "
            f"tier_cols_filled={self.tier_columns_filled} "
            f"skipped_already_priced={self.items_with_existing_price_row_skipped} "
            f"no_product={self.items_no_matching_product} "
            f"errors={len(self.errors)}"
        )


def _parse_decimal(s: str | None) -> Decimal | None:
    if not s:
        return None
    try:
        d = Decimal(str(s).strip())
    except (InvalidOperation, ValueError):
        return None
    if d <= 0:
        return None
    return d


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        # YYYY-MM-DD per PIES schema
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _qname(name: str) -> str:
    return f"{{{PIES_NS}}}{name}"


def _stream_items(xml_stream: io.IOBase) -> Iterator[tuple[str, str, dict[str, Decimal]]]:
    """Yield (brand_aaia, part_number, price_map) for each Item with at least
    one USD price. Streaming so we don't load the whole 450MB file."""
    item_tag = _qname("Item")
    part_tag = _qname("PartNumber")
    brand_tag = _qname("BrandAAIAID")
    prices_tag = _qname("Prices")
    pricing_tag = _qname("Pricing")
    currency_tag = _qname("CurrencyCode")
    price_tag = _qname("Price")
    effdate_tag = _qname("EffectiveDate")

    context = iterparse(xml_stream, events=("end",))
    for _event, elem in context:
        if elem.tag != item_tag:
            continue

        part_num: str | None = None
        brand: str | None = None
        # price_type → (effective_date, decimal) — keep most recent USD entry
        best: dict[str, tuple[date | None, Decimal]] = {}

        for child in elem:
            if child.tag == part_tag and child.text:
                part_num = child.text.strip()
            elif child.tag == brand_tag and child.text:
                brand = child.text.strip()
            elif child.tag == prices_tag:
                for pricing in child.findall(pricing_tag):
                    price_type = (pricing.get("PriceType") or "").strip()
                    if not price_type:
                        continue
                    # Filter to USD only
                    currency_elem = pricing.find(currency_tag)
                    currency = (currency_elem.text or "").strip() if currency_elem is not None else ""
                    if currency != "USD":
                        continue
                    price_elem = pricing.find(price_tag)
                    if price_elem is None:
                        continue
                    val = _parse_decimal(price_elem.text)
                    if val is None:
                        continue
                    eff_elem = pricing.find(effdate_tag)
                    eff = _parse_date(eff_elem.text if eff_elem is not None else None)
                    prev = best.get(price_type)
                    if prev is None or (eff is not None and (prev[0] is None or eff > prev[0])):
                        best[price_type] = (eff, val)

        # Convert PIES price types → our tier columns
        price_map: dict[str, Decimal] = {}
        if brand and part_num:
            # MSRP / Suggested Retail
            rmp = best.get("RMP") or best.get("LST")
            if rmp:
                price_map["suggested_retail_price"] = rmp[1]
            elif "MAP" in best:
                price_map["suggested_retail_price"] = best["MAP"][1]

            # Walk-in retail
            if "RET" in best:
                price_map["retail_price"] = best["RET"][1]

            # Jobber
            if "JBR" in best:
                price_map["jobber_price"] = best["JBR"][1]

            # Warehouse distributor (AAM cost) — pick the LOWEST observed
            # WD/WD[0-9A-Z] tier; that's the cheapest tier Titan qualifies for
            # and matches the P5 "cost" semantics in nte_parts_master.
            wd_values = [v for k, (_, v) in best.items() if _WD_RE.match(k)]
            if wd_values:
                wd_cost = min(wd_values)
                price_map["dealer_price"] = wd_cost
                price_map["cost"] = wd_cost

        elem.clear()
        if brand and part_num and price_map:
            yield brand, part_num, price_map


async def sync_prices_from_pies_zip(
    db: AsyncSession,
    zip_path: Path,
    sku_to_pid: dict[str, int],
    pids_with_existing_price: set[int],
    result: PiesPriceSyncResult,
    chunk_upsert: int = 2000,
    fill_null_tiers: bool = False,
) -> None:
    """Process a single PIES zip. Mutates `result` in place + `pids_with_existing_price`
    as new rows are inserted.

    When `fill_null_tiers=True`, for products that ALREADY have a price row
    we UPDATE only the tier columns that are currently NULL — useful for
    backfilling cost/dealer on the 26k PIES rows the original sync wrote
    before WD1/RET handling was added.
    """
    log.info("Processing %s …", zip_path.name)
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as e:
        result.errors.append(f"{zip_path.name}: bad zip ({e})")
        return

    pending_insert: list[dict[str, Any]] = []

    try:
        xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not xml_names:
            result.files_skipped_no_items += 1
            return

        with zf.open(xml_names[0]) as xml_stream:
            for brand, part_num, price_map in _stream_items(xml_stream):
                result.items_seen += 1
                result.items_with_usd_prices += 1
                sku = f"{brand}-{part_num}"
                pid = sku_to_pid.get(sku)
                if pid is None:
                    result.items_no_matching_product += 1
                    continue
                result.items_matched_existing_product += 1

                if pid in pids_with_existing_price:
                    if fill_null_tiers:
                        cols_filled = await _refill_null_tiers(db, pid, price_map)
                        result.tier_columns_filled += cols_filled
                    else:
                        result.items_with_existing_price_row_skipped += 1
                    continue

                pending_insert.append({"product_id": pid, **price_map})
                pids_with_existing_price.add(pid)

                if len(pending_insert) >= chunk_upsert:
                    await _upsert_chunk(db, pending_insert, result)
                    pending_insert = []
    finally:
        zf.close()

    if pending_insert:
        await _upsert_chunk(db, pending_insert, result)

    result.files_processed += 1


async def _refill_null_tiers(
    db: AsyncSession,
    product_id: int,
    incoming: dict[str, Any],
) -> int:
    """For an existing ProductPrice row, set any NULL tier column to the
    matching incoming value. Returns count of columns actually updated.
    Commits the change.
    """
    if not incoming:
        return 0
    # Build a SET … WHERE col IS NULL clause per column. SQLAlchemy core update().
    # We do one statement per row but ensure we only touch NULL columns —
    # combining all incoming values into a single UPDATE with COALESCE could
    # accidentally overwrite a non-NULL value if a column wasn't in the
    # incoming map (defaulting to NULL). Per-column WHERE is cleanest.
    cols_filled = 0
    for col, val in incoming.items():
        # Map snake-case dict key to the actual ProductPrice column attribute
        col_attr = getattr(ProductPrice, col, None)
        if col_attr is None:
            continue
        stmt = (
            update(ProductPrice)
            .where(ProductPrice.product_id == product_id)
            .where(col_attr.is_(None))
            .values({col: val})
        )
        r = await db.execute(stmt)
        if r.rowcount:
            cols_filled += r.rowcount
    if cols_filled:
        await db.commit()
    return cols_filled


async def _upsert_chunk(
    db: AsyncSession,
    rows: list[dict[str, Any]],
    result: PiesPriceSyncResult,
) -> None:
    if not rows:
        return
    # ON CONFLICT DO NOTHING — keep nte_parts_master prices when both exist.
    # (We pre-filtered against pids_with_existing_price too; this is belt+suspenders.)
    stmt = pg_insert(ProductPrice).values(rows).on_conflict_do_nothing(
        index_elements=["product_id"]
    )
    try:
        r = await db.execute(stmt)
        await db.commit()
        # rowcount on async pg_insert with ON CONFLICT may not be exact; use len(rows)
        result.inserted += len(rows)
        if result.inserted % 5000 == 0:
            log.info("  …%d PIES prices inserted", result.inserted)
    except Exception as e:
        await db.rollback()
        result.errors.append(f"upsert chunk failed: {e}")
        log.exception("upsert failed")


async def sync_prices_from_pies_dir(
    db: AsyncSession,
    pies_dir: Path,
    *,
    limit_files: int | None = None,
    file_pattern: str = "AAM_*_PIES_*.zip",
    fill_null_tiers: bool = False,
) -> PiesPriceSyncResult:
    """Walk a directory of PIES zips and sync each. Loads the product-sku
    map and the "already-priced" set once at start.

    Pass `fill_null_tiers=True` to backfill NULL tier columns on rows that
    already exist (use this after fixing the extraction logic to pick up
    additional PIES price types).
    """
    result = PiesPriceSyncResult()

    log.info("Loading product SKU map…")
    sku_rows = (await db.execute(select(Product.id, Product.sku))).all()
    sku_to_pid = {sku: pid for (pid, sku) in sku_rows}
    log.info("  %d products", len(sku_to_pid))

    log.info("Loading existing-price set…")
    priced_rows = (await db.execute(select(ProductPrice.product_id))).all()
    pids_with_existing_price: set[int] = {r[0] for r in priced_rows}
    log.info("  %d products already have a price row%s",
             len(pids_with_existing_price),
             " (will refill NULL tiers)" if fill_null_tiers else " (will skip)")

    zips = sorted(pies_dir.glob(file_pattern))
    if limit_files is not None:
        zips = zips[:limit_files]
    log.info("Found %d PIES zips to process", len(zips))

    for zp in zips:
        try:
            await sync_prices_from_pies_zip(
                db, zp, sku_to_pid, pids_with_existing_price, result,
                fill_null_tiers=fill_null_tiers,
            )
        except Exception as e:
            result.errors.append(f"{zp.name}: {e}")
            log.exception("Failed processing %s", zp.name)

    log.info(result.summary())
    return result
