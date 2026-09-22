"""Orders router — checkout (cart → order + IMS315 push) and order history.

Phase 1 scope:
  * Checkout requires a logged-in user with a linked Customer record.
    Anonymous checkout is on the Phase 2 backlog (FS-013).
  * Payment type defaults to PURCHASE_ORDER. Authorize.net wiring lands once
    sandbox creds are in (FS-012, blocked on creds).
  * Order push uses local-mode FACS (writes CSVs to app/data/facs_dropbox/)
    until FTP creds are configured.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import (
    is_acting_as_impersonator,
    require_user,
    resolve_effective_customer_id,
)
from app.models import (
    Cart,
    CartLine,
    Customer,
    FACSPushStatus,
    Order,
    OrderFulfillment,
    OrderLine,
    OrderStatus,
    PaymentType,
    Product,
    User,
    Warehouse,
)
from app.services.email_service import (
    compose_order_confirmation,
    order_for_email,
    send_email,
)
from app.services.facs_pusher import PushOutcome, push_csv, push_csvs
from app.services.ims315 import GeneratedCSV
from app.services.fulfillment_service import build_csvs_from_plan, plan_fulfillment
from app.services.tax_service import estimate_sales_tax


router = APIRouter(prefix="/api/orders", tags=["orders"])


# ---- Schemas ----


class AddressIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    addr1: str = Field(min_length=1, max_length=200)
    addr2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=2, max_length=2)
    zip: str = Field(min_length=3, max_length=20)


class CheckoutRequest(BaseModel):
    shipping: AddressIn
    billing: AddressIn | None = None  # if None, mirror shipping
    contact_email: EmailStr
    contact_phone: str = Field(min_length=7, max_length=32)
    payment_type: PaymentType = PaymentType.PURCHASE_ORDER
    customer_po_number: str | None = Field(default=None, max_length=100)
    comments: str | None = Field(default=None, max_length=2000)
    required_date: date | None = None


class EstimateRequest(BaseModel):
    """Like CheckoutRequest but only enough to get freight + tax numbers back.

    Used by the frontend Order Summary panel to show real totals before the
    user clicks "Place Order".
    """

    ship_to_state: str = Field(min_length=2, max_length=2)
    ship_to_zip: str | None = Field(default=None, max_length=20)


class EstimateResponse(BaseModel):
    item_total: str
    freight_total: str
    handling_total: str
    discount_total: str
    tax_total: str
    tax_rate_x1000: int
    grand_total: str
    freight_status: str  # "ok" | "quote_required" | "free"
    freight_notes: list[str]
    tax_notes: list[str]


class FulfillmentOut(BaseModel):
    routing_type: str
    facs_warehouse_code: int
    file_name: str
    push_status: str
    item_subtotal: str
    line_count: int


class OrderLineOut(BaseModel):
    line_number: int
    sku: str
    description: str | None
    quantity: int
    backorder_quantity: int
    unit_price: str
    line_total: str
    routing: str | None
    is_freight: bool
    is_discount: bool
    is_handling: bool


class OrderOut(BaseModel):
    id: int
    web_order_number: str
    status: str
    payment_type: str
    customer_po_number: str | None
    contact_email: str | None
    contact_phone: str | None
    item_total: str
    shipping_total: str
    handling_total: str
    discount_total: str
    tax_total: str
    grand_total: str
    order_date: date | None
    required_date: date | None
    placed_at: datetime
    shipping: dict[str, Any]
    billing: dict[str, Any]
    fulfillments: list[FulfillmentOut]
    lines: list[OrderLineOut]


class OrderSummary(BaseModel):
    id: int
    web_order_number: str
    status: str
    item_count: int
    grand_total: str
    placed_at: datetime
    fulfillment_count: int


# ---- Helpers ----


async def _next_web_order_number(db: AsyncSession) -> str:
    """Generate a unique web order number: NTW + zero-padded sequence.

    Uses MAX(id)+1 over the order table — fine for Phase 1 throughput. Once
    we're posting >1 order per second we'll switch to a Postgres sequence.
    """
    last_id = (await db.execute(select(func.max(Order.id)))).scalar() or 0
    # NTW = Nelson Truck Web. The clone kept Titan's "TTW" until 2026-09-22;
    # no Nelson web orders existed yet, so nothing needed renumbering.
    return f"NTW{(last_id + 1):07d}"


def _addr_or_default(addr: AddressIn | None, fallback: AddressIn) -> AddressIn:
    return addr or fallback


def _addr_dict(prefix: str, order: Order) -> dict[str, Any]:
    """Serialize the snapshot fields back into a dict for the response."""
    return {
        "name":    getattr(order, f"{prefix}_name"),
        "company": getattr(order, f"{prefix}_company"),
        "addr1":   getattr(order, f"{prefix}_addr1"),
        "addr2":   getattr(order, f"{prefix}_addr2"),
        "city":    getattr(order, f"{prefix}_city"),
        "state":   getattr(order, f"{prefix}_state"),
        "zip":     getattr(order, f"{prefix}_zip"),
    }


# ---- Routes ----


@router.post("/checkout", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def checkout(
    body: CheckoutRequest,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Convert the user's cart into a placed order + push IMS315 to FACS.

    Honors admin Shop-as-Customer impersonation (A4.28) — when active, the
    order is placed against the impersonated customer and Order.acting_as_*
    columns record who actually clicked Submit.
    """
    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    if effective_customer_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Your account is not linked to a Nelson customer record. "
                "Visit /account to link your customer number, or contact sales@nelsontruck.com."
            ),
        )

    customer = (await db.execute(
        select(Customer).where(Customer.id == effective_customer_id)
    )).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=400, detail="Linked customer no longer exists")

    cart = (await db.execute(
        select(Cart)
        .where(Cart.customer_id == customer.id, Cart.submitted_at.is_(None))
        .order_by(desc(Cart.updated_at))
        .limit(1)
    )).scalar_one_or_none()
    if cart is None:
        # Maybe they have an anonymous-token cart that wasn't merged yet
        raise HTTPException(status_code=400, detail="No cart found")

    # Reload lines explicitly to be safe
    line_rows = (await db.execute(
        select(CartLine).where(CartLine.cart_id == cart.id)
    )).scalars().all()
    if not line_rows:
        raise HTTPException(status_code=400, detail="Cart is empty")

    # Blowout ("Hidden except in-stock") lines: re-validate against LIVE on-hand
    # so a race (two shoppers grabbing the last unit) or a stale cart can't check
    # out more than exists. No backorder for these.
    from app.models import Product
    from app.services.channels import on_hand_map, product_instock_only_for, viewer_channel
    _channel = await viewer_channel(db, user, request)
    _lpids = [ln.product_id for ln in line_rows if ln.product_id]
    _prods = {p.id: p for p in (await db.execute(
        select(Product).where(Product.id.in_(_lpids))
    )).scalars().all()} if _lpids else {}
    _oh = await on_hand_map(db, _lpids)
    _short = [
        # Nelson's CartLine has no sku column, so take it from the joined Product.
        f"{p.sku}: {_oh.get(ln.product_id, 0)} in stock (cart has {ln.quantity})"
        for ln in line_rows
        if (p := _prods.get(ln.product_id)) is not None
        and product_instock_only_for(p, _channel)
        and ln.quantity > _oh.get(ln.product_id, 0)
    ]
    if _short:
        raise HTTPException(
            status_code=409,
            detail="Some clearance items are no longer available in the requested quantity: "
                   + "; ".join(_short) + ". Please adjust your cart and try again.",
        )

    plan = await plan_fulfillment(db, cart=cart, customer=customer)
    if not plan.buckets:
        raise HTTPException(status_code=500, detail="Fulfillment planning produced no buckets")

    billing = _addr_or_default(body.billing, body.shipping)

    item_total = plan.total_item_subtotal

    # ---- Freight: NOT quoted on the web ----
    # Freight is applied as a straight fee in the existing ERP (FACS) when the
    # order is processed, so the web order carries $0 freight and the ERP adds
    # the actual charge to the invoice. (Per Ben, 2026-06-05 — no web freight
    # quoting for now; B2B settles by PO / net terms.)
    freight_total = Decimal("0")

    # ---- Tax: WA destination flat rate (Phase 1) ----
    discount_total = Decimal("0")
    handling_total = Decimal("0")
    taxable_subtotal = item_total + freight_total + handling_total + discount_total
    tax_est = estimate_sales_tax(
        taxable_subtotal=taxable_subtotal,
        ship_to_state=body.shipping.state,
        is_tax_exempt=customer.is_tax_exempt,
    )
    tax_total = tax_est.amount
    tax_rate_x1000 = tax_est.rate_x1000

    grand_total = item_total + freight_total + handling_total + tax_total + discount_total

    web_order_number = await _next_web_order_number(db)
    order_date = date.today()
    required_date = body.required_date or (order_date + timedelta(days=2))

    final_comments = (body.comments or "").strip() or None

    impersonating = is_acting_as_impersonator(user, request)

    order = Order(
        web_order_number=web_order_number,
        customer_id=customer.id,
        status=OrderStatus.PLACED,
        payment_type=body.payment_type,
        customer_po_number=body.customer_po_number,
        billing_name=billing.name,
        billing_company=billing.company,
        billing_addr1=billing.addr1,
        billing_addr2=billing.addr2,
        billing_city=billing.city,
        billing_state=billing.state.upper(),
        billing_zip=billing.zip,
        shipping_name=body.shipping.name,
        shipping_company=body.shipping.company,
        shipping_addr1=body.shipping.addr1,
        shipping_addr2=body.shipping.addr2,
        shipping_city=body.shipping.city,
        shipping_state=body.shipping.state.upper(),
        shipping_zip=body.shipping.zip,
        contact_email=body.contact_email,
        contact_phone=body.contact_phone,
        sales_rep_code=customer.sales_rep_code,
        item_total_usd=item_total,
        shipping_total_usd=freight_total,
        handling_total_usd=handling_total,
        discount_total_usd=discount_total,
        tax_total_usd=tax_total,
        tax_rate_x1000=tax_rate_x1000,
        grand_total_usd=grand_total,
        order_date=order_date,
        required_date=required_date,
        comments=final_comments,
        # Audit (A4.28 + Phase 1 jobber columns)
        submitted_by_user_id=user.id,
        acting_as_customer_id=customer.id if impersonating else None,
        acting_as_staff_user_id=user.id if impersonating else None,
        source_cart_id=cart.id,
    )
    db.add(order)
    await db.flush()  # populate order.id without committing

    # Freeze the cart so the active-cart picker stops surfacing it.
    cart.submitted_at = datetime.now(timezone.utc)

    # ---- Persist OrderLine rows from the plan ----
    line_no = 0
    for bucket in plan.buckets:
        for alloc in bucket.allocations:
            line_no += 1
            db.add(OrderLine(
                order_id=order.id,
                line_number=line_no,
                product_id=alloc.product_id,
                sku=alloc.sku,
                description=alloc.description,
                quantity=alloc.quantity if bucket.routing != "BO" else 0,
                backorder_quantity=alloc.quantity if bucket.routing == "BO" else 0,
                unit_price_usd=alloc.unit_price,
                warehouse_id=alloc.warehouse_id,
                contract_id=alloc.contract_id,
                is_freight=False,
                is_discount=False,
                is_handling=False,
            ))

    # ---- Build IMS315 CSVs ----
    pay_type_str = "CASH" if body.payment_type == PaymentType.CREDIT_CARD else "PO"

    header_kwargs = dict(
        addr1=billing.addr1,
        addr2=billing.addr2 or "",
        city=billing.city,
        state=billing.state.upper(),
        zip=billing.zip,
        email=body.contact_email,
        contact_name=billing.name,
        phone=body.contact_phone,
        fax="0",
        ship_addr1=body.shipping.addr1,
        ship_addr2=body.shipping.addr2 or "",
        ship_city=body.shipping.city,
        ship_state=body.shipping.state.upper(),
        ship_zip=body.shipping.zip,
        customer_po_number=body.customer_po_number or "",
        comments="WEB ORDER",
        payment_type=pay_type_str,
        sales_rep=customer.sales_rep_code or "",
        order_date=order_date,
        required_date=required_date,
    )

    artifacts = build_csvs_from_plan(
        plan=plan,
        web_order_number=web_order_number,
        customer=customer,
        order_header_kwargs=header_kwargs,
        freight_total=freight_total,
        discount_total=discount_total,
        handling_total=handling_total,
        tax_total=tax_total,
        tax_rate_x1000=tax_rate_x1000,
    )

    # ---- Persist OrderFulfillment rows (CSV stored for audit/replay) ----
    fulfillment_rows: list[OrderFulfillment] = []
    for routing, csv, bucket, freight_share, discount_share, handling_share in artifacts:
        f = OrderFulfillment(
            order_id=order.id,
            warehouse_id=bucket.warehouse_id,
            file_name=csv.filename,
            routing_type=routing,
            facs_warehouse_code=bucket.facs_warehouse_code,
            item_subtotal_usd=bucket.item_subtotal,
            shipping_share_usd=freight_share,
            handling_share_usd=handling_share,
            discount_share_usd=discount_share,
            push_status=FACSPushStatus.PENDING,
            csv_content=csv.content,
        )
        db.add(f)
        fulfillment_rows.append(f)

    # Empty the cart now (before push so even if push fails, cart is clean)
    for cl in line_rows:
        await db.delete(cl)

    await db.flush()

    # ---- Push CSVs to FACS (local-mode in dev) ----
    push_results = await push_csvs([csv for _, csv, _, _, _, _ in artifacts])
    by_filename = {r.filename: r for r in push_results}
    push_ok = True
    now = datetime.now(timezone.utc)
    for f in fulfillment_rows:
        r = by_filename.get(f.file_name)
        if r is None:
            f.push_status = FACSPushStatus.FAILED
            f.last_error = "no result returned from pusher"
            push_ok = False
            continue
        if r.outcome in (PushOutcome.OK, PushOutcome.LOCAL_DROPPED):
            f.push_status = FACSPushStatus.PUSHED
            f.pushed_at = now
            f.push_attempts = 1
        else:
            f.push_status = FACSPushStatus.FAILED
            f.last_error = r.error or "unknown"
            f.push_attempts = 1
            push_ok = False

    if push_ok:
        order.status = OrderStatus.PUSHED_TO_FACS

    await db.commit()
    await db.refresh(order)

    # ---- Send order confirmation email (best-effort; never fails the order) ----
    try:
        ship_to_str = ", ".join(filter(None, [
            body.shipping.name, body.shipping.company,
            body.shipping.addr1, body.shipping.addr2,
            f"{body.shipping.city}, {body.shipping.state.upper()} {body.shipping.zip}",
        ]))
        # Re-fetch lines + fulfillments with the relationship loaded
        order_full = (await db.execute(
            select(Order)
            .where(Order.id == order.id)
            .options(selectinload(Order.lines), selectinload(Order.fulfillments))
        )).scalar_one()
        email_data = order_for_email(order_full, order_full.lines, order_full.fulfillments, ship_to_str)
        composed = compose_order_confirmation(email_data)
        send_email(composed)
    except Exception:
        # We log inside send_email; here we just swallow so the order still returns 201.
        pass

    # ---- Build response ----
    return await _serialize_order(db, order)


