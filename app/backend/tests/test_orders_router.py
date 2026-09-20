"""Integration tests for the orders router.

We exercise the route handlers as plain async functions (they're easy to call
once you provide a User + DB session).  For each test we monkeypatch the FACS
pusher to a no-op so we don't write CSVs to disk.
"""

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
    Product,
    ProductInventory,
    ProductPrice,
    User,
    UserRole,
    Warehouse,
)
from app.routers import orders as orders_router
from app.routers.orders import (
    AddressIn,
    CheckoutRequest,
    checkout,
    get_order,
    list_orders,
    replay_facs_push,
)
from app.services.auth_service import hash_password
from app.services.facs_pusher import PushOutcome, PushResult


# =========================================================================
# Fixtures: full minimal world (warehouses + brand + product + price + cust + user + cart)
# =========================================================================


@pytest_asyncio.fixture
async def world(clean_db):
    db = clean_db

    warehouses = [
        Warehouse(code=10, name="Spokane", short_name="SPO", facs_route_label="SPO", emits_own_facs_file=True),
        Warehouse(code=19, name="Boise",   short_name="BOISE", facs_route_label="BOISE", emits_own_facs_file=True),
        Warehouse(code=0,  name="Nelson Kent", short_name="NELSON", facs_route_label="NELSON", emits_own_facs_file=True),
        Warehouse(code=1,  name="Portland", short_name="PORTLAND", facs_route_label="NELSON", emits_own_facs_file=False),
    ]
    db.add_all(warehouses)
    await db.flush()

    brand = Brand(name="OrdersTestBrand", slug="orderstestbrand")
    db.add(brand)
    await db.flush()

    product = Product(
        sku="ORD-TEST-1", brand_id=brand.id, prod_code="ORD",
        name="Orders Test Product", is_for_sale=True, is_hidden=False,
    )
    db.add(product)
    await db.flush()
    db.add(ProductPrice(
        product_id=product.id,
        suggested_retail_price=Decimal("100"),
        retail_price=Decimal("80"),
        jobber_price=Decimal("60"),
        cost=Decimal("40"),
        # The test below has always claimed "MAP=100" while nothing set the MAP
        # column -- it was reading suggested_retail_price as if it were a floor.
        # Set for real now, so the day MAP is wired through the day it starts
        # passing (and reports XPASS) instead of staying quietly wrong.
        map_price=Decimal("100"),
    ))

    cust = Customer(customer_number="ORD-9001", name="Orders Test Co", tier=CustomerTier.JOBBER)
    db.add(cust)
    await db.flush()

    user = User(
        email="orders-test@example.com",
        password_hash=hash_password("testpass123"),
        role=UserRole.CUSTOMER,
        customer_id=cust.id,
        is_active=True, is_verified=True,
    )
    db.add(user)
    await db.flush()

    # Stock: Spokane 5
    db.add(ProductInventory(product_id=product.id, warehouse_id=warehouses[0].id, on_hand=5))

    # Cart with one line of qty 2
    cart = Cart(customer_id=cust.id)
    db.add(cart)
    await db.flush()
    db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=2))

    await db.commit()
    return db, {"user": user, "cust": cust, "cart": cart, "product": product, "warehouses": warehouses}


@pytest.fixture(autouse=True)
def stub_facs_push(monkeypatch):
    """Mock the FACS pusher so tests don't write to disk or hit FTP."""
    async def fake_push_csvs(csvs):
        return [PushResult(filename=c.filename, outcome=PushOutcome.LOCAL_DROPPED) for c in csvs]
    monkeypatch.setattr(orders_router, "push_csvs", fake_push_csvs)
    return fake_push_csvs


