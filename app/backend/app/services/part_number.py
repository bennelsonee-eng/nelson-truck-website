"""Shopper-facing part numbers.

Website SKUs are ``{brand.aaia_code}-{manufacturer part number}`` (e.g.
``HWZD-9751-3-01`` for Weatherguard). The AAIA prefix is the cross-reference
key that links AAIA/DCI codes to the ERP's internal product code (KNK for
Weatherguard) and lets search match either form. Shoppers should see the
brand and the manufacturer's own number instead: ``Weatherguard: 9751-3-01``.

Mirrors ``formatPartNumber`` in the frontend's App.tsx.
"""
from __future__ import annotations


def mfr_part_number(sku: str | None) -> str:
    """The manufacturer's part number: the SKU without its short brand prefix."""
    if not sku:
        return ""
    idx = sku.find("-")
    return sku[idx + 1:] if 0 < idx < 6 else sku


def part_label(sku: str | None, brand: str | None) -> str:
    """``Brand: part number`` when the brand is known, else just the part number."""
    if not sku:
        return ""
    if brand and "-" in sku:
        return f"{brand}: {sku[sku.find('-') + 1:]}"
    return mfr_part_number(sku)
