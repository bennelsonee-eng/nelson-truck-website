"""Year/Make/Model API.

Backed by the real PACE-loaded vcdb_make / vcdb_model / vcdb_base_vehicle
tables (75 makes, 1,734 models, 13,871 base_vehicles as of 2026-05-09 ingest).

Frontend speaks SLUGS (`make_slug=ford`, `model_slug=f-150`); we compute slugs
on the fly from the canonical names so we don't have to maintain a separate
slug column. Slug is `lower(name).replace(' ', '-').replace('/', '-')` etc.

Falls back to the static seed in `services/ymm_data.py` if the DB is empty
(e.g. fresh checkout before PACE ingest has run).
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import VcdbBaseVehicle, VcdbMake, VcdbModel
from app.services import ymm_data


router = APIRouter(prefix="/api/ymm", tags=["ymm"])


# Make IDs we promote to "popular" — truck-shop priorities.  Pulled from
# AAM YMM API's own popular list: Chevy/Ford/GMC/Jeep/Ram/Toyota.
POPULAR_MAKE_IDS = {54, 47, 48, 42, 1168, 76}
# Truck-friendly body types we surface first when no year is picked.
TRUCK_VEHICLE_TYPES = {"Pickup", "Pickup Truck", "Truck", "SUV", "Van", "Cab Chassis"}

# Makes presented as ONE combined entry in the picker (presentation only — the
# underlying VCDB makes stay separate so every fitment / base_vehicle_id key is
# unchanged). RAM split from Dodge into its own VCDB make in 2010-11, but
# customers still shop "Dodge/Ram" as a single brand — picking "Dodge" was
# silently missing every Ram 1500/2500/3500 + ProMaster. Keyed by member NAME
# (not id) so a VCDB re-ingest that renumbers make ids can't break the merge.
MERGED_MAKES: dict[str, dict] = {
    "dodge-ram": {"name": "Dodge / RAM", "member_names": {"Dodge", "Ram"}, "is_featured": True, "since": "2026-06-20"},
}


async def _member_make_ids(db: AsyncSession, make_slug: str) -> list[int]:
    """Real vcdb make_ids backing a picker make_slug.

    Merged slug (e.g. 'dodge-ram') → every underlying make_id; normal slug →
    the single resolved id (or [] if unknown)."""
    cfg = MERGED_MAKES.get(make_slug)
    if cfg is not None:
        rows = (await db.execute(
            select(VcdbMake.id).where(VcdbMake.name.in_(cfg["member_names"]))
        )).all()
        return [r[0] for r in rows]
    mid = await _resolve_make_id(db, make_slug)
    return [mid] if mid is not None else []


def _slug(s: str) -> str:
    """Match the frontend's slug convention: lower, alphanumeric + hyphen."""
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


# ---- Years ---------------------------------------------------------------- #


@router.get("/years")
async def get_years(db: AsyncSession = Depends(get_db)) -> list[int]:
    rows = (await db.execute(
        select(distinct(VcdbBaseVehicle.year))
        .where(VcdbBaseVehicle.year > 0)
        .order_by(VcdbBaseVehicle.year.desc())
    )).all()
    if rows:
        return [r[0] for r in rows]
    # Fall back to static seed if vcdb is empty
    return ymm_data.current_year_range()


# ---- Makes ---------------------------------------------------------------- #