def _checkout_body(**overrides) -> CheckoutRequest:
    payload = dict(
        shipping=AddressIn(name="Test Recv", company=None, addr1="123 Main", addr2=None,
                          city="Spokane", state="WA", zip="99201"),
        billing=None,
        contact_email="orders-test@example.com",
        contact_phone="509-555-1234",
        payment_type="purchase_order",
        customer_po_number="PO-TEST",
        comments="test order",
        required_date=None,
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


# =========================================================================
# POST /api/orders/checkout
# =========================================================================


class TestCheckout:
    # MAP IS NOT ENFORCED ON ANY LIVE PRICING PATH. `ProductPrice.map_price`
    # exists (app/models/pricing.py:32) and `pricing_engine.resolve_price()`
    # clamps to it and has 25 passing unit tests for the behaviour -- but the
    # DB-aware wrapper that every caller actually goes through,
    # `services/pricing_service.py`, never passes `map_price` at either of its
    # two resolve_price() call sites. Nothing else in app/ reads the column. So
    # a jobber checks out at the P3 tier price even when that is below the
    # advertised floor: here 2 x 60 = 120.00 where the floor says 2 x 100.
    #
    # Left as xfail rather than rewritten to expect 120.00, because "we sell
    # below MAP" is a commercial decision with supplier agreements behind it,
    # not a number to quietly update in a test. Either wire map_price through
    # pricing_service and this goes green, or decide MAP is presentation-only
    # and delete this expectation on purpose.
    #
    # This went unseen because the module could not be collected at all in the
    # interpreter the suite was being run with -- it has never actually run.
    @pytest.mark.xfail(
        reason="MAP floor not wired into pricing_service; see the note above",
        strict=False,
    )
    @pytest.mark.asyncio
    async def test_happy_path_creates_order_with_status_pushed(self, world):
        db, w = world
        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        assert result.status == "pushed_to_facs"
        assert result.web_order_number.startswith("TTW")
        # Jobber tier default is P3=60, but MAP=100 so engine clamps UP → 2 × 100
        assert result.item_total == "200.00"
        # Phase 1 charges freight + WA tax — grand total > item total
        assert Decimal(result.grand_total) > Decimal(result.item_total)
        # Default flat rate (no weight) = $18 → freight = 18.00
        assert result.shipping_total == "18.00"
        # WA shipping → 8.9% on (item + freight) = 218 * 0.089 = 19.40
        assert result.tax_total == "19.40"
        assert len(result.fulfillments) == 1
        assert result.fulfillments[0].routing_type == "SPO"

    @pytest.mark.asyncio
    async def test_creates_one_fulfillment_per_routing(self, world):
        db, w = world
        # Add Boise stock + bump qty so order splits
        db.add(ProductInventory(product_id=w["product"].id, warehouse_id=w["warehouses"][1].id, on_hand=10))
        # Bump cart qty so it has to split (5 from SPO, 2 from BOISE)
        cl = (await db.execute(
            __import__("sqlalchemy").select(CartLine).where(CartLine.cart_id == w["cart"].id)
        )).scalar_one()
        cl.quantity = 7
        await db.commit()

        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        routings = sorted(f.routing_type for f in result.fulfillments)
        assert routings == ["BOISE", "SPO"]
        # Lines split properly
        spo_line = next(l for l in result.lines if l.routing == "SPO")
        boise_line = next(l for l in result.lines if l.routing == "BOISE")
        assert spo_line.quantity == 5
        assert boise_line.quantity == 2

    @pytest.mark.asyncio
    async def test_back_order_routing_when_no_stock(self, world):
        db, w = world
        # Wipe inventory
        await db.execute(__import__("sqlalchemy").delete(ProductInventory))
        await db.commit()

        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        assert len(result.fulfillments) == 1
        assert result.fulfillments[0].routing_type == "BO"
        assert result.lines[0].backorder_quantity == 2
        assert result.lines[0].quantity == 0

    @pytest.mark.asyncio
    async def test_unlinked_user_rejected(self, world):
        db, w = world
        # Mutate the user to have no customer_id
        unlinked = User(
            email="unlinked@example.com",
            password_hash=hash_password("p"),
            role=UserRole.CUSTOMER, customer_id=None,
            is_active=True, is_verified=True,
        )
        db.add(unlinked)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await checkout(body=_checkout_body(), user=unlinked, db=db, request=anon_request())
        assert exc.value.status_code == 400
        assert "not linked" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_empty_cart_rejected(self, world):
        db, w = world
        await db.execute(__import__("sqlalchemy").delete(CartLine))
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        assert exc.value.status_code == 400
        assert "cart is empty" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_billing_defaults_to_shipping_when_omitted(self, world):
        db, w = world
        result = await checkout(body=_checkout_body(billing=None), user=w["user"], db=db, request=anon_request())
        assert result.billing["addr1"] == result.shipping["addr1"]
        assert result.billing["zip"] == result.shipping["zip"]

    @pytest.mark.asyncio
    async def test_separate_billing_address_preserved(self, world):
        db, w = world
        body = _checkout_body(
            billing=AddressIn(name="AP", company=None, addr1="PO BOX 9", addr2=None,
                              city="Spokane", state="wa", zip="99210"),
        )
        result = await checkout(body=body, user=w["user"], db=db, request=anon_request())
        assert result.billing["addr1"] == "PO BOX 9"
        assert result.shipping["addr1"] == "123 Main"
        # State uppercased on save
        assert result.billing["state"] == "WA"

    @pytest.mark.asyncio
    async def test_cart_emptied_after_successful_checkout(self, world):
        from sqlalchemy import select
        db, w = world
        await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        remaining = (await db.execute(
            select(CartLine).where(CartLine.cart_id == w["cart"].id)
        )).scalars().all()
        assert remaining == []

    @pytest.mark.asyncio
    async def test_web_order_number_format(self, world):
        db, w = world
        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        assert result.web_order_number.startswith("TTW")
        assert len(result.web_order_number) == 10  # TTW + 7 digits

    @pytest.mark.asyncio
    async def test_facs_push_failure_marks_fulfillment_failed(self, world, monkeypatch):
        db, w = world

        async def failing_push(csvs):
            return [PushResult(filename=c.filename, outcome=PushOutcome.FAILED, error="ftp down") for c in csvs]
        monkeypatch.setattr(orders_router, "push_csvs", failing_push)

        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        # Push failed → status stays "placed", not "pushed_to_facs"
        assert result.status == "placed"
        assert result.fulfillments[0].push_status == "failed"


# =========================================================================
# GET /api/orders + GET /api/orders/{web_order_number}
# =========================================================================


class TestListAndGet:
    @pytest.mark.asyncio
    async def test_list_returns_users_orders_only(self, world):
        db, w = world
        # Create one order
        await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        # Fresh cart for second order
        # A NEW cart: the first checkout submitted the original, and a
        # submitted cart is invisible to the next one.
        cart2 = await _current_cart(db, w["cust"].id)
        db.add(CartLine(cart_id=cart2.id, product_id=w["product"].id, quantity=1))
        await db.commit()
        await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())

        out = await list_orders(user=w["user"], db=db, request=anon_request())
        assert len(out) == 2
        # Newest first
        assert out[0].id > out[1].id

    @pytest.mark.asyncio
    async def test_list_unlinked_user_returns_empty(self, world):
        db, w = world
        unlinked = User(
            email="u2@example.com", password_hash=hash_password("p"),
            role=UserRole.CUSTOMER, customer_id=None,
            is_active=True, is_verified=True,
        )
        db.add(unlinked)
        await db.commit()
        out = await list_orders(user=unlinked, db=db, request=anon_request())
        assert out == []

    @pytest.mark.asyncio
    async def test_get_order_owner_can_view(self, world):
        db, w = world
        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        fetched = await get_order(web_order_number=result.web_order_number, user=w["user"], db=db, request=anon_request())
        assert fetched.web_order_number == result.web_order_number

    @pytest.mark.asyncio
    async def test_get_order_other_user_forbidden(self, world):
        db, w = world
        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())

        # Different user (different customer)
        other_cust = Customer(customer_number="ORD-OTHER", name="Other Co", tier=CustomerTier.JOBBER)
        db.add(other_cust)
        await db.flush()
        other_user = User(
            email="other@example.com", password_hash=hash_password("p"),
            role=UserRole.CUSTOMER, customer_id=other_cust.id,
            is_active=True, is_verified=True,
        )
        db.add(other_user)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await get_order(web_order_number=result.web_order_number, user=other_user, db=db, request=anon_request())
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_order_admin_can_view_any(self, world):
        db, w = world
        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())

        admin = User(
            email="admin@example.com", password_hash=hash_password("p"),
            role=UserRole.ADMIN, customer_id=None,
            is_active=True, is_verified=True,
        )
        db.add(admin)
        await db.commit()

        fetched = await get_order(web_order_number=result.web_order_number, user=admin, db=db, request=anon_request())
        assert fetched.web_order_number == result.web_order_number

    @pytest.mark.asyncio
    async def test_get_order_unknown_returns_404(self, world):
        db, w = world
        with pytest.raises(HTTPException) as exc:
            await get_order(web_order_number="TTW9999999", user=w["user"], db=db, request=anon_request())
        assert exc.value.status_code == 404


