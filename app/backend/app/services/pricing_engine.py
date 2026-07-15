"""Pricing engine — contract-aware price resolution.

Pure-function design: takes pre-loaded inputs, returns resolved price + traceability.
The DB-querying wrapper lives in `pricing_service.py`.

Resolution order (per addendum 003 + user clarifications 2026-04-25):
  1. Filter contract rules to matching ones (customer, scope, qty, not-expired)
  2. Sort by priority ASC (LOWER number wins per user — "Priority 1 beats Priority 9")
  3. Apply top-priority rule's formula via pricing_formula parser
  4. If no contract matches → fall through to tier-default price
  5. Apply aging-discount overlay (FS-080) if configured + days threshold met
  6. Apply MAP enforcement — clamp final to MAP minimum if MAP enforced

Returns a `PriceResolution` with final price + traceability (which rule, which step).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Mapping, Sequence

from app.services.pricing_formula import (
    FormulaKind,
    apply_formula,
    parse_formula,
)


__all__ = [
    "ContractRule",
    "PriceResolution",
    "ResolutionStatus",
    "AgingDiscountTier",
    "AgingDiscountConfig",
    "resolve_price",
]


class ResolutionStatus(str, Enum):
    """Outcome category for a price resolution."""

    OK_CONTRACT = "ok_contract"           # Resolved via a matching contract rule
    OK_TIER_DEFAULT = "ok_tier_default"   # No contract matched; used the customer-tier default
    MAP_CLAMPED = "map_clamped"           # Resolved but clamped UP to MAP floor
    AGED_DISCOUNT_APPLIED = "aged_discount_applied"  # Aging overlay reduced the price (FS-080)
    NO_PRICE = "no_price"                 # Could not resolve (no contract, no tier default, no nothing)


@dataclass(frozen=True)
class ContractRule:
    """A pre-loaded contract row for resolution.

    Mirrors the columns from `contracts_copy` (Titan production schema):
      cust_id, contract, ourparts_num, prod_code, group_code,
      priority, min_quantity, exp_date, discount(=formula)

    Used as a value object — the engine doesn't query DB; caller pre-filters.
    """

    contract_id: int                       # Internal Contract.id (for tracing)
    contract_name: str                     # Human-readable e.g. "Sourcewell via NAFG"
    customer_id: str                       # Match key (cust_id from contracts_copy)
    brand: str | None                      # prod_code in contracts_copy
    group_code: str | None                 # group_code in contracts_copy
    part_number: str | None                # ourparts_num in contracts_copy
    priority: int                          # Lower wins
    min_quantity: int                      # qty gate
    pricing_formula: str                   # The DSL string ("P3*.83" etc.)
    expiration_date: date | None           # None = never expires


@dataclass(frozen=True)
class AgingDiscountTier:
    """One row in the aging-discount config table (FS-080)."""

    min_days: int               # apply if days_in_inventory >= min_days
    max_days: int | None        # None = no upper bound
    discount_percent: Decimal   # 0-100, e.g. Decimal("10") = 10% off


@dataclass(frozen=True)
class AgingDiscountConfig:
    """Configurable in CMS by Admin (FS-080)."""

    enabled: bool = False
    tiers: tuple[AgingDiscountTier, ...] = ()


@dataclass(frozen=True)
class PriceResolution:
    """The full traced result of a price resolution."""

    price: Decimal | None                 # Final price (None if NO_PRICE)
    status: ResolutionStatus
    base_price: Decimal | None = None     # Pre-overlay price
    contract_used: ContractRule | None = None
    aging_discount_pct: Decimal | None = None
    map_clamped_from: Decimal | None = None
    notes: list[str] = field(default_factory=list)


# -------------------------------------------------------------------------
# Scope matching
# -------------------------------------------------------------------------


def rule_matches_product(
    rule: ContractRule,
    product_part_number: str | None,
    product_brand_code: str | None,
    product_group_code: str | None,
) -> bool:
    """Does this rule's scope match this product?

    Empty/None rule fields = "wildcard for this dimension".
    All non-null rule dimensions must match the product. (AND semantics.)
    """
    if rule.part_number and rule.part_number != product_part_number:
        return False
    if rule.brand and rule.brand != product_brand_code:
        return False
    if rule.group_code and rule.group_code != "0" and rule.group_code != product_group_code:
        return False
    return True


def rule_matches_customer(rule: ContractRule, customer_id: str) -> bool:
    """Does this rule apply to this customer?"""
    return rule.customer_id == customer_id


def rule_is_active(rule: ContractRule, qty: int, today: date | None = None) -> bool:
    """qty + expiration check."""
    if today is None:
        from datetime import date as _date
        today = _date.today()
    if qty < rule.min_quantity:
        return False
    if rule.expiration_date is not None and rule.expiration_date < today:
        return False
    return True


def filter_matching_rules(
    rules: Sequence[ContractRule],
    customer_id: str,
    product_part_number: str | None,
    product_brand_code: str | None,
    product_group_code: str | None,
    qty: int,
    today: date | None = None,
) -> list[ContractRule]:
    """Pre-filter applicable rules. Caller can pass a smaller pre-filtered list
    from a DB query to keep this fast even with 605K total rules."""
    return [
        r for r in rules
        if rule_matches_customer(r, customer_id)
        and rule_matches_product(r, product_part_number, product_brand_code, product_group_code)
        and rule_is_active(r, qty, today)
    ]


# -------------------------------------------------------------------------
# Aging-discount overlay (FS-080)
# -------------------------------------------------------------------------


def find_aging_discount(
    config: AgingDiscountConfig,
    days_in_inventory: int | None,
) -> Decimal | None:
    """Return the matching aging-discount percentage (0–100) or None if no match / disabled."""
    if not config.enabled:
        return None
    if days_in_inventory is None:
        return None
    for tier in config.tiers:
        if days_in_inventory < tier.min_days:
            continue
        if tier.max_days is not None and days_in_inventory > tier.max_days:
            continue
        return tier.discount_percent
    return None


def apply_aging_discount(price: Decimal, discount_percent: Decimal) -> Decimal:
    """price - (price × pct/100), rounded to 2 decimals."""
    factor = (Decimal(100) - discount_percent) / Decimal(100)
    return (price * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# -------------------------------------------------------------------------
# Main resolution
# -------------------------------------------------------------------------


def resolve_price(
    *,
    customer_id: str,
    product_part_number: str | None,
    product_brand_code: str | None,
    product_group_code: str | None,
    qty: int,
    tier_prices: Mapping[int, Decimal | None],
    matching_rules: Sequence[ContractRule],
    tier_default_price: Decimal | None = None,
    map_price: Decimal | None = None,
    days_in_inventory: int | None = None,
    aging_config: AgingDiscountConfig = AgingDiscountConfig(),
    today: date | None = None,
) -> PriceResolution:
    """Resolve the final price for (customer, product, qty).

    Args:
        customer_id: cust_id from contracts table.
        product_part_number: ourparts_num.
        product_brand_code: prod_code (e.g., "YAK", "WES").
        product_group_code: group_code (e.g., "2", "3"; "0" is wildcard).
        qty: quantity being priced.
        tier_prices: this part's P1-P5 from nte_parts_master, e.g.
            {1: Decimal("199.99"), 2: ..., 3: ..., 4: ..., 5: Decimal("75")}.
        matching_rules: contract rules pre-filtered by the caller (typically
            a DB query for "all rules for this customer + brand + part").
            The engine does an additional in-memory filter to be safe.
        tier_default_price: fallback if no contract matches (e.g., the
            customer-tier baseline from ProductPrice).
        map_price: optional MAP floor — final price clamped UP to this.
        days_in_inventory: from tte_inv_days; drives FS-080 aging discount.
        aging_config: thresholds + percentages.
        today: date for expiration check (default = today).

    Returns:
        PriceResolution with final price + traceability.
    """
    notes: list[str] = []

    # Step 1+2+3 — filter, sort, take winner
    applicable = filter_matching_rules(
        matching_rules,
        customer_id=customer_id,
        product_part_number=product_part_number,
        product_brand_code=product_brand_code,
        product_group_code=product_group_code,
        qty=qty,
        today=today,
    )
    applicable.sort(key=lambda r: r.priority)  # ASC — lower wins

    base_price: Decimal | None = None
    used_rule: ContractRule | None = None
    status: ResolutionStatus

    for rule in applicable:
        formula = parse_formula(rule.pricing_formula)
        candidate = apply_formula(formula, tier_prices)
        if candidate is None:
            notes.append(f"rule {rule.contract_id} formula '{rule.pricing_formula}' unresolvable; skipping")
            continue
        base_price = candidate
        used_rule = rule
        break  # first resolvable wins

    if base_price is not None and used_rule is not None:
        status = ResolutionStatus.OK_CONTRACT
    elif tier_default_price is not None:
        base_price = tier_default_price
        status = ResolutionStatus.OK_TIER_DEFAULT
        notes.append("no contract matched; used tier default price")
    else:
        return PriceResolution(
            price=None,
            status=ResolutionStatus.NO_PRICE,
            notes=notes + ["no contract matched and no tier default available"],
        )

    # Round base price to 2 decimals (carry through formula fractional results)
    base_price = base_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    final = base_price
    aging_pct: Decimal | None = None

    # Step 5 — aging-discount overlay (FS-080)
    aging_pct = find_aging_discount(aging_config, days_in_inventory)
    if aging_pct is not None and aging_pct > 0:
        discounted = apply_aging_discount(final, aging_pct)
        if discounted < final:
            final = discounted
            status = ResolutionStatus.AGED_DISCOUNT_APPLIED
            notes.append(f"aging discount {aging_pct}% applied (days={days_in_inventory})")

    # Step 6 — MAP clamp (final cannot go below MAP if MAP set)
    map_clamped_from: Decimal | None = None
    if map_price is not None and final < map_price:
        map_clamped_from = final
        final = map_price
        status = ResolutionStatus.MAP_CLAMPED
        notes.append(f"MAP enforcement: clamped from {map_clamped_from} to {map_price}")

    return PriceResolution(
        price=final,
        status=status,
        base_price=base_price,
        contract_used=used_rule,
        aging_discount_pct=aging_pct if aging_pct and aging_pct > 0 else None,
        map_clamped_from=map_clamped_from,
        notes=notes,
    )
