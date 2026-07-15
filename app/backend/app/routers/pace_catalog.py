"""PACE-backed catalog API: real fitment-driven YMM + category browse.

Powers the Year/Make/Model selector and the Parts category browse on the
website. Queries the pace_fitment + pace_part + product tables loaded by
`app/scripts/import_pace_brand.py`.

Endpoints:
  GET /api/pace/years                                   — distinct years with fitment data
  GET /api/pace/years/{year}/makes                      — makes available in that year
  GET /api/pace/years/{year}/makes/{make_id}/models     — models for that year+make
  GET /api/pace/resolve?year=&make_id=&model_id=        — resolve to a base_vehicle_id
  GET /api/pace/vehicles/{base_vehicle_id}/part-types   — categories with parts for this vehicle
  GET /api/pace/vehicles/{base_vehicle_id}/brands       — brands with parts for this vehicle
  GET /api/pace/vehicles/{base_vehicle_id}/parts        — parts that fit this vehicle (filterable)
  GET /api/pace/categories                              — top-level part-type categories
  GET /api/pace/part-types?category=                    — part types (optionally in category)
  GET /api/pace/part-types/{part_type_id}/parts         — parts in a category (no vehicle filter)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import pace_search


router = APIRouter(prefix="/api/pace", tags=["pace-catalog"])


# ---- YMM dropdowns ------------------------------------------------------- #


@router.get("/years")
async def get_years(db: AsyncSession = Depends(get_db)) -> list[int]:
    return await pace_search.list_years(db)


@router.get("/years/{year}/makes")
async def get_makes_for_year(year: int, db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await pace_search.list_makes_for_year(db, year)


@router.get("/years/{year}/makes/{make_id}/models")
async def get_models_for_year_make(
    year: int, make_id: int, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return await pace_search.list_models_for_year_make(db, year, make_id)


@router.get("/resolve")
async def resolve_ymm(
    year: int, make_id: int, model_id: int, db: AsyncSession = Depends(get_db)
) -> dict:
    """Resolve YMM to base_vehicle_id (the foreign key the rest of the API uses)."""
    bv = await pace_search.resolve_base_vehicle(db, year, make_id, model_id)
    if bv is None:
        raise HTTPException(404, detail=f"No vehicle for {year} make={make_id} model={model_id}")
    return bv


# ---- Vehicle-scoped fitment lookups -------------------------------------- #


@router.get("/vehicles/{base_vehicle_id}/part-types")
async def vehicle_part_types(
    base_vehicle_id: int, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return await pace_search.part_types_for_vehicle(db, base_vehicle_id)


@router.get("/vehicles/{base_vehicle_id}/brands")
async def vehicle_brands(
    base_vehicle_id: int, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    return await pace_search.brands_for_vehicle(db, base_vehicle_id)


@router.get("/vehicles/{base_vehicle_id}/parts")
async def vehicle_parts(
    base_vehicle_id: int,
    part_type_id: int | None = Query(None, description="Filter to one PartType (category)"),
    brand_id: int | None = Query(None, description="Filter to one brand"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await pace_search.parts_for_vehicle(
        db, base_vehicle_id,
        part_type_id=part_type_id,
        brand_id=brand_id,
        limit=limit,
        offset=offset,
    )


# ---- Iterative facet picker (mirrors PACE's ajaxGetFacet UX) -------------- #

# Qualifier columns we accept as query params (must match PaceFitment column names).
_QUALIFIER_PARAMS = (
    "sub_model_id", "bed_length_id", "bed_type_id", "body_num_doors",
    "body_type_id", "drive_type_id", "engine_base_id", "fuel_type_id",
    "aspiration_id", "region_id", "position_id",
)


def _collect_qualifiers(
    sub_model_id: int | None = None,
    bed_length_id: int | None = None,
    bed_type_id: int | None = None,
    body_num_doors: int | None = None,
    body_type_id: int | None = None,
    drive_type_id: int | None = None,
    engine_base_id: int | None = None,
    fuel_type_id: int | None = None,
    aspiration_id: int | None = None,
    region_id: int | None = None,
    position_id: int | None = None,
) -> dict[str, int | None]:
    return {
        "sub_model_id": sub_model_id,
        "bed_length_id": bed_length_id,
        "bed_type_id": bed_type_id,
        "body_num_doors": body_num_doors,
        "body_type_id": body_type_id,
        "drive_type_id": drive_type_id,
        "engine_base_id": engine_base_id,
        "fuel_type_id": fuel_type_id,
        "aspiration_id": aspiration_id,
        "region_id": region_id,
        "position_id": position_id,
    }


@router.get("/vehicles/{base_vehicle_id}/next-facet")
async def vehicle_next_facet(
    base_vehicle_id: int,
    sub_model_id: int | None = Query(None),
    bed_length_id: int | None = Query(None),
    bed_type_id: int | None = Query(None),
    body_num_doors: int | None = Query(None),
    body_type_id: int | None = Query(None),
    drive_type_id: int | None = Query(None),
    engine_base_id: int | None = Query(None),
    fuel_type_id: int | None = Query(None),
    aspiration_id: int | None = Query(None),
    region_id: int | None = Query(None),
    position_id: int | None = Query(None),
    part_type_id: int | None = Query(None, description="Restrict facet computation to one category"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Returns the NEXT qualifier to ask the user about, or {done: true} if fitment is exact.

    Query params let you pass any qualifiers already picked. Repeat-call this
    endpoint after the user picks each one to walk them through refinement
    (PACE's ajaxGetFacet pattern).
    """
    qualifiers = _collect_qualifiers(
        sub_model_id, bed_length_id, bed_type_id, body_num_doors,
        body_type_id, drive_type_id, engine_base_id, fuel_type_id,
        aspiration_id, region_id, position_id,
    )
    facet = await pace_search.next_facet(db, base_vehicle_id, qualifiers,
                                          part_type_id=part_type_id)
    if facet is None:
        return {"done": True, "qualifiers": qualifiers}
    return {"done": False, "qualifiers": qualifiers, "facet": facet}


