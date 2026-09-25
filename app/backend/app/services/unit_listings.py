"""Rules and helpers for trucks & equipment for sale.

Everything that decides what a customer may see lives here, so the admin API,
the public API and the Build & Price quote builder cannot drift apart:

  * price policy -- Jerr-Dan does not let dealers advertise a retail price, so a
    Jerr-Dan unit is never "show price", whatever the admin picked;
  * the price range a qualified customer is given, and when;
  * what a listing needs before it can be published (10+ photos, an on-hand ERP
    part unless it is consigned, a price, a location...);
  * the follow-up promise ("a salesperson will be in touch shortly" in business
    hours, "tomorrow morning" after them);
  * photo processing, VIN decoding, the spec-sheet parser, and the erp_onhand
    mirror of the legacy on-hand feed.
"""
from __future__ import annotations

import csv
import io
import logging
import math
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.unit_listing import (ErpOnhand, ErpUnitOrder, UnitListing,
                                     UnitListingMedia, UnitListingPart)

log = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

CATEGORY_LABELS: dict[str, str] = {
    "wrecker": "Wreckers",
    "carrier": "Carriers & Rollbacks",
    "aerial": "Aerial & Bucket Trucks",
    "trailer": "Trailers",
    "crane": "Crane Trucks & Cranes",
    "cab-chassis": "Cab & Chassis",
    "service": "Service & Utility Trucks",
    "dump": "Dump Trucks & Bodies",
    "equipment": "Equipment",
    "other": "Other Trucks",
}
CATEGORY_SINGULAR: dict[str, str] = {
    "wrecker": "Wrecker", "carrier": "Carrier", "aerial": "Bucket truck",
    "trailer": "Trailer", "crane": "Crane", "cab-chassis": "Cab & chassis",
    "service": "Service truck", "dump": "Dump", "equipment": "Equipment", "other": "Truck",
}
LOCATION_LABELS = {"portland": "Portland, OR", "kent": "Kent, WA", "spokane": "Spokane, WA"}
# ERP warehouse code -> listing location
WAREHOUSE_LOCATION = {1: "portland", 2: "kent", 10: "spokane"}

# Specs worth asking for, per category. Offered as suggestions in the editor;
# a listing can carry any label.
CATEGORY_SPEC_HINTS: dict[str, list[str]] = {
    "wrecker": ["Wrecker model", "Boom capacity", "Wheel-lift capacity", "Wheel-lift reach",
                "Winches", "Winch capacity", "Body length", "Controls"],
    "carrier": ["Deck length", "Deck width", "Deck material", "Capacity", "Winch capacity",
                "Wheel lift", "Rails", "Controls"],
    "aerial": ["Working height", "Platform height", "Side reach", "Platform capacity",
               "Boom type", "Insulated", "Jib", "Outriggers"],
    "trailer": ["Deck length", "Deck width", "Capacity", "Axles", "Deck type",
                "Suspension", "Tires", "Winch"],
    "crane": ["Crane make/model", "Capacity", "Max reach", "Boom sections", "Rotation",
              "Controls", "Outriggers", "Year of crane"],
    "cab-chassis": ["Frame", "PTO provision", "Upfit-ready", "Cab-to-axle"],
    "service": ["Body length", "Compartments", "Crane", "Compressor", "Welder"],
    "dump": ["Body length", "Side height", "Capacity (yd³)", "Hoist", "Tarp", "Tailgate"],
    "equipment": ["Capacity", "Dimensions", "Weight", "Mounting", "Hours", "Condition notes"],
    "other": [],
}

# Controlled feature vocabulary (a trimmed version of CTT's 99 checkboxes).
FEATURES: list[str] = [
    "4x4", "Dually", "Air Brakes", "Anti-Lock Brakes", "Air Ride Suspension", "Exhaust Brake",
    "Jake Brake", "PTO", "PTO Prep", "Snow Plow Prep", "Aluminum Wheels", "LED Light Bar",
    "Strobe Package", "Work Lights", "Backup Camera", "Wireless Remote", "Toolboxes",
    "Headache Rack", "Lift Gate", "Under CDL", "Air Conditioning", "Cruise Control",
    "Power Windows", "Power Locks", "Bluetooth", "Tilt Steering", "Block Heater",
    "Two-Way Radio Prep", "DOT Inspected", "Warranty Remaining",
]

# Badges the admin can put on a listing (Ben, 2026-09-25: "tags like hot item
# ... new build and more action items that can be dictated in admin"). Anything
# typed is allowed too; these are the ones offered, with their colour.
TAG_PRESETS: dict[str, str] = {
    "Hot item": "red", "New build": "blue", "Just arrived": "green", "Price reduced": "amber",
    "Ready to work": "green", "Low miles": "slate", "Demo unit": "slate", "Fleet special": "blue",
    "Won't last": "red", "Make an offer": "amber",
}

# ---------------------------------------------------------------------------
# Price policy
# ---------------------------------------------------------------------------

