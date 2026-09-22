"""Catalog API — browse, search, product detail.

Read-only endpoints serving anonymous retail (Phase 1).
B2B-tier pricing comes once auth is wired in Week 2.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, resolve_effective_customer_id
from app.models import (
    Brand,
    Customer,
    Kit,
    Product,
    ProductAttribute,
    ProductDescription,
    ProductImage,
    ProductInventory,
    ProductPrice,
    ProductResource,
    ProductSpecTable,
    User,
    Warehouse,
)
from app.services.pricing_service import (
    TierPricingDisplay,
    anonymous_retail_display,
    build_tier_display,
    build_tier_display_batch,
)
from app.services.channels import (
    ALL_CHANNELS,
    hidden_col_name,
    product_hidden_for,
    visible_to_channel_clause,
)
from app.services.channels import tier_to_channel as _tier_to_channel
from app.services.channels import viewer_channel as _viewer_channel
from app.services.search import search_products


log = logging.getLogger(__name__)


router = APIRouter(prefix="/api/catalog", tags=["catalog"])

# Nelson's staffed retail counters — the only places a customer can actually
# "pick it up today." Portland = warehouse code 1, Kent = code 2. Spokane
# (code 10) is the parent group's HQ warehouse, NOT a Nelson pickup branch, so
# its on-hand must never feed the homepage "in stock & ready today" promise.
PICKUP_WAREHOUSE_CODES = (1, 2)


def _format_money(d: Decimal | None) -> str | None:
    if d is None:
        return None
    return str(d.quantize(Decimal("0.01")))


def _serialize_product_card(hit: dict[str, Any]) -> dict[str, Any]:
    """Convert a Typesense search hit into a product card dict for the UI."""
    doc = hit["document"]
    # photocomingsoon.jpg URLs from aam-files are explicit "no image yet"
    # placeholders; drop them to None so the frontend's no-image fallback
    # renders the "No image" tile instead of the placeholder graphic.
    image_url = doc.get("image_url") or None
    if image_url and "photocomingsoon" in image_url.lower():
        image_url = None
    return {
        "id": int(doc["id"]),
        "sku": doc["sku"],
        "name": doc["name"],
        "brand": doc.get("brand_name"),
        "in_stock": doc.get("in_stock", False),
        "stock_total": doc.get("stock_total", 0),
        "cta_mode": doc.get("cta_mode", "add_to_cart"),
        "shipping_mode": doc.get("shipping_mode") or "ship",
        "freight_class": doc.get("freight_class") or None,
        "image_url": image_url,
        "category_top": doc.get("category_top") or None,
        "description": doc.get("description") or None,
        "series": doc.get("series") or None,
    }


@router.get("/featured-pickup")
async def featured_pickup(
    request: Request,
    limit: int = Query(12, ge=1, le=48),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    """Homepage "In stock & ready today" grid.

    Returns only products with positive on-hand at a Nelson pickup counter
    (Portland / Kent — see ``PICKUP_WAREHOUSE_CODES``). Spokane-only stock is
    deliberately excluded so the "pick it up today" promise on the card is
    honest — an item sitting in Spokane can't be grabbed off the shelf in
    Portland or Kent today.

    Distinct from ``/browse`` (which counts on-hand across *every* warehouse
    and is served from the company-wide Typesense index).
    """
    # Per-product on-hand summed over the pickup branches only. HAVING > 0
    # drops products whose only stock is at a non-pickup warehouse.
    pickup_stock_sq = (
        select(
            ProductInventory.product_id.label("pid"),
            func.sum(ProductInventory.on_hand).label("qty"),
        )
        .join(Warehouse, Warehouse.id == ProductInventory.warehouse_id)
        .where(
            Warehouse.code.in_(PICKUP_WAREHOUSE_CODES),
            ProductInventory.on_hand > 0,
        )
        .group_by(ProductInventory.product_id)
        .having(func.sum(ProductInventory.on_hand) > 0)
        .subquery()
    )

    # A real product photo (not a "photo coming soon" placeholder) makes a far
    # better showcase card, so rank image-having products first.
    has_image = (
        select(ProductImage.id)
        .where(
            ProductImage.product_id == Product.id,
            ProductImage.url.isnot(None),
            ~ProductImage.url.ilike("%photocomingsoon%"),
        )
        .exists()
        .label("has_image")
    )

    # Per-customer-channel visibility (parity with /browse + hot-products): a
    # product hidden from this viewer's channel drops off the pickup showcase.
    channel = await _viewer_channel(db, user, request)
    rows = (await db.execute(
        select(Product, pickup_stock_sq.c.qty, has_image)
        .options(selectinload(Product.brand), selectinload(Product.images))
        .join(Brand, Brand.id == Product.brand_id)
        .join(pickup_stock_sq, pickup_stock_sq.c.pid == Product.id)
        .where(
            visible_to_channel_clause(channel),
            Product.is_for_sale == True,  # noqa: E712
            Brand.is_active == True,  # noqa: E712
        )
        .order_by(has_image.desc(), pickup_stock_sq.c.qty.desc(), Product.name.asc())
        .limit(limit)
    )).all()

    def _usable(url: str | None) -> bool:
        return bool(url) and "photocomingsoon" not in url.lower()

    hits = []
    for product, pickup_qty, _has_image in rows:
        imgs = [i for i in product.images if _usable(i.url)]
        primary = (
            next((i.url for i in imgs if i.is_primary), None)
            or (imgs[0].url if imgs else None)
            or (product.brand.logo_url if (product.brand and product.brand.logo_url) else None)
        )
        hits.append({
            "id": product.id,
            "sku": product.sku,
            "name": product.name,
            "brand": product.brand.name if product.brand else None,
            "image_url": primary,
            "in_stock": True,
            "pickup_stock": int(pickup_qty or 0),
        })

    return {"hits": hits}


@router.get("/browse")
async def browse(
    request: Request,
    q: str | None = Query(None, description="Search query"),
    brand: list[str] = Query([], description="Repeatable brand filter (multiple = OR within Brand)"),
    category_top: str | None = Query(None, description="Filter to top-level category"),
    category_path: str | None = Query(None, description="Filter to exact full category path"),
    in_stock: bool = Query(False, description="Only show in-stock items"),
    cta_mode: str | None = Query(None, description="Filter by CTA mode"),
    base_vehicle_id: int | None = Query(None, description="If set, restrict to parts that fit this vehicle (PACE fitment)"),
    vehicle_type: str | None = Query(None, description="Restrict to a class of vehicles (e.g. 'Van') — products with at least one fitment to that class, or no fitments at all (universal)"),
    attrs: list[str] = Query([], description="Repeatable PIES-attribute filters, encoded as 'Key|Value' (e.g. 'Material|Steel'). Multiple = AND across keys, OR within the same key."),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    sort: str | None = Query(None, description="Override sort_by"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
):
    """Faceted catalog browse.

    Two execution paths:
      - **Default (Typesense)**: full-text + facet search via Typesense.
      - **Fitment-filtered (PACE-backed)**: when `base_vehicle_id` is set OR
        Typesense is unreachable, queries directly from Postgres via
        pace_search. Slightly slower, but supports YMM-fitment filtering
        which Typesense doesn't have indexed.
    """
    # Anonymous browse is identical for every viewer — retail prices come from
    # the sentinel price book, not a per-customer contract — so serve it from a
    # short-TTL process cache to collapse repeat loads of popular categories.
    # Logged-in browse carries per-customer tier pricing and is NEVER cached
    # here. Key off the RAW params so a cache hit skips brand canonicalization
    # (a per-brand DB lookup) entirely.
    from app.services.browse_cache import browse_cache
    cache_key = None
    if user is None:
        cache_key = (
            "browse", q, tuple(sorted(brand or [])), category_top, category_path,
            in_stock, cta_mode, base_vehicle_id, vehicle_type,
            tuple(sorted(attrs or [])), page, per_page, sort,
        )
        cached = browse_cache.get(cache_key)
        if cached is not None:
            return cached

    # Normalize each brand to its canonical display name. Callers historically
    # pass display name ("Warn") but shared links / autocomplete also pass
    # slug ("warn"). Multi-brand: each entry is resolved independently.
    canonical_brands: list[str] = []
    for raw in (brand or []):
        if not raw:
            continue
        bn = (await db.execute(
            select(Brand.name)
            .where(or_(func.lower(Brand.name) == raw.lower(),
                       Brand.slug == raw.lower()))
            .limit(1)
        )).scalar_one_or_none()
        if bn:
            canonical_brands.append(bn)
    # First brand wins for the Typesense path (which only takes one). The
    # PACE path takes the full list so multi-brand filtering works there.
    first_brand = canonical_brands[0] if canonical_brands else None
    is_multi_brand = len(canonical_brands) > 1

    # Vehicle-in-search-text (error report #21): when the shopper types a
    # Year/Make/Model into the free-text box ("2026 ford f-150 tonneau cover")
    # and hasn't already picked a vehicle, parse the truck out, resolve it to a
    # base_vehicle_id, and strip those words so only the product term
    # ("tonneau cover") stays as the query. Results then filter to parts that
    # fit that truck (or are universal) instead of ranking Ram/Silverado covers
    # alongside the Ford ones. Skipped when a vehicle filter is already set.
    #
    # Note we DON'T set `base_vehicle_id` (that routes to the DB browse path,
    # whose keyword filter only ILIKEs name/sku/brand and would miss covers
    # whose fitment lives in the description/category). Instead we keep the
    # Typesense relevance path and pass the vehicle as `fit_bvid`, the new
    # indexed-fitment filter.
    resolved_vehicle: dict[str, Any] | None = None
    fit_bvid: int | None = None
    if q and base_vehicle_id is None and not vehicle_type:
        from app.services.ymm_parse import parse_vehicle_from_query
        parsed = await parse_vehicle_from_query(db, q)
        if parsed:
            resolved_vehicle = {
                "base_vehicle_id": parsed["base_vehicle_id"],
                "label": parsed["label"],
            }
            fit_bvid = parsed["base_vehicle_id"]
            q = parsed["residual_q"] or None

    # Path A: fitment-filtered → query DB direct (Typesense doesn't index fitment)
    # Path A also: any category-filtered query when not full-text searching, since
    # the DB path is already fast for that and avoids Typesense altogether.
    # Path A also: any attr-filtered query — Typesense doesn't index PIES
    # product_attribute rows; the attribute drill-down only renders on
    # category pages, which already route through pace.
    # Path A also: multi-brand — Typesense filter is single-valued at the
    # current call site, and OR semantics map cleanly onto the DB-direct path.
    # category_path (exact full_path) ALWAYS goes DB-direct, even with q:
    # Typesense indexes the path as `category_paths` joined with a bare ">"
    # (no spaces) while the DB / autocomplete chips use " > ", so the
    # Typesense `category_paths:=` filter matches nothing and the page comes
    # back empty (the "443 + Floor Mats -> 0" bug). The DB path matches
    # Category.full_path exactly AND ILIKEs q, giving the right count.
    # Price sorts ALSO go DB-direct: Typesense indexes no price field, so a
    # price sort_by errors there and only reaches the pace path via the
    # exception fallback below. Route it explicitly so the resolved-retail sort
    # key is used deterministically (and we skip a guaranteed-failing Typesense
    # round-trip). Owner ask 2026-06-06.
    pace_only = bool(base_vehicle_id) or bool(vehicle_type) or bool(attrs) or is_multi_brand or bool(category_path) or (
        sort in ("price_asc", "price_desc")
    ) or (
        bool(category_top) and not q
    )
    if pace_only:
        result = await _browse_via_pace(
            db, base_vehicle_id, q=q, brands=canonical_brands,
            category_top=category_top, category_path=category_path,
            vehicle_type=vehicle_type, attrs=attrs, sort=sort,
            in_stock_only=in_stock, user=user, request=request,
            page=page, per_page=per_page,
        )
        if cache_key is not None:
            browse_cache.set(cache_key, result)
        return result

    # Path B: full-text search path via Typesense (with fast-fail fallback).
    #
    # Part-number-style queries trigger infix matching on the SKU field —
    # same heuristic the autocomplete dropdown uses. Without this, clicking
    # a brand chip in the autocomplete (which uses infix for SKU substrings
    # like "44072" → "BHTJ-440721") loses the part hits when navigating to
    # the full catalog page, because plain Typesense full-text doesn't
    # split SKUs on `-` and won't match a bare numeric substring.
    import re as _re
    # >=3 (not >=4): a 3-char numeric query like "443" is a legitimate SKU
    # substring. Plain full-text only matches "443" as a whole token (1 hit),
    # but infix SKU matching finds every BHTJ-*443* part (~500). Threshold of 4
    # silently dropped all 3-char part searches to the full-text path.
    looks_like_part_number = bool(q) and (
        len(q) >= 3
        and " " not in q
        and bool(_re.search(r"\d", q))
        and bool(_re.match(r"^[A-Za-z0-9._/\-]+$", q))
    )
    channel = await _viewer_channel(db, user, request)
    try:
        response = search_products(
            query=q, brand=first_brand, category_top=category_top,
            category_path=category_path, in_stock_only=in_stock,
            cta_mode=cta_mode, page=page, per_page=per_page, sort_by=sort,
            infix="always" if looks_like_part_number else None,
            channel=channel, fit_base_vehicle_id=fit_bvid,
        )
    except Exception:
        # Typesense down — fall back to a DB-direct search that honors `q`
        # (and the parsed vehicle, if any, via base_vehicle_id).
        result = await _browse_via_pace(
            db, fit_bvid, q=q, brands=canonical_brands,
            category_top=category_top, category_path=category_path,
            attrs=attrs, sort=sort,
            in_stock_only=in_stock, user=user, request=request,
            page=page, per_page=per_page,
        )
        if resolved_vehicle is not None:
            result["resolved_vehicle"] = resolved_vehicle
        if cache_key is not None:
            browse_cache.set(cache_key, result)
        return result

    hits = [_serialize_product_card(h) for h in response.get("hits", [])]
    facets = {}
    for fc in response.get("facet_counts", []):
        field = fc["field_name"]
        counts = [
            {"value": c["value"], "count": c["count"]}
            for c in fc.get("counts", [])
        ]
        facets[field] = counts

    result = {
        "hits": hits,
        "found": response.get("found", 0),
        "page": response.get("page", page),
        "per_page": per_page,
        "search_time_ms": response.get("search_time_ms", 0),
        "facets": facets,
    }
    if resolved_vehicle is not None:
        # So the storefront can show a "Showing results that fit <truck>" chip.
        result["resolved_vehicle"] = resolved_vehicle
    if cache_key is not None:
        browse_cache.set(cache_key, result)
    return result


async def _browse_via_pace(
    db: AsyncSession,
    base_vehicle_id: int | None,
    *,
    q: str | None = None,
    brands: list[str] | None = None,
    category_top: str | None = None,
    category_path: str | None = None,
    vehicle_type: str | None = None,
    attrs: list[str] | None = None,
    sort: str | None = None,
    in_stock_only: bool = False,
    user: User | None = None,
    request: Request | None = None,
    page: int = 1,
    per_page: int = 24,
) -> dict[str, Any]:
    """Direct Postgres browse — used when YMM-filtering or Typesense is down.

    Supports a `q` text filter via ILIKE against Product.sku / Product.name
    / Brand.name so the search bar keeps working when Typesense is down.
    Not as good as Typesense (no fuzzy / ranking) but functional."""
    import time as _time
    from sqlalchemy import and_, bindparam, case as sa_case, distinct, func, or_, text
    from app.models import (
        Category, PacePart, PaceFitment, PcdbPartType, ProductImage,
        VcdbBaseVehicle, VcdbModel,
    )
    _t0 = _time.perf_counter()

    # Resolve the viewer's channel so per-customer-channel hides apply on this
    # DB path too (Typesense-down / YMM-filter fallback). Internal callers pass
    # no request -> retail.
    channel = "retail"
    if user is not None and request is not None:
        channel = await _viewer_channel(db, user, request)

    # Always join Brand so we can filter out deactivated brands (RV-OEM
    # noise like Lippert / Dometic that snuck in via PACE feeds).
    base_q = (
        select(Product)
        .options(selectinload(Product.brand), selectinload(Product.images))
        .join(Brand, Brand.id == Product.brand_id)
        .where(visible_to_channel_clause(channel), Product.is_for_sale == True,  # noqa: E712
               Brand.is_active == True)  # noqa: E712
    )

    if base_vehicle_id is not None:
        # Three-way OR — same pattern as the vehicle_type branch below.
        # A product surfaces under YMM=2024 Ford F-150 if ANY holds:
        #   (1) it has a PaceFitment for this base_vehicle_id, OR
        #   (2) it has NO pace_part rows at all (PIES-only / universal), OR
        #   (3) it has pace_part rows but NONE of them have any fitment
        #       (universal kit, e.g. emergency-warning strip lights).
        # Owner ask 2026-05-17: categories like "Emergency and Warning
        # Lighting" are highly universal — a strict fitment filter
        # zeroed out 186 products on the F-150. The L4 fitment-badge
        # work (deferred) will distinguish (1) as "Match" from (2)/(3)
        # as "Check fitment / Universal" in the row UI.
        # Cases (2)+(3) — "carries no ACES fitment at all" — are precomputed
        # into the indexed Product.has_no_fitment flag (maintained by ingest +
        # the backfill migration), so we no longer OR two catalog-wide
        # semi-join scans here. Case (1) stays a vehicle-scoped subquery.
        vehicle_fit_ids = (
            select(distinct(PacePart.product_id))
            .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
            .where(PaceFitment.base_vehicle_id == base_vehicle_id,
                    PacePart.product_id.is_not(None))
        )
        base_q = base_q.where(
            or_(
                Product.id.in_(vehicle_fit_ids),
                Product.has_no_fitment == True,  # noqa: E712
            )
        )

    if vehicle_type:
        # Three passes UNIONed together — a product surfaces under
        # vehicle_type=Van if ANY of these hold:
        #   (1) it has at least one fitment to a Van model, OR
        #   (2) it has NO pace_part rows at all (PIES-only with no fitment), OR
        #   (3) it has pace_part rows but NONE of those parts have ANY
        #       pace_fitment rows (universal kit shipped without ACES).
        # The bug we fixed: previously (2) and (3) were collapsed into a
        # "no pace_part" check, which excluded Lippert van-package kits that
        # have pace_part metadata but no ACES fitment.
        # Cases (2)+(3) collapse into the indexed Product.has_no_fitment flag
        # (see the base_vehicle_id branch above); case (1) stays a
        # vehicle-class-scoped subquery.
        type_fit_ids = (
            select(distinct(PacePart.product_id))
            .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
            .join(VcdbBaseVehicle, VcdbBaseVehicle.id == PaceFitment.base_vehicle_id)
            .join(VcdbModel, VcdbModel.id == VcdbBaseVehicle.model_id)
            .where(VcdbModel.vehicle_type == vehicle_type,
                    PacePart.product_id.is_not(None))
        )
        base_q = base_q.where(
            or_(
                Product.id.in_(type_fit_ids),
                Product.has_no_fitment == True,  # noqa: E712
            )
        )

    if q:
        # Free-text filter — split q on whitespace, AND each token against
        # ILIKE on (sku OR product name OR brand name). So "sprinter awning"
        # matches a product whose name contains BOTH "sprinter" and "awning",
        # not just the literal phrase. Brand is already joined via base_q.
        tokens = [t for t in q.strip().split() if t]
        for tok in tokens:
            pattern = f"%{tok}%"
            base_q = base_q.where(or_(
                Product.sku.ilike(pattern),
                Product.name.ilike(pattern),
                Brand.name.ilike(pattern),
            ))

    # NOTE: brand filter is applied LAST (after category + attrs) so that
    # `base_q` snapshot here can be reused for computing brand facet counts
    # — facets show "available brands AFTER applying every OTHER filter."
    if category_top or category_path:
        from app.models import ProductCategory
        # `category_path` is an exact full_path match ("Truck Accessories >
        # Exterior > Bug and Hood Shields"). `category_top` is a category
        # NAME lookup ("Exterior") that walks descendants — works regardless
        # of where Exterior sits in the tree after 2026-05-10 re-parenting.
        if category_path:
            target_path = category_path
            like_pattern = f"{target_path} > %"
            cat_q = select(Category.id).where(
                (Category.full_path == target_path) | (Category.full_path.like(like_pattern))
            )
        else:
            target_name = category_top
            # Find the category by name + walk every descendant via full_path
            # prefix. Self-join: descendants have full_path starting with
            # "<ancestor.full_path> > ".
            from sqlalchemy.orm import aliased
            anchor = aliased(Category)
            cat_q = (
                select(Category.id)
                .select_from(Category)
                .join(anchor, (Category.id == anchor.id)
                              | (Category.full_path.like(anchor.full_path.op('||')(' > %'))))
                .where(anchor.name == target_name)
                .distinct()
            )
        prod_in_cat = (
            select(ProductCategory.product_id)
            .where(ProductCategory.category_id.in_(cat_q))
        )
        base_q = base_q.where(Product.id.in_(prod_in_cat))

    # PIES attribute filter — `attrs` is a repeatable "Key|Value" param.
    # Multiple values for the SAME key → OR (any-of). Different keys → AND
    # (each must match).
    #
    # Values arrive as canonical (the storefront UI displays canonical
    # labels). We expand each canonical back to the set of raw values it
    # covers using two sources:
    #   1. `attribute_value_alias` rows with source='manual' (curator
    #      confirmed merges)
    #   2. The deterministic auto_canonical() — any raw row that folds to
    #      the requested canonical without an explicit alias entry
    if attrs:
        from sqlalchemy import tuple_
        from app.models import (
            AttributeKeyAlias, AttributeValueAlias, ProductAttribute,
        )
        from app.services.attribute_canonical import auto_canonical
        from app.services.attribute_key_merge import (
            normalize_key_name, group_value_bucket,
        )
        by_key: dict[str, list[str]] = {}
        for raw in attrs:
            if not raw or "|" not in raw:
                continue
            k, v = raw.split("|", 1)
            k = k.strip()
            v = v.strip()
            if not k or not v:
                continue
            by_key.setdefault(k, []).append(v)

        # The storefront sends the merged-group LABEL as the key. Resolve each
        # selected key to its member attribute_keys: manual synonyms from
        # attribute_key_alias + deterministic label-variants (same normalized
        # name). Fetch the distinct-key universe once for the auto resolution.
        all_distinct_keys: list[str] = []
        if by_key:
            all_distinct_keys = (await db.execute(
                select(distinct(ProductAttribute.attribute_key))
            )).scalars().all()

        async def _resolve_members(label: str) -> list[str]:
            members = {label}
            manual_members = (await db.execute(
                select(AttributeKeyAlias.member_key)
                .where(AttributeKeyAlias.group_label == label)
            )).scalars().all()
            members.update(manual_members)
            nlabel = normalize_key_name(label)
            members.update(
                k for k in all_distinct_keys if normalize_key_name(k) == nlabel
            )
            return list(members)

        for key, canonical_values in by_key.items():
            members = await _resolve_members(key)
            if len(members) > 1:
                # Merged group: match products where ANY member key holds a
                # value in the SAME bucket as the selected value. Bucketing
                # here MUST match the facet-render side (group_value_bucket).
                want_buckets = {group_value_bucket(cv) for cv in canonical_values}
                pair_rows = (await db.execute(
                    select(distinct(ProductAttribute.attribute_key),
                           ProductAttribute.attribute_value)
                    .where(ProductAttribute.attribute_key.in_(members))
                    .where(ProductAttribute.attribute_value.is_not(None))
                    .where(ProductAttribute.attribute_value != "")
                )).all()
                wanted_pairs = [
                    (mk, rv) for mk, rv in pair_rows
                    if group_value_bucket(rv) in want_buckets
                ]
                if not wanted_pairs:
                    base_q = base_q.where(Product.id == -1)
                    continue
                attr_pids = (
                    select(distinct(ProductAttribute.product_id))
                    .where(tuple_(ProductAttribute.attribute_key,
                                  ProductAttribute.attribute_value).in_(wanted_pairs))
                )
                base_q = base_q.where(Product.id.in_(attr_pids))
                continue

            # --- single key (unchanged): resolve canonical -> raw values ---
            # Resolve each canonical to the set of raw values it matches.
            wanted_raws: set[str] = set()
            # 1) manual aliases
            manual = (await db.execute(
                select(
                    AttributeValueAlias.raw_value,
                    AttributeValueAlias.canonical_value,
                )
                .where(AttributeValueAlias.attribute_key == key)
                .where(AttributeValueAlias.canonical_value.in_(canonical_values))
                .where(AttributeValueAlias.source == "manual")
            )).all()
            aliased_raws = {raw for raw, _ in manual}
            wanted_raws.update(aliased_raws)
            # 2) auto-canonical fallback — look at every distinct raw value
            # for this key, fold via auto_canonical, and pick the ones that
            # land on a requested canonical (and aren't already covered by
            # a manual alias for a different canonical, which would conflict).
            manual_keyed = {raw for raw, _ in manual}
            # All raws currently mapped to ANY canonical via manual aliases
            all_manual_for_key = (await db.execute(
                select(AttributeValueAlias.raw_value)
                .where(AttributeValueAlias.attribute_key == key)
                .where(AttributeValueAlias.source == "manual")
            )).scalars().all()
            distinct_raws = (await db.execute(
                select(distinct(ProductAttribute.attribute_value))
                .where(ProductAttribute.attribute_key == key)
                .where(ProductAttribute.attribute_value.is_not(None))
                .where(ProductAttribute.attribute_value != "")
            )).scalars().all()
            canonical_set = set(canonical_values)
            for raw in distinct_raws:
                if raw in set(all_manual_for_key) and raw not in manual_keyed:
                    continue  # already manually aliased to a different canonical
                if auto_canonical(raw) in canonical_set:
                    wanted_raws.add(raw)
            if not wanted_raws:
                # No raws match — force empty result instead of dropping filter
                base_q = base_q.where(Product.id == -1)
                continue
            attr_pids = (
                select(distinct(ProductAttribute.product_id))
                .where(ProductAttribute.attribute_key == key)
                .where(ProductAttribute.attribute_value.in_(list(wanted_raws)))
            )
            base_q = base_q.where(Product.id.in_(attr_pids))

    # "In stock only" checkbox filter — restricts to products whose SUM
    # of on_hand across all warehouses is > 0. Applied here (after vehicle,
    # category, attr, and brand-normalization but BEFORE the brand-facet
    # snapshot) so the brand facets honor the in-stock filter too.
    if in_stock_only:
        from app.models import ProductInventory
        in_stock_pids = (
            select(ProductInventory.product_id)
            .group_by(ProductInventory.product_id)
            .having(func.sum(ProductInventory.on_hand) > 0)
        )
        base_q = base_q.where(Product.id.in_(in_stock_pids))

    from sqlalchemy import Column, Integer, MetaData, Table, insert as sa_insert
    from app.models import ProductInventory, ProductPrice

    # `base_q` here carries every filter EXCEPT the user's brand SELECTION
    # (vehicle / category / attr / in-stock). That filter — especially the
    # catalog-wide vehicle fitment subquery — costs ~1.8s on a big category,
    # and was previously re-executed ~4x per request (total count, in-stock
    # count, page slice, brand facets ≈ 7s cold on Seat Covers + Truck).
    # Materialize the matching product-id set ONCE into a session temp table,
    # then run all four as cheap index joins against it. Validated on prod:
    # Seat Covers + Truck 7.06s -> ~1.75s, byte-identical result counts.
    match_tbl = Table(
        "_browse_match", MetaData(), Column("id", Integer, primary_key=True),
    )
    # No ON COMMIT DROP — DROP IF EXISTS guards against a leftover temp table
    # on a pooled connection so the recreate is deterministic each request.
    await db.execute(text("DROP TABLE IF EXISTS _browse_match"))
    await db.execute(text("CREATE TEMP TABLE _browse_match (id integer PRIMARY KEY)"))
    await db.execute(
        sa_insert(match_tbl).from_select(
            ["id"], base_q.with_only_columns(Product.id).distinct()
        )
    )

    # Brand SELECTION is applied on TOP of the materialized set, so the brand
    # facet rail below (which reads the un-branded temp table) still shows
    # "Husky (X)" even when the user has selected "WeatherTech." Multi-brand →
    # OR each entry; accept EITHER the display name ("Warn") OR slug ("warn").
    # No brand selected → the matched set IS the whole temp table.
    if brands:
        brand_clauses = [
            or_(func.lower(Brand.name) == b.lower(), Brand.slug == b.lower())
            for b in brands
        ]
        matched_ids = (
            select(match_tbl.c.id)
            .join(Product, Product.id == match_tbl.c.id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(or_(*brand_clauses))
        )
    else:
        matched_ids = select(match_tbl.c.id)
    matched_ids_sq = matched_ids.subquery()

    total = (await db.execute(
        select(func.count()).select_from(matched_ids_sq)
    )).scalar_one()
    # In-stock count alongside total — header badge "X products · N in stock".
    in_stock_count = 0
    if total > 0:
        in_stock_count = (await db.execute(
            select(func.count(func.distinct(ProductInventory.product_id)))
            .where(ProductInventory.product_id.in_(select(matched_ids_sq.c.id)))
            .where(ProductInventory.on_hand > 0)
        )).scalar_one() or 0
    offset = max(0, (page - 1) * per_page)
    # Sort order — owner ask 2026-05-17:
    #   - DEFAULT: in-stock items first (when any exist), then name A→Z.
    #     Composite sort gives the customer something to act on without
    #     burying OOS — they're still on later pages of the same category.
    #   - "name_asc" / "name_desc": pure alphabetical, ignores stock.
    #   - "price_asc" / "price_desc": pure price, overrides stock-first
    #     so a customer sorting by price gets a true price ladder.
    #
    # Composite sort needs the same `coalesce(sum(on_hand), 0) > 0`
    # predicate the stock badge uses. LEFT JOIN the per-product on-hand
    # sum, then sort with `(on_hand_total > 0) DESC` as the primary key.
    stock_sort_sq = (
        select(
            ProductInventory.product_id,
            func.coalesce(func.sum(ProductInventory.on_hand), 0).label("on_hand_total"),
        )
        .group_by(ProductInventory.product_id)
        .subquery("stock_sort")
    )
    # Sort by the SAME price the storefront displays — the contract/sentinel
    # resolved retail (persisted in resolved_retail_price). The raw retail_price
    # tier diverges from the displayed price by a per-brand markup, so sorting on
    # it scattered brands (e.g. in-stock Western snow plows sank below their
    # displayed price). Fall back to retail_price / SRP for any product not yet
    # recomputed so a fresh column never blanks the ladder. Owner ask 2026-06-06.
    price_sort_sq = (
        select(
            ProductPrice.product_id,
            func.coalesce(
                ProductPrice.resolved_retail_price,
                ProductPrice.retail_price,
                ProductPrice.suggested_retail_price,
            ).label("sort_price"),
        )
        .subquery("price_sort")
    )
    sorted_q = (
        select(Product)
        .options(selectinload(Product.brand), selectinload(Product.images))
        .where(Product.id.in_(select(matched_ids_sq.c.id)))
        .outerjoin(stock_sort_sq, stock_sort_sq.c.product_id == Product.id)
        .outerjoin(price_sort_sq, price_sort_sq.c.product_id == Product.id)
    )
    if sort == "name_asc":
        sorted_q = sorted_q.order_by(Product.name.asc())
    elif sort == "name_desc":
        sorted_q = sorted_q.order_by(Product.name.desc())
    elif sort == "price_asc":
        # Pure price ladder. NULL prices to the END.
        sorted_q = sorted_q.order_by(
            price_sort_sq.c.sort_price.asc().nulls_last(),
            Product.name.asc(),
        )
    elif sort == "price_desc":
        sorted_q = sorted_q.order_by(
            price_sort_sq.c.sort_price.desc().nulls_last(),
            Product.name.asc(),
        )
    else:
        # Default: in-stock first, then alphabetical. The first ORDER BY
        # column is a boolean (on_hand > 0) so all in-stock products
        # tie at the top; the secondary name asc gives them a stable
        # display order within the in-stock group, and again within OOS.
        sorted_q = sorted_q.order_by(
            (func.coalesce(stock_sort_sq.c.on_hand_total, 0) > 0).desc(),
            Product.name.asc(),
        )
    rows = (await db.execute(
        sorted_q.offset(offset).limit(per_page)
    )).scalars().unique().all()

    # Bulk-load inventory totals for just this page of products.  Avoids the
    # 296K-row reindex needing to be perfectly fresh.  Updated 2026-05-14
    # when TTE inventory linker came online — previously this path hard-coded
    # in_stock=False which was right when we had no inventory loaded.
    page_pids = [p.id for p in rows]
    stock_lookup: dict[int, int] = {}
    locations_lookup: dict[int, int] = {}
    price_lookup: dict[int, dict[str, float | None]] = {}
    if page_pids:
        from app.models import ProductInventory, ProductPrice
        stock_rows = (await db.execute(
            select(
                ProductInventory.product_id,
                func.sum(ProductInventory.on_hand),
                func.count(
                    func.distinct(
                        # Count warehouses where this product has positive stock
                        sa_case((ProductInventory.on_hand > 0, ProductInventory.warehouse_id),
                                else_=None)
                    )
                ),
            )
            .where(ProductInventory.product_id.in_(page_pids))
            .group_by(ProductInventory.product_id)
        )).all()
        # Critical: don't name the loop variable `total` — that shadows the
        # row-count `total` from above and Python leaks for-vars into the
        # enclosing scope, so the response `found` would end up being the
        # on_hand of the last product on the page instead of the actual
        # number of matching products.
        for pid, pid_on_hand, loc_count in stock_rows:
            stock_lookup[pid] = int(pid_on_hand or 0)
            locations_lookup[pid] = int(loc_count or 0)
        # Baseline prices (anonymous retail view). Tier pricing comes once
        # auth is wired into the browse path; for now show retail (or
        # suggested_retail_price as fallback) + sale price.
        price_rows = (await db.execute(
            select(
                ProductPrice.product_id,
                ProductPrice.retail_price,
                ProductPrice.suggested_retail_price,
                ProductPrice.sale_price,
            )
            .where(ProductPrice.product_id.in_(page_pids))
        )).all()
        for pid, retail, srp, sale in price_rows:
            display = retail or srp
            price_lookup[pid] = {
                "retail": float(display) if display is not None else None,
                "sale": float(sale) if sale is not None else None,
            }

        # Sentinel-driven retail: the website's published retail price comes
        # from the contract pricing engine using "TITAN WEBSITE SALES"
        # (customer_number=106415). Owner directive 2026-05-17 — see
        # feedback_map_retail_only.md and the pricing_service docs. Overlays
        # on top of the simple ProductPrice.retail_price lookup so any
        # product NOT covered by a sentinel contract falls back gracefully.
        from app.services.pricing_service import resolve_retail_for_products
        try:
            sentinel_prices = await resolve_retail_for_products(db, list(rows))
            for pid, resolved in sentinel_prices.items():
                if resolved is None:
                    continue
                entry = price_lookup.setdefault(pid, {"retail": None, "sale": None})
                entry["retail"] = float(resolved)
        except Exception:
            log.exception("sentinel retail resolution failed; using ProductPrice.retail_price")

    # Tier-aware pricing for logged-in B2B customers. Owner ask 2026-05-17
    # (L1 in project_storefront_queue.md): "Your Cost" stack on every list
    # and grid row when the customer has a contract on file. Engine logic
    # already lives in pricing_service.build_tier_display — we batch the
    # ProductPrice + Contract loads here and call build_tier_display per
    # row so each gets contract-resolved per-product.
    # Honors admin "Shop as Customer" impersonation: when an admin has an
    # `imp_cust` JWT claim, tier pricing reflects that customer's contracts
    # rather than the admin's own (typically null) customer linkage.
    tier_pricing_lookup: dict[int, dict[str, Any]] = {}
    effective_cust_id: int | None = None
    if user is not None and request is not None:
        effective_cust_id = await resolve_effective_customer_id(db, user, request)
    elif user is not None:
        effective_cust_id = user.customer_id
    if page_pids and effective_cust_id is not None:
        customer = (await db.execute(
            select(Customer).where(Customer.id == effective_cust_id)
        )).scalar_one_or_none()
        if customer is not None:
            # Batch resolve tier pricing for the whole page in a fixed number
            # of queries (customer contracts once + page ProductPrice once)
            # instead of ~3 queries per row. Falls back to the per-product
            # path if the batch raises, so one malformed contract can't 500
            # the page.
            try:
                displays = await build_tier_display_batch(
                    db, customer=customer, products=list(rows)
                )
                for pid, display in displays.items():
                    tier_pricing_lookup[pid] = display.as_dict()
            except Exception:
                log.exception("batch tier pricing failed; falling back per-product")
                for p in rows:
                    try:
                        display = await build_tier_display(db, customer=customer, product=p)
                        tier_pricing_lookup[p.id] = display.as_dict()
                    except Exception:
                        continue

    # Fitment summary per product on the page. Owner ask 2026-05-17: list
    # row should preview the first couple of "Year Make Model" applications
    # inline; universal kits show "Universal." Bulk query — one SQL hit
    # for the page's product_ids, then group in Python so we can return
    # the top-3 most-trucks-fit + the total fitment-row count.
    fitment_lookup: dict[int, dict[str, Any]] = {}
    if page_pids:
        fit_rows = (await db.execute(text("""
            SELECT pp.product_id,
                   m.name AS make_name,
                   mo.name AS model_name,
                   MIN(bv.year) AS y_start,
                   MAX(bv.year) AS y_end,
                   COUNT(*)     AS fits
            FROM pace_part pp
            JOIN pace_fitment f ON f.pace_part_id = pp.id
            JOIN vcdb_base_vehicle bv ON bv.id = f.base_vehicle_id
            JOIN vcdb_make m ON m.id = bv.make_id
            JOIN vcdb_model mo ON mo.id = bv.model_id
            WHERE pp.product_id IN :pids
              AND m.name <> 'UNKNOWN'
            GROUP BY pp.product_id, m.name, mo.name
        """).bindparams(bindparam("pids", expanding=True)), {"pids": page_pids})).all()
        # Group by product → list of (make, model, year_start, year_end, fits)
        # sorted by fits DESC so the top fitments surface first.
        per_product: dict[int, list[tuple]] = {}
        for pid, make, model, y_start, y_end, fits in fit_rows:
            per_product.setdefault(pid, []).append((make, model, int(y_start) if y_start else None, int(y_end) if y_end else None, int(fits)))
        for pid, groups in per_product.items():
            groups.sort(key=lambda g: g[4], reverse=True)
            summary: list[str] = []
            for make, model, y_start, y_end, _ in groups[:3]:
                if y_start and y_end:
                    yr = f"{y_start}-{y_end}" if y_start != y_end else str(y_start)
                else:
                    yr = ""
                summary.append(f"{yr} {make} {model}".strip())
            fitment_lookup[pid] = {
                "summary": summary,
                "group_count": len(groups),  # distinct make+model groups
                "universal": False,
            }

    hits = []
    for p in rows:
        # Image fallback chain: primary product image → any product image → brand logo.
        # "photocomingsoon" URLs from the aam-files CDN are explicit "no image
        # yet" placeholders; skip them and drop back to the brand logo so the
        # card has a more on-brand appearance.
        def _usable(url: str | None) -> bool:
            return bool(url) and "photocomingsoon" not in url.lower()
        usable_imgs = [i for i in p.images if _usable(i.url)]
        primary = next((img.url for img in usable_imgs if img.is_primary), None) \
                  or (usable_imgs[0].url if usable_imgs else None) \
                  or (p.brand.logo_url if (p.brand and p.brand.logo_url) else None)
        stock_total = stock_lookup.get(p.id, 0)
        prices = price_lookup.get(p.id, {})
        fitment = fitment_lookup.get(p.id)
        tier_pricing = tier_pricing_lookup.get(p.id)
        # Brand-level special-order lead time (L9). Surfaced inline on OOS
        # rows so customers know what they're committing to. Null when not
        # set; UI then shows just the generic "Special order" label.
        lt_min = p.brand.special_order_lead_time_min_days if p.brand else None
        lt_max = p.brand.special_order_lead_time_max_days if p.brand else None
        hits.append({
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "brand": p.brand.name if p.brand else None,
            "special_order_lead_time_min_days": lt_min,
            "special_order_lead_time_max_days": lt_max,
            "in_stock": stock_total > 0,
            "stock_total": stock_total,
            "locations_count": locations_lookup.get(p.id, 0),
            "cta_mode": p.cta_mode.value if hasattr(p.cta_mode, "value") else (p.cta_mode or "add_to_cart"),
            "shipping_mode": p.shipping_mode or "ship",
            "freight_class": p.freight_class,
            "image_url": primary,
            "category_top": (category_top or category_path or "").split(" > ")[0] or None,
            "description": p.description,
            "series": p.series,
            "retail_price": prices.get("retail"),
            "sale_price": prices.get("sale"),
            # Tier-resolved customer cost (logged-in B2B only). Anonymous
            # users get null and the frontend falls back to retail_price.
            "tier_pricing": tier_pricing,
            # Top-3 "Year Make Model" applications + total group count.
            # Universal (no fitments) products get summary=[] + universal=True
            # so the storefront can render "Universal" instead.
            "fitment_summary": fitment["summary"] if fitment else [],
            "fitment_group_count": fitment["group_count"] if fitment else 0,
            "fitment_universal": fitment is None,
        })

    # Brand facet counts — every active filter EXCEPT brand applied, so
    # the rail tells the customer "you currently have N WeatherTech and
    # M Husky in this view." Re-selecting a brand doesn't shrink the
    # OTHER brands' counts (standard faceted-nav behavior). Capped at
    # 50 brands so we don't render a wall when the user is on a top
    # category with hundreds of brands.
    # Reads the un-branded matched set straight off the temp table (its id is
    # the PK, so count(*) == count(distinct product)). No filter re-evaluation.
    brand_facet_rows = (await db.execute(
        select(Brand.name, func.count())
        .select_from(match_tbl)
        .join(Product, Product.id == match_tbl.c.id)
        .join(Brand, Brand.id == Product.brand_id)
        .group_by(Brand.name)
        .order_by(func.count().desc())
        .limit(50)
    )).all()
    brand_facet = [
        {"value": name, "count": int(n)}
        for name, n in brand_facet_rows
    ]

    return {
        "hits": hits,
        "found": total,
        "in_stock_count": int(in_stock_count),
        "page": page,
        "per_page": per_page,
        "search_time_ms": int((_time.perf_counter() - _t0) * 1000),
        "facets": {"brand_name": brand_facet},
        "fitment_filtered": base_vehicle_id is not None,
    }


@router.get("/products/{sku}")
async def product_detail(
    sku: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Full PDP data — tier-aware pricing if logged in with linked customer."""
    stmt = (
        select(Product)
        .where(Product.sku == sku)
        .options(
            selectinload(Product.brand),
            selectinload(Product.images),
        )
    )
    result = await db.execute(stmt)
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product not found: {sku}")

    # The viewer's channel (retail for anonymous/bots) — drives the per-channel
    # visibility gate below and is reused by the kit gate further down.
    channel = await _viewer_channel(db, user, request)

    # Hidden-for-this-channel / not-for-sale / deactivated-brand products are
    # "gone" to that audience: return 410 so search engines and AI bots (which
    # are the retail channel) drop the URL instead of indexing a dead page (they
    # get no content, and the SPA renders a noindex "no longer available" state).
    # A product visible to retail but hidden from, say, wholesale still serves a
    # normal 200 to the public. Staff (admin/editor) always get the full PDP so
    # they can preview a hidden line before turning it back on.
    _role = (user.role.value if user and hasattr(user.role, "value") else str(getattr(user, "role", ""))) if user else ""
    _is_staff = _role in ("admin", "editor")
    _brand_active = product.brand.is_active if product.brand else True
    if (product_hidden_for(product, channel) or not product.is_for_sale or not _brand_active) and not _is_staff:
        raise HTTPException(status_code=410, detail=f"This product is no longer available: {sku}")

    # Categorized text content — PIES descriptions + scraped feature blocks.
    # Source: PIES loader writes generic codes (DES/FEA/INL/WAR/etc.); the
    # Buyers extended scraper writes code='FEA' rows for hero bullets +
    # feature carousels. Frontend Description tab groups by code; Specs tab
    # renders attributes if any are present (Layout B premium-plow PDPs).
    desc_rows = (await db.execute(
        select(ProductDescription)
        .where(ProductDescription.product_id == product.id)
        .order_by(ProductDescription.description_code, ProductDescription.sequence)
    )).scalars().all()
    descriptions = [
        {
            "code": d.description_code,
            "language_code": d.language_code,
            "sequence": d.sequence,
            "text": d.text,
        }
        for d in desc_rows
    ]
    attr_rows = (await db.execute(
        select(ProductAttribute)
        .where(ProductAttribute.product_id == product.id)
        .order_by(ProductAttribute.attribute_key)
    )).scalars().all()
    attributes = [
        {
            "key": a.attribute_key,
            "value": a.attribute_value,
            "uom": a.attribute_uom,
        }
        for a in attr_rows
    ]

    # Downloadable resources (install guides, datasheets, parts sheets).
    # WeatherGuard van-package ingest writes source='weatherguard' rows.
    res_rows = (await db.execute(
        select(ProductResource)
        .where(ProductResource.product_id == product.id)
        .order_by(ProductResource.sort_order, ProductResource.id)
    )).scalars().all()
    resources = [
        {
            "kind": r.kind.value if hasattr(r.kind, "value") else str(r.kind),
            "url": r.url,
            "title": r.title,
        }
        for r in res_rows
    ]

    # Manufacturer spec matrices (Knapheide: model x length x height x width,
    # grouped by cab-to-axle). Key/value attributes can't carry these, so they
    # travel as tables and render as tables on the Specs tab.
    spec_rows = (await db.execute(
        select(ProductSpecTable)
        .where(ProductSpecTable.product_id == product.id)
        .order_by(ProductSpecTable.sort_order, ProductSpecTable.id)
    )).scalars().all()
    spec_tables = [
        {"title": t.title, "headers": t.headers, "rows": t.rows, "note": t.note}
        for t in spec_rows
    ]

    # Kit / package bill-of-materials. Van packages (HWZD-600-8xxx) carry a Kit
    # whose components are the individual WeatherGuard part numbers. Each
    # component links to its own PDP when the part resolves to a catalog product.
    kit_block: dict[str, Any] | None = None
    kit = (await db.execute(
        select(Kit)
        .where(Kit.product_id == product.id)
        .options(selectinload(Kit.components))
    )).scalars().first()
    if kit is not None:
        # Live gate: a kit is shown only when it's active, within its
        # availability window, AND allowed for the viewer's channel — otherwise
        # 404 (hide entirely; parity with the catalog/search hide).
        from app.services.kit_inventory import kit_enabled_channels
        live_channels = kit_enabled_channels(
            is_active=kit.is_active, available_from=kit.available_from,
            available_until=kit.available_until,
            avail_retail=kit.avail_retail, avail_wholesale=kit.avail_wholesale,
            avail_dealer=kit.avail_dealer, avail_municipality=kit.avail_municipality,
        )
        if channel not in live_channels:
            raise HTTPException(status_code=404, detail=f"Product not found: {sku}")
        comps = sorted(kit.components, key=lambda c: (c.sort_order or 0))
        sku_by_pid: dict[int, str] = {}
        pid_list = [c.product_id for c in comps if c.product_id]
        if pid_list:
            for row in (await db.execute(
                select(Product.id, Product.sku).where(Product.id.in_(pid_list))
            )).all():
                sku_by_pid[row.id] = row.sku
        kit_block = {
            "sku": kit.sku,
            "trade": kit.trade,
            "vehicle_make": kit.vehicle_make,
            "vehicle_model": kit.vehicle_model,
            "wheelbase": kit.wheelbase,
            "hand": kit.hand,
            "components": [
                {
                    "part_number": c.part_number,
                    "quantity": c.quantity,
                    "description": c.description,
                    "product_id": c.product_id,
                    "sku": sku_by_pid.get(c.product_id),
                }
                for c in comps
            ],
        }

    # Inventory by warehouse
    inv_stmt = (
        select(ProductInventory)
        .where(ProductInventory.product_id == product.id)
        .options(selectinload(ProductInventory.warehouse))
    )
    inv_rows = (await db.execute(inv_stmt)).scalars().all()
    inventory = [
        {
            "warehouse_code": inv.warehouse.code,
            "warehouse_name": inv.warehouse.short_name,
            "on_hand": inv.on_hand,
            # available = on_hand minus open allocations (pending picks).
            # Falls back to on_hand when the legacy feed didn't supply it.
            "available": inv.available if inv.available is not None else inv.on_hand,
        }
        for inv in inv_rows
    ]
    # gl_cost is internal-only — never returned in the public response.

    # Tier-aware pricing. Honors admin "Shop as Customer" impersonation —
    # resolve_effective_customer_id returns the impersonated customer_id when
    # an admin's JWT carries an `imp_cust` claim, otherwise falls back to
    # user.customer_id. For anonymous + retail-tier users, build_tier_display
    # routes through build_retail_display which uses sentinel customer
    # 106415's contracts (owner directive 2026-05-17).
    from app.services.pricing_service import build_retail_display
    effective_cust_id: int | None = None
    if user is not None:
        effective_cust_id = await resolve_effective_customer_id(db, user, request)
    if effective_cust_id is not None:
        cust = (await db.execute(select(Customer).where(Customer.id == effective_cust_id))).scalar_one_or_none()
        if cust:
            display = await build_tier_display(db, customer=cust, product=product)
        else:
            display = await build_retail_display(db, product)
    else:
        display = await build_retail_display(db, product)

    pricing_block = display.as_dict()

    # R2 reseller-pair callout: when this product has a confirmed
    # ProductMatch where it's the MORE-EXPENSIVE sibling, surface the
    # cheaper alternate as a nudge near the buy box. Owner ask 2026-05-17.
    reseller_alternate: dict[str, Any] | None = None
    try:
        from app.models import ProductMatch, ProductMatchStatus, ProductPrice as _PP
        own_retail = None
        own_pp = (await db.execute(
            select(_PP.retail_price).where(_PP.product_id == product.id)
        )).scalar_one_or_none()
        if own_pp is not None:
            own_retail = float(own_pp)
        if own_retail is not None and own_retail > 0:
            matches = (await db.execute(
                select(ProductMatch).where(
                    ProductMatch.status == ProductMatchStatus.CONFIRMED,
                    or_(
                        ProductMatch.canonical_product_id == product.id,
                        ProductMatch.alias_product_id == product.id,
                    ),
                )
            )).scalars().all()
            best_savings = 0.0
            for m in matches:
                other_id = m.alias_product_id if m.canonical_product_id == product.id else m.canonical_product_id
                other = (await db.execute(
                    select(Product).options(selectinload(Product.brand))
                    .where(Product.id == other_id)
                )).scalar_one_or_none()
                if other is None: continue
                other_pp = (await db.execute(
                    select(_PP.retail_price).where(_PP.product_id == other_id)
                )).scalar_one_or_none()
                if other_pp is None: continue
                other_retail = float(other_pp)
                savings = own_retail - other_retail
                if savings > best_savings:
                    best_savings = savings
                    reseller_alternate = {
                        "sku": other.sku,
                        "name": other.name,
                        "brand": other.brand.name if other.brand else None,
                        "retail_price": other_retail,
                        "savings": round(savings, 2),
                    }
    except Exception:
        # Reseller callout is decoration; PDP must not 500 if the table is empty
        # or the lookup fails.
        reseller_alternate = None

    return {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "extended_description": product.extended_description,
        "reseller_alternate": reseller_alternate,
        "brand": {
            "id": product.brand.id,
            "name": product.brand.name,
            "slug": product.brand.slug,
            "special_order_lead_time_min_days": product.brand.special_order_lead_time_min_days,
            "special_order_lead_time_max_days": product.brand.special_order_lead_time_max_days,
        },
        "prod_code": product.prod_code,
        "weight_lb": float(product.weight_lb) if product.weight_lb else None,
        "dimensions": {
            "length_in": float(product.length_in) if product.length_in else None,
            "width_in": float(product.width_in) if product.width_in else None,
            "height_in": float(product.height_in) if product.height_in else None,
        },
        "freight_class": product.freight_class,
        "cta_mode": product.cta_mode.value if hasattr(product.cta_mode, "value") else str(product.cta_mode),
        # Retail shipping mode + flat-rate (the storefront gates display to
        # retail; B2B has a separate freight program). See retail_freight.py.
        "shipping_mode": product.shipping_mode,
        "flat_ship_amount": float(product.flat_ship_amount) if product.flat_ship_amount is not None else None,
        "is_for_sale": product.is_for_sale,
        # Per-channel: hidden for THIS viewer (retail for bots) — drives the
        # SPA <Seo noindex>. A wholesale-only hide stays indexable to the public.
        "is_hidden": product_hidden_for(product, channel),
        "images": [
            {"url": img.url, "alt": img.alt_text, "sort_order": img.sort_order}
            for img in product.images
        ],
        "inventory": inventory,
        "total_on_hand": sum(inv["on_hand"] for inv in inventory),
        "pricing": pricing_block,
        "viewer_tier": display.tier,
        "descriptions": descriptions,
        "attributes": attributes,
        "resources": resources,
        "spec_tables": spec_tables,
        "kit": kit_block,
    }


