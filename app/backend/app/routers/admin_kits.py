"""Admin kit router — create/manage package kits (e.g. WeatherGuard van packages).

A kit is a sellable package product with a bill-of-materials (component part
numbers + quantities), vehicle fitment, resources, and a website category
placement. Backs the "Create a kit package" guided-wizard admin page.

All endpoints require ADMIN role. Mounted at /api/admin/kits.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import require_admin
from app.models import (
    Brand,
    Category,
    Kit,
    KitComponent,
    Product,
    ProductCategory,
    ProductImage,
    ProductPrice,
    ProductResource,
    ResourceKind,
    User,
)
from app.services.kit_inventory import recompute_all_kits, recompute_kit_stock
from app.services.search import index_products

# Kit pricing tiers -> product_price columns. "wholesale" is the jobber tier.
PRICE_TIERS = {
    "retail": "retail_price",
    "wholesale": "jobber_price",
    "dealer": "dealer_price",
    "municipality": "municipality_price",
}


def _to_decimal(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None

router = APIRouter(prefix="/api/admin/kits", tags=["admin", "kits"])


# ---- Schemas ---------------------------------------------------------------

class ComponentIn(BaseModel):
    part_number: str
    product_id: int | None = None
    quantity: int = 1
    description: str | None = None


class ResourceIn(BaseModel):
    title: str | None = None
    url: str
    kind: str = "installation"


class ImageIn(BaseModel):
    url: str
    is_primary: bool = False


class KitPrices(BaseModel):
    """Per-tier kit prices (None = leave the existing product_price column as-is)."""
    retail: float | None = None
    wholesale: float | None = None
    dealer: float | None = None
    municipality: float | None = None


class KitIn(BaseModel):
    sku: str
    name: str
    kit_type: str = "van_package"
    trade: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    wheelbase: str | None = None
    roof_height: str | None = None
    hand: str | None = None
    description: str | None = None
    is_active: bool = True
    product_id: int | None = None
    category_id: int | None = None  # website placement for the package product
    components: list[ComponentIn] = Field(default_factory=list)
    # Optional: when present, replace the package product's resources / images.
    resources: list[ResourceIn] | None = None
    images: list[ImageIn] | None = None
    # Pricing + channel availability. prices=None leaves pricing untouched.
    prices: KitPrices | None = None
    avail_retail: bool = True
    avail_wholesale: bool = True
    avail_dealer: bool = True
    avail_municipality: bool = True
    # Availability window (inclusive dates; null = open-ended).
    available_from: date | None = None
    available_until: date | None = None


class ComponentOut(BaseModel):
    id: int
    part_number: str
    product_id: int | None
    product_sku: str | None
    product_name: str | None
    quantity: int
    description: str | None
    sort_order: int


class KitOut(BaseModel):
    id: int
    sku: str
    name: str
    kit_type: str
    trade: str | None
    vehicle_make: str | None
    vehicle_model: str | None
    wheelbase: str | None
    roof_height: str | None
    hand: str | None
    description: str | None
    is_active: bool
    source: str | None
    product_id: int | None
    category_id: int | None
    category_full_path: str | None
    components: list[ComponentOut]
    resources: list[ResourceIn] = Field(default_factory=list)
    images: list[ImageIn] = Field(default_factory=list)
    prices: KitPrices = Field(default_factory=KitPrices)
    price_is_manual: bool = False
    avail_retail: bool = True
    avail_wholesale: bool = True
    avail_dealer: bool = True
    avail_municipality: bool = True
    available_from: date | None = None
    available_until: date | None = None
    # Derived from component inventory (materialized onto the package product).
    derived_on_hand: int = 0
    stock_by_warehouse: list[dict] = Field(default_factory=list)
    limiting_part: str | None = None
    unlinked_components: int = 0


class KitSummary(BaseModel):
    id: int
    sku: str
    name: str
    trade: str | None
    vehicle_make: str | None
    vehicle_model: str | None
    wheelbase: str | None
    component_count: int
    is_active: bool
    # Whether the package is actually showing on the storefront right now, and
    # if not, every reason it's hidden.
    showing: bool = True
    hidden_reasons: list[str] = Field(default_factory=list)


def _kit_hidden_reasons(kit: Kit, product_hidden: bool, product_for_sale: bool,
                        today: date) -> list[str]:
    """Every reason a kit isn't showing on the website right now (empty = live)."""
    reasons: list[str] = []
    if not kit.product_id:
        reasons.append("Not linked to a product")
    if not kit.is_active:
        reasons.append("Inactive (turned off in admin)")
    if kit.available_from and today < kit.available_from:
        reasons.append(f"Scheduled — opens {kit.available_from.isoformat()}")
    if kit.available_until and today > kit.available_until:
        reasons.append(f"Expired — ended {kit.available_until.isoformat()}")
    if not (kit.avail_retail or kit.avail_wholesale or kit.avail_dealer or kit.avail_municipality):
        reasons.append("No customer channels enabled")
    if kit.product_id and product_hidden:
        reasons.append("Product is hidden")
    if kit.product_id and not product_for_sale:
        reasons.append("Product is not for sale")
    return reasons


