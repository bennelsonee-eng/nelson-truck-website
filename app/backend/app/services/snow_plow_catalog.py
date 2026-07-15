"""Curated snow-plow model catalog for the comparison builder.

Phase 1 hand-curated data covering Western, Meyer, and Buyers/SnowDogg
flagship lineups.  This sits alongside the live product catalog (which is
SKU-grain) — the spec data here is *model-level* so the comparison page
can do an apples-to-apples spec table even when individual SKUs aren't
in inventory yet.

Phase 1.5 will replace this with a real `snow_plow_model` DB table that
admins can edit + that the importer hydrates from the brand catalogs.

Spec sources: westernplows.com, meyerproducts.com, buyersproducts.com /
snowdogg.com (manufacturer-published as of 2025-2026 model years).  Pricing
ranges are MSRP order-of-magnitude — Titan tier pricing applies at quote
time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


PlowFamily = Literal["straight_blade", "v_plow", "winged", "specialty"]
ControlSystem = Literal["handheld", "joystick", "cab_command", "in_cab_touch"]
HydraulicType = Literal["truck_mounted_hydraulic", "self_contained_electric"]


@dataclass
class PlowModel:
    id: str                      # url-safe slug, e.g. "western-pro-plus"
    brand: str                   # "Western" | "Meyer" | "SnowDogg"
    model: str                   # display model name e.g. "Pro-Plus"
    family: PlowFamily
    family_label: str            # "Straight Blade" | "V-Plow" | "Winged"
    blade_widths_in: list[str]   # e.g. ["7'6\"", "8'", "8'6\""]
    blade_height_in: float       # plow blade height
    weight_lb: int               # approximate base weight
    cutting_edge: str            # material spec
    moldboard: str               # construction (steel/poly/stainless)
    mount: str                   # e.g. "UltraMount 3"
    hydraulics: HydraulicType
    control: list[ControlSystem]
    truck_classes: list[str]     # ["1500", "2500", "3500"] etc.
    msrp_low: int                # USD ballpark
    msrp_high: int
    best_for: str                # one-line application guidance
    highlights: list[str]        # 2-4 bullet selling points
    # ---- Moldboard SKUs ----
    # User insight Apr 27 2026: "the pictures will line up with moldboard part
    # numbers — we will use these later to form kit part numbers or a different
    # part of the website that can piece the whole complete snowplow together."
    # So each PlowModel maps to N moldboard SKUs (one per blade width / material
    # variant) sourced from titantruck.com's WSM catalog.  The first SKU in the
    # list is the "default" rendered as the wizard card hero.  The remaining
    # SKUs are surfaced in the comparison page and the future kit-builder.
    # Format: list of Titan stockids like "WEST:PPMS8-EQP", "MYP:09446-EQP",
    # or "SNOW:16020412-EQP".  Resolved to image paths by `image_url_for_sku()`
    # which checks the static-asset manifest at scrape time.
    moldboard_skus: list[str] = field(default_factory=list)
    # ---- Legacy / fallback ----
    image_url: str | None = None  # deprecated — prefer moldboard_skus
    notes: str | None = None
    snow_belt_rank: int = 0       # rough popularity rank (0 = unranked)


CATALOG: list[PlowModel] = [
    # ============================ WESTERN ============================
    PlowModel(
        id="western-hts",
        brand="Western", model="HTS",
        family="straight_blade", family_label="Straight Blade",
        blade_widths_in=["7'6\""],
        blade_height_in=27, weight_lb=420,
        cutting_edge="6\" carbon steel",
        moldboard="11-gauge powder-coated steel",
        mount="UltraMount 2",
        hydraulics="self_contained_electric",
        control=["handheld"],
        truck_classes=["1500", "2500"],
        msrp_low=4800, msrp_high=5800,
        best_for="Half-ton driveways + light commercial",
        highlights=["Lightest Western blade", "Self-contained pump = quick install", "Affordable entry to the Western lineup"],
        moldboard_skus=["WEST:HTS76-EQP"],
        snow_belt_rank=4,
    ),
    PlowModel(
        id="western-pro-plow-3",
        brand="Western", model="PRO-PLOW 3",
        family="straight_blade", family_label="Straight Blade",
        blade_widths_in=["7'6\"", "8'", "8'6\""],
        blade_height_in=29, weight_lb=620,
        cutting_edge="6\" high-carbon steel",
        moldboard="12-gauge powder-coated steel",
        mount="UltraMount 3",
        hydraulics="truck_mounted_hydraulic",
        control=["handheld", "joystick"],
        truck_classes=["1500", "2500", "3500"],
        msrp_low=5400, msrp_high=6600,
        best_for="Mid-weight commercial straight-blade",
        highlights=["Trip-edge moldboard", "Sealed hydraulics", "Most-installed Western model"],
        # NOTE: Titan's catalog ships "PRO-PLOW Series 2"; "PRO-PLOW 3" is the
        # newest Western nomenclature.  Hardware spec is essentially identical
        # — same UT3 mount, same trip-edge moldboard.  Until Titan rolls Series
        # 3 SKUs into WSM we use Series 2 imagery.
        moldboard_skus=[
            "WEST:PPS2MS86-EQP",   # 8'6" steel — default hero (most popular width)
            "WEST:PPS2MS8-EQP",    # 8' steel
            "WEST:PPS2MS76-EQP",   # 7'6" steel
            "WEST:PPS2PLY8-EQP",   # 8' poly
            "WEST:PPS2PLY76-EQP",  # 7'6" poly
        ],
        snow_belt_rank=2,
    ),
    PlowModel(
        id="western-pro-plus",
        brand="Western", model="PRO PLUS",
        family="straight_blade", family_label="Straight Blade",
        blade_widths_in=["8'", "8'6\"", "9'"],
        blade_height_in=31.5, weight_lb=740,
        cutting_edge="6\" high-carbon steel",
        moldboard="11-gauge powder-coated steel",
        mount="UltraMount 3",
        hydraulics="truck_mounted_hydraulic",
        control=["handheld", "joystick", "cab_command"],
        truck_classes=["2500", "3500"],
        msrp_low=6200, msrp_high=7800,
        best_for="Heavy commercial straight-blade",
        highlights=["Taller moldboard rolls more snow", "Trip-edge protection", "PowerBar piston rod"],
        moldboard_skus=[
            "WEST:PPMS86-EQP",   # 8'6" — default
            "WEST:PPMS8-EQP",    # 8'
            "WEST:PPMS9-EQP",    # 9'
            "WEST:PPHD10-EQP",   # 10' HD
        ],
        snow_belt_rank=1,
    ),
    PlowModel(
        id="western-mvp-3",
        brand="Western", model="MVP 3",
        family="v_plow", family_label="V-Plow",
        blade_widths_in=["7'6\"", "8'6\"", "9'6\""],
        blade_height_in=31, weight_lb=890,
        cutting_edge="6\" carbon steel",
        moldboard="14-gauge stainless or 12-gauge steel",
        mount="UltraMount 3",
        hydraulics="truck_mounted_hydraulic",
        control=["handheld", "joystick"],
        truck_classes=["2500", "3500"],
        msrp_low=8200, msrp_high=10500,
        best_for="Commercial cul-de-sacs, EOD piles, hard-pack",
        highlights=["Flared wings carry more snow", "Center-link strength", "Smallest mount in V-class"],
        moldboard_skus=[
            "WEST:MVP3MS86-EQP",   # 8'6" steel — default
            "WEST:MVP3MS96-EQP",   # 9'6" steel
            "WEST:MVP3MS106-EQP",  # 10'6" steel
            "WEST:MVP3SS86-EQP",   # 8'6" stainless
            "WEST:MVP3SS96-EQP",   # 9'6" stainless
            "WEST:MVP3SS106-EQP",  # 10'6" stainless
            "WEST:MVP3PLY86-EQP",  # 8'6" poly
            "WEST:MVP3PLY96-EQP",  # 9'6" poly
        ],
        snow_belt_rank=2,
    ),
    PlowModel(
        id="western-wideout",
        brand="Western", model="WIDE-OUT",
        family="winged", family_label="Winged Blade",
        blade_widths_in=["8'", "8'6\""],   # extends to 10'
        blade_height_in=32, weight_lb=1010,
        cutting_edge="6\" carbon steel",
        moldboard="14-gauge stainless or steel",
        mount="UltraMount 3",
        hydraulics="truck_mounted_hydraulic",
        control=["joystick", "cab_command"],
        truck_classes=["2500", "3500", "4500"],
        msrp_low=10500, msrp_high=13800,
        best_for="Open commercial parking lots — fastest-clearing plow class",
        highlights=["Extends 8' → 10'", "Scoop / windrow / straight in one plow", "Dominant for parking-lot speed"],
        moldboard_skus=[
            "WEST:WIDE810-EQP",  # 8'-10' standard — default
            "WEST:WIDEXL-EQP",   # 8.5'-11' XL
        ],
        snow_belt_rank=1,
    ),
    PlowModel(
        id="western-defender",
        brand="Western", model="DEFENDER",
        family="straight_blade", family_label="Straight Blade",
        blade_widths_in=["6'", "6'8\""],
        blade_height_in=22, weight_lb=295,
        cutting_edge="3/8\" steel",
        moldboard="14-gauge steel",
        mount="DEFENDER mount",
        hydraulics="self_contained_electric",
        control=["handheld"],
        truck_classes=["mid-size"],
        msrp_low=3800, msrp_high=4600,
        best_for="Mid-size pickup contractor work (Tacoma / Colorado / Ranger / Maverick / Ridgeline)",
        highlights=["Right-sized contractor-grade for mid-size trucks", "Lightweight DC self-contained pump", "Optional flared wings"],
        notes="Mid-size truck contractor blade — NOT a residential unit.  Right-sized for the smaller truck class but built for commercial use.",
        moldboard_skus=[
            "WEST:DEF68-EQP",  # 6'-8"
            "WEST:DEF72-EQP",  # 7'-2"
        ],
        snow_belt_rank=5,
    ),

    # ============================ MEYER ============================
    PlowModel(
        id="meyer-drive-pro",
        brand="Meyer", model="Drive Pro",
        family="straight_blade", family_label="Straight Blade",
        blade_widths_in=["6'8\"", "7'6\""],
        blade_height_in=24, weight_lb=345,
        cutting_edge="3/8\" steel",
        moldboard="11-gauge steel",
        mount="EZ-Mount Plus 2",
        hydraulics="self_contained_electric",
        control=["handheld"],
        truck_classes=["mid-size", "1500"],
        msrp_low=4200, msrp_high=4900,
        best_for="Mid-size + half-ton contractor work",
        highlights=["Right-sized contractor build for smaller trucks", "Quick-attach mount", "1-touch controller"],
        notes="Mid-size + half-ton contractor blade — NOT a residential 'Home Plow' class unit.  Built for commercial duty on smaller trucks.",
        moldboard_skus=[
            "MYP:09499-EQP",  # 6'8" — default
            "MYP:09507-EQP",  # 7'6"
            "MYP:09473-EQP",  # 6'
            "MYP:09472-EQP",  # 5' (sub-compact)
        ],
        snow_belt_rank=4,
    ),
    PlowModel(
        id="meyer-ez-plus",
        brand="Meyer", model="Diamond Edge",   # was EZ Plus — Meyer rebranded
        family="straight_blade", family_label="Straight Blade",
        blade_widths_in=["7'6\"", "8'", "8'6\""],
        blade_height_in=29, weight_lb=560,
        cutting_edge="6\" steel",
        moldboard="11-gauge powder-coated steel",
        mount="EZ-Mount Plus 2",
        hydraulics="truck_mounted_hydraulic",
        control=["handheld", "joystick"],
        truck_classes=["1500", "2500"],
        msrp_low=5200, msrp_high=6300,
        best_for="Light commercial routes",
        highlights=["Truck-mounted hydraulic = fast cycle", "Pivot-bar trip protection"],
        notes="Replaces the discontinued EZ Plus.  Same EZ-Mount Plus 2 mount, same routes, slightly stiffer moldboard.",
        moldboard_skus=[
            "MYP:84352-EQP",  # 8'6" — default
            "MYP:84351-EQP",  # 8'
            "MYP:84350-EQP",  # 7'6"
            "MYP:84353-EQP",  # 9'
        ],
        snow_belt_rank=3,
    ),
    PlowModel(
        id="meyer-super-v2",
        brand="Meyer", model="Super V2",
        family="v_plow", family_label="V-Plow",
        blade_widths_in=["8'6\"", "9'6\""],
        blade_height_in=31, weight_lb=900,
        cutting_edge="6\" steel",
        moldboard="11-gauge stainless or steel",
        mount="EZ-Mount Plus 2",
        hydraulics="truck_mounted_hydraulic",
        control=["handheld", "joystick"],
        truck_classes=["2500", "3500"],
        msrp_low=8400, msrp_high=10200,
        best_for="Commercial routes that mix lots + driveways",
        highlights=["Heated turn-signal lights", "Stainless option for rust resistance", "Robust pivot-pin design"],
        moldboard_skus=[
            "MYP:09446-EQP",   # 8'6" steel — default
            "MYP:09447-EQP",   # 9'6" steel
            "MYP:09494-EQP",   # 8'6" stainless
            "MYP:09495-EQP",   # 9'6" stainless
        ],
        snow_belt_rank=2,
    ),
    PlowModel(
        id="meyer-xls",
        brand="Meyer", model="Wingman",   # was XLS — Meyer rebranded the winged line
        family="winged", family_label="Winged Blade",
        blade_widths_in=["6'8\""],   # extends w/ wings
        blade_height_in=27, weight_lb=620,
        cutting_edge="6\" steel",
        moldboard="11-gauge steel",
        mount="EZ-Mount Plus 2",
        hydraulics="truck_mounted_hydraulic",
        control=["joystick"],
        # Owner correction 2026-05-17: the 6'8" Wingman is rated for mid-size
        # too; only the wider configurations need a 2500-class chassis.
        truck_classes=["mid-size", "2500", "3500"],
        msrp_low=9800, msrp_high=12600,
        best_for="Parking lots needing rapid windrow + scoop",
        highlights=["Hydraulic wings extend coverage", "Pivot-bar trip", "Bolt-on cutting edge"],
        notes="Replaces the discontinued XLS.  Wingman is Meyer's current winged offering.",
        moldboard_skus=[
            "MYP:09478-EQP",  # 6'8" Wingman
        ],
        snow_belt_rank=3,
    ),
    PlowModel(
        id="meyer-lot-pro",
        brand="Meyer", model="Lot Pro",
        family="straight_blade", family_label="Straight Blade",
        blade_widths_in=["8'", "9'", "10'"],
        blade_height_in=34, weight_lb=860,
        cutting_edge="6\" steel",
        moldboard="11-gauge steel",
        mount="EZ-Mount Plus 2",
        hydraulics="truck_mounted_hydraulic",
        control=["handheld", "joystick"],
        truck_classes=["3500", "4500"],
        msrp_low=7200, msrp_high=9000,
        best_for="1-ton + chassis-cab fleets",
        highlights=["Tallest moldboard in straight class", "Heavy-duty pivot pins", "Built for daily commercial duty"],
        moldboard_skus=[
            "MYP:09402-EQP",  # 8'6" — default
            "MYP:09401-EQP",  # 8'
            "MYP:09403-EQP",  # 9'
            "MYP:09400-EQP",  # 7'6"
            "MYP:09405-EQP",  # 8' poly
            "MYP:09406-EQP",  # 8'6" poly
            "MYP:09407-EQP",  # 9' poly
            "MYP:09404-EQP",  # 7'6" poly
            "MYP:09275-EQP",  # 7'6" Light Duty
        ],
        snow_belt_rank=4,
    ),

    # ============================ SNOWDOGG (BUYERS) ============================
    # SnowDogg refreshed the lineup to a "II" suffix series — MDII, EXII, VXFII,
    # XP810II, etc.  Internally identical hardware lineage, new badging.  Titan's
    # WSM catalog already lists the II SKUs so that's what we map to.
    PlowModel(
        id="snowdogg-md-series",
        brand="SnowDogg", model="MD Series",
        family="straight_blade", family_label="Straight Blade",
        blade_widths_in=["7'6\"", "8'"],
        blade_height_in=29, weight_lb=510,
        cutting_edge="3/8\" steel",
        moldboard="304 stainless or steel",
        mount="Rapidlink",
        hydraulics="self_contained_electric",
        control=["handheld"],
        # Owner correction 2026-05-17: MD is SnowDogg's medium-duty line —
        # the 7'6" model is mid-size compatible (Tacoma / Colorado / Ranger).
        truck_classes=["mid-size", "1500", "2500"],
        msrp_low=4800, msrp_high=5900,
        best_for="Light + medium commercial half-ton/3-quarter routes",
        highlights=["Stainless option resists rust forever", "Rapidlink mount - fast on/off", "Best price-to-spec ratio"],
        moldboard_skus=["SNOW:16020412-EQP"],   # MDII
        snow_belt_rank=2,
    ),
    PlowModel(
        id="snowdogg-ex-series",
        brand="SnowDogg", model="EX Series",
        family="straight_blade", family_label="Straight Blade",
        blade_widths_in=["8'", "8'6\""],
        blade_height_in=31, weight_lb=720,
        cutting_edge="6\" carbon steel",
        moldboard="304 stainless",
        mount="Rapidlink",
        hydraulics="truck_mounted_hydraulic",
        control=["handheld", "joystick"],
        truck_classes=["2500", "3500"],
        msrp_low=6400, msrp_high=7800,
        best_for="Commercial routes wanting Western-grade build at lower MSRP",
        highlights=["Full stainless moldboard", "Truck-mounted hydraulic", "Strong municipal warranty terms"],
        moldboard_skus=["SNOW:16020612-EQP"],   # EXII
        snow_belt_rank=2,
    ),
    PlowModel(
        id="snowdogg-vx-series",
        brand="SnowDogg", model="VX Series",
        family="v_plow", family_label="V-Plow",
        blade_widths_in=["8'6\"", "9'"],
        blade_height_in=31, weight_lb=850,
        cutting_edge="6\" carbon steel",
        moldboard="304 stainless",
        mount="Rapidlink",
        hydraulics="truck_mounted_hydraulic",
        control=["handheld", "joystick"],
        truck_classes=["2500", "3500"],
        msrp_low=8600, msrp_high=10500,
        best_for="Stainless V-plow for commercial routes",
        highlights=["Stainless construction", "Quad LED snow lights", "Trip-edge with full moldboard return"],
        moldboard_skus=["SNOW:16020712-EQP"],   # VMD75II (V-plow MD class)
        snow_belt_rank=3,
    ),
    PlowModel(
        id="snowdogg-vxf-series",
        brand="SnowDogg", model="VXF Series",
        family="v_plow", family_label="V-Plow",
        blade_widths_in=["9'", "10'"],
        blade_height_in=34, weight_lb=1080,
        cutting_edge="6\" carbon steel",
        moldboard="304 stainless flared",
        mount="Rapidlink",
        hydraulics="truck_mounted_hydraulic",
        control=["joystick", "cab_command"],
        truck_classes=["3500", "4500"],
        msrp_low=11500, msrp_high=14200,
        best_for="Heavy commercial / municipal — flared V-plow",
        highlights=["Flared wings = bigger scoop volume", "Tallest VX moldboard", "Cab-command compatible"],
        moldboard_skus=["SNOW:16020724-EQP"],   # VXFII
        snow_belt_rank=2,
    ),
    PlowModel(
        id="snowdogg-xp-series",
        brand="SnowDogg", model="XP Series",
        family="winged", family_label="Winged Blade",
        blade_widths_in=["8'6\""],
        blade_height_in=32, weight_lb=1020,
        cutting_edge="6\" carbon steel",
        moldboard="304 stainless",
        mount="Rapidlink",
        hydraulics="truck_mounted_hydraulic",
        control=["joystick"],
        truck_classes=["2500", "3500", "4500"],
        msrp_low=10800, msrp_high=13500,
        best_for="Open commercial lots needing scoop + reach",
        highlights=["Hydraulic wings extend 8'6\" → 10'9\"", "Stainless construction", "VXF-grade hydraulics"],
        moldboard_skus=["SNOW:16020922-EQP"],   # XP810II
        snow_belt_rank=4,
    ),
]


# ---------------------------------------------------------------------------
# SKU → image-path resolver
# ---------------------------------------------------------------------------
# Loaded once at module import.  Re-run the scraper to refresh and restart the
# backend.  The manifest was written by `app/scripts/scrape_titan_plow_images.py`
# at scrape time and lives next to the image assets.

import json as _json
from pathlib import Path as _Path

# this file is at  app/backend/app/services/snow_plow_catalog.py
# manifest lives at app/backend/static/snow-plows/skus/_manifest.json
# .parent x3 walks up:  services -> app -> backend
_MANIFEST_PATH = (
    _Path(__file__).resolve().parent.parent.parent
    / "static" / "snow-plows" / "skus" / "_manifest.json"
)
_SKU_TO_IMAGE: dict[str, str] = {}
_SKU_TO_META: dict[str, dict] = {}

try:
    if _MANIFEST_PATH.exists():
        _manifest = _json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        for entry in _manifest.get("skus", []):
            stockid = entry.get("stockid")
            sanitized = entry.get("stockid_sanitized")
            if stockid and sanitized:
                # Public URL path — served by FastAPI's StaticFiles mount at /static/
                _SKU_TO_IMAGE[stockid] = f"/static/snow-plows/skus/{sanitized}/hero.jpg"
                _SKU_TO_META[stockid] = entry
except Exception:
    # Don't crash the app if the manifest is missing or malformed; the wizard
    # just renders a placeholder card.
    _SKU_TO_IMAGE = {}
    _SKU_TO_META = {}


def image_url_for_sku(sku: str) -> str | None:
    """Resolve a moldboard stockid (e.g. "WEST:PPMS86-EQP") to its served URL."""
    return _SKU_TO_IMAGE.get(sku)


def hero_image_url(model: PlowModel) -> str | None:
    """The default image for a plow card — first moldboard SKU's hero shot."""
    if model.image_url:                       # explicit override (rare)
        return model.image_url
    for sku in model.moldboard_skus:
        url = _SKU_TO_IMAGE.get(sku)
        if url:
            return url
    return None


