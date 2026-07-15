"""Tests for fulfillment_service — warehouse split + IMS315 CSV materialization.

Pure tests cover:
  * `_allocate_proportional()` — proportional money splits
  * `build_csvs_from_plan()` — header construction + per-bucket money
    allocation, fed a synthetic plan (no DB)

Integration tests cover:
  * `plan_fulfillment()` — actual cart → bucket walk against a seeded test DB
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio

from app.models import (
    Brand,
    Cart,
    CartLine,
    Customer,
    CustomerTier,
    Product,
    ProductInventory,
    ProductPrice,
    Warehouse,
)
from app.services.fulfillment_service import (
    ROUTE_TO_FACS_WAREHOUSE,
    FulfillmentBucket,
    FulfillmentPlan,
    LineAllocation,
    _allocate_proportional,
    build_csvs_from_plan,
    plan_fulfillment,
)


# =========================================================================
# Pure: _allocate_proportional()
# =========================================================================


def _bucket(routing: str, sub: Decimal) -> FulfillmentBucket:
    """Tiny helper: bucket with a single dummy allocation that sums to `sub`."""
    return FulfillmentBucket(
        routing=routing,
        facs_warehouse_code=ROUTE_TO_FACS_WAREHOUSE[routing],
        warehouse_id=None,
        allocations=[LineAllocation(
            cart_line_id=0, product_id=0, sku="X", description="x",
            quantity=1, unit_price=sub, warehouse_code=0, warehouse_id=None,
            routing=routing,
        )],
    )


class TestAllocateProportional:
    def test_zero_total_yields_zero_per_bucket(self):
        plan = FulfillmentPlan(buckets=[_bucket("SPO", Decimal("100"))], total_item_subtotal=Decimal("100"))
        shares = _allocate_proportional(plan, Decimal("0"))
        assert shares == {"SPO": Decimal("0")}

    def test_zero_subtotal_yields_zero_per_bucket(self):
        # Edge case — every bucket has 0 items; can't proportionally split
        plan = FulfillmentPlan(buckets=[_bucket("SPO", Decimal("0"))], total_item_subtotal=Decimal("0"))
        shares = _allocate_proportional(plan, Decimal("100"))
        assert shares == {"SPO": Decimal("0")}

    def test_single_bucket_gets_full_amount(self):
        plan = FulfillmentPlan(buckets=[_bucket("SPO", Decimal("100"))], total_item_subtotal=Decimal("100"))
        assert _allocate_proportional(plan, Decimal("25.00")) == {"SPO": Decimal("25.00")}

    def test_two_bucket_even_split(self):
        plan = FulfillmentPlan(
            buckets=[_bucket("SPO", Decimal("100")), _bucket("NELSON", Decimal("100"))],
            total_item_subtotal=Decimal("200"),
        )
        shares = _allocate_proportional(plan, Decimal("50.00"))
        # 50/50 split; last bucket absorbs rounding
        assert shares["SPO"] == Decimal("25.00")
        assert shares["NELSON"] == Decimal("25.00")

    def test_uneven_split_proportional_to_subtotal(self):
        # 75% / 25% split
        plan = FulfillmentPlan(
            buckets=[_bucket("SPO", Decimal("300")), _bucket("NELSON", Decimal("100"))],
            total_item_subtotal=Decimal("400"),
        )
        shares = _allocate_proportional(plan, Decimal("100.00"))
        assert shares["SPO"] == Decimal("75.00")
        assert shares["NELSON"] == Decimal("25.00")

    def test_last_bucket_absorbs_rounding_remainder(self):
        # 100/3 split → ~33.33 each, but last bucket eats the .01 leftover
        plan = FulfillmentPlan(
            buckets=[
                _bucket("SPO", Decimal("100")),
                _bucket("BOISE", Decimal("100")),
                _bucket("NELSON", Decimal("100")),
            ],
            total_item_subtotal=Decimal("300"),
        )
        shares = _allocate_proportional(plan, Decimal("100.00"))
        # Sum must equal 100 exactly — no fractional cents lost
        assert sum(shares.values()) == Decimal("100.00")
        assert shares["SPO"] == Decimal("33.33")
        assert shares["BOISE"] == Decimal("33.33")
        assert shares["NELSON"] == Decimal("33.34")  # absorbed the +0.01

    def test_negative_totals_split_correctly(self):
        # Discount line is negative; proportional split should still work
        plan = FulfillmentPlan(
            buckets=[_bucket("SPO", Decimal("100")), _bucket("NELSON", Decimal("100"))],
            total_item_subtotal=Decimal("200"),
        )
        shares = _allocate_proportional(plan, Decimal("-10.00"))
        assert sum(shares.values()) == Decimal("-10.00")


# =========================================================================
# Pure: build_csvs_from_plan() — header + money fields
# =========================================================================


class _FakeCustomer:
    """Minimal stand-in for the real Customer ORM model."""

    def __init__(self):
        self.customer_number = "T-9999"
        self.name = "Test, Customer LLC"  # Comma intentionally — IMS315 should strip


def _alloc(routing: str, sku: str, qty: int, price: str = "10.00") -> LineAllocation:
    return LineAllocation(
        cart_line_id=0, product_id=0, sku=sku, description=f"desc {sku}",
        quantity=qty, unit_price=Decimal(price),
        warehouse_code=ROUTE_TO_FACS_WAREHOUSE[routing], warehouse_id=None,
        routing=routing,
    )


def _plan(*buckets: tuple[str, list[LineAllocation]]) -> FulfillmentPlan:
    bs = []
    total = Decimal("0")
    for routing, allocs in buckets:
        b = FulfillmentBucket(
            routing=routing,
            facs_warehouse_code=ROUTE_TO_FACS_WAREHOUSE[routing],
            warehouse_id=None,
            allocations=allocs,
        )
        bs.append(b)
        total += b.item_subtotal
    return FulfillmentPlan(buckets=bs, total_item_subtotal=total)


def _header_kwargs():
    return dict(
        addr1="123 MAIN", addr2="", city="SPOKANE", state="WA", zip="99201",
        email="t@example.com", contact_name="TEST", phone="509-555-1234",
        fax="0",
        ship_addr1="123 MAIN", ship_addr2="", ship_city="SPOKANE", ship_state="WA", ship_zip="99201",
        customer_po_number="PO-123", comments="WEB ORDER", payment_type="PO", sales_rep="",
        order_date=None, required_date=None,
    )


class TestBuildCSVsFromPlan:
    def test_single_bucket_produces_single_csv(self):
        plan = _plan(("SPO", [_alloc("SPO", "ABC123", 2, "5.00")]))
        out = build_csvs_from_plan(
            plan=plan, web_order_number="TTW0000099", customer=_FakeCustomer(),
            order_header_kwargs=_header_kwargs(),
        )
        assert len(out) == 1
        routing, csv, bucket, freight, discount, handling = out[0]
        assert routing == "SPO"
        assert csv.filename == "ORDERS_TITAN_SPO_TTW0000099_10.CSV"
        assert "TTW0000099" in csv.content
        assert "ABC123" in csv.content
        assert ",2," in csv.content  # qty 2

    def test_back_order_uses_backorder_quantity_not_quantity(self):
        plan = _plan(("BO", [_alloc("BO", "BO-SKU", 5, "10.00")]))
        out = build_csvs_from_plan(
            plan=plan, web_order_number="TTW0000100", customer=_FakeCustomer(),
            order_header_kwargs=_header_kwargs(),
        )
        _, csv, *_ = out[0]
        # Type-2 row: order_no, "2", sku, desc(blank), qty, b/o, price
        # For BO: qty=0, b/o=5
        assert ",BO-SKU,,0,5," in csv.content

    def test_tax_only_attached_to_spokane_bucket(self):
        plan = _plan(
            ("SPO",    [_alloc("SPO", "A", 1, "100.00")]),
            ("NELSON", [_alloc("NELSON", "B", 1, "100.00")]),
        )
        out = build_csvs_from_plan(
            plan=plan, web_order_number="TTW0001",
            customer=_FakeCustomer(), order_header_kwargs=_header_kwargs(),
            tax_total=Decimal("8.00"), tax_rate_x1000=80,
        )
        spo_csv = next(c for r, c, *_ in out if r == "SPO").content
        nelson_csv = next(c for r, c, *_ in out if r == "NELSON").content
        assert "$8.00" in spo_csv          # tax attached
        assert "$8.00" not in nelson_csv   # tax NOT attached

    def test_proportional_freight_split(self):
        plan = _plan(
            ("SPO",    [_alloc("SPO", "A", 1, "300.00")]),  # 75%
            ("NELSON", [_alloc("NELSON", "B", 1, "100.00")]),  # 25%
        )
        out = build_csvs_from_plan(
            plan=plan, web_order_number="TTW0002",
            customer=_FakeCustomer(), order_header_kwargs=_header_kwargs(),
            freight_total=Decimal("40.00"),
        )
        results = {r: (csv, freight) for r, csv, _, freight, _, _ in out}
        assert results["SPO"][1] == Decimal("30.00")     # 75% of 40
        assert results["NELSON"][1] == Decimal("10.00")  # 25% of 40

    def test_customer_name_commas_get_scrubbed(self):
        plan = _plan(("SPO", [_alloc("SPO", "A", 1, "5.00")]))
        out = build_csvs_from_plan(
            plan=plan, web_order_number="TTW0003",
            customer=_FakeCustomer(),  # name="Test, Customer LLC"
            order_header_kwargs=_header_kwargs(),
        )
        _, csv, *_ = out[0]
        # Comma stripped, name uppercased; "TEST CUSTOMER LLC" expected
        assert "TEST CUSTOMER LLC" in csv.content
        assert "Test, Customer LLC" not in csv.content

    def test_filename_warehouse_code_per_routing(self):
        plan = _plan(
            ("SPO",    [_alloc("SPO",    "A", 1, "1")]),
            ("BOISE",  [_alloc("BOISE",  "B", 1, "1")]),
            ("NELSON", [_alloc("NELSON", "C", 1, "1")]),
            ("BO",     [_alloc("BO",     "D", 1, "1")]),
        )
        out = build_csvs_from_plan(
            plan=plan, web_order_number="TTW0004",
            customer=_FakeCustomer(), order_header_kwargs=_header_kwargs(),
        )
        names = {r: csv.filename for r, csv, *_ in out}
        assert names["SPO"]    == "ORDERS_TITAN_SPO_TTW0004_10.CSV"
        assert names["BOISE"]  == "ORDERS_TITAN_BOISE_TTW0004_19.CSV"
        assert names["NELSON"] == "ORDERS_TITAN_NELSON_TTW0004_10.CSV"
        assert names["BO"]     == "ORDERS_TITAN_BO_TTW0004_10.CSV"


# =========================================================================
# DB integration: plan_fulfillment()
# =========================================================================


@pytest_asyncio.fixture
async def seed_warehouses(clean_db):
    db = clean_db
    warehouses = [
        Warehouse(code=10, name="Spokane", short_name="SPO", facs_route_label="SPO", emits_own_facs_file=True),
        Warehouse(code=19, name="Boise",   short_name="BOISE", facs_route_label="BOISE", emits_own_facs_file=True),
        Warehouse(code=0,  name="Nelson Kent", short_name="NELSON", facs_route_label="NELSON", emits_own_facs_file=True),
        Warehouse(code=1,  name="Portland",     short_name="PORTLAND", facs_route_label="NELSON", emits_own_facs_file=False),
    ]
    db.add_all(warehouses)
    await db.commit()
    return db, {w.code: w for w in warehouses}


@pytest_asyncio.fixture
async def seed_full(seed_warehouses):
    db, wh_by_code = seed_warehouses
    brand = Brand(name="TestBrand", slug="testbrand")
    db.add(brand)
    await db.flush()

    product = Product(
        sku="MULTIWH", brand_id=brand.id, prod_code="TST", name="Multi-warehouse SKU",
        is_for_sale=True, is_hidden=False,
    )
    db.add(product)
    await db.flush()
    db.add(ProductPrice(
        product_id=product.id,
        suggested_retail_price=Decimal("100"),
        retail_price=Decimal("80"),
        jobber_price=Decimal("60"),
        cost=Decimal("40"),
    ))

    cust = Customer(customer_number="C-WH-1", name="Test", tier=CustomerTier.JOBBER)
    db.add(cust)
    await db.flush()

    cart = Cart(customer_id=cust.id)
    db.add(cart)
    await db.flush()

    await db.commit()
    return db, wh_by_code, brand, product, cust, cart


class TestPlanFulfillment:
    @pytest.mark.asyncio
    async def test_no_stock_anywhere_routes_to_back_order(self, seed_full):
        db, wh, brand, product, cust, cart = seed_full
        # No ProductInventory rows — everything must go to BO
        db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=3))
        await db.commit()

        plan = await plan_fulfillment(db, cart=cart, customer=cust)
        assert len(plan.buckets) == 1
        assert plan.buckets[0].routing == "BO"
        assert plan.buckets[0].allocations[0].quantity == 3

    @pytest.mark.asyncio
    async def test_full_fill_from_spokane(self, seed_full):
        db, wh, brand, product, cust, cart = seed_full
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[10].id, on_hand=10))
        db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=3))
        await db.commit()

        plan = await plan_fulfillment(db, cart=cart, customer=cust)
        assert len(plan.buckets) == 1
        assert plan.buckets[0].routing == "SPO"
        assert plan.buckets[0].allocations[0].quantity == 3

    @pytest.mark.asyncio
    async def test_split_spokane_then_nelson(self, seed_full):
        db, wh, brand, product, cust, cart = seed_full
        # Spokane has 2, Nelson Kent (code 0) has 5 — qty 6 should split 2+4
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[10].id, on_hand=2))
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[0].id, on_hand=5))
        db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=6))
        await db.commit()

        plan = await plan_fulfillment(db, cart=cart, customer=cust)
        routings = {b.routing: b for b in plan.buckets}
        assert routings["SPO"].allocations[0].quantity == 2
        assert routings["NELSON"].allocations[0].quantity == 4

    @pytest.mark.asyncio
    async def test_partial_fill_remainder_goes_to_bo(self, seed_full):
        db, wh, brand, product, cust, cart = seed_full
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[10].id, on_hand=2))
        db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=5))
        await db.commit()

        plan = await plan_fulfillment(db, cart=cart, customer=cust)
        routings = {b.routing: b for b in plan.buckets}
        assert routings["SPO"].allocations[0].quantity == 2
        assert routings["BO"].allocations[0].quantity == 3

    @pytest.mark.asyncio
    async def test_portland_rolls_under_nelson_routing(self, seed_full):
        db, wh, brand, product, cust, cart = seed_full
        # Only Portland (code 1, route NELSON) has stock — bucket should still be NELSON
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[1].id, on_hand=5))
        db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=3))
        await db.commit()

        plan = await plan_fulfillment(db, cart=cart, customer=cust)
        assert len(plan.buckets) == 1
        assert plan.buckets[0].routing == "NELSON"
        assert plan.buckets[0].allocations[0].warehouse_code == 1

    @pytest.mark.asyncio
    async def test_priority_order_spokane_before_boise(self, seed_full):
        db, wh, brand, product, cust, cart = seed_full
        # Both Spokane and Boise have stock; should pick Spokane first
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[10].id, on_hand=10))
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[19].id, on_hand=10))
        db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=3))
        await db.commit()

        plan = await plan_fulfillment(db, cart=cart, customer=cust)
        # Only one bucket; must be SPO (priority wins)
        assert len(plan.buckets) == 1
        assert plan.buckets[0].routing == "SPO"

    @pytest.mark.asyncio
    async def test_total_item_subtotal_sums_all_buckets(self, seed_full):
        db, wh, brand, product, cust, cart = seed_full
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[10].id, on_hand=2))
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[0].id, on_hand=10))
        db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=5))
        await db.commit()

        plan = await plan_fulfillment(db, cart=cart, customer=cust)
        # Jobber tier_default 60 → MAP-clamped UP to 100; total = 5*100 = 500
        per_unit = plan.buckets[0].allocations[0].unit_price
        assert plan.total_item_subtotal == per_unit * 5

    @pytest.mark.asyncio
    async def test_buckets_returned_in_canonical_order(self, seed_full):
        db, wh, brand, product, cust, cart = seed_full
        # Fill from all 4 routings; expected order: SPO, BOISE, NELSON, BO
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[10].id, on_hand=1))
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[19].id, on_hand=1))
        db.add(ProductInventory(product_id=product.id, warehouse_id=wh[0].id, on_hand=1))
        db.add(CartLine(cart_id=cart.id, product_id=product.id, quantity=10))  # 7 will be BO
        await db.commit()

        plan = await plan_fulfillment(db, cart=cart, customer=cust)
        routings = [b.routing for b in plan.buckets]
        assert routings == ["SPO", "BOISE", "NELSON", "BO"]
