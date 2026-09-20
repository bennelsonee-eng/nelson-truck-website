"""Integration tests for the customer-signals + reorder endpoints."""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from tests.fake_request import anon_request
from app.models import (
    Brand,
    Cart,
    CartLine,
    Customer,
    CustomerTier,
    LostSale,
    LostSaleReason,
    PriceMatchRequest,
    PriceMatchStatus,
    Product,
    ProductInventory,
    ProductPrice,
    User,
    UserRole,
    Warehouse,
)
from app.routers import orders as orders_module
from app.routers.orders import (
    AddressIn,
    CheckoutRequest,
    checkout,
    reorder,
)
from app.routers.signals import LostSaleIn, PriceMatchIn, record_lost_sale, record_price_match
from app.services.auth_service import hash_password
from app.services.facs_pusher import PushOutcome, PushResult


@pytest_asyncio.fixture
async def signals_world(clean_db):
    db = clean_db
    brand = Brand(name="SigBrand", slug="sigbrand")
    db.add(brand); await db.flush()
    product = Product(sku="SIG-1", brand_id=brand.id, prod_code="SIG", name="Signal Test")
    db.add(product); await db.flush()
    cust = Customer(customer_number="SIG-9", name="Signal Co", tier=CustomerTier.JOBBER)
    db.add(cust); await db.flush()
    user = User(
        email="signal@example.com", password_hash=hash_password("p"),
        role=UserRole.CUSTOMER, customer_id=cust.id, is_active=True, is_verified=True,
    )
    db.add(user)
    await db.commit()
    return db, user, cust, product


# =========================================================================
# /api/signals/lost-sale
# =========================================================================


class TestLostSale:
    @pytest.mark.asyncio
    async def test_records_lost_sale_for_logged_in_user(self, signals_world):
        from fastapi import Request
        db, user, cust, product = signals_world

        class FakeRequest:
            cookies = {"titan_session": "anon-token"}

        out = await record_lost_sale(
            body=LostSaleIn(sku="SIG-1", reason=LostSaleReason.PRICE_TOO_HIGH, note="too pricey"),
            request=FakeRequest(),
            user=user, db=db,
        )
        assert out.sku == "SIG-1"
        assert out.reason == "price_too_high"

        rec = (await db.execute(select(LostSale))).scalars().first()
        assert rec is not None
        assert rec.user_id == user.id
        assert rec.customer_id == cust.id
        assert rec.session_token == "anon-token"
        assert rec.note == "too pricey"

    @pytest.mark.asyncio
    async def test_anonymous_lost_sale_records_session_only(self, signals_world):
        db, _, _, _ = signals_world

        class FakeRequest:
            cookies = {"titan_session": "anon-only-token"}

        out = await record_lost_sale(
            body=LostSaleIn(sku="SIG-1", reason=LostSaleReason.OUT_OF_STOCK, note=None),
            request=FakeRequest(), user=None, db=db,
        )
        assert out.reason == "out_of_stock"
        rec = (await db.execute(select(LostSale))).scalars().first()
        assert rec.user_id is None
        assert rec.customer_id is None
        assert rec.session_token == "anon-only-token"

    @pytest.mark.asyncio
    async def test_unknown_sku_still_records_with_null_product(self, signals_world):
        db, user, _, _ = signals_world

        class FakeRequest:
            cookies = {}

        out = await record_lost_sale(
            body=LostSaleIn(sku="NOT-A-SKU", reason=LostSaleReason.OTHER),
            request=FakeRequest(), user=user, db=db,
        )
        rec = (await db.execute(select(LostSale))).scalars().first()
        assert rec.product_id is None
        assert rec.sku == "NOT-A-SKU"


# =========================================================================
# /api/signals/price-match
# =========================================================================


class TestPriceMatch:
    @pytest.mark.asyncio
    async def test_records_price_match_request_pending(self, signals_world):
        db, user, _, _ = signals_world
        out = await record_price_match(
            body=PriceMatchIn(
                sku="SIG-1",
                competitor_name="SuperCheapTruck.com",
                competitor_url="https://supercheaptruck.com/some-product",
                competitor_price_usd="$199.99",
                notes="Found a better deal",
            ),
            user=user, db=db,
        )
        assert out.status == "pending"
        assert out.competitor_name == "SuperCheapTruck.com"

        rec = (await db.execute(select(PriceMatchRequest))).scalars().first()
        assert rec is not None
        assert rec.status == PriceMatchStatus.PENDING
        assert rec.user_id == user.id

    @pytest.mark.asyncio
    async def test_url_optional(self, signals_world):
        db, user, _, _ = signals_world
        out = await record_price_match(
            body=PriceMatchIn(
                sku="SIG-1",
                competitor_name="Local Shop",
                competitor_price_usd="$50",
            ),
            user=user, db=db,
        )
        assert out.competitor_url is None