# ---- Helpers ---------------------------------------------------------------

async def _resolve_components(db: AsyncSession, comps: list[KitComponent]) -> list[ComponentOut]:
    pids = [c.product_id for c in comps if c.product_id]
    prod = {}
    if pids:
        rows = (await db.execute(
            select(Product.id, Product.sku, Product.name).where(Product.id.in_(pids))
        )).all()
        prod = {r.id: (r.sku, r.name) for r in rows}
    out = []
    for c in sorted(comps, key=lambda x: x.sort_order):
        sku, name = prod.get(c.product_id, (None, None))
        out.append(ComponentOut(
            id=c.id, part_number=c.part_number, product_id=c.product_id,
            product_sku=sku, product_name=name, quantity=c.quantity,
            description=c.description, sort_order=c.sort_order,
        ))
    return out


async def _primary_category(db: AsyncSession, product_id: int | None) -> tuple[int | None, str | None]:
    if not product_id:
        return None, None
    row = (await db.execute(
        select(Category.id, Category.full_path)
        .join(ProductCategory, ProductCategory.category_id == Category.id)
        .where(ProductCategory.product_id == product_id, ProductCategory.is_primary.is_(True))
        .limit(1)
    )).first()
    return (row.id, row.full_path) if row else (None, None)


async def _kit_out(db: AsyncSession, kit: Kit) -> KitOut:
    cat_id, cat_path = await _primary_category(db, kit.product_id)
    resources: list[ResourceIn] = []
    images: list[ImageIn] = []
    if kit.product_id:
        rrows = (await db.execute(
            select(ProductResource.title, ProductResource.url, ProductResource.kind)
            .where(ProductResource.product_id == kit.product_id)
            .order_by(ProductResource.sort_order)
        )).all()
        resources = [ResourceIn(title=r.title, url=r.url,
                                kind=(r.kind.value if hasattr(r.kind, "value") else str(r.kind)))
                     for r in rrows]
        irows = (await db.execute(
            select(ProductImage.url, ProductImage.is_primary)
            .where(ProductImage.product_id == kit.product_id)
            .order_by(ProductImage.sort_order)
        )).all()
        images = [ImageIn(url=i.url, is_primary=i.is_primary) for i in irows]
    prices = await _load_prices(db, kit.product_id)
    stock = await recompute_kit_stock(db, kit, materialize=False)
    return KitOut(
        id=kit.id, sku=kit.sku, name=kit.name, kit_type=kit.kit_type, trade=kit.trade,
        vehicle_make=kit.vehicle_make, vehicle_model=kit.vehicle_model, wheelbase=kit.wheelbase,
        roof_height=kit.roof_height, hand=kit.hand, description=kit.description,
        is_active=kit.is_active, source=kit.source, product_id=kit.product_id,
        category_id=cat_id, category_full_path=cat_path,
        components=await _resolve_components(db, kit.components),
        resources=resources, images=images,
        prices=prices, price_is_manual=kit.price_is_manual,
        avail_retail=kit.avail_retail, avail_wholesale=kit.avail_wholesale,
        avail_dealer=kit.avail_dealer, avail_municipality=kit.avail_municipality,
        available_from=kit.available_from, available_until=kit.available_until,
        derived_on_hand=stock["total_on_hand"], stock_by_warehouse=stock["by_warehouse"],
        limiting_part=stock["limiting_part"], unlinked_components=stock["unlinked"],
    )


