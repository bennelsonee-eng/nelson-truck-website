"""Typesense indexing + search service.

Maintains a single `products` collection. Reindex bulk-loads all products
from the DB; on-demand updates patch single documents.

Stock-aware ranking: products with on_hand > 0 get a `stock_score` boost
so they sort ahead of out-of-stock items at the same relevance.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any, Callable, Iterable

import typesense
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Brand, Category, Product, ProductCategory, ProductImage, ProductInventory


__all__ = [
    "client",
    "PRODUCTS_SCHEMA",
    "ensure_collection",
    "reindex_all_products",
    "search_products",
]


log = logging.getLogger(__name__)

settings = get_settings()

# Typesense collection name (config-driven so Nelson can share an instance with
# Titan without index collisions — see config.typesense_collection).
COLLECTION = settings.typesense_collection

# Process-level Typesense reachability flag. Probed once at first call;
# if Typesense is unreachable, every subsequent search_products() raises
# immediately so the catalog router can fall through to its DB-direct path
# without burning connection time on retries.
_typesense_reachable: bool | None = None  # None = not yet probed
_TYPESENSE_PROBE_PORT_TIMEOUT = 0.5  # half-second TCP probe


def client() -> typesense.Client:
    # Fast-fail if Typesense is unreachable. Was 30s — that meant catalog
    # endpoints would stall for 30 sec waiting for retries when Typesense
    # is down. Reduced to 2s so the DB-direct fallback fires quickly.
    return typesense.Client({
        "nodes": [{
            "host": settings.typesense_host,
            "port": settings.typesense_port,
            "protocol": settings.typesense_protocol,
        }],
        "api_key": settings.typesense_api_key,
        "connection_timeout_seconds": 2,
        "num_retries": 1,
        "retry_interval_seconds": 0.5,
    })


PRODUCTS_SCHEMA = {
    "name": COLLECTION,
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "sku", "type": "string", "facet": False, "infix": True},
        {"name": "name", "type": "string"},
        {"name": "description", "type": "string", "optional": True},
        {"name": "brand_name", "type": "string", "facet": True},
        {"name": "prod_code", "type": "string", "facet": True, "optional": True},
        {"name": "in_stock", "type": "bool", "facet": True},
        {"name": "stock_total", "type": "int32"},
        {"name": "stock_score", "type": "float"},  # ranking boost field
        {"name": "is_hidden", "type": "bool", "facet": True},
        {"name": "is_for_sale", "type": "bool", "facet": True},
        {"name": "cta_mode", "type": "string", "facet": True},
        {"name": "weight_lb", "type": "float", "optional": True},
        {"name": "freight_class", "type": "string", "facet": True, "optional": True},
        {"name": "created_at_unix", "type": "int64"},
        # Display + facet fields populated from WSM details import.
        # category_paths is the array of every ancestor path so we can
        # filter "products under Truck Equipment > Snow Plows/Spreaders"
        # with an exact-match facet against any intermediate level.
        {"name": "image_url", "type": "string", "optional": True},
        {"name": "category_path", "type": "string", "optional": True},          # leaf full_path (display)
        {"name": "category_paths", "type": "string[]", "facet": True, "optional": True},  # all ancestors
        {"name": "category_top", "type": "string", "facet": True, "optional": True},
        # Customer channels allowed to see this product. Every product carries
        # all four; a kit narrows it to the channels its admin enabled, so a
        # filter `allowed_channels:=<viewer channel>` hides channel-restricted
        # kits from disallowed visitors entirely (not just on the PDP).
        {"name": "allowed_channels", "type": "string[]", "facet": True, "optional": True},
        # Fitment (error report #21): the VCDB base_vehicle_ids this product
        # fits, so a vehicle parsed out of the search text can filter results
        # to "fits this truck or is universal". `has_no_fitment` mirrors the
        # Product flag the DB browse path uses for universal/PIES-only parts.
        {"name": "has_no_fitment", "type": "bool", "facet": True, "optional": True},
        {"name": "fit_base_vehicle_ids", "type": "int64[]", "facet": False, "optional": True},
    ],
    "default_sorting_field": "stock_score",
}

ALL_CHANNELS = ["retail", "wholesale", "dealer", "municipality"]


def ensure_collection() -> None:
    """Create the `products` collection if it doesn't exist."""
    c = client()
    try:
        existing = c.collections[COLLECTION].retrieve()
        log.info("Typesense `products` collection exists (%d docs)", existing["num_documents"])
    except typesense.exceptions.ObjectNotFound:
        log.info("Creating Typesense `products` collection…")
        c.collections.create(PRODUCTS_SCHEMA)
        log.info("Created.")


