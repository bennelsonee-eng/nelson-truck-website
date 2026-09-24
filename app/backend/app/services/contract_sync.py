"""Contract-pricing sync — legacy MySQL `contracts_copy` → the `contract` table.

Nelson's contract pricing lives in the legacy MySQL (schema `nelsontruck1`) in
`contracts_copy`, where `company = 'nelson'` marks our rows (Titan's are in the
same table). Ben reloads that table from the contracts file; this pulls the
result over the same read-only PHP bridge the price sync uses.

The July 2026 load was a one-off from a hand-exported CSV
(`scripts/import_initial_data.py --contracts`) with no way to refresh. This
replaces that: every run rebuilds the synced rows, so re-running is safe.

What it does NOT touch: contract rows added in the app (partner programs such
as Sourcewell), which carry a different `description`. Only rows this sync owns
— or the shape the July import left behind — are replaced.

Mapping (unchanged from the July import, so prices don't move):
    cust_id       → customer_id (matched on customer.customer_number)
    contract      → name, as "contract-<value>"
    prod_code     → brand
    group_code    → group_code ("0" means "any")
    ourparts_num  → part_number
    discount      → pricing_formula (rows without one are skipped)
    exp_date      → expiration_date
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Contract, Customer

log = logging.getLogger(__name__)

SOURCE_TABLE = "contracts_copy"
COMPANY = "nelson"
# Stamped on every row this sync owns, so a refresh only replaces its own work.
SOURCE_TAG = "source:contracts_copy"
PAGE = 20_000
COLUMNS = "cust_id, contract, ourparts_num, prod_code, group_code, priority, min_quantity, exp_date, discount"


@dataclass
class ContractSyncResult:
    rows_read: int = 0
    parsed: int = 0
    skipped_no_formula: int = 0
    skipped_no_customer: int = 0
    unknown_customers: set[str] = field(default_factory=set)
    deleted: int = 0
    inserted: int = 0
    dry_run: bool = False

    def summary(self) -> str:
        return (
            f"contracts_copy sync{' (dry run)' if self.dry_run else ''}: "
            f"read={self.rows_read} usable={self.parsed} inserted={self.inserted} "
            f"replaced={self.deleted} | skipped: no_formula={self.skipped_no_formula} "
            f"customer_not_on_site={self.skipped_no_customer}"
        )


def _int(v: object, default: int) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _date(v: object) -> date | None:
    s = (str(v) if v is not None else "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


async def _fetch_page(settings: Settings, offset: int) -> list[dict]:
    """One page of Nelson rows from the bridge (SELECT-only, read-only)."""
    query = (
        f"SELECT {COLUMNS} FROM {SOURCE_TABLE} "
        f"WHERE company = '{COMPANY}' ORDER BY cust_id, contract, ourparts_num "
        f"LIMIT {PAGE} OFFSET {offset}"
    )
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.get(settings.titan_bridge_url,
                             params={"token": settings.titan_bridge_token, "query": query, "format": "json"})
        r.raise_for_status()
        return r.json().get("rows", [])


async def sync_contracts(db: AsyncSession, settings: Settings, *, dry_run: bool = False,
                         max_rows: int | None = None) -> ContractSyncResult:
    result = ContractSyncResult(dry_run=dry_run)
    if not (settings.titan_bridge_url and settings.titan_bridge_token):
        raise RuntimeError("titan_bridge_url / titan_bridge_token not set")

    by_number = {n: i for i, n in (await db.execute(select(Customer.id, Customer.customer_number))).all()}
    log.info("%d customers on the site to match against", len(by_number))

    rows: list[dict] = []
    offset = 0
    while True:
        page = await _fetch_page(settings, offset)
        if not page:
            break
        result.rows_read += len(page)
        for r in page:
            formula = (str(r.get("discount") or "")).strip()
            if not formula:
                result.skipped_no_formula += 1
                continue
            number = (str(r.get("cust_id") or "")).strip()
            customer_id = by_number.get(number)
            if customer_id is None:
                result.skipped_no_customer += 1
                if len(result.unknown_customers) < 50:
                    result.unknown_customers.add(number)
                continue
            group_code = (str(r.get("group_code") or "")).strip() or None
            rows.append({
                "name": f"contract-{(str(r.get('contract') or '')).strip() or 'default'}",
                "description": SOURCE_TAG,
                "customer_id": customer_id,
                "brand": (str(r.get("prod_code") or "")).strip() or None,
                "group_code": None if group_code == "0" else group_code,
                "part_number": (str(r.get("ourparts_num") or "")).strip() or None,
                "priority": _int(r.get("priority"), 100),
                "min_quantity": _int(r.get("min_quantity"), 0),
                "pricing_formula": formula,
                "expiration_date": _date(r.get("exp_date")),
                "is_active": True,
            })
        offset += PAGE
        if len(page) < PAGE or (max_rows and result.rows_read >= max_rows):
            break
    result.parsed = len(rows)

    if dry_run or not rows:
        log.info(result.summary())
        return result

    # Replace in one transaction: the rows this sync owns, plus the shape the
    # July one-off import left behind (name "contract-…" with no description).
    # One transaction: back up what we own, delete it, insert the fresh set.
    # (The session may already have a transaction open, so no db.begin() here.)
    await db.execute(text(
        "create table if not exists _bak_contract_sync as select * from contract where false"))
    await db.execute(text("truncate _bak_contract_sync"))
    await db.execute(text(
        "insert into _bak_contract_sync select * from contract "
        "where description = :tag or (description is null and name like 'contract-%')"
    ).bindparams(tag=SOURCE_TAG))
    deleted = await db.execute(
        delete(Contract).where(
            (Contract.description == SOURCE_TAG)
            | (Contract.description.is_(None) & Contract.name.like("contract-%"))
        )
    )
    result.deleted = deleted.rowcount or 0
    for i in range(0, len(rows), 2000):
        await db.execute(pg_insert(Contract).values(rows[i:i + 2000]))
        result.inserted += len(rows[i:i + 2000])
    await db.commit()
    log.info(result.summary())
    return result
