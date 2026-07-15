"""PACE-backed search service: real YMM dropdowns + fitment-filtered parts + category browse.

Reads from vcdb_*, pcdb_*, pace_part, pace_fitment, product, product_image, product_pricing.

Replaces the static seed in `services/ymm_data.py` once PACE ingestion is run.
While vcdb_* is still being backfilled (year=0 placeholder rows), the
year/make/model endpoints return whatever data has been resolved so far.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, case, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Brand,
    PacePart,
    PaceFitment,
    PcdbPartType,
    PcdbPosition,
    Product,
    ProductImage,
    ProductPricing,
    VcdbAspiration,
    VcdbBedLength,
    VcdbBedType,
    VcdbBodyType,
    VcdbDriveType,
    VcdbEngineBase,
    VcdbFuelType,
    VcdbRegion,
    VcdbSubModel,
    VcdbBaseVehicle,
    VcdbMake,
    VcdbModel,
)


# ---------------------------------------------------------------------------
# YMM dropdowns (real, fitment-aware)
# ---------------------------------------------------------------------------


async def list_years(db: AsyncSession) -> list[int]:
    """All years that have at least one BaseVehicle in our fitment data."""
    rows = await db.execute(
        select(distinct(VcdbBaseVehicle.year))
        .where(VcdbBaseVehicle.year > 0)  # filter year=0 placeholders
        .order_by(VcdbBaseVehicle.year.desc())
    )
    return [r[0] for r in rows.all()]


async def list_makes_for_year(db: AsyncSession, year: int) -> list[dict]:
    """Distinct makes with at least one BaseVehicle in `year`."""
    rows = await db.execute(
        select(VcdbMake.id, VcdbMake.name)
        .join(VcdbBaseVehicle, VcdbBaseVehicle.make_id == VcdbMake.id)
        .where(VcdbBaseVehicle.year == year)
        .group_by(VcdbMake.id, VcdbMake.name)
        .order_by(VcdbMake.name)
    )
    return [{"id": r[0], "name": r[1]} for r in rows.all()]


async def list_models_for_year_make(db: AsyncSession, year: int, make_id: int) -> list[dict]:
    """Distinct models with at least one BaseVehicle in (year, make_id)."""
    rows = await db.execute(
        select(VcdbModel.id, VcdbModel.name, VcdbModel.vehicle_type)
        .join(VcdbBaseVehicle, VcdbBaseVehicle.model_id == VcdbModel.id)
        .where(VcdbBaseVehicle.year == year, VcdbBaseVehicle.make_id == make_id)
        .group_by(VcdbModel.id, VcdbModel.name, VcdbModel.vehicle_type)
        .order_by(VcdbModel.name)
    )
    return [{"id": r[0], "name": r[1], "vehicle_type": r[2]} for r in rows.all()]


async def resolve_base_vehicle(db: AsyncSession, year: int, make_id: int, model_id: int) -> dict | None:
    """Return the BaseVehicle id for a YMM combo, or None."""
    bv = (await db.execute(
        select(VcdbBaseVehicle.id, VcdbMake.name, VcdbModel.name)
        .join(VcdbMake, VcdbMake.id == VcdbBaseVehicle.make_id)
        .join(VcdbModel, VcdbModel.id == VcdbBaseVehicle.model_id)
        .where(
            VcdbBaseVehicle.year == year,
            VcdbBaseVehicle.make_id == make_id,
            VcdbBaseVehicle.model_id == model_id,
        )
    )).first()
    if bv is None:
        return None
    return {
        "base_vehicle_id": bv[0],
        "label": f"{year} {bv[1]} {bv[2]}",
        "year": year,
        "make": bv[1],
        "model": bv[2],
    }


# ---------------------------------------------------------------------------
# Fitment-filtered parts search
# ---------------------------------------------------------------------------


async def parts_for_vehicle(
    db: AsyncSession,
    base_vehicle_id: int,
    *,
    part_type_id: int | None = None,
    brand_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """All Products that fit the given BaseVehicle, optionally filtered by category and brand.

    Returns: {total, items: [{sku, name, brand, image_url, list_price, jobber_price, part_types}]}
    """
    # Base query: fitments → pace_parts → products
    fitment_q = (
        select(PaceFitment.pace_part_id)
        .where(PaceFitment.base_vehicle_id == base_vehicle_id)
        .distinct()
    )
    if part_type_id is not None:
        fitment_q = fitment_q.where(PaceFitment.part_type_id == part_type_id)

    pp_q = (
        select(PacePart.id, PacePart.product_id)
        .where(PacePart.id.in_(fitment_q))
    )
    if brand_id is not None:
        pp_q = pp_q.where(PacePart.brand_id == brand_id)

    # Outer query: hydrate products
    base = (
        select(Product)
        .options(selectinload(Product.brand))
        .where(Product.id.in_(select(PacePart.product_id).where(PacePart.id.in_(fitment_q),
                                                                PacePart.product_id.is_not(None))))
    )
    if brand_id is not None:
        base = base.where(Product.brand_id == brand_id)
    base = base.where(Product.is_hidden == False, Product.is_for_sale == True)  # noqa: E712

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    rows = (await db.execute(
        base.order_by(Product.name).limit(limit).offset(offset)
    )).scalars().all()

    items = []
    if rows:
        product_ids = [r.id for r in rows]
        # Primary images
        imgs = (await db.execute(
            select(ProductImage.product_id, ProductImage.url)
            .where(ProductImage.product_id.in_(product_ids), ProductImage.is_primary == True)  # noqa: E712
        )).all()
        img_map = {pid: u for pid, u in imgs}

        # Current LST price per product (cheap fallback to first available)
        prices = (await db.execute(
            select(ProductPricing.product_id, ProductPricing.price_type, ProductPricing.price)
            .where(ProductPricing.product_id.in_(product_ids), ProductPricing.is_current == True)  # noqa: E712
        )).all()
        price_map: dict[int, dict[str, Any]] = {}
        for pid, ptype, price in prices:
            price_map.setdefault(pid, {})[ptype] = price

        for p in rows:
            pmap = price_map.get(p.id, {})
            items.append({
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "brand": p.brand.name if p.brand else None,
                "brand_aaia": p.brand.aaia_code if p.brand else None,
                "image_url": img_map.get(p.id),
                "list_price": float(pmap["LST"]) if "LST" in pmap else None,
                "jobber_price": float(pmap["JBR"]) if "JBR" in pmap else None,
                "msrp": float(pmap["MSR"]) if "MSR" in pmap else None,
            })
    return {"total": total, "items": items, "limit": limit, "offset": offset}


async def part_types_for_vehicle(db: AsyncSession, base_vehicle_id: int) -> list[dict]:
    """Categories (PartTypes) with at least one fitting part for this vehicle.

    Powers the left-rail category facet on YMM result pages.
    """
    rows = (await db.execute(
        select(PcdbPartType.id, PcdbPartType.name, PcdbPartType.category_name,
               func.count(distinct(PaceFitment.pace_part_id)).label("part_count"))
        .join(PaceFitment, PaceFitment.part_type_id == PcdbPartType.id)
        .where(PaceFitment.base_vehicle_id == base_vehicle_id)
        .group_by(PcdbPartType.id, PcdbPartType.name, PcdbPartType.category_name)
        .order_by(PcdbPartType.name)
    )).all()
    return [
        {"id": r[0], "name": r[1], "category": r[2], "part_count": r[3]}
        for r in rows
    ]


async def brands_for_vehicle(db: AsyncSession, base_vehicle_id: int) -> list[dict]:
    """Brands with at least one fitting part for this vehicle (brand-filter facet)."""
    rows = (await db.execute(
        select(Brand.id, Brand.name, Brand.aaia_code,
               func.count(distinct(PacePart.id)).label("part_count"))
        .join(PacePart, PacePart.brand_id == Brand.id)
        .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
        .where(PaceFitment.base_vehicle_id == base_vehicle_id)
        .group_by(Brand.id, Brand.name, Brand.aaia_code)
        .order_by(Brand.name)
    )).all()
    return [
        {"id": r[0], "name": r[1], "aaia_code": r[2], "part_count": r[3]}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Category browse (no vehicle context — full catalog by category)
# ---------------------------------------------------------------------------


async def list_part_type_categories(db: AsyncSession) -> list[dict]:
    """Top-level part-type categories. Returns distinct category_name values
    plus the count of part-types under each."""
    rows = (await db.execute(
        select(PcdbPartType.category_name, func.count().label("part_type_count"))
        .where(PcdbPartType.category_name.is_not(None))
        .group_by(PcdbPartType.category_name)
        .order_by(PcdbPartType.category_name)
    )).all()
    return [{"category": r[0], "part_type_count": r[1]} for r in rows]


async def list_part_types(db: AsyncSession, category: str | None = None) -> list[dict]:
    """All PartTypes, optionally filtered to one category, with the count of
    distinct parts available across all brands."""
    q = (
        select(PcdbPartType.id, PcdbPartType.name, PcdbPartType.category_name,
               func.count(distinct(PacePart.id)).label("part_count"))
        .join(PacePart, PacePart.part_terminology_id == PcdbPartType.id)
    )
    if category is not None:
        q = q.where(PcdbPartType.category_name == category)
    q = q.group_by(PcdbPartType.id, PcdbPartType.name, PcdbPartType.category_name)
    q = q.order_by(PcdbPartType.name)
    rows = (await db.execute(q)).all()
    return [
        {"id": r[0], "name": r[1], "category": r[2], "part_count": r[3]}
        for r in rows
    ]


async def parts_in_part_type(
    db: AsyncSession,
    part_type_id: int,
    *,
    brand_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Browse parts in a category (no fitment filter).

    Useful for Phase-1 catalog pages where the user lands without selecting
    a vehicle yet.
    """
    base = (
        select(Product)
        .options(selectinload(Product.brand))
        .join(PacePart, PacePart.product_id == Product.id)
        .where(PacePart.part_terminology_id == part_type_id)
        .where(Product.is_hidden == False, Product.is_for_sale == True)  # noqa: E712
    )
    if brand_id is not None:
        base = base.where(Product.brand_id == brand_id)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(
        base.order_by(Product.name).limit(limit).offset(offset)
    )).scalars().all()
    items = [
        {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "brand": p.brand.name if p.brand else None,
            "brand_aaia": p.brand.aaia_code if p.brand else None,
        }
        for p in rows
    ]
    return {"total": total, "items": items, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Iterative facet picker (mirrors PACE's ajaxGetFacet UX)
# ---------------------------------------------------------------------------

# Order matches PACE's typical refinement flow: ask the most-discriminating
# qualifiers first (sub-model, then truck-specific dims, then engine specs).
# Each entry: (PaceFitment column, user-facing label, name table model or None for raw int, name column or None)
FACET_PRIORITY = [
    ("sub_model_id", "Sub Model", VcdbSubModel, "name"),
    ("bed_length_id", "Bed Length", VcdbBedLength, "label"),
    ("bed_type_id", "Bed Type", VcdbBedType, "name"),
    ("body_num_doors", "Doors", None, None),  # plain int, no name table
    ("body_type_id", "Body Type", VcdbBodyType, "name"),
    ("drive_type_id", "Drive Type", VcdbDriveType, "name"),
    ("engine_base_id", "Engine", VcdbEngineBase, "label"),
    ("fuel_type_id", "Fuel Type", VcdbFuelType, "name"),
    ("aspiration_id", "Aspiration", VcdbAspiration, "name"),
    ("region_id", "Region", VcdbRegion, "name"),
    ("position_id", "Position", PcdbPosition, "name"),
]


def _build_qualifier_filters(qualifiers: dict[str, int | None]):
    """Each picked qualifier → 'fitment column == val OR column IS NULL'.
    NULL fitment columns are wildcards — that part fits regardless of that qualifier.
    """
    filters = []
    for col_name, val in (qualifiers or {}).items():
        if val is None or val == "":
            continue
        col = getattr(PaceFitment, col_name, None)
        if col is None:
            continue
        try:
            iv = int(val)
        except (ValueError, TypeError):
            continue
        filters.append(or_(col == iv, col.is_(None)))
    return filters


async def next_facet(
    db: AsyncSession,
    base_vehicle_id: int,
    qualifiers: dict[str, int | None] | None = None,
    *,
    part_type_id: int | None = None,
) -> dict[str, Any] | None:
    """Determine the next required qualifier for full fitment certainty.

    qualifiers: {fitment_column_name: int_id} of already-picked refinements.
    part_type_id: optional filter — only consider fitments in this category.

    Returns:
      {"name": "sub_model_id", "label": "Sub Model", "choices": {"656": "XLT", ...}}
      OR None when fitment is fully qualified (no ambiguous qualifier remaining).
    """
    qualifiers = qualifiers or {}
    base_filters = [PaceFitment.base_vehicle_id == base_vehicle_id]
    if part_type_id is not None:
        base_filters.append(PaceFitment.part_type_id == part_type_id)
    base_filters.extend(_build_qualifier_filters(qualifiers))

    for col_name, label, name_model, name_col in FACET_PRIORITY:
        if qualifiers.get(col_name):
            continue
        col = getattr(PaceFitment, col_name)
        rows = (await db.execute(
            select(distinct(col)).where(and_(*base_filters, col.is_not(None)))
        )).all()
        distinct_vals = [r[0] for r in rows if r[0] is not None]
        if len(distinct_vals) <= 1:
            continue  # this qualifier doesn't disambiguate

        if name_model is None:
            # Raw int — sort numerically, label = str(value)
            choices = {str(v): str(v) for v in sorted(distinct_vals)}
        else:
            name_q = (
                select(name_model.id, getattr(name_model, name_col))
                .where(name_model.id.in_(distinct_vals))
            )
            name_rows = (await db.execute(name_q)).all()
            name_map = {r[0]: (r[1] or f"{label}#{r[0]}") for r in name_rows}
            # Include any IDs whose name row is missing (placeholder fallback)
            for v in distinct_vals:
                name_map.setdefault(v, f"{label}#{v}")
            choices = dict(sorted(
                ((str(v), name_map[v]) for v in distinct_vals),
                key=lambda kv: kv[1],
            ))
        return {
            "name": col_name,
            "label": label,
            "choices": choices,
        }
    return None


async def parts_for_vehicle_with_status(
    db: AsyncSession,
    base_vehicle_id: int,
    qualifiers: dict[str, int | None] | None = None,
    *,
    part_type_id: int | None = None,
    brand_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Fitment-aware product list with per-part 'fitment_status' (exact|maybe).

    'maybe' = the user hasn't picked enough qualifiers to disambiguate; product
    has multiple fitment rows that differ on an unpicked qualifier (e.g. they
    haven't told us bed length yet, and this part has 3 bed-length variants).
    """
    qualifiers = qualifiers or {}
    fitment_filters = [PaceFitment.base_vehicle_id == base_vehicle_id]
    if part_type_id is not None:
        fitment_filters.append(PaceFitment.part_type_id == part_type_id)
    fitment_filters.extend(_build_qualifier_filters(qualifiers))

    candidate_part_ids_q = (
        select(distinct(PaceFitment.pace_part_id)).where(and_(*fitment_filters))
    )

    pq = (
        select(Product)
        .options(selectinload(Product.brand))
        .join(PacePart, PacePart.product_id == Product.id)
        .where(PacePart.id.in_(candidate_part_ids_q))
        .where(Product.is_hidden == False, Product.is_for_sale == True)  # noqa: E712
    )
    if brand_id is not None:
        pq = pq.where(Product.brand_id == brand_id)
    total = (await db.execute(select(func.count()).select_from(pq.subquery()))).scalar_one()
    products = (await db.execute(
        pq.order_by(Product.name).limit(limit).offset(offset)
    )).scalars().all()

    items: list[dict] = []
    if products:
        product_ids = [p.id for p in products]
        # Pull all matching fitments for these products (to compute status)
        f_rows = (await db.execute(
            select(PaceFitment, PacePart.product_id)
            .join(PacePart, PacePart.id == PaceFitment.pace_part_id)
            .where(PacePart.product_id.in_(product_ids))
            .where(and_(*fitment_filters))
        )).all()
        fitments_by_product: dict[int, list] = {}
        for f, pid in f_rows:
            fitments_by_product.setdefault(pid, []).append(f)

        imgs = (await db.execute(
            select(ProductImage.product_id, ProductImage.url)
            .where(ProductImage.product_id.in_(product_ids), ProductImage.is_primary == True)  # noqa: E712
        )).all()
        img_map = {pid: u for pid, u in imgs}

        prices = (await db.execute(
            select(ProductPricing.product_id, ProductPricing.price_type, ProductPricing.price)
            .where(ProductPricing.product_id.in_(product_ids), ProductPricing.is_current == True)  # noqa: E712
        )).all()
        price_map: dict[int, dict[str, Any]] = {}
        for pid, ptype, price in prices:
            price_map.setdefault(pid, {})[ptype] = price

        for p in products:
            fits = fitments_by_product.get(p.id, [])
            status = "exact"
            if len(fits) > 1:
                for col_name, *_ in FACET_PRIORITY:
                    if qualifiers.get(col_name):
                        continue
                    vals = {getattr(f, col_name) for f in fits}
                    vals.discard(None)
                    if len(vals) > 1:
                        status = "maybe"
                        break
            pmap = price_map.get(p.id, {})
            items.append({
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "brand": p.brand.name if p.brand else None,
                "brand_aaia": p.brand.aaia_code if p.brand else None,
                "image_url": img_map.get(p.id),
                "list_price": float(pmap["LST"]) if "LST" in pmap else None,
                "jobber_price": float(pmap["JBR"]) if "JBR" in pmap else None,
                "msrp": float(pmap["MSR"]) if "MSR" in pmap else None,
                "fitment_status": status,
            })
    return {
        "total": total,
        "items": items,
        "limit": limit,
        "offset": offset,
        "qualifiers": qualifiers,
    }
