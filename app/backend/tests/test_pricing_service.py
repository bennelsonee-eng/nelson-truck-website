"""Tests for pricing_service — TierPricingDisplay + Front Counter math + DB integration."""

from __future__ import annotations

from decimal import Decimal

import pytest
import pytest_asyncio

from app.models import (
    Brand,
    Contract,
    Customer,
    CustomerTier,
    Product,
    ProductPrice,
)
from app.services.pricing_service import (
    TierPricingDisplay,
    anonymous_retail_display,
    build_tier_display,
    build_tier_display_batch,
    front_counter_quote,
    resolve_for_customer,
)


# =========================================================================
# Pure: front_counter_quote()
# =========================================================================


class TestFrontCounterQuote:
    def test_no_markup_returns_map(self):
        assert front_counter_quote(
            cost_basis=Decimal("100"), map_retail=Decimal("150"), markup_pct=0
        ) == Decimal("150")

    def test_no_markup_falls_back_to_cost_when_map_missing(self):
        assert front_counter_quote(
            cost_basis=Decimal("100"), map_retail=None, markup_pct=0
        ) == Decimal("100")

    def test_no_markup_no_cost_no_map_returns_none(self):
        assert front_counter_quote(cost_basis=None, map_retail=None, markup_pct=None) is None

    def test_markup_above_map_uses_marked_up_price(self):
        # cost 100 + 50% = 150; MAP 120 → use 150
        assert front_counter_quote(
            cost_basis=Decimal("100"), map_retail=Decimal("120"), markup_pct=50
        ) == Decimal("150.00")

    def test_markup_below_map_uses_map_floor(self):
        # cost 100 + 10% = 110; MAP 150 → use MAP 150
        assert front_counter_quote(
            cost_basis=Decimal("100"), map_retail=Decimal("150"), markup_pct=10
        ) == Decimal("150")

    def test_markup_exactly_equal_to_map_returns_map(self):
        # cost 100 + 50% = 150; MAP 150 → use MAP (tie goes to MAP)
        assert front_counter_quote(
            cost_basis=Decimal("100"), map_retail=Decimal("150"), markup_pct=50
        ) == Decimal("150")

    def test_markup_with_no_cost_basis_falls_back_to_map(self):
        assert front_counter_quote(
            cost_basis=None, map_retail=Decimal("99"), markup_pct=25
        ) == Decimal("99")

    def test_markup_with_no_map_uses_marked_price(self):
        assert front_counter_quote(
            cost_basis=Decimal("80"), map_retail=None, markup_pct=25
        ) == Decimal("100.00")

    def test_zero_markup_treated_as_no_markup(self):
        # markup=0 should behave the same as None — return MAP / cost
        assert front_counter_quote(
            cost_basis=Decimal("100"), map_retail=Decimal("120"), markup_pct=0
        ) == Decimal("120")

    def test_high_markup_doesnt_overflow(self):
        # Sanity check upper bound (validator caps at 500 in the API)
        assert front_counter_quote(
            cost_basis=Decimal("10"), map_retail=Decimal("5"), markup_pct=500
        ) == Decimal("60.00")

    def test_quantize_to_two_decimals(self):
        assert front_counter_quote(
            cost_basis=Decimal("3.33"), map_retail=Decimal("1"), markup_pct=10
        ) == Decimal("3.66")  # 3.33 * 1.10 = 3.663 → 3.66


# =========================================================================
# Pure: anonymous_retail_display()
# =========================================================================


class TestAnonymousRetailDisplay:
    def _price(self, **kw) -> ProductPrice:
        defaults = dict(
            suggested_retail_price=None, retail_price=None, jobber_price=None,
            dealer_price=None, cost=None, sale_price=None, map_price=None,
            sale_starts_at=None, sale_ends_at=None, last_synced_at=None,
            municipality_price=None,
        )
        defaults.update(kw)
        # ProductPrice has product_id required — but since we only read fields
        # for display, we can construct without committing
        return ProductPrice(product_id=1, **defaults)

    def test_none_input_returns_call_for_price(self):
        d = anonymous_retail_display(None)
        assert d.tier == "retail"
        assert d.primary_label == "Retail"
        assert d.primary_amount is None

    def test_retail_below_suggested_still_shows_single_line(self):
        # Owner 2026-05-17: retail price already reflects MAP, so the old
        # strike-through "Save $X off Suggested Retail" display is off.
        d = anonymous_retail_display(self._price(
            suggested_retail_price=Decimal("100"), retail_price=Decimal("80")
        ))
        assert d.primary_amount == Decimal("80")
        assert d.secondary_amount is None
        assert d.savings_amount is None

    def test_single_line_when_retail_equals_suggested(self):
        d = anonymous_retail_display(self._price(
            suggested_retail_price=Decimal("100"), retail_price=Decimal("100")
        ))
        assert d.primary_amount == Decimal("100")
        assert d.secondary_amount is None
        assert d.savings_amount is None

    def test_single_line_when_only_retail_set(self):
        d = anonymous_retail_display(self._price(retail_price=Decimal("80")))
        assert d.primary_amount == Decimal("80")
        assert d.secondary_amount is None

    def test_single_line_when_only_suggested_set_uses_suggested(self):
        d = anonymous_retail_display(self._price(suggested_retail_price=Decimal("100")))
        assert d.primary_amount == Decimal("100")
        assert d.secondary_amount is None

    def test_dict_serialization_shape(self):
        d = anonymous_retail_display(self._price(
            suggested_retail_price=Decimal("100"), retail_price=Decimal("80")
        ))
        out = d.as_dict()
        assert out["primary_amount"] == "80.00"
        assert out["secondary_amount"] is None
        assert out["savings_amount"] is None
        assert out["map_clamped"] is False
        assert out["original_amount"] is None


