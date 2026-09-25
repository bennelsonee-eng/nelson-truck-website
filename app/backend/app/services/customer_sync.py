"""Customer sync — fills the website's `customer` table from the ERP mirror.

Source: `cus190_erp`, the website database's own mirror of the ERP's customer
master (filled by `scripts/sync_erp_feeds.py`, which copies the ERP Postgres
rows that land nightly as the CUS190 feed). Both live in `nelson_web`, so this
is a plain in-database read — no MySQL, no PHP bridge, no CSV.

It used to read `nte_cus190` through the legacy bridge. That table does not
exist in the `nelsontruck1` schema and never did, so the sync had never once
run: every website customer was still the placeholder the July contracts load
created ("Customer 79902", no name, no email, no address, no phone).

Target: the `customer` + `customer_address` tables.

What it does NOT do:
  * It never deletes or deactivates a customer that is absent from the mirror.
    388 of them exist — they came from the contracts file and have contract
    rows but no ERP record, so dropping them would take their pricing with it.
  * It never changes an existing customer's `tier`. See TIER below.

TIER: every customer today is `JOBBER`, a blanket default from the July load,
and new ones are created the same way. The ERP does carry a real per-customer
price level in `cus190_erp.price_type` (3: 2174, 1: 830, 0: 768, 2: 237,
5: 66, 4: 4, null: 210), but mapping those onto the four-value CustomerTier
enum is a pricing decision, not a data one — and not a free one either, since
`retail_price` is only above `jobber_price` on about half the catalogue. So
this sync leaves tier alone; price_type stays in `cus190_erp` in the same
database, ready to drive that mapping in one UPDATE once it is decided.

Run modes:
  * Programmatic: `await sync_customers_from_erp_mirror(db)`
  * CLI: `python -m scripts.sync_customers --dry-run`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AddressType,
    Customer,
    CustomerAddress,
    CustomerTier,
)


log = logging.getLogger(__name__)


# The mirror table, and the columns worth carrying across. Everything the ERP
# sends that the website has nowhere to put (territory, location_code,
# default_warehouse, po_required, tax_code, start_date, erp_id) stays in
# cus190_erp rather than being dropped on the floor.
SOURCE_TABLE = "cus190_erp"

SOURCE_QUERY = f"""
    select customer_number, name, contact, address1, address2, city, state, zip,
           phone, fax, email, terms, tax_exempt, status, price_type,
           bill_to_customer, sales_rep, credit_limit
    from {SOURCE_TABLE}
    where coalesce(customer_number, '') <> ''
"""

# "A" is an open account; "C" is closed (205 of 4,289).
STATUS_ACTIVE = "A"

# The ERP writes '0' into bill_to_customer to mean "bills itself". Treating
# that as a parent would hang 3,544 customers off a customer numbered 0 that
# does not exist; only 391 rows name a real different parent.
NO_PARENT = {"", "0"}


@dataclass
class SyncResult:
    rows_read: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    parents_linked: int = 0
    addresses_written: int = 0
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    def summary(self) -> str:
        return (
            f"{SOURCE_TABLE} sync: read={self.rows_read} inserted={self.inserted} "
            f"updated={self.updated} skipped={self.skipped} "
            f"parents_linked={self.parents_linked} "
            f"addresses={self.addresses_written} errors={len(self.errors)} "
            f"dry_run={self.dry_run}"
        )


# --- Helpers ----------------------------------------------------------------


def _s(v: Any) -> str | None:
    """Trim to a non-empty string, or None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _parse_decimal(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _build_address(
    addr_type: AddressType,
    *,
    name: str | None,
    company: str,
    addr1: str | None,
    addr2: str | None,
    city: str | None,
    state: str | None,
    zip_: str | None,
) -> CustomerAddress | None:
    """A partial address is worse than none — it would ship somewhere wrong."""
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
        state=state[:2].upper(),
        zip=zip_,
        country="US",
    )


# --- Main sync --------------------------------------------------------------


async def sync_customers_from_erp_mirror(
    db: AsyncSession,
    *,
    dry_run: bool = False,
    limit: int | None = None,
    default_tier: CustomerTier = CustomerTier.JOBBER,
) -> SyncResult:
    """Upsert every `cus190_erp` row into `customer` (+ its primary addresses),
    then link `parent_customer_id` from `bill_to_customer` in a second pass.

    Matched on `customer_number`, which carries a unique index, so the sync is
    idempotent: running it twice changes nothing the second time.
    """
    result = SyncResult(dry_run=dry_run)

    sql = SOURCE_QUERY + (f" limit {int(limit)}" if limit else "")
    try:
        rows = (await db.execute(text(sql))).mappings().all()
    except Exception as e:
        msg = f"Reading {SOURCE_TABLE} failed: {e}"
        result.errors.append(msg)
        log.exception(msg)
        return result

    if not rows:
        msg = (f"{SOURCE_TABLE} is empty — run scripts/sync_erp_feeds.py first, "
               f"or the website would learn nothing about its customers")
        result.errors.append(msg)
        log.warning(msg)
        return result

    # cus_num -> bill_to, for the second pass once every row exists.
    parent_map: dict[str, str] = {}

    for row in rows:
        result.rows_read += 1
        try:
            cus_num = await _upsert_one(db, row, default_tier, dry_run, result)
        except Exception as e:
            result.errors.append(f"row {row.get('customer_number', '?')}: {e}")
            log.exception("Sync row failed")
            continue
        if not cus_num:
            continue
        bill_to = _s(row.get("bill_to_customer"))
        if bill_to and bill_to not in NO_PARENT and bill_to != cus_num:
            parent_map[cus_num] = bill_to

    if not dry_run and parent_map:
        result.parents_linked = await _link_parents(db, parent_map)
    elif dry_run:
        result.parents_linked = len(parent_map)

    if dry_run:
        await db.rollback()
    else:
        await db.commit()

    log.info(result.summary())
    return result