@router.get("/brands")
async def list_brands(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """List all active brands with logo + product counts.

    Hits Typesense for product counts via facets when available; falls
    back to a DB-direct count when Typesense is down (so /brands stays
    healthy regardless of Typesense uptime — needed for the no-dead-link
    + no-dead-image health checks).
    """
    from sqlalchemy import func as sa_func
    from app.models import Brand

    counts: dict[str, int] = {}
    try:
        response = search_products(query=None, per_page=1)
        brand_facet = next(
            (fc for fc in response.get("facet_counts", []) if fc["field_name"] == "brand_name"),
            None,
        )
        if brand_facet:
            counts = {c["value"]: c["count"] for c in brand_facet.get("counts", [])}
    except Exception:
        # Typesense down — fall through to DB-direct.
        pass

    if not counts:
        # DB fallback — count products grouped by brand_id.
        rows = (await db.execute(
            select(Brand.name, sa_func.count(Product.id))
            .join(Product, Product.brand_id == Brand.id)
            .where(Brand.is_active.is_(True),
                   Product.is_hidden == False,  # noqa: E712
                   Product.is_for_sale == True)  # noqa: E712
            .group_by(Brand.name)
            .order_by(sa_func.count(Product.id).desc())
        )).all()
        counts = {name: int(n) for name, n in rows}

    # Decorate with logo + slug for health-check + featured-brand rail
    brand_rows = (await db.execute(
        select(Brand.name, Brand.slug, Brand.logo_url, Brand.is_featured)
        .where(Brand.is_active.is_(True))
    )).all()
    by_name = {b.name: b for b in brand_rows}
    return [
        {
            "name": name,
            "product_count": n,
            "slug": (by_name.get(name).slug if by_name.get(name) else None),
            "logo_url": (by_name.get(name).logo_url if by_name.get(name) else None),
            "is_featured": (by_name.get(name).is_featured if by_name.get(name) else False),
        }
        for name, n in counts.items()
    ]


@router.get("/brands/index")
async def brands_index(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """A→Z brand directory grouped by first letter for the /brands page.

    Tries Typesense for facet counts; falls back to a single DB
    GROUP BY when Typesense is down so the page stays usable.
    """
    from sqlalchemy import func as sa_func
    from app.models import Brand
    rows = (await db.execute(
        select(Brand).where(Brand.is_active.is_(True)).order_by(Brand.name)
    )).scalars().all()

    counts_by_name: dict[str, int] = {}
    try:
        response = search_products(query=None, per_page=1)
        brand_facet = next(
            (fc for fc in response.get("facet_counts", []) if fc["field_name"] == "brand_name"),
            None,
        )
        counts_by_name = {c["value"]: c["count"] for c in (brand_facet.get("counts", []) if brand_facet else [])}
    except Exception:
        # Typesense down — DB-direct count
        count_rows = (await db.execute(
            select(Brand.name, sa_func.count(Product.id))
            .join(Product, Product.brand_id == Brand.id)
            .where(Brand.is_active.is_(True),
                   Product.is_hidden == False,  # noqa: E712
                   Product.is_for_sale == True)  # noqa: E712
            .group_by(Brand.name)
        )).all()
        counts_by_name = {name: int(n) for name, n in count_rows}

    by_letter: dict[str, list[dict[str, Any]]] = {}
    for b in rows:
        letter = (b.name[0] if b.name else "#").upper()
        if not letter.isalpha():
            letter = "#"
        by_letter.setdefault(letter, []).append({
            "name": b.name,
            "slug": b.slug,
            "product_count": counts_by_name.get(b.name, 0),
            "is_featured": bool(b.is_featured),
            "logo_url": b.logo_url,
        })
    return {
        "letters": sorted(by_letter.keys()),
        "groups": [{"letter": k, "brands": by_letter[k]} for k in sorted(by_letter.keys())],
    }


@router.get("/stats")
async def catalog_stats(db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Live catalog stats for the home page hero copy.

    Replaces the hardcoded "221,000 parts. 131 brands." with the real
    counts straight from the DB so the homepage stays honest as we
    re-ingest feeds and (de)activate brands.
    """
    from sqlalchemy import func as sa_func
    from app.models import Brand

    product_total = (await db.execute(
        select(sa_func.count(Product.id))
        .join(Brand, Brand.id == Product.brand_id)
        .where(Brand.is_active.is_(True),
               Product.is_hidden == False,  # noqa: E712
               Product.is_for_sale == True)  # noqa: E712
    )).scalar_one()
    brand_total = (await db.execute(
        select(sa_func.count(sa_func.distinct(Product.brand_id)))
        .join(Brand, Brand.id == Product.brand_id)
        .where(Brand.is_active.is_(True),
               Product.is_hidden == False,  # noqa: E712
               Product.is_for_sale == True)  # noqa: E712
    )).scalar_one()
    return {"products": int(product_total), "brands": int(brand_total)}


@router.get("/categories/tree")
async def categories_tree(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    """Full category tree, depth-first, with product counts AND a representative
    image_url per node.  Powers the "Shop by category" landing pages + nested
    mega-menu navigation.

    Counts come from the product_category bridge.  Image fallback chain:
    primary product image of any product in this category → primary product
    image of any descendant's product → brand logo of any product's brand →
    null.  Falls back to Typesense facet counts only if no DB rows exist yet
    (legacy WSM-era data path).

    The built tree is identical for every viewer and only changes when
    categories / their images / PACE ingestion change, so it's served from a
    long-TTL process cache (browse_cache.tree_cache). The first (cold) request
    pays the ~2.8s build; subsequent ones are a dict lookup.
    """
    from sqlalchemy import func, text
    from app.models import Category
    from app.services.browse_cache import tree_cache

    cached = tree_cache.get("tree")
    if cached is not None:
        return cached

    rows = (await db.execute(
        select(Category).where(Category.is_active.is_(True)).order_by(Category.full_path)
    )).scalars().all()

    # Per-category direct product counts from the bridge
    direct_count_rows = (await db.execute(text(
        "SELECT category_id, COUNT(DISTINCT product_id) AS n "
        "FROM product_category GROUP BY category_id"
    ))).all()
    direct_count = {cid: n for cid, n in direct_count_rows}

    # Per-category representative image — pick a varied, category-appropriate image.
    # Strategy (in order of preference):
    #   0a. STOCKED+IMAGED: highest-on-hand product in this category that ALSO
    #       has a valid primary image. Picks what we actually sell.
    #   0b. SALES-HISTORY: highest-shipped product in this category over the
    #       last 12 months with a primary image. Proxy for "what customers ask
    #       for." Falls through silently if order data isn't loaded yet.
    #   0c. NAME-MATCH: a product whose name contains one of the category's
    #       distinctive keywords (e.g. "Mud Guards and Mud Flaps" matches names
    #       containing "guards" or "flaps"). Fires when nothing is in stock /
    #       no sales history exists yet.
    #   1. Own-direct: any product mapped directly to this category.
    #   2. Descendant: an image from any descendant category's products.
    #   3. Brand logo: a logo of any brand selling in this category's tree.
    # Inheritance from PARENT happens in Python below, but only as a last resort
    # so sibling categories don't all collide on the same parent image.
    img_rows = (await db.execute(text("""
        WITH RECURSIVE descendants AS (
          SELECT id AS root_id, id AS desc_id, full_path FROM category WHERE is_active
          UNION ALL
          SELECT d.root_id, c.id AS desc_id, c.full_path FROM category c
            JOIN descendants d ON c.parent_id = d.desc_id
        ),
        -- Build a keyword list per category from its name. Drop stop words +
        -- the "Accessories" trailer; keep words >= 4 chars.
        cat_keywords AS (
          SELECT id AS cat_id, LOWER(word) AS word
          FROM (
            SELECT
              c.id,
              regexp_split_to_table(
                regexp_replace(c.name, ' and Accessories$', '', 'i'),
                ' '
              ) AS word
            FROM category c
          ) AS x
          WHERE LOWER(word) NOT IN
            ('and','or','the','of','a','an','for','with','to','accessories',
             'replacement','part','parts','kit','kits','&')
            AND LENGTH(word) >= 4
        ),
        -- Tier 0a: highest-on-hand product in this category with a valid image.
        -- This is the "what we actually sell" signal. Falls through silently
        -- if product_inventory is empty (Phase 0) or if no in-stock product
        -- in the category has an image.
        cat_stocked AS (
          SELECT DISTINCT ON (pc.category_id)
            pc.category_id AS root_id, pi.url
          FROM product_category pc
          JOIN product p ON p.id = pc.product_id
          JOIN product_image pi ON pi.product_id = p.id
          JOIN (
            SELECT product_id, SUM(on_hand) AS total
            FROM product_inventory
            GROUP BY product_id
            HAVING SUM(on_hand) > 0
          ) inv ON inv.product_id = p.id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
          ORDER BY pc.category_id, inv.total DESC, pi.id DESC
        ),
        -- Tier 0b: top-seller in the last 12 months with a valid image.
        cat_topseller AS (
          SELECT DISTINCT ON (pc.category_id)
            pc.category_id AS root_id, pi.url
          FROM product_category pc
          JOIN product p ON p.id = pc.product_id
          JOIN product_image pi ON pi.product_id = p.id
          JOIN (
            SELECT product_id, SUM(quantity) AS sold
            FROM order_line
            WHERE created_at >= NOW() - INTERVAL '365 days'
            GROUP BY product_id
          ) sales ON sales.product_id = p.id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            AND sales.sold > 0
          ORDER BY pc.category_id, sales.sold DESC, pi.id DESC
        ),
        -- Tier 0c: products whose name contains a category keyword.
        cat_namematch AS (
          SELECT DISTINCT ON (pc.category_id) pc.category_id AS root_id, pi.url
          FROM product_category pc
          JOIN product p ON p.id = pc.product_id
          JOIN product_image pi ON pi.product_id = p.id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            -- Trusted image sources only:
            --   aam-files (Google CDN, primary PIES image host)
            --   titantruck.com/images (our own legacy WSM images, including
            --     the Truck Bodies series imports from 2026-05-12)
            --   /static/* (locally-hosted brand-logos + category-images)
            -- This excludes random manufacturer-direct URLs (curtmfg.com,
            -- dometic.com, ranchhand.com, etc.) that had cert issues.
            AND (
              pi.url LIKE 'http://storage.googleapis.com/aam-files/%'
              OR pi.url LIKE 'https://www.titantruck.com/images/%'
              OR pi.url LIKE '/static/%'
            )
            AND EXISTS (
              SELECT 1 FROM cat_keywords ck
              WHERE ck.cat_id = pc.category_id
                AND LOWER(p.name) LIKE '%' || ck.word || '%'
            )
          ORDER BY pc.category_id, pi.id DESC
        ),
        -- Tier 1: own-direct products (no name match).
        cat_own AS (
          SELECT DISTINCT ON (pc.category_id)
            pc.category_id AS root_id, pi.url
          FROM product_category pc
          JOIN product_image pi ON pi.product_id = pc.product_id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            AND (
              pi.url LIKE 'http://storage.googleapis.com/aam-files/%'
              OR pi.url LIKE 'https://www.titantruck.com/images/%'
              OR pi.url LIKE '/static/%'
            )
          ORDER BY pc.category_id, pi.id DESC
        ),
        -- Tier 2: descendant products (for branches with kids but no direct hits).
        cat_desc AS (
          SELECT DISTINCT ON (d.root_id)
            d.root_id, pi.url
          FROM descendants d
          JOIN product_category pc ON pc.category_id = d.desc_id
          JOIN product_image pi ON pi.product_id = pc.product_id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            AND d.root_id <> d.desc_id  -- exclude self; cat_own already covers that
          ORDER BY d.root_id, pi.id DESC
        ),
        -- Tier 3: brand logo of a brand selling in this category's tree.
        cat_logo AS (
          SELECT DISTINCT ON (d.root_id)
            d.root_id, b.logo_url AS url
          FROM descendants d
          JOIN product_category pc ON pc.category_id = d.desc_id
          JOIN product p ON p.id = pc.product_id
          JOIN brand b ON b.id = p.brand_id
          WHERE b.logo_url IS NOT NULL AND b.logo_url <> ''
          ORDER BY d.root_id, b.id
        )
        SELECT
          c.id,
          -- Admin curation wins over every algorithmic tier
          COALESCE(c.curated_image_url, cs.url, ct.url, cn.url, co.url, cd.url, cl.url) AS image_url
        FROM category c
        LEFT JOIN cat_stocked   cs ON cs.root_id = c.id
        LEFT JOIN cat_topseller ct ON ct.root_id = c.id
        LEFT JOIN cat_namematch cn ON cn.root_id = c.id
        LEFT JOIN cat_own       co ON co.root_id = c.id
        LEFT JOIN cat_desc      cd ON cd.root_id = c.id
        LEFT JOIN cat_logo      cl ON cl.root_id = c.id
    """))).all()
    image_by_cat = {cid: url for cid, url in img_rows if url}

    # If product_category is empty, fall back to Typesense (legacy)
    counts_by_top: dict[str, int] = {}
    if not direct_count:
        try:
            response = search_products(query=None, per_page=1)
            top_facet = next(
                (fc for fc in response.get("facet_counts", []) if fc["field_name"] == "category_top"),
                None,
            )
            counts_by_top = {c["value"]: c["count"] for c in (top_facet.get("counts", []) if top_facet else [])}
        except Exception:
            counts_by_top = {}

    # If a category has no image of its own, inherit from the nearest ancestor
    # that does. Walk up parent chain. This means every sub-category under
    # "Cargo Management" gets at least the Cargo Management image even if it
    # has no products of its own yet.
    parent_by_id = {c.id: c.parent_id for c in rows}
    def inherit_image(cid: int) -> str | None:
        seen = set()
        cur = cid
        while cur and cur not in seen:
            seen.add(cur)
            url = image_by_cat.get(cur)
            if url:
                return url
            cur = parent_by_id.get(cur)
        return None

    # Build a nested structure
    by_id: dict[int, dict[str, Any]] = {}
    for c in rows:
        own_img = image_by_cat.get(c.id)
        by_id[c.id] = {
            "id": c.id, "name": c.name, "slug": c.slug, "full_path": c.full_path,
            "depth": c.depth, "parent_id": c.parent_id,
            "direct_count": direct_count.get(c.id, 0),
            # rolled-up count: own + all descendants. Filled in pass 2.
            "product_count": direct_count.get(c.id, 0)
                              or counts_by_top.get(c.full_path.split(">", 1)[0].strip(), 0),
            "image_url": own_img or inherit_image(c.parent_id) if not own_img else own_img,
            "image_inherited": not bool(own_img) and bool(inherit_image(c.parent_id) if c.parent_id else None),
            "children": [],
        }

    # Pass 2: roll up descendant counts to parents (depth-first from leaves)
    roots: list[dict[str, Any]] = []
    for c in rows:
        node = by_id[c.id]
        if c.parent_id and c.parent_id in by_id:
            by_id[c.parent_id]["children"].append(node)
        else:
            roots.append(node)

    def rollup(node: dict[str, Any]) -> int:
        own = node.get("direct_count", 0) or 0
        kids = sum(rollup(ch) for ch in node["children"])
        node["product_count"] = own + kids
        return node["product_count"]

    for r in roots:
        rollup(r)

    # Prune dead branches: any category whose rolled-up product_count is 0 is
    # an empty Auto Care taxonomy bucket Titan doesn't carry (Gauges, Trailer
    # Parts, dead Interior leaves like Pet Barriers, etc.). Removing them
    # eliminates "category with no products and no image" links.
    def prune_empty(node: dict[str, Any]) -> bool:
        """Returns True if the node should be kept."""
        node["children"] = [ch for ch in node["children"] if prune_empty(ch)]
        return (node.get("product_count") or 0) > 0
    roots = [r for r in roots if prune_empty(r)]

    tree_cache.set("tree", roots)
    return roots


def _category_product_ids_subq(
    category_top: str | None,
    category_path: str | None,
):
    """Build a scalar subquery yielding product_ids that belong to the given
    category (top name or full path). Matches the resolver in
    `_browse_via_pace` so the attribute facets line up with what the grid
    shows.
    """
    from sqlalchemy.orm import aliased
    from app.models import Category, ProductCategory
    if category_path:
        like_pattern = f"{category_path} > %"
        cat_q = select(Category.id).where(
            (Category.full_path == category_path) | (Category.full_path.like(like_pattern))
        )
    elif category_top:
        anchor = aliased(Category)
        cat_q = (
            select(Category.id)
            .select_from(Category)
            .join(anchor, (Category.id == anchor.id)
                          | (Category.full_path.like(anchor.full_path.op('||')(' > %'))))
            .where(anchor.name == category_top)
            .distinct()
        )
    else:
        return None
    return select(ProductCategory.product_id).where(ProductCategory.category_id.in_(cat_q))


# PIES AttributeID values that are NEVER useful as drill-down facets:
# - Regulatory / compliance disclaimers (Prop 65, Carb, hazmat)
# - PIES taxonomy fields that duplicate our category navigation
# - Identifiers / codes used for lookups, not for filtering
# - Brand / manufacturer (already a separate facet group)
# Stored lowercase so the comparison is case-insensitive.
_ATTR_DENYLIST = {
    # Regulatory / compliance disclaimers — flag, not a filter.
    "california proposition 65",
    "carb compliant",
    "hazardous material",
    "prop 65 warning",
    # Customs / tariff fields — back-office data, not customer-facing.
    "tariff 301 - xa",
    "tariff 301",
    "country of manufacture",
    "harmonized tariff code",
    # PIES taxonomy fields that duplicate our category navigation.
    "subcategory",
    "category",
    # Identifiers — one value per product, useless as a filter.
    "asin",
    "upc",
    "ean",
    "gtin",
    "item number",
    "mfr part number",
    "manufacturer part number",
    "oem part number",
    "part number",
    "part terminology id",
    "part type",
    "sku",
    "title",
    # Already a dedicated facet group on the page.
    "brand",
    "manufacturer",
    # Free text that doesn't filter well.
    "warranty",
    "country of origin",
    "description",
    # Labor / fulfillment fields — back-office data, not a shopping filter
    # (issue #13). "Install time" belongs on the PDP Specs tab and only
    # matters at checkout if the customer elects installation — it should
    # NOT narrow the catalog. The ILIKE guards below catch the ~20 PIES
    # spelling variants ("Avg Install time", "Estimated Install Time", etc.)
    # but the dominant literals are listed here for documentation.
    "install time",
    "installation time",
    "avg install time",
    "estimated install time",
    "ships in multiple boxes",
}

# Substring patterns for attribute keys that are NEVER customer-facing
# filters but ship under many spelling variants — cheaper to match by
# pattern than to enumerate every PIES vendor's wording. Compared against
# lower(attribute_key) with SQL LIKE (so '%' wildcards on both sides).
_ATTR_DENYLIST_PATTERNS = (
    "%install time%",       # Install Time, Avg Install time, Est. Install Time (Hour)...
    "%installation time%",  # Installation Time, Installation Time (hrs)...
    "%ships in multiple box%",  # Ships in Multiple Boxes (back-office fulfillment flag)
)


@router.get("/category-attributes")
async def category_attributes(
    request: Request,
    category_top: str | None = Query(None, description="Top-level category name"),
    category_path: str | None = Query(None, description="Exact full category path"),
    base_vehicle_id: int | None = Query(None, description="Restrict to parts that fit this vehicle"),
    vehicle_type: str | None = Query(None, description="Restrict to parts that fit a vehicle class (e.g. 'Van')"),
    max_keys: int = Query(6, ge=1, le=20, description="Max attribute keys to return"),
    max_values_per_key: int = Query(8, ge=1, le=50, description="Max values per attribute key"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-subcategory PIES attribute facets.

    For products inside the given category (mirrors `_browse_via_pace`'s
    category resolver), aggregate the `product_attribute` rows and return
    the top attribute keys + their top values + counts. Powers the left-rail
    drill-down on the catalog browse page.

    Quality filters:
      - Drop keys whose coverage is < ~3% of the category, OR < 5 products
        (avoids one-off attributes from a single SKU).
      - Drop keys that have only one distinct value across the whole
        category (not useful as a filter).
      - Drop keys with extreme cardinality (>200 distinct values) — those
        tend to be free-text fields, not facetable.

    Returns:
        attributes: ordered list of {key, values: [{value, uom, count}]}
        products_total: total products in the category
        products_with_attributes: count of products that have at least one
            PIES attribute row — telegraphs how complete the cataloging is.
    """
    from sqlalchemy import distinct, func, text
    from app.models import (
        AttributeValueAlias, Brand, PacePart, PaceFitment, Product,
        ProductAttribute, VcdbBaseVehicle, VcdbModel,
    )
    from app.services.attribute_canonical import bucket_by_canonical

    if not (category_top or category_path):
        return {
            "attributes": [],
            "products_total": 0,
            "products_with_attributes": 0,
        }

    # Attribute facets are pure aggregation (no pricing, no per-viewer data)
    # and only change when the PACE/PIES feed is re-ingested, so cache the
    # computed response per (category + vehicle filter + shape) for a few
    # minutes. This is the 10+-query hot path the left-rail drill-down fires
    # on every category page view.
    from app.services.browse_cache import attrs_cache
    attrs_key = (
        "attrs", category_top, category_path, base_vehicle_id, vehicle_type,
        max_keys, max_values_per_key,
    )
    cached = attrs_cache.get(attrs_key)
    if cached is not None:
        return cached

    # Build the same product filter chain that /browse uses (only active,
    # for-sale products under an active brand, optionally vehicle-filtered),
    # scoped to the viewer's channel so facets reflect what they can see.
    channel = await _viewer_channel(db, user, request)
    base_q = (
        select(Product.id)
        .join(Brand, Brand.id == Product.brand_id)
        .where(visible_to_channel_clause(channel), Product.is_for_sale == True,  # noqa: E712
               Brand.is_active == True)  # noqa: E712
    )
    pid_subq = _category_product_ids_subq(category_top, category_path)
    if pid_subq is not None:
        base_q = base_q.where(Product.id.in_(pid_subq))

    if base_vehicle_id is not None:
        fit_ids = (
            select(distinct(PacePart.product_id))
            .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
            .where(PaceFitment.base_vehicle_id == base_vehicle_id,
                   PacePart.product_id.is_not(None))
        )
        base_q = base_q.where(Product.id.in_(fit_ids))

    if vehicle_type:
        from sqlalchemy import or_
        # Mirrors _browse_via_pace: a product surfaces under a vehicle class if
        # it has a fitment to that class OR carries no ACES fitment at all
        # (the indexed Product.has_no_fitment flag collapses the old
        # "no pace_part" + "pace_part-but-no-fitment" catalog-wide scans).
        type_fit_ids = (
            select(distinct(PacePart.product_id))
            .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
            .join(VcdbBaseVehicle, VcdbBaseVehicle.id == PaceFitment.base_vehicle_id)
            .join(VcdbModel, VcdbModel.id == VcdbBaseVehicle.model_id)
            .where(VcdbModel.vehicle_type == vehicle_type,
                   PacePart.product_id.is_not(None))
        )
        base_q = base_q.where(
            or_(
                Product.id.in_(type_fit_ids),
                Product.has_no_fitment == True,  # noqa: E712
            )
        )

    products_total = (await db.execute(
        select(func.count()).select_from(base_q.subquery())
    )).scalar_one()
    if products_total == 0:
        return {
            "attributes": [],
            "products_total": 0,
            "products_with_attributes": 0,
        }

    pid_in_cat = base_q.subquery()
    products_with_attrs = (await db.execute(
        select(func.count(distinct(ProductAttribute.product_id)))
        .where(ProductAttribute.product_id.in_(select(pid_in_cat.c.id)))
    )).scalar_one()

    # Per-key coverage stats. Keep keys that:
    #   - appear on at least 5 products AND at least 3% of the category
    #   - have between 2 and 200 distinct values (filterable, not free-text)
    min_coverage_count = max(5, int(products_total * 0.03))
    # Pull a wider initial slice, then apply the discrimination guard in
    # Python so we don't over-fetch but also don't punt on keys that look
    # like identifiers (n_values ≈ n_products → one value per product).
    raw_rows = (await db.execute(
        select(
            ProductAttribute.attribute_key,
            func.count(distinct(ProductAttribute.product_id)).label("n_products"),
            func.count(distinct(ProductAttribute.attribute_value)).label("n_values"),
        )
        .where(ProductAttribute.product_id.in_(select(pid_in_cat.c.id)))
        .where(ProductAttribute.attribute_value.is_not(None))
        .where(ProductAttribute.attribute_value != "")
        .where(~func.lower(ProductAttribute.attribute_key).in_(_ATTR_DENYLIST))
        # Pattern-deny labor/fulfillment fields with many spelling variants
        # (install time, ships-in-boxes) — see _ATTR_DENYLIST_PATTERNS.
        # Each .where() ANDs, so notlike() every pattern.
        .where(func.lower(ProductAttribute.attribute_key).notlike(_ATTR_DENYLIST_PATTERNS[0]))
        .where(func.lower(ProductAttribute.attribute_key).notlike(_ATTR_DENYLIST_PATTERNS[1]))
        .where(func.lower(ProductAttribute.attribute_key).notlike(_ATTR_DENYLIST_PATTERNS[2]))
        # Drop supplier-specific suffix variants. PIES feeds from some
        # brands ship a parallel "X - XA" / "X - XB" key for every real
        # attribute (tariff bucketing, internal reporting). These dupe
        # the real key with worse data and clutter the rail.
        .where(~ProductAttribute.attribute_key.ilike('% - XA'))
        .where(~ProductAttribute.attribute_key.ilike('% - XB'))
        .where(~ProductAttribute.attribute_key.ilike('% - XC'))
        .group_by(ProductAttribute.attribute_key)
        .having(func.count(distinct(ProductAttribute.product_id)) >= min_coverage_count)
        .having(func.count(distinct(ProductAttribute.attribute_value)).between(2, 200))
        .order_by(func.count(distinct(ProductAttribute.product_id)).desc())
        .limit(max_keys * 3)
    )).all()
    # If n_values / n_products > 0.7 the key is acting like an identifier
    # (mostly-unique values), and a checkbox list won't help the user.
    key_rows = [
        (k, np, nv) for k, np, nv in raw_rows
        if nv / max(np, 1) <= 0.7
    ][:max_keys]

    # Load manual alias overrides for every key we're about to surface,
    # in one round-trip. Curator-confirmed aliases (source='manual') take
    # precedence over the deterministic auto_canonical().
    alias_keys = [k for k, _, _ in key_rows]
    alias_lookup: dict[str, dict[str, str]] = {}
    if alias_keys:
        alias_rows = (await db.execute(
            select(
                AttributeValueAlias.attribute_key,
                AttributeValueAlias.raw_value,
                AttributeValueAlias.canonical_value,
            )
            .where(AttributeValueAlias.attribute_key.in_(alias_keys))
            .where(AttributeValueAlias.source == "manual")
        )).all()
        for k, raw, canonical in alias_rows:
            alias_lookup.setdefault(k, {})[raw] = canonical

    # Load the manual KEY-merge map for the surfaced keys, so synonym keys
    # ("Volume" / "Gallon Capacity") collapse into one facet group. Combined
    # with deterministic label-variant folding ("Overall Length" vs
    # "Overall Length (in.)"), this groups the rail's redundant filters.
    from app.models import AttributeKeyAlias
    from app.services.attribute_key_merge import compute_key_groups, merge_values
    key_merge_map: dict[str, str] = {}
    if alias_keys:
        km_rows = (await db.execute(
            select(AttributeKeyAlias.member_key, AttributeKeyAlias.group_label)
            .where(AttributeKeyAlias.member_key.in_(alias_keys))
        )).all()
        key_merge_map = {m: g for m, g in km_rows}

    stats = {k: (np, nv) for k, np, nv in key_rows}
    groups = compute_key_groups([(k, np) for k, np, _ in key_rows], key_merge_map)

    attributes: list[dict[str, Any]] = []
    for grp in groups:
        if not grp.is_merged:
            key = grp.label  # the lone member
            # Pull more rows than we'll surface so canonicalization (case,
            # punctuation, manual aliases) can fold variants and still have
            # `max_values_per_key` positions left over after collapse.
            raw_value_rows = (await db.execute(
                select(
                    ProductAttribute.attribute_value,
                    ProductAttribute.attribute_uom,
                    func.count(distinct(ProductAttribute.product_id)).label("n"),
                )
                .where(ProductAttribute.product_id.in_(select(pid_in_cat.c.id)))
                .where(ProductAttribute.attribute_key == key)
                .where(ProductAttribute.attribute_value.is_not(None))
                .where(ProductAttribute.attribute_value != "")
                .group_by(ProductAttribute.attribute_value, ProductAttribute.attribute_uom)
                .order_by(func.count(distinct(ProductAttribute.product_id)).desc())
                .limit(max_values_per_key * 4)
            )).all()

            # Bucket by canonical (auto-canonicalize via Title Case + plural-
            # fold + punctuation-aware casing, overridden by any manual alias
            # the curator has confirmed for this key).
            buckets = bucket_by_canonical(
                ((v, uom, n) for v, uom, n in raw_value_rows),
                manual_aliases=alias_lookup.get(key, {}),
            )
            values = [
                {"value": b.canonical, "uom": b.uom, "count": b.count}
                for b in buckets[:max_values_per_key]
            ]
            n_products, n_values = stats.get(key, (0, 0))
            members = None
        else:
            # Merged group: union raw values across every member key, then
            # re-bucket by numeric signature so "100" / "100 Gallon" /
            # "100 Gallons" collapse to one checkbox.
            raw_value_rows = (await db.execute(
                select(
                    ProductAttribute.attribute_value,
                    ProductAttribute.attribute_uom,
                    func.count(distinct(ProductAttribute.product_id)).label("n"),
                )
                .where(ProductAttribute.product_id.in_(select(pid_in_cat.c.id)))
                .where(ProductAttribute.attribute_key.in_(grp.members))
                .where(ProductAttribute.attribute_value.is_not(None))
                .where(ProductAttribute.attribute_value != "")
                .group_by(ProductAttribute.attribute_value, ProductAttribute.attribute_uom)
                .order_by(func.count(distinct(ProductAttribute.product_id)).desc())
                .limit(max_values_per_key * 8)
            )).all()
            merged = merge_values((v, uom, n) for v, uom, n in raw_value_rows)
            values = [
                {"value": mv.label, "uom": mv.uom, "count": mv.count}
                for mv in merged[:max_values_per_key]
            ]
            # Distinct products across all member keys (a product may carry
            # more than one member key — count it once).
            n_products = (await db.execute(
                select(func.count(distinct(ProductAttribute.product_id)))
                .where(ProductAttribute.product_id.in_(select(pid_in_cat.c.id)))
                .where(ProductAttribute.attribute_key.in_(grp.members))
            )).scalar_one()
            n_values = len(merged)
            members = grp.members

        if not values:
            continue
        attr: dict[str, Any] = {
            "key": grp.label,
            "products_with_key": int(n_products),
            "distinct_values": int(n_values),
            "values": values,
        }
        if members:
            attr["merged_from"] = members
        attributes.append(attr)

    result = {
        "attributes": attributes,
        "products_total": int(products_total),
        "products_with_attributes": int(products_with_attrs),
    }
    attrs_cache.set(attrs_key, result)
    return result


@router.get("/category/{slug}")
async def category_detail(slug: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Look up a category by leaf slug for landing pages.  Returns the category
    + immediate children + breadcrumb (parent chain) + image_url per node.
    Use the slug as it appears in `Category.slug`; ambiguous slugs return the
    first match.
    """
    from sqlalchemy import text
    from app.models import Category
    cat = (await db.execute(
        select(Category).where(Category.slug == slug).order_by(Category.depth)
    )).scalars().first()
    if cat is None:
        raise HTTPException(status_code=404, detail=f"Category not found: {slug}")

    children_rows = (await db.execute(
        select(Category).where(Category.parent_id == cat.id).order_by(Category.name)
    )).scalars().all()

    # Per-category representative image with the same tiered preference order
    # used by /categories/tree (name-match → own-direct → descendants → brand
    # logo). Tier 0 (name-match) prevents "Mud Guards and Mud Flaps" from
    # picking a heat shield just because it was the newest import.
    cat_ids = [cat.id] + [c.id for c in children_rows]
    img_rows = (await db.execute(text("""
        WITH RECURSIVE descendants AS (
          SELECT id AS root_id, id AS desc_id FROM category WHERE id = ANY(:cat_ids)
          UNION ALL
          SELECT d.root_id, c.id FROM category c JOIN descendants d ON c.parent_id = d.desc_id
        ),
        cat_keywords AS (
          SELECT id AS cat_id, LOWER(word) AS word
          FROM (
            SELECT c.id, regexp_split_to_table(
              regexp_replace(c.name, ' and Accessories$', '', 'i'),
              ' '
            ) AS word
            FROM category c WHERE c.id = ANY(:cat_ids)
          ) x
          WHERE LOWER(word) NOT IN
            ('and','or','the','of','a','an','for','with','to','accessories',
             'replacement','part','parts','kit','kits','&')
            AND LENGTH(word) >= 4
        ),
        cat_stocked AS (
          SELECT DISTINCT ON (pc.category_id) pc.category_id AS root_id, pi.url
          FROM product_category pc
          JOIN product p ON p.id = pc.product_id
          JOIN product_image pi ON pi.product_id = p.id
          JOIN (
            SELECT product_id, SUM(on_hand) AS total
            FROM product_inventory GROUP BY product_id HAVING SUM(on_hand) > 0
          ) inv ON inv.product_id = p.id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            AND pc.category_id = ANY(:cat_ids)
          ORDER BY pc.category_id, inv.total DESC, pi.id DESC
        ),
        cat_topseller AS (
          SELECT DISTINCT ON (pc.category_id) pc.category_id AS root_id, pi.url
          FROM product_category pc
          JOIN product p ON p.id = pc.product_id
          JOIN product_image pi ON pi.product_id = p.id
          JOIN (
            SELECT product_id, SUM(quantity) AS sold FROM order_line
            WHERE created_at >= NOW() - INTERVAL '365 days'
            GROUP BY product_id
          ) sales ON sales.product_id = p.id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            AND sales.sold > 0
            AND pc.category_id = ANY(:cat_ids)
          ORDER BY pc.category_id, sales.sold DESC, pi.id DESC
        ),
        cat_namematch AS (
          SELECT DISTINCT ON (pc.category_id) pc.category_id AS root_id, pi.url
          FROM product_category pc
          JOIN product p ON p.id = pc.product_id
          JOIN product_image pi ON pi.product_id = p.id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            -- Trusted image sources only (aam-files + titantruck.com/images
            -- + locally-hosted /static); excludes random manufacturer-direct
            -- URLs that had cert issues (curtmfg.com / dometic.com / etc.)
            AND (
              pi.url LIKE 'http://storage.googleapis.com/aam-files/%'
              OR pi.url LIKE 'https://www.titantruck.com/images/%'
              OR pi.url LIKE '/static/%'
            )
            AND EXISTS (
              SELECT 1 FROM cat_keywords ck
              WHERE ck.cat_id = pc.category_id
                AND LOWER(p.name) LIKE '%' || ck.word || '%'
            )
          ORDER BY pc.category_id, pi.id DESC
        ),
        cat_own AS (
          SELECT DISTINCT ON (pc.category_id) pc.category_id AS root_id, pi.url
          FROM product_category pc
          JOIN product_image pi ON pi.product_id = pc.product_id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            AND pc.category_id = ANY(:cat_ids)
          ORDER BY pc.category_id, pi.id DESC
        ),
        cat_desc AS (
          SELECT DISTINCT ON (d.root_id) d.root_id, pi.url
          FROM descendants d
          JOIN product_category pc ON pc.category_id = d.desc_id
          JOIN product_image pi ON pi.product_id = pc.product_id
          WHERE pi.is_primary = true AND pi.url IS NOT NULL AND pi.url <> ''
            AND d.root_id <> d.desc_id
          ORDER BY d.root_id, pi.id DESC
        ),
        cat_logo AS (
          SELECT DISTINCT ON (d.root_id) d.root_id, b.logo_url AS url
          FROM descendants d
          JOIN product_category pc ON pc.category_id = d.desc_id
          JOIN product p ON p.id = pc.product_id
          JOIN brand b ON b.id = p.brand_id
          WHERE b.logo_url IS NOT NULL AND b.logo_url <> ''
          ORDER BY d.root_id, b.id
        )
        SELECT c.id,
               COALESCE(c.curated_image_url, cs.url, ct.url, cn.url, co.url, cd.url, cl.url) AS image_url
        FROM category c
        LEFT JOIN cat_stocked   cs ON cs.root_id = c.id
        LEFT JOIN cat_topseller ct ON ct.root_id = c.id
        LEFT JOIN cat_namematch cn ON cn.root_id = c.id
        LEFT JOIN cat_own       co ON co.root_id = c.id
        LEFT JOIN cat_desc      cd ON cd.root_id = c.id
        LEFT JOIN cat_logo      cl ON cl.root_id = c.id
        WHERE c.id = ANY(:cat_ids)
    """), {"cat_ids": cat_ids})).all()
    image_by_cat = {cid: url for cid, url in img_rows if url}

    # Per-child product count (rolled-up across descendants) so we can hide
    # dead taxonomy buckets that have no Titan inventory.
    count_rows = (await db.execute(text("""
        WITH RECURSIVE descendants AS (
          SELECT id AS root_id, id AS desc_id FROM category WHERE id = ANY(:cat_ids)
          UNION ALL
          SELECT d.root_id, c.id FROM category c JOIN descendants d ON c.parent_id = d.desc_id
        )
        SELECT d.root_id, COUNT(DISTINCT pc.product_id) AS n
        FROM descendants d
        LEFT JOIN product_category pc ON pc.category_id = d.desc_id
        GROUP BY d.root_id
    """), {"cat_ids": cat_ids})).all()
    count_by_cat = {cid: int(n or 0) for cid, n in count_rows}

    # Build breadcrumb by walking parent chain
    breadcrumb: list[dict[str, Any]] = []
    cursor: Category | None = cat
    parent_chain: list[Category] = []
    while cursor is not None:
        breadcrumb.append({"name": cursor.name, "slug": cursor.slug, "full_path": cursor.full_path})
        parent_chain.append(cursor)
        if cursor.parent_id is None:
            break
        cursor = (await db.execute(select(Category).where(Category.id == cursor.parent_id))).scalar_one_or_none()
    breadcrumb.reverse()

    # For inheritance fallback, look up parent's images too if needed
    if cat.id not in image_by_cat and cat.parent_id:
        # Walk up the chain — at most 2-3 hops in our tree
        for ancestor in parent_chain[1:]:
            if ancestor.id in image_by_cat:
                image_by_cat[cat.id] = image_by_cat[ancestor.id]
                break
            # Could fetch ancestor's image_url separately if not in our scope
    # Children use the parent's image as a LAST-resort fallback if their own
    # tier chain returned nothing. Empty taxonomy buckets (0 rolled-up products)
    # are pruned so we never render a link that goes to a dead page.
    children_payload = []
    for c in children_rows:
        n = count_by_cat.get(c.id, 0)
        if n <= 0:
            continue  # skip dead Auto Care taxonomy leaves
        children_payload.append({
            "id": c.id, "name": c.name, "slug": c.slug, "full_path": c.full_path,
            "image_url": image_by_cat.get(c.id) or image_by_cat.get(cat.id),
            "product_count": n,
        })

    # Hide dead-end categories: if THIS category has no rolled-up products and
    # also has no live children, treat it as gone (404).  The tree endpoint
    # already prunes empty branches, but a direct URL to e.g. /categories/data-loggers
    # would otherwise render an empty page with breadcrumb + no content.
    own_count = count_by_cat.get(cat.id, 0)
    if own_count == 0 and len(children_payload) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Category '{cat.full_path}' has no products in the Titan catalog",
        )

    return {
        "id": cat.id,
        "name": cat.name,
        "slug": cat.slug,
        "full_path": cat.full_path,
        "depth": cat.depth,
        "image_url": image_by_cat.get(cat.id),
        "breadcrumb": breadcrumb,
        "children": children_payload,
        "product_count": own_count,
    }


# Lowercased {make_names}, {model_names} from the real VCDB tables, loaded once
# per process. Used to strip Year/Make/Model tokens out of an autocomplete query
# before the Category/Brand DB counts run (see _residual_keyword_tokens). The
# sets only change on a PACE re-ingest, which ships with a backend restart, so a
# process-lifetime cache is safe.
_YMM_NAME_SETS: tuple[set[str], set[str]] | None = None


async def _ymm_name_sets(db: AsyncSession) -> tuple[set[str], set[str]]:
    global _YMM_NAME_SETS
    if _YMM_NAME_SETS is not None:
        return _YMM_NAME_SETS
    from app.models import VcdbMake, VcdbModel
    makes = {
        n.lower()
        for (n,) in (await db.execute(select(VcdbMake.name).where(VcdbMake.name != "UNKNOWN"))).all()
    }
    models = {
        n.lower()
        for (n,) in (await db.execute(select(VcdbModel.name).where(VcdbModel.name != "UNKNOWN"))).all()
    }
    _YMM_NAME_SETS = (makes, models)
    return _YMM_NAME_SETS


async def _residual_keyword_tokens(db: AsyncSession, q: str) -> list[str]:
    """Drop Year/Make/Model tokens from an autocomplete query, returning just the
    part-type keyword(s).

    Why: the Categories/Brands columns count products whose sku/name/brand text
    matches EVERY token (AND). A query like "2021 Ford F-150 tonneau" carries
    fitment tokens ("2021", "Ford", "F-150") that never appear in a part's
    name/sku/brand text, so requiring them zeroes out every match — the columns
    came back empty even though "tonneau" obviously maps to Tonneau covers + BAK/
    Truxedo/UnderCover. (The Parts column dodges this because it goes through
    Typesense, which ranks rather than AND-filters.) Stripping the recognized
    Y/M/M tokens leaves "tonneau" to drive the counts.

    Conservative: a token is only dropped if it's a 4-digit year or part of a
    make/model name match. If stripping would remove EVERYTHING (a pure-vehicle
    query with no part keyword), the original tokens are returned so behavior is
    unchanged from before.
    """
    import re
    makes, models = await _ymm_name_sets(db)
    raw = [t for t in q.strip().split() if t]
    # Years first — anything 1900-2099 is a model year, never part text.
    toks = [t for t in raw if not re.fullmatch(r"(19|20)\d{2}", t)]
    n = len(toks)
    lower = [t.lower() for t in toks]
    drop = [False] * n
    # Match make/model names as contiguous n-grams, longest first so a multi-word
    # model ("F-250 Super Duty") is consumed whole before its leading word alone.
    for size in (4, 3, 2, 1):
        for i in range(0, n - size + 1):
            if any(drop[i:i + size]):
                continue
            phrase = " ".join(lower[i:i + size])
            if phrase in makes or phrase in models:
                for j in range(i, i + size):
                    drop[j] = True
    residual = [toks[i] for i in range(n) if not drop[i]]
    # Non-empty residual → the keyword(s) the customer actually wants binned.
    # Empty residual → pure Y/M/M; fall back to the raw query (no regression).
    return residual or raw or [q]


async def _autocomplete_db_counts(
    db: AsyncSession, q: str, category_top: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compute the dropdown's category + brand counts from the DB so they match
    the landing page exactly.

    The catalog page counts products via Postgres ILIKE on the raw sku/name
    (punctuation intact), but Typesense facet counts come from infix matching
    that strips '.'/'-' (so "440" matches inside "82904.40"). That made the
    dropdown chip (e.g. "Floor Mats (629)") overcount vs the page it lands on
    (609). We recompute counts here with the SAME predicate the page uses:
    AND each whitespace token across (sku OR name OR brand name), active +
    sellable only, then roll each match up to every ancestor category path
    (mirroring Typesense's category_paths array) and group.

    Fast (~60ms) thanks to the pg_trgm GIN indexes on product.sku / .name
    (ix_product_sku_trgm / ix_product_name_trgm). Match-first (CTE) then join
    the category tree keeps the working set tiny.
    """
    from sqlalchemy import and_, distinct, func as _func, or_ as _or
    from sqlalchemy.orm import aliased
    from app.models import Category, ProductCategory

    # Strip Year/Make/Model tokens so a "<vehicle> <keyword>" query bins by the
    # keyword. Without this, the AND-all-tokens predicate below required a part's
    # text to literally contain "2021"/"Ford"/"F-150" and returned nothing.
    tokens = await _residual_keyword_tokens(db, q)
    matched = (
        select(Product.id.label("pid"))
        .join(Brand, Brand.id == Product.brand_id)
        .where(
            Product.is_hidden == False,  # noqa: E712
            Product.is_for_sale == True,  # noqa: E712
            Brand.is_active == True,  # noqa: E712
            and_(*[
                _or(
                    Product.sku.ilike(f"%{t}%"),
                    Product.name.ilike(f"%{t}%"),
                    Brand.name.ilike(f"%{t}%"),
                )
                for t in tokens
            ]),
        )
    )
    # Showroom Mode / category-scoped search: only count products inside the
    # given top-level category subtree, so the Categories + Brands columns can't
    # leak items outside "Truck Accessories".
    if category_top:
        _cat_ids = select(Category.id).where(
            (Category.full_path == category_top) | (Category.full_path.like(f"{category_top} > %"))
        )
        matched = matched.where(
            Product.id.in_(select(ProductCategory.product_id).where(ProductCategory.category_id.in_(_cat_ids)))
        )
    m = matched.subquery()

    # Categories: roll each matched product up to EVERY ancestor full_path so a
    # match deep in the tree also counts toward its parent shelves, exactly like
    # Typesense's multi-value category_paths. Keep only deep paths (with " > ").
    leaf = aliased(Category)
    anc = aliased(Category)
    cat_stmt = (
        select(anc.full_path, _func.count(distinct(m.c.pid)).label("cnt"))
        .select_from(m)
        .join(ProductCategory, ProductCategory.product_id == m.c.pid)
        .join(leaf, leaf.id == ProductCategory.category_id)
        .join(anc, _or(leaf.full_path == anc.full_path,
                       leaf.full_path.like(anc.full_path.op("||")(" > %"))))
        .where(anc.full_path.like("% > %"))
        .group_by(anc.full_path)
    )
    if category_top:
        # Only suggest subcategories within the scoped top-level category.
        cat_stmt = cat_stmt.where(anc.full_path.like(f"{category_top} > %"))
    cat_rows = (await db.execute(cat_stmt)).all()
    # Deepest first (most specific shelf), then highest q-match count — this
    # picks WHICH categories to suggest (relevance to the typed query).
    cat_rows = sorted(cat_rows, key=lambda r: (r.full_path.count(">"), r.cnt), reverse=True)
    cand_paths = [r.full_path for r in cat_rows][:8]

    # A category chip is a "browse this category" click and lands on the
    # category's FULL page (the frontend drops q on category click — see
    # pickCategory), so the chip count must be the full category size, not the
    # q-filtered count. Roll every active/sellable product up to each candidate
    # ancestor path and count distinct products (category + descendants).
    full_counts: dict[str, int] = {}
    if cand_paths:
        fleaf = aliased(Category)
        fanc = aliased(Category)
        full_stmt = (
            select(fanc.full_path, _func.count(distinct(ProductCategory.product_id)).label("cnt"))
            .select_from(ProductCategory)
            .join(Product, Product.id == ProductCategory.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .join(fleaf, fleaf.id == ProductCategory.category_id)
            .join(fanc, _or(fleaf.full_path == fanc.full_path,
                            fleaf.full_path.like(fanc.full_path.op("||")(" > %"))))
            .where(
                Product.is_hidden == False,  # noqa: E712
                Product.is_for_sale == True,  # noqa: E712
                Brand.is_active == True,  # noqa: E712
                fanc.full_path.in_(cand_paths),
            )
            .group_by(fanc.full_path)
        )
        full_counts = {fp: cnt for fp, cnt in (await db.execute(full_stmt)).all()}
    categories = [
        {"name": fp.rsplit(">", 1)[-1].strip(), "path": fp, "count": full_counts.get(fp, 0)}
        for fp in cand_paths
    ]

    brand_stmt = (
        select(Brand.name, _func.count(distinct(m.c.pid)).label("cnt"))
        .select_from(m)
        .join(Product, Product.id == m.c.pid)
        .join(Brand, Brand.id == Product.brand_id)
        .group_by(Brand.name)
        .order_by(_func.count(distinct(m.c.pid)).desc(), Brand.name)
        .limit(8)
    )
    brand_rows = (await db.execute(brand_stmt)).all()
    brands = [{"name": n, "count": cnt} for n, cnt in brand_rows]
    return categories, brands


@router.get("/autocomplete")
async def autocomplete(
    response: Response,
    request: Request,
    q: str = Query(min_length=1, max_length=80),
    parts_limit: int = Query(8, ge=1, le=30),
    category_top: str | None = Query(None, description="Scope results to a top-level category (e.g. Retail Showroom Mode locks search to 'Truck Accessories')"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Quick-search dropdown: returns 3 columns — Parts, Categories, Brands.

    Mirrors the PACE/AAM-Pro autocomplete pattern. Tries Typesense first
    (full-text, ranked); falls back to a DB-direct ILIKE search when
    Typesense is down (Phase 0 environments + reachability blips). The
    fallback isn't ranked the same way but it keeps the search bar
    functional, which is more important than perfect ranking.
    """
    # Never cache the dropdown — counts/results must always reflect the live
    # catalog (a stale browser-cached response showed old category counts).
    response.headers["Cache-Control"] = "no-store"
    try:
        # Autocomplete-specific tuning:
        #   - sort by text-match relevance first (the user typed something
        #     specific — likely a part number), THEN stock as a tiebreaker.
        #   - infix=always on the SKU field — Typesense doesn't split SKU
        #     "SNOW-16160700A" on the `-` under default tokenization, so a
        #     bare "16160700A" query can't prefix-match the single SKU
        #     token. Infix bridges that gap.
        #
        # Part-number-style queries (alphanumeric, no spaces, has digits)
        # get TWO searches: first an SKU-only infix query so exact-SKU
        # hits surface at the top, then a broader cross-field search to
        # fill in narrative-text matches. Without the split, Typesense's
        # `_text_match` rewards exact-token name matches above infix-SKU
        # matches and the exact part lands below sibling part mentions.
        import re as _re
        # >=3 so 3-char numeric SKU substrings ("443") get infix SKU matching
        # in the autocomplete too — matches the /browse threshold above.
        looks_like_part_number = (
            len(q) >= 3
            and " " not in q
            and bool(_re.search(r"\d", q))
            and bool(_re.match(r"^[A-Za-z0-9._/\-]+$", q))
        )
        parts: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        channel = await _viewer_channel(db, user, request)
        if looks_like_part_number:
            try:
                sku_resp = search_products(
                    query=q, per_page=parts_limit,
                    query_by="sku",
                    sort_by="_text_match:desc,stock_score:desc",
                    infix="always",
                    channel=channel,
                    category_top=category_top,
                )
                for h in sku_resp.get("hits", []):
                    pid = int(h["document"]["id"])
                    if pid in seen_ids: continue
                    seen_ids.add(pid)
                    parts.append({
                        "id": pid,
                        "sku": h["document"]["sku"],
                        "name": h["document"]["name"],
                        "brand": h["document"].get("brand_name"),
                        "image_url": None,
                        "in_stock": h["document"].get("in_stock", False),
                    })
            except Exception:
                pass
        # Broader cross-field search. Owner ask 2026-05-17: in-stock items
        # should surface ahead of OOS in the autocomplete dropdown for
        # name/keyword queries like "floorliner" (where every WeatherTech
        # hit ties on text match). The looks_like_part_number SKU-only
        # search above already pinned exact part-number hits to the top
        # using text-match relevance, so this broader pass is free to
        # optimize for stock. Matches the /browse default ordering.
        response = search_products(
            query=q, per_page=parts_limit,
            sort_by="stock_score:desc,_text_match:desc",
            infix="always",
            channel=channel,
            category_top=category_top,
            # Facet on category_paths so the dropdown can show
            # subcategories ("Truck Accessories > Automotive Lighting >
            # Emergency and Warning Lighting") instead of bare top-level
            # parents ("Truck Accessories"). Owner ask 2026-05-17 — bare
            # "Truck Accessories" for an "emergency" query isn't useful;
            # the customer wants to land in the specific subcategory.
            facet_by="brand_name,category_paths",
        )
        def _image_or_none(url: str | None) -> str | None:
            if not url or "photocomingsoon" in url.lower():
                return None
            return url
        # Decorate the SKU-first hits already in `parts` with the same
        # image-fallback, then top up with broader-search hits we haven't
        # already seen. `seen_ids` dedupes across the two queries.
        for p in parts:
            # No image_url set on the SKU-first hits — pull from the
            # broader response if available.
            for h in response.get("hits", []):
                if int(h["document"]["id"]) == p["id"]:
                    p["image_url"] = _image_or_none(h["document"].get("image_url"))
                    break
        for h in response.get("hits", []):
            pid = int(h["document"]["id"])
            if pid in seen_ids:
                continue
            if len(parts) >= parts_limit:
                break
            seen_ids.add(pid)
            parts.append({
                "id": pid,
                "sku": h["document"]["sku"],
                "name": h["document"]["name"],
                "brand": h["document"].get("brand_name"),
                "image_url": _image_or_none(h["document"].get("image_url")),
                "in_stock": h["document"].get("in_stock", False),
            })
        facets = {fc["field_name"]: fc.get("counts", []) for fc in response.get("facet_counts", [])}
        # category_paths is the multi-value array of every ancestor. Drop
        # top-level paths (no ">") and surface the deepest matches so the
        # dropdown points the customer at a specific shelf, not the whole
        # department. Owner ask 2026-05-17.
        #
        # Typesense stores paths joined with bare ">" but the DB stores
        # them with " > " (spaces around the separator) — the /browse
        # PACE path matches Category.full_path == category_path EXACTLY,
        # so we have to normalize to the DB format here or the click
        # lands on a 0-results page.
        def _normalize_path(v: str) -> str:
            parts = [p.strip() for p in v.split(">") if p.strip()]
            return " > ".join(parts)

        # Category + brand COUNTS come from the DB (not Typesense facets) so the
        # chip count equals the catalog page the click lands on. Typesense infix
        # strips punctuation (so "440" matches inside "82904.40"), the page's
        # ILIKE does not — that mismatch overcounted the chips. _normalize_path
        # / facets.category_paths are no longer used for counts.
        categories, brands = await _autocomplete_db_counts(db, q, category_top)
        return {
            "query": q,
            "parts": parts,
            "categories": categories,
            "brands": brands,
            "found": response.get("found", 0),
            "search_time_ms": response.get("search_time_ms", 0),
        }
    except Exception:
        # Typesense unreachable. Drop to DB ILIKE (scoped to the viewer channel).
        _ch = await _viewer_channel(db, user, request)
        return await _autocomplete_db_fallback(db, q, parts_limit, category_top, channel=_ch)


async def _autocomplete_db_fallback(
    db: AsyncSession, q: str, parts_limit: int, category_top: str | None = None,
    channel: str = "retail",
) -> dict[str, Any]:
    """ILIKE-based fallback when Typesense is down. Matches against SKU,
    product name, and brand name. Categories + Brands are derived from
    the matching product set. `category_top` scopes everything to one
    top-level category subtree (Retail Showroom Mode). `channel` scopes to the
    viewer's per-channel visibility."""
    from sqlalchemy import and_, func, or_, text as sa_text
    from app.models import Category, ProductImage, ProductCategory
    # Strip Year/Make/Model tokens (same rationale as the Typesense path) so a
    # "<vehicle> <keyword>" query matches on the keyword instead of demanding a
    # part's text contain the year/make/model literally.
    tokens = await _residual_keyword_tokens(db, q)
    # Showroom Mode subtree gate, reused across parts / categories / brands.
    _subtree_pids = None
    if category_top:
        _cat_ids = select(Category.id).where(
            (Category.full_path == category_top) | (Category.full_path.like(f"{category_top} > %"))
        )
        _subtree_pids = select(ProductCategory.product_id).where(ProductCategory.category_id.in_(_cat_ids))
    # Step 1: top N matching products. AND every token across (sku OR
    # product name OR brand name). Sort by prefix match on the FIRST token
    # so a search for "warn 12000" still ranks SKUs starting with "warn".
    first = tokens[0]
    token_clauses = [
        or_(
            Product.sku.ilike(f"%{t}%"),
            Product.name.ilike(f"%{t}%"),
            Brand.name.ilike(f"%{t}%"),
        )
        for t in tokens
    ]
    parts_q = (
        select(Product, Brand)
        .join(Brand, Brand.id == Product.brand_id)
        .where(
            visible_to_channel_clause(channel),
            Product.is_for_sale == True,  # noqa: E712
            Brand.is_active == True,  # noqa: E712
            and_(*token_clauses),
        )
        .order_by(
            (Product.sku.ilike(f"{first}%")).desc(),
            (Product.name.ilike(f"{first}%")).desc(),
            Product.name,
        )
        .limit(parts_limit)
    )
    if _subtree_pids is not None:
        parts_q = parts_q.where(Product.id.in_(_subtree_pids))
    rows = (await db.execute(parts_q)).all()
    # Resolve primary images for hits
    pids = [p.id for p, _ in rows]
    images: dict[int, str] = {}
    if pids:
        img_rows = (await db.execute(
            select(ProductImage.product_id, ProductImage.url)
            .where(ProductImage.product_id.in_(pids), ProductImage.is_primary == True)  # noqa: E712
        )).all()
        images = {pid: url for pid, url in img_rows}
    parts = [
        {
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "brand": b.name,
            "image_url": images.get(p.id),
            "in_stock": False,  # no inventory load yet
        }
        for p, b in rows
    ]
    # Step 2: top-N matching categories by name.  `pattern` is the ILIKE
    # wildcarded version of the first token — full-string match on `q` would
    # miss multi-word queries like "v plow" / "tow hitch".
    pattern = f"%{first}%"
    cat_q = (
        select(Category.name, Category.full_path)
        .where(Category.is_active == True, Category.name.ilike(pattern))  # noqa: E712
        .order_by((Category.name.ilike(f"{q}%")).desc(), Category.name)
        .limit(8)
    )
    if category_top:
        cat_q = cat_q.where(Category.full_path.like(f"{category_top} > %"))
    cat_rows = (await db.execute(cat_q)).all()
    categories = [{"name": n, "count": 0, "full_path": fp} for n, fp in cat_rows]
    # Step 3: matching brands
    brand_q = (
        select(Brand.name)
        .where(Brand.is_active == True, Brand.name.ilike(pattern))  # noqa: E712
        .order_by((Brand.name.ilike(f"{q}%")).desc(), Brand.name)
        .limit(8)
    )
    if _subtree_pids is not None:
        # Only brands that actually have a product in the scoped subtree.
        brand_q = brand_q.where(Brand.id.in_(
            select(Product.brand_id).where(Product.id.in_(_subtree_pids))
        ))
    brand_rows = (await db.execute(brand_q)).all()
    brands = [{"name": n, "count": 0} for n, in brand_rows]
    return {
        "query": q,
        "parts": parts,
        "categories": categories,
        "brands": brands,
        "found": len(parts),
        "search_time_ms": 0,
        "_source": "db_fallback",
    }


@router.get("/products/{sku}/fitments")
async def product_fitments(
    sku: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the vehicles a product fits, grouped by make + model with
    year ranges. Used by the PDP Fitment tab.

    For products with NO fitment rows (universal kits / winches / etc.)
    returns {"universal": True, "groups": []}."""
    from sqlalchemy import text as sa_text
    product = (await db.execute(
        select(Product.id, Product.name).where(Product.sku == sku)
    )).first()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product not found: {sku}")

    rows = (await db.execute(sa_text("""
        SELECT m.name AS make_name, mo.name AS model_name,
               MIN(bv.year) AS y_start, MAX(bv.year) AS y_end, COUNT(*) AS fits
        FROM pace_part pp
        JOIN pace_fitment f ON f.pace_part_id = pp.id
        JOIN vcdb_base_vehicle bv ON bv.id = f.base_vehicle_id
        JOIN vcdb_make m ON m.id = bv.make_id
        JOIN vcdb_model mo ON mo.id = bv.model_id
        WHERE pp.product_id = :pid
          AND m.name <> 'UNKNOWN'
        GROUP BY m.name, mo.name
        ORDER BY m.name, mo.name
    """), {"pid": product.id})).all()

    groups: dict[str, list[dict[str, Any]]] = {}
    total_models = 0
    for make_name, model_name, y_start, y_end, fits in rows:
        groups.setdefault(make_name, []).append({
            "model": model_name,
            "year_start": int(y_start) if y_start else None,
            "year_end": int(y_end) if y_end else None,
            "fitment_count": int(fits),
        })
        total_models += 1

    return {
        "sku": sku,
        "universal": len(groups) == 0,
        "make_count": len(groups),
        "model_count": total_models,
        "groups": [
            {"make": make, "models": models}
            for make, models in groups.items()
        ],
    }


@router.get("/hot-products")
async def hot_products(
    request: Request,
    limit: int = Query(8, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Pick "hot" products for the home-page widget.

    Phase 1 heuristic: in-stock + has an image + sorted by stock_score.
    Phase 1.5 will replace with order-velocity-based ranking.

    Tries Typesense first. When it's down, falls back to a DB query that
    picks products with images, ordered by featured-brand-first so the
    widget shows recognizable hero brands (CURT, WeatherTech, ARB...).
    """
    # Scope to the viewer's channel so a product hidden from them never shows.
    channel = await _viewer_channel(db, user, request)
    pool_size = min(100, max(limit * 8, 24))
    try:
        response = search_products(query=None, in_stock_only=True, per_page=pool_size, channel=channel)
        out: list[dict[str, Any]] = []
        for h in response.get("hits", []):
            doc = h["document"]
            if not doc.get("image_url"):
                continue
            out.append({
                "sku": doc["sku"],
                "name": doc["name"],
                "brand": doc.get("brand_name"),
                "image_url": doc["image_url"],
                "in_stock": doc.get("in_stock", False),
                "stock_total": doc.get("stock_total", 0),
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        # Typesense down — DB-direct picks. Use a window function to pick
        # the top product per brand (by id DESC) so the rail shows ONE
        # product per featured brand (variety > recency-bias).
        from sqlalchemy import text as sa_text
        _hcol = hidden_col_name(channel)  # safe identifier (validated channel)
        rows = (await db.execute(sa_text(f"""
          WITH ranked AS (
            SELECT p.id, p.sku, p.name, b.name AS brand_name, pi.url,
                   ROW_NUMBER() OVER (PARTITION BY b.id ORDER BY p.id DESC) AS rn,
                   b.is_featured, b.sort_order
            FROM product p
            JOIN brand b ON b.id = p.brand_id
            JOIN product_image pi ON pi.product_id = p.id AND pi.is_primary
            WHERE p.{_hcol} = false AND p.is_for_sale = true
              AND b.is_active = true
              AND pi.url LIKE 'http%'
          )
          SELECT id, sku, name, brand_name, url FROM ranked
          WHERE rn = 1
          ORDER BY is_featured DESC, sort_order, brand_name
          LIMIT :limit
        """), {"limit": limit})).all()
        return [
            {
                "sku": r.sku,
                "name": r.name,
                "brand": r.brand_name,
                "image_url": r.url,
                "in_stock": False,
                "stock_total": 0,
            }
            for r in rows
        ]


@router.get("/snow-weather")
async def snow_weather() -> dict[str, Any]:
    """7-day NWS forecast for both Titan locations (Spokane + Boise).

    Powers the winter weather widget on /snow-plows.  Frontend gates by
    current month (Oct-Apr) so this endpoint is fine to keep available
    year-round; off-season the widget just doesn't render.

    Returns: {locations: [{key, name, headline, periods: [...]}, ...]}
    Each period is enriched with a `snow_risk` tier (snow / wintry / cold /
    none) for highlighting actionable days.
    """
    from app.services.weather_service import fetch_all_locations
    try:
        locations = await fetch_all_locations()
        return {"ok": True, "locations": locations}
    except Exception as e:
        # Don't break the snow page if NWS is down — return empty + error msg
        return {"ok": False, "error": str(e), "locations": []}


@router.get("/snow-plow-models")
async def snow_plow_models(
    family: str | None = Query(None, description="Filter by family: straight_blade / v_plow / winged"),
    brand: str | None = Query(None, description="Filter by brand: Western / Meyer / SnowDogg"),
    truck_class: str | None = Query(None, description="Filter to plows that fit a truck class (1500/2500/3500/etc.)"),
) -> list[dict[str, Any]]:
    """List the curated snow plow model catalog for the comparison picker."""
    from app.services.snow_plow_catalog import list_models, model_to_dict
    out = []
    for m in list_models():
        if family and m.family != family: continue
        if brand and m.brand.lower() != brand.lower(): continue
        if truck_class and truck_class not in m.truck_classes: continue
        out.append(model_to_dict(m))
    # Sort by snow_belt_rank ascending then brand+model
    out.sort(key=lambda d: (d.get("snow_belt_rank") or 99, d["brand"], d["model"]))
    return out


@router.get("/snow-plow-models/recommend")
async def snow_plow_recommend(
    truck_class: str = Query(..., description="mid-size / 1500 / 2500 / 3500 / 4500 / 5500"),
    route_type: str = Query(..., description="residential / mixed_commercial / lots / municipal"),
    budget: str = Query("any", description="under_5k / 5k_8k / 8k_12k / over_12k / any"),
    limit: int = Query(3, ge=1, le=6),
) -> dict[str, Any]:
    """Recommend up to N plows from the curated catalog for this buyer.

    Driven by truck-class + route-type + budget.  Returns matches with a
    score and per-plow reasoning so the wizard UI can explain the pick.
    """
    from app.services.snow_plow_recommender import recommend_plows, result_to_dict
    try:
        result = recommend_plows(
            truck_class=truck_class,
            route_type=route_type,
            budget=budget,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "truck_class": truck_class,
        "route_type": route_type,
        "budget": budget,
        **result_to_dict(result),
    }


@router.get("/snow-plow-models/compare")
async def snow_plow_compare(ids: str = Query(..., description="Comma-separated model ids")) -> dict[str, Any]:
    """Side-by-side comparison payload for selected plow models.

    Returns each selected model's full spec dict plus a `differences` map so
    the UI can highlight rows where models disagree (e.g., one is electric,
    another is hydraulic).
    """
    from app.services.snow_plow_catalog import get_model, model_to_dict
    selected_ids = [s.strip() for s in ids.split(",") if s.strip()]
    if not selected_ids:
        raise HTTPException(status_code=400, detail="ids parameter is empty")
    if len(selected_ids) > 4:
        raise HTTPException(status_code=400, detail="Compare at most 4 models at a time")
    models = []
    for sid in selected_ids:
        m = get_model(sid)
        if m is None:
            raise HTTPException(status_code=404, detail=f"Unknown model id: {sid}")
        models.append(model_to_dict(m))

    # Compute attribute-level "all match" flags so the UI can dim shared-row
    # values and highlight the differences.
    if len(models) > 1:
        keys_to_compare = [
            "family_label", "blade_widths_in", "blade_height_in", "weight_lb",
            "cutting_edge", "moldboard", "mount", "hydraulics", "control",
            "truck_classes",
        ]
        all_match: dict[str, bool] = {}
        for k in keys_to_compare:
            values = [str(m.get(k)) for m in models]
            all_match[k] = len(set(values)) == 1
    else:
        all_match = {}

    return {
        "models": models,
        "all_match": all_match,
    }


@router.get("/snow-plows-landing")
async def snow_plows_landing(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """One-shot payload for the /snow-plows landing page.

    Bundles the data the page needs so the frontend doesn't have to chain
    half a dozen requests:
      - Top brands we carry for snow & ice (with product counts + in-stock)
      - Plow-type subcategories (live from the category tree)
      - Featured "in stock now" snow products (image, sku, name, brand, qty)
      - Total snow inventory + warehouse breakdown (by route)
    """
    from app.models import Brand, Product, ProductImage, ProductInventory, Warehouse, Category, ProductCategory
    from sqlalchemy import select, func

    # Per-channel visibility so a line hidden from this viewer's channel drops
    # out of the brand counts too (parity with the browse/search listings).
    channel = await _viewer_channel(db, user, request)

    # Top snow plow brand names — ranked by REAL Titan sales velocity from
    # tte_rcv390 (last 12 months, Apr 2025 - Apr 2026):
    #   #1 Western (WEST) — $1.47M, 3,193 units (10× next brand)
    #   #2 Buyers SnowDogg (SNOW) — $270K, 574 units
    #   #3 Buyer Products (BUY) — $201K, 1,788 units (parts + SaltDogg + spreaders)
    #   #4 Meyer (MYP) — $12K, 79 units (small but kept for parts coverage)
    snow_brand_names = ["Western Snow Plows", "Buyers Snow Dogg", "Buyer Products", "Meyer Products"]
    brand_rows = (await db.execute(
        select(Brand).where(Brand.name.in_(snow_brand_names))
    )).scalars().all()
    brands_by_name = {b.name: b for b in brand_rows}

    brand_summaries: list[dict[str, Any]] = []
    # Brand identity — the `lineup` text drives the large header inside each
    # card (since we don't yet host real brand logos).  Real logo SVGs go in
    # Phase 1.5 (need to license / fetch from each manufacturer).
    descriptors = {
        "Western Snow Plows": {
            "rank": "#1 by sales — $1.5M last year",
            "tagline": "The undisputed Titan favorite.  Outsells the next snow brand 10:1.",
            "lineup": "Pro-Plus · MVP3 · Wideout · HTS · Defender",
            "image": None,
            "color": "from-red-700 to-red-900",
        },
        "Buyers Snow Dogg": {
            "rank": "#2 by sales — $270K last year",
            "tagline": "All-stainless construction, factory-direct support, our fastest-growing brand.",
            "lineup": "VX · MD · EX · HD · XP series",
            "image": None,
            "color": "from-emerald-700 to-emerald-900",
        },
        "Buyer Products": {
            "rank": "#3 by sales — $200K last year",
            "tagline": "SaltDogg spreaders, plow harnesses, cutting edges, controllers — the parts shop that keeps your route running.",
            "lineup": "SaltDogg spreaders · Plow parts · Harnesses",
            "image": None,
            "color": "from-blue-700 to-blue-900",
        },
        "Meyer Products": {
            "rank": "#4 — Parts & smaller-truck coverage",
            "tagline": "Drive Pro, Super V2, EZ Plus.  Strong mid-size truck coverage and a deep parts catalog.",
            "lineup": "Super V2 · Lot Pro · XLS · Drive Pro · EZ Plus",
            "image": None,
            "color": "from-amber-600 to-amber-800",
        },
    }

    # Resolve the snow plow category root so we can scope counts to actual
    # snow products only — Buyer Products has 12K SKUs but only ~500 are
    # snow-related (spreaders, harnesses, etc.), and showing the 12K count
    # on a snow card lies to the buyer.
    snow_category_root = (await db.execute(
        select(Category).where(Category.full_path == "Truck Equipment>Snow Plows/Spreaders")
    )).scalar_one_or_none()
    snow_descendant_ids: set[int] = set()
    if snow_category_root:
        snow_descendant_ids.add(snow_category_root.id)
        # Walk the snow subtree (BFS one or two levels deep is enough)
        frontier = [snow_category_root.id]
        while frontier:
            children = (await db.execute(
                select(Category.id).where(Category.parent_id.in_(frontier))
            )).all()
            new_ids = [cid for (cid,) in children if cid not in snow_descendant_ids]
            snow_descendant_ids.update(new_ids)
            frontier = new_ids

    # Snow-only brand names — every SKU under these brands is snow gear by
    # definition (the brand name literally is "Snow Plows" / "Snow Dogg"),
    # so it's safe to count brand-wide instead of category-scoped.
    SNOW_PURE_BRANDS = {"Western Snow Plows", "Buyers Snow Dogg"}

    for name in ["Western Snow Plows", "Buyers Snow Dogg", "Buyer Products", "Meyer Products"]:
        b = brands_by_name.get(name)
        is_pure_snow = name in SNOW_PURE_BRANDS
        # Mixed-brand (Buyer Products, Meyer): scope to snow categories.
        # Pure-snow brand: count brand-wide (every SKU is snow).
        if b is not None and snow_descendant_ids and not is_pure_snow:
            snow_q = (
                select(
                    func.count(Product.id.distinct()),
                    func.count(Product.id.distinct()).filter(ProductInventory.on_hand > 0),
                )
                .select_from(Product)
                .join(ProductCategory, ProductCategory.product_id == Product.id)
                .outerjoin(ProductInventory, ProductInventory.product_id == Product.id)
                .where(
                    Product.brand_id == b.id,
                    Product.is_for_sale.is_(True),
                    visible_to_channel_clause(channel),
                    ProductCategory.category_id.in_(snow_descendant_ids),
                )
            )
            snow_total, snow_in_stock = (await db.execute(snow_q)).one()
        elif b is not None:
            # Fallback: brand-wide if we can't resolve the snow tree
            inv_q = select(
                func.count(Product.id),
                func.count(Product.id).filter(ProductInventory.on_hand > 0),
            ).select_from(Product).outerjoin(
                ProductInventory, ProductInventory.product_id == Product.id
            ).where(Product.brand_id == b.id, Product.is_for_sale.is_(True), visible_to_channel_clause(channel))
            snow_total, snow_in_stock = (await db.execute(inv_q)).one()
        else:
            snow_total, snow_in_stock = 0, 0

        brand_summaries.append({
            "name": name,
            "slug": b.slug if b else None,
            "total_products": int(snow_total or 0),
            "in_stock_skus": int(snow_in_stock or 0),
            **descriptors[name],
        })

    # Snow plow subcategories (all leaf-or-mid nodes under Truck Equipment > Snow Plows/Spreaders)
    snow_root = (await db.execute(
        select(Category).where(Category.full_path == "Truck Equipment>Snow Plows/Spreaders")
    )).scalar_one_or_none()
    plow_categories: list[dict[str, Any]] = []
    if snow_root:
        children = (await db.execute(
            select(Category).where(Category.parent_id == snow_root.id).order_by(Category.name)
        )).scalars().all()
        for c in children:
            n = (await db.execute(
                select(func.count(ProductCategory.product_id)).where(ProductCategory.category_id == c.id)
            )).scalar()
            # Walk grandchildren too for full count
            grand = (await db.execute(
                select(Category).where(Category.parent_id == c.id)
            )).scalars().all()
            for g in grand:
                gn = (await db.execute(
                    select(func.count(ProductCategory.product_id)).where(ProductCategory.category_id == g.id)
                )).scalar()
                n = (n or 0) + (gn or 0)
            plow_categories.append({
                "name": c.name,
                "slug": c.slug,
                "full_path": c.full_path,
                "product_count": int(n or 0),
            })

    # Featured = real top-sellers from tte_rcv390 sales history (last 12 mo).
    # Cross-reference with our local product DB to get image + PDP link where
    # available; for SKUs we don't have locally (most Western parts), render
    # a quote-CTA card.
    from app.services.snow_top_sellers import list_top_sellers, top_seller_to_dict
    from app.models import ProductImage as PIModel
    sellers = list_top_sellers(limit=12)
    seller_skus = [s.sku for s in sellers]
    local_rows = (await db.execute(
        select(Product.sku, Product.name).where(Product.sku.in_(seller_skus))
    )).all()
    local_skus = {sku: name for sku, name in local_rows}
    image_rows = (await db.execute(
        select(Product.sku, PIModel.url)
        .join(PIModel, PIModel.product_id == Product.id)
        .where(Product.sku.in_(seller_skus))
        .order_by(Product.sku, PIModel.sort_order)
    )).all()
    images_by_sku: dict[str, str] = {}
    for sku, url in image_rows:
        images_by_sku.setdefault(sku, url)

    featured: list[dict[str, Any]] = []
    for s in sellers:
        d = top_seller_to_dict(s)
        d["has_local_pdp"] = s.sku in local_skus
        d["image_url"] = images_by_sku.get(s.sku)
        featured.append(d)

    # Sum total snow on-hand + by-warehouse breakdown
    total_snow_inventory = sum(b["in_stock_skus"] for b in brand_summaries)

    return {
        "brands": brand_summaries,
        "plow_categories": plow_categories,
        "featured_in_stock": featured,
        "total_in_stock_skus": total_snow_inventory,
    }


@router.get("/products/{sku}/warehouse-stock")
async def warehouse_stock(sku: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Per-warehouse stock detail for a product (PDP table).

    Returns each warehouse the product touches with on_hand + lead-time +
    next-day-cutoff so the PDP can render a "Locations (n)" breakdown that
    matches PACE's layout.
    """
    from app.models import ProductInventory, Warehouse
    product = (await db.execute(
        select(Product).where(Product.sku == sku)
    )).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product not found: {sku}")
    inv_rows = (await db.execute(
        select(ProductInventory, Warehouse)
        .join(Warehouse, Warehouse.id == ProductInventory.warehouse_id)
        .where(ProductInventory.product_id == product.id)
        .order_by(Warehouse.code)
    )).all()
    locations = [
        {
            "warehouse_code": w.code,
            "warehouse_name": w.short_name or w.name,
            "on_hand": inv.on_hand,
            "in_stock": inv.on_hand > 0,
            # Phase 1 lead-time table by routing: SPO/BOISE = next-day, NELSON = 1-2 days
            "lead_time": "Next Day" if w.facs_route_label in ("SPO", "BOISE") else "1-2 Days",
            # Cutoff: SPO = 6 PM PT, BOISE = 6 PM MT, NELSON = 4 PM PT (placeholder)
            "next_day_cutoff": {
                "SPO": "6 PM PT Mon-Thu",
                "BOISE": "6 PM MT Mon-Thu",
                "NELSON": "4 PM PT Mon-Thu",
            }.get(w.facs_route_label, ""),
            "facs_route": w.facs_route_label,
        }
        for inv, w in inv_rows
    ]
    return {
        "sku": sku,
        "total_on_hand": sum(l["on_hand"] for l in locations),
        "locations": locations,
    }


@router.get("/products/{sku}/alternates")
async def product_alternates(
    sku: str,
    request: Request,
    base_vehicle_id: int | None = Query(None, description="When set, only return parts fitting this vehicle"),
    limit: int = Query(8, ge=1, le=20),
    in_stock_only: bool = Query(False, description="Only return alternates with stock_total > 0"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Like-products / alternates rail for the PDP. Owner ask 2026-05-17 (R1).

    Two modes:
      * `base_vehicle_id` provided (YMM on the session) → "Other products
        for your {Year Make Model}". Candidates must share the current
        product's primary category AND have a PaceFitment for that vehicle.
      * No base_vehicle_id → "Like this part". Candidates share the primary
        category and EITHER overlap on at least one of the current product's
        fitments OR share a PCDB part type.

    `in_stock_only=true` filters the results to live stock — used by the
    PDP's "Available now" callout when the source product is OOS.

    Ranking (owner ask 2026-05-17): in-stock first, then featured-brand
    boost, then stock_total DESC, then name. The featured-brand boost
    promotes heavily-stocked brands over lightly-stocked alternates when
    everything else is equal — a customer landing on a thin-stock SKU
    sees the brand we can ship today first.
    """
    from sqlalchemy import and_ as sa_and, or_ as sa_or
    from app.models import (
        PacePart, PaceFitment, ProductCategory,
    )

    product = (await db.execute(
        select(Product).where(Product.sku == sku)
    )).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product not found: {sku}")

    # Primary category — required anchor.
    prim_cat = (await db.execute(
        select(ProductCategory.category_id)
        .where(ProductCategory.product_id == product.id, ProductCategory.is_primary.is_(True))
        .limit(1)
    )).scalar_one_or_none()
    if prim_cat is None:
        return {"sku": sku, "mode": "none", "items": []}

    # Current product's part types + fitments, used for the no-YMM path.
    own_pace_parts = (await db.execute(
        select(PacePart.id, PacePart.part_terminology_id)
        .where(PacePart.product_id == product.id)
    )).all()
    own_pace_part_ids = [r.id for r in own_pace_parts]
    own_part_type_ids: set[int] = {r.part_terminology_id for r in own_pace_parts if r.part_terminology_id}
    own_vehicle_ids: set[int] = set()
    if own_pace_part_ids:
        rows = (await db.execute(
            select(PaceFitment.base_vehicle_id, PaceFitment.part_type_id)
            .where(PaceFitment.pace_part_id.in_(own_pace_part_ids))
        )).all()
        for r in rows:
            own_vehicle_ids.add(r.base_vehicle_id)
            if r.part_type_id:
                own_part_type_ids.add(r.part_type_id)

    # Candidate query: same primary category, different product, active +
    # visible to the viewer's channel.
    channel = await _viewer_channel(db, user, request)
    base_q = (
        select(Product)
        .options(selectinload(Product.brand), selectinload(Product.images))
        .join(ProductCategory, ProductCategory.product_id == Product.id)
        .where(
            ProductCategory.category_id == prim_cat,
            ProductCategory.is_primary.is_(True),
            Product.id != product.id,
            Product.is_for_sale.is_(True),
            visible_to_channel_clause(channel),
        )
    )

    mode = "category"
    if base_vehicle_id is not None:
        # YMM mode: require fitment to the specified vehicle.
        fit_pids = (
            select(PacePart.product_id)
            .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
            .where(PaceFitment.base_vehicle_id == base_vehicle_id,
                   PacePart.product_id.is_not(None))
        )
        base_q = base_q.where(Product.id.in_(fit_pids))
        mode = "for_vehicle"
    elif not in_stock_only:
        # No-YMM "Like this part" mode. Restrict to products that share a
        # PCDB part type OR overlap a fitment with the current product.
        # We DON'T apply this restriction when in_stock_only is on: the
        # whole point of in_stock_only is "show me anything we can ship
        # today from this subcategory," even if the part-terminology IDs
        # differ. Otherwise an OOS WeatherTech deflector hides the
        # in-stock AVS hood protector that sits in the same category.
        # Owner ask 2026-05-17.
        filters = []
        if own_part_type_ids:
            samept_pids = (
                select(PacePart.product_id)
                .where(PacePart.part_terminology_id.in_(own_part_type_ids),
                       PacePart.product_id.is_not(None))
            )
            filters.append(Product.id.in_(samept_pids))
        if own_vehicle_ids:
            sharedfit_pids = (
                select(PacePart.product_id)
                .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
                .where(PaceFitment.base_vehicle_id.in_(own_vehicle_ids),
                       PacePart.product_id.is_not(None))
            )
            filters.append(Product.id.in_(sharedfit_pids))
        if filters:
            base_q = base_q.where(sa_or(*filters))
            mode = "like_this"
        # else: fall back to "same primary category" only.
    elif own_vehicle_ids:
        # in_stock_only with NO base_vehicle_id (e.g. customer typed the
        # vehicle into the search bar instead of using the YMM picker, so
        # the session carries no vehicle). The source product itself is
        # vehicle-specific, so the in-stock substitute MUST still fit one of
        # the vehicles the source fits — otherwise we suggest a Ram cover as
        # the "in stock alt" for an F-250 cover (reported 2026-06-25). Part
        # TYPE stays relaxed (deflector vs protector is fine, per the
        # 2026-05-17 ask); only fitment is enforced. Universal/no-ACES-fitment
        # products are allowed since they fit everything.
        sharedfit_pids = (
            select(PacePart.product_id)
            .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
            .where(PaceFitment.base_vehicle_id.in_(own_vehicle_ids),
                   PacePart.product_id.is_not(None))
        )
        base_q = base_q.where(
            sa_or(Product.id.in_(sharedfit_pids), Product.has_no_fitment.is_(True))
        )
        mode = "in_stock_same_fit"
    # else (in_stock_only, source has no fitment of its own): leave as
    # "same primary category" — a universal source legitimately matches any
    # in-stock cousin in the subcategory.

    # Pull a small candidate set first (50), then post-rank in Python
    # using batched stock + price lookups. Two things have to happen at
    # the SQL level so the 50-row window is the RIGHT 50:
    #
    #   1. Filter on stock when in_stock_only — otherwise a category
    #      with 200+ OOS siblings would fill the window before any
    #      in-stock cousin appears.
    #
    #   2. Order by total on-hand DESC — within whichever bucket the
    #      filter leaves, surface the deepest-stocked candidates first.
    #      Owner ask 2026-05-17: "use it to promote our top lines"
    #      when multiple alternates exist. A brand with 40 units beats
    #      a brand with 1 unit.
    inv_agg = (
        select(
            ProductInventory.product_id.label("pid"),
            func.coalesce(func.sum(ProductInventory.on_hand), 0).label("total"),
        )
        .group_by(ProductInventory.product_id)
        .subquery()
    )
    base_q = base_q.outerjoin(inv_agg, inv_agg.c.pid == Product.id)
    if in_stock_only:
        base_q = base_q.where(inv_agg.c.total > 0)
    base_q = base_q.order_by(
        func.coalesce(inv_agg.c.total, 0).desc(),
        Product.id.asc(),
    )
    candidates = (await db.execute(base_q.limit(50))).scalars().all()
    if not candidates:
        return {"sku": sku, "mode": mode, "items": []}

    cand_ids = [c.id for c in candidates]
    # Stock totals
    stock_rows = (await db.execute(
        select(ProductInventory.product_id, func.coalesce(func.sum(ProductInventory.on_hand), 0))
        .where(ProductInventory.product_id.in_(cand_ids))
        .group_by(ProductInventory.product_id)
    )).all()
    stock_lookup = {pid: int(total or 0) for pid, total in stock_rows}

    # Primary image
    img_stmt = (
        select(ProductImage.product_id, ProductImage.url)
        .where(ProductImage.product_id.in_(cand_ids))
        .order_by(ProductImage.product_id, ProductImage.sort_order, ProductImage.id)
        .distinct(ProductImage.product_id)
    )
    image_lookup = {pid: url for pid, url in (await db.execute(img_stmt)).all()}

    # Retail price (sentinel-resolved). For B2B contracts we'd need the user's
    # customer — but the rail just shows a quick-glance retail price. The PDP
    # itself carries the contract-resolved primary. Skip tier pricing here.
    from app.services.pricing_service import resolve_retail_for_products
    try:
        retail_prices = await resolve_retail_for_products(db, list(candidates))
    except Exception:
        retail_prices = {}

    def _img(url: str | None) -> str | None:
        if not url: return None
        if "photocomingsoon" in url.lower(): return None
        return url

    if in_stock_only:
        candidates = [c for c in candidates if stock_lookup.get(c.id, 0) > 0]

    def _featured(p: Product) -> bool:
        return bool(p.brand and getattr(p.brand, "is_featured", False))

    # Owner ask 2026-05-17 ("our top lines if multiple exist"):
    # stock-depth dominates the ranking — a 40-unit AVS beats a 1-unit
    # WeatherTech even if WeatherTech is the featured brand. Featured
    # only kicks in as a tiebreaker when stock totals match.
    ranked = sorted(
        candidates,
        key=lambda p: (
            -1 if stock_lookup.get(p.id, 0) > 0 else 0,    # in-stock first
            -stock_lookup.get(p.id, 0),                       # then deeper stock
            -1 if _featured(p) else 0,                       # featured brand as tiebreaker
            (p.name or "").lower(),
        ),
    )[:limit]

    items = []
    for p in ranked:
        retail = retail_prices.get(p.id)
        items.append({
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "brand": p.brand.name if p.brand else None,
            "image_url": _img(image_lookup.get(p.id)),
            "in_stock": stock_lookup.get(p.id, 0) > 0,
            "stock_total": stock_lookup.get(p.id, 0),
            "retail_price": float(retail) if retail is not None else None,
            "cta_mode": p.cta_mode.value if hasattr(p.cta_mode, "value") else str(p.cta_mode),
        })
    return {"sku": sku, "mode": mode, "items": items}


@router.get("/products/{sku}/accessories")
async def product_accessories(
    sku: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Parts and sized bodies listed underneath a truck body (ported from Titan 2026-09-21).

    Rows come from product_accessory (link_truck_body_parts.py). Same guards as
    the alternates rail: only parts for sale and visible to the viewer's
    channel. A price is shown to retail only -- the rail's quick-glance price
    is the retail one, and showing that to a jobber/dealer/municipality account
    would quote them the wrong number; their card links to the part page,
    which carries their price. Stock is the total on hand (Nelson has no
    per-channel shelf split; Titan's version counts the viewer's own shelf).
    """
    from app.models import ProductAccessory
    from app.services.channels import on_hand_map

    body = (await db.execute(select(Product).where(Product.sku == sku))).scalar_one_or_none()
    if body is None:
        raise HTTPException(status_code=404, detail=f"Product not found: {sku}")
    channel = await _viewer_channel(db, user, request)

    rows = (await db.execute(
        select(ProductAccessory.group_name, ProductAccessory.sort_order, Product)
        .join(Product, Product.id == ProductAccessory.part_product_id)
        .options(selectinload(Product.brand))
        .where(
            ProductAccessory.body_product_id == body.id,
            Product.is_for_sale.is_(True),
            visible_to_channel_clause(channel),
        )
    )).all()
    if not rows:
        return {"sku": sku, "groups": [], "show_prices": channel == "retail"}

    ids = [p.id for _, _, p in rows]
    stock = await on_hand_map(db, ids)
    img_rows = (await db.execute(
        select(ProductImage.product_id, ProductImage.url)
        .where(ProductImage.product_id.in_(ids))
        .order_by(ProductImage.product_id, ProductImage.is_primary.desc(),
                  ProductImage.sort_order, ProductImage.id)
        .distinct(ProductImage.product_id)
    )).all()
    # Localized images come in pairs (<hash>_1280.jpg / <hash>_400.jpg); a card
    # only needs the 400px one.
    images = {pid: (url.replace("_1280.jpg", "_400.jpg") if url and url.startswith("/static/product-images/")
                    else url) for pid, url in img_rows}
    prices: dict[int, Any] = {}
    if channel == "retail":
        from app.services.pricing_service import resolve_retail_for_products
        try:
            prices = await resolve_retail_for_products(db, [p for _, _, p in rows])
        except Exception:  # noqa: BLE001 -- a price lookup failure must not hide the list
            prices = {}

    groups: dict[str, dict[str, Any]] = {}
    for group, order, p in rows:
        g = groups.setdefault(group, {"name": group, "order": order, "items": []})
        price = prices.get(p.id)
        g["items"].append({
            "sku": p.sku,
            "name": p.name,
            "brand": p.brand.name if p.brand else None,
            "image_url": images.get(p.id),
            "in_stock": stock.get(p.id, 0) > 0,
            "stock_total": stock.get(p.id, 0),
            "price": float(price) if price is not None and float(price) > 0 else None,
        })
    out = sorted(groups.values(), key=lambda g: g["order"])
    for g in out:
        # in stock first, then by name, so the part a customer can have today leads each group
        g["items"].sort(key=lambda i: (not i["in_stock"], (i["name"] or "").lower()))
        g.pop("order")
    return {"sku": sku, "groups": out, "show_prices": channel == "retail"}


# =====================================================================
# ADMIN: category image curation
#
# Lets an admin browse categories, see every candidate product image for
# each one, and pin a specific image as the category's representative.
# The pinned URL wins over the algorithmic tier chain in /categories/tree
# and /category/{slug}.
# =====================================================================


def _require_admin(user: User | None) -> User:
    """Lightweight admin gate. UserRole.ADMIN required."""
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


@router.get("/admin/categories")
async def admin_list_categories(
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Flat list of every active category with current curated_image_url +
    a count of how many candidate primary images are available to pick from.
    Used by the admin image-curation page."""
    _require_admin(user)
    from sqlalchemy import text
    # Owner ask 2026-05-17: curator should only list categories that
    # actually appear on the public storefront — i.e. categories with
    # at least one product when rolled up through descendants. Mirrors
    # the prune_empty() pass in /categories/tree.
    #
    # Implementation: materialize (root, desc) descendants once, then
    # aggregate two metrics per root in one pass:
    #   - product_count_rolled: distinct products under root (filter pred)
    #   - candidate_count: distinct primary images under root (gallery size)
    rows = (await db.execute(text("""
        WITH RECURSIVE descendants AS (
          SELECT id AS root_id, id AS desc_id FROM category WHERE is_active
          UNION ALL
          SELECT d.root_id, c.id FROM category c
            JOIN descendants d ON c.parent_id = d.desc_id
        ),
        per_root_products AS (
          SELECT d.root_id, COUNT(DISTINCT pc.product_id) AS product_count_rolled
          FROM descendants d
          LEFT JOIN product_category pc ON pc.category_id = d.desc_id
          GROUP BY d.root_id
        ),
        per_root_images AS (
          SELECT d.root_id, COUNT(DISTINCT pi.id) AS candidate_count
          FROM descendants d
          JOIN product_category pc ON pc.category_id = d.desc_id
          JOIN product_image pi ON pi.product_id = pc.product_id
          WHERE pi.is_primary = true
            AND pi.url IS NOT NULL
            AND pi.url <> ''
          GROUP BY d.root_id
        )
        SELECT
          c.id,
          c.name,
          c.full_path,
          c.depth,
          c.curated_image_url,
          COALESCE(pri.candidate_count, 0) AS candidate_count,
          COALESCE(prp.product_count_rolled, 0) AS product_count
        FROM category c
        LEFT JOIN per_root_images pri ON pri.root_id = c.id
        LEFT JOIN per_root_products prp ON prp.root_id = c.id
        WHERE c.is_active = true
          AND COALESCE(prp.product_count_rolled, 0) > 0
        ORDER BY c.full_path
    """))).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "full_path": r.full_path,
            "depth": r.depth,
            "curated_image_url": r.curated_image_url,
            "candidate_count": int(r.candidate_count or 0),
            "product_count": int(r.product_count or 0),
        }
        for r in rows
    ]


@router.get("/admin/categories/{cat_id}/candidates")
async def admin_category_candidates(
    cat_id: int,
    limit: int = Query(48, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Return every primary product image attached to a product mapped to
    this category. The admin picks one from this gallery."""
    _require_admin(user)
    from sqlalchemy import text
    cat_row = (await db.execute(text(
        "SELECT id, name, full_path, curated_image_url FROM category WHERE id = :id"
    ), {"id": cat_id})).first()
    if cat_row is None:
        raise HTTPException(status_code=404, detail=f"Category not found: {cat_id}")

    # Order candidates by what's actually in stock + recently sold so the
    # admin sees the strongest representative products at the top of the
    # gallery, not just whatever got imported last. Walks descendants so
    # parent categories (e.g. "Bumpers and Grille Guards") that have no
    # directly-mapped products still surface candidates from their
    # subcategories (Front Bumpers, Rear Bumpers, …).
    candidates = (await db.execute(text("""
        WITH RECURSIVE descendants AS (
          SELECT id AS desc_id FROM category WHERE id = :id
          UNION ALL
          SELECT c.id FROM category c JOIN descendants d ON c.parent_id = d.desc_id
        ),
        per_product AS (
          SELECT DISTINCT ON (p.id)
            p.id          AS product_id,
            p.sku,
            p.name        AS product_name,
            b.name        AS brand_name,
            pi.url        AS image_url,
            COALESCE(inv.total, 0) AS on_hand,
            COALESCE(sales.sold, 0) AS sold_12mo
          FROM descendants d
          JOIN product_category pc ON pc.category_id = d.desc_id
          JOIN product p ON p.id = pc.product_id
          JOIN product_image pi ON pi.product_id = p.id
          LEFT JOIN brand b ON b.id = p.brand_id
          LEFT JOIN (
            SELECT product_id, SUM(on_hand) AS total
            FROM product_inventory GROUP BY product_id
          ) inv ON inv.product_id = p.id
          LEFT JOIN (
            SELECT product_id, SUM(quantity) AS sold FROM order_line
            WHERE created_at >= NOW() - INTERVAL '365 days'
            GROUP BY product_id
          ) sales ON sales.product_id = p.id
          WHERE pi.is_primary = true
            AND pi.url IS NOT NULL AND pi.url <> ''
          ORDER BY p.id, pi.id DESC
        )
        SELECT * FROM per_product
        ORDER BY
          CASE WHEN on_hand > 0 THEN 0 ELSE 1 END,
          on_hand DESC,
          sold_12mo DESC,
          product_id DESC
        LIMIT :limit
    """), {"id": cat_id, "limit": limit})).all()

    return {
        "id": cat_row.id,
        "name": cat_row.name,
        "full_path": cat_row.full_path,
        "curated_image_url": cat_row.curated_image_url,
        "candidates": [
            {
                "product_id": c.product_id,
                "sku": c.sku,
                "product_name": c.product_name,
                "brand_name": c.brand_name,
                "image_url": c.image_url,
                "on_hand": int(c.on_hand or 0),
                "sold_12mo": int(c.sold_12mo or 0),
            }
            for c in candidates
        ],
    }


@router.put("/admin/categories/{cat_id}/curated-image")
async def admin_set_curated_image(
    cat_id: int,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Pin a specific image_url as the category's representative.
    Pass {"image_url": null} to clear and fall back to algorithmic pick."""
    _require_admin(user)
    from sqlalchemy import text
    image_url = payload.get("image_url")  # may be None to clear
    if image_url is not None and not isinstance(image_url, str):
        raise HTTPException(status_code=400, detail="image_url must be a string or null")
    if isinstance(image_url, str) and len(image_url) > 1000:
        raise HTTPException(status_code=400, detail="image_url too long (max 1000 chars)")
    result = await db.execute(text("""
        UPDATE category SET curated_image_url = :url, updated_at = NOW()
        WHERE id = :id
        RETURNING id, name, full_path, curated_image_url
    """), {"id": cat_id, "url": image_url})
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Category not found: {cat_id}")
    await db.commit()
    # Pinning an image changes what /categories/tree returns, so drop its cache
    # to reflect the new pin immediately instead of waiting out the TTL.
    from app.services.browse_cache import tree_cache
    tree_cache.clear()
    return {
        "id": row.id,
        "name": row.name,
        "full_path": row.full_path,
        "curated_image_url": row.curated_image_url,
    }


# =====================================================================
# ADMIN: PIES attribute-value curation
#
# Surfaces near-duplicate raw values per attribute_key (e.g. "TPE -
# Thermoplastic Elastomer" / "Thermoplastic Elastomer (TPE)") and lets
# an admin confirm them as a single canonical bucket. Manual aliases
# land in `attribute_value_alias` and are consulted by
# /category-attributes + /browse so the customer-facing filters collapse
# variants into one checkbox.
# =====================================================================


@router.get("/admin/attribute-keys")
async def admin_attribute_keys(
    min_products: int = Query(
        25, ge=1, le=10000,
        description="Skip keys that appear on fewer products than this — keeps "
                    "the queue short and focused on customer-visible attributes",
    ),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List attribute_keys with curation stats.

    Cheap signals only — does NOT run the full clustering pass per key
    (that's deferred to /admin/attribute-keys/{key}/clusters because the
    catalog has 2K+ distinct PIES keys and per-key Python clustering is
    too slow for a page load). Uses a single SQL aggregate to compute:

      - `raw_value_count`: distinct raw attribute_value strings
      - `case_folded_value_count`: distinct lower(trim(...)) forms
      - `auto_foldable_value_count`: raw - case_folded — the cheap
        proxy for "this key definitely has merge candidates", used as
        the queue-priority signal in place of true cluster count
      - `products_with_key`, `manual_alias_count`, `reviewed_at`

    Sort: unreviewed + has-auto-folds first; tie-break on products.
    """
    _require_admin(user)
    from sqlalchemy import text
    # Single CTE: count per key with case-fold dedup.  Pushes the
    # 2K-key / 3M-row aggregation to Postgres instead of looping in
    # Python.  Roughly 1-2 s on a warm DB.
    rows = (await db.execute(text("""
        WITH per_key AS (
          SELECT
            attribute_key,
            COUNT(DISTINCT attribute_value) AS raw_value_count,
            COUNT(DISTINCT LOWER(TRIM(attribute_value))) AS case_folded_count,
            COUNT(DISTINCT product_id) AS products_with_key
          FROM product_attribute
          WHERE attribute_value IS NOT NULL
            AND attribute_value <> ''
          GROUP BY attribute_key
          HAVING COUNT(DISTINCT product_id) >= :min_products
        ),
        alias_counts AS (
          SELECT attribute_key, COUNT(*) AS n
          FROM attribute_value_alias
          WHERE source = 'manual'
          GROUP BY attribute_key
        ),
        review AS (
          SELECT attribute_key, reviewed_at FROM attribute_key_review
        )
        SELECT
          pk.attribute_key,
          pk.raw_value_count,
          pk.case_folded_count,
          pk.products_with_key,
          COALESCE(ac.n, 0) AS manual_alias_count,
          rv.reviewed_at
        FROM per_key pk
        LEFT JOIN alias_counts ac ON ac.attribute_key = pk.attribute_key
        LEFT JOIN review rv ON rv.attribute_key = pk.attribute_key
    """), {"min_products": min_products})).all()

    out: list[dict[str, Any]] = []
    for r in rows:
        kl = r.attribute_key.lower()
        if kl in _ATTR_DENYLIST:
            continue
        if kl.endswith(" - xa") or kl.endswith(" - xb") or kl.endswith(" - xc"):
            continue
        raw = int(r.raw_value_count)
        case_folded = int(r.case_folded_count)
        # Only meaningful if there's > 1 distinct value at all
        if raw < 2:
            continue
        auto_foldable = raw - case_folded
        out.append({
            "attribute_key": r.attribute_key,
            "raw_value_count": raw,
            "canonical_value_count": case_folded,  # cheap approximation; full
                                                   # canonical count comes from
                                                   # the per-key endpoint
            "auto_foldable_value_count": auto_foldable,
            "manual_alias_count": int(r.manual_alias_count),
            "products_with_key": int(r.products_with_key),
            "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        })

    def _sort_key(row: dict[str, Any]) -> tuple:
        return (
            0 if row["reviewed_at"] is None else 1,
            -row["auto_foldable_value_count"],
            -row["products_with_key"],
        )
    out.sort(key=_sort_key)
    return out


@router.get("/admin/attribute-keys/{attribute_key}/clusters")
async def admin_attribute_key_clusters(
    attribute_key: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-key clusters + long tail for the curation UI."""
    _require_admin(user)
    from sqlalchemy import distinct, func, select
    from app.models import AttributeValueAlias, ProductAttribute
    from app.services.attribute_canonical import (
        bucket_by_canonical, suggest_clusters,
    )

    if attribute_key.lower() in _ATTR_DENYLIST:
        raise HTTPException(
            status_code=400,
            detail=f"attribute_key '{attribute_key}' is on the denylist",
        )

    raws = (await db.execute(
        select(
            ProductAttribute.attribute_value,
            ProductAttribute.attribute_uom,
            func.count(distinct(ProductAttribute.product_id)).label("n"),
        )
        .where(ProductAttribute.attribute_key == attribute_key)
        .where(ProductAttribute.attribute_value.is_not(None))
        .where(ProductAttribute.attribute_value != "")
        .group_by(ProductAttribute.attribute_value, ProductAttribute.attribute_uom)
    )).all()
    if not raws:
        return {
            "attribute_key": attribute_key,
            "auto_merged": [],
            "suggested_clusters": [],
            "long_tail": [],
            "manual_aliases": [],
        }

    manual_rows = (await db.execute(
        select(AttributeValueAlias.raw_value, AttributeValueAlias.canonical_value)
        .where(AttributeValueAlias.attribute_key == attribute_key)
        .where(AttributeValueAlias.source == "manual")
    )).all()
    manual_aliases = {raw: canon for raw, canon in manual_rows}

    buckets = bucket_by_canonical(
        ((v, uom, n) for v, uom, n in raws),
        manual_aliases=manual_aliases,
    )

    auto_merged: list[dict[str, Any]] = []
    for b in buckets:
        if len(b.raw_values) > 1:
            auto_merged.append({
                "canonical": b.canonical,
                "count": b.count,
                "raw_values": b.raw_values,
            })

    clusters, long_tail = suggest_clusters(buckets)

    def _bucket_json(b) -> dict[str, Any]:
        return {
            "canonical": b.canonical,
            "count": b.count,
            "raw_values": b.raw_values,
            "uom": b.uom,
        }

    return {
        "attribute_key": attribute_key,
        "auto_merged": auto_merged,
        "suggested_clusters": [
            {
                "canonical": c.canonical,
                "total_count": c.total_count,
                "members": [_bucket_json(m) for m in c.members],
            }
            for c in clusters
        ],
        "long_tail": [_bucket_json(b) for b in long_tail],
        "manual_aliases": [
            {"raw_value": raw, "canonical_value": canon}
            for raw, canon in manual_rows
        ],
    }


@router.put("/admin/attribute-aliases")
async def admin_save_attribute_aliases(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Save a cluster as a set of manual aliases.

    Body: {"attribute_key": str, "canonical": str, "raw_values": [str]}

    Upserts one alias row per raw_value: (key, raw) -> canonical, source='manual'.
    Existing rows for the same (key, raw) are overwritten so a curator
    can re-classify a value into a different canonical."""
    _require_admin(user)
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models import AttributeValueAlias

    attribute_key = (payload.get("attribute_key") or "").strip()
    canonical = (payload.get("canonical") or "").strip()
    raw_values = payload.get("raw_values") or []
    if not attribute_key or not canonical or not raw_values:
        raise HTTPException(
            status_code=400,
            detail="attribute_key, canonical, and non-empty raw_values are required",
        )
    if attribute_key.lower() in _ATTR_DENYLIST:
        raise HTTPException(
            status_code=400,
            detail=f"attribute_key '{attribute_key}' is on the denylist",
        )
    if not isinstance(raw_values, list) or not all(isinstance(r, str) for r in raw_values):
        raise HTTPException(status_code=400, detail="raw_values must be a list of strings")

    for raw in raw_values:
        raw = raw.strip()
        if not raw:
            continue
        stmt = pg_insert(AttributeValueAlias.__table__).values(
            attribute_key=attribute_key,
            raw_value=raw,
            canonical_value=canonical,
            source="manual",
        ).on_conflict_do_update(
            constraint="uq_attribute_value_alias_key_raw",
            set_={
                "canonical_value": canonical,
                "source": "manual",
                "updated_at": func.now(),
            },
        )
        await db.execute(stmt)
    await db.commit()

    rows = (await db.execute(
        select(
            AttributeValueAlias.raw_value,
            AttributeValueAlias.canonical_value,
        )
        .where(AttributeValueAlias.attribute_key == attribute_key)
        .where(AttributeValueAlias.source == "manual")
    )).all()
    return {
        "attribute_key": attribute_key,
        "canonical": canonical,
        "raw_values_saved": raw_values,
        "manual_aliases": [
            {"raw_value": raw, "canonical_value": canon}
            for raw, canon in rows
        ],
    }


@router.delete("/admin/attribute-aliases")
async def admin_delete_attribute_aliases(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Remove manual aliases for one or more raw_values under a key.
    Releases those raws back to auto-canonicalization."""
    _require_admin(user)
    from sqlalchemy import delete
    from app.models import AttributeValueAlias

    attribute_key = (payload.get("attribute_key") or "").strip()
    raw_values = payload.get("raw_values") or []
    if not attribute_key or not raw_values:
        raise HTTPException(
            status_code=400,
            detail="attribute_key and non-empty raw_values are required",
        )
    if not isinstance(raw_values, list):
        raise HTTPException(status_code=400, detail="raw_values must be a list")

    await db.execute(
        delete(AttributeValueAlias)
        .where(AttributeValueAlias.attribute_key == attribute_key)
        .where(AttributeValueAlias.raw_value.in_(raw_values))
    )
    await db.commit()
    return {"attribute_key": attribute_key, "removed": raw_values}


@router.post("/admin/attribute-keys/{attribute_key}/mark-reviewed")
async def admin_mark_attribute_reviewed(
    attribute_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark a key reviewed (or refresh reviewed_at). Drops the key off
    the curator's queue."""
    _require_admin(user)
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models import AttributeKeyReview

    stmt = pg_insert(AttributeKeyReview.__table__).values(
        attribute_key=attribute_key,
        reviewed_by_user_id=user.id if user else None,
    ).on_conflict_do_update(
        constraint="uq_attribute_key_review_key",
        set_={
            "reviewed_at": func.now(),
            "reviewed_by_user_id": user.id if user else None,
            "updated_at": func.now(),
        },
    )
    await db.execute(stmt)
    await db.commit()
    return {"attribute_key": attribute_key, "reviewed": True}


@router.delete("/admin/attribute-keys/{attribute_key}/mark-reviewed")
async def admin_unmark_attribute_reviewed(
    attribute_key: str,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Clear the reviewed marker — pushes the key back into the queue."""
    _require_admin(user)
    from sqlalchemy import delete
    from app.models import AttributeKeyReview

    await db.execute(
        delete(AttributeKeyReview).where(AttributeKeyReview.attribute_key == attribute_key)
    )
    await db.commit()
    return {"attribute_key": attribute_key, "reviewed": False}


# =====================================================================
# ADMIN: facet-KEY merge map (synonym keys -> one facet group)
#
# One level up from attribute-aliases (which merge VALUES within a key),
# these merge whole KEYS that describe the same attribute under different
# names — e.g. Volume / Gallon Capacity / Liquid Storage Capacity on the
# Transfer Tanks rail. Label-variant keys ("X" vs "X (in.)") fold
# automatically and never need a row here.
# =====================================================================


@router.get("/admin/attribute-key-merges")
async def admin_list_attribute_key_merges(
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """List curator-confirmed key-merge groups as {group_label: [member_keys]}."""
    _require_admin(user)
    from app.models import AttributeKeyAlias

    rows = (await db.execute(
        select(AttributeKeyAlias.group_label, AttributeKeyAlias.member_key)
        .order_by(AttributeKeyAlias.group_label, AttributeKeyAlias.member_key)
    )).all()
    groups: dict[str, list[str]] = {}
    for label, member in rows:
        groups.setdefault(label, []).append(member)
    return {"groups": [{"group_label": k, "members": v} for k, v in groups.items()]}


@router.get("/admin/attribute-key-merge-suggestions")
async def admin_attribute_key_merge_suggestions(
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Detector-driven SYNONYM clusters for the curator to confirm.

    Read-only scan across leaf categories. Excludes pure label-variants
    (auto-folded), coincidental numeric overlap, and keys already merged.
    May take a few seconds on a cold cache."""
    _require_admin(user)
    from app.models import AttributeKeyAlias
    from app.services.attribute_key_suggest import suggest_key_merges

    merged = set((await db.execute(
        select(AttributeKeyAlias.member_key)
    )).scalars().all())
    clusters = await suggest_key_merges(
        db, denylist=_ATTR_DENYLIST, already_merged=merged,
    )
    return {"clusters": clusters}


@router.put("/admin/attribute-key-merges")
async def admin_save_attribute_key_merge(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Create/replace a key-merge group.

    Body: {"group_label": str, "member_keys": [str, ...]}

    Every member (including whichever key matches group_label) gets a row
    member_key -> group_label. To keep the unique-per-member invariant, any
    prior membership for these members OR this label is cleared first, so
    re-saving is idempotent and a key can be moved between groups."""
    _require_admin(user)
    from sqlalchemy import delete, or_
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.models import AttributeKeyAlias

    group_label = (payload.get("group_label") or "").strip()
    member_keys = payload.get("member_keys") or []
    if not group_label or not isinstance(member_keys, list):
        raise HTTPException(
            status_code=400,
            detail="group_label and a member_keys list are required",
        )
    members = sorted({m.strip() for m in member_keys if isinstance(m, str) and m.strip()})
    if len(members) < 2:
        raise HTTPException(
            status_code=400,
            detail="a merge group needs at least 2 member keys",
        )
    for m in members:
        if m.lower() in _ATTR_DENYLIST:
            raise HTTPException(status_code=400, detail=f"member '{m}' is on the denylist")

    # Clear any existing membership for these members or this label, then insert.
    await db.execute(
        delete(AttributeKeyAlias).where(
            or_(AttributeKeyAlias.member_key.in_(members),
                AttributeKeyAlias.group_label == group_label)
        )
    )
    for m in members:
        await db.execute(
            pg_insert(AttributeKeyAlias.__table__).values(
                member_key=m, group_label=group_label, source="manual",
            ).on_conflict_do_update(
                constraint="uq_attribute_key_alias_member",
                set_={"group_label": group_label, "source": "manual",
                      "updated_at": func.now()},
            )
        )
    await db.commit()
    return {"group_label": group_label, "members": members}


@router.delete("/admin/attribute-key-merges")
async def admin_delete_attribute_key_merge(
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Dissolve a merge group (by group_label) — its keys split back into
    their own facets (still subject to automatic label-variant folding)."""
    _require_admin(user)
    from sqlalchemy import delete
    from app.models import AttributeKeyAlias

    group_label = (payload.get("group_label") or "").strip()
    if not group_label:
        raise HTTPException(status_code=400, detail="group_label is required")
    await db.execute(
        delete(AttributeKeyAlias).where(AttributeKeyAlias.group_label == group_label)
    )
    await db.commit()
    return {"group_label": group_label, "removed": True}


# =====================================================================
# ADMIN: reseller-finder queue (S1)
#
# Auto-scorer in scripts/find_reseller_pairs.py writes pending pairs.
# This endpoint surfaces them with both products' details so the admin
# can confirm/reject from /admin/reseller-finder.
# =====================================================================


@router.get("/admin/category-curator/{cat_id}/products")
async def admin_category_products(
    cat_id: int,
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """List products currently in this category (primary mapping). For
    the Category Curator admin page so misclassified products can be
    bulk-moved. Owner ask 2026-05-17 (C1).
    """
    _require_admin(user)
    from app.models import Category, ProductCategory

    cat = (await db.execute(select(Category).where(Category.id == cat_id))).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=404, detail=f"Category not found: {cat_id}")

    prod_rows = (await db.execute(
        select(Product)
        .options(selectinload(Product.brand), selectinload(Product.images))
        .join(ProductCategory, ProductCategory.product_id == Product.id)
        .where(ProductCategory.category_id == cat_id)
        .where(ProductCategory.is_primary.is_(True))
        .order_by(Product.name)
        .limit(limit)
    )).scalars().all()

    items = []
    for p in prod_rows:
        img = next((i.url for i in sorted(p.images, key=lambda i: (i.sort_order, i.id))), None)
        if img and "photocomingsoon" in img.lower(): img = None
        items.append({
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "brand": p.brand.name if p.brand else None,
            "image_url": img,
            "is_for_sale": p.is_for_sale,
        })
    return {
        "category_id": cat.id,
        "category_name": cat.name,
        "category_path": cat.full_path,
        "items": items,
    }


@router.post("/admin/category-curator/move")
async def admin_category_move(
    body: dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Bulk-move primary-category mapping for a list of products.

    Body: {product_ids: [...], from_category_id: N, to_category_id: M}
    Writes one AuditLog row per move so reverts are possible.
    """
    admin = _require_admin(user)
    from app.models import AuditLog, Category, ProductCategory

    product_ids = body.get("product_ids") or []
    from_id = body.get("from_category_id")
    to_id = body.get("to_category_id")
    if not product_ids or from_id is None or to_id is None:
        raise HTTPException(status_code=400, detail="product_ids, from_category_id, to_category_id required")
    if from_id == to_id:
        raise HTTPException(status_code=400, detail="Source and destination categories must differ")

    # Validate categories exist.
    cats = {c.id: c for c in (await db.execute(
        select(Category).where(Category.id.in_([from_id, to_id]))
    )).scalars().all()}
    if from_id not in cats or to_id not in cats:
        raise HTTPException(status_code=404, detail="Category not found")

    # Apply: flip the primary product_category rows.
    rows = (await db.execute(
        select(ProductCategory)
        .where(
            ProductCategory.product_id.in_(product_ids),
            ProductCategory.category_id == from_id,
            ProductCategory.is_primary.is_(True),
        )
    )).scalars().all()
    moved_pids: list[int] = []
    for r in rows:
        r.category_id = to_id
        moved_pids.append(r.product_id)
        db.add(AuditLog(
            user_id=admin.id,
            user_email=admin.email,
            action="update",
            entity_type="ProductCategory",
            entity_id=str(r.product_id),
            before={"category_id": from_id},
            after={"category_id": to_id},
            summary=f"Category Curator: moved product {r.product_id} from cat#{from_id} ({cats[from_id].full_path}) to cat#{to_id} ({cats[to_id].full_path})",
            ip_address=request.client.host if request.client else None,
        ))
    await db.commit()
    return {
        "moved_count": len(moved_pids),
        "moved_product_ids": moved_pids,
        "from_category_id": from_id,
        "to_category_id": to_id,
    }


@router.get("/admin/attribute-decompositions")
async def admin_list_decompositions(
    raw_key: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """List existing AttributeValueDecomposition rows, optionally filtered
    to a single raw_key. Owner ask 2026-05-17 (A1). The decomposition data
    layer is shipped; the curator UI + apply-to-facets path land in a
    follow-up — for now this endpoint plus the POST/DELETE below is enough
    to populate decompositions via API / SQL.
    """
    _require_admin(user)
    from app.models import AttributeValueDecomposition

    stmt = select(AttributeValueDecomposition).order_by(
        AttributeValueDecomposition.raw_key,
        AttributeValueDecomposition.raw_value,
        AttributeValueDecomposition.target_key,
    )
    if raw_key:
        stmt = stmt.where(AttributeValueDecomposition.raw_key == raw_key)
    rows = (await db.execute(stmt)).scalars().all()
    items = [
        {
            "id": r.id,
            "raw_key": r.raw_key,
            "raw_value": r.raw_value,
            "target_key": r.target_key,
            "target_canonical": r.target_canonical,
            "source": r.source,
        }
        for r in rows
    ]
    return {"items": items}


@router.post("/admin/attribute-decompositions")
async def admin_save_decomposition(
    body: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Save the decomposition for one (raw_key, raw_value) — replaces any
    previous rows for that pair. body shape:
      {raw_key, raw_value, targets: [{target_key, target_canonical}, ...]}
    """
    _require_admin(user)
    from sqlalchemy import delete as sa_delete
    from app.models import AttributeValueDecomposition

    raw_key = (body.get("raw_key") or "").strip()
    raw_value = (body.get("raw_value") or "").strip()
    targets = body.get("targets") or []
    if not raw_key or not raw_value:
        raise HTTPException(status_code=400, detail="raw_key + raw_value required")
    # Replace existing
    await db.execute(
        sa_delete(AttributeValueDecomposition)
        .where(
            AttributeValueDecomposition.raw_key == raw_key,
            AttributeValueDecomposition.raw_value == raw_value,
        )
    )
    inserted = 0
    for t in targets:
        tk = (t.get("target_key") or "").strip()
        tc = (t.get("target_canonical") or "").strip()
        if not tk or not tc: continue
        db.add(AttributeValueDecomposition(
            raw_key=raw_key, raw_value=raw_value,
            target_key=tk, target_canonical=tc, source="manual",
        ))
        inserted += 1
    await db.commit()
    return {"raw_key": raw_key, "raw_value": raw_value, "inserted": inserted}


@router.delete("/admin/attribute-decompositions")
async def admin_delete_decomposition(
    raw_key: str = Query(...),
    raw_value: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Remove all decomposition rows for a (raw_key, raw_value) pair."""
    _require_admin(user)
    from sqlalchemy import delete as sa_delete
    from app.models import AttributeValueDecomposition

    r = await db.execute(
        sa_delete(AttributeValueDecomposition)
        .where(
            AttributeValueDecomposition.raw_key == raw_key,
            AttributeValueDecomposition.raw_value == raw_value,
        )
    )
    await db.commit()
    return {"raw_key": raw_key, "raw_value": raw_value, "deleted": r.rowcount or 0}


@router.get("/admin/attribute-synonym-suggestions")
async def admin_synonym_suggestions(
    attribute_key: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """A2 — suggest new raw → canonical merges for unaliased values.

    For each raw value that doesn't yet have an AttributeValueAlias row,
    case-fold and look for an existing canonical that matches under
    standard normalization (collapse whitespace, drop punctuation). When
    found, suggest the merge so the curator can confirm with one click.

    Lightweight implementation — no fuzzy matching, just the deterministic
    rules. This is what makes incoming PIES feeds with "Powdercoated"
    automatically connect to the existing "Powder Coated" canonical.
    """
    _require_admin(user)
    import re as _re
    from app.models import AttributeValueAlias

    def _norm(v: str) -> str:
        # Lower, strip non-alnum runs to single space, collapse, trim.
        s = _re.sub(r"[^a-z0-9]+", " ", v.lower()).strip()
        return _re.sub(r"\s+", " ", s)

    # All raw values for this key, with usage count
    raw_rows = (await db.execute(
        select(
            ProductAttribute.attribute_value,
            func.count(distinct(ProductAttribute.product_id)).label("n"),
        )
        .where(ProductAttribute.attribute_key == attribute_key)
        .where(ProductAttribute.attribute_value.is_not(None))
        .where(ProductAttribute.attribute_value != "")
        .group_by(ProductAttribute.attribute_value)
    )).all()

    # Existing canonicals + their raw aliases
    alias_rows = (await db.execute(
        select(AttributeValueAlias.raw_value, AttributeValueAlias.canonical_value)
        .where(AttributeValueAlias.attribute_key == attribute_key)
    )).all()
    raw_to_canonical = {r.lower(): c for r, c in alias_rows}
    canonicals = {c for _, c in alias_rows}
    canonical_norms = {_norm(c): c for c in canonicals}

    suggestions: list[dict[str, Any]] = []
    for row in raw_rows:
        raw = row.attribute_value
        n = int(row.n)
        if raw.lower() in raw_to_canonical:
            continue  # already aliased
        norm = _norm(raw)
        # Try exact-normalized match to a canonical
        match = canonical_norms.get(norm)
        if match and match != raw:
            suggestions.append({
                "raw_value": raw,
                "canonical_value": match,
                "rule": "case-fold-punct",
                "n_products": n,
            })

    suggestions.sort(key=lambda s: s["n_products"], reverse=True)
    return {"attribute_key": attribute_key, "suggestions": suggestions}


@router.get("/admin/reseller-finder/queue")
async def admin_reseller_queue(
    status: str = Query("pending", description="pending | confirmed | rejected"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    _require_admin(user)
    from app.models import ProductMatch, ProductMatchStatus, ProductPrice

    try:
        st_enum = ProductMatchStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown status: {status}")

    rows = (await db.execute(
        select(ProductMatch)
        .where(ProductMatch.status == st_enum)
        .order_by(ProductMatch.score.desc(), ProductMatch.id.desc())
        .limit(limit)
    )).scalars().all()
    if not rows:
        return {"status": status, "items": [], "total_pending": 0}

    # Bulk-load products + brands + primary images + prices for the queue.
    pids = list({r.canonical_product_id for r in rows} | {r.alias_product_id for r in rows})
    products = {p.id: p for p in (await db.execute(
        select(Product).options(selectinload(Product.brand), selectinload(Product.images))
        .where(Product.id.in_(pids))
    )).scalars().all()}
    price_rows = (await db.execute(
        select(ProductPrice).where(ProductPrice.product_id.in_(pids))
    )).scalars().all()
    price_lookup = {pp.product_id: pp for pp in price_rows}

    def _serialize(p: Product) -> dict[str, Any]:
        img = next((i.url for i in sorted(p.images, key=lambda i: (i.sort_order, i.id))), None)
        if img and "photocomingsoon" in img.lower(): img = None
        pp = price_lookup.get(p.id)
        return {
            "id": p.id, "sku": p.sku, "name": p.name,
            "brand": p.brand.name if p.brand else None,
            "image_url": img,
            "retail_price": float(pp.retail_price) if pp and pp.retail_price is not None else None,
            "cost": float(pp.cost) if pp and pp.cost is not None else None,
        }

    total_pending = (await db.execute(
        select(func.count(ProductMatch.id)).where(ProductMatch.status == ProductMatchStatus.PENDING)
    )).scalar_one() or 0

    items = []
    for r in rows:
        a = products.get(r.canonical_product_id)
        b = products.get(r.alias_product_id)
        if not a or not b:
            continue
        items.append({
            "match_id": r.id,
            "score": round(r.score, 3),
            "status": r.status.value,
            "source": r.source.value if hasattr(r.source, "value") else str(r.source),
            "signals": r.signals or {},
            "canonical": _serialize(a),
            "alias": _serialize(b),
        })
    return {"status": status, "items": items, "total_pending": int(total_pending)}


@router.post("/admin/reseller-finder/{match_id}/decide")
async def admin_reseller_decide(
    match_id: int,
    action: str = Query(..., description="confirm | reject | reopen"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Set the match's status. confirm → confirmed; reject → rejected;
    reopen → pending (puts the row back into the queue).
    """
    admin = _require_admin(user)
    from datetime import datetime as _dt, timezone as _tz
    from app.models import ProductMatch, ProductMatchStatus

    next_status = {
        "confirm": ProductMatchStatus.CONFIRMED,
        "reject": ProductMatchStatus.REJECTED,
        "reopen": ProductMatchStatus.PENDING,
    }.get(action)
    if next_status is None:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    m = (await db.execute(select(ProductMatch).where(ProductMatch.id == match_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail=f"Match not found: {match_id}")
    m.status = next_status
    m.decided_by_user_id = admin.id if next_status != ProductMatchStatus.PENDING else None
    m.decided_at = _dt.now(tz=_tz.utc) if next_status != ProductMatchStatus.PENDING else None
    await db.commit()
    return {"match_id": match_id, "status": next_status.value}


@router.get("/admin/reseller-finder/margins")
async def admin_reseller_margins(
    min_gap_pct: float = Query(0.0, ge=0.0, description="Filter to pairs whose retail price gap ≥ this %"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """S2 — margin report. Lists confirmed pairs sorted by retail price gap
    descending. Filterable to "gap ≥ N%" for the re-marketing decision.
    """
    _require_admin(user)
    from app.models import ProductMatch, ProductMatchStatus, ProductPrice

    rows = (await db.execute(
        select(ProductMatch).where(ProductMatch.status == ProductMatchStatus.CONFIRMED)
    )).scalars().all()
    if not rows:
        return {"items": []}

    pids = list({r.canonical_product_id for r in rows} | {r.alias_product_id for r in rows})
    products = {p.id: p for p in (await db.execute(
        select(Product).options(selectinload(Product.brand))
        .where(Product.id.in_(pids))
    )).scalars().all()}
    prices = {pp.product_id: pp for pp in (await db.execute(
        select(ProductPrice).where(ProductPrice.product_id.in_(pids))
    )).scalars().all()}

    items = []
    for r in rows:
        a = products.get(r.canonical_product_id); b = products.get(r.alias_product_id)
        pa = prices.get(r.canonical_product_id); pb = prices.get(r.alias_product_id)
        if not a or not b or not pa or not pb: continue
        ra = pa.retail_price; rb = pb.retail_price
        if ra is None or rb is None: continue
        hi, lo = (ra, rb) if ra >= rb else (rb, ra)
        if lo == 0: continue
        gap_abs = float(hi - lo)
        gap_pct = float((hi - lo) / lo) * 100
        if gap_pct < min_gap_pct: continue
        items.append({
            "match_id": r.id,
            "expensive": {
                "sku": (a if ra >= rb else b).sku,
                "brand": (a if ra >= rb else b).brand.name if (a if ra >= rb else b).brand else None,
                "retail_price": float(hi),
            },
            "cheap": {
                "sku": (a if ra < rb else b).sku,
                "brand": (a if ra < rb else b).brand.name if (a if ra < rb else b).brand else None,
                "retail_price": float(lo),
            },
            "gap_abs": gap_abs,
            "gap_pct": round(gap_pct, 1),
        })
    items.sort(key=lambda i: i["gap_pct"], reverse=True)
    return {"items": items[:limit]}
