"""DB integration tests for the cart_service async wrapper.

Pure planner tests live in ``test_cart_service.py``; this module verifies the
async DB-touching wrapper applies the planner's actions correctly and leaves
the database in the expected shape.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import (
    Brand,
    Cart,
    CartLine,
    Customer,
    CustomerTier,
    Product,
    ProductPrice,
)
from app.services.cart_service import merge_anonymous_into_customer_cart


@pytest_asyncio.fixture
async def cart_world(clean_db):
    db = clean_db
    brand = Brand(name="CartBrand", slug="cartbrand")
    db.add(brand)
    await db.flush()
    p1 = Product(sku="CART-A", brand_id=brand.id, prod_code="CT", name="A")
    p2 = Product(sku="CART-B", brand_id=brand.id, prod_code="CT", name="B")
    p3 = Product(sku="CART-C", brand_id=brand.id, prod_code="CT", name="C")
    db.add_all([p1, p2, p3])
    await db.flush()
    db.add(ProductPrice(product_id=p1.id, retail_price=Decimal("10")))
    db.add(ProductPrice(product_id=p2.id, retail_price=Decimal("20")))
    db.add(ProductPrice(product_id=p3.id, retail_price=Decimal("30")))
    cust = Customer(customer_number="CART-1", name="Cart Test", tier=CustomerTier.JOBBER)
    db.add(cust)
    await db.commit()
    return db, cust, p1, p2, p3


async def _line_count(db, cart_id: int) -> int:
    rows = (await db.execute(select(CartLine).where(CartLine.cart_id == cart_id))).scalars().all()
    return len(rows)


async def _qty(db, cart_id: int, product_id: int) -> int:
    line = (await db.execute(
        select(CartLine).where(CartLine.cart_id == cart_id, CartLine.product_id == product_id)
    )).scalar_one_or_none()
    return line.quantity if line else 0


class TestCartMergeWrapper:
    @pytest.mark.asyncio
    async def test_no_session_token_returns_existing_customer_cart(self, cart_world):
        db, cust, p1, p2, p3 = cart_world
        # Pre-create a customer cart
        cart = Cart(customer_id=cust.id)
        db.add(cart)
        await db.commit()

        result = await merge_anonymous_into_customer_cart(
            db, session_token=None, customer_id=cust.id,
        )
        assert result is not None and result.id == cart.id

    @pytest.mark.asyncio
    async def test_anon_cart_with_no_customer_cart_reassigns(self, cart_world):
        db, cust, p1, p2, p3 = cart_world
        anon = Cart(session_token="anon-token-1")
        db.add(anon)
        await db.flush()
        db.add(CartLine(cart_id=anon.id, product_id=p1.id, quantity=2))
        db.add(CartLine(cart_id=anon.id, product_id=p2.id, quantity=3))
        await db.commit()
        anon_id = anon.id

        result = await merge_anonymous_into_customer_cart(
            db, session_token="anon-token-1", customer_id=cust.id,
        )
        await db.commit()

        assert result is not None
        # Reassigned: same cart row, now keyed by customer_id, session_token cleared
        await db.refresh(result)
        assert result.id == anon_id
        assert result.customer_id == cust.id
        assert result.session_token is None
        assert await _qty(db, result.id, p1.id) == 2
        assert await _qty(db, result.id, p2.id) == 3

    @pytest.mark.asyncio
    async def test_overlap_sums_quantities_and_drops_anon_cart(self, cart_world):
        db, cust, p1, p2, p3 = cart_world
        # Customer cart already has CART-A qty=5, CART-B qty=2
        cust_cart = Cart(customer_id=cust.id)
        db.add(cust_cart)
        await db.flush()
        db.add(CartLine(cart_id=cust_cart.id, product_id=p1.id, quantity=5))
        db.add(CartLine(cart_id=cust_cart.id, product_id=p2.id, quantity=2))
        # Anon cart has CART-A qty=3 (overlaps), CART-C qty=4 (new)
        anon = Cart(session_token="anon-token-2")
        db.add(anon)
        await db.flush()
        db.add(CartLine(cart_id=anon.id, product_id=p1.id, quantity=3))
        db.add(CartLine(cart_id=anon.id, product_id=p3.id, quantity=4))
        await db.commit()
        anon_id = anon.id
        cust_cart_id = cust_cart.id

        result = await merge_anonymous_into_customer_cart(
            db, session_token="anon-token-2", customer_id=cust.id,
        )
        await db.commit()

        assert result is not None and result.id == cust_cart_id
        # 5 + 3 = 8 for A
        assert await _qty(db, cust_cart_id, p1.id) == 8
        # B unchanged
        assert await _qty(db, cust_cart_id, p2.id) == 2
        # C moved from anon
        assert await _qty(db, cust_cart_id, p3.id) == 4
        # Anon cart deleted
        anon_check = (await db.execute(select(Cart).where(Cart.id == anon_id))).scalar_one_or_none()
        assert anon_check is None

    @pytest.mark.asyncio
    async def test_no_anon_cart_no_op(self, cart_world):
        db, cust, p1, p2, p3 = cart_world
        # Customer cart with one line; anon token doesn't exist
        cust_cart = Cart(customer_id=cust.id)
        db.add(cust_cart)
        await db.flush()
        db.add(CartLine(cart_id=cust_cart.id, product_id=p1.id, quantity=5))
        await db.commit()

        result = await merge_anonymous_into_customer_cart(
            db, session_token="never-existed", customer_id=cust.id,
        )
        await db.commit()

        assert result is not None and result.id == cust_cart.id
        assert await _qty(db, cust_cart.id, p1.id) == 5

    @pytest.mark.asyncio
    async def test_quantity_cap_respected_during_merge(self, cart_world):
        db, cust, p1, p2, p3 = cart_world
        cust_cart = Cart(customer_id=cust.id)
        db.add(cust_cart)
        await db.flush()
        db.add(CartLine(cart_id=cust_cart.id, product_id=p1.id, quantity=600))
        anon = Cart(session_token="anon-cap")
        db.add(anon)
        await db.flush()
        db.add(CartLine(cart_id=anon.id, product_id=p1.id, quantity=600))
        await db.commit()

        await merge_anonymous_into_customer_cart(
            db, session_token="anon-cap", customer_id=cust.id,
        )
        await db.commit()
        # 600 + 600 = 1200, capped at 999
        assert await _qty(db, cust_cart.id, p1.id) == 999
