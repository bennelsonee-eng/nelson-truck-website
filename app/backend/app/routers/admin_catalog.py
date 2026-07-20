"""Admin catalog tree — show/hide + shipping-mode + flat-rate overrides.

The Windows-explorer tree the admin uses to turn manufacturer lines on/off
(completely or partially) and set shipping parameters. Rooted at the
manufacturer line (brand / AAIA), narrowing brand → category → subcategory →
curated filters → part numbers, with a default catch-all at every level so no
part is orphaned. Every route is admin-only.

    GET  /api/admin/catalog/fields                 field metadata for the UI
    GET  /api/admin/catalog/roots                  manufacturer lines + counts
    GET  /api/admin/catalog/children               child categories + buckets
    GET  /api/admin/catalog/filters                curated filters for a scope
    GET  /api/admin/catalog/parts                  paginated parts in a scope
    GET  /api/admin/catalog/overrides              overrides at a scope
    POST /api/admin/catalog/override               upsert one field override
    DELETE /api/admin/catalog/override/{id}         clear an override
    GET  /api/admin/catalog/pending                count of un-applied toggles
    POST /api/admin/catalog/apply-now              resolve now + reindex

Writes only change `catalog_override`; the resolver materializes them onto the
derived product columns at the nightly re-index or on Apply-now.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.dependencies import require_admin
from app.models import (
    Brand,
    CatalogOverride,
    Category,
    Product,
    ProductCategory,
    ShippingMode,
    User,
)
from app.services.catalog_visibility import (
    derive_scope_type,
    resolve_effective,
    scope_key_for,
)

log = logging.getLogger("admin_catalog")
router = APIRouter(prefix="/api/admin/catalog", tags=["admin-catalog"])

FieldT = Literal["hidden", "shipping_mode", "flat_ship_amount"]

# Field metadata drives the UI's per-node controls. Values are the strings
# stored in catalog_override.value; the resolver casts them.
FIELD_META: list[dict[str, Any]] = [
    {
        "key": "hidden", "label": "Visibility", "type": "enum",
        "values": [
            {"value": "false", "label": "Visible"},
            {"value": "true", "label": "Hidden"},
        ],
    },
    {
        "key": "shipping_mode", "label": "Shipping", "type": "enum",
        "values": [
            {"value": ShippingMode.SHIP.value, "label": "Ship"},
            {"value": ShippingMode.TRUCK_FREIGHT.value, "label": "Truck Freight"},
            {"value": ShippingMode.WILL_CALL.value, "label": "Will Call (pickup only)"},
        ],
    },
    {
        "key": "flat_ship_amount", "label": "Flat shipping", "type": "money",
        "null_label": "Weight-based (default)",
        "help": "Blank = weight-based; 0 = free; e.g. 19.00 = flat $19. Retail only.",
    },
]

_SHIPPING_VALUES = {m.value for m in ShippingMode}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _validate_value(field: str, value: str | None) -> str:
    """Normalize/validate an override value for a field. Raises 400 on bad input."""
    if field == "hidden":
        v = str(value).strip().lower()
        if v not in ("true", "false"):
            raise HTTPException(400, "hidden value must be 'true' or 'false'")
        return v
    if field == "shipping_mode":
        v = str(value).strip()
        if v not in _SHIPPING_VALUES:
            raise HTTPException(400, f"shipping_mode must be one of {sorted(_SHIPPING_VALUES)}")
        return v
    if field == "flat_ship_amount":
        # "" / None => NULL (weight-based); else a non-negative money value.
        if value is None or str(value).strip() == "":
            return ""
        try:
            from decimal import Decimal
            d = Decimal(str(value).strip())
        except Exception:
            raise HTTPException(400, "flat_ship_amount must be a number, blank, or 0")
        if d < 0:
            raise HTTPException(400, "flat_ship_amount cannot be negative")
        return f"{d:.2f}"
    raise HTTPException(400, f"unknown field {field!r}")


async def _descendant_category_ids(db: AsyncSession, category_id: int) -> list[int]:
    row = (await db.execute(
        select(Category.full_path).where(Category.id == category_id)
    )).scalar_one_or_none()
    if row is None:
        return []
    ids = (await db.execute(
        select(Category.id).where(
            or_(Category.full_path == row, Category.full_path.like(f"{row} > %"))
        )
    )).scalars().all()
    return list(ids)


async def _scope_product_ids_subq(
    db: AsyncSession,
    *,
    brand_id: int | None,
    category_id: int | None,
    uncategorized: bool = False,
):
    """A product-id predicate for a tree scope (brand ∩ category, or brand ∩
    no-category for the 'uncategorized' bucket). Returns a SQLAlchemy predicate
    over Product, ANDed by the caller."""
    preds = []
    if brand_id is not None:
        preds.append(Product.brand_id == brand_id)
    if category_id is not None:
        cat_ids = await _descendant_category_ids(db, category_id)
        if not cat_ids:
            preds.append(Product.id == -1)
        else:
            preds.append(Product.id.in_(
                select(ProductCategory.product_id).where(ProductCategory.category_id.in_(cat_ids))
            ))
    if uncategorized:
        preds.append(~Product.id.in_(select(ProductCategory.product_id)))
    return and_(*preds) if preds else None


def _override_row(ov: CatalogOverride) -> dict[str, Any]:
    pending = ov.applied_at is None or (ov.updated_at and ov.applied_at < ov.updated_at)
    return {
        "id": ov.id,
        "scope_type": ov.scope_type,
        "scope_key": ov.scope_key,
        "field": ov.field,
        "value": ov.value,
        "brand_id": ov.brand_id,
        "category_id": ov.category_id,
        "product_id": ov.product_id,
        "attr_key": ov.attr_key,
        "attr_value": ov.attr_value,
        "note": ov.note,
        "pending": bool(pending),
        "updated_by": ov.updated_by,
        "updated_at": ov.updated_at.isoformat() if ov.updated_at else None,
    }


async def _overrides_at(db: AsyncSession, scope_key: str) -> dict[str, dict]:
    """Explicit overrides at exactly this scope, keyed by field."""
    rows = (await db.execute(
        select(CatalogOverride).where(CatalogOverride.scope_key == scope_key)
    )).scalars().all()
    return {r.field: _override_row(r) for r in rows}


# --------------------------------------------------------------------------- #
# Metadata + roots
# --------------------------------------------------------------------------- #

@router.get("/fields")
async def get_fields(admin: User = Depends(require_admin)) -> dict[str, Any]:
    return {"fields": FIELD_META}


@router.get("/roots")
async def get_roots(
    q: str | None = Query(None, description="Filter manufacturer lines by name"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Manufacturer lines (brands) with product counts + their brand-level overrides."""
    stmt = (
        select(Brand.id, Brand.name, Brand.aaia_code, Brand.is_active,
               func.count(Product.id))
        .join(Product, Product.brand_id == Brand.id)
        .group_by(Brand.id, Brand.name, Brand.aaia_code, Brand.is_active)
    )
    if q and q.strip():
        stmt = stmt.where(Brand.name.ilike(f"%{q.strip()}%"))
    stmt = stmt.order_by(Brand.name)
    rows = (await db.execute(stmt)).all()

    # Brand-level overrides (brand set; no category/attr/product) in one query.
    brand_ovs = (await db.execute(
        select(CatalogOverride).where(
            CatalogOverride.brand_id.is_not(None),
            CatalogOverride.category_id.is_(None),
            CatalogOverride.attr_key.is_(None),
            CatalogOverride.product_id.is_(None),
        )
    )).scalars().all()
    by_brand: dict[int, dict[str, dict]] = {}
    for ov in brand_ovs:
        by_brand.setdefault(ov.brand_id, {})[ov.field] = _override_row(ov)

    from app.models import Kit
    kit_count = (await db.execute(
        select(func.count()).select_from(Kit).where(Kit.product_id.is_not(None))
    )).scalar_one()

    return {
        "nodes": [
            {
                "type": "brand",
                "brand_id": bid,
                "label": name,
                "aaia_code": aaia,
                "count": cnt,
                "expandable": True,
                "scope": {"brand_id": bid},
                "scope_key": scope_key_for(brand_id=bid),
                "overrides": by_brand.get(bid, {}),
            }
            for bid, name, aaia, _active, cnt in rows
        ],
        "total": len(rows),
        "kit_count": kit_count,
    }


