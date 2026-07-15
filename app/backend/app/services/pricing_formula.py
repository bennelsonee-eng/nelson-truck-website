"""Pricing formula parser — interprets the Titan contracts DSL.

Formulas observed in production data (`contracts_copy`):
  - "P3"          — use tier 3 price as-is
  - "P3*.83"      — tier 3 × 0.83  (17% off)
  - "P5/.65"      — tier 5 ÷ 0.65  (cost / divisor for a markup)
  - "P4*1.1"     — tier 4 × 1.10  (10% above)
  - "135.00"      — fixed price
  - "300"         — fixed price (no decimal)

Tier numbers found in production: P1, P2, P3, P4, P5
  P1 = List
  P2 = Retail
  P3 = Wholesale (Jobber tier — most common in contracts)
  P4 = (intermediate)
  P5 = Cost
(Per Nelson convention from CLAUDE.md; verify with user when sample resolutions land.)

Resolution returns a Decimal price or None if parsing fails. Caller decides
how to handle None (skip rule, fall through to next priority, etc).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping


__all__ = [
    "FormulaKind",
    "ParsedFormula",
    "TierPrices",
    "parse_formula",
    "apply_formula",
    "resolve",
]


class FormulaKind(str, Enum):
    """Classification of a pricing formula."""

    TIER_ONLY = "tier_only"           # "P3"
    TIER_X_FACTOR = "tier_x_factor"   # "P3*.83"
    TIER_DIV_FACTOR = "tier_div_factor"  # "P5/.65"
    FIXED = "fixed"                    # "135.00"
    UNKNOWN = "unknown"                # anything we don't recognize


@dataclass(frozen=True)
class ParsedFormula:
    """A pricing formula in structured form.

    For TIER_ONLY: tier=N, factor=None, fixed=None.
    For TIER_X_FACTOR / TIER_DIV_FACTOR: tier=N, factor=Decimal, fixed=None.
    For FIXED: tier=None, factor=None, fixed=Decimal.
    For UNKNOWN: all None; original_text preserved.
    """

    kind: FormulaKind
    tier: int | None
    factor: Decimal | None
    fixed: Decimal | None
    original_text: str

    def is_resolvable(self) -> bool:
        return self.kind != FormulaKind.UNKNOWN


# Type alias: per-part tier prices, e.g., {1: Decimal("199.99"), 2: ..., 5: ...}
TierPrices = Mapping[int, Decimal | None]


# --- Parsing ----------------------------------------------------------------

# Strict patterns — case-insensitive on P
_TIER_ONLY = re.compile(r"^\s*P(\d+)\s*$", re.IGNORECASE)
_TIER_X_FACTOR = re.compile(r"^\s*P(\d+)\s*\*\s*([+-]?\.?\d+(?:\.\d+)?)\s*$", re.IGNORECASE)
_TIER_DIV_FACTOR = re.compile(r"^\s*P(\d+)\s*/\s*([+-]?\.?\d+(?:\.\d+)?)\s*$", re.IGNORECASE)
_FIXED = re.compile(r"^\s*\$?\s*([+-]?\.?\d+(?:\.\d+)?)\s*$")


def parse_formula(text: str) -> ParsedFormula:
    """Parse a formula string into a ParsedFormula. Never raises."""
    if text is None:
        return ParsedFormula(FormulaKind.UNKNOWN, None, None, None, "")
    s = str(text).strip()
    if not s:
        return ParsedFormula(FormulaKind.UNKNOWN, None, None, None, s)

    m = _TIER_ONLY.match(s)
    if m:
        return ParsedFormula(
            FormulaKind.TIER_ONLY,
            tier=int(m.group(1)),
            factor=None,
            fixed=None,
            original_text=s,
        )

    m = _TIER_X_FACTOR.match(s)
    if m:
        try:
            return ParsedFormula(
                FormulaKind.TIER_X_FACTOR,
                tier=int(m.group(1)),
                factor=Decimal(m.group(2)),
                fixed=None,
                original_text=s,
            )
        except InvalidOperation:
            pass

    m = _TIER_DIV_FACTOR.match(s)
    if m:
        try:
            factor = Decimal(m.group(2))
            if factor == 0:
                # Division by zero — treat as unknown
                return ParsedFormula(FormulaKind.UNKNOWN, None, None, None, s)
            return ParsedFormula(
                FormulaKind.TIER_DIV_FACTOR,
                tier=int(m.group(1)),
                factor=factor,
                fixed=None,
                original_text=s,
            )
        except InvalidOperation:
            pass

    m = _FIXED.match(s)
    if m:
        try:
            return ParsedFormula(
                FormulaKind.FIXED,
                tier=None,
                factor=None,
                fixed=Decimal(m.group(1)),
                original_text=s,
            )
        except InvalidOperation:
            pass

    return ParsedFormula(FormulaKind.UNKNOWN, None, None, None, s)


# --- Application -----------------------------------------------------------


def apply_formula(formula: ParsedFormula, tier_prices: TierPrices) -> Decimal | None:
    """Evaluate a parsed formula against a part's tier prices.

    Returns None if:
    - formula is UNKNOWN
    - formula references a tier that's missing from tier_prices
    - the referenced tier price is None (not set on the part)
    """
    if formula.kind == FormulaKind.FIXED:
        return formula.fixed

    if formula.kind == FormulaKind.UNKNOWN:
        return None

    if formula.tier is None:
        return None

    base = tier_prices.get(formula.tier)
    if base is None:
        return None

    if formula.kind == FormulaKind.TIER_ONLY:
        return Decimal(base)

    if formula.kind == FormulaKind.TIER_X_FACTOR:
        return Decimal(base) * formula.factor  # type: ignore[arg-type]

    if formula.kind == FormulaKind.TIER_DIV_FACTOR:
        return Decimal(base) / formula.factor  # type: ignore[operator]

    return None


def resolve(text: str, tier_prices: TierPrices) -> Decimal | None:
    """Convenience: parse + apply in one call."""
    return apply_formula(parse_formula(text), tier_prices)