def _resource_kind(value: str | None) -> ResourceKind:
    try:
        return ResourceKind(value) if value else ResourceKind.INSTALLATION
    except ValueError:
        return ResourceKind.OTHER


async def _set_resources_images(
    db: AsyncSession, product_id: int | None,
    resources: list["ResourceIn"] | None, images: list["ImageIn"] | None,
) -> None:
    """Replace the package product's resources / images with the provided sets.
    `None` means 'leave untouched'; an empty list means 'clear'."""
    if not product_id:
        return
    if resources is not None:
        await db.execute(
            ProductResource.__table__.delete().where(ProductResource.product_id == product_id)
        )
        for i, r in enumerate(resources):
            if not r.url:
                continue
            db.add(ProductResource(
                product_id=product_id, kind=_resource_kind(r.kind), url=r.url,
                title=r.title, sort_order=i, source="manual",
            ))
    if images is not None:
        await db.execute(
            ProductImage.__table__.delete().where(ProductImage.product_id == product_id)
        )
        any_primary = any(im.is_primary for im in images)
        for i, im in enumerate(images):
            if not im.url:
                continue
            db.add(ProductImage(
                product_id=product_id, url=im.url,
                is_primary=(im.is_primary or (not any_primary and i == 0)),
                sort_order=i,
            ))


async def _place_in_category(db: AsyncSession, product_id: int | None, category_id: int | None) -> None:
    """Set the package product's primary website category to category_id."""
    if not product_id or not category_id:
        return
    # demote existing primaries, add/keep the chosen one as primary
    existing = (await db.execute(
        select(ProductCategory).where(ProductCategory.product_id == product_id)
    )).scalars().all()
    has_target = False
    for pc in existing:
        if pc.category_id == category_id:
            pc.is_primary = True; has_target = True
        else:
            pc.is_primary = False
    if not has_target:
        db.add(ProductCategory(product_id=product_id, category_id=category_id, is_primary=True))


async def _load_prices(db: AsyncSession, product_id: int | None) -> KitPrices:
    if not product_id:
        return KitPrices()
    pp = (await db.execute(
        select(ProductPrice).where(ProductPrice.product_id == product_id)
    )).scalar_one_or_none()
    if not pp:
        return KitPrices()
    return KitPrices(
        retail=float(pp.retail_price) if pp.retail_price is not None else None,
        wholesale=float(pp.jobber_price) if pp.jobber_price is not None else None,
        dealer=float(pp.dealer_price) if pp.dealer_price is not None else None,
        municipality=float(pp.municipality_price) if pp.municipality_price is not None else None,
    )


async def _set_prices(db: AsyncSession, product_id: int | None, prices: KitPrices | None) -> bool:
    """Upsert the package product's product_price from the kit's tier prices.
    Only writes columns whose value is provided (non-None). Returns True if any
    price was set (so the kit can be flagged price_is_manual)."""
    if not product_id or prices is None:
        return False
    pp = (await db.execute(
        select(ProductPrice).where(ProductPrice.product_id == product_id)
    )).scalar_one_or_none()
    if pp is None:
        pp = ProductPrice(product_id=product_id)
        db.add(pp)
    wrote = False
    for tier, col in PRICE_TIERS.items():
        v = getattr(prices, tier, None)
        if v is not None:
            setattr(pp, col, _to_decimal(v))
            wrote = True
    return wrote


# ---- Endpoints -------------------------------------------------------------