# =========================================================================
# TierPricingDisplay.as_dict()
# =========================================================================


class TestTierPricingDisplayDict:
    def test_quantize_money(self):
        # Use 12.346 to avoid banker's-rounding ambiguity at .5
        d = TierPricingDisplay(
            tier="jobber",
            primary_label="Your Cost",
            primary_amount=Decimal("12.346"),
            secondary_label="MAP Retail",
            secondary_amount=Decimal("15"),
        )
        out = d.as_dict()
        assert out["primary_amount"] == "12.35"
        assert out["secondary_amount"] == "15.00"

    def test_map_clamp_fields_pass_through(self):
        d = TierPricingDisplay(
            tier="jobber",
            primary_label="Your Cost",
            primary_amount=Decimal("200"),
            secondary_amount=Decimal("200"),
            map_clamped=True,
            original_amount=Decimal("160"),
        )
        out = d.as_dict()
        assert out["map_clamped"] is True
        assert out["original_amount"] == "160.00"

    def test_notes_default_to_empty_list(self):
        d = TierPricingDisplay(tier="retail", primary_label="Retail", primary_amount=None)
        assert d.as_dict()["notes"] == []


# =========================================================================
# DB integration: build_tier_display() + resolve_for_customer()
# =========================================================================


@pytest_asyncio.fixture
async def seed_brand_product(clean_db):
    """Minimal seed: one Brand + one Product + one ProductPrice + the YAK contract.

    The product is keyed by the YAK brand prefix so contract.brand=YAK matches.
    """
    db = clean_db
    brand = Brand(name="Yakima", slug="yakima")
    db.add(brand)
    await db.flush()

    product = Product(
        sku="YAKTEST1", brand_id=brand.id, prod_code="YAK", name="Test Yakima Rack",
        description="Test", is_for_sale=True, is_hidden=False,
    )
    db.add(product)
    await db.flush()

    price = ProductPrice(
        product_id=product.id,
        suggested_retail_price=Decimal("200.00"),  # P1 — MAP floor
        retail_price=Decimal("180.00"),            # P2
        jobber_price=Decimal("130.00"),            # P3 — jobber default
        dealer_price=Decimal("120.00"),            # P4
        cost=Decimal("100.00"),                    # P5
    )
    db.add(price)
    await db.commit()
    return db, brand, product, price


@pytest_asyncio.fixture
async def seed_jobber_customer(seed_brand_product):
    db, brand, product, price = seed_brand_product
    cust = Customer(
        customer_number="TEST-J1",
        name="Test Jobber Customer",
        tier=CustomerTier.JOBBER,
    )
    db.add(cust)
    await db.commit()
    return db, brand, product, price, cust


@pytest_asyncio.fixture
async def seed_muni_customer(seed_brand_product):
    db, brand, product, price = seed_brand_product
    cust = Customer(
        customer_number="TEST-M1",
        name="Test City",
        tier=CustomerTier.MUNICIPALITY,
    )
    db.add(cust)
    await db.commit()
    return db, brand, product, price, cust


class TestBuildTierDisplayJobber:
    @pytest.mark.asyncio
    async def test_jobber_no_contract_uses_tier_default(self, seed_jobber_customer):
        db, brand, product, price, cust = seed_jobber_customer
        d = await build_tier_display(db, customer=cust, product=product)
        assert d.tier == "jobber"
        assert d.primary_label == "Your Cost"
        # P3 jobber price = 130. MAP no longer clamps contract pricing
        # (owner rule 2026-05-17: MAP is retail-only).
        assert d.primary_amount == Decimal("130")
        assert d.secondary_amount == Decimal("200")  # MAP Retail still shown alongside
        assert d.map_clamped is False
        assert d.original_amount is None

    @pytest.mark.asyncio
    async def test_jobber_with_contract_below_map_no_clamp(self, seed_jobber_customer):
        db, brand, product, price, cust = seed_jobber_customer
        # P5/.95 contract → 100/.95 ≈ 105.26. Under the retail-only MAP rule
        # this should surface as-is rather than being floored to suggested retail.
        contract = Contract(
            customer_id=cust.id,
            name="Test contract",
            brand="YAK",
            priority=1,
            min_quantity=0,
            pricing_formula="P5/.95",
        )
        db.add(contract)
        await db.commit()

        d = await build_tier_display(db, customer=cust, product=product)
        assert d.map_clamped is False
        assert d.original_amount is None
        assert d.primary_amount is not None and d.primary_amount < Decimal("200")
        assert d.contract_id == contract.id
        assert d.contract_name == "Test contract"

    @pytest.mark.asyncio
    async def test_jobber_with_high_priced_contract_no_clamp(self, seed_jobber_customer):
        db, brand, product, price, cust = seed_jobber_customer
        # Contract = P1 (suggested retail 200) — equals MAP, no clamp
        contract = Contract(
            customer_id=cust.id,
            name="High contract",
            brand="YAK",
            priority=1,
            min_quantity=0,
            pricing_formula="P1",
        )
        db.add(contract)
        await db.commit()

        d = await build_tier_display(db, customer=cust, product=product)
        # P1=200, MAP=200, no clamp
        assert d.map_clamped is False
        assert d.original_amount is None
        assert d.primary_amount == Decimal("200")


