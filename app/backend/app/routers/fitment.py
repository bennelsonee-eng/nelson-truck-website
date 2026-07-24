"""Fitment landing pages — programmatic {category}×{vehicle} SEO/AEO pages.

"Floor Mats for Ford F-250" style pages, generated only for combos that have
at least one IN-STOCK product that fits (lean, high-quality — no thin pages).
This is the biggest organic + AI-answer lever for a fitment catalog: it matches
exactly how buyers (and AI shopping assistants) phrase queries.

Data path: pace_fitment (ACES/VCDB, ~5.6M rows) → pace_part.product_id → product,
joined to vcdb_base_vehicle → vcdb_make/vcdb_model, filtered to in-stock
(product_inventory.on_hand > 0). URLs use slugified LEAF names (the stored
category.slug is hierarchical/slashed, so we slugify names into clean single
path segments and resolve back to ids).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fitment", tags=["fitment"])

# Postgres slugify matching the frontend's: lowercase, non-alphanumeric runs → '-',
# trim leading/trailing '-'. Keep in lockstep with slugify() in the frontend.
def _slug(col: str) -> str:
    return f"lower(trim(both '-' from regexp_replace({col}, '[^a-z0-9]+', '-', 'gi')))"


# The set of valid combos changes only when inventory/fitment changes, and the
# enumeration is a heavy aggregate — cache it (also drives the sitemap).
_combos_cache: dict[str, Any] = {"data": None, "at": 0.0}
_COMBOS_TTL = 3600.0  # 1 hour


async def get_combos(db: AsyncSession) -> dict[str, Any]:
    """Every {category, make, model} combo with >=1 in-stock fitted product.
    Cached for an hour. Shared by the /combos API and the fitment sitemap."""
    now = time.time()
    if _combos_cache["data"] is not None and now - _combos_cache["at"] < _COMBOS_TTL:
        return _combos_cache["data"]

    rows = (await db.execute(text(f"""
        SELECT DISTINCT
            {_slug('c.name')}  AS category,
            {_slug('mk.name')} AS make,
            {_slug('md.name')} AS model
        FROM product_inventory pi
        JOIN product p        ON p.id = pi.product_id
                              AND p.is_hidden_retail = false AND p.is_for_sale = true
        JOIN pace_part pp     ON pp.product_id = p.id
        JOIN pace_fitment pf  ON pf.pace_part_id = pp.id
        JOIN vcdb_base_vehicle bv ON bv.id = pf.base_vehicle_id
        JOIN vcdb_make mk     ON mk.id = bv.make_id
        JOIN vcdb_model md    ON md.id = bv.model_id
        JOIN product_category pc ON pc.product_id = p.id
        JOIN category c       ON c.id = pc.category_id
        WHERE pi.on_hand > 0
    """))).all()

    combos = [{"category": r.category, "make": r.make, "model": r.model}
              for r in rows if r.category and r.make and r.model]
    data = {"count": len(combos), "combos": combos}
    _combos_cache["data"] = data
    _combos_cache["at"] = now
    return data


@router.get("/combos")
async def combos(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Every {category, make, model} combo with >=1 in-stock fitted product.
    Drives /sitemap-fitment.xml and internal linking. Cached for an hour."""
    return await get_combos(db)


@router.get("/page/{category}/{make}/{model}")
async def page(category: str, make: str, model: str,
               db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Data for one fitment landing page: resolve the slugs to ids, then return
    the in-stock products (in this category) that fit this make/model."""
    # 1) Resolve make + model + category ids from their slugs (small, indexed tables).
    mk = (await db.execute(text(f"""
        SELECT id, name FROM vcdb_make WHERE {_slug('name')} = :s LIMIT 1
    """), {"s": make})).first()
    if not mk:
        raise HTTPException(404, f"Unknown make: {make}")

    md = (await db.execute(text(f"""
        SELECT id, name FROM vcdb_model
        WHERE make_id = :mid AND {_slug('name')} = :s LIMIT 1
    """), {"mid": mk.id, "s": model})).first()
    if not md:
        raise HTTPException(404, f"Unknown model: {make}/{model}")

    # A slug can (rarely) map to >1 category name; prefer the one that actually
    # has matching in-stock fitted products for this vehicle.
    cats = (await db.execute(text(f"""
        SELECT id, name, full_path FROM category
        WHERE is_active AND {_slug('name')} = :s
        ORDER BY depth
    """), {"s": category})).all()
    if not cats:
        raise HTTPException(404, f"Unknown category: {category}")

    # base_vehicle ids for this make/model (all years).
    bv_ids = [r.id for r in (await db.execute(text("""
        SELECT id, year FROM vcdb_base_vehicle WHERE make_id = :mid AND model_id = :mdid
    """), {"mid": mk.id, "mdid": md.id})).all()]
    years = (await db.execute(text("""
        SELECT min(year), max(year) FROM vcdb_base_vehicle WHERE make_id=:mid AND model_id=:mdid
    """), {"mid": mk.id, "mdid": md.id})).first()

    # 2) Pick the category (of possibly-several same-slug) that has products, and
    #    fetch its in-stock fitted product cards.
    chosen = None
    products: list[dict[str, Any]] = []
    for c in cats:
        rows = (await db.execute(text("""
            SELECT p.id, p.sku, p.name, b.name AS brand,
                   (SELECT url FROM product_image WHERE product_id = p.id
                      ORDER BY sort_order LIMIT 1) AS image_url,
                   COALESCE((SELECT sum(on_hand) FROM product_inventory
                              WHERE product_id = p.id), 0) AS stock_total
            FROM product p
            JOIN brand b ON b.id = p.brand_id
            WHERE p.is_hidden_retail = false AND p.is_for_sale = true
              AND EXISTS (SELECT 1 FROM product_inventory pi
                          WHERE pi.product_id = p.id AND pi.on_hand > 0)
              AND EXISTS (SELECT 1 FROM product_category pc
                          WHERE pc.product_id = p.id AND pc.category_id = :cid)
              AND EXISTS (SELECT 1 FROM pace_part pp
                          JOIN pace_fitment pf ON pf.pace_part_id = pp.id
                          WHERE pp.product_id = p.id
                            AND pf.base_vehicle_id = ANY(:bv))
            ORDER BY stock_total DESC, p.name
            LIMIT 200
        """), {"cid": c.id, "bv": bv_ids})).all()
        if rows:
            chosen = c
            image_none = "photocomingsoon"
            products = [{
                "id": r.id, "sku": r.sku, "name": r.name, "brand": r.brand,
                "image_url": (r.image_url if r.image_url and image_none not in r.image_url.lower() else None),
                "in_stock": True, "stock_total": int(r.stock_total or 0),
            } for r in rows]
            break

    if chosen is None or not products:
        raise HTTPException(404, f"No in-stock products for {category}/{make}/{model}")

    return {
        "category": {"name": chosen.name, "slug": category, "full_path": chosen.full_path},
        "make": mk.name,
        "model": md.name,
        "year_min": years[0] if years else None,
        "year_max": years[1] if years else None,
        "count": len(products),
        "products": products,
    }
