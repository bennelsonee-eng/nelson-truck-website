"""Special Rules registry.

A single, admin-visible list of the non-obvious "special rules" the storefront
applies — things a future admin (or session) would otherwise have to discover
in code. Entries are DERIVED FROM LIVE CONFIG wherever possible so the page can
never drift from what the app actually does.

Currently surfaces:
  * YMM merged makes (e.g. "Dodge / RAM") — generated straight from
    ymm.MERGED_MAKES so adding a merge there auto-appears here.
  * Suppressed drill-down facets — generated from catalog._ATTR_DENYLIST /
    _ATTR_DENYLIST_PATTERNS so editing the suppression list auto-updates here.

To document a new rule, prefer wiring it off the real config (like the merge
loop below) rather than hand-maintaining a parallel description.
"""

from __future__ import annotations

from typing import Any

from app.routers.ymm import MERGED_MAKES


def list_special_rules() -> list[dict[str, Any]]:
    """Return the active special rules, newest-config first within a category."""
    rules: list[dict[str, Any]] = []

    # --- Catalog · Facets · Install Time suppressed (issue #13) --------------
    # Derived from the live suppression config so the page can't drift from
    # what /category-attributes actually hides.
    from app.routers.catalog import _ATTR_DENYLIST, _ATTR_DENYLIST_PATTERNS

    install_keys = sorted(
        k for k in _ATTR_DENYLIST
        if "install time" in k or "installation time" in k
    )
    rules.append({
        "id": "facet-suppress-install-time",
        "category": "Catalog · Drill-down facets",
        "title": "“Install Time” is hidden from the left-rail filters",
        "summary": (
            "Install / installation time is NOT shown as a shopping filter on "
            "category pages. It still appears on each product’s Specs tab."
        ),
        "detail": (
            "Reported by Jared (issue #13) on Lift Kit Accessories: install time "
            "is reference data, not something a customer shops by. It is suppressed "
            "from the catalog drill-down facets but kept on the PDP Specs tab "
            "(e.g. “Installation Time: 5+ Hours”). "
            "NOTE: a product’s install time IS expected to be used at CHECKOUT once "
            "installation is offered in the cart — this rule only removes it as a "
            "browse filter, it does not discard the data. "
            "The “Ships in Multiple Boxes” fulfillment flag is suppressed the same way."
        ),
        "scope": (
            "Left-rail attribute facets on /catalog (the /category-attributes "
            "endpoint). Matches exact keys [" + ", ".join(install_keys) + "] plus "
            "any attribute key matching patterns " + ", ".join(
                repr(p) for p in _ATTR_DENYLIST_PATTERNS
            ) + " (covers ~20 PIES spelling variants). PDP Specs tab unaffected."
        ),
        "source": "app/backend/app/routers/catalog.py — _ATTR_DENYLIST / _ATTR_DENYLIST_PATTERNS",
        "since": "2026-06-22",
        "status": "active",
    })

    # --- Catalog · Year/Make/Model merged makes (from ymm.MERGED_MAKES) -------
    for slug, cfg in MERGED_MAKES.items():
        members = " + ".join(sorted(cfg["member_names"]))
        rules.append({
            "id": f"ymm-merge-{slug}",
            "category": "Catalog · Year / Make / Model",
            "title": f"{members} shown as one make “{cfg['name']}”",
            "summary": (
                f"The vehicle (YMM) picker presents the separate VCDB makes {members} "
                f"as a single “{cfg['name']}” entry."
            ),
            "detail": (
                "Some manufacturers split or rebranded into separate VCDB makes (e.g. RAM "
                "split from Dodge in 2010-11), but customers still shop them as one brand. "
                "Picking the parent make would otherwise miss every spun-off model "
                "(Ram 1500 / 2500 / 3500 + ProMaster). This rule merges them in the picker "
                "ONLY — the underlying VCDB makes, base_vehicle_id values, and every product "
                "fitment stay unchanged, so it is safe across catalog re-ingests."
            ),
            "scope": (
                f"YMM make dropdown, model list, and resolve (combined slug “{slug}”). "
                "Selecting a model still reports its real make (e.g. “2026 Ram 1500”). "
                "Fitment / base_vehicle keys unchanged."
            ),
            "source": "app/backend/app/routers/ymm.py — MERGED_MAKES",
            "since": cfg.get("since"),
            "status": "active",
        })

    return rules