def drop_collection() -> None:
    """Drop the products collection (for clean reindex)."""
    c = client()
    try:
        c.collections[COLLECTION].delete()
        log.info("Dropped `products` collection")
    except typesense.exceptions.ObjectNotFound:
        pass


def _doc_for_product(
    p: Product,
    brand_name: str,
    stock_total: int,
    image_url: str | None = None,
    category_path: str | None = None,
    allowed_channels: list[str] | None = None,
    fit_vehicle_ids: list[int] | None = None,
) -> dict[str, Any]:
    in_stock = stock_total > 0
    # Per-customer-channel visibility: a product hidden from a channel via the
    # admin catalog tree (Product.is_hidden_<channel>) drops that channel here,
    # so the storefront's `allowed_channels:=<viewer channel>` filter hides it
    # for that audience with no extra query. Then intersect with the kit-channel
    # list (`allowed_channels` arg): None = not a kit / unrestricted; an explicit
    # [] is a kit hidden right now (inactive / out-of-window) and must stay empty
    # so the filter excludes it — the intersection preserves that.
    visible_channels = [c for c in ALL_CHANNELS if not getattr(p, f"is_hidden_{c}", False)]
    if allowed_channels is not None:
        visible_channels = [c for c in visible_channels if c in allowed_channels]
    doc: dict[str, Any] = {
        "allowed_channels": visible_channels,
        "id": str(p.id),
        "sku": p.sku,
        "name": p.name,
        "description": (p.description or "")[:5000],
        "brand_name": brand_name,
        "prod_code": p.prod_code or "",
        "in_stock": in_stock,
        "stock_total": int(stock_total),
        # stock_score: in-stock items get a baseline of 100; OOS get 0.
        # Within the same status, more stock = slightly higher score.
        "stock_score": 100.0 + min(50.0, stock_total * 0.5) if in_stock else 0.0,
        "is_hidden": bool(p.is_hidden),
        "is_for_sale": bool(p.is_for_sale),
        "cta_mode": str(p.cta_mode.value) if hasattr(p.cta_mode, "value") else str(p.cta_mode),
        "weight_lb": float(p.weight_lb) if p.weight_lb else 0.0,
        "freight_class": p.freight_class or "",
        "created_at_unix": int(p.created_at.timestamp()),
        "has_no_fitment": bool(getattr(p, "has_no_fitment", False)),
    }
    if fit_vehicle_ids:
        doc["fit_base_vehicle_ids"] = fit_vehicle_ids
    if image_url:
        doc["image_url"] = image_url
    if category_path:
        doc["category_path"] = category_path
        # Top-of-tree facet (e.g., "Truck Accessories") for navigation tiles
        doc["category_top"] = category_path.split(">", 1)[0].strip()
        # Expand to every ancestor path so we can exact-match-filter at any
        # depth (e.g. clicking "Truck Equipment > Snow Plows/Spreaders" must
        # surface the leaf-level products tagged with paths underneath it).
        parts = [p.strip() for p in category_path.split(">") if p.strip()]
        doc["category_paths"] = [
            ">".join(parts[: i + 1]) for i in range(len(parts))
        ]
    return doc