# Jerr-Dan does not let its dealers advertise a retail price on wreckers and
# carriers (Ben, 2026-09-25). A price is only ever given one-to-one: by phone,
# by email, or as a range once a customer has confirmed the unit's specs and
# left contact details. Matched on the upfit make, the chassis/equipment make,
# and any linked ERP part in the JERR product code.
RESTRICTED_PRICE_MAKES = {"jerrdan"}
RESTRICTED_PROD_CODES = {"JERR"}


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def price_restricted(listing: UnitListing, part_prod_codes: Iterable[str | None] = ()) -> bool:
    if _norm(listing.upfit_make) in RESTRICTED_PRICE_MAKES:
        return True
    if _norm(listing.make) in RESTRICTED_PRICE_MAKES:
        return True
    return any((pc or "").upper() in RESTRICTED_PROD_CODES for pc in part_prod_codes)


def effective_price_mode(listing: UnitListing, restricted: bool) -> str:
    mode = listing.price_mode if listing.price_mode in ("show", "call", "range") else "range"
    if restricted and mode == "show":
        return "range"
    return mode


def _round_down(v: float, step: int) -> int:
    return int(math.floor(v / step) * step)


def _round_up(v: float, step: int) -> int:
    return int(math.ceil(v / step) * step)


def effective_range(listing: UnitListing, cost: float | None = None) -> tuple[int, int] | None:
    """The range a qualified customer is told. An explicit range wins; otherwise
    3% either side of the asking price, rounded outward to the nearest $1,000.

    A worked-out range never starts below what the unit cost us: on a thin
    margin the 3% would otherwise quote under cost (the 2024 F-550 MPL60 at
    $159,500 on $156,440 would have opened at $154,000). An explicit range the
    admin typed is taken as meant."""
    if listing.range_low and listing.range_high and listing.range_high >= listing.range_low:
        return int(listing.range_low), int(listing.range_high)
    base = listing.sale_price or listing.price
    if not base:
        return None
    b = float(base)
    low, high = _round_down(b * 0.97, 1000), _round_up(b * 1.03, 1000)
    if cost:
        low = max(low, _round_up(cost, 1000))
        high = max(high, low)
    return low, high


def builder_range(low: float, high: float) -> tuple[int, int]:
    """The Build & Price range: the configured low/high widened a little for the
    market and rounded outward to $5,000, so it reads as the honest ballpark it
    is ("$130,000 - $150,000"), never as a quote."""
    return _round_down(low * 0.97, 5000), _round_up(high * 1.03, 5000)


# ---------------------------------------------------------------------------
# Titles, slugs, default qualifier specs
# ---------------------------------------------------------------------------

def _fmt_int(n: int | None) -> str:
    return f"{n:,}" if n else ""


def listing_title(l: UnitListing) -> str:
    bits = [str(l.year) if l.year else "", l.make or "", l.model or "", l.trim or ""]
    title = " ".join(b for b in bits if b).strip()
    if not title:
        title = l.headline or CATEGORY_SINGULAR.get(l.category, "Unit")
    if l.condition == "used" and l.unit_type == "equipment" and not title.lower().startswith("used"):
        title = f"Used {title}"
    return title[:200]


# Words that already say what the unit is, so the category noun isn't repeated
# ("Vulcan 894 wrecker", not "Vulcan 894 wrecker wrecker").
_KIND_WORDS = re.compile(r"wrecker|carrier|rollback|aerial|bucket|lift|trailer|crane|body|bed|truck", re.I)


def listing_subtitle(l: UnitListing) -> str:
    if l.upfit_make or l.upfit_model:
        up = " ".join(b for b in [l.upfit_make or "", l.upfit_model or ""] if b)
        if _KIND_WORDS.search(up):
            return up
        return f"{up} {CATEGORY_SINGULAR.get(l.category, '').lower()}".strip()
    return CATEGORY_SINGULAR.get(l.category, "")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:120] or "unit"


def default_qualify_specs(l: UnitListing) -> list[dict[str, str]]:
    """What a customer confirms before a price range is given -- the facts that
    make two quotes comparable. Built from the listing; editable in the admin."""
    out: list[dict[str, str]] = []
    if l.unit_type != "equipment":
        chassis = " ".join(b for b in [str(l.year or ""), l.make or "", l.model or "", l.trim or ""] if b).strip()
        if chassis:
            out.append({"label": "Chassis", "value": chassis})
        drive_fuel = " · ".join(b for b in [l.drive or "", l.engine or l.fuel or ""] if b)
        if drive_fuel:
            out.append({"label": "Drivetrain", "value": drive_fuel})
        if l.cab_type:
            out.append({"label": "Cab", "value": l.cab_type})
    up = " ".join(b for b in [l.upfit_make or "", l.upfit_model or ""] if b).strip()
    if up:
        out.append({"label": "Body / equipment", "value": up})
    for s in (l.specs or [])[:3]:
        if s.get("label") and s.get("value"):
            out.append({"label": str(s["label"]), "value": str(s["value"])})
    if l.condition in ("used", "demo"):
        miles = f"{_fmt_int(l.mileage)} miles" if l.mileage else ""
        out.append({"label": "Condition", "value": " · ".join(b for b in [l.condition.title(), miles] if b)})
    return out[:7]


# ---------------------------------------------------------------------------
# Follow-up promise
# ---------------------------------------------------------------------------

OPEN_AT = time(8, 0)
# Leave the last half hour out: a 4:55pm request should hear "tomorrow morning",
# not "shortly".
PROMISE_CUTOFF = time(16, 30)


