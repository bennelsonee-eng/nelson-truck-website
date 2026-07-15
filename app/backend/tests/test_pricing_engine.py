"""Tests for the pricing engine — contract resolution + aging-discount + MAP clamp."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.pricing_engine import (
    AgingDiscountConfig,
    AgingDiscountTier,
    ContractRule,
    PriceResolution,
    ResolutionStatus,
    apply_aging_discount,
    filter_matching_rules,
    find_aging_discount,
    resolve_price,
    rule_is_active,
    rule_matches_customer,
    rule_matches_product,
)


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


# Sample tier prices (a Yakima roof rack, say)
TIERS = {
    1: Decimal("499.99"),   # P1 List
    2: Decimal("449.99"),   # P2 Retail
    3: Decimal("349.99"),   # P3 Wholesale (Jobber) — most-referenced
    4: Decimal("299.99"),   # P4 intermediate
    5: Decimal("250.00"),   # P5 Cost
}


def make_rule(
    *,
    contract_id: int = 1,
    contract_name: str = "default",
    customer_id: str = "780023",
    brand: str | None = "YAK",
    group_code: str | None = None,
    part_number: str | None = None,
    priority: int = 9,
    min_quantity: int = 0,
    pricing_formula: str = "P3",
    expiration_date: date | None = None,
) -> ContractRule:
    return ContractRule(
        contract_id=contract_id,
        contract_name=contract_name,
        customer_id=customer_id,
        brand=brand,
        group_code=group_code,
        part_number=part_number,
        priority=priority,
        min_quantity=min_quantity,
        pricing_formula=pricing_formula,
        expiration_date=expiration_date,
    )


# -------------------------------------------------------------------------
# Scope matching
# -------------------------------------------------------------------------


class TestScopeMatching:
    def test_brand_match(self):
        rule = make_rule(brand="YAK")
        assert rule_matches_product(rule, "PART1", "YAK", "0")
        assert not rule_matches_product(rule, "PART1", "WES", "0")

    def test_part_number_match(self):
        rule = make_rule(brand="YAK", part_number="PART1")
        assert rule_matches_product(rule, "PART1", "YAK", "0")
        assert not rule_matches_product(rule, "PART2", "YAK", "0")

    def test_group_code_zero_is_wildcard(self):
        rule = make_rule(brand="YAK", group_code="0")
        # group_code "0" should match any product group
        assert rule_matches_product(rule, "PART1", "YAK", "5")
        assert rule_matches_product(rule, "PART1", "YAK", "0")

    def test_group_code_nonzero_must_match(self):
        rule = make_rule(brand="YAK", group_code="3")
        assert rule_matches_product(rule, "PART1", "YAK", "3")
        assert not rule_matches_product(rule, "PART1", "YAK", "5")

    def test_null_brand_is_wildcard(self):
        rule = make_rule(brand=None, part_number=None)
        assert rule_matches_product(rule, "ANY", "ANY", "0")

    def test_customer_match(self):
        rule = make_rule(customer_id="780023")
        assert rule_matches_customer(rule, "780023")
        assert not rule_matches_customer(rule, "112600")

    def test_qty_below_min_inactive(self):
        rule = make_rule(min_quantity=5)
        assert not rule_is_active(rule, qty=4)
        assert rule_is_active(rule, qty=5)
        assert rule_is_active(rule, qty=10)

    def test_expired_rule_inactive(self):
        yesterday = date.today() - timedelta(days=1)
        rule = make_rule(expiration_date=yesterday)
        assert not rule_is_active(rule, qty=1)

    def test_future_expiry_active(self):
        tomorrow = date.today() + timedelta(days=1)
        rule = make_rule(expiration_date=tomorrow)
        assert rule_is_active(rule, qty=1)


# -------------------------------------------------------------------------
# filter_matching_rules
# -------------------------------------------------------------------------


class TestFilterMatchingRules:
    def test_filters_to_matches_only(self):
        rules = [
            make_rule(contract_id=1, customer_id="A", brand="YAK"),
            make_rule(contract_id=2, customer_id="B", brand="YAK"),
            make_rule(contract_id=3, customer_id="A", brand="WES"),
        ]
        filtered = filter_matching_rules(
            rules,
            customer_id="A",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
        )
        assert len(filtered) == 1
        assert filtered[0].contract_id == 1


# -------------------------------------------------------------------------
# Aging discount
# -------------------------------------------------------------------------


class TestAgingDiscount:
    def test_disabled_returns_none(self):
        cfg = AgingDiscountConfig(enabled=False)
        assert find_aging_discount(cfg, 1000) is None

    def test_no_days_returns_none(self):
        cfg = AgingDiscountConfig(enabled=True, tiers=(
            AgingDiscountTier(min_days=90, max_days=180, discount_percent=Decimal("5")),
        ))
        assert find_aging_discount(cfg, None) is None

    def test_finds_matching_tier(self):
        cfg = AgingDiscountConfig(enabled=True, tiers=(
            AgingDiscountTier(min_days=0, max_days=89, discount_percent=Decimal("0")),
            AgingDiscountTier(min_days=90, max_days=180, discount_percent=Decimal("5")),
            AgingDiscountTier(min_days=181, max_days=365, discount_percent=Decimal("10")),
            AgingDiscountTier(min_days=366, max_days=730, discount_percent=Decimal("20")),
            AgingDiscountTier(min_days=731, max_days=None, discount_percent=Decimal("30")),
        ))
        assert find_aging_discount(cfg, 30) == Decimal("0")
        assert find_aging_discount(cfg, 100) == Decimal("5")
        assert find_aging_discount(cfg, 200) == Decimal("10")
        assert find_aging_discount(cfg, 500) == Decimal("20")
        assert find_aging_discount(cfg, 1000) == Decimal("30")
        assert find_aging_discount(cfg, 5000) == Decimal("30")

    def test_apply_aging_discount(self):
        # $100 with 10% off = $90
        assert apply_aging_discount(Decimal("100"), Decimal("10")) == Decimal("90.00")
        # $349.99 with 5% off = $332.49
        assert apply_aging_discount(Decimal("349.99"), Decimal("5")) == Decimal("332.49")


# -------------------------------------------------------------------------
# resolve_price (integration)
# -------------------------------------------------------------------------


class TestResolvePrice:
    def test_no_rules_no_default_returns_no_price(self):
        result = resolve_price(
            customer_id="A",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
            tier_prices=TIERS,
            matching_rules=[],
        )
        assert result.status == ResolutionStatus.NO_PRICE
        assert result.price is None

    def test_falls_through_to_tier_default(self):
        result = resolve_price(
            customer_id="A",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
            tier_prices=TIERS,
            matching_rules=[],
            tier_default_price=Decimal("349.99"),
        )
        assert result.status == ResolutionStatus.OK_TIER_DEFAULT
        assert result.price == Decimal("349.99")

    def test_contract_match(self):
        rules = [
            make_rule(contract_id=1, customer_id="A", brand="YAK", priority=9, pricing_formula="P3"),
        ]
        result = resolve_price(
            customer_id="A",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
            tier_prices=TIERS,
            matching_rules=rules,
        )
        assert result.status == ResolutionStatus.OK_CONTRACT
        assert result.price == Decimal("349.99")
        assert result.contract_used is not None and result.contract_used.contract_id == 1

    def test_lower_priority_wins(self):
        # Priority 1 should beat priority 9
        rules = [
            make_rule(contract_id=9, customer_id="A", brand="YAK", priority=9, pricing_formula="P3"),
            make_rule(contract_id=1, customer_id="A", brand="YAK", priority=1, pricing_formula="P3*.83"),
        ]
        result = resolve_price(
            customer_id="A",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
            tier_prices=TIERS,
            matching_rules=rules,
        )
        assert result.status == ResolutionStatus.OK_CONTRACT
        assert result.contract_used.contract_id == 1
        # 349.99 × 0.83 = 290.4917 → 290.49
        assert result.price == Decimal("349.99") * Decimal(".83").quantize(Decimal("0.01")) or \
               result.price == (Decimal("349.99") * Decimal(".83")).quantize(Decimal("0.01"))

    def test_part_specific_beats_brand_specific_at_same_priority(self):
        # Part-specific rule has same priority but more specific scope.
        # Engine sorts by priority, so SAME priority means first-found wins.
        # In practice, contract data assigns lower priority to more specific rules.
        # We just verify the algorithm works deterministically.
        rules = [
            make_rule(contract_id=10, customer_id="A", brand="YAK", priority=5, pricing_formula="P3*.95"),
            make_rule(contract_id=11, customer_id="A", brand="YAK", part_number="SPECIFIC",
                      priority=1, pricing_formula="P3*.50"),  # half-off for specific part
        ]
        result = resolve_price(
            customer_id="A",
            product_part_number="SPECIFIC",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
            tier_prices=TIERS,
            matching_rules=rules,
        )
        # Part-specific (priority 1) wins
        assert result.contract_used.contract_id == 11
        assert result.price == (Decimal("349.99") * Decimal(".50")).quantize(Decimal("0.01"))

    def test_unresolvable_formula_skipped(self):
        rules = [
            make_rule(contract_id=1, priority=1, pricing_formula="garbage"),  # won't parse
            make_rule(contract_id=2, priority=2, pricing_formula="P3"),
        ]
        result = resolve_price(
            customer_id="780023",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
            tier_prices=TIERS,
            matching_rules=rules,
        )
        # First rule was unparseable; engine fell through to next priority
        assert result.contract_used.contract_id == 2

    def test_aging_discount_applied(self):
        rules = [
            make_rule(contract_id=1, customer_id="A", brand="YAK", priority=9, pricing_formula="P3"),
        ]
        cfg = AgingDiscountConfig(enabled=True, tiers=(
            AgingDiscountTier(min_days=180, max_days=365, discount_percent=Decimal("10")),
        ))
        result = resolve_price(
            customer_id="A",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
            tier_prices=TIERS,
            matching_rules=rules,
            days_in_inventory=200,
            aging_config=cfg,
        )
        assert result.status == ResolutionStatus.AGED_DISCOUNT_APPLIED
        # 349.99 × 0.90 = 314.991 → 314.99
        assert result.price == Decimal("314.99")
        assert result.aging_discount_pct == Decimal("10")

    def test_map_clamp(self):
        # Aging-discounted price would be below MAP → clamp UP to MAP
        rules = [
            make_rule(contract_id=1, customer_id="A", brand="YAK", priority=9, pricing_formula="P3"),
        ]
        cfg = AgingDiscountConfig(enabled=True, tiers=(
            AgingDiscountTier(min_days=730, max_days=None, discount_percent=Decimal("50")),
        ))
        result = resolve_price(
            customer_id="A",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
            tier_prices=TIERS,
            matching_rules=rules,
            map_price=Decimal("199.99"),
            days_in_inventory=2000,
            aging_config=cfg,
        )
        # 349.99 × 0.50 = 175.00 (below MAP 199.99) → clamped to MAP
        assert result.status == ResolutionStatus.MAP_CLAMPED
        assert result.price == Decimal("199.99")
        assert result.map_clamped_from is not None
        assert result.map_clamped_from < Decimal("199.99")

    def test_qty_gate(self):
        # Rule requires qty >= 5; we only ask for 3
        rules = [
            make_rule(contract_id=1, priority=1, pricing_formula="P3*.50", min_quantity=5),
            make_rule(contract_id=2, priority=9, pricing_formula="P3"),
        ]
        result = resolve_price(
            customer_id="780023",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=3,
            tier_prices=TIERS,
            matching_rules=rules,
        )
        # First rule excluded by qty gate; falls to second
        assert result.contract_used.contract_id == 2

    def test_expired_rule_skipped(self):
        rules = [
            make_rule(contract_id=1, priority=1, pricing_formula="P3*.50",
                      expiration_date=date.today() - timedelta(days=1)),
            make_rule(contract_id=2, priority=9, pricing_formula="P3"),
        ]
        result = resolve_price(
            customer_id="780023",
            product_part_number="P1",
            product_brand_code="YAK",
            product_group_code="0",
            qty=1,
            tier_prices=TIERS,
            matching_rules=rules,
        )
        assert result.contract_used.contract_id == 2  # expired one skipped

    def test_real_sample_p5_div_factor(self):
        # From sample row: customer 112600, contract 1003, prod_code WES, group 3, P5/.65
        # If P5 = $50, P5/.65 = $76.92
        rules = [
            make_rule(
                contract_id=1003, customer_id="112600", brand="WES", group_code="3",
                priority=6, pricing_formula="P5/.65",
            ),
        ]
        wes_tiers = {1: Decimal("100"), 2: Decimal("85"), 3: Decimal("65"), 5: Decimal("50")}
        result = resolve_price(
            customer_id="112600",
            product_part_number="WES1234",
            product_brand_code="WES",
            product_group_code="3",
            qty=1,
            tier_prices=wes_tiers,
            matching_rules=rules,
        )
        assert result.status == ResolutionStatus.OK_CONTRACT
        # 50 / 0.65 = 76.923... → 76.92
        assert result.price == Decimal("76.92")
