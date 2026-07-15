"""Curated top snow plow + parts sellers, sourced from real sales history.

Pulled from `tte_rcv390` MySQL with the query:

    SELECT prod_code, ourparts_num, description,
           SUM(quantity) AS units, SUM(ext_sales) AS revenue
    FROM tte_rcv390
    WHERE prod_code IN ('WEST','MYP','SNOW','BUY')
      AND ourparts_num != ''
      AND date >= '2025-04-01'
    GROUP BY prod_code, ourparts_num
    ORDER BY units DESC
    LIMIT 30

…then filtered to remove freight/service line items and curated to the
items most worth surfacing on the landing page (a mix of high-volume
parts + commercially significant whole units).

Phase 1.5 will replace this static list with a periodic MySQL pull that
auto-refreshes monthly.  For now: refresh by re-running the query and
hand-editing this file.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class TopSeller:
    sku: str                  # full SKU as it appears in tte_rcv390 (prod_code + ourparts_num)
    brand: str                # display brand name
    description: str          # short description from tte_rcv390
    units_last_12mo: int      # units sold in trailing 12 months
    revenue_last_12mo: int    # revenue ($USD) in trailing 12 months
    category: str             # rollup: 'plow_parts' | 'controls' | 'lighting' | 'mount_kit' | 'spreader' | 'fluid'
    note: str = ""            # optional context for the card


# Sourced 2026-04-26 from tte_rcv390 (last 12 months).  Order = display order.
TOP_SELLERS: list[TopSeller] = [
    TopSeller(
        sku="WEST35500", brand="Western",
        description="Plow Handheld Controller (WP series)",
        units_last_12mo=154, revenue_last_12mo=69_817,
        category="controls",
        note="Replacement controller for Western plows — the #2 unit driver in the lineup",
    ),
    TopSeller(
        sku="WEST72530", brand="Western",
        description="Halogen Light Kit — Complete",
        units_last_12mo=93, revenue_last_12mo=41_981,
        category="lighting",
        note="Complete halogen plow light kit — replaces failed factory units",
    ),
    TopSeller(
        sku="WEST31271-1", brand="Western",
        description="Mount Kit — Ford F350/F450 DRW Diesel (2017+)",
        units_last_12mo=38, revenue_last_12mo=26_004,
        category="mount_kit",
        note="One of the only vehicle-specific parts in a plow build",
    ),
    TopSeller(
        sku="WEST29070-1", brand="Western",
        description="3-Port Module — DRL/Non-DRL",
        units_last_12mo=150, revenue_last_12mo=24_782,
        category="plow_parts",
        note="Common harness module — most installs need one",
    ),
    TopSeller(
        sku="WEST72527", brand="Western",
        description="Cable Assembly — Vehicle Side w/Fuse",
        units_last_12mo=43, revenue_last_12mo=9_491,
        category="plow_parts",
    ),
    TopSeller(
        sku="WEST85973-2", brand="Western",
        description="Plug-in Halogen Harness Kit (SD)",
        units_last_12mo=31, revenue_last_12mo=8_624,
        category="plow_parts",
    ),
    TopSeller(
        sku="WEST11766", brand="Western",
        description="Truck-Side Electrical Kit",
        units_last_12mo=32, revenue_last_12mo=8_526,
        category="plow_parts",
    ),
    TopSeller(
        sku="WEST63655", brand="Western",
        description="Hydraulic Fluid — 55 Gallon Drum",
        units_last_12mo=632, revenue_last_12mo=259,
        category="fluid",
        note="Bulk shop consumable — top by unit count.  Mostly internal restock.",
    ),
    TopSeller(
        sku="WEST49311", brand="Western",
        description="Hydraulic Fluid — 1 Quart (WP Series)",
        units_last_12mo=121, revenue_last_12mo=2_416,
        category="fluid",
        note="Per-truck top-up size — what actual contractors buy",
    ),
    TopSeller(
        sku="SNOW16150005", brand="SnowDogg",
        description="Low-Temp Hydraulic Fluid — Quart",
        units_last_12mo=94, revenue_last_12mo=757,
        category="fluid",
    ),
    TopSeller(
        sku="BUYB1237PPB", brand="Buyer Products",
        description="Thermo Flex Fender Guard — Black",
        units_last_12mo=86, revenue_last_12mo=1_075,
        category="plow_parts",
    ),
    TopSeller(
        sku="BUY405BZ", brand="Buyer Products",
        description="Galvanized Anti-Sail Brackets",
        units_last_12mo=74, revenue_last_12mo=580,
        category="plow_parts",
    ),
]


CATEGORY_LABEL = {
    "plow_parts": "Plow Parts",
    "controls":   "Controls",
    "lighting":   "Lighting",
    "mount_kit":  "Mount Kit",
    "spreader":   "Spreader",
    "fluid":      "Hydraulic Fluid",
}


def list_top_sellers(limit: int = 12) -> list[TopSeller]:
    return TOP_SELLERS[:limit]


def top_seller_to_dict(t: TopSeller) -> dict:
    d = asdict(t)
    d["category_label"] = CATEGORY_LABEL.get(t.category, t.category)
    return d