# =========================================================================
# /api/orders/{web_order_number}/reorder
# =========================================================================


@pytest_asyncio.fixture
async def reorder_world(clean_db):
    db = clean_db
    warehouses = [
        Warehouse(code=10, name="Spokane", short_name="SPO", facs_route_label="SPO"),
        Warehouse(code=19, name="Boise",   short_name="BOISE", facs_route_label="BOISE"),
        Warehouse(code=0,  name="Nelson",  short_name="NELSON", facs_route_label="NELSON"),
    ]
    db.add_all(warehouses); await db.flush()
    brand = Brand(name="ReorderBrand", slug="reorderbrand")
    db.add(brand); await db.flush()
    p1 = Product(sku="RE-1", brand_id=brand.id, prod_code="RE", name="One",  is_for_sale=True, is_hidden=False)
    p2 = Product(sku="RE-2", brand_id=brand.id, prod_code="RE", name="Two",  is_for_sale=True, is_hidden=False)
    p3 = Product(sku="RE-3", brand_id=brand.id, prod_code="RE", name="Discontinued", is_for_sale=False, is_hidden=True)
    db.add_all([p1, p2, p3]); await db.flush()
    db.add(ProductPrice(product_id=p1.id, retail_price=Decimal("10"), suggested_retail_price=Decimal("12"), jobber_price=Decimal("8"), cost=Decimal("5")))
    db.add(ProductPrice(product_id=p2.id, retail_price=Decimal("20"), suggested_retail_price=Decimal("25"), jobber_price=Decimal("15"), cost=Decimal("10")))
    db.add(ProductPrice(product_id=p3.id, retail_price=Decimal("30"), suggested_retail_price=Decimal("35"), jobber_price=Decimal("22"), cost=Decimal("15")))
    db.add(ProductInventory(product_id=p1.id, warehouse_id=warehouses[0].id, on_hand=20))
    db.add(ProductInventory(product_id=p2.id, warehouse_id=warehouses[0].id, on_hand=20))

    cust = Customer(customer_number="RE-9", name="Reorder Co", tier=CustomerTier.JOBBER)
    db.add(cust); await db.flush()
    user = User(
        email="reorder@example.com", password_hash=hash_password("p"),
        role=UserRole.CUSTOMER, customer_id=cust.id, is_active=True, is_verified=True,
    )
    db.add(user); await db.flush()

    cart = Cart(customer_id=cust.id)
    db.add(cart); await db.flush()
    db.add(CartLine(cart_id=cart.id, product_id=p1.id, quantity=1))
    db.add(CartLine(cart_id=cart.id, product_id=p2.id, quantity=2))
    await db.commit()
    return db, {"user": user, "cust": cust, "p1": p1, "p2": p2, "p3": p3, "cart": cart}


def _checkout_body(**overrides):
    payload = dict(
        shipping=AddressIn(name="R", company=None, addr1="1 R St", addr2=None, city="Spokane", state="WA", zip="99201"),
        billing=None, contact_email="reorder@example.com", contact_phone="509-555-0001",
        payment_type="purchase_order", customer_po_number=None, comments=None, required_date=None,
    )
    payload.update(overrides)
    return CheckoutRequest(**payload)