class TestBuildTierDisplayMunicipality:
    @pytest.mark.asyncio
    async def test_muni_returns_contract_price_layout(self, seed_muni_customer):
        db, brand, product, price, cust = seed_muni_customer
        contract = Contract(
            customer_id=cust.id,
            name="Sourcewell via NAFG",
            brand="YAK",
            priority=1,
            min_quantity=0,
            pricing_formula="P3*.83",  # 130 * 0.83 ≈ 107.90
        )
        db.add(contract)
        await db.commit()

        d = await build_tier_display(db, customer=cust, product=product)
        assert d.tier == "municipality"
        assert d.primary_label == "Contract Price"
        # 130 * 0.83 = 107.90. MAP doesn't clamp contract pricing under the
        # retail-only MAP rule (owner 2026-05-17).
        assert d.primary_amount == Decimal("107.90")
        assert d.contract_name == "Sourcewell via NAFG"
        assert d.map_clamped is False


class TestResolveForCustomer:
    @pytest.mark.asyncio
    async def test_resolve_for_customer_returns_priceresolution(self, seed_jobber_customer):
        db, brand, product, price, cust = seed_jobber_customer
        res = await resolve_for_customer(db, customer=cust, product=product, qty=1)
        assert res.price is not None
        # P3 jobber price = 130. MAP is no longer applied to contract pricing
        # (owner rule 2026-05-17: MAP is retail-only).
        assert res.price == Decimal("130")


@pytest_asyncio.fixture
async def seed_retail_customer(seed_brand_product):
    db, brand, product, price = seed_brand_product
    cust = Customer(
        customer_number="TEST-R1",
        name="Test Retail Customer",
        tier=CustomerTier.RETAIL,
    )
    db.add(cust)
    await db.commit()
    return db, brand, product, price, cust


# =========================================================================
# build_tier_display_batch parity — the batched browse path MUST produce the
# exact same TierPricingDisplay as the per-product build_tier_display it
# replaces. These guard the catalog N+1 fix against pricing drift.
# =========================================================================


class TestBuildTierDisplayBatchParity:
    async def _assert_parity(self, db, cust, product):
        """batch[product.id] must equal the per-product display, field for field."""
        per_product = await build_tier_display(db, customer=cust, product=product)
        batched = await build_tier_display_batch(db, customer=cust, products=[product])
        assert set(batched.keys()) == {product.id}
        assert batched[product.id].as_dict() == per_product.as_dict()

    @pytest.mark.asyncio
    async def test_empty_products_returns_empty_dict(self, seed_jobber_customer):
        db, brand, product, price, cust = seed_jobber_customer
        assert await build_tier_display_batch(db, customer=cust, products=[]) == {}

    @pytest.mark.asyncio
    async def test_jobber_no_contract_parity(self, seed_jobber_customer):
        db, brand, product, price, cust = seed_jobber_customer
        await self._assert_parity(db, cust, product)

    @pytest.mark.asyncio
    async def test_jobber_with_contract_parity(self, seed_jobber_customer):
        db, brand, product, price, cust = seed_jobber_customer
        db.add(Contract(
            customer_id=cust.id, name="Test contract", brand="YAK",
            priority=1, min_quantity=0, pricing_formula="P5/.95",
        ))
        await db.commit()
        await self._assert_parity(db, cust, product)

    @pytest.mark.asyncio
    async def test_muni_with_contract_parity(self, seed_muni_customer):
        db, brand, product, price, cust = seed_muni_customer
        db.add(Contract(
            customer_id=cust.id, name="Sourcewell via NAFG", brand="YAK",
            priority=1, min_quantity=0, pricing_formula="P3*.83",
        ))
        await db.commit()
        await self._assert_parity(db, cust, product)

    @pytest.mark.asyncio
    async def test_retail_tier_parity(self, seed_retail_customer):
        # Retail-tier logged-in shoppers get the sentinel-driven retail price;
        # batch and per-product both route through resolve_retail_for_products.
        db, brand, product, price, cust = seed_retail_customer
        await self._assert_parity(db, cust, product)