async def reindex_all_products(db: AsyncSession, *, drop_first: bool = False) -> int:
    """Bulk-reindex all products from the DB into Typesense.

    Returns the number of documents indexed.
    """
    if drop_first:
        drop_collection()
    ensure_collection()
    c = client()
    coll = c.collections[COLLECTION].documents

    # Pre-load brand names + per-product total inventory + primary image + primary category
    log.info("Loading brand names + inventory totals + images + categories…")
    brand_lookup = {b.id: b.name for b in (await db.execute(select(Brand))).scalars().all()}
    inv_stmt = select(
        ProductInventory.product_id,
        func.sum(ProductInventory.on_hand).label("total"),
    ).group_by(ProductInventory.product_id)
    inv_rows = (await db.execute(inv_stmt)).all()
    stock_lookup = {pid: int(total or 0) for pid, total in inv_rows}

    # Primary image per product (sort_order ASC, first one wins).  Single
    # query with DISTINCT ON to keep memory low across 200K products.
    img_stmt = (
        select(ProductImage.product_id, ProductImage.url)
        .order_by(ProductImage.product_id, ProductImage.sort_order, ProductImage.id)
        .distinct(ProductImage.product_id)
    )
    image_lookup = {pid: url for pid, url in (await db.execute(img_stmt)).all()}

    # Primary category path (the row marked is_primary=True; first one wins)
    cat_stmt = (
        select(ProductCategory.product_id, Category.full_path)
        .join(Category, Category.id == ProductCategory.category_id)
        .where(ProductCategory.is_primary.is_(True))
        .order_by(ProductCategory.product_id, ProductCategory.id)
        .distinct(ProductCategory.product_id)
    )
    category_lookup = {pid: path for pid, path in (await db.execute(cat_stmt)).all()}

    # Fitment map: product_id -> sorted list of base_vehicle_ids it fits, via
    # pace_part -> pace_fitment (same join the DB browse path uses). ~2.1M
    # (product, vehicle) pairs; built once with sets to dedup products that
    # reach the same vehicle through multiple pace_parts. Powers the search
    # bar's "fits this truck" filter (error report #21).
    from app.models import PaceFitment, PacePart
    fit_stmt = (
        select(PacePart.product_id, PaceFitment.base_vehicle_id)
        .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
        .where(PacePart.product_id.is_not(None))
    )
    fit_sets: dict[int, set[int]] = {}
    for pid, bvid in (await db.execute(fit_stmt)).all():
        if bvid is not None:
            fit_sets.setdefault(pid, set()).add(bvid)
    fit_lookup = {pid: sorted(s) for pid, s in fit_sets.items()}
    del fit_sets

    # Kit channel availability — a kit narrows its package product's channels to
    # the ones it's live for RIGHT NOW (inactive or outside its availability
    # window -> [] -> hidden everywhere). Computed for ALL kits, not just active
    # ones, so an inactive/expired kit's product is explicitly hidden (omitting
    # it would default to all-channels = visible).
    from app.models import Kit
    from app.services.kit_inventory import kit_enabled_channels
    _today = datetime.date.today()
    kit_rows = (await db.execute(
        select(Kit.product_id, Kit.is_active, Kit.available_from, Kit.available_until,
               Kit.avail_retail, Kit.avail_wholesale, Kit.avail_dealer, Kit.avail_municipality)
        .where(Kit.product_id.is_not(None))
    )).all()
    channel_lookup: dict[int, list[str]] = {}
    for pid, is_active, af, au, av_r, av_w, av_d, av_m in kit_rows:
        channel_lookup[pid] = kit_enabled_channels(
            is_active=is_active, available_from=af, available_until=au,
            avail_retail=av_r, avail_wholesale=av_w, avail_dealer=av_d,
            avail_municipality=av_m, today=_today)

    log.info("  %d brands, %d w/inventory, %d w/images, %d w/categories, %d kits",
             len(brand_lookup), len(stock_lookup), len(image_lookup),
             len(category_lookup), len(channel_lookup))

    # Stream products in chunks; bulk-import to Typesense per chunk
    log.info("Building docs + indexing…")
    PAGE_SIZE = 1000
    indexed = 0
    last_id = 0
    while True:
        stmt = (
            select(Product)
            .where(Product.id > last_id)
            .order_by(Product.id)
            .limit(PAGE_SIZE)
        )
        rows = (await db.execute(stmt)).scalars().all()
        if not rows:
            break

        docs = [
            _doc_for_product(
                p,
                brand_lookup.get(p.brand_id, "Unknown"),
                stock_lookup.get(p.id, 0),
                image_url=image_lookup.get(p.id),
                category_path=category_lookup.get(p.id),
                allowed_channels=channel_lookup.get(p.id),
                fit_vehicle_ids=fit_lookup.get(p.id),
            )
            for p in rows
        ]
        # Typesense bulk import — JSONL format
        coll.import_(docs, {"action": "upsert"})
        indexed += len(docs)
        last_id = rows[-1].id

        if indexed % 10000 == 0:
            log.info("  …%d indexed", indexed)

    log.info("Reindexed %d products", indexed)
    return indexed