async def _current_cart(db, customer_id):
    """The customer's LIVE (unsubmitted) cart, created if there isn't one.

    checkout() consumes the cart: it stamps submitted_at, and both a second
    checkout() and reorder() then look for a cart with submitted_at IS NULL.
    These tests used to hold on to the pre-checkout cart id, which after the
    first checkout is a submitted cart nothing will ever pick up again -- so the
    second checkout raised 400 "No cart found", and reorder quietly filled a NEW
    cart while the assertions looked at the old one. The endpoints were right;
    the tests had simply never run (their module could not be collected) since
    the behaviour was introduced.
    """
    cart = (await db.execute(
        select(Cart)
        .where(Cart.customer_id == customer_id, Cart.submitted_at.is_(None))
        .order_by(Cart.updated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cart is None:
        cart = Cart(customer_id=customer_id)
        db.add(cart)
        await db.commit()
        await db.refresh(cart)
    return cart


@pytest.fixture(autouse=True)
def stub_facs(monkeypatch):
    async def fake_push_csvs(csvs):
        return [PushResult(filename=c.filename, outcome=PushOutcome.LOCAL_DROPPED) for c in csvs]
    monkeypatch.setattr(orders_module, "push_csvs", fake_push_csvs)


class TestReorder:
    @pytest.mark.asyncio
    async def test_reorder_clones_lines_back_into_cart(self, reorder_world):
        db, w = reorder_world
        # Place an order first (consumes the cart)
        order = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        # Cart is now empty
        cart_lines = (await db.execute(select(CartLine).where(CartLine.cart_id == w["cart"].id))).scalars().all()
        assert cart_lines == []

        # Reorder
        result = await reorder(web_order_number=order.web_order_number, user=w["user"], db=db, request=anon_request())
        assert result.lines_added == 2
        assert result.lines_skipped == 0

        # Into the CURRENT cart: checkout submitted the original, so
        # reorder opened a new one. The old id holds nothing.
        cart = await _current_cart(db, w["cust"].id)
        cart_lines = (await db.execute(select(CartLine).where(CartLine.cart_id == cart.id))).scalars().all()
        assert len(cart_lines) == 2

    @pytest.mark.asyncio
    async def test_reorder_skips_discontinued_products(self, reorder_world):
        db, w = reorder_world
        # Add discontinued product to cart
        db.add(CartLine(cart_id=w["cart"].id, product_id=w["p3"].id, quantity=1))
        # Need stock too or the order will go BO
        warehouses = (await db.execute(select(Warehouse))).scalars().all()
        spo = next(wh for wh in warehouses if wh.code == 10)
        db.add(ProductInventory(product_id=w["p3"].id, warehouse_id=spo.id, on_hand=10))
        await db.commit()
        order = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())

        # Now mutate p3 to be discontinued AFTER the order was placed
        product3 = (await db.execute(select(Product).where(Product.sku == "RE-3"))).scalar_one()
        product3.is_hidden = True
        product3.is_for_sale = False
        await db.commit()

        result = await reorder(web_order_number=order.web_order_number, user=w["user"], db=db, request=anon_request())
        assert result.lines_skipped >= 1
        assert any("discontinued" in r or "hidden" in r for r in result.skipped_reasons)

    @pytest.mark.asyncio
    async def test_reorder_other_users_order_forbidden(self, reorder_world):
        db, w = reorder_world
        order = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())

        other_cust = Customer(customer_number="OTHER", name="Other", tier=CustomerTier.JOBBER)
        db.add(other_cust); await db.flush()
        other_user = User(
            email="other@example.com", password_hash=hash_password("p"),
            role=UserRole.CUSTOMER, customer_id=other_cust.id, is_active=True, is_verified=True,
        )
        db.add(other_user); await db.commit()

        with pytest.raises(HTTPException) as exc:
            await reorder(web_order_number=order.web_order_number, user=other_user, db=db, request=anon_request())
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_order_404(self, reorder_world):
        db, w = reorder_world
        with pytest.raises(HTTPException) as exc:
            await reorder(web_order_number="TTW0099999", user=w["user"], db=db, request=anon_request())
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_unlinked_user_400(self, reorder_world):
        db, w = reorder_world
        order = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        # Make a fresh user with no customer
        bare = User(
            email="bare@example.com", password_hash=hash_password("p"),
            role=UserRole.CUSTOMER, customer_id=None, is_active=True, is_verified=True,
        )
        db.add(bare); await db.commit()
        with pytest.raises(HTTPException) as exc:
            await reorder(web_order_number=order.web_order_number, user=bare, db=db, request=anon_request())
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_reorder_sums_into_existing_cart_lines(self, reorder_world):
        db, w = reorder_world
        order = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        # Pre-populate the CURRENT cart with p1 qty=5 -- reorder sums into
        # whichever cart is live after checkout, not the submitted one.
        cart = await _current_cart(db, w["cust"].id)
        db.add(CartLine(cart_id=cart.id, product_id=w["p1"].id, quantity=5))
        await db.commit()

        await reorder(web_order_number=order.web_order_number, user=w["user"], db=db, request=anon_request())
        # p1 should be 5 + 1 = 6
        line = (await db.execute(
            select(CartLine).where(CartLine.cart_id == cart.id, CartLine.product_id == w["p1"].id)
        )).scalar_one()
        assert line.quantity == 6