def follow_up_message(first_name: str | None = None, now: datetime | None = None) -> dict[str, str]:
    """What the customer is told about when a salesperson will reply.

    Both branches are open Mon-Fri 8am-5pm Pacific. Holidays are not modelled.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(PACIFIC)
    name = f", {first_name}" if first_name else ""
    wd = now.weekday()  # Mon=0
    t = now.time()
    if wd < 5 and OPEN_AT <= t < PROMISE_CUTOFF:
        when = "shortly"
        text = (f"Thanks{name} — we've received your request, and a friendly salesperson "
                f"will be in touch shortly about your buying needs.")
    elif wd < 5 and t < OPEN_AT:
        when = "this morning"
        text = (f"Thanks{name} — we've received your request. Our sales team opens at 8am "
                f"Pacific and a salesperson will follow up with you this morning.")
    else:
        # After hours: next business morning.
        nxt = now.date() + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        day = "tomorrow" if (nxt - now.date()).days == 1 else nxt.strftime("%A")
        when = f"{day} morning"
        text = (f"Thanks{name} — we've received your request. Our sales team is out for the "
                f"day, and a salesperson will follow up with you {day} morning.")
    return {"when": when, "text": text}


# ---------------------------------------------------------------------------
# Publish checklist ("Listing Health")
# ---------------------------------------------------------------------------

MIN_PHOTOS = 10
GOOD_DESCRIPTION = 250


@dataclass
class HealthItem:
    key: str
    label: str
    ok: bool
    blocking: bool
    detail: str = ""


def listing_health(
    l: UnitListing,
    *,
    photos: int,
    videos: int,
    parts_total: int,
    parts_on_hand: int,
    restricted: bool,
) -> list[HealthItem]:
    items: list[HealthItem] = []
    consigned = l.ownership == "consignment"

    if consigned:
        items.append(HealthItem("parts", "Consigned — no ERP part needed", True, True,
                                "Sold for a customer; consignor details are internal."))
    elif l.availability == "future_build":
        items.append(HealthItem("parts", "ERP part number linked", parts_total > 0, True,
                                "A future build still needs the chassis or body part it will be built from."))
    else:
        items.append(HealthItem("parts", "ERP part on hand", parts_on_hand > 0, True,
                                f"{parts_on_hand} of {parts_total} linked parts are on hand."
                                if parts_total else "Link the unit's ERP part number."))

    items.append(HealthItem("photos", f"{MIN_PHOTOS}+ photos", photos >= MIN_PHOTOS, True,
                            f"{photos} uploaded."))

    ident_ok = bool(l.make and l.model) and (l.unit_type == "equipment" or bool(l.year))
    items.append(HealthItem("identity", "Year, make & model", ident_ok, True))

    items.append(HealthItem("location", "Location", bool(l.location), True))

    mode = effective_price_mode(l, restricted)
    if l.availability == "future_build":
        price_ok = bool(l.price)
        price_label = "Retail price (future build)"
    elif mode == "show":
        price_ok = bool(l.price)
        price_label = "Price"
    elif mode == "range":
        price_ok = effective_range(l) is not None
        price_label = "Price or range for the price-range chat"
    else:
        price_ok = True
        price_label = "Call for price"
    items.append(HealthItem("price", price_label, price_ok, True))

    if l.availability == "future_build":
        items.append(HealthItem("available", "Available date", bool(l.available_date or l.available_note), True))

    desc_len = len((l.description or "").strip())
    items.append(HealthItem("description", f"Description ({GOOD_DESCRIPTION}+ characters)",
                            desc_len >= GOOD_DESCRIPTION, False, f"{desc_len} characters."))
    items.append(HealthItem("video", "At least one video", videos > 0 or bool(l.video_urls), False))
    spec_count = len([s for s in (l.specs or []) if s.get("value")])
    chassis_count = sum(1 for v in (l.engine, l.transmission, l.gvwr_lbs, l.drive, l.fuel) if v)
    items.append(HealthItem("specs", "Key specs filled in",
                            spec_count >= 3 or (l.unit_type != "equipment" and chassis_count >= 3), False))
    return items


def erp_state(l: UnitListing, pstat: dict[str, Any], mirror_live: bool,
              sold_by_order: bool = False) -> str:
    """What the ERP says about a Nelson-owned, in-stock listing: "ok" or "sold".

    Sold means the unit has left the lot (no linked part on hand), or an open
    order on it counts as a sale by Ben's rule (money down, or an account
    customer with a valid PO). A quote -- the ERP marks the unit committed, but
    nobody has bought it -- leaves it for sale. Sold units stay on the site,
    marked SOLD.

    Consigned units and future builds aren't tracked this way, and nothing is
    judged while the on-hand mirror is empty (a failed refresh must not mark
    every unit sold)."""
    if not mirror_live or l.ownership == "consignment" or l.availability != "in_stock":
        return "ok"
    parts = pstat.get("parts") or []
    if not parts:
        return "ok"
    if pstat.get("on_hand", 0) == 0:
        return "sold"
    if sold_by_order:
        return "sold"
    return "ok"


# -- the ERP's orders and quotes on a unit ---------------------------------

# Charge terms = a customer "with an account". COD and VISA (card on file) are not.
ACCOUNT_TERMS = {"N10TH", "N10THA", "N30", "O/A", "OA"}
# Nelson's own accounts: demos, internal moves, adjustments -- never a sale.
INTERNAL_CUSTOMERS = {"43850", "43856"}
# What gets typed in the PO box when there is no PO.
PO_PLACEHOLDER = re.compile(r"QUOTE|DEMO|ADJUST|\bTBD\b|^N/?A$|\bNONE\b|\bSTOCK\b|\bHOLD\b|ON FILE|VERBAL|PENDING", re.I)


def classify_order(order_type: str | None, status: str | None, customer_number: str | None,
                   customer_name: str | None, terms: str | None, po: str | None,
                   deposit: float) -> tuple[str, str, bool, bool, bool]:
    """-> (classification, reason, is_account, po_valid, is_internal)."""
    cust = (customer_number or "").strip()
    internal = cust in INTERNAL_CUSTOMERS or (customer_name or "").upper().startswith("NELSON TRUCK EQUIPMENT")
    account = (terms or "").strip().upper() in ACCOUNT_TERMS
    po = (po or "").strip()
    po_valid = bool(po) and not PO_PLACEHOLDER.search(po)
    if internal:
        return "internal", "Nelson's own account (demo, internal or adjustment)", account, po_valid, True
    if (order_type or "").upper() == "Q" or (status or "").lower() in ("draft", "quote"):
        return "quote", "written up as a quote", account, po_valid, False
    if deposit > 0:
        return "sale", f"${deposit:,.0f} down", account, po_valid, False
    if account and po_valid:
        return "sale", f"account customer with PO {po}", account, po_valid, False
    if account:
        return "quote", f"account customer, no valid PO ({po or 'blank'})", account, po_valid, False
    return "quote", f"{(terms or 'no').strip()} terms and no money down", account, po_valid, False


async def refresh_unit_orders(db: AsyncSession, erp_dsn: str) -> int:
    """Mirror the ERP's open orders and quotes on unit part numbers.

    Units are the on-hand parts over $10,000 at cost plus anything linked to a
    listing. Invoiced orders are left out on purpose: an invoiced unit leaves
    the on-hand, which already marks it sold -- and Landoll and Jerr-Dan part
    numbers are reused for every unit of a model, so last year's invoice for a
    455B-53 says nothing about the one on the lot today."""
    import asyncpg

    pns = set((await db.execute(select(ErpOnhand.part_number).where(ErpOnhand.gl_cost >= 10000))).scalars().all())
    pns |= set((await db.execute(select(UnitListingPart.part_number))).scalars().all())
    pns = {p for p in pns if p and not PSEUDO_PART.match(p)}
    if not pns:
        return 0
    conn = await asyncpg.connect(erp_dsn.replace("postgresql+asyncpg://", "postgresql://"), timeout=20)
    try:
        rows = await conn.fetch("""
            with lines as (
                select l.order_id, l.ourparts_num, l.serial_number, l.qty_ordered
                from sales_order_lines l
                where l.ourparts_num = any($1::text[])
            ), dep as (
                select order_id, -sum(extended_price) as received
                from sales_order_lines
                where ourparts_num ~* '^(MIS ?)?DEPOSIT'
                group by order_id
            )
            select lines.ourparts_num, lines.serial_number, lines.qty_ordered,
                   o.order_number, o.order_type, o.status, o.order_date, o.po_number,
                   c.customer_number, coalesce(c.name, o.walkin_customer_name) as customer_name,
                   c.terms, coalesce(dep.received, 0) as received
            from lines
            join sales_orders o on o.id = lines.order_id
            left join customers c on c.id = o.customer_id
            left join dep on dep.order_id = o.id
            where coalesce(o.status, '') not in ('invoiced', 'shipped', 'closed', 'complete', 'completed',
                                                 'void', 'voided', 'cancelled', 'canceled', 'deleted')
              and o.order_date > now() - interval '18 months'
              and coalesce(lines.qty_ordered, 0) > 0
        """, list(pns))
    finally:
        await conn.close()

    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        cls, reason, account, po_ok, internal = classify_order(
            r["order_type"], r["status"], r["customer_number"], r["customer_name"],
            r["terms"], r["po_number"], float(r["received"] or 0))
        out.append({
            "part_number": r["ourparts_num"][:60], "serial": ((r["serial_number"] or "").strip()[:40] or None),
            "order_number": str(r["order_number"])[:20], "order_type": (r["order_type"] or "")[:4] or None,
            "order_status": (r["status"] or "")[:20] or None, "order_date": r["order_date"],
            "customer_number": (r["customer_number"] or "")[:20] or None,
            "customer_name": (r["customer_name"] or "")[:160] or None,
            "terms": (r["terms"] or "")[:12] or None, "is_account": account,
            "po_number": ((r["po_number"] or "").strip()[:40] or None), "po_valid": po_ok,
            "deposit_received": Decimal(str(max(float(r["received"] or 0), 0))), "is_internal": internal,
            "qty_ordered": r["qty_ordered"], "classification": cls, "reason": reason[:200], "synced_at": now,
        })
    await db.execute(delete(ErpUnitOrder))
    if out:
        await db.execute(ErpUnitOrder.__table__.insert(), out)
    await db.commit()
    return len(out)


def part_sold(part_number: str, serial: str | None, orders: list[ErpUnitOrder], on_hand: int) -> bool:
    """Is this unit sold by the ERP's orders?

    A part number that names one unit (CHASSIS-<VIN>, or only one on hand):
    any sale order sells it. A model-level number (JERRMPL40 covers eight
    bodies) is sold for this unit when a sale order carries its serial, or --
    since legacy order lines carry no serial -- when the sale orders cover
    every one on hand. Seven MPL40 sales against eight bodies leaves one to
    sell."""
    mine = [o for o in orders if o.part_number == part_number and o.classification == "sale"]
    if not mine:
        return False
    if part_number.upper().startswith("CHASSIS") or on_hand <= 1:
        return True
    if serial and any(o.serial and _norm(o.serial).endswith(_norm(serial)[-6:]) for o in mine):
        return True
    return len([o for o in mine if not o.serial]) >= on_hand


async def orders_for(db: AsyncSession, pstats: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """Per listing: the ERP orders on its part numbers (for the admin to watch)
    and whether they make the unit sold."""
    pns = {p["part_number"] for ps in pstats.values() for p in ps.get("parts", [])}
    if not pns:
        return {lid: {"orders": [], "sold": False} for lid in pstats}
    orders = (await db.execute(select(ErpUnitOrder).where(ErpUnitOrder.part_number.in_(pns))
                               .order_by(ErpUnitOrder.order_date.desc()))).scalars().all()
    counts = dict((await db.execute(select(ErpOnhand.part_number, func.count())
                                    .where(ErpOnhand.part_number.in_(pns), ErpOnhand.onhand > 0)
                                    .group_by(ErpOnhand.part_number))).all())
    out: dict[int, dict[str, Any]] = {}
    for lid, ps in pstats.items():
        parts = ps.get("parts", [])
        mine = [o for o in orders if any(o.part_number == p["part_number"] for p in parts)]
        sold = any(part_sold(p["part_number"], p.get("serial"), orders, counts.get(p["part_number"], 0))
                   for p in parts)
        out[lid] = {"orders": mine, "sold": sold}
    return out


def order_out(o: ErpUnitOrder) -> dict[str, Any]:
    return {"order_number": o.order_number, "order_type": o.order_type, "status": o.order_status,
            "order_date": o.order_date.isoformat() if o.order_date else None,
            "customer_number": o.customer_number, "customer_name": o.customer_name,
            "terms": o.terms, "is_account": o.is_account, "po_number": o.po_number,
            "po_valid": o.po_valid, "deposit_received": float(o.deposit_received or 0),
            "classification": o.classification, "reason": o.reason, "serial": o.serial}


async def erp_mirror_live(db: AsyncSession) -> bool:
    return (await db.execute(select(ErpOnhand.id).limit(1))).first() is not None


def health_score(items: list[HealthItem]) -> dict[str, Any]:
    done = sum(1 for i in items if i.ok)
    blocking_open = [i for i in items if i.blocking and not i.ok]
    pct = round(100 * done / len(items)) if items else 0
    label = ("Excellent" if not blocking_open and done == len(items)
             else "Ready to publish" if not blocking_open
             else "Incomplete")
    return {"score": pct, "done": done, "total": len(items), "label": label,
            "can_publish": not blocking_open,
            "items": [i.__dict__ for i in items]}


# ---------------------------------------------------------------------------
# ERP on-hand mirror
# ---------------------------------------------------------------------------

# Accounting entries that live in the inventory table but are not goods:
# deposits, corrections, rebates. Never offered as a unit to list.
PSEUDO_PART = re.compile(
    r"^(MIS\b|MISC\b|INV\s|INVOICE\s|CREDIT\s|TAX\s|PRE\s?PAY|SOLD\s|OEM\s|DEPOSIT)", re.I)


def _dec(v: Any) -> Decimal | None:
    try:
        s = str(v).strip()
        return Decimal(s) if s not in ("", "None", "NULL") else None
    except Exception:
        return None


def _int(v: Any) -> int | None:
    d = _dec(v)
    return int(d) if d is not None else None


async def refresh_erp_onhand(db: AsyncSession, inv_csv: Path, master_csv: Path) -> int:
    """Rebuild erp_onhand from the two CSVs the inventory job has just fetched.

    Only rows with stock are kept. The 87 MB parts master is streamed and only
    the few thousand part numbers on hand are held, so this costs a couple of
    seconds every 15 minutes.
    """
    inv_rows: list[dict[str, str]] = []
    with inv_csv.open(newline="", encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            if (_dec(r.get("onhand")) or 0) > 0:
                inv_rows.append(r)
    wanted = {(r.get("ourparts_num") or "").strip() for r in inv_rows}

    master: dict[str, dict[str, str]] = {}
    if master_csv.exists():
        with master_csv.open(newline="", encoding="utf-8", errors="replace") as f:
            for r in csv.DictReader(f):
                k = (r.get("ourparts_num") or "").strip()
                if k in wanted and k not in master:
                    master[k] = r

    now = datetime.now(timezone.utc)
    rows = []
    for r in inv_rows:
        pn = (r.get("ourparts_num") or "").strip()
        if not pn:
            continue
        m = master.get(pn, {})
        rows.append({
            "part_number": pn[:60],
            "prod_code": ((r.get("prod_code") or m.get("prod_code") or "").strip() or None),
            "warehouse": _int(r.get("warehouse")),
            "onhand": _dec(r.get("onhand")) or Decimal(0),
            "available": _dec(r.get("available")),
            "gl_cost": _dec(r.get("gl_cost")),
            "days": _int(r.get("days")),
            "serial": ((r.get("serial") or "").strip()[:40] or None),
            "description": ((m.get("description") or "").strip()[:200] or None),
            "extra_desc": ((m.get("extra_desc") or "").strip()[:200] or None),
            "p1": _dec(m.get("P1")), "p2": _dec(m.get("P2")), "p3": _dec(m.get("P3")),
            "synced_at": now,
        })
    await db.execute(delete(ErpOnhand))
    if rows:
        await db.execute(ErpOnhand.__table__.insert(), rows)
    await db.commit()
    return len(rows)


def classify_erp_part(prod_code: str | None, part_number: str) -> str:
    pc = (prod_code or "").upper()
    if pc == "CHASSIS" or part_number.upper().startswith("CHASSIS"):
        return "Cab & chassis"
    if pc == "JERR":
        return "Jerr-Dan body"
    if pc == "DRL":
        return "Dur-A-Lift"
    if pc in ("LAND", "LAN"):
        return "Landoll trailer"
    if pc in ("USE", "USED"):
        return "Used unit"
    return "Other equipment"


def guess_from_erp(row: ErpOnhand) -> dict[str, Any]:
    """Prefill a new listing from an on-hand row: year/make/model from the ERP
    description ("2025 RAM 5500 CREWCAB 60CA 4X4"), the VIN from the serial or
    extra description, the category from the product code."""
    desc = f"{row.description or ''} {row.extra_desc or ''}"
    out: dict[str, Any] = {}
    m = re.search(r"\b(19[89]\d|20[0-3]\d)\b", desc)
    if m:
        out["year"] = int(m.group(1))
    for mk, pretty in (("FORD", "Ford"), ("RAM", "Ram"), ("DODGE", "Ram"), ("ISUZU", "Isuzu"),
                       ("FREIGHTLINER", "Freightliner"), ("INTERNATION", "International"),
                       ("IHC", "International"), ("CHEV", "Chevrolet"), ("GMC", "GMC"),
                       ("HINO", "Hino"), ("KENWORTH", "Kenworth"), ("PETERBILT", "Peterbilt"),
                       ("LANDOLL", "Landoll")):
        if re.search(rf"\b{mk}", desc, re.I):
            out["make"] = pretty
            break
    mm = re.search(r"\b(F[- ]?[3-7]50|[3-5]500|NRR|NPR|NQR|M2(?: 106)?|MV607|4300|455B|MPL\s?\d+)\b", desc, re.I)
    if mm:
        out["model"] = mm.group(1).upper().replace(" ", "")
    if re.search(r"\b4X4\b", desc, re.I):
        out["drive"] = "4x4"
    if re.search(r"CREW\s?CAB", desc, re.I):
        out["cab_type"] = "Crew cab"
    elif re.search(r"\bSTD\b|STANDARD|REG(ULAR)?\s?CAB", desc, re.I):
        out["cab_type"] = "Regular cab"
    ca = re.search(r"\b(\d{2,3})\s?CA\b", desc, re.I)
    if ca:
        out["cab_to_axle_in"] = int(ca.group(1))
    vin = None
    for cand in (row.serial or "", row.extra_desc or ""):
        v = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", cand.upper().replace("IFD", "1FD"))
        if v:
            vin = v.group(1)
            break
    if vin:
        out["vin"] = vin
    pc = (row.prod_code or "").upper()
    out["category"] = {"CHASSIS": "cab-chassis", "JERR": "carrier", "DRL": "aerial",
                       "LAND": "trailer"}.get(pc, "other")
    if pc == "DRL":
        out["upfit_make"] = "Dur-A-Lift"
    if pc == "JERR":
        out["upfit_make"] = "Jerr-Dan"
        if re.search(r"MPL|WRECK", desc, re.I):
            out["category"] = "wrecker"
    if pc == "LAND":
        out["unit_type"] = "trailer"
        out["make"] = "Landoll"
    if pc == "USE" or (row.description or "").upper().startswith("USED"):
        out["condition"] = "used"
    out["location"] = WAREHOUSE_LOCATION.get(row.warehouse or 0)
    return out


# ---------------------------------------------------------------------------
# VIN decode (NHTSA vPIC, free and public)
# ---------------------------------------------------------------------------

VPIC = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValuesExtended/{vin}?format=json"
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")


async def decode_vin(vin: str) -> dict[str, Any]:
    vin = (vin or "").strip().upper()
    if not VIN_RE.match(vin):
        return {"ok": False, "error": "A VIN is 17 characters, with no I, O or Q."}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(VPIC.format(vin=vin))
            r.raise_for_status()
            res = (r.json().get("Results") or [{}])[0]
    except Exception as e:
        return {"ok": False, "error": f"The NHTSA VIN service did not answer ({type(e).__name__})."}

    def g(k: str) -> str:
        v = (res.get(k) or "").strip()
        return "" if v in ("Not Applicable", "0") else v

    out: dict[str, Any] = {}
    if g("ModelYear").isdigit():
        out["year"] = int(g("ModelYear"))
    if g("Make"):
        out["make"] = g("Make").title()
    if g("Model"):
        out["model"] = g("Model")
    if g("Trim") or g("Series"):
        out["trim"] = g("Trim") or g("Series")
    drive = g("DriveType")
    if drive:
        out["drive"] = ("4x4" if re.search(r"4x4|4WD|AWD", drive, re.I)
                        else "6x4" if "6x4" in drive else "4x2" if re.search(r"4x2|2WD|RWD", drive, re.I)
                        else drive)
    fuel = g("FuelTypePrimary")
    if fuel:
        out["fuel"] = "Diesel" if "diesel" in fuel.lower() else "Gas" if "gas" in fuel.lower() else fuel
    eng = " ".join(b for b in [
        f"{float(g('DisplacementL')):.1f}L" if g("DisplacementL").replace(".", "").isdigit() else "",
        g("EngineModel"), f"V{g('EngineCylinders')}" if g("EngineConfiguration") == "V-Shaped" and g("EngineCylinders") else "",
    ] if b).strip()
    if eng:
        out["engine"] = eng
    if g("EngineHP").split(".")[0].isdigit():
        out["horsepower"] = int(g("EngineHP").split(".")[0])
    trans = " ".join(b for b in [f"{g('TransmissionSpeeds')}-speed" if g("TransmissionSpeeds") else "",
                                  g("TransmissionStyle")] if b)
    if trans:
        out["transmission"] = trans
    gv = g("GVWR")
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d{1,3}(?:,\d{3})+", gv)]
    if nums:
        out["gvwr_lbs"] = max(nums)
        out["gvwr_class"] = gv.split(":")[0].strip()
    cab = g("BodyCabType") or g("CabType")
    if cab:
        out["cab_type"] = cab
    if g("WheelBaseShort").replace(".", "").isdigit():
        out["wheelbase_in"] = float(g("WheelBaseShort"))
    if g("BrakeSystemType"):
        out["brakes"] = g("BrakeSystemType")
    return {"ok": True, "vin": vin, "fields": out,
            "note": g("ErrorText") if g("ErrorCode") not in ("", "0") else ""}


# ---------------------------------------------------------------------------
# Spec-sheet parser
# ---------------------------------------------------------------------------

def _num(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s))


def parse_spec_sheet(text: str) -> dict[str, Any]:
    """Pull the fields a window sticker or order guide states plainly. Fills
    suggestions only -- the editor never overwrites a field someone typed."""
    t = text or ""
    out: dict[str, Any] = {}

    def find(pat: str) -> re.Match[str] | None:
        return re.search(pat, t, re.I)

    m = find(r"GVWR[^\d]{0,40}(\d{1,3}(?:,\d{3})+|\d{4,6})")
    if m:
        out["gvwr_lbs"] = _num(m.group(1))
    m = find(r"(?:wheelbase|\bWB\b)[^\d]{0,20}(\d{2,3}(?:\.\d)?)")
    if m:
        out["wheelbase_in"] = float(m.group(1))
    m = find(r"(?:cab[- ]to[- ]axle|\bCA\b)[^\d]{0,20}(\d{2,3}(?:\.\d)?)")
    if m:
        out["cab_to_axle_in"] = float(m.group(1))
    m = find(r"front\s+axle[^\d]{0,40}(\d{1,3}(?:,\d{3})+|\d{4,5})")
    if m:
        out["front_axle_lbs"] = _num(m.group(1))
    m = find(r"rear\s+axle[^\d]{0,40}(\d{1,3}(?:,\d{3})+|\d{4,5})")
    if m:
        out["rear_axle_lbs"] = _num(m.group(1))
    m = find(r"(\d{3})\s*(?:hp|horsepower)\b")
    if m:
        out["horsepower"] = int(m.group(1))
    m = find(r"(\d\.\dL[^\n,;]{0,50}(?:diesel|gas|V8|V10|I6|engine))")
    if m:
        out["engine"] = m.group(1).strip()
    m = find(r"(\d{1,2}[- ]speed[^\n,;]{0,40}(?:automatic|manual|transmission|allison))")
    if m:
        out["transmission"] = m.group(1).strip()
    elif find(r"\ballison\b"):
        out["transmission"] = "Allison automatic"
    m = find(r"(\d{2,3})\s*(?:gal|gallon)")
    if m:
        out["fuel_capacity"] = f"{m.group(1)} gal"
    m = find(r"\b(\d{3}/\d{2}R\d{2}(?:\.5)?)\b")
    if m:
        out["tires"] = m.group(1).upper()
    m = find(r"\b(4x4|4x2|6x4|6x6)\b")
    if m:
        out["drive"] = m.group(1).lower()
    if find(r"\bdiesel\b"):
        out.setdefault("fuel", "Diesel")
    elif find(r"\bgas(oline)?\b"):
        out.setdefault("fuel", "Gas")
    m = find(r"(crew\s*cab|super\s*cab|extended\s*cab|regular\s*cab|standard\s*cab|day\s*cab)")
    if m:
        out["cab_type"] = m.group(1).title()
    m = find(r"(?:exterior|paint|color)[:\s]+([A-Za-z][A-Za-z \-]{2,30}?)(?:\n|,|;|$)")
    if m:
        out["color"] = m.group(1).strip()
    return out


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
DOC_EXT = {".pdf"}
PHOTO_MAX_BYTES = 40 * 1024 * 1024
VIDEO_MAX_BYTES = 750 * 1024 * 1024
DOC_MAX_BYTES = 30 * 1024 * 1024
FULL_EDGE = 2000
THUMB_EDGE = 640


def media_kind_for(filename: str) -> str | None:
    ext = Path(filename or "").suffix.lower()
    if ext in PHOTO_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    if ext in DOC_EXT:
        return "document"
    return None


def process_photo(src: Path, out_dir: Path) -> dict[str, Any]:
    """Orient per EXIF, drop all metadata (phones embed GPS), and write a
    2000px JPEG plus a 640px thumbnail. Returns file names and dimensions."""
    from PIL import Image, ImageOps
    if src.suffix.lower() in (".heic", ".heif"):
        import pillow_heif
        pillow_heif.register_heif_opener()
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").split()[-1])
            im = bg
        elif im.mode == "L":
            im = im.convert("RGB")
        w0, h0 = im.size
        stem = uuid.uuid4().hex
        full = im.copy()
        full.thumbnail((FULL_EDGE, FULL_EDGE), Image.LANCZOS)
        full.save(out_dir / f"{stem}.jpg", "JPEG", quality=86, optimize=True, progressive=True)
        thumb = im.copy()
        thumb.thumbnail((THUMB_EDGE, THUMB_EDGE), Image.LANCZOS)
        thumb.save(out_dir / f"{stem}_t.jpg", "JPEG", quality=80, optimize=True, progressive=True)
        return {"stem": stem, "width": full.size[0], "height": full.size[1],
                "source_width": w0, "source_height": h0}


def process_poster(data: bytes, out_dir: Path) -> str:
    """A video's poster frame, captured in the admin's browser and uploaded
    with the video (there is no ffmpeg on the server)."""
    from PIL import Image
    stem = uuid.uuid4().hex
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((1280, 1280), Image.LANCZOS)
        im.save(out_dir / f"{stem}_poster.jpg", "JPEG", quality=82, optimize=True)
    return f"{stem}_poster.jpg"


# ---------------------------------------------------------------------------
# Loading helpers used by both routers
# ---------------------------------------------------------------------------

async def parts_status(db: AsyncSession, listing_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Per listing: linked parts with on-hand state, prod codes, cost and age.
    Cost and age are admin-only; the public router uses prod codes alone."""
    if not listing_ids:
        return {}
    parts = (await db.execute(
        select(UnitListingPart).where(UnitListingPart.listing_id.in_(listing_ids))
        .order_by(UnitListingPart.listing_id, UnitListingPart.sort_order, UnitListingPart.id)
    )).scalars().all()
    pns = {p.part_number for p in parts}
    oh_rows = (await db.execute(select(ErpOnhand).where(ErpOnhand.part_number.in_(pns)))).scalars().all() if pns else []
    by_pn: dict[str, list[ErpOnhand]] = {}
    for r in oh_rows:
        by_pn.setdefault(r.part_number, []).append(r)

    out: dict[int, dict[str, Any]] = {lid: {"parts": [], "prod_codes": [], "on_hand": 0, "committed": 0,
                                           "gl_cost": 0.0, "max_days": None, "list_p1": 0.0}
                                      for lid in listing_ids}
    for p in parts:
        rows = by_pn.get(p.part_number, [])
        if p.serial:
            s = _norm(p.serial)
            match = [r for r in rows if r.serial and (_norm(r.serial) == s or _norm(r.serial).endswith(s) or s.endswith(_norm(r.serial)))]
        else:
            match = rows
        on = [r for r in match if (r.onhand or 0) > 0]
        # "available" drops to 0 when the unit is on a customer's order: still
        # on the lot, but sold. Such a part can't carry a listing.
        free = [r for r in on if r.available is None or r.available > 0]
        first = (free or on or rows or [None])[0]
        entry = {
            "id": p.id, "part_number": p.part_number, "serial": p.serial, "role": p.role,
            "on_hand": bool(on), "committed": bool(on) and not free,
            "prod_code": first.prod_code if first else None,
            "warehouse": first.warehouse if first else None,
            "description": first.description if first else None,
            "gl_cost": float(first.gl_cost) if first and first.gl_cost is not None else None,
            "days": first.days if first else None,
            "p1": float(first.p1) if first and first.p1 else None,
            "p2": float(first.p2) if first and first.p2 else None,
            "p3": float(first.p3) if first and first.p3 else None,
        }
        o = out[p.listing_id]
        o["parts"].append(entry)
        if entry["prod_code"]:
            o["prod_codes"].append(entry["prod_code"])
        if entry["committed"]:
            o["committed"] += 1
        if entry["on_hand"]:
            o["on_hand"] += 1
            o["gl_cost"] += entry["gl_cost"] or 0.0
            o["list_p1"] += entry["p1"] or 0.0
            if entry["days"] is not None:
                o["max_days"] = max(o["max_days"] or 0, entry["days"])
    return out


async def media_for(db: AsyncSession, listing_ids: list[int]) -> dict[int, list[UnitListingMedia]]:
    if not listing_ids:
        return {}
    rows = (await db.execute(
        select(UnitListingMedia).where(UnitListingMedia.listing_id.in_(listing_ids))
        .order_by(UnitListingMedia.listing_id, UnitListingMedia.sort_order, UnitListingMedia.id)
    )).scalars().all()
    out: dict[int, list[UnitListingMedia]] = {lid: [] for lid in listing_ids}
    for m in rows:
        out[m.listing_id].append(m)
    return out


def money(v: Any) -> float | None:
    return float(v) if v is not None else None
