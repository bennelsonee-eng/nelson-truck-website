"""Cart router — read/modify the current user's cart.

Anonymous users get a session-token cookie identifying their cart. Logged-in
users have one cart per customer (or one per user if no customer assigned yet).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import (
    get_current_user,
    get_or_issue_session_token,
    resolve_effective_customer_id,
)
from app.models import Brand, Cart, CartLine, Customer, Product, ProductPrice, User
from app.services.pricing_service import resolve_for_customer


router = APIRouter(prefix="/api/cart", tags=["cart"])


# ---- Schemas ----

class CartLineOut(BaseModel):
    id: int
    product_id: int
    sku: str
    name: str
    brand: str
    quantity: int
    unit_price: str | None
    line_total: str | None
    map_retail: str | None = None  # Suggested Retail (P1) — front counter floor


class CartOut(BaseModel):
    id: int
    line_count: int
    item_count: int
    subtotal: str
    lines: list[CartLineOut]


class AddLineRequest(BaseModel):
    sku: str
    quantity: int = Field(default=1, ge=1, le=999)


class UpdateLineRequest(BaseModel):
    quantity: int = Field(ge=1, le=999)


# Multi-cart (A4.6) — used by the cart-picker UI
class CartSummary(BaseModel):
    id: int
    label: str | None
    line_count: int
    item_count: int
    subtotal: str
    is_consolidation_cart: bool
    is_active: bool  # True if this is the cart get/add/update endpoints would target
    created_at: datetime
    updated_at: datetime


class NewCartRequest(BaseModel):
    label: str | None = Field(default=None, max_length=100)


class PatchCartRequest(BaseModel):
    label: str | None = Field(default=None, max_length=100)
    archive: bool | None = Field(
        default=None,
        description="If true, marks the cart submitted_at=now so the picker stops surfacing it",
    )


# ---- Helpers ----

async def _get_or_create_cart(
    db: AsyncSession,
    effective_customer_id: int | None,
    session_token: str,
) -> Cart:
    """Return an open (submitted_at IS NULL) cart for the resolved owner,
    creating one if none exists. `effective_customer_id` is the result of
    `resolve_effective_customer_id` — so impersonation flows here too.

    Multi-cart support (A4.6) is groundwork-only at this layer: we pick the
    most-recently-updated open cart when several exist. The cart-picker UX
    that lets the jobber switch between carts is a separate slice.
    """
    if effective_customer_id is not None:
        stmt = (
            select(Cart)
            .where(
                Cart.customer_id == effective_customer_id,
                Cart.submitted_at.is_(None),
            )
            .order_by(desc(Cart.updated_at))
            .limit(1)
        )
        cart = (await db.execute(stmt)).scalar_one_or_none()
        if cart is None:
            cart = Cart(customer_id=effective_customer_id)
            db.add(cart)
            await db.commit()
            await db.refresh(cart)
        return cart
    # Anonymous (or logged-in user without customer_id linked yet)
    stmt = select(Cart).where(Cart.session_token == session_token)
    cart = (await db.execute(stmt)).scalar_one_or_none()
    if cart is None:
        cart = Cart(session_token=session_token)
        db.add(cart)
        await db.commit()
        await db.refresh(cart)
    return cart


async def _serialize_cart(db: AsyncSession, cart: Cart, customer: Customer | None = None) -> CartOut:
    """Build the JSON shape with product info + line totals.

    If customer is provided (logged-in with linked customer record), each line's
    unit price is resolved via the pricing engine for tier-aware pricing.
    Otherwise, anonymous retail price (ProductPrice.retail_price) is used.
    """
    # Fetch lines with product + price
    stmt = (
        select(CartLine, Product, Brand, ProductPrice)
        .where(CartLine.cart_id == cart.id)
        .join(Product, Product.id == CartLine.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .outerjoin(ProductPrice, ProductPrice.product_id == Product.id)
        .order_by(CartLine.created_at)
    )
    rows = (await db.execute(stmt)).all()

    lines: list[CartLineOut] = []
    subtotal = Decimal("0")
    item_count = 0
    for line, product, brand, price in rows:
        if customer:
            res = await resolve_for_customer(db, customer=customer, product=product, qty=line.quantity)
            unit = res.price
        else:
            unit = price.retail_price if price else None
            if unit is None and price:
                unit = price.suggested_retail_price

        line_total = (unit * line.quantity) if unit else None
        map_r = price.suggested_retail_price if price else None
        lines.append(CartLineOut(
            id=line.id,
            product_id=product.id,
            sku=product.sku,
            name=product.name,
            brand=brand.name,
            quantity=line.quantity,
            unit_price=str(unit.quantize(Decimal("0.01"))) if unit else None,
            line_total=str(line_total.quantize(Decimal("0.01"))) if line_total else None,
            map_retail=str(map_r.quantize(Decimal("0.01"))) if map_r else None,
        ))
        if line_total is not None:
            subtotal += line_total
        item_count += line.quantity

    return CartOut(
        id=cart.id,
        line_count=len(lines),
        item_count=item_count,
        subtotal=str(subtotal.quantize(Decimal("0.01"))),
        lines=lines,
    )


async def _customer_for_id(db: AsyncSession, customer_id: int | None) -> Customer | None:
    if customer_id is None:
        return None
    return (await db.execute(select(Customer).where(Customer.id == customer_id))).scalar_one_or_none()


async def _resolve_owner(
    request: Request,
    db: AsyncSession,
    user: User | None,
) -> int | None:
    """Resolve which customer_id this request should treat as the cart owner.

    Honors the admin Shop-as-Customer impersonation claim (A4.28). For an
    anonymous request OR a logged-in user without customer linkage, returns
    None — the caller falls back to the session_token cart in that case.
    """
    if user is None:
        return None
    return await resolve_effective_customer_id(db, user, request)


# ---- Routes ----

@router.get("", response_model=CartOut)
async def get_cart(
    request: Request,
    response: Response,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_token = get_or_issue_session_token(request, response)
    owner_id = await _resolve_owner(request, db, user)
    cart = await _get_or_create_cart(db, owner_id, session_token)
    customer = await _customer_for_id(db, owner_id)
    return await _serialize_cart(db, cart, customer)


@router.post("/lines", response_model=CartOut, status_code=status.HTTP_201_CREATED)
async def add_line(
    body: AddLineRequest,
    request: Request,
    response: Response,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Resolve product
    product = (
        await db.execute(select(Product).where(Product.sku == body.sku))
    ).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product not found: {body.sku}")
    # Block add-to-cart if the product is hidden from THIS viewer's channel
    # (a retail-hidden part can't be added by a retail shopper, etc.).
    from app.services.channels import (
        product_hidden_for, product_instock_only_for, total_on_hand, viewer_channel,
    )
    channel = await viewer_channel(db, user, request)
    if not product.is_for_sale or product_hidden_for(product, channel):
        raise HTTPException(status_code=400, detail="Product not available")

    # Blowout ("Hidden except in-stock") items: never sell past LIVE on-hand, so
    # nobody buys 10 of the last 1 at the clearance price (and none once sold out).
    instock_only = product_instock_only_for(product, channel)
    on_hand_cap = await total_on_hand(db, product.id) if instock_only else None
    if instock_only and on_hand_cap <= 0:
        raise HTTPException(status_code=400, detail="This clearance item is sold out.")

    session_token = get_or_issue_session_token(request, response)
    owner_id = await _resolve_owner(request, db, user)
    cart = await _get_or_create_cart(db, owner_id, session_token)

    # Upsert line — if already in cart, add to qty (capped at on-hand for blowouts).
    existing_line = (
        await db.execute(
            select(CartLine)
            .where(CartLine.cart_id == cart.id)
            .where(CartLine.product_id == product.id)
        )
    ).scalar_one_or_none()
    if existing_line:
        want = existing_line.quantity + body.quantity
        existing_line.quantity = min(999, want if on_hand_cap is None else min(want, on_hand_cap))
    else:
        want = body.quantity
        db.add(CartLine(cart_id=cart.id, product_id=product.id,
                        quantity=min(999, want if on_hand_cap is None else min(want, on_hand_cap))))
    await db.commit()
    await db.refresh(cart)
    customer = await _customer_for_id(db, owner_id)
    return await _serialize_cart(db, cart, customer)


@router.patch("/lines/{line_id}", response_model=CartOut)
async def update_line(
    line_id: int,
    body: UpdateLineRequest,
    request: Request,
    response: Response,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_token = get_or_issue_session_token(request, response)
    owner_id = await _resolve_owner(request, db, user)
    cart = await _get_or_create_cart(db, owner_id, session_token)
    line = (
        await db.execute(
            select(CartLine).where(CartLine.id == line_id).where(CartLine.cart_id == cart.id)
        )
    ).scalar_one_or_none()
    if line is None:
        raise HTTPException(status_code=404, detail="Line not in cart")
    # Cap blowout ("Hidden except in-stock") items at live on-hand.
    from app.services.channels import product_instock_only_for, total_on_hand, viewer_channel
    qty = body.quantity
    prod = (await db.execute(select(Product).where(Product.id == line.product_id))).scalar_one_or_none()
    if prod is not None and product_instock_only_for(prod, await viewer_channel(db, user, request)):
        oh = await total_on_hand(db, line.product_id)
        if oh <= 0:
            raise HTTPException(status_code=400, detail="This clearance item is sold out.")
        qty = min(qty, oh)
    line.quantity = qty
    await db.commit()
    customer = await _customer_for_id(db, owner_id)
    return await _serialize_cart(db, cart, customer)


@router.delete("/lines/{line_id}", response_model=CartOut)
async def remove_line(
    line_id: int,
    request: Request,
    response: Response,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_token = get_or_issue_session_token(request, response)
    owner_id = await _resolve_owner(request, db, user)
    cart = await _get_or_create_cart(db, owner_id, session_token)
    line = (
        await db.execute(
            select(CartLine).where(CartLine.id == line_id).where(CartLine.cart_id == cart.id)
        )
    ).scalar_one_or_none()
    if line is None:
        raise HTTPException(status_code=404, detail="Line not in cart")
    await db.delete(line)
    await db.commit()
    customer = await _customer_for_id(db, owner_id)
    return await _serialize_cart(db, cart, customer)


@router.delete("", status_code=204)
async def clear_cart(
    request: Request,
    response: Response,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_token = get_or_issue_session_token(request, response)
    owner_id = await _resolve_owner(request, db, user)
    cart = await _get_or_create_cart(db, owner_id, session_token)
    for line in cart.lines:
        await db.delete(line)
    await db.commit()
    return None


# ---- Multi-cart endpoints (A4.6) ----


async def _serialize_cart_summary(
    cart: Cart, *, is_active: bool, line_count: int, item_count: int, subtotal: Decimal
) -> CartSummary:
    return CartSummary(
        id=cart.id,
        label=cart.label,
        line_count=line_count,
        item_count=item_count,
        subtotal=str(subtotal.quantize(Decimal("0.01"))),
        is_consolidation_cart=cart.is_consolidation_cart,
        is_active=is_active,
        created_at=cart.created_at,
        updated_at=cart.updated_at,
    )


@router.get("/list", response_model=list[CartSummary])
async def list_carts(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the user's OPEN carts (submitted_at IS NULL). Most recently
    updated first; the first row is the cart get/add/update endpoints
    currently target.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    owner_id = await _resolve_owner(request, db, user)
    if owner_id is None:
        return []

    carts = (await db.execute(
        select(Cart)
        .where(Cart.customer_id == owner_id, Cart.submitted_at.is_(None))
        .order_by(desc(Cart.updated_at))
        .options(selectinload(Cart.lines))
    )).scalars().unique().all()

    # Compute line + item + subtotal per cart (anonymous-retail price path —
    # tier pricing requires the customer + pricing engine, which is overkill
    # for a picker list).
    cart_summaries: list[CartSummary] = []
    for idx, c in enumerate(carts):
        line_count = len(c.lines)
        item_count = sum(l.quantity for l in c.lines)
        subtotal = Decimal("0")
        for l in c.lines:
            if l.unit_price_snapshot is not None:
                subtotal += l.unit_price_snapshot * l.quantity
        cart_summaries.append(
            await _serialize_cart_summary(
                c,
                is_active=(idx == 0),
                line_count=line_count,
                item_count=item_count,
                subtotal=subtotal,
            )
        )
    return cart_summaries


@router.post("/new", response_model=CartSummary, status_code=status.HTTP_201_CREATED)
async def new_cart(
    body: NewCartRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new empty cart for the resolved owner. Becomes the active
    cart by virtue of being most-recently-updated.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    owner_id = await _resolve_owner(request, db, user)
    if owner_id is None:
        raise HTTPException(
            status_code=400,
            detail="Account is not linked to a customer; cannot create named carts",
        )

    cart = Cart(customer_id=owner_id, user_id=user.id, label=body.label)
    db.add(cart)
    await db.commit()
    await db.refresh(cart)
    return await _serialize_cart_summary(
        cart, is_active=True, line_count=0, item_count=0, subtotal=Decimal("0")
    )


@router.post("/{cart_id}/activate", response_model=CartSummary)
async def activate_cart(
    cart_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Make the given cart the active one. We achieve "active" via
    most-recently-updated semantics — bumping updated_at without other
    changes is enough for the cart get/add/update endpoints to pick it up.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    owner_id = await _resolve_owner(request, db, user)
    if owner_id is None:
        raise HTTPException(status_code=400, detail="Account is not linked to a customer")

    cart = (await db.execute(
        select(Cart)
        .where(
            Cart.id == cart_id,
            Cart.customer_id == owner_id,
            Cart.submitted_at.is_(None),
        )
        .options(selectinload(Cart.lines))
    )).scalar_one_or_none()
    if cart is None:
        raise HTTPException(status_code=404, detail="Cart not found or already submitted")

    # Touch updated_at — SQLAlchemy onupdate handles this on flush since we
    # actually need a write. Forcing an attribute set works:
    cart.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(cart)

    line_count = len(cart.lines)
    item_count = sum(l.quantity for l in cart.lines)
    subtotal = sum(
        ((l.unit_price_snapshot or Decimal("0")) * l.quantity for l in cart.lines),
        Decimal("0"),
    )
    return await _serialize_cart_summary(
        cart, is_active=True, line_count=line_count, item_count=item_count, subtotal=subtotal
    )


@router.patch("/{cart_id}", response_model=CartSummary)
async def patch_cart(
    cart_id: int,
    body: PatchCartRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update cart label and/or archive it (set submitted_at without
    converting to an Order). Archive is used when a jobber abandons a
    cart but doesn't want to delete its lines (e.g., quote-builder snapshot).
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    owner_id = await _resolve_owner(request, db, user)
    if owner_id is None:
        raise HTTPException(status_code=400, detail="Account is not linked to a customer")

    cart = (await db.execute(
        select(Cart)
        .where(Cart.id == cart_id, Cart.customer_id == owner_id)
        .options(selectinload(Cart.lines))
    )).scalar_one_or_none()
    if cart is None:
        raise HTTPException(status_code=404, detail="Cart not found")

    if body.label is not None:
        cart.label = body.label
    if body.archive is True:
        if cart.submitted_at is None:
            cart.submitted_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(cart)

    line_count = len(cart.lines)
    item_count = sum(l.quantity for l in cart.lines)
    subtotal = sum(
        ((l.unit_price_snapshot or Decimal("0")) * l.quantity for l in cart.lines),
        Decimal("0"),
    )
    return await _serialize_cart_summary(
        cart,
        is_active=(cart.submitted_at is None),
        line_count=line_count,
        item_count=item_count,
        subtotal=subtotal,
    )