async def index_products(
    db: AsyncSession,
    product_ids: list[int],
    *,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """Re-index specific products by id. Gathers all lookup data ONCE (inventory,
    images, categories, kit channels, fitment) then imports to Typesense in
    chunks, so a large set is a single round of DB queries (not per-chunk). If
    `progress` is given it's called with (done, total) after each import chunk —
    used to drive the Apply-now progress bar. Best-effort: swallows Typesense
    errors so a save never fails on a search hiccup. Returns docs upserted."""
    if not product_ids:
        return 0
    if not _probe_typesense():
        return 0
    from app.models import Kit
    prods = (await db.execute(
        select(Product).where(Product.id.in_(product_ids))
    )).scalars().all()
    if not prods:
        return 0
    brand_lookup = {b.id: b.name for b in (await db.execute(select(Brand))).scalars().all()}
    inv = (await db.execute(
        select(ProductInventory.product_id, func.sum(ProductInventory.on_hand))
        .where(ProductInventory.product_id.in_(product_ids))
        .group_by(ProductInventory.product_id)
    )).all()
    stock_lookup = {pid: int(t or 0) for pid, t in inv}
    imgs = (await db.execute(
        select(ProductImage.product_id, ProductImage.url)
        .where(ProductImage.product_id.in_(product_ids))
        .order_by(ProductImage.product_id, ProductImage.sort_order, ProductImage.id)
        .distinct(ProductImage.product_id)
    )).all()
    image_lookup = {pid: url for pid, url in imgs}
    cats = (await db.execute(
        select(ProductCategory.product_id, Category.full_path)
        .join(Category, Category.id == ProductCategory.category_id)
        .where(ProductCategory.product_id.in_(product_ids), ProductCategory.is_primary.is_(True))
        .order_by(ProductCategory.product_id, ProductCategory.id)
        .distinct(ProductCategory.product_id)
    )).all()
    category_lookup = {pid: path for pid, path in cats}
    from app.services.kit_inventory import kit_enabled_channels
    _today = datetime.date.today()
    kit_rows = (await db.execute(
        select(Kit.product_id, Kit.is_active, Kit.available_from, Kit.available_until,
               Kit.avail_retail, Kit.avail_wholesale, Kit.avail_dealer, Kit.avail_municipality)
        .where(Kit.product_id.in_(product_ids))
    )).all()
    channel_lookup = {
        pid: kit_enabled_channels(
            is_active=ia, available_from=af, available_until=au,
            avail_retail=r, avail_wholesale=w, avail_dealer=d, avail_municipality=m, today=_today)
        for pid, ia, af, au, r, w, d, m in kit_rows
    }
    from app.models import PaceFitment, PacePart
    fit_rows = (await db.execute(
        select(PacePart.product_id, PaceFitment.base_vehicle_id)
        .join(PaceFitment, PaceFitment.pace_part_id == PacePart.id)
        .where(PacePart.product_id.in_(product_ids))
    )).all()
    fit_sets: dict[int, set[int]] = {}
    for pid, bvid in fit_rows:
        if bvid is not None:
            fit_sets.setdefault(pid, set()).add(bvid)
    fit_lookup = {pid: sorted(s) for pid, s in fit_sets.items()}
    docs = [
        _doc_for_product(
            p, brand_lookup.get(p.brand_id, "Unknown"), stock_lookup.get(p.id, 0),
            image_url=image_lookup.get(p.id), category_path=category_lookup.get(p.id),
            allowed_channels=channel_lookup.get(p.id),
            fit_vehicle_ids=fit_lookup.get(p.id),
        )
        for p in prods
    ]
    # All the expensive gathering above ran ONCE for the whole id set. Only the
    # Typesense import is chunked — each chunk in a worker thread so the event
    # loop keeps serving status polls (and other requests) during a big reindex.
    total = len(docs)
    coll = client().collections[COLLECTION].documents
    IMPORT_CHUNK = 2000
    for i in range(0, total, IMPORT_CHUNK):
        try:
            await asyncio.to_thread(coll.import_, docs[i:i + IMPORT_CHUNK], {"action": "upsert"})
        except Exception:
            log.exception("index_products upsert chunk failed (non-fatal)")
        if progress is not None:
            progress(min(i + IMPORT_CHUNK, total), total)
    return total


def _probe_typesense() -> bool:
    """Half-second TCP probe to see if Typesense is even listening.
    Caches the result process-wide so we only pay this cost once.
    """
    global _typesense_reachable
    if _typesense_reachable is not None:
        return _typesense_reachable
    import socket
    try:
        with socket.create_connection(
            (settings.typesense_host, settings.typesense_port),
            timeout=_TYPESENSE_PROBE_PORT_TIMEOUT,
        ):
            _typesense_reachable = True
    except (OSError, socket.timeout):
        log.warning("Typesense unreachable at %s:%s — catalog routes will use "
                    "DB-direct fallback for search", settings.typesense_host,
                    settings.typesense_port)
        _typesense_reachable = False
    return _typesense_reachable


def search_products(
    *,
    query: str | None = None,
    brand: str | None = None,
    category_top: str | None = None,
    category_path: str | None = None,
    in_stock_only: bool = False,
    cta_mode: str | None = None,
    page: int = 1,
    per_page: int = 24,
    sort_by: str | None = None,
    query_by: str | None = None,
    infix: str | None = None,
    facet_by: str | None = None,
    channel: str | None = None,
    fit_base_vehicle_id: int | None = None,
) -> dict[str, Any]:
    """Search the products collection.

    Returns Typesense's response dict (hits, found, page, search_time_ms…).
    Raises ConnectionError immediately if Typesense isn't reachable so callers
    can fall through to a DB-direct path without burning retry budget.
    """
    if not _probe_typesense():
        raise ConnectionError("Typesense unreachable — fast-fail")
    c = client()
    filters: list[str] = ["is_hidden:false", "is_for_sale:true"]
    # Always apply the channel filter (default retail for un-channeled callers)
    # so per-channel-hidden products and channel-restricted kits never leak to
    # the wrong audience. Every product carries its visible channels in
    # `allowed_channels`, so unrestricted products match their own channels.
    filters.append(f"allowed_channels:={channel or 'retail'}")
    if brand:
        filters.append(f"brand_name:={brand}")
    if in_stock_only:
        filters.append("in_stock:=true")
    if cta_mode:
        filters.append(f"cta_mode:={cta_mode}")
    if category_top:
        filters.append(f"category_top:={category_top}")
    if category_path:
        # Filter against the multi-value `category_paths` array so passing an
        # intermediate level (e.g. "Truck Equipment>Snow Plows/Spreaders")
        # matches every leaf product tagged with a deeper path.
        filters.append(f"category_paths:={category_path}")
    if fit_base_vehicle_id is not None:
        # Vehicle parsed out of the search text (error report #21): keep only
        # products that fit this base_vehicle_id OR carry no ACES fitment at
        # all (universal / PIES-only) — mirrors the DB browse path's
        # base_vehicle_id three-way OR. Parenthesised so it ANDs as one clause.
        filters.append(
            f"(fit_base_vehicle_ids:={fit_base_vehicle_id} || has_no_fitment:=true)"
        )

    # Default query_by ranks part-number fields ahead of free text so a
    # numeric query ("52032") preferentially hits SKU / prod_code. Field
    # weights derived from the per-field defaults below so an explicit
    # `query_by="sku"` call doesn't crash with a weights-count mismatch.
    effective_query_by = query_by or "sku,prod_code,name,brand_name,description"
    _field_weights = {
        "sku": "10",
        "prod_code": "5",
        "name": "3",
        "brand_name": "2",
        "description": "1",
    }
    weights = ",".join(
        _field_weights.get(f.strip(), "1")
        for f in effective_query_by.split(",")
    )
    params: dict[str, Any] = {
        "q": query or "*",
        "query_by": effective_query_by,
        "query_by_weights": weights,  # matches arity of query_by
        "filter_by": " && ".join(filters),
        # `facet_by` is overridable so the autocomplete dropdown can swap
        # in `category_paths` (every ancestor level) instead of the default
        # `category_top` (parent only) — owner ask 2026-05-17 to surface
        # subcategories like "Automotive Lighting > Emergency and Warning
        # Lighting" in place of bare "Truck Accessories" in suggestions.
        "facet_by": facet_by or "brand_name,in_stock,cta_mode,category_top",
        "sort_by": sort_by or "stock_score:desc,_text_match:desc",
        "per_page": min(per_page, 250),
        "page": max(page, 1),
    }
    if infix:
        # Enable infix-match against the `sku` field so "52032" matches the
        # "BHTJ-52032" Husky Liners legacy SKU prefix. Other fields are
        # 'off' (Typesense requires one value per query_by field).
        n_fields = len([f for f in params["query_by"].split(",") if f.strip()])
        params["infix"] = ",".join(
            [infix if f.strip() == "sku" else "off"
             for f in params["query_by"].split(",")]
        )
        # Avoid double-counting fuzzy: when an infix match is found, be strict
        # on typos so "52032" doesn't also fuzzy-match "5202".
        params["num_typos"] = 0
    return c.collections[COLLECTION].documents.search(params)
