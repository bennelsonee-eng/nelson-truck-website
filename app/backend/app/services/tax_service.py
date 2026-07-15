"""Sales tax estimation — Phase 1 destination-based simplified.

Phase 1 model:
  * Ship-to state = WA → apply flat WA combined rate (state 6.5% + ~2.4% local
    average = ~8.9%).  This matches what the existing PHP web checkout does.
    The ZIP-level WA-DOR rate database lands in Phase 1.5 (port from Nelson ERP
    `wa_tax_rates` table — see `load_wa_tax_rates.py`).
  * Ship-to state ≠ WA → 0 tax (Titan doesn't currently have nexus elsewhere).
  * Tax-exempt customers → 0 tax regardless.

The IMS315 export uses `tax_rate_x1000` integer (e.g., 89 = 8.9%).  We return
both the dollar amount AND the rate-x1000 so the FACS file is internally
consistent.

Returns ``None`` for `tax_amount` when the caller passed an unknown state code
(so they can decide between "show zero" or "block checkout until address is
clean").
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


__all__ = [
    "TaxEstimate",
    "WA_DEFAULT_RATE_X1000",
    "estimate_sales_tax",
]


# WA state 6.5% + average ~2.4% local destination = ~8.9%
WA_DEFAULT_RATE_X1000 = 89


@dataclass(frozen=True)
class TaxEstimate:
    amount: Decimal
    rate_x1000: int
    notes: list[str]


def estimate_sales_tax(
    *,
    taxable_subtotal: Decimal,
    ship_to_state: str | None,
    is_tax_exempt: bool = False,
) -> TaxEstimate:
    """Estimate sales tax for an order.

    `taxable_subtotal` should be the items + freight + handling - discount
    portion that's actually taxable (caller is responsible for excluding any
    non-taxable line items).
    """
    notes: list[str] = []

    if is_tax_exempt:
        notes.append("Customer is tax-exempt")
        return TaxEstimate(amount=Decimal("0"), rate_x1000=0, notes=notes)

    state = (ship_to_state or "").strip().upper()
    if state != "WA":
        notes.append(f"No nexus in {state or '(unspecified)'} — no tax collected")
        return TaxEstimate(amount=Decimal("0"), rate_x1000=0, notes=notes)

    # WA — apply default combined rate
    rate = Decimal(WA_DEFAULT_RATE_X1000) / Decimal(1000)
    amount = (taxable_subtotal * rate).quantize(Decimal("0.01"))
    notes.append(f"WA combined rate {WA_DEFAULT_RATE_X1000 / 10:.1f}% (Phase 1 flat — ZIP lookup in Phase 1.5)")
    return TaxEstimate(amount=amount, rate_x1000=WA_DEFAULT_RATE_X1000, notes=notes)