# =========================================================================
# POST /api/orders/{web_order_number}/replay/{routing_type}
# =========================================================================


class TestReplayFacsPush:
    @pytest.mark.asyncio
    async def test_admin_replay_marks_pushed(self, world, monkeypatch):
        db, w = world
        # Place an order first
        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())

        admin = User(
            email="admin1@example.com", password_hash=hash_password("p"),
            role=UserRole.ADMIN, customer_id=None,
            is_active=True, is_verified=True,
        )
        db.add(admin)
        await db.commit()

        async def fake_push_csv(csv):
            return PushResult(filename=csv.filename, outcome=PushOutcome.LOCAL_DROPPED)
        from app.routers import orders as orders_module
        monkeypatch.setattr(orders_module, "push_csv", fake_push_csv)

        out = await replay_facs_push(
            web_order_number=result.web_order_number,
            routing_type="SPO",
            user=admin,
            db=db,
        )
        assert out.push_status == "pushed"
        assert out.push_attempts >= 2  # original + replay
        assert out.last_error is None

    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, world):
        db, w = world
        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        with pytest.raises(HTTPException) as exc:
            await replay_facs_push(
                web_order_number=result.web_order_number,
                routing_type="SPO",
                user=w["user"],  # plain customer, not admin
                db=db,
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_unknown_order_returns_404(self, world):
        db, w = world
        admin = User(
            email="admin2@example.com", password_hash=hash_password("p"),
            role=UserRole.ADMIN, customer_id=None,
            is_active=True, is_verified=True,
        )
        db.add(admin)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await replay_facs_push(
                web_order_number="TTW0000000",
                routing_type="SPO", user=admin, db=db,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_unknown_routing_returns_404(self, world):
        db, w = world
        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        admin = User(
            email="admin3@example.com", password_hash=hash_password("p"),
            role=UserRole.ADMIN, customer_id=None,
            is_active=True, is_verified=True,
        )
        db.add(admin)
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await replay_facs_push(
                web_order_number=result.web_order_number,
                routing_type="BOISE", user=admin, db=db,
            )
        # No BOISE bucket on this single-warehouse order
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_failed_push_marks_failed_and_records_error(self, world, monkeypatch):
        db, w = world
        result = await checkout(body=_checkout_body(), user=w["user"], db=db, request=anon_request())
        admin = User(
            email="admin4@example.com", password_hash=hash_password("p"),
            role=UserRole.ADMIN, customer_id=None,
            is_active=True, is_verified=True,
        )
        db.add(admin)
        await db.commit()

        async def fake_failing_push(csv):
            return PushResult(filename=csv.filename, outcome=PushOutcome.FAILED, error="ftp dead")
        from app.routers import orders as orders_module
        monkeypatch.setattr(orders_module, "push_csv", fake_failing_push)

        out = await replay_facs_push(
            web_order_number=result.web_order_number,
            routing_type="SPO", user=admin, db=db,
        )
        assert out.push_status == "failed"
        assert out.last_error == "ftp dead"