@router.get("/vehicles/{base_vehicle_id}/parts-with-status")
async def vehicle_parts_with_status(
    base_vehicle_id: int,
    sub_model_id: int | None = Query(None),
    bed_length_id: int | None = Query(None),
    bed_type_id: int | None = Query(None),
    body_num_doors: int | None = Query(None),
    body_type_id: int | None = Query(None),
    drive_type_id: int | None = Query(None),
    engine_base_id: int | None = Query(None),
    fuel_type_id: int | None = Query(None),
    aspiration_id: int | None = Query(None),
    region_id: int | None = Query(None),
    position_id: int | None = Query(None),
    part_type_id: int | None = Query(None, description="Filter to one PartType"),
    brand_id: int | None = Query(None, description="Filter to one brand"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Like /parts but each item has fitment_status: 'exact' | 'maybe'.

    'maybe' = there's an unpicked qualifier that disambiguates this part.
    UI should show a yellow Maybe badge + prompt the user for more info
    (i.e., call /next-facet to find the missing qualifier).
    """
    qualifiers = _collect_qualifiers(
        sub_model_id, bed_length_id, bed_type_id, body_num_doors,
        body_type_id, drive_type_id, engine_base_id, fuel_type_id,
        aspiration_id, region_id, position_id,
    )
    return await pace_search.parts_for_vehicle_with_status(
        db, base_vehicle_id, qualifiers,
        part_type_id=part_type_id, brand_id=brand_id,
        limit=limit, offset=offset,
    )


# ---- Catalog browse (no vehicle context) --------------------------------- #


@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)) -> list[dict]:
    return await pace_search.list_part_type_categories(db)


@router.get("/part-types")
async def list_part_types(
    category: str | None = Query(None, description="Filter to one PartType category name"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await pace_search.list_part_types(db, category=category)


@router.get("/part-types/{part_type_id}/parts")
async def parts_in_part_type(
    part_type_id: int,
    brand_id: int | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await pace_search.parts_in_part_type(
        db, part_type_id, brand_id=brand_id, limit=limit, offset=offset
    )