@router.get("", response_model=list[KitSummary])
async def list_kits(
    q: str = "", limit: int = 200,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> list[KitSummary]:
    cnt = (
        select(KitComponent.kit_id, func.count().label("n"))
        .group_by(KitComponent.kit_id).subquery()
    )
    stmt = (
        select(Kit, func.coalesce(cnt.c.n, 0))
        .outerjoin(cnt, cnt.c.kit_id == Kit.id)
        .order_by(Kit.name).limit(min(max(limit, 1), 500))
    )
    if q.strip():
        p = f"%{q.strip()}%"
        stmt = stmt.where(or_(Kit.sku.ilike(p), Kit.name.ilike(p), Kit.trade.ilike(p)))
    rows = (await db.execute(stmt)).all()
    pids = [k.product_id for k, _ in rows if k.product_id]
    prod_vis: dict[int, tuple[bool, bool]] = {}
    if pids:
        for pid, hidden, for_sale in (await db.execute(
            select(Product.id, Product.is_hidden, Product.is_for_sale).where(Product.id.in_(pids))
        )).all():
            prod_vis[pid] = (bool(hidden), bool(for_sale))
    today = date.today()
    out: list[KitSummary] = []
    for k, n in rows:
        ph, pfs = prod_vis.get(k.product_id, (False, True))
        reasons = _kit_hidden_reasons(k, ph, pfs, today)
        out.append(KitSummary(
            id=k.id, sku=k.sku, name=k.name, trade=k.trade, vehicle_make=k.vehicle_make,
            vehicle_model=k.vehicle_model, wheelbase=k.wheelbase, component_count=n,
            is_active=k.is_active, showing=not reasons, hidden_reasons=reasons,
        ))
    return out


@router.get("/component-search")
async def component_search(
    q: str, limit: int = 15,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Find products to add as BOM components (by sku or name)."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    p = f"%{q}%"
    rows = (await db.execute(
        select(Product.id, Product.sku, Product.name, Brand.name.label("brand"))
        .join(Brand, Brand.id == Product.brand_id)
        .where(Product.is_hidden.is_(False), or_(Product.sku.ilike(p), Product.name.ilike(p)))
        .order_by(Product.sku).limit(min(max(limit, 1), 30))
    )).all()
    return [{"id": r.id, "sku": r.sku, "name": r.name, "brand": r.brand} for r in rows]


@router.get("/resolve-part/{part_number}")
async def resolve_part(
    part_number: str,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    """Resolve a WeatherGuard part number to a product (sku = HWZD-<part>)."""
    pn = part_number.strip()
    candidates = [pn, f"HWZD-{pn}"] if not pn.upper().startswith("HWZD-") else [pn]
    row = (await db.execute(
        select(Product.id, Product.sku, Product.name).where(Product.sku.in_(candidates)).limit(1)
    )).first()
    return {"found": bool(row), "product_id": row.id if row else None,
            "sku": row.sku if row else None, "name": row.name if row else None}


@router.post("/recompute-stock")
async def recompute_stock_all(
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-derive every kit's stock from its components and materialize it onto
    the package products. Run after an inventory sync."""
    return await recompute_all_kits(db)


@router.get("/fitment-check")
async def fitment_check(
    product_ids: list[int] = Query(default=[]),
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    """Vehicle-fitment reconciliation for a kit's components.

    Pulls each component's YMM fitment (pace_part → pace_fitment → vcdb), then:
      * surfaces each component's makes/models so the admin can verify;
      * computes the fitment the parts SHARE (so the kit's make/model can be
        auto-filled);
      * flags a conflict when two or more fitment-bearing components share NO
        common make — i.e. a Ford part packaged with a Ram part.
    Universal components (no fitment rows — generic mounts/hardware) fit
    everything and never trigger a conflict.
    """
    if not product_ids:
        return {"components": [], "common": {}, "conflict": False, "warnings": []}

    rows = (await db.execute(text("""
        SELECT pp.product_id AS pid, m.name AS make, mo.name AS model, bv.year AS yr
        FROM pace_part pp
        JOIN pace_fitment f ON f.pace_part_id = pp.id
        JOIN vcdb_base_vehicle bv ON bv.id = f.base_vehicle_id
        JOIN vcdb_make m ON m.id = bv.make_id
        JOIN vcdb_model mo ON mo.id = bv.model_id
        WHERE pp.product_id = ANY(:pids) AND m.name <> 'UNKNOWN'
    """), {"pids": product_ids})).all()

    per: dict[int, dict] = defaultdict(lambda: {"makes": set(), "pairs": set(), "years": set()})
    for r in rows:
        d = per[r.pid]
        d["makes"].add(r.make)
        d["pairs"].add((r.make, r.model))
        if r.yr:
            d["years"].add(int(r.yr))

    info = {p.id: (p.sku, p.name) for p in (await db.execute(
        select(Product.id, Product.sku, Product.name).where(Product.id.in_(product_ids))
    )).all()}

    components: list[dict] = []
    bearing: list[tuple[int, set, set]] = []  # (pid, makes, pairs) for non-universal
    seen: set[int] = set()
    for pid in product_ids:
        if pid in seen:
            continue
        seen.add(pid)
        sku, name = info.get(pid, (None, None))
        d = per.get(pid)
        if not d or not d["makes"]:
            components.append({"product_id": pid, "sku": sku, "name": name,
                               "universal": True, "makes": [], "models": [], "vehicle_count": 0})
        else:
            components.append({"product_id": pid, "sku": sku, "name": name, "universal": False,
                               "makes": sorted(d["makes"]),
                               "models": [f"{mk} {mo}" for mk, mo in sorted(d["pairs"])][:12],
                               "vehicle_count": len(d["pairs"])})
            bearing.append((pid, d["makes"], d["pairs"]))

    common_makes: set | None = None
    common_pairs: set | None = None
    years: set = set()
    for pid, makes, pairs in bearing:
        common_makes = makes if common_makes is None else (common_makes & makes)
        common_pairs = pairs if common_pairs is None else (common_pairs & pairs)
        years |= per[pid]["years"]
    common_makes = common_makes or set()
    common_pairs = common_pairs or set()

    conflict = len(bearing) >= 2 and not common_makes
    warnings: list[str] = []
    if conflict:
        detail = "; ".join(f"{info.get(pid, ('?',))[0]} → {', '.join(sorted(mk))}"
                           for pid, mk, _ in bearing if mk)
        warnings.append("These components don't share a vehicle make — a package should be "
                        f"parts for the same vehicle. Mismatch: {detail}")
    elif len(bearing) >= 2 and not common_pairs and common_makes:
        # Same make(s) but no exact shared model — softer heads-up.
        warnings.append("Components share a make but no single common model — double-check "
                        "the fitment overlap before saving.")

    common = {
        "makes": sorted(common_makes),
        "models": [f"{mk} {mo}" for mk, mo in sorted(common_pairs)][:20],
        "vehicle_count": len(common_pairs),
        "year_start": min(years) if years else None,
        "year_end": max(years) if years else None,
        # Single best make/model to auto-fill the kit fitment fields.
        "suggest_make": sorted(common_makes)[0] if len(common_makes) == 1 else None,
        "suggest_model": (sorted(common_pairs)[0][1]
                          if len({mo for _, mo in common_pairs}) == 1 and common_pairs else None),
    }
    return {"components": components, "common": common,
            "conflict": conflict, "warnings": warnings,
            "fitment_bearing": len(bearing), "universal": len(components) - len(bearing)}


@router.get("/{kit_id}/suggest-pricing")
async def suggest_pricing(
    kit_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    """Suggest each tier price by summing the component prices at that tier.
    Flags components that can't be fully priced (unlinked, or no price on file)."""
    kit = (await db.execute(
        select(Kit).options(selectinload(Kit.components)).where(Kit.id == kit_id)
    )).scalar_one_or_none()
    if not kit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kit not found")
    pids = [c.product_id for c in kit.components if c.product_id]
    pp_by_pid: dict[int, ProductPrice] = {}
    if pids:
        for pp in (await db.execute(
            select(ProductPrice).where(ProductPrice.product_id.in_(pids))
        )).scalars():
            pp_by_pid[pp.product_id] = pp
    totals = {t: Decimal("0") for t in PRICE_TIERS}
    missing: list[dict] = []
    for c in kit.components:
        pp = pp_by_pid.get(c.product_id) if c.product_id else None
        for tier, col in PRICE_TIERS.items():
            v = getattr(pp, col, None) if pp else None
            if v is not None:
                totals[tier] += Decimal(v) * (c.quantity or 1)
        # "Missing" = can't be priced at all (unlinked, or no retail price on
        # file). A tier that's simply absent (e.g. municipality) lowers that
        # tier's suggestion but doesn't flag the part.
        if not pp or pp.retail_price is None:
            missing.append({"part_number": c.part_number, "quantity": c.quantity,
                            "linked": bool(c.product_id)})
    return {
        "suggested": {t: round(float(totals[t]), 2) for t in PRICE_TIERS},
        "missing_count": len(missing),
        "missing_parts": missing[:50],
    }


@router.get("/{kit_id}", response_model=KitOut)
async def get_kit(
    kit_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> KitOut:
    kit = (await db.execute(
        select(Kit).options(selectinload(Kit.components)).where(Kit.id == kit_id)
    )).scalar_one_or_none()
    if not kit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kit not found")
    return await _kit_out(db, kit)


@router.post("", response_model=KitOut, status_code=status.HTTP_201_CREATED)
async def create_kit(
    body: KitIn, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> KitOut:
    if (await db.execute(select(Kit.id).where(Kit.sku == body.sku))).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A kit with this SKU already exists")
    kit = Kit(
        sku=body.sku, name=body.name, kit_type=body.kit_type, trade=body.trade,
        vehicle_make=body.vehicle_make, vehicle_model=body.vehicle_model, wheelbase=body.wheelbase,
        roof_height=body.roof_height, hand=body.hand, description=body.description,
        is_active=body.is_active, product_id=body.product_id, source="manual",
        avail_retail=body.avail_retail, avail_wholesale=body.avail_wholesale,
        avail_dealer=body.avail_dealer, avail_municipality=body.avail_municipality,
        available_from=body.available_from, available_until=body.available_until,
    )
    for i, c in enumerate(body.components):
        kit.components.append(KitComponent(
            part_number=c.part_number, product_id=c.product_id, quantity=c.quantity,
            description=c.description, sort_order=i,
        ))
    db.add(kit)
    await _place_in_category(db, body.product_id, body.category_id)
    await _set_resources_images(db, body.product_id, body.resources, body.images)
    if await _set_prices(db, body.product_id, body.prices):
        kit.price_is_manual = True
    await recompute_kit_stock(db, kit)
    await db.commit()
    await db.refresh(kit, ["components"])
    if kit.product_id:
        await index_products(db, [kit.product_id])
    return await _kit_out(db, kit)


@router.put("/{kit_id}", response_model=KitOut)
async def update_kit(
    kit_id: int, body: KitIn,
    user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> KitOut:
    kit = (await db.execute(
        select(Kit).options(selectinload(Kit.components)).where(Kit.id == kit_id)
    )).scalar_one_or_none()
    if not kit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kit not found")
    for f in ("sku", "name", "kit_type", "trade", "vehicle_make", "vehicle_model",
              "wheelbase", "roof_height", "hand", "description", "is_active", "product_id",
              "avail_retail", "avail_wholesale", "avail_dealer", "avail_municipality",
              "available_from", "available_until"):
        setattr(kit, f, getattr(body, f))
    kit.components.clear()
    for i, c in enumerate(body.components):
        kit.components.append(KitComponent(
            part_number=c.part_number, product_id=c.product_id, quantity=c.quantity,
            description=c.description, sort_order=i,
        ))
    await _place_in_category(db, body.product_id, body.category_id)
    await _set_resources_images(db, body.product_id, body.resources, body.images)
    if await _set_prices(db, body.product_id, body.prices):
        kit.price_is_manual = True
    # recompute needs the rebuilt components; they're attached to the session.
    await db.flush()
    await recompute_kit_stock(db, kit)
    await db.commit()
    await db.refresh(kit, ["components"])
    if kit.product_id:
        await index_products(db, [kit.product_id])
    return await _kit_out(db, kit)


@router.delete("/{kit_id}")
async def delete_kit(
    kit_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    kit = (await db.execute(select(Kit).where(Kit.id == kit_id))).scalar_one_or_none()
    if not kit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kit not found")
    await db.delete(kit)
    await db.commit()
    return {"deleted": kit_id}
