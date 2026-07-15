"""DewEze hydraulic-pump-kit YMM finder endpoints.

Powers the side-navigation drill-down on the Hydraulic Pump Kits
category page, similar to how the van interior + snow plow navigators
work today.

Endpoints:

  GET /api/deweze/makes
      Returns distinct makes with counts and year ranges.
        [{"make": "Ford", "count": 47, "min_year": 1973, "max_year": 2024}, ...]

  GET /api/deweze/years?make=Ford
      Returns year buckets that have kits for the given make.

  GET /api/deweze/engines?make=Ford&year=2018
      Returns distinct engine models for the given make + year.

  GET /api/deweze/kits?make=Ford&year=2018&engine=6.7L
      Filtered list of DewEze kit products that fit the chosen vehicle.
      Each kit includes its primary schematic image + installation PDF URL.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db


router = APIRouter(prefix="/api/deweze", tags=["deweze"])


# Raw SQL — the deweze_application table is small enough (~300-500 rows)
# that ad-hoc queries beat the SQLAlchemy ORM ceremony.


@router.get("/makes")
async def list_makes(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """All makes that have DewEze kits, with kit counts + year range."""
    sql = """
        SELECT
            make,
            COUNT(DISTINCT product_id) AS kit_count,
            MIN(year_start) FILTER (WHERE year_start IS NOT NULL) AS min_year,
            MAX(year_end)   FILTER (WHERE year_end   IS NOT NULL) AS max_year
        FROM deweze_application
        WHERE make IS NOT NULL AND make <> ''
        GROUP BY make
        ORDER BY kit_count DESC, make
    """
    rows = (await db.execute(__import__("sqlalchemy").text(sql))).all()
    return [
        {
            "make": r[0],
            "kit_count": r[1],
            "min_year": r[2],
            "max_year": r[3],
        }
        for r in rows
    ]


@router.get("/years")
async def list_years(
    make: str = Query(..., description="Make filter (e.g., 'Ford')"),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """All year ranges that have kits for the given make.

    Returns one bucket per discrete (year_start, year_end) range with
    counts.  Front-end can flatten these into a clean year picker.
    """
    sql = """
        SELECT year_start, year_end, COUNT(DISTINCT product_id) AS kit_count
        FROM deweze_application
        WHERE make = :make
          AND year_start IS NOT NULL
        GROUP BY year_start, year_end
        ORDER BY year_end DESC NULLS LAST, year_start DESC
    """
    from sqlalchemy import text
    rows = (await db.execute(text(sql), {"make": make})).all()
    return [
        {"year_start": r[0], "year_end": r[1], "kit_count": r[2]}
        for r in rows
    ]


@router.get("/engines")
async def list_engines(
    make: str = Query(..., description="Make filter"),
    year: int | None = Query(None, description="Year to filter (must fall in start/end)"),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """All engine_or_model values for the given make (optionally year)."""
    where = ["make = :make", "engine_or_model IS NOT NULL", "engine_or_model <> ''"]
    params: dict[str, Any] = {"make": make}
    if year is not None:
        where.append("(year_start IS NULL OR year_start <= :year)")
        where.append("(year_end   IS NULL OR year_end   >= :year)")
        params["year"] = year
    sql = f"""
        SELECT engine_or_model, engine_size, engine_fuel,
               COUNT(DISTINCT product_id) AS kit_count
        FROM deweze_application
        WHERE {' AND '.join(where)}
        GROUP BY engine_or_model, engine_size, engine_fuel
        ORDER BY engine_or_model
    """
    from sqlalchemy import text
    rows = (await db.execute(text(sql), params)).all()
    return [
        {
            "engine_or_model": r[0],
            "engine_size": r[1],
            "engine_fuel": r[2],
            "kit_count": r[3],
        }
        for r in rows
    ]


@router.get("/kits")
async def list_kits(
    make: str | None = Query(None),
    year: int | None = Query(None),
    engine: str | None = Query(None, description="Match engine_or_model (substring, case-insensitive)"),
    pump_type: str | None = Query(None, description="A/AA/B etc."),
    include_obsolete: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Filtered DewEze kit products with full per-product details.

    Returns each matching product with its primary schematic image,
    Installation Manual PDF URL, and a list of matching application
    rows so the UI can render "fits 2017-2019 Ford 6.7L diesel".
    """
    where = ["1=1"]
    params: dict[str, Any] = {}
    if make:
        where.append("a.make = :make")
        params["make"] = make
    if year is not None:
        where.append("(a.year_start IS NULL OR a.year_start <= :year)")
        where.append("(a.year_end   IS NULL OR a.year_end   >= :year)")
        params["year"] = year
    if engine:
        where.append("a.engine_or_model ILIKE :engine")
        params["engine"] = f"%{engine}%"
    if pump_type:
        where.append("a.pump_type_short = :pump_type")
        params["pump_type"] = pump_type
    if not include_obsolete:
        where.append("a.obsolete = FALSE")

    sql = f"""
        SELECT DISTINCT p.id, p.sku, p.name, p.description, p.legacy_wsm_url,
               (SELECT url FROM product_image
                WHERE product_id = p.id AND is_primary = TRUE
                ORDER BY id LIMIT 1) AS image_url
        FROM product p
        JOIN deweze_application a ON a.product_id = p.id
        WHERE p.brand_id = 91 AND p.is_for_sale AND NOT p.is_hidden
          AND {' AND '.join(where)}
        ORDER BY p.sku
    """
    from sqlalchemy import text
    prod_rows = (await db.execute(text(sql), params)).all()
    products = [
        {
            "id": r[0],
            "sku": r[1],
            "name": r[2],
            "description": r[3],
            "manual_pdf_url": r[4],
            "image_url": r[5],
        }
        for r in prod_rows
    ]

    # Also load the application rows for each matched product
    if products:
        pids = [p["id"] for p in products]
        app_rows = (await db.execute(text(
            "SELECT product_id, make, engine_or_model, engine_size, engine_fuel, "
            "       year_start, year_end, pump_type_short, pump_type_name, "
            "       pump_port, belt, clutch_configuration, obsolete "
            "FROM deweze_application "
            "WHERE product_id = ANY(:pids) "
            "ORDER BY product_id, year_end DESC NULLS LAST"
        ), {"pids": pids})).all()
        app_by_pid: dict[int, list[dict]] = {}
        for r in app_rows:
            app_by_pid.setdefault(r[0], []).append({
                "make": r[1], "engine_or_model": r[2],
                "engine_size": r[3], "engine_fuel": r[4],
                "year_start": r[5], "year_end": r[6],
                "pump_type_short": r[7], "pump_type_name": r[8],
                "pump_port": r[9], "belt": r[10],
                "clutch_configuration": r[11], "obsolete": r[12],
            })
        for p in products:
            p["applications"] = app_by_pid.get(p["id"], [])

    return {"products": products, "found": len(products)}
