"""Fulfillment service — splits a cart across warehouses and emits IMS315 CSVs.

Phase 1 routing rule (per addendum 003 + Q14):

  For each line in the cart, walk the warehouses in priority order:
    1. Spokane    (code=10, route=SPO)     — HQ, fastest path to FACS pickup
    2. Boise      (code=19, route=BOISE)
    3. Nelson Kent (code=0,  route=NELSON) — combined with Portland
    4. Portland   (code=1,  route=NELSON)  — rolls up under Nelson's file
    5. Back-order (route=BO)                — no warehouse has stock

  Allocate as much qty as the warehouse can supply, then fall through.
  Group resulting per-line allocations by routing destination and emit
  one OrderFulfillment + one IMS315 CSV file per group.

Money totals:
  - Item subtotals are summed per fulfillment.
  - Freight + handling + discount are split proportionally to item subtotal share.
  - Tax goes ONLY to the Spokane fulfillment (matches existing PHP convention —
    Spokane handles cross-border tax accounting; other warehouses ship tax-free
    on FACS's books and tax is reconciled centrally).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Cart,
    CartLine,
    Customer,
    Product,
    ProductInventory,
    Warehouse,
)
from app.services.ims315 import (
    GeneratedCSV,
    OrderHeader,
    OrderLine as Ims315Line,
    RoutingType,
    build_csv,
)
from app.services.pricing_service import resolve_for_customer


__all__ = [
    "ROUTING_PRIORITY",
    "ROUTE_TO_FACS_WAREHOUSE",
    "LineAllocation",
    "FulfillmentBucket",
    "FulfillmentPlan",
    "plan_fulfillment",
    "build_csvs_from_plan",
]


# Warehouse-code priority for line allocation.  Lower index = first to try.
ROUTING_PRIORITY: list[tuple[int, str]] = [
    (10, "SPO"),      # Spokane HQ
    (19, "BOISE"),    # Boise
    (0,  "NELSON"),   # Nelson Kent
    (1,  "NELSON"),   # Portland (rolls under NELSON)
]


# Each routing bucket maps to a FACS warehouse code (the # in the file name).
# Per addendum 003: SPO=10, BOISE=19, NELSON ships under code 10 (Spokane is
# the main FACS account that owns the NELSON cross-route), BO=10 as well.
ROUTE_TO_FACS_WAREHOUSE: dict[str, int] = {
    "SPO":    10,
    "BOISE":  19,
    "NELSON": 10,
    "BO":     10,
}


@dataclass
class LineAllocation:
    """How much of a single CartLine ships from a single warehouse."""

    cart_line_id: int
    product_id: int
    sku: str
    description: str
    quantity: int
    unit_price: Decimal
    warehouse_code: int      # the source warehouse (for our DB)
    warehouse_id: int | None  # id of the source warehouse row
    routing: str             # "SPO" | "BOISE" | "NELSON" | "BO"
    contract_id: int | None = None


@dataclass
class FulfillmentBucket:
    """A group of LineAllocations that share a routing — one CSV per bucket."""

    routing: str
    facs_warehouse_code: int
    warehouse_id: int | None    # primary warehouse for this routing (first match)
    allocations: list[LineAllocation] = field(default_factory=list)

    @property
    def item_subtotal(self) -> Decimal:
        return sum(
            (a.unit_price * a.quantity for a in self.allocations),
            start=Decimal("0"),
        )


@dataclass
class FulfillmentPlan:
    """The full plan: one bucket per routing destination."""

    buckets: list[FulfillmentBucket]
    total_item_subtotal: Decimal

    def bucket_by_routing(self, routing: str) -> FulfillmentBucket | None:
        for b in self.buckets:
            if b.routing == routing:
                return b
        return None


async def plan_fulfillment(
    db: AsyncSession,
    *,
    cart: Cart,
    customer: Customer | None,
) -> FulfillmentPlan:
    """Allocate every cart line across warehouses by priority + return a plan.

    `customer` is required for tier-aware pricing — anonymous checkout is not
    supported in Phase 1 (login is forced upstream of this call).
    """
    # Load cart lines and their products (CartLine has product_id FK only,
    # no ORM relationship — fetch products in a separate query).
    line_stmt = (
        select(CartLine)
        .where(CartLine.cart_id == cart.id)
        .order_by(CartLine.created_at)
    )
    lines = (await db.execute(line_stmt)).scalars().all()
    product_ids = [l.product_id for l in lines]
    products_by_id: dict[int, Product] = {}
    if product_ids:
        prod_rows = (await db.execute(
            select(Product).where(Product.id.in_(product_ids))
        )).scalars().all()
        products_by_id = {p.id: p for p in prod_rows}

    # Index of warehouse_code → (id, route_label, emits_own_file)
    wh_rows = (await db.execute(select(Warehouse))).scalars().all()
    wh_by_code: dict[int, Warehouse] = {w.code: w for w in wh_rows}

    # Index of (product_id, warehouse_code) → on_hand
    inv_rows = (await db.execute(select(ProductInventory))).scalars().all()
    inv_by_pw: dict[tuple[int, int], int] = {}
    for inv in inv_rows:
        wh = next((w for w in wh_rows if w.id == inv.warehouse_id), None)
        if wh is not None:
            inv_by_pw[(inv.product_id, wh.code)] = inv.on_hand

    buckets: dict[str, FulfillmentBucket] = {}

    def get_bucket(routing: str, warehouse_id: int | None) -> FulfillmentBucket:
        if routing not in buckets:
            buckets[routing] = FulfillmentBucket(
                routing=routing,
                facs_warehouse_code=ROUTE_TO_FACS_WAREHOUSE[routing],
                warehouse_id=warehouse_id,
                allocations=[],
            )
        return buckets[routing]

    total_item = Decimal("0")

    for line in lines:
        product = products_by_id.get(line.product_id)
        if product is None:
            continue

        # Tier-aware unit price (same logic as cart serializer)
        if customer:
            res = await resolve_for_customer(
                db, customer=customer, product=product, qty=line.quantity
            )
            unit_price = res.price or Decimal("0")
            contract_id = res.contract_used.contract_id if res.contract_used else None
        else:
            # Anonymous — fall back to retail price stored on ProductPrice
            from app.models import ProductPrice
            pp = (await db.execute(
                select(ProductPrice).where(ProductPrice.product_id == product.id)
            )).scalar_one_or_none()
            unit_price = (pp.retail_price if pp and pp.retail_price else Decimal("0"))
            contract_id = None

        remaining = line.quantity

        # Walk warehouses in priority order, allocating as available
        for code, route_label in ROUTING_PRIORITY:
            if remaining <= 0:
                break
            on_hand = inv_by_pw.get((product.id, code), 0)
            if on_hand <= 0:
                continue
            take = min(remaining, on_hand)
            wh = wh_by_code.get(code)
            bucket = get_bucket(route_label, wh.id if wh else None)
            bucket.allocations.append(LineAllocation(
                cart_line_id=line.id,
                product_id=product.id,
                sku=product.sku,
                description=product.name,
                quantity=take,
                unit_price=unit_price,
                warehouse_code=code,
                warehouse_id=wh.id if wh else None,
                routing=route_label,
                contract_id=contract_id,
            ))
            total_item += unit_price * take
            remaining -= take

        # Anything left → back-order
        if remaining > 0:
            bucket = get_bucket("BO", None)
            bucket.allocations.append(LineAllocation(
                cart_line_id=line.id,
                product_id=product.id,
                sku=product.sku,
                description=product.name,
                quantity=remaining,
                unit_price=unit_price,
                warehouse_code=0,
                warehouse_id=None,
                routing="BO",
                contract_id=contract_id,
            ))
            total_item += unit_price * remaining

    # Stable bucket order for downstream code: SPO → BOISE → NELSON → BO
    routing_order = ["SPO", "BOISE", "NELSON", "BO"]
    ordered = [buckets[r] for r in routing_order if r in buckets]
    return FulfillmentPlan(buckets=ordered, total_item_subtotal=total_item)


def _allocate_proportional(
    plan: FulfillmentPlan, total_amount: Decimal
) -> dict[str, Decimal]:
    """Split a total across buckets proportionally to item_subtotal.

    Last bucket absorbs any rounding remainder so the parts always sum exactly
    to `total_amount`.
    """
    if total_amount == 0 or plan.total_item_subtotal == 0:
        return {b.routing: Decimal("0") for b in plan.buckets}

    shares: dict[str, Decimal] = {}
    accumulated = Decimal("0")
    for i, bucket in enumerate(plan.buckets):
        if i == len(plan.buckets) - 1:
            shares[bucket.routing] = total_amount - accumulated
        else:
            share = (
                total_amount * bucket.item_subtotal / plan.total_item_subtotal
            ).quantize(Decimal("0.01"))
            shares[bucket.routing] = share
            accumulated += share
    return shares


def build_csvs_from_plan(
    *,
    plan: FulfillmentPlan,
    web_order_number: str,
    customer: Customer,
    order_header_kwargs: dict,
    freight_total: Decimal = Decimal("0"),
    discount_total: Decimal = Decimal("0"),  # negative number expected
    handling_total: Decimal = Decimal("0"),
    tax_total: Decimal = Decimal("0"),       # only Spokane bucket gets tax
    tax_rate_x1000: int = 0,
) -> list[tuple[str, GeneratedCSV, FulfillmentBucket, Decimal, Decimal, Decimal]]:
    """Materialize one IMS315 CSV per fulfillment bucket.

    Returns a list of (routing, csv, bucket, freight_share, discount_share,
    handling_share) so the caller can persist OrderFulfillment rows with the
    right per-warehouse money allocations.
    """
    freight_shares = _allocate_proportional(plan, freight_total)
    discount_shares = _allocate_proportional(plan, discount_total)
    handling_shares = _allocate_proportional(plan, handling_total)

    out: list[tuple[str, GeneratedCSV, FulfillmentBucket, Decimal, Decimal, Decimal]] = []

    for bucket in plan.buckets:
        ims_lines = [
            Ims315Line(
                part_number=a.sku,
                description="",  # production PHP leaves this blank
                quantity=a.quantity if bucket.routing != "BO" else 0,
                backorder_quantity=a.quantity if bucket.routing == "BO" else 0,
                unit_price=a.unit_price,
            )
            for a in bucket.allocations
        ]

        # Tax only attaches to Spokane bucket per PHP convention
        bucket_tax = tax_total if bucket.routing == "SPO" else Decimal("0")
        bucket_tax_rate = tax_rate_x1000 if bucket.routing == "SPO" else 0

        header = OrderHeader(
            order_number=web_order_number,
            customer_id=customer.customer_number,
            customer_name=customer.name,
            **order_header_kwargs,
            shipping_amount=freight_shares.get(bucket.routing, Decimal("0")),
            tax_amount=bucket_tax,
            tax_rate_x1000=bucket_tax_rate,
        )

        csv = build_csv(
            header=header,
            lines=ims_lines,
            routing=RoutingType(bucket.routing),
            warehouse_code=bucket.facs_warehouse_code,
            freight_amount=freight_shares.get(bucket.routing) or None,
            discount_amount=discount_shares.get(bucket.routing) or None,
            handling_amount=handling_shares.get(bucket.routing) or None,
        )

        out.append((
            bucket.routing,
            csv,
            bucket,
            freight_shares.get(bucket.routing, Decimal("0")),
            discount_shares.get(bucket.routing, Decimal("0")),
            handling_shares.get(bucket.routing, Decimal("0")),
        ))

    return out
