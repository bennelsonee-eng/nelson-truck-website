"""Deals endpoints.

Public:
    GET /api/deals/home?audience=retail|wholesale&placement=home
        The active deal collection for an audience: countdown (ends_at),
        sidebar highlights, and enriched featured product cards.

Admin (ADMIN or EDITOR):
    GET    /api/admin/deals                       list collections (+ raw items)
    POST   /api/admin/deals                       create collection
    PUT    /api/admin/deals/{cid}                 update collection
    DELETE /api/admin/deals/{cid}                 delete collection
    POST   /api/admin/deals/{cid}/items           add item
    PUT    /api/admin/deal-items/{iid}            update item
    DELETE /api/admin/deal-items/{iid}            delete item
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import require_editor
from app.models import (
    Brand, DealAudience, DealCollection, DealItem, DealItemKind,
    Product, ProductImage, ProductInventory, ProductPrice, User,
)
from app.models.base import utc_now
from app.services.pricing_service import resolve_retail_for_products

router = APIRouter(tags=["deals"])


# ---------------------------------------------------------------------------
# Public schemas
# ---------------------------------------------------------------------------
class DealHighlightOut(BaseModel):
    id: int
    label: str | None
    sublabel: str | None
    icon: str | None
    link_url: str | None


class DealProductOut(BaseModel):
    id: int
    sku: str
    name: str
    brand: str | None
    image_url: str | None
    retail_price: float | None
    in_stock: bool
    stock_total: int
    badge_label: str | None
    badge_tone: str | None
    cta_mode: str


class DealCollectionMeta(BaseModel):
    id: int
    name: str
    ends_at: datetime | None


class DealHomeOut(BaseModel):
    collection: DealCollectionMeta | None
    highlights: list[DealHighlightOut]
    products: list[DealProductOut]


def _aud_match(audience: str) -> list[DealAudience]:
    try:
        aud = DealAudience(audience)
    except ValueError:
        aud = DealAudience.RETAIL
    return [DealAudience.BOTH] if aud is DealAudience.BOTH else [DealAudience.BOTH, aud]


async def _enrich(db: AsyncSession, items: list[DealItem]) -> list[DealProductOut]:
    """Turn product deal-items (sku + badge) into enriched cards, in item order."""
    skus = [it.sku for it in items if it.sku]
    if not skus:
        return []
    products = (await db.execute(select(Product).where(Product.sku.in_(skus)))).scalars().all()
    by_sku = {p.sku: p for p in products}
    pids = [p.id for p in products]

    # Brand names
    brand_ids = {p.brand_id for p in products}
    brands = dict((await db.execute(select(Brand.id, Brand.name).where(Brand.id.in_(brand_ids)))).all()) if brand_ids else {}

    # Primary image per product
    img_rows = (await db.execute(
        select(ProductImage.product_id, ProductImage.url)
        .where(ProductImage.product_id.in_(pids))
        .order_by(ProductImage.product_id, ProductImage.is_primary.desc(), ProductImage.sort_order)
    )).all() if pids else []
    img_by_pid: dict[int, str] = {}
    for pid, url in img_rows:
        img_by_pid.setdefault(pid, url)

    # Inventory totals
    inv_rows = (await db.execute(
        select(ProductInventory.product_id, func.coalesce(func.sum(ProductInventory.on_hand), 0))
        .where(ProductInventory.product_id.in_(pids)).group_by(ProductInventory.product_id)
    )).all() if pids else []
    stock_by_pid = {pid: int(total) for pid, total in inv_rows}

    prices = await resolve_retail_for_products(db, list(products))

    out: list[DealProductOut] = []
    for it in items:
        p = by_sku.get(it.sku or "")
        if p is None:
            continue
        total = stock_by_pid.get(p.id, 0)
        price = prices.get(p.id)
        out.append(DealProductOut(
            id=p.id, sku=p.sku, name=p.name, brand=brands.get(p.brand_id),
            image_url=img_by_pid.get(p.id),
            retail_price=float(price) if price is not None else None,
            in_stock=total > 0, stock_total=total,
            badge_label=it.badge_label, badge_tone=it.badge_tone,
            cta_mode=p.cta_mode.value if hasattr(p.cta_mode, "value") else str(p.cta_mode),
        ))
    return out


@router.get("/api/deals/home", response_model=DealHomeOut)
async def deals_home(
    audience: str = "retail",
    placement: str = "home",
    db: AsyncSession = Depends(get_db),
) -> DealHomeOut:
    now = utc_now()
    coll = (await db.execute(
        select(DealCollection)
        .where(
            DealCollection.is_active.is_(True),
            DealCollection.placement == placement,
            DealCollection.audience.in_(_aud_match(audience)),
            or_(DealCollection.starts_at.is_(None), DealCollection.starts_at <= now),
            or_(DealCollection.ends_at.is_(None), DealCollection.ends_at >= now),
        )
        .order_by(DealCollection.sort_order, DealCollection.id)
        .options(selectinload(DealCollection.items))
    )).scalars().first()

    if coll is None:
        return DealHomeOut(collection=None, highlights=[], products=[])

    aud_ok = set(_aud_match(audience))
    items = [it for it in coll.items if it.is_active and it.audience in aud_ok]
    items.sort(key=lambda it: (it.sort_order, it.id))

    highlights = [
        DealHighlightOut(id=it.id, label=it.label, sublabel=it.sublabel, icon=it.icon, link_url=it.link_url)
        for it in items if it.kind == DealItemKind.HIGHLIGHT
    ]
    products = await _enrich(db, [it for it in items if it.kind == DealItemKind.PRODUCT])
    return DealHomeOut(
        collection=DealCollectionMeta(id=coll.id, name=coll.name, ends_at=coll.ends_at),
        highlights=highlights, products=products,
    )


# ---------------------------------------------------------------------------
# Admin schemas + CRUD
# ---------------------------------------------------------------------------
class DealItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: DealItemKind
    audience: DealAudience
    sort_order: int
    is_active: bool
    sku: str | None
    badge_label: str | None
    badge_tone: str | None
    label: str | None
    sublabel: str | None
    icon: str | None
    link_url: str | None


class DealCollectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    placement: str
    audience: DealAudience
    is_active: bool
    starts_at: datetime | None
    ends_at: datetime | None
    sort_order: int
    items: list[DealItemOut]


class DealCollectionIn(BaseModel):
    name: str
    placement: str = "home"
    audience: DealAudience = DealAudience.BOTH
    is_active: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    sort_order: int = 1000


class DealCollectionUpdate(BaseModel):
    name: str | None = None
    placement: str | None = None
    audience: DealAudience | None = None
    is_active: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    sort_order: int | None = None


class DealItemIn(BaseModel):
    kind: DealItemKind
    audience: DealAudience = DealAudience.BOTH
    sort_order: int = 1000
    is_active: bool = True
    sku: str | None = None
    badge_label: str | None = None
    badge_tone: str | None = None
    label: str | None = None
    sublabel: str | None = None
    icon: str | None = None
    link_url: str | None = None


class DealItemUpdate(DealItemIn):
    kind: DealItemKind | None = None  # all optional for PATCH-style update
    audience: DealAudience | None = None


@router.get("/api/admin/deals", response_model=list[DealCollectionOut])
async def admin_list_deals(db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    rows = (await db.execute(
        select(DealCollection).order_by(DealCollection.sort_order, DealCollection.id)
        .options(selectinload(DealCollection.items))
    )).scalars().all()
    return list(rows)


@router.post("/api/admin/deals", response_model=DealCollectionOut, status_code=201)
async def admin_create_deal(payload: DealCollectionIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    coll = DealCollection(**payload.model_dump())
    db.add(coll)
    await db.commit()
    coll = (await db.execute(
        select(DealCollection).where(DealCollection.id == coll.id).options(selectinload(DealCollection.items))
    )).scalar_one()
    return coll


@router.put("/api/admin/deals/{cid}", response_model=DealCollectionOut)
async def admin_update_deal(cid: int, payload: DealCollectionUpdate, db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    coll = (await db.execute(
        select(DealCollection).where(DealCollection.id == cid).options(selectinload(DealCollection.items))
    )).scalar_one_or_none()
    if coll is None:
        raise HTTPException(404, "Collection not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(coll, k, v)
    await db.commit()
    await db.refresh(coll)
    return coll


@router.delete("/api/admin/deals/{cid}")
async def admin_delete_deal(cid: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    coll = await db.get(DealCollection, cid)
    if coll is None:
        raise HTTPException(404, "Collection not found")
    await db.delete(coll)
    await db.commit()
    return {"deleted": cid}


@router.post("/api/admin/deals/{cid}/items", response_model=DealItemOut, status_code=201)
async def admin_add_item(cid: int, payload: DealItemIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    if await db.get(DealCollection, cid) is None:
        raise HTTPException(404, "Collection not found")
    item = DealItem(collection_id=cid, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.put("/api/admin/deal-items/{iid}", response_model=DealItemOut)
async def admin_update_item(iid: int, payload: DealItemUpdate, db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    item = await db.get(DealItem, iid)
    if item is None:
        raise HTTPException(404, "Item not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/api/admin/deal-items/{iid}")
async def admin_delete_item(iid: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    item = await db.get(DealItem, iid)
    if item is None:
        raise HTTPException(404, "Item not found")
    await db.delete(item)
    await db.commit()
    return {"deleted": iid}