# --------------------------------------------------------------------------- #
# Children (categories + buckets)
# --------------------------------------------------------------------------- #

@router.get("/children")
async def get_children(
    brand_id: int = Query(..., description="Manufacturer line"),
    category_id: int | None = Query(None, description="Parent category, or none for the line root"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Child category nodes under a brand (optionally under a parent category),
    plus the catch-all buckets. Only categories that contain this brand's
    products are shown; every part stays reachable via a bucket."""
    # The categories this brand's products sit in, plus every ancestor so
    # intermediate tree nodes appear.
    brand_leaf_paths = (await db.execute(
        select(func.distinct(Category.full_path))
        .select_from(Category)
        .join(ProductCategory, ProductCategory.category_id == Category.id)
        .join(Product, and_(Product.id == ProductCategory.product_id, Product.brand_id == brand_id))
    )).scalars().all()
    visible_paths: set[str] = set()
    for p in brand_leaf_paths:
        parts = [seg.strip() for seg in p.split(" > ")]
        for i in range(len(parts)):
            visible_paths.add(" > ".join(parts[: i + 1]))

    # Direct children of the parent category (or top-level).
    if category_id is None:
        parent_path = None
        child_q = select(Category).where(Category.parent_id.is_(None))
    else:
        parent_path = (await db.execute(
            select(Category.full_path).where(Category.id == category_id)
        )).scalar_one_or_none()
        child_q = select(Category).where(Category.parent_id == category_id)
    children = [c for c in (await db.execute(child_q.order_by(Category.sort_order, Category.name))).scalars().all()
                if c.full_path in visible_paths]

    nodes: list[dict[str, Any]] = []
    for c in children:
        pred = await _scope_product_ids_subq(db, brand_id=brand_id, category_id=c.id)
        cnt = (await db.execute(select(func.count()).select_from(Product).where(pred))).scalar_one()
        sk = scope_key_for(brand_id=brand_id, category_id=c.id)
        nodes.append({
            "type": "category",
            "brand_id": brand_id,
            "category_id": c.id,
            "label": c.name,
            "count": cnt,
            "expandable": True,
            "scope": {"brand_id": brand_id, "category_id": c.id},
            "scope_key": sk,
            "overrides": await _overrides_at(db, sk),
        })

    # Catch-all buckets.
    if category_id is None:
        # Uncategorized: brand parts with no category at all.
        pred = await _scope_product_ids_subq(db, brand_id=brand_id, category_id=None, uncategorized=True)
        cnt = (await db.execute(select(func.count()).select_from(Product).where(pred))).scalar_one()
        if cnt:
            nodes.append({
                "type": "bucket", "bucket": "uncategorized",
                "brand_id": brand_id, "label": "Uncategorized (no category)",
                "count": cnt, "expandable": True,
                "scope": {"brand_id": brand_id, "uncategorized": True},
                "scope_key": scope_key_for(brand_id=brand_id),  # toggles the line; parts listed via /parts
                "overrides": {},
            })

    return {"nodes": nodes, "parent_category_id": category_id, "parent_path": parent_path}


# --------------------------------------------------------------------------- #
# Parts (leaf listing) + bulk apply
# --------------------------------------------------------------------------- #

async def _parts_where(
    db: AsyncSession,
    *,
    brand_id: int | None,
    category_id: int | None,
    uncategorized: bool,
    attr_key: str | None,
    attr_value: str | None,
    q: str | None,
    kits: bool = False,
):
    """The Product WHERE used by both the parts list and the bulk-apply tool —
    scope (brand ∩ category, or uncategorized, or kit packages) ∩ optional
    curated filter ∩ optional text search."""
    pred = await _scope_product_ids_subq(
        db, brand_id=brand_id, category_id=category_id, uncategorized=uncategorized
    )
    conds = [] if pred is None else [pred]
    if kits:
        # Kit packages: the sellable package product of each kit.
        from app.models import Kit
        conds.append(Product.id.in_(select(Kit.product_id).where(Kit.product_id.is_not(None))))
    if attr_key and attr_value is not None:
        from app.services.catalog_visibility import _attr_product_ids_select
        sel = await _attr_product_ids_select(db, attr_key, attr_value)
        conds.append(Product.id.in_(sel) if sel is not None else Product.id == -1)
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(or_(Product.sku.ilike(like), Product.name.ilike(like)))
    return and_(*conds) if conds else None


@router.get("/parts")
async def get_parts(
    brand_id: int | None = Query(None),
    category_id: int | None = Query(None),
    uncategorized: bool = Query(False, description="Brand parts with no category"),
    kits: bool = Query(False, description="Kit package products"),
    attr_key: str | None = Query(None, description="Curated filter key (with attr_value)"),
    attr_value: str | None = Query(None),
    q: str | None = Query(None, description="Filter by sku/name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Parts in a scope — ALL of them (hidden and visible), listed directly from
    the category→product resolver so parts with no filters/attributes still
    appear. Each carries its effective fields + any product-level override."""
    where = await _parts_where(
        db, brand_id=brand_id, category_id=category_id, uncategorized=uncategorized,
        kits=kits, attr_key=attr_key, attr_value=attr_value, q=q,
    )

    count_q = select(func.count()).select_from(Product)
    if where is not None:
        count_q = count_q.where(where)
    total = (await db.execute(count_q)).scalar_one()

    rows_q = select(
        Product.id, Product.sku, Product.name,
        Product.is_hidden, Product.shipping_mode, Product.flat_ship_amount,
    )
    if where is not None:
        rows_q = rows_q.where(where)
    rows_q = rows_q.order_by(Product.sku).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(rows_q)).all()

    pids = [r[0] for r in rows]
    prod_ovs: dict[int, dict[str, dict]] = {}
    if pids:
        for ov in (await db.execute(
            select(CatalogOverride).where(CatalogOverride.product_id.in_(pids))
        )).scalars().all():
            prod_ovs.setdefault(ov.product_id, {})[ov.field] = _override_row(ov)

    parts = [
        {
            "type": "part",
            "product_id": pid, "sku": sku, "label": name,
            "effective": {
                "hidden": bool(is_hidden),
                "shipping_mode": shipping_mode,
                "flat_ship_amount": (f"{flat:.2f}" if flat is not None else None),
            },
            "scope": {"product_id": pid},
            "scope_key": scope_key_for(product_id=pid),
            "overrides": prod_ovs.get(pid, {}),
        }
        for pid, sku, name, is_hidden, shipping_mode, flat in rows
    ]
    return {"parts": parts, "total": total, "page": page, "page_size": page_size}


MAX_BULK = 5000


class BulkBody(BaseModel):
    field: FieldT
    value: str | None = None       # the value to set
    clear: bool = False            # true = remove per-SKU overrides for `field`
    brand_id: int | None = None
    category_id: int | None = None
    uncategorized: bool = False
    kits: bool = False
    attr_key: str | None = None    # curated filter to narrow the selection
    attr_value: str | None = None
    q: str | None = None


@router.post("/bulk-apply")
async def bulk_apply(
    body: BulkBody,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Stamp a PER-SKU override on every part matching a scope (optionally
    narrowed by a curated filter / search). This is how a filter hides "all
    matching parts at once" without persistent overlapping filter rules — the
    result is explicit per-part state you can see and undo on each SKU."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy import delete

    where = await _parts_where(
        db, brand_id=body.brand_id, category_id=body.category_id,
        uncategorized=body.uncategorized, kits=body.kits, attr_key=body.attr_key,
        attr_value=body.attr_value, q=body.q,
    )
    id_q = select(Product.id)
    if where is not None:
        id_q = id_q.where(where)
    pids = (await db.execute(id_q)).scalars().all()
    if not pids:
        return {"applied": 0, "matched": 0}
    if len(pids) > MAX_BULK:
        raise HTTPException(
            400, f"{len(pids)} parts match — over the {MAX_BULK} bulk limit. "
                 "Narrow with a filter or a subcategory first."
        )

    if body.clear:
        res = await db.execute(
            delete(CatalogOverride).where(
                CatalogOverride.product_id.in_(pids), CatalogOverride.field == body.field
            )
        )
        await db.commit()
        return {"applied": res.rowcount or 0, "matched": len(pids), "cleared": True}

    value = _validate_value(body.field, body.value)
    now_email = admin.email or ""
    rows = [{
        "scope_type": "product", "scope_key": scope_key_for(product_id=pid),
        "field": body.field, "value": value, "product_id": pid,
        "updated_by": now_email, "updated_by_id": admin.id,
    } for pid in pids]
    stmt = pg_insert(CatalogOverride).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_catalog_override_scope_field",
        set_={"value": stmt.excluded.value, "updated_by": now_email,
              "updated_by_id": admin.id, "updated_at": func.now()},
    )
    await db.execute(stmt)
    await db.commit()
    return {"applied": len(pids), "matched": len(pids)}


# --------------------------------------------------------------------------- #
# Filters (curated attribute dimension)
# --------------------------------------------------------------------------- #

@router.get("/filters")
async def get_filters(
    brand_id: int = Query(...),
    category_id: int | None = Query(None),
    max_keys: int = Query(12, ge=1, le=40),
    max_values: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Curated filter groups + values for a brand ∩ category scope, admin
    variant: uses the SAME curation as the storefront left rail (manual
    AttributeValueAlias + auto_canonical fold) but drops the visibility gate so
    filters for already-hidden parts still show and stay toggleable."""
    from sqlalchemy import distinct
    from app.models import AttributeValueAlias, ProductAttribute
    from app.services.attribute_canonical import auto_canonical
    try:
        from app.routers.catalog import _ATTR_DENYLIST  # curated deny set
    except Exception:
        _ATTR_DENYLIST = set()

    pred = await _scope_product_ids_subq(db, brand_id=brand_id, category_id=category_id)
    pid_subq = select(Product.id)
    if pred is not None:
        pid_subq = pid_subq.where(pred)

    # Discriminating keys in scope (coverage + not-an-identifier), same guards
    # as category_attributes but scope-bounded and un-gated by visibility.
    key_rows = (await db.execute(
        select(
            ProductAttribute.attribute_key,
            func.count(distinct(ProductAttribute.product_id)).label("np"),
            func.count(distinct(ProductAttribute.attribute_value)).label("nv"),
        )
        .where(ProductAttribute.product_id.in_(pid_subq))
        .where(ProductAttribute.attribute_value.is_not(None))
        .where(ProductAttribute.attribute_value != "")
        .where(~func.lower(ProductAttribute.attribute_key).in_(_ATTR_DENYLIST))
        .where(~ProductAttribute.attribute_key.ilike('% - X_'))
        .group_by(ProductAttribute.attribute_key)
        .having(func.count(distinct(ProductAttribute.product_id)) >= 2)
        .having(func.count(distinct(ProductAttribute.attribute_value)).between(2, 200))
        .order_by(func.count(distinct(ProductAttribute.product_id)).desc())
        .limit(max_keys * 2)
    )).all()
    keys = [k for k, np, nv in key_rows if nv / max(np, 1) <= 0.7][:max_keys]
    if not keys:
        return {"groups": []}

    # Manual canonical aliases for these keys (curator-approved).
    alias_lookup: dict[tuple[str, str], str] = {}
    for k, raw, canon in (await db.execute(
        select(AttributeValueAlias.attribute_key, AttributeValueAlias.raw_value,
               AttributeValueAlias.canonical_value)
        .where(AttributeValueAlias.attribute_key.in_(keys))
        .where(AttributeValueAlias.source == "manual")
    )).all():
        alias_lookup[(k, raw)] = canon

    # Raw (key, value, count) in scope -> fold to canonical, sum per (key, canon).
    val_rows = (await db.execute(
        select(
            ProductAttribute.attribute_key,
            ProductAttribute.attribute_value,
            func.count(distinct(ProductAttribute.product_id)),
        )
        .where(ProductAttribute.product_id.in_(pid_subq))
        .where(ProductAttribute.attribute_key.in_(keys))
        .where(ProductAttribute.attribute_value.is_not(None))
        .where(ProductAttribute.attribute_value != "")
        .group_by(ProductAttribute.attribute_key, ProductAttribute.attribute_value)
    )).all()

    grouped: dict[str, dict[str, int]] = {k: {} for k in keys}
    for k, raw, cnt in val_rows:
        canon = alias_lookup.get((k, raw)) or auto_canonical(raw)
        if not canon:
            continue
        grouped[k][canon] = grouped[k].get(canon, 0) + int(cnt)

    groups = []
    for k in keys:
        vals = sorted(grouped[k].items(), key=lambda kv: -kv[1])[:max_values]
        if len(vals) < 2:
            continue
        groups.append({
            "key": k,
            "values": [{"attr_value": v, "count": c} for v, c in vals],
        })
    return {"groups": groups}


# --------------------------------------------------------------------------- #
# Overrides CRUD
# --------------------------------------------------------------------------- #

class OverrideBody(BaseModel):
    field: FieldT
    value: str | None = None
    brand_id: int | None = None
    category_id: int | None = None
    product_id: int | None = None
    attr_key: str | None = None
    attr_value: str | None = None
    note: str | None = Field(default=None, max_length=2000)


@router.get("/overrides")
async def list_overrides(
    scope_key: str | None = Query(None),
    field: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    stmt = select(CatalogOverride)
    if scope_key:
        stmt = stmt.where(CatalogOverride.scope_key == scope_key)
    if field:
        stmt = stmt.where(CatalogOverride.field == field)
    rows = (await db.execute(stmt.order_by(CatalogOverride.id))).scalars().all()
    return {"overrides": [_override_row(r) for r in rows], "total": len(rows)}


@router.post("/override", status_code=status.HTTP_200_OK)
async def upsert_override(
    body: OverrideBody,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    if not any([body.brand_id, body.category_id, body.product_id, body.attr_key]):
        raise HTTPException(400, "an override needs at least one scope dimension")
    if body.attr_key and body.attr_value is None:
        raise HTTPException(400, "a filter scope needs both attr_key and attr_value")
    value = _validate_value(body.field, body.value)

    scope_key = scope_key_for(
        brand_id=body.brand_id, category_id=body.category_id,
        product_id=body.product_id, attr_key=body.attr_key, attr_value=body.attr_value,
    )
    scope_type = derive_scope_type(
        brand_id=body.brand_id, category_id=body.category_id,
        product_id=body.product_id, attr_key=body.attr_key,
    )
    existing = (await db.execute(
        select(CatalogOverride).where(
            CatalogOverride.scope_key == scope_key, CatalogOverride.field == body.field
        )
    )).scalar_one_or_none()
    if existing is None:
        ov = CatalogOverride(
            scope_type=scope_type, scope_key=scope_key, field=body.field, value=value,
            brand_id=body.brand_id, category_id=body.category_id, product_id=body.product_id,
            attr_key=body.attr_key, attr_value=body.attr_value, note=body.note,
            updated_by=admin.email or "", updated_by_id=admin.id,
        )
        db.add(ov)
    else:
        existing.value = value
        existing.note = body.note
        existing.updated_by = admin.email or ""
        existing.updated_by_id = admin.id
        ov = existing
    await db.commit()
    await db.refresh(ov)
    return {"override": _override_row(ov), "pending": True}


@router.delete("/override/{override_id}")
async def delete_override(
    override_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    ov = (await db.execute(
        select(CatalogOverride).where(CatalogOverride.id == override_id)
    )).scalar_one_or_none()
    if ov is None:
        raise HTTPException(404, "override not found")
    await db.delete(ov)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Pending + Apply now
# --------------------------------------------------------------------------- #

@router.get("/pending")
async def get_pending(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Overrides changed since the last resolve (not yet live on the site)."""
    n = (await db.execute(
        select(func.count()).select_from(CatalogOverride).where(
            or_(CatalogOverride.applied_at.is_(None),
                CatalogOverride.applied_at < CatalogOverride.updated_at)
        )
    )).scalar_one()
    total = (await db.execute(select(func.count()).select_from(CatalogOverride))).scalar_one()
    return {"pending": n, "total_overrides": total}


_apply_lock = asyncio.Lock()


async def _apply_and_reindex() -> None:
    """Resolve overrides, then rebuild the search index so the change is live
    everywhere (DB-backed surfaces reflect it the moment resolve commits)."""
    async with async_session() as db:
        await resolve_effective(db)
    try:
        from app.services.search import reindex_all_products
        async with async_session() as db:
            n = await reindex_all_products(db)
        log.info("apply-now reindexed %d products", n)
    except Exception:
        log.exception("apply-now reindex failed (resolve already committed)")


@router.post("/apply-now")
async def apply_now(
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Resolve overrides now and kick off a background reindex. DB-backed
    surfaces (browse, sitemap, product pages) reflect the change immediately;
    search catches up when the reindex finishes."""
    if _apply_lock.locked():
        return {"status": "already_running"}

    async def _runner():
        async with _apply_lock:
            await _apply_and_reindex()

    asyncio.create_task(_runner())
    return {"status": "started"}
