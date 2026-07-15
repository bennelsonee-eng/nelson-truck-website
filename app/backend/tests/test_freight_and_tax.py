"""Tests for freight + sales-tax services (Phase 1)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.freight_service import (
    DEFAULT_RATE_NO_WEIGHT,
    QUOTE_REQUIRED_OVER_LB,
    WEIGHT_TIERS,
    FreightStatus,
    estimate_ground_freight,
)
from app.services.tax_service import (
    WA_DEFAULT_RATE_X1000,
    estimate_sales_tax,
)


# =========================================================================
# Freight
# =========================================================================


class TestFreightWeightTiers:
    def test_zero_weight_uses_default_flat(self):
        e = estimate_ground_freight(total_weight_lb=Decimal("0"), item_total=Decimal("100"))
        assert e.status == FreightStatus.OK
        assert e.amount == DEFAULT_RATE_NO_WEIGHT
        assert any("default flat rate" in n for n in e.notes)

    def test_none_weight_uses_default_flat(self):
        e = estimate_ground_freight(total_weight_lb=None, item_total=Decimal("100"))
        assert e.amount == DEFAULT_RATE_NO_WEIGHT

    def test_under_10lb_first_tier(self):
        for w in ["1", "5", "9.99", "10"]:
            e = estimate_ground_freight(total_weight_lb=Decimal(w), item_total=Decimal("50"))
            assert e.status == FreightStatus.OK
            assert e.amount == WEIGHT_TIERS[0][1]

    def test_10_to_50lb_second_tier(self):
        e = estimate_ground_freight(total_weight_lb=Decimal("25"), item_total=Decimal("100"))
        assert e.amount == WEIGHT_TIERS[1][1]

    def test_50_to_150lb_third_tier(self):
        e = estimate_ground_freight(total_weight_lb=Decimal("100"), item_total=Decimal("500"))
        assert e.amount == WEIGHT_TIERS[2][1]

    def test_150_to_500lb_fourth_tier(self):
        e = estimate_ground_freight(total_weight_lb=Decimal("400"), item_total=Decimal("1000"))
        assert e.amount == WEIGHT_TIERS[3][1]

    def test_over_500lb_quote_required(self):
        e = estimate_ground_freight(total_weight_lb=Decimal("750"), item_total=Decimal("5000"))
        assert e.status == FreightStatus.QUOTE_REQUIRED
        assert e.amount == Decimal("0")
        assert any("manual freight quote required" in n for n in e.notes)

    def test_exactly_at_quote_threshold_uses_top_tier(self):
        e = estimate_ground_freight(total_weight_lb=QUOTE_REQUIRED_OVER_LB, item_total=Decimal("1"))
        # Equal to threshold — still in tier (≤ 500 lb), not over
        assert e.status == FreightStatus.OK

    def test_negative_weight_treated_as_zero(self):
        e = estimate_ground_freight(total_weight_lb=Decimal("-5"), item_total=Decimal("100"))
        assert e.amount == DEFAULT_RATE_NO_WEIGHT  # null/zero/negative all fall back


# =========================================================================
# Tax
# =========================================================================


class TestSalesTax:
    def test_wa_destination_applies_default_rate(self):
        t = estimate_sales_tax(taxable_subtotal=Decimal("100.00"), ship_to_state="WA")
        # 100 * 0.089 = 8.90
        assert t.amount == Decimal("8.90")
        assert t.rate_x1000 == WA_DEFAULT_RATE_X1000

    def test_wa_lowercase_still_matches(self):
        t = estimate_sales_tax(taxable_subtotal=Decimal("100"), ship_to_state="wa")
        assert t.rate_x1000 == WA_DEFAULT_RATE_X1000

    def test_oregon_destination_no_tax(self):
        t = estimate_sales_tax(taxable_subtotal=Decimal("100"), ship_to_state="OR")
        assert t.amount == Decimal("0")
        assert t.rate_x1000 == 0
        assert any("No nexus" in n for n in t.notes)

    def test_california_destination_no_tax(self):
        t = estimate_sales_tax(taxable_subtotal=Decimal("100"), ship_to_state="CA")
        assert t.amount == Decimal("0")

    def test_unknown_state_no_tax(self):
        t = estimate_sales_tax(taxable_subtotal=Decimal("100"), ship_to_state=None)
        assert t.amount == Decimal("0")

    def test_tax_exempt_customer_in_wa(self):
        t = estimate_sales_tax(
            taxable_subtotal=Decimal("100"),
            ship_to_state="WA",
            is_tax_exempt=True,
        )
        assert t.amount == Decimal("0")
        assert t.rate_x1000 == 0
        assert any("tax-exempt" in n for n in t.notes)

    def test_zero_subtotal_returns_zero_tax(self):
        t = estimate_sales_tax(taxable_subtotal=Decimal("0"), ship_to_state="WA")
        assert t.amount == Decimal("0")

    def test_tax_quantizes_to_two_decimals(self):
        # 33.33 * 0.089 = 2.96637 → 2.97
        t = estimate_sales_tax(taxable_subtotal=Decimal("33.33"), ship_to_state="WA")
        assert t.amount == Decimal("2.97")

    def test_large_subtotal_no_overflow(self):
        t = estimate_sales_tax(taxable_subtotal=Decimal("1000000.00"), ship_to_state="WA")
        # 1M * 0.089 = 89,000
        assert t.amount == Decimal("89000.00")
