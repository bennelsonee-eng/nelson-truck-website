"""Tests for the pricing formula parser + applier.

Covers all four formula classes observed in production contracts data
(per `discovery/notes/07_wsm_catalog_analysis.md` and the
`contracts_copy.csv` analyzer output).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.pricing_formula import (
    FormulaKind,
    apply_formula,
    parse_formula,
    resolve,
)


# Sample tier prices for one part — based on the kind of values nte_parts_master holds
SAMPLE_TIERS = {
    1: Decimal("199.99"),   # P1 = List
    2: Decimal("169.99"),   # P2 = Retail
    3: Decimal("119.99"),   # P3 = Wholesale (Jobber)
    4: Decimal("99.99"),    # P4 = intermediate
    5: Decimal("75.00"),    # P5 = Cost
}


# -------------------------------------------------------------------------
# Parsing
# -------------------------------------------------------------------------


class TestParseFormula:
    def test_tier_only(self):
        f = parse_formula("P3")
        assert f.kind == FormulaKind.TIER_ONLY
        assert f.tier == 3
        assert f.factor is None
        assert f.fixed is None

    def test_tier_only_lowercase(self):
        f = parse_formula("p3")
        assert f.kind == FormulaKind.TIER_ONLY
        assert f.tier == 3

    def test_tier_only_with_whitespace(self):
        f = parse_formula("  P5  ")
        assert f.kind == FormulaKind.TIER_ONLY
        assert f.tier == 5

    def test_tier_x_factor(self):
        f = parse_formula("P3*.83")
        assert f.kind == FormulaKind.TIER_X_FACTOR
        assert f.tier == 3
        assert f.factor == Decimal(".83")

    def test_tier_x_factor_with_leading_zero(self):
        f = parse_formula("P4*0.95")
        assert f.kind == FormulaKind.TIER_X_FACTOR
        assert f.tier == 4
        assert f.factor == Decimal("0.95")

    def test_tier_x_factor_above_one(self):
        f = parse_formula("P4*1.1")
        assert f.kind == FormulaKind.TIER_X_FACTOR
        assert f.tier == 4
        assert f.factor == Decimal("1.1")

    def test_tier_div_factor(self):
        f = parse_formula("P5/.65")
        assert f.kind == FormulaKind.TIER_DIV_FACTOR
        assert f.tier == 5
        assert f.factor == Decimal(".65")

    def test_tier_div_factor_zero_is_unknown(self):
        f = parse_formula("P5/0")
        assert f.kind == FormulaKind.UNKNOWN

    def test_fixed_with_decimal(self):
        f = parse_formula("135.00")
        assert f.kind == FormulaKind.FIXED
        assert f.fixed == Decimal("135.00")

    def test_fixed_without_decimal(self):
        f = parse_formula("300")
        assert f.kind == FormulaKind.FIXED
        assert f.fixed == Decimal("300")

    def test_fixed_with_dollar(self):
        f = parse_formula("$250.00")
        assert f.kind == FormulaKind.FIXED
        assert f.fixed == Decimal("250.00")

    def test_empty_is_unknown(self):
        assert parse_formula("").kind == FormulaKind.UNKNOWN
        assert parse_formula("   ").kind == FormulaKind.UNKNOWN
        assert parse_formula(None).kind == FormulaKind.UNKNOWN  # type: ignore[arg-type]

    def test_garbage_is_unknown(self):
        assert parse_formula("hello").kind == FormulaKind.UNKNOWN
        assert parse_formula("P3+P5").kind == FormulaKind.UNKNOWN  # complex, Phase 2
        assert parse_formula("Pi*.83").kind == FormulaKind.UNKNOWN  # not a digit


# -------------------------------------------------------------------------
# Application
# -------------------------------------------------------------------------


class TestApplyFormula:
    def test_tier_only(self):
        f = parse_formula("P3")
        assert apply_formula(f, SAMPLE_TIERS) == Decimal("119.99")

    def test_tier_x_factor(self):
        f = parse_formula("P3*.83")
        # 119.99 * 0.83 = 99.5917
        assert apply_formula(f, SAMPLE_TIERS) == Decimal("119.99") * Decimal(".83")

    def test_tier_div_factor_cost_markup(self):
        f = parse_formula("P5/.65")
        # 75.00 / 0.65 = 115.3846... — cost-plus markup
        result = apply_formula(f, SAMPLE_TIERS)
        assert result is not None
        assert result == Decimal("75.00") / Decimal(".65")

    def test_fixed(self):
        f = parse_formula("135.00")
        assert apply_formula(f, SAMPLE_TIERS) == Decimal("135.00")

    def test_missing_tier_returns_none(self):
        # Reference P9 which doesn't exist in our sample tiers
        f = parse_formula("P9")
        assert apply_formula(f, SAMPLE_TIERS) is None

    def test_none_tier_value_returns_none(self):
        # P3 is None on the part (e.g., not set)
        partial = {1: Decimal("100"), 3: None, 5: Decimal("50")}
        f = parse_formula("P3*.83")
        assert apply_formula(f, partial) is None

    def test_unknown_returns_none(self):
        f = parse_formula("garbage")
        assert apply_formula(f, SAMPLE_TIERS) is None


# -------------------------------------------------------------------------
# resolve() convenience
# -------------------------------------------------------------------------


class TestResolve:
    def test_basic(self):
        assert resolve("P3", SAMPLE_TIERS) == Decimal("119.99")

    def test_factor(self):
        assert resolve("P3*.83", SAMPLE_TIERS) == Decimal("119.99") * Decimal(".83")

    def test_div(self):
        assert resolve("P5/.65", SAMPLE_TIERS) == Decimal("75.00") / Decimal(".65")

    def test_fixed(self):
        assert resolve("135.00", SAMPLE_TIERS) == Decimal("135.00")

    def test_garbage(self):
        assert resolve("nonsense", SAMPLE_TIERS) is None


# -------------------------------------------------------------------------
# Real-data samples (from contracts_copy analysis)
# -------------------------------------------------------------------------


class TestRealSamples:
    """Spot-check against actual production formulas observed in contracts_copy.csv."""

    @pytest.mark.parametrize("formula,expected_kind", [
        ("P3", FormulaKind.TIER_ONLY),         # 51% of all rules
        ("P3*.83", FormulaKind.TIER_X_FACTOR),
        ("P4*1.1", FormulaKind.TIER_X_FACTOR),
        ("P3*.95", FormulaKind.TIER_X_FACTOR),
        ("P2*.95", FormulaKind.TIER_X_FACTOR),
        ("P3*.97", FormulaKind.TIER_X_FACTOR),
        ("P5/.81", FormulaKind.TIER_DIV_FACTOR),
        ("P5/.7", FormulaKind.TIER_DIV_FACTOR),
        ("P5/.75", FormulaKind.TIER_DIV_FACTOR),
        ("P5/.65", FormulaKind.TIER_DIV_FACTOR),
        ("P5/.8", FormulaKind.TIER_DIV_FACTOR),
        ("P4*.95", FormulaKind.TIER_X_FACTOR),
        ("P1", FormulaKind.TIER_ONLY),
        ("P4", FormulaKind.TIER_ONLY),
        ("P5", FormulaKind.TIER_ONLY),
        ("135.00", FormulaKind.FIXED),
        ("511.9", FormulaKind.FIXED),
        ("300", FormulaKind.FIXED),
        ("120", FormulaKind.FIXED),
        ("475", FormulaKind.FIXED),
    ])
    def test_real_formula_classification(self, formula: str, expected_kind: FormulaKind):
        assert parse_formula(formula).kind == expected_kind