def list_models() -> list[PlowModel]:
    return list(CATALOG)


def get_model(id: str) -> PlowModel | None:
    return next((m for m in CATALOG if m.id == id), None)


def model_to_dict(m: PlowModel) -> dict:
    d = asdict(m)
    # Resolved hero image URL — what the frontend actually consumes
    d["hero_image_url"] = hero_image_url(m)
    # Per-SKU image map for the comparison page / future kit-builder
    d["moldboard_image_urls"] = {
        sku: _SKU_TO_IMAGE.get(sku) for sku in m.moldboard_skus
    }
    # Manufacturer content (descriptions, full spec tables, PDF links, videos)
    # — populated by snow_plow_manufacturer_content.py from the scraper output.
    # Falls through to {} if scrape didn't cover this plow.
    d["manufacturer"] = _MANUFACTURER_CONTENT.get(m.id, {})
    return d


# Load manufacturer content at import time.  See:
#   app/scripts/build_manufacturer_content.py
# Re-run that script after refreshing manufacturer_data/ scrapes, then
# restart the backend to pick up the new content.
try:
    from app.services.snow_plow_manufacturer_content import MANUFACTURER_CONTENT as _MANUFACTURER_CONTENT
except Exception:
    _MANUFACTURER_CONTENT: dict[str, dict] = {}
