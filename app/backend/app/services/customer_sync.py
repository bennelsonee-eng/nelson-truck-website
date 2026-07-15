"""Customer sync — pulls nte_cus190 from the legacy MySQL bridge into local Postgres.

Source: the read-only PHP bridge at `settings.titan_bridge_url` (lives on the
TigerTech web root — see `app/scripts/dump_titan_tables.php` for the source).
Authenticated via `settings.titan_bridge_token`. Returns JSON (or CSV) for any
table or arbitrary SELECT. No direct MySQL credentials needed on this side.
(Field names keep the `titan_` prefix — inherited from the Titan clone — but
this Nelson site reads the `nte_` tables.)

Target: Postgres `customer` + `customer_address` tables on the Nelson-website DB.

Why this exists: the admin Shop-as-Customer dropdown (SOW A4.28) needs a
populated `customer` table. Run this sync once after deploy to bring all
Nelson customers in.

Run modes:
  * Programmatic: `await sync_customers_from_tte_cus190(db, settings)`
  * CLI: `python -m scripts.sync_customers --dry-run --limit 50`

Column mapping below matches the real FACS tte_cus190 schema (confirmed
via the bridge's DESCRIBE 2026-05-17).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    AddressType,
    Customer,
    CustomerAddress,
    CustomerTier,
)


log = logging.getLogger(__name__)


# Real column names in the legacy cus190 table (per DESCRIBE 2026-05-17). The
# bridge returns a header row whose `cus_num` value is literally "Customer #" —
# we skip that. Otherwise everything else is a real customer.
# Nelson pulls nte_cus190 (Titan pulls tte_cus190). Verify the bridge exposes
# nte_cus190 — see open item in NELSON_WEBSITE_SEPARATION_PLAN.md §8.
SOURCE_TABLE = "nte_cus190"

COL_CUS_NUM = "cus_num"
COL_NAME = "name"
COL_BILL_ADDR1 = "addr1"
COL_BILL_ADDR2 = "addr2"
COL_BILL_CITY = "city"
COL_BILL_STATE = "state"
COL_BILL_ZIP = "zip"
COL_SHIP_NAME = "ship_to_name"
COL_SHIP_ADDR1 = "ship_to_address_1"
COL_SHIP_ADDR2 = "ship_to_address_2"
COL_SHIP_CITY = "ship_to_city"
COL_SHIP_STATE = "ship_to_state"
COL_SHIP_ZIP = "ship_to_zip_code"
COL_PHONE = "phone_number"
COL_FAX = "fax_number"
COL_CONTACT_NAME = "contact_name"
COL_CONTACT_EMAIL = "contact_email"
COL_CONTACT_PHONE = "contact_phone"
COL_TERMS = "terms"
COL_CREDIT_LIMIT = "credit_limit"
COL_TAX_EXEMPT = "tax_exempt"
COL_TAX_EXEMPT_STATE = "tax_exempt_state"
COL_TAX_EXEMPT_NUMBER = "tax_exempt_number"
COL_SALES_REP = "sales_rep_number"
COL_CUST_STATUS = "cust_status"          # "A" = active
COL_BILL_TO_CUSTOMER = "bill_to_customer"  # cus_num of parent; equal to cus_num for top-level
COL_DEALER = "dealer"                    # "Y" / "N"


# --- Result -----------------------------------------------------------------


@dataclass
class SyncResult:
    rows_read: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    parents_linked: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> str:
        return (
            f"nte_cus190 sync: read={self.rows_read} inserted={self.inserted} "
            f"updated={self.updated} skipped={self.skipped} "
            f"parents_linked={self.parents_linked} errors={len(self.errors)} "
            f"dry_run={self.dry_run}"
        )


# --- Helpers ----------------------------------------------------------------


def _get(row: dict[str, Any], col: str) -> str | None:
    v = row.get(col)
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return str(v) if v != "" else None


def _bool_yn(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().upper().startswith("Y")
    return bool(v)


def _parse_decimal(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _is_header_row(row: dict[str, Any]) -> bool:
    """The first row that FACS exports is a label row, not a customer."""
    val = (row.get(COL_CUS_NUM) or "").strip()
    return val == "" or val.lower() == "customer #"


def _build_address(
    addr_type: AddressType,
    name: str | None,
    company: str,
    addr1: str | None,
    addr2: str | None,
    city: str | None,
    state: str | None,
    zip_: str | None,
) -> CustomerAddress | None:
    if not (addr1 and city and state and zip_):
        return None
    return CustomerAddress(
        address_type=addr_type,
        is_primary=True,
        name=name,
        company=company,
        addr1=addr1,
        addr2=addr2,
        city=city,
        state=(state or "")[:2].upper(),
        zip=zip_,
        country="US",
    )


async def _fetch_rows(settings: Settings, limit: int | None = None) -> list[dict[str, Any]]:
    """Hit the PHP bridge and return the parsed row list."""
    params: dict[str, Any] = {
        "token": settings.titan_bridge_token,
        "table": SOURCE_TABLE,
        "format": "json",
    }
    if limit:
        params["limit"] = int(limit)
    url = settings.titan_bridge_url
    async with httpx.AsyncClient(timeout=120, verify=True) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        body = r.json()
    return body.get("rows", [])


# --- Main sync function -----------------------------------------------------


async def sync_customers_from_tte_cus190(
    db: AsyncSession,
    settings: Settings,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    default_tier: CustomerTier = CustomerTier.JOBBER,
) -> SyncResult:
    """Pull every row from tte_cus190 via the PHP bridge → upsert into the
    local customer + customer_address tables. After all rows land, a second
    pass populates `parent_customer_id` from `bill_to_customer`.
    """
    result = SyncResult(dry_run=dry_run)

    if not (settings.titan_bridge_url and settings.titan_bridge_token):
        msg = "titan_bridge_url / titan_bridge_token not set"
        result.errors.append(msg)
        log.warning(msg)
        return result

    try:
        rows = await _fetch_rows(settings, limit=limit)
    except Exception as e:
        msg = f"Bridge fetch failed: {e}"
        result.errors.append(msg)
        log.exception(msg)
        return result

    # Map cus_num → bill_to_customer for the parent-linking second pass.
    parent_map: dict[str, str] = {}

    for row in rows:
        result.rows_read += 1
        if _is_header_row(row):
            result.skipped += 1
            continue
        try:
            cus_num = await _upsert_one(db, row, default_tier, dry_run, result)
            if cus_num:
                bill_to = _get(row, COL_BILL_TO_CUSTOMER)
                if bill_to and bill_to != cus_num:
                    parent_map[cus_num] = bill_to
        except Exception as e:
            result.errors.append(f"row {row.get(COL_CUS_NUM, '?')}: {e}")
            log.exception("Sync row failed")

    # Second pass: link parent_customer_id where bill_to_customer differs.
    if not dry_run and parent_map:
        all_nums = list({n for n in parent_map.keys()} | {p for p in parent_map.values()})
        existing = (
            await db.execute(
                select(Customer.id, Customer.customer_number).where(
                    Customer.customer_number.in_(all_nums)
                )
            )
        ).all()
        id_by_num = {num: cid for cid, num in existing}
        for child_num, parent_num in parent_map.items():
            child_id = id_by_num.get(child_num)
            parent_id = id_by_num.get(parent_num)
            if child_id is None or parent_id is None:
                continue
            child = (
                await db.execute(select(Customer).where(Customer.id == child_id))
            ).scalar_one_or_none()
            if child is not None and child.parent_customer_id != parent_id:
                child.parent_customer_id = parent_id
                result.parents_linked += 1

    if not dry_run:
        await db.commit()
    else:
        await db.rollback()

    log.info(result.summary())
    return result


async def _upsert_one(
    db: AsyncSession,
    row: dict[str, Any],
    default_tier: CustomerTier,
    dry_run: bool,
    result: SyncResult,
) -> str | None:
    cus_num = _get(row, COL_CUS_NUM)
    if not cus_num:
        result.skipped += 1
        return None

    name = _get(row, COL_NAME) or f"Customer {cus_num}"
    is_active = (_get(row, COL_CUST_STATUS) or "").upper() == "A"
    is_dealer = _bool_yn(_get(row, COL_DEALER))

    # Tier heuristic: dealer=Y → DEALER, else default (JOBBER). The customer_class
    # column carries other distinctions (COD, etc.) that we can refine later.
    tier = CustomerTier.DEALER if is_dealer else default_tier

    existing = (
        await db.execute(
            select(Customer).where(Customer.customer_number == cus_num)
        )
    ).scalar_one_or_none()

    if existing is None:
        cust = Customer(
            customer_number=cus_num,
            tier=tier,
            name=name,
            contact_name=_get(row, COL_CONTACT_NAME),
            email=_get(row, COL_CONTACT_EMAIL),
            phone=_get(row, COL_PHONE) or _get(row, COL_CONTACT_PHONE),
            fax=_get(row, COL_FAX),
            sales_rep_code=_get(row, COL_SALES_REP),
            is_tax_exempt=_bool_yn(_get(row, COL_TAX_EXEMPT)),
            tax_exempt_cert_number=_get(row, COL_TAX_EXEMPT_NUMBER),
            tax_exempt_state=_get(row, COL_TAX_EXEMPT_STATE),
            payment_terms=_get(row, COL_TERMS),
            is_active=is_active,
        )
        credit = _parse_decimal(_get(row, COL_CREDIT_LIMIT))
        if credit is not None:
            try:
                cust.credit_limit_usd = int(credit)
            except (TypeError, ValueError):
                pass
        if dry_run:
            result.inserted += 1
            return cus_num
        db.add(cust)
        await db.flush()
        result.inserted += 1
    else:
        cust = existing
        # Preserve admin-set tier; update everything else.
        cust.name = name
        cust.contact_name = _get(row, COL_CONTACT_NAME) or cust.contact_name
        cust.email = _get(row, COL_CONTACT_EMAIL) or cust.email
        cust.phone = _get(row, COL_PHONE) or _get(row, COL_CONTACT_PHONE) or cust.phone
        cust.fax = _get(row, COL_FAX) or cust.fax
        cust.sales_rep_code = _get(row, COL_SALES_REP) or cust.sales_rep_code
        cust.is_tax_exempt = _bool_yn(_get(row, COL_TAX_EXEMPT))
        cust.tax_exempt_cert_number = _get(row, COL_TAX_EXEMPT_NUMBER) or cust.tax_exempt_cert_number
        cust.tax_exempt_state = _get(row, COL_TAX_EXEMPT_STATE) or cust.tax_exempt_state
        cust.payment_terms = _get(row, COL_TERMS) or cust.payment_terms
        cust.is_active = is_active
        credit = _parse_decimal(_get(row, COL_CREDIT_LIMIT))
        if credit is not None:
            try:
                cust.credit_limit_usd = int(credit)
            except (TypeError, ValueError):
                pass
        if dry_run:
            result.updated += 1
            return cus_num
        result.updated += 1

    # Address replacement — purge existing primary addresses, then rebuild.
    if not dry_run and cust.id is not None:
        existing_addrs = (
            await db.execute(
                select(CustomerAddress).where(
                    CustomerAddress.customer_id == cust.id,
                    CustomerAddress.is_primary.is_(True),
                )
            )
        ).scalars().all()
        for a in existing_addrs:
            await db.delete(a)
        await db.flush()

    bill_addr = _build_address(
        AddressType.BILLING,
        name=cust.contact_name,
        company=cust.name,
        addr1=_get(row, COL_BILL_ADDR1),
        addr2=_get(row, COL_BILL_ADDR2),
        city=_get(row, COL_BILL_CITY),
        state=_get(row, COL_BILL_STATE),
        zip_=_get(row, COL_BILL_ZIP),
    )
    ship_addr = _build_address(
        AddressType.SHIPPING,
        name=_get(row, COL_SHIP_NAME) or cust.contact_name,
        company=cust.name,
        addr1=_get(row, COL_SHIP_ADDR1),
        addr2=_get(row, COL_SHIP_ADDR2),
        city=_get(row, COL_SHIP_CITY),
        state=_get(row, COL_SHIP_STATE),
        zip_=_get(row, COL_SHIP_ZIP),
    )
    # Ship-to falls back to bill-to when ship_* columns are empty (very common).
    if ship_addr is None and bill_addr is not None:
        ship_addr = _build_address(
            AddressType.SHIPPING,
            name=cust.contact_name,
            company=cust.name,
            addr1=_get(row, COL_BILL_ADDR1),
            addr2=_get(row, COL_BILL_ADDR2),
            city=_get(row, COL_BILL_CITY),
            state=_get(row, COL_BILL_STATE),
            zip_=_get(row, COL_BILL_ZIP),
        )

    if not dry_run:
        if bill_addr is not None:
            bill_addr.customer_id = cust.id
            db.add(bill_addr)
        if ship_addr is not None:
            ship_addr.customer_id = cust.id
            db.add(ship_addr)

    return cus_num