@router.post("/estimate", response_model=EstimateResponse)
async def estimate_order(
    body: EstimateRequest,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute live freight + tax + grand total against the user's current cart.

    Used by the checkout page summary panel.  Doesn't mutate anything.
    Honors admin Shop-as-Customer impersonation (A4.28).
    """
    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    if effective_customer_id is None:
        raise HTTPException(status_code=400, detail="Account is not linked to a Nelson customer")
    customer = (await db.execute(
        select(Customer).where(Customer.id == effective_customer_id)
    )).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=400, detail="Linked customer no longer exists")
    cart = (await db.execute(
        select(Cart)
        .where(Cart.customer_id == customer.id, Cart.submitted_at.is_(None))
        .order_by(desc(Cart.updated_at))
        .limit(1)
    )).scalar_one_or_none()
    if cart is None:
        raise HTTPException(status_code=400, detail="No cart found")

    plan = await plan_fulfillment(db, cart=cart, customer=customer)
    item_total = plan.total_item_subtotal

    # ---- Freight: NOT quoted on the web ----
    # Freight is a straight fee applied in the existing ERP (FACS); the web
    # never quotes it. (Per Ben, 2026-06-05.)
    freight_total = Decimal("0")
    handling_total = Decimal("0")
    discount_total = Decimal("0")
    tax_est = estimate_sales_tax(
        taxable_subtotal=item_total + freight_total + handling_total + discount_total,
        ship_to_state=body.ship_to_state,
        is_tax_exempt=customer.is_tax_exempt,
    )
    grand_total = item_total + freight_total + handling_total + tax_est.amount + discount_total

    def _f(d: Decimal) -> str:
        return str(d.quantize(Decimal("0.01")))

    return EstimateResponse(
        item_total=_f(item_total),
        freight_total=_f(freight_total),
        handling_total=_f(handling_total),
        discount_total=_f(discount_total),
        tax_total=_f(tax_est.amount),
        tax_rate_x1000=tax_est.rate_x1000,
        grand_total=_f(grand_total),
        freight_status="billed_separately",
        freight_notes=["Freight is added by Nelson as a flat fee on your invoice."],
        tax_notes=tax_est.notes,
    )


@router.get("", response_model=list[OrderSummary])
async def list_orders(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    if effective_customer_id is None:
        return []
    stmt = (
        select(Order)
        .where(Order.customer_id == effective_customer_id)
        .order_by(desc(Order.id))
        .limit(200)
        .options(selectinload(Order.lines), selectinload(Order.fulfillments))
    )
    rows = (await db.execute(stmt)).scalars().all()
    out: list[OrderSummary] = []
    for o in rows:
        out.append(OrderSummary(
            id=o.id,
            web_order_number=o.web_order_number,
            status=o.status.value if hasattr(o.status, "value") else str(o.status),
            item_count=sum(l.quantity + l.backorder_quantity for l in o.lines if not (l.is_freight or l.is_discount or l.is_handling)),
            grand_total=str(o.grand_total_usd.quantize(Decimal("0.01"))),
            placed_at=o.created_at,
            fulfillment_count=len(o.fulfillments),
        ))
    return out


class ReplayResult(BaseModel):
    fulfillment_id: int
    file_name: str
    routing_type: str
    push_status: str
    push_attempts: int
    last_error: str | None


class ReorderResult(BaseModel):
    cart_id: int
    lines_added: int
    lines_skipped: int
    skipped_reasons: list[str]


@router.post("/{web_order_number}/reorder", response_model=ReorderResult)
async def reorder(
    web_order_number: str,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-add every line from a past order back into the user's current cart.

    Hidden / not-for-sale / missing products are skipped (with reasons returned).
    Quantities collapse: if the cart already has the product, qty += old qty
    (capped at 999 to match AddLineRequest validation). Honors Shop-as-Customer.
    """
    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    if effective_customer_id is None:
        raise HTTPException(status_code=400, detail="Account is not linked to a Nelson customer")

    order = (await db.execute(
        select(Order).where(Order.web_order_number == web_order_number)
        .options(selectinload(Order.lines))
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order not found: {web_order_number}")
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if effective_customer_id != order.customer_id and role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to reorder this order")

    cart = (await db.execute(
        select(Cart)
        .where(Cart.customer_id == effective_customer_id, Cart.submitted_at.is_(None))
        .order_by(desc(Cart.updated_at))
        .limit(1)
    )).scalar_one_or_none()
    if cart is None:
        cart = Cart(customer_id=effective_customer_id)
        db.add(cart)
        await db.flush()

    skipped: list[str] = []
    from app.services.channels import product_hidden_for, viewer_channel
    channel = await viewer_channel(db, user, request)
    added = 0
    for line in order.lines:
        if line.is_freight or line.is_discount or line.is_handling:
            continue
        qty = line.quantity + line.backorder_quantity
        if qty <= 0:
            continue
        product = (await db.execute(
            select(Product).where(Product.sku == line.sku)
        )).scalar_one_or_none()
        if product is None:
            skipped.append(f"{line.sku}: no longer in catalog")
            continue
        if product_hidden_for(product, channel) or not product.is_for_sale:
            skipped.append(f"{line.sku}: discontinued or hidden")
            continue
        existing = (await db.execute(
            select(CartLine).where(CartLine.cart_id == cart.id, CartLine.product_id == product.id)
        )).scalar_one_or_none()
        if existing:
            existing.quantity = min(999, existing.quantity + qty)
        else:
            db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=min(999, qty)))
        added += 1

    await db.commit()
    return ReorderResult(
        cart_id=cart.id, lines_added=added, lines_skipped=len(skipped),
        skipped_reasons=skipped,
    )


@router.post("/{web_order_number}/replay/{routing_type}", response_model=ReplayResult)
async def replay_facs_push(
    web_order_number: str,
    routing_type: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-push a stored IMS315 CSV to FACS.

    Admin-only.  Used when a FACS file got lost in transit, the FTP was down,
    or we need to regenerate after a cleanup.  Replays the exact CSV that was
    persisted at order time — no recomputation.
    """
    # Admin gate (or order-owner if you want self-service later)
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required for FACS replay")

    routing_norm = routing_type.upper()

    order = (await db.execute(
        select(Order)
        .where(Order.web_order_number == web_order_number)
        .options(selectinload(Order.fulfillments))
    )).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order not found: {web_order_number}")

    fulfillment = next((f for f in order.fulfillments if f.routing_type == routing_norm), None)
    if fulfillment is None:
        raise HTTPException(
            status_code=404,
            detail=f"No {routing_norm} fulfillment for order {web_order_number}",
        )
    if not fulfillment.csv_content:
        raise HTTPException(
            status_code=400,
            detail=f"Fulfillment {fulfillment.id} has no stored CSV — cannot replay",
        )

    csv = GeneratedCSV(filename=fulfillment.file_name, content=fulfillment.csv_content)
    result = await push_csv(csv)

    fulfillment.push_attempts = (fulfillment.push_attempts or 0) + 1
    if result.outcome in (PushOutcome.OK, PushOutcome.LOCAL_DROPPED):
        fulfillment.push_status = FACSPushStatus.PUSHED
        fulfillment.pushed_at = datetime.now(timezone.utc)
        fulfillment.last_error = None
        # Reset back to PUSHED_TO_FACS on the order if it had been failed
        if order.status == OrderStatus.PLACED:
            order.status = OrderStatus.PUSHED_TO_FACS
    else:
        fulfillment.push_status = FACSPushStatus.FAILED
        fulfillment.last_error = result.error or "unknown"

    await db.commit()
    await db.refresh(fulfillment)

    return ReplayResult(
        fulfillment_id=fulfillment.id,
        file_name=fulfillment.file_name,
        routing_type=fulfillment.routing_type,
        push_status=fulfillment.push_status.value if hasattr(fulfillment.push_status, "value") else str(fulfillment.push_status),
        push_attempts=fulfillment.push_attempts,
        last_error=fulfillment.last_error,
    )


@router.get("/{web_order_number}", response_model=OrderOut)
async def get_order(
    web_order_number: str,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Order)
        .where(Order.web_order_number == web_order_number)
        .options(selectinload(Order.lines), selectinload(Order.fulfillments))
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order not found: {web_order_number}")
    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if effective_customer_id != order.customer_id and role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to view this order")
    return await _serialize_order(db, order)


# ---- Serialization ----


async def _serialize_order(db: AsyncSession, order: Order) -> OrderOut:
    # Make sure relationships are loaded
    if not hasattr(order, "_sa_instance_state") or "lines" not in order.__dict__:
        # Re-fetch with relationships
        order = (await db.execute(
            select(Order)
            .where(Order.id == order.id)
            .options(selectinload(Order.lines), selectinload(Order.fulfillments))
        )).scalar_one()

    # Index warehouse for routing lookup on lines
    wh_rows = (await db.execute(select(Warehouse))).scalars().all()
    wh_by_id: dict[int, Warehouse] = {w.id: w for w in wh_rows}

    def _routing_for_line(l: OrderLine) -> str | None:
        if l.warehouse_id is None:
            return "BO" if l.backorder_quantity > 0 else None
        wh = wh_by_id.get(l.warehouse_id)
        return wh.facs_route_label if wh else None

    lines_out = [
        OrderLineOut(
            line_number=l.line_number,
            sku=l.sku,
            description=l.description,
            quantity=l.quantity,
            backorder_quantity=l.backorder_quantity,
            unit_price=str(l.unit_price_usd.quantize(Decimal("0.01"))),
            line_total=str((l.unit_price_usd * (l.quantity + l.backorder_quantity)).quantize(Decimal("0.01"))),
            routing=_routing_for_line(l),
            is_freight=l.is_freight,
            is_discount=l.is_discount,
            is_handling=l.is_handling,
        )
        for l in sorted(order.lines, key=lambda x: x.line_number)
    ]

    fulfillments_out = [
        FulfillmentOut(
            routing_type=f.routing_type,
            facs_warehouse_code=f.facs_warehouse_code,
            file_name=f.file_name,
            push_status=f.push_status.value if hasattr(f.push_status, "value") else str(f.push_status),
            item_subtotal=str(f.item_subtotal_usd.quantize(Decimal("0.01"))),
            line_count=sum(1 for l in order.lines if (
                (f.warehouse_id is not None and l.warehouse_id == f.warehouse_id)
                or (f.routing_type == "BO" and l.backorder_quantity > 0)
            )),
        )
        for f in sorted(order.fulfillments, key=lambda x: x.routing_type)
    ]

    return OrderOut(
        id=order.id,
        web_order_number=order.web_order_number,
        status=order.status.value if hasattr(order.status, "value") else str(order.status),
        payment_type=order.payment_type.value if hasattr(order.payment_type, "value") else str(order.payment_type),
        customer_po_number=order.customer_po_number,
        contact_email=order.contact_email,
        contact_phone=order.contact_phone,
        item_total=str(order.item_total_usd.quantize(Decimal("0.01"))),
        shipping_total=str(order.shipping_total_usd.quantize(Decimal("0.01"))),
        handling_total=str(order.handling_total_usd.quantize(Decimal("0.01"))),
        discount_total=str(order.discount_total_usd.quantize(Decimal("0.01"))),
        tax_total=str(order.tax_total_usd.quantize(Decimal("0.01"))),
        grand_total=str(order.grand_total_usd.quantize(Decimal("0.01"))),
        order_date=order.order_date,
        required_date=order.required_date,
        placed_at=order.created_at,
        shipping=_addr_dict("shipping", order),
        billing=_addr_dict("billing", order),
        fulfillments=fulfillments_out,
        lines=lines_out,
    )