async def _link_parents(db: AsyncSession, parent_map: dict[str, str]) -> int:
    """Point each child at its billing parent. A parent the mirror names but
    the website does not carry is skipped rather than invented."""
    wanted = set(parent_map) | set(parent_map.values())
    rows = (
        await db.execute(
            select(Customer.id, Customer.customer_number).where(
                Customer.customer_number.in_(wanted)
            )
        )
    ).all()
    id_by_num = {num: cid for cid, num in rows}

    children = (
        await db.execute(
            select(Customer).where(Customer.customer_number.in_(list(parent_map)))
        )
    ).scalars().all()

    linked = 0
    for child in children:
        parent_id = id_by_num.get(parent_map[child.customer_number])
        if parent_id is None or parent_id == child.id:
            continue
        if child.parent_customer_id != parent_id:
            child.parent_customer_id = parent_id
            linked += 1
    return linked


async def _upsert_one(
    db: AsyncSession,
    row: Any,
    default_tier: CustomerTier,
    dry_run: bool,
    result: SyncResult,
) -> str | None:
    cus_num = _s(row.get("customer_number"))
    if not cus_num:
        result.skipped += 1
        return None

    name = _s(row.get("name")) or f"Customer {cus_num}"
    is_active = (_s(row.get("status")) or "").upper() == STATUS_ACTIVE

    existing = (
        await db.execute(select(Customer).where(Customer.customer_number == cus_num))
    ).scalar_one_or_none()

    if existing is None:
        cust = Customer(
            customer_number=cus_num,
            tier=default_tier,
            name=name,
            is_tax_exempt=bool(row.get("tax_exempt")),
            is_active=is_active,
        )
        db.add(cust)
        result.inserted += 1
    else:
        cust = existing
        result.updated += 1

    # Written on both paths. The ERP is authoritative for these, so a value it
    # sends overwrites; a field it leaves empty keeps whatever is there rather
    # than blanking a detail someone added in the admin.
    cust.name = name
    cust.contact_name = _s(row.get("contact")) or cust.contact_name
    cust.email = _s(row.get("email")) or cust.email
    cust.phone = _s(row.get("phone")) or cust.phone
    cust.fax = _s(row.get("fax")) or cust.fax
    cust.sales_rep_code = _s(row.get("sales_rep")) or cust.sales_rep_code
    cust.payment_terms = _s(row.get("terms")) or cust.payment_terms
    cust.is_tax_exempt = bool(row.get("tax_exempt"))
    cust.is_active = is_active

    credit = _parse_decimal(row.get("credit_limit"))
    if credit is not None:
        try:
            cust.credit_limit_usd = int(credit)
        except (TypeError, ValueError):
            pass

    if dry_run:
        return cus_num

    await db.flush()  # a new customer needs its id before addresses hang off it

    # The CUS190 feed carries one address, the billing one; there are no ship_to
    # columns, so shipping is the same address until someone edits it in the
    # admin. Primary addresses are rebuilt each run; non-primary ones (added by
    # a customer or a rep) are left alone.
    addr1 = _s(row.get("address1"))
    city = _s(row.get("city"))
    state = _s(row.get("state"))
    zip_ = _s(row.get("zip"))
    if not (addr1 and city and state and zip_):
        return cus_num

    stale = (
        await db.execute(
            select(CustomerAddress).where(
                CustomerAddress.customer_id == cust.id,
                CustomerAddress.is_primary.is_(True),
            )
        )
    ).scalars().all()
    for a in stale:
        await db.delete(a)
    if stale:
        await db.flush()

    for addr_type in (AddressType.BILLING, AddressType.SHIPPING):
        addr = _build_address(
            addr_type,
            name=cust.contact_name,
            company=cust.name,
            addr1=addr1,
            addr2=_s(row.get("address2")),
            city=city,
            state=state,
            zip_=zip_,
        )
        if addr is not None:
            addr.customer_id = cust.id
            db.add(addr)
            result.addresses_written += 1

    return cus_num
