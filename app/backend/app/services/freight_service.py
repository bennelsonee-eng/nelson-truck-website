"""Freight estimation — Phase 1 table-based.

Real-time FedEx/UPS API integration is Phase 2.  For now we use a simple
weight-tier ground rate that approximates real ship costs for the 90% case
(small accessory parts).  Items above 500 lb fall through to "quote required"
which the UI shows as a `Get Shipping Quote` flow.

Returns a `FreightEstimate` so callers can distinguish between "we computed
freight" and "we need a manual quote".
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


__all__ = [
    "FreightEstimate",
    "FreightStatus",
    "estimate_ground_freight",
    "WEIGHT_TIERS",
]


WEIGHT_TIERS: tuple[tuple[Decimal, Decimal], ...] = (
    # (max_weight_lb_inclusive, flat_rate_usd)
    (Decimal("10"),  Decimal("12.00")),
    (Decimal("50"),  Decimal("25.00")),
    (Decimal("150"), Decimal("55.00")),
    (Decimal("500"), Decimal("145.00")),
)


# Items above this weight require a manual quote (truck/freight-class shipping)
QUOTE_REQUIRED_OVER_LB = Decimal("500")


# Flat fallback rate when item_total is non-trivial but weight is unknown
DEFAULT_RATE_NO_WEIGHT = Decimal("18.00")


class FreightStatus:
    OK = "ok"
    QUOTE_REQUIRED = "quote_required"
    FREE = "free"  # placeholder for future "free shipping over $X" promo


@dataclass(frozen=True)
class FreightEstimate:
    status: str
    amount: Decimal
    notes: list[str]


def estimate_ground_freight(
    *,
    total_weight_lb: Decimal | None,
    item_total: Decimal,
    ship_to_state: str | None = None,
) -> FreightEstimate:
    """Estimate ground freight for a domestic shipment.

    Phase 1 ignores destination — same flat rates apply nationwide.  Phase 2
    will introduce zone-based pricing.

    A null/zero weight returns a default rate (so the UI still shows *some*
    number rather than $0 for products without weight data).
    """
    notes: list[str] = []

    if total_weight_lb is None or total_weight_lb <= 0:
        notes.append("No product weights on file — used default flat rate")
        return FreightEstimate(
            status=FreightStatus.OK, amount=DEFAULT_RATE_NO_WEIGHT, notes=notes
        )

    if total_weight_lb > QUOTE_REQUIRED_OVER_LB:
        notes.append(f"Total weight {total_weight_lb} lb exceeds {QUOTE_REQUIRED_OVER_LB} lb — manual freight quote required")
        return FreightEstimate(status=FreightStatus.QUOTE_REQUIRED, amount=Decimal("0"), notes=notes)

    for max_lb, rate in WEIGHT_TIERS:
        if total_weight_lb <= max_lb:
            notes.append(f"Weight tier ≤ {max_lb} lb")
            return FreightEstimate(status=FreightStatus.OK, amount=rate, notes=notes)

    # Defensive fallback — should be unreachable due to QUOTE_REQUIRED_OVER_LB
    return FreightEstimate(status=FreightStatus.OK, amount=WEIGHT_TIERS[-1][1], notes=notes)
