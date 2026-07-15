"""Year/Make/Model fitment lookups — Phase 1 static seed.

Populates the YMM selector dropdowns without requiring a fitment-data import.
Phase 1.5 will replace these constants with a real `vehicle_make` /
`vehicle_model` / `product_fitment` schema and a fitment importer (likely
sourced from PACE/AAM Group's vehicle-fitment feed).

For now, the selector persists the user's choice to localStorage so we can
plumb it through the catalog filters when fitment data lands — no schema
break required.

Seed coverage focuses on truck/van/SUV makes that match Titan's typical
customer fleet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


__all__ = [
    "Make",
    "Model",
    "current_year_range",
    "list_makes",
    "list_models",
    "find_make",
    "find_model",
]


@dataclass(frozen=True)
class Make:
    slug: str
    name: str
    is_featured: bool = False


@dataclass(frozen=True)
class Model:
    slug: str
    name: str
    body_type: str  # "pickup" | "van" | "suv" | "chassis_cab" | "passenger_car"
    year_start: int = 1990
    year_end: int | None = None  # None = current


# ---------------------------------------------------------------------------
# Year range — generate 1990 → current+1 (so people can shop next-year models)
# ---------------------------------------------------------------------------


def current_year_range() -> list[int]:
    cy = date.today().year
    return list(range(cy + 1, 1989, -1))  # newest first


# ---------------------------------------------------------------------------
# Makes — alphabetical; featured = the dominant truck/van brands
# ---------------------------------------------------------------------------


_MAKES: list[Make] = [
    Make("chevrolet",  "Chevrolet",   is_featured=True),
    Make("dodge",      "Dodge",       is_featured=True),
    Make("ford",       "Ford",        is_featured=True),
    Make("freightliner","Freightliner",is_featured=True),
    Make("gmc",        "GMC",         is_featured=True),
    Make("honda",      "Honda"),
    Make("hyundai",    "Hyundai"),
    Make("international","International"),
    Make("isuzu",      "Isuzu",       is_featured=True),
    Make("jeep",       "Jeep",        is_featured=True),
    Make("kenworth",   "Kenworth"),
    Make("mack",       "Mack"),
    Make("mazda",      "Mazda"),
    Make("mercedes-benz","Mercedes-Benz",is_featured=True),
    Make("mitsubishi-fuso","Mitsubishi Fuso"),
    Make("nissan",     "Nissan",      is_featured=True),
    Make("peterbilt",  "Peterbilt"),
    Make("ram",        "Ram",         is_featured=True),
    Make("subaru",     "Subaru"),
    Make("toyota",     "Toyota",      is_featured=True),
    Make("volkswagen", "Volkswagen"),
    Make("volvo",      "Volvo"),
]


# ---------------------------------------------------------------------------
# Models per make — focus on truck/van lineups; passenger cars omitted for
# the trucks that have car siblings.  Phase 1.5 imports the full PACE/AAM
# fitment feed (~3K models).
# ---------------------------------------------------------------------------


_MODELS_BY_MAKE: dict[str, list[Model]] = {
    "ford": [
        Model("f150",            "F-150",              "pickup"),
        Model("f250-super-duty", "F-250 Super Duty",   "pickup"),
        Model("f350-super-duty", "F-350 Super Duty",   "pickup"),
        Model("f450-super-duty", "F-450 Super Duty",   "chassis_cab"),
        Model("f550-super-duty", "F-550 Super Duty",   "chassis_cab"),
        Model("ranger",          "Ranger",             "pickup"),
        Model("maverick",        "Maverick",           "pickup", year_start=2022),
        Model("transit",         "Transit",            "van",    year_start=2014),
        Model("transit-connect", "Transit Connect",    "van",    year_start=2010),
        Model("e-series",        "E-Series",           "van",    year_end=2014),
        Model("expedition",      "Expedition",         "suv"),
        Model("explorer",        "Explorer",           "suv"),
        Model("bronco",          "Bronco",             "suv"),
        Model("escape",          "Escape",             "suv"),
    ],
    "chevrolet": [
        Model("silverado-1500",  "Silverado 1500",     "pickup"),
        Model("silverado-2500hd","Silverado 2500HD",   "pickup"),
        Model("silverado-3500hd","Silverado 3500HD",   "pickup"),
        Model("silverado-4500hd","Silverado 4500HD",   "chassis_cab", year_start=2019),
        Model("silverado-5500hd","Silverado 5500HD",   "chassis_cab", year_start=2019),
        Model("colorado",        "Colorado",           "pickup",      year_start=2004),
        Model("express",         "Express",            "van"),
        Model("city-express",    "City Express",       "van",         year_start=2015, year_end=2018),
        Model("suburban",        "Suburban",           "suv"),
        Model("tahoe",           "Tahoe",              "suv"),
        Model("blazer",          "Blazer",             "suv"),
        Model("trailblazer",     "Trailblazer",        "suv"),
    ],
    "gmc": [
        Model("sierra-1500",     "Sierra 1500",        "pickup"),
        Model("sierra-2500hd",   "Sierra 2500HD",      "pickup"),
        Model("sierra-3500hd",   "Sierra 3500HD",      "pickup"),
        Model("sierra-4500hd",   "Sierra 4500HD",      "chassis_cab", year_start=2019),
        Model("sierra-5500hd",   "Sierra 5500HD",      "chassis_cab", year_start=2019),
        Model("canyon",          "Canyon",             "pickup",      year_start=2004),
        Model("savana",          "Savana",             "van"),
        Model("yukon",           "Yukon",              "suv"),
        Model("yukon-xl",        "Yukon XL",           "suv"),
        Model("acadia",          "Acadia",             "suv",         year_start=2007),
    ],
    "ram": [
        Model("1500",            "1500",               "pickup",      year_start=2011),
        Model("2500",            "2500",               "pickup",      year_start=2011),
        Model("3500",            "3500",               "pickup",      year_start=2011),
        Model("4500",            "4500",               "chassis_cab", year_start=2011),
        Model("5500",            "5500",               "chassis_cab", year_start=2011),
        Model("promaster",       "ProMaster",          "van",         year_start=2014),
        Model("promaster-city",  "ProMaster City",     "van",         year_start=2015, year_end=2022),
    ],
    "dodge": [
        Model("ram-1500",        "Ram 1500 (legacy)",  "pickup",      year_end=2010),
        Model("ram-2500",        "Ram 2500 (legacy)",  "pickup",      year_end=2010),
        Model("ram-3500",        "Ram 3500 (legacy)",  "pickup",      year_end=2010),
        Model("ram-4500",        "Ram 4500 (legacy)",  "chassis_cab", year_end=2010),
        Model("durango",         "Durango",            "suv"),
        Model("dakota",          "Dakota",             "pickup",      year_end=2011),
    ],
    "toyota": [
        Model("tundra",          "Tundra",             "pickup"),
        Model("tacoma",          "Tacoma",             "pickup"),
        Model("4runner",         "4Runner",            "suv"),
        Model("sequoia",         "Sequoia",            "suv"),
        Model("land-cruiser",    "Land Cruiser",       "suv"),
        Model("highlander",      "Highlander",         "suv"),
        Model("rav4",            "RAV4",               "suv"),
    ],
    "nissan": [
        Model("titan",           "Titan",              "pickup"),
        Model("titan-xd",        "Titan XD",           "pickup",      year_start=2016),
        Model("frontier",        "Frontier",           "pickup"),
        Model("nv1500",          "NV1500",             "van",         year_start=2012, year_end=2021),
        Model("nv2500",          "NV2500",             "van",         year_start=2012, year_end=2021),
        Model("nv3500",          "NV3500",             "van",         year_start=2012, year_end=2021),
        Model("nv200",           "NV200",              "van",         year_start=2013, year_end=2021),
        Model("armada",          "Armada",             "suv"),
        Model("pathfinder",      "Pathfinder",         "suv"),
    ],
    "jeep": [
        Model("wrangler",        "Wrangler",           "suv"),
        Model("gladiator",       "Gladiator",          "pickup",      year_start=2020),
        Model("grand-cherokee",  "Grand Cherokee",     "suv"),
        Model("cherokee",        "Cherokee",           "suv"),
        Model("compass",         "Compass",            "suv"),
        Model("wagoneer",        "Wagoneer",           "suv",         year_start=2022),
    ],
    "honda": [
        Model("ridgeline",       "Ridgeline",          "pickup"),
        Model("pilot",           "Pilot",              "suv"),
        Model("passport",        "Passport",           "suv"),
        Model("cr-v",            "CR-V",               "suv"),
    ],
    "hyundai": [
        Model("santa-cruz",      "Santa Cruz",         "pickup",      year_start=2022),
        Model("santa-fe",        "Santa Fe",           "suv"),
        Model("palisade",        "Palisade",           "suv",         year_start=2020),
        Model("tucson",          "Tucson",             "suv"),
    ],
    "isuzu": [
        Model("npr",             "NPR",                "chassis_cab"),
        Model("nqr",             "NQR",                "chassis_cab"),
        Model("nrr",             "NRR",                "chassis_cab"),
        Model("ftr",             "FTR",                "chassis_cab"),
    ],
    "mercedes-benz": [
        Model("sprinter",        "Sprinter",           "van"),
        Model("metris",          "Metris",             "van",         year_start=2016, year_end=2023),
    ],
    "freightliner": [
        Model("sprinter",        "Sprinter",           "van",         year_end=2018),
        Model("m2-106",          "M2 106",             "chassis_cab"),
        Model("cascadia",        "Cascadia",           "chassis_cab"),
    ],
    "international": [
        Model("mv",              "MV Series",          "chassis_cab", year_start=2019),
        Model("hv",              "HV Series",          "chassis_cab", year_start=2019),
        Model("durastar",        "DuraStar",           "chassis_cab", year_end=2018),
    ],
    "kenworth": [
        Model("t370",            "T370",               "chassis_cab"),
        Model("t680",            "T680",               "chassis_cab"),
        Model("w900",            "W900",               "chassis_cab"),
    ],
    "peterbilt": [
        Model("220",             "220",                "chassis_cab"),
        Model("337",             "337",                "chassis_cab"),
        Model("389",             "389",                "chassis_cab"),
    ],
    "mack": [
        Model("granite",         "Granite",            "chassis_cab"),
        Model("anthem",          "Anthem",             "chassis_cab"),
    ],
    "volvo": [
        Model("vnl",             "VNL",                "chassis_cab"),
        Model("vnr",             "VNR",                "chassis_cab"),
    ],
    "volkswagen": [
        Model("atlas",           "Atlas",              "suv",         year_start=2018),
        Model("tiguan",          "Tiguan",             "suv"),
    ],
    "subaru": [
        Model("outback",         "Outback",            "suv"),
        Model("forester",        "Forester",           "suv"),
        Model("ascent",          "Ascent",             "suv",         year_start=2019),
    ],
    "mazda": [
        Model("cx-5",            "CX-5",               "suv"),
        Model("cx-9",            "CX-9",               "suv"),
        Model("cx-50",           "CX-50",              "suv",         year_start=2022),
    ],
    "mitsubishi-fuso": [
        Model("fe",              "FE Series",          "chassis_cab"),
        Model("fg",              "FG Series",          "chassis_cab"),
    ],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_makes(featured_first: bool = True) -> list[Make]:
    if featured_first:
        return sorted(_MAKES, key=lambda m: (not m.is_featured, m.name))
    return sorted(_MAKES, key=lambda m: m.name)


def list_models(make_slug: str, year: int | None = None) -> list[Model]:
    """Return models for a make, optionally filtered to those that include `year`."""
    models = _MODELS_BY_MAKE.get(make_slug.lower(), [])
    if year is not None:
        models = [
            m for m in models
            if m.year_start <= year and (m.year_end is None or year <= m.year_end)
        ]
    return sorted(models, key=lambda m: m.name)


def find_make(slug: str) -> Make | None:
    s = slug.lower()
    return next((m for m in _MAKES if m.slug == s), None)


def find_model(make_slug: str, model_slug: str) -> Model | None:
    s = model_slug.lower()
    return next((m for m in list_models(make_slug) if m.slug == s), None)
