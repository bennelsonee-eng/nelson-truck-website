"""IMS315 CSV writer — produces FACS-compliant order CSVs.

Generates the file format Spokane Computer's FACS system expects (per
addendum 002 + 003, reverse-engineered from production PHP and 60 real samples).

Filename pattern: `ORDERS_TITAN_{TYPE}_{ORDER#}_{WAREHOUSE#}.CSV`
  TYPE: SPO | BOISE | NELSON | BO
  WAREHOUSE#: 10 (Spokane) | 19 (Boise)

Multi-warehouse orders produce multiple files — one per OrderFulfillment.
Freight, discount, handling are split proportionally across fulfillments
(matches existing PHP behavior).

Field formatting conventions (from PHP analysis):
  - Comma-delimited, NO quoting (commas stripped from text fields)
  - Text fields uppercased
  - Phone/fax fields have a leading space: ` 360-373-3101`, ` 0`
  - Currency in unit_price column: `$149.99` (with $)
  - Empty fields = literal empty between commas (no quoting)
  - Spokane file passes tax info; other warehouses pass zeros
  - Required Date = Order Date + 2 days (admin-configurable in Phase 2)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Iterable


__all__ = [
    "RoutingType",
    "ShipVia",
    "OrderHeader",
    "OrderLine",
    "GeneratedCSV",
    "build_csv",
    "filename_for",
]


class RoutingType(str, Enum):
    SPO = "SPO"          # Spokane fulfillment
    BOISE = "BOISE"      # Boise fulfillment
    NELSON = "NELSON"    # Nelson Truck Equipment cross-routing (Kent + Portland)
    BO = "BO"            # Back-order (no warehouse has stock)


class ShipVia(str, Enum):
    """Per-warehouse default Ship Via labels (per PHP ship_via_default mapping)."""

    SPO = "PPD_DATED"     # placeholder; format computed at runtime as `MM/DD PPD`
    BOISE = "PPD_DATED"   # same
    NELSON = "PAL"
    BO = "BACK ORDERED"


@dataclass(frozen=True)
class OrderLine:
    """Detail line (Type 2 record)."""

    part_number: str           # SKU or synthetic (FREIGHT/DISCOUNT/HANDLING)
    description: str = ""      # blank in real production data; FACS looks up itself
    quantity: int = 1
    backorder_quantity: int = 0
    unit_price: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class OrderHeader:
    """Order header (Type 1 record). Plus money totals and routing context."""

    order_number: str
    customer_id: str           # FACS customer number; "106415" for anonymous retail
    customer_name: str         # company name (uppercased; commas stripped before write)
    addr1: str
    addr2: str
    city: str
    state: str
    zip: str
    email: str
    contact_name: str
    phone: str
    fax: str = "0"
    ship_addr1: str = ""
    ship_addr2: str = ""
    ship_city: str = ""
    ship_state: str = ""
    ship_zip: str = ""
    customer_po_number: str = ""
    comments: str = "WEB ORDER"
    payment_type: str = "PO"   # "PO" for A/R, "CASH" for credit card
    sales_rep: str = ""

    # Money totals (per-warehouse — split proportionally before writing)
    item_total: Decimal = Decimal("0")     # always 0 in real PHP — FACS computes
    shipping_amount: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")     # only Spokane sends tax; others = 0
    tax_rate_x1000: int = 0
    charge_amount: Decimal = Decimal("0")  # always 0 — FACS computes total

    order_date: date | None = None
    required_date: date | None = None


@dataclass(frozen=True)
class GeneratedCSV:
    """Output: filename + content."""

    filename: str
    content: str  # CRLF line endings (FACS expects \r\n per PHP convention)


# --- Field sanitization ----------------------------------------------------


def _scrub(s: str) -> str:
    """Strip commas (matches PHP str_replace), uppercase. Used on address fields."""
    if s is None:
        return ""
    return str(s).replace(",", "").upper().strip()


def _scrub_keep_case(s: str) -> str:
    """Strip commas only (preserves case — for email)."""
    if s is None:
        return ""
    return str(s).replace(",", "").strip()


def _money(d: Decimal | int | float | str) -> str:
    """Format a Decimal as `$XX.XX` (PHP-style)."""
    if d is None:
        return "$0.00"
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    sign = "-" if d < 0 else ""
    abs_d = abs(d).quantize(Decimal("0.01"))
    return f"${sign}{abs_d}"


def _date(d: date | None) -> str:
    if d is None:
        return ""
    return d.strftime("%m/%d/%Y")


# --- Builder ---------------------------------------------------------------


def filename_for(routing: RoutingType, order_number: str, warehouse_code: int) -> str:
    """Build IMS315 filename per addendum 003 convention."""
    return f"ORDERS_TITAN_{routing.value}_{order_number}_{warehouse_code}.CSV"


def _ship_via_for(routing: RoutingType, order_date: date | None) -> str:
    """SPO/BOISE use date+PPD (e.g., '04/25 PPD'); NELSON='PAL'; BO='BACK ORDERED'."""
    if routing in (RoutingType.SPO, RoutingType.BOISE):
        d = order_date or date.today()
        return f"{d.strftime('%m/%d')} PPD"
    if routing == RoutingType.NELSON:
        return "PAL"
    if routing == RoutingType.BO:
        return "BACK ORDERED"
    return ""


def _format_header_row(h: OrderHeader, ship_via: str) -> str:
    """Type 1 (order header) — 31 fields per the IMS315 spec."""
    fields = [
        h.order_number,                             # 1. Order #
        "1",                                        # 2. Record Type
        h.customer_id,                              # 3. Customer ID
        _scrub(h.customer_name),                    # 4. Customer Name
        _scrub(h.addr1),                            # 5. Address 1
        _scrub(h.addr2),                            # 6. Address 2
        _scrub(h.city),                             # 7. City
        _scrub(h.state),                            # 8. State
        _scrub(h.zip),                              # 9. Zip
        _scrub_keep_case(h.email),                  # 10. Email
        _scrub(h.contact_name),                     # 11. Contact Name
        f" {h.phone}" if h.phone else " ",          # 12. Phone (leading space, PHP convention)
        f" {h.fax}" if h.fax else " 0",             # 13. Fax (leading space)
        _scrub(h.ship_addr1 or h.addr1),            # 14. Ship Address 1
        _scrub(h.ship_addr2 or h.addr2),            # 15. Ship Address 2
        _scrub(h.ship_city or h.city),              # 16. Ship City
        _scrub(h.ship_state or h.state),            # 17. Ship State
        _scrub(h.ship_zip or h.zip),                # 18. Ship Zip
        _scrub(h.customer_po_number),               # 19. Customer PO Number
        ship_via,                                   # 20. Ship Via
        h.comments,                                 # 21. Comments
        h.payment_type,                             # 22. Payment Type
        # Money block: PHP sends 0,0,$tax,$tax_rate,0 for Spokane; all-zero otherwise
        str(int(h.item_total) if h.item_total == 0 else h.item_total),  # 23. Item Total
        str(int(h.shipping_amount) if h.shipping_amount == 0 else h.shipping_amount),  # 24. Shipping
        _money(h.tax_amount) if h.tax_amount > 0 else "0",              # 25. Tax Amount (with $ if non-zero)
        str(h.tax_rate_x1000),                                          # 26. Tax Code (PHP uses tax_rate_x1000)
        str(int(h.charge_amount) if h.charge_amount == 0 else h.charge_amount),  # 27. Charge Amount
        _date(h.order_date or date.today()),       # 28. Order Date
        _date(h.required_date or (date.today() + timedelta(days=2))),  # 29. Required Date
        h.order_number,                             # 30. Reference Number (= order #)
        h.sales_rep,                                # 31. Sales Rep
    ]
    return ",".join(fields)


def _format_detail_row(order_number: str, line: OrderLine) -> str:
    """Type 2 (detail) — 7 fields."""
    fields = [
        order_number,
        "2",
        line.part_number,
        line.description,                           # blank in production
        str(line.quantity),
        str(line.backorder_quantity),
        _money(line.unit_price),
    ]
    return ",".join(fields)


def build_csv(
    *,
    header: OrderHeader,
    lines: Iterable[OrderLine],
    routing: RoutingType,
    warehouse_code: int,
    freight_amount: Decimal | None = None,
    discount_amount: Decimal | None = None,  # negative number expected (e.g., Decimal("-14.99"))
    handling_amount: Decimal | None = None,
) -> GeneratedCSV:
    """Build a single IMS315 CSV file (header + lines + optional FREIGHT/DISCOUNT/HANDLING).

    Caller is responsible for already having allocated the proportional shares
    of freight/discount/handling for THIS warehouse fulfillment (per the
    multi-warehouse split logic in the fulfillment service).
    """
    ship_via = _ship_via_for(routing, header.order_date)

    rows = [_format_header_row(header, ship_via)]
    for line in lines:
        rows.append(_format_detail_row(header.order_number, line))

    # Synthetic special-case lines
    if freight_amount is not None and freight_amount != 0:
        rows.append(_format_detail_row(
            header.order_number,
            OrderLine(part_number="FREIGHT", description="", quantity=1, unit_price=freight_amount),
        ))
    if discount_amount is not None and discount_amount != 0:
        rows.append(_format_detail_row(
            header.order_number,
            OrderLine(part_number="DISCOUNT", description="", quantity=1, unit_price=discount_amount),
        ))
    if handling_amount is not None and handling_amount != 0:
        rows.append(_format_detail_row(
            header.order_number,
            OrderLine(part_number="HANDLING", description="", quantity=1, unit_price=handling_amount),
        ))

    content = "\r\n".join(rows) + "\r\n"
    filename = filename_for(routing, header.order_number, warehouse_code)
    return GeneratedCSV(filename=filename, content=content)