@router.get("/makes")
async def get_makes(
    featured_first: bool = True,
    year: int | None = Query(None, description="If set, restrict to makes available that year"),
    vehicle_type: str | None = Query(None, description="If set (e.g. 'Van'), only makes that have a model of this type"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Returns [{slug, name, is_featured}] for the YMM dropdown.

    `featured_first=true` puts truck-shop popular makes (Chevy/Ford/GMC/Jeep/Ram/Toyota)
    at the top of the list.

    `vehicle_type='Van'` restricts to makes that build vans — used by the
    YMM picker's Van tab so the Make dropdown drops from 75 entries to
    the ~10 van-building OEMs (Ford, Mercedes-Benz, RAM, Chevy, GMC,
    Nissan, etc.).
    """
    if vehicle_type:
        q = (
            select(VcdbMake.id, VcdbMake.name)
            .join(VcdbBaseVehicle, VcdbBaseVehicle.make_id == VcdbMake.id)
            .join(VcdbModel, VcdbModel.id == VcdbBaseVehicle.model_id)
            .where(
                VcdbMake.name != "UNKNOWN",
                VcdbModel.vehicle_type == vehicle_type,
            )
            .group_by(VcdbMake.id, VcdbMake.name)
        )
        if year is not None:
            q = q.where(VcdbBaseVehicle.year == year)
    elif year is not None:
        q = (
            select(VcdbMake.id, VcdbMake.name)
            .join(VcdbBaseVehicle, VcdbBaseVehicle.make_id == VcdbMake.id)
            .where(VcdbBaseVehicle.year == year, VcdbMake.name != "UNKNOWN")
            .group_by(VcdbMake.id, VcdbMake.name)
        )
    else:
        q = select(VcdbMake.id, VcdbMake.name).where(VcdbMake.name != "UNKNOWN")
    rows = (await db.execute(q.order_by(VcdbMake.name))).all()

    if not rows:
        # Static seed fallback
        return [
            {"slug": m.slug, "name": m.name, "is_featured": m.is_featured}
            for m in ymm_data.list_makes(featured_first=featured_first)
        ]

    items = [
        {"id": r[0], "slug": _slug(r[1]), "name": r[1], "is_featured": r[0] in POPULAR_MAKE_IDS}
        for r in rows
    ]
    # Collapse configured makes into one combined picker entry (presentation
    # only — see MERGED_MAKES). If any member survives the year/type filter,
    # replace the members with a single synthetic make.
    for slug, cfg in MERGED_MAKES.items():
        if any(it["name"] in cfg["member_names"] for it in items):
            items = [it for it in items if it["name"] not in cfg["member_names"]]
            items.append({"id": None, "slug": slug, "name": cfg["name"], "is_featured": cfg["is_featured"]})
    if featured_first:
        items.sort(key=lambda x: (not x["is_featured"], x["name"]))
    return items


# ---- Models --------------------------------------------------------------- #


@router.get("/makes/{make_slug}/models")
async def get_models(
    make_slug: str,
    year: int | None = Query(None),
    vehicle_type: str | None = Query(None, description="If set (e.g. 'Van'), restrict to models of this type"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Returns [{slug, name, body_type, year_start, year_end}]."""
    # Resolve make_slug → one or more vcdb make_ids (merged slugs span several).
    member_ids = await _member_make_ids(db, make_slug)
    if not member_ids:
        # Fall back to static seed
        if ymm_data.find_make(make_slug) is None:
            raise HTTPException(404, detail=f"Unknown make: {make_slug}")
        return [
            {"slug": m.slug, "name": m.name, "body_type": m.body_type,
             "year_start": m.year_start, "year_end": m.year_end}
            for m in ymm_data.list_models(make_slug, year=year)
        ]

    # Pull models with year coverage from the DB
    base_q = (
        select(VcdbModel.id, VcdbModel.name, VcdbModel.vehicle_type,
               VcdbBaseVehicle.year)
        .join(VcdbBaseVehicle, VcdbBaseVehicle.model_id == VcdbModel.id)
        .where(VcdbBaseVehicle.make_id.in_(member_ids))
    )
    if year is not None:
        base_q = base_q.where(VcdbBaseVehicle.year == year)
    if vehicle_type is not None:
        base_q = base_q.where(VcdbModel.vehicle_type == vehicle_type)
    rows = (await db.execute(base_q)).all()

    # Aggregate: model_id -> {name, vehicle_type, years[]}
    agg: dict[int, dict] = {}
    for mid, name, vtype, yr in rows:
        if mid not in agg:
            agg[mid] = {"name": name, "vehicle_type": vtype, "years": set()}
        agg[mid]["years"].add(yr)

    result = []
    for mid, info in agg.items():
        years = info["years"]
        result.append({
            "id": mid,
            "slug": _slug(info["name"]),
            "name": info["name"],
            "body_type": (info["vehicle_type"] or "").lower() or None,
            "year_start": min(years) if years else None,
            "year_end": max(years) if years else None,
        })
    result.sort(key=lambda x: x["name"])
    return result


# ---- Van Navigator (side-rail tree: Make -> Family -> Variant) ----------- #


def _van_family_for(make_name: str, model_name: str) -> str:
    """Group sibling van variants under a single family label.

    Rules:
      - "Transit-150 / -250 / -350 / -350 HD"   -> "Transit"
      - "Transit Connect"                       -> "Transit Connect" (own family;
                                                   it's a compact city van,
                                                   different vehicle from Transit)
      - "Sprinter 1500 / 2500 / 3500 / 3500XD"  -> "Sprinter"
      - "eSprinter"                             -> "eSprinter"
      - "E-150 / E-150 Econoline / E-350 SD ..."-> "E-Series"
      - "E-Transit"                             -> "E-Transit" (electric, own family)
      - "NV1500 / NV2500 / NV3500"              -> "NV"
      - "NV200"                                 -> "NV200" (compact, own family)
      - "ProMaster 1500/2500/3500/EV"           -> "ProMaster"
      - "ProMaster City"                        -> "ProMaster City" (compact)
      - "Express 1500/2500/3500"                -> "Express"
      - "Savana 1500/2500/3500"                 -> "Savana"
      - Passenger minivans (Sienna, Odyssey, Pacifica, Caravan, etc.) — each
        gets its own family with one variant.
    """
    n = model_name
    # Ford Transit family
    if n.startswith("Transit-"):
        return "Transit"
    if n == "Transit Connect":
        return "Transit Connect"
    if n == "E-Transit":
        return "E-Transit"
    if n.startswith("E-"):
        return "E-Series"
    # Mercedes
    if n.startswith("Sprinter"):
        return "Sprinter"
    if n == "eSprinter":
        return "eSprinter"
    if n == "Metris":
        return "Metris"
    # Nissan
    if n == "NV200":
        return "NV200"
    if n.startswith("NV") and n != "NV200":
        return "NV"
    # Ram
    if n == "ProMaster City":
        return "ProMaster City"
    if n == "ProMaster EV":
        return "ProMaster EV"
    if n.startswith("ProMaster"):
        return "ProMaster"
    # GM
    if n.startswith("Express"):
        return "Express"
    if n.startswith("Savana"):
        return "Savana"
    # Everything else (Sienna, Odyssey, Pacifica, Voyager, Caravan, Grand
    # Caravan, Town & Country, Quest, Sedona, Routan, Grenadier Quartermaster)
    # is its own family with one variant.
    return n


@router.get("/van-tree")
async def get_van_tree(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Hierarchical tree of every van model in our VCDB, grouped:

      make
        family (e.g. "Transit" groups Transit-150/-250/-350/-350 HD)
          variant (one per vcdb_model — the wheelbase / payload class)

    Each variant carries a `base_vehicle_id` for the newest model year we
    have data for, so clicking it can jump straight into PACE fitment
    without going through /resolve.

    Used by the VanNavigator side-rail. Cargo-van makes (Ford, Mercedes-
    Benz, Ram, Chevrolet, GMC, Nissan) sort first; minivan-only makes
    (Honda, Toyota, Kia, etc.) follow.
    """
    rows = (await db.execute(
        select(
            VcdbMake.id, VcdbMake.name,
            VcdbModel.id, VcdbModel.name,
            VcdbBaseVehicle.id, VcdbBaseVehicle.year,
        )
        .join(VcdbBaseVehicle, VcdbBaseVehicle.make_id == VcdbMake.id)
        .join(VcdbModel,
              (VcdbModel.id == VcdbBaseVehicle.model_id) & (VcdbModel.vehicle_type == "Van"))
        .where(VcdbMake.name != "UNKNOWN")
    )).all()

    # (make_id, model_id) -> latest year row
    latest: dict[tuple[int, int], dict] = {}
    for make_id, make_name, model_id, model_name, bv_id, year in rows:
        key = (make_id, model_id)
        if key not in latest or year > latest[key]["year"]:
            latest[key] = {
                "make_id": make_id, "make_name": make_name,
                "model_id": model_id, "model_name": model_name,
                "year": year, "base_vehicle_id": bv_id,
            }

    # Bucket by (make, family)
    tree: dict[str, dict] = {}
    for v in latest.values():
        family = _van_family_for(v["make_name"], v["model_name"])
        make_key = v["make_name"]
        if make_key not in tree:
            tree[make_key] = {"make": make_key, "families": {}}
        fams = tree[make_key]["families"]
        if family not in fams:
            fams[family] = {"name": family, "variants": []}
        fams[family]["variants"].append({
            "model_id": v["model_id"],
            "name": v["model_name"],
            "year": v["year"],
            "base_vehicle_id": v["base_vehicle_id"],
            "make_slug": _slug(v["make_name"]),
            "model_slug": _slug(v["model_name"]),
        })

    # Cargo-van OEMs first (they're the focus); minivan-only OEMs after
    CARGO_OEMS = ["Ford", "Mercedes-Benz", "Ram", "Chevrolet", "GMC", "Nissan", "Freightliner"]
    def make_rank(name: str) -> tuple[int, str]:
        if name in CARGO_OEMS:
            return (CARGO_OEMS.index(name), name)
        return (len(CARGO_OEMS), name)

    result = []
    for make in sorted(tree.values(), key=lambda x: make_rank(x["make"])):
        # Sort families: known cargo families first (Transit, Sprinter, ProMaster,
        # Express, Savana, E-Series, NV) then alpha
        FAMILY_PRIORITY = [
            "Transit", "Sprinter", "ProMaster", "Express", "Savana", "NV",
            "E-Series", "E-Transit", "eSprinter", "Transit Connect",
            "ProMaster City", "ProMaster EV", "NV200", "Metris",
        ]
        def fam_rank(f: dict) -> tuple[int, str]:
            if f["name"] in FAMILY_PRIORITY:
                return (FAMILY_PRIORITY.index(f["name"]), f["name"])
            return (len(FAMILY_PRIORITY), f["name"])

        fams_sorted = sorted(make["families"].values(), key=fam_rank)
        for fam in fams_sorted:
            # Sort variants by name (so "Transit-150" before "Transit-350")
            fam["variants"].sort(key=lambda v: v["name"])

        result.append({"make": make["make"], "families": fams_sorted})

    return result


# ---- Popular Vans --------------------------------------------------------- #


@router.get("/popular-vans")
async def get_popular_vans(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Curated quick-pick rail of the van families Titan customers ask for
    most often. Returns one entry per "van family" (Sprinter, Transit,
    ProMaster, etc.) — the flagship variant + newest year — so a single
    click jumps the user into Sprinter/Transit/ProMaster fitment without
    picking Year/Make/Model from scratch.

    The "anchor year" is the newest year we have data for that model.
    """
    rows = (await db.execute(
        select(
            VcdbMake.id, VcdbMake.name,
            VcdbModel.id, VcdbModel.name,
            VcdbBaseVehicle.id, VcdbBaseVehicle.year,
        )
        .join(VcdbBaseVehicle, VcdbBaseVehicle.make_id == VcdbMake.id)
        .join(VcdbModel,
              (VcdbModel.id == VcdbBaseVehicle.model_id) & (VcdbModel.vehicle_type == "Van"))
        .where(VcdbMake.name != "UNKNOWN")
    )).all()

    # Group by (make_id, model_id) -> newest base_vehicle row.
    by_model: dict[tuple[int, int], dict] = {}
    for make_id, make_name, model_id, model_name, bv_id, year in rows:
        key = (make_id, model_id)
        existing = by_model.get(key)
        if existing is None or year > existing["year"]:
            by_model[key] = {
                "make_id": make_id, "make_name": make_name,
                "model_id": model_id, "model_name": model_name,
                "year": year, "base_vehicle_id": bv_id,
            }

    # Group by van family + flagship priority. Each family yields ONE entry
    # so the rail doesn't fill up with 4 Sprinter variants.
    # (family_label, priority, model_name_pattern)
    FAMILIES = [
        ("Sprinter",   0, ("Mercedes-Benz", "Sprinter 2500")),  # flagship cargo size
        ("Transit",    1, ("Ford", "Transit-250")),
        ("ProMaster",  2, ("Ram", "ProMaster 2500")),
        ("E-Transit",  3, ("Ford", "E-Transit")),
        ("Express",    4, ("Chevrolet", "Express 2500")),
        ("Savana",     5, ("GMC", "Savana 2500")),
        ("NV",         6, ("Nissan", "NV2500")),
        ("Metris",     7, ("Mercedes-Benz", "Metris")),
        ("E-Series",   8, ("Ford", "E-250")),
        ("Transit Connect", 9, ("Ford", "Transit Connect")),
        ("ProMaster City",  10, ("Ram", "ProMaster City")),
    ]
    out = []
    for label, _pri, (preferred_make, preferred_model) in FAMILIES:
        # Find the best by (make_name, model_name) match — exact match first
        match = next(
            (v for v in by_model.values()
             if v["make_name"] == preferred_make and v["model_name"] == preferred_model),
            None,
        )
        if match is None:
            # Soft fallback: any van starting with this family label
            match = next(
                (v for v in by_model.values()
                 if v["model_name"].lower().startswith(label.lower())),
                None,
            )
        if match is None:
            continue
        out.append({
            "family": label,
            "make": {"slug": _slug(match["make_name"]), "name": match["make_name"]},
            "model": {"slug": _slug(match["model_name"]), "name": match["model_name"]},
            "year": match["year"],
            "base_vehicle_id": match["base_vehicle_id"],
            "label": f"{match['year']} {match['make_name']} {match['model_name']}",
        })
    return out


# ---- Popular Trucks + Popular SUVs --------------------------------------- #


async def _popular_by_families(
    db: AsyncSession,
    vehicle_type: str,
    families: list[tuple[str, tuple[str, str]]],
) -> list[dict]:
    """Generic helper: given a list of (label, (preferred_make, preferred_model))
    tuples, resolve each to its newest base_vehicle_id and return one entry
    per family. Used by /popular-trucks and /popular-suvs (and /popular-vans
    once refactored)."""
    rows = (await db.execute(
        select(
            VcdbMake.id, VcdbMake.name,
            VcdbModel.id, VcdbModel.name,
            VcdbBaseVehicle.id, VcdbBaseVehicle.year,
        )
        .join(VcdbBaseVehicle, VcdbBaseVehicle.make_id == VcdbMake.id)
        .join(VcdbModel,
              (VcdbModel.id == VcdbBaseVehicle.model_id) & (VcdbModel.vehicle_type == vehicle_type))
        .where(VcdbMake.name != "UNKNOWN")
    )).all()
    by_model: dict[tuple[int, int], dict] = {}
    for make_id, make_name, model_id, model_name, bv_id, year in rows:
        key = (make_id, model_id)
        if key not in by_model or year > by_model[key]["year"]:
            by_model[key] = {
                "make_name": make_name, "model_name": model_name,
                "year": year, "base_vehicle_id": bv_id,
            }

    out = []
    for label, (preferred_make, preferred_model) in families:
        match = next(
            (v for v in by_model.values()
             if v["make_name"] == preferred_make and v["model_name"] == preferred_model),
            None,
        )
        if match is None:
            match = next(
                (v for v in by_model.values()
                 if v["model_name"].lower().startswith(preferred_model.lower())),
                None,
            )
        if match is None:
            continue
        out.append({
            "family": label,
            "make": {"slug": _slug(match["make_name"]), "name": match["make_name"]},
            "model": {"slug": _slug(match["model_name"]), "name": match["model_name"]},
            "year": match["year"],
            "base_vehicle_id": match["base_vehicle_id"],
            "label": f"{match['year']} {match['make_name']} {match['model_name']}",
        })
    return out


@router.get("/popular-trucks")
async def get_popular_trucks(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Curated quick-pick rail of the most-shopped pickup trucks."""
    families = [
        ("F-150",       ("Ford", "F-150")),
        ("Silverado",   ("Chevrolet", "Silverado 1500")),
        ("Sierra",      ("GMC", "Sierra 1500")),
        ("Ram 1500",    ("Ram", "1500")),
        ("Tacoma",      ("Toyota", "Tacoma")),
        ("Tundra",      ("Toyota", "Tundra")),
        ("F-250 Super Duty", ("Ford", "F-250 Super Duty")),
        ("F-350 Super Duty", ("Ford", "F-350 Super Duty")),
        ("Silverado HD",     ("Chevrolet", "Silverado 2500 HD")),
        ("Sierra HD",        ("GMC", "Sierra 2500 HD")),
        ("Ram 2500",         ("Ram", "2500")),
        ("Ram 3500",         ("Ram", "3500")),
        ("Frontier",         ("Nissan", "Frontier")),
        ("TITAN",            ("Nissan", "TITAN")),
        ("Gladiator",        ("Jeep", "Gladiator")),
        ("Ridgeline",        ("Honda", "Ridgeline")),
        ("Colorado",         ("Chevrolet", "Colorado")),
        ("Canyon",           ("GMC", "Canyon")),
        ("Ranger",           ("Ford", "Ranger")),
        ("Maverick",         ("Ford", "Maverick")),
    ]
    return await _popular_by_families(db, "Truck", families)


@router.get("/popular-suvs")
async def get_popular_suvs(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Curated quick-pick rail of the most-shopped SUVs."""
    families = [
        ("Wrangler",     ("Jeep", "Wrangler")),
        ("Bronco",       ("Ford", "Bronco")),
        ("4Runner",      ("Toyota", "4Runner")),
        ("Tahoe",        ("Chevrolet", "Tahoe")),
        ("Suburban",     ("Chevrolet", "Suburban")),
        ("Yukon",        ("GMC", "Yukon")),
        ("Yukon XL",     ("GMC", "Yukon XL")),
        ("Expedition",   ("Ford", "Expedition")),
        ("Grand Cherokee", ("Jeep", "Grand Cherokee")),
        ("Cherokee",     ("Jeep", "Cherokee")),
        ("Sequoia",      ("Toyota", "Sequoia")),
        ("Land Cruiser", ("Toyota", "Land Cruiser")),
        ("Armada",       ("Nissan", "Armada")),
        ("Pathfinder",   ("Nissan", "Pathfinder")),
        ("Pilot",        ("Honda", "Pilot")),
        ("Passport",     ("Honda", "Passport")),
        ("Defender",     ("Land Rover", "Defender")),
        ("Range Rover",  ("Land Rover", "Range Rover")),
        ("Grenadier",    ("INEOS", "Grenadier")),
        ("Escalade",     ("Cadillac", "Escalade")),
    ]
    return await _popular_by_families(db, "SUV", families)


# ---- Resolve YMM ---------------------------------------------------------- #


@router.get("/resolve")
async def resolve(
    year: int,
    make_slug: str,
    model_slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Validate a YMM combo, return the canonical labels + base_vehicle_id."""
    member_ids = await _member_make_ids(db, make_slug)
    if not member_ids:
        # Fall back to static seed
        make = ymm_data.find_make(make_slug)
        if make is None:
            raise HTTPException(404, detail=f"Unknown make: {make_slug}")
        model = ymm_data.find_model(make_slug, model_slug)
        if model is None:
            raise HTTPException(404, detail=f"Unknown model: {model_slug}")
        if year < model.year_start or (model.year_end and year > model.year_end):
            raise HTTPException(
                400,
                detail=f"{year} {make.name} {model.name} not produced "
                       f"(years: {model.year_start}-{model.year_end or 'current'})",
            )
        return {
            "year": year,
            "make": {"slug": make.slug, "name": make.name},
            "model": {"slug": model.slug, "name": model.name, "body_type": model.body_type},
            "label": f"{year} {make.name} {model.name}",
        }

    model_id = await _resolve_model_id(db, member_ids, model_slug)
    if model_id is None:
        raise HTTPException(404, detail=f"Unknown model: {model_slug} for make {make_slug}")

    # Resolve against the real make the model belongs to (a merged slug spans
    # several) so the returned label shows the accurate make — e.g. picking
    # "Dodge / RAM" → 1500 resolves to "2026 Ram 1500".
    bv = (await db.execute(
        select(VcdbBaseVehicle.id, VcdbBaseVehicle.make_id, VcdbMake.name, VcdbModel.name, VcdbModel.vehicle_type)
        .join(VcdbMake, VcdbMake.id == VcdbBaseVehicle.make_id)
        .join(VcdbModel, VcdbModel.id == VcdbBaseVehicle.model_id)
        .where(
            VcdbBaseVehicle.year == year,
            VcdbBaseVehicle.make_id.in_(member_ids),
            VcdbBaseVehicle.model_id == model_id,
        )
    )).first()
    if bv is None:
        raise HTTPException(
            400,
            detail=f"{year} {make_slug} {model_slug} not produced (no BaseVehicle row)",
        )
    return {
        "base_vehicle_id": bv[0],
        "year": year,
        # Keep the picker slug the caller passed (so re-opening the picker keeps
        # the merged make selected) but report the real make name for display.
        "make": {"id": bv[1], "slug": make_slug, "name": bv[2]},
        "model": {"id": model_id, "slug": model_slug, "name": bv[3],
                  "body_type": (bv[4] or "").lower() or None},
        "label": f"{year} {bv[2]} {bv[3]}",
    }


# ---- internal helpers ----------------------------------------------------- #


async def _resolve_make_id(db: AsyncSession, make_slug: str) -> int | None:
    """slug -> make_id via name comparison.  Caches in-process."""
    rows = (await db.execute(
        select(VcdbMake.id, VcdbMake.name).where(VcdbMake.name != "UNKNOWN")
    )).all()
    for mid, name in rows:
        if _slug(name) == make_slug:
            return mid
    return None


async def _resolve_model_id(db: AsyncSession, make_ids: list[int], model_slug: str) -> int | None:
    """slug -> model_id, scoped to the chosen make(s). `make_ids` may hold more
    than one id for a merged make (e.g. Dodge + Ram)."""
    rows = (await db.execute(
        select(VcdbModel.id, VcdbModel.name)
        .join(VcdbBaseVehicle, VcdbBaseVehicle.model_id == VcdbModel.id)
        .where(VcdbBaseVehicle.make_id.in_(make_ids), VcdbModel.name != "UNKNOWN")
        .group_by(VcdbModel.id, VcdbModel.name)
    )).all()
    for mid, name in rows:
        if _slug(name) == model_slug:
            return mid
    return None
