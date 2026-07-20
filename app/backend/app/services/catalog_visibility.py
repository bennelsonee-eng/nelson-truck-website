"""Catalog override resolver + kit-conflict detection.

Folds the whole `catalog_override` set down onto the derived product columns
(`Product.is_hidden`, `Product.shipping_mode`). Every existing surface reads
those columns, so materializing them here is all that's needed — nothing
downstream changes.

Per field, precedence is encoded by APPLICATION ORDER (later writes win):
    baseline → brand → category (shallow→deep) → filter → product
so the most-specific override always wins. For the `hidden` field, value
"false" is an explicit SHOW that punches through a broader hide (or baseline).

Run at the nightly re-index and on "Apply now". After resolving, reconcile
kit-conflict messages: any hidden part still used by an ACTIVE kit raises an
`admin_message`; showing it again auto-resolves that message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, distinct, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AdminMessage,
    AttributeValueAlias,
    Category,
    CatalogOverride,
    Kit,
    KitComponent,
    Product,
    ProductAttribute,
    ProductCategory,
)
from app.services.attribute_canonical import auto_canonical

log = logging.getLogger("catalog_visibility")

SCOPE_TYPES = ("brand", "category", "product", "filter")


def _to_decimal_or_none(v) -> Decimal | None:
    """Cast an override value to a money Decimal. Empty/blank/'none' -> NULL
    (fall back to the weight-tiered calc)."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("none", "null"):
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


# Each overridable field maps to the (effective column, baseline column) it
# materializes, plus a caster turning the stored string `value` into the
# column's Python type.
_FIELD_SPECS = {
    "hidden": {
        "col": Product.is_hidden,
        "base": Product.base_hidden,
        "cast": lambda v: str(v).lower() in ("1", "true", "t", "yes"),
    },
    "shipping_mode": {
        "col": Product.shipping_mode,
        "base": Product.base_shipping_mode,
        "cast": lambda v: str(v),
    },
    "flat_ship_amount": {
        "col": Product.flat_ship_amount,
        "base": Product.base_flat_ship_amount,
        "cast": _to_decimal_or_none,
    },
}


# --------------------------------------------------------------------------- #
# scope_key — deterministic identity so a repeat toggle upserts
# --------------------------------------------------------------------------- #

def scope_key_for(
    scope_type: str | None = None,
    *,
    brand_id: int | None = None,
    category_id: int | None = None,
    product_id: int | None = None,
    attr_key: str | None = None,
    attr_value: str | None = None,
) -> str:
    """Deterministic identity for a scope, built from whichever dimensions are
    set. The tree is rooted at a manufacturer line and narrows downward, so a
    scope is the AND of its dimensions (e.g. brand=80 AND category=123 = "this
    line within this category"). A product scope wins outright. `scope_type` is
    an optional descriptive hint (see derive_scope_type) — the key is computed
    from the dimensions regardless."""
    if product_id is not None:
        return f"product:{product_id}"
    parts: list[str] = []
    if brand_id is not None:
        parts.append(f"brand={brand_id}")
    if category_id is not None:
        parts.append(f"category={category_id}")
    if attr_key:
        parts.append(f"attr={attr_key}={attr_value}")
    if not parts:
        raise ValueError("scope has no target dimensions")
    return "scope:" + "|".join(parts)


def derive_scope_type(
    *,
    brand_id: int | None = None,
    category_id: int | None = None,
    product_id: int | None = None,
    attr_key: str | None = None,
) -> str:
    """The deepest dimension present — a label for display/ordering only."""
    if product_id is not None:
        return "product"
    if attr_key:
        return "filter"
    if category_id is not None:
        return "category"
    if brand_id is not None:
        return "brand"
    raise ValueError("scope has no target dimensions")


# --------------------------------------------------------------------------- #
# Scope → product-id resolvers
# --------------------------------------------------------------------------- #

async def _descendant_category_ids(db: AsyncSession, category_id: int) -> list[int]:
    """The category plus every descendant, via the materialized full_path."""
    row = (await db.execute(
        select(Category.full_path).where(Category.id == category_id)
    )).scalar_one_or_none()
    if row is None:
        return []
    like_pattern = f"{row} > %"
    ids = (await db.execute(
        select(Category.id).where(
            or_(Category.full_path == row, Category.full_path.like(like_pattern))
        )
    )).scalars().all()
    return list(ids)


async def _category_product_ids_select(db: AsyncSession, category_id: int):
    """Scalar subquery of product_ids in a category subtree (any assignment —
    mirrors the browse resolver)."""
    cat_ids = await _descendant_category_ids(db, category_id)
    if not cat_ids:
        return None
    return select(distinct(ProductCategory.product_id)).where(
        ProductCategory.category_id.in_(cat_ids)
    )


async def _filter_raw_values(db: AsyncSession, attr_key: str, canonical_value: str) -> list[str]:
    """Resolve a CURATED canonical value back to the raw PIES values it matches
    — identical logic to the storefront left-rail filter (catalog.py): manual
    aliases first, then an auto_canonical fallback over the remaining raws."""
    canonical_set = {canonical_value}

    manual_rows = (await db.execute(
        select(AttributeValueAlias.raw_value)
        .where(AttributeValueAlias.attribute_key == attr_key)
        .where(AttributeValueAlias.canonical_value == canonical_value)
        .where(AttributeValueAlias.source == "manual")
    )).scalars().all()
    wanted: set[str] = set(manual_rows)
    manual_keyed = set(manual_rows)

    all_manual = set((await db.execute(
        select(AttributeValueAlias.raw_value)
        .where(AttributeValueAlias.attribute_key == attr_key)
        .where(AttributeValueAlias.source == "manual")
    )).scalars().all())

    distinct_raws = (await db.execute(
        select(distinct(ProductAttribute.attribute_value))
        .where(ProductAttribute.attribute_key == attr_key)
        .where(ProductAttribute.attribute_value.is_not(None))
        .where(ProductAttribute.attribute_value != "")
    )).scalars().all()
    for raw in distinct_raws:
        if raw in all_manual and raw not in manual_keyed:
            continue  # curator pinned this raw to a different canonical
        if auto_canonical(raw) in canonical_set:
            wanted.add(raw)
    return list(wanted)


async def _attr_product_ids_select(db: AsyncSession, attr_key: str, attr_value: str):
    """Scalar subquery of product_ids carrying a CURATED (key, canonical value),
    unbounded by scope. None if nothing matches."""
    raws = await _filter_raw_values(db, attr_key, attr_value)
    if not raws:
        return None
    return select(distinct(ProductAttribute.product_id)).where(
        ProductAttribute.attribute_key == attr_key,
        ProductAttribute.attribute_value.in_(raws),
    )


async def _scope_predicate(db: AsyncSession, ov: CatalogOverride):
    """A Product predicate = AND of every dimension this override carries
    (brand ∩ category ∩ filter ∩ product). None if a dimension resolves to
    nothing (caller skips)."""
    preds = []
    if ov.product_id is not None:
        preds.append(Product.id == ov.product_id)
    if ov.brand_id is not None:
        preds.append(Product.brand_id == ov.brand_id)
    if ov.category_id is not None:
        sel = await _category_product_ids_select(db, ov.category_id)
        if sel is None:
            return None
        preds.append(Product.id.in_(sel))
    if ov.attr_key and ov.attr_value is not None:
        sel = await _attr_product_ids_select(db, ov.attr_key, ov.attr_value)
        if sel is None:
            return None
        preds.append(Product.id.in_(sel))
    if not preds:
        return None
    return and_(*preds)


def _specificity(ov: CatalogOverride) -> int:
    """Higher = more specific = applied LATER (wins). A product scope wins
    outright; otherwise more dimensions = more specific."""
    if ov.product_id is not None:
        return 1000
    s = 0
    if ov.brand_id is not None:
        s += 1
    if ov.category_id is not None:
        s += 10
    if ov.attr_key:
        s += 100
    return s


# --------------------------------------------------------------------------- #
# Resolver
# --------------------------------------------------------------------------- #

@dataclass
class ResolveResult:
    overrides: int
    hidden_total: int
    kit_conflicts_open: int
    kit_conflicts_resolved: int
    per_field: dict = dc_field(default_factory=dict)


async def _apply_field(db: AsyncSession, field_name: str, overrides: list[CatalogOverride]) -> None:
    spec = _FIELD_SPECS[field_name]
    col, base, cast = spec["col"], spec["base"], spec["cast"]

    # 1. Reset drifted rows to baseline (tiny write in the common case).
    await db.execute(
        update(Product).where(col.is_distinct_from(base)).values({col: base})
    )

    # 2. Apply overrides for this field, least→most specific (specificity), with
    #    deeper categories applied later so a deeper override still wins.
    field_ovs = [o for o in overrides if o.field == field_name]
    cat_ids = [o.category_id for o in field_ovs if o.category_id]
    depths = dict((await db.execute(
        select(Category.id, Category.depth).where(Category.id.in_(cat_ids or [-1]))
    )).all()) if cat_ids else {}

    def sort_key(o: CatalogOverride):
        return (_specificity(o), depths.get(o.category_id, 0) if o.category_id else 0)

    for ov in sorted(field_ovs, key=sort_key):
        pred = await _scope_predicate(db, ov)
        if pred is None:
            continue
        target = cast(ov.value)
        # is_distinct_from = NULL-safe "not equal", valid for bool/str/numeric
        # alike (col.is_not(x) only works for NULL/bool operands in Postgres).
        await db.execute(
            update(Product).where(pred, col.is_distinct_from(target)).values({col: target})
        )


async def resolve_effective(db: AsyncSession, *, commit: bool = True) -> ResolveResult:
    """Recompute every derived product column from baselines + overrides, then
    reconcile kit-conflict messages. Commits by default (batch job)."""
    overrides = (await db.execute(select(CatalogOverride))).scalars().all()

    for field_name in _FIELD_SPECS:
        await _apply_field(db, field_name, overrides)

    # Stamp every override as applied so the UI can show "pending until tonight"
    # for any toggle made after the last resolve (updated_at > applied_at).
    await db.execute(update(CatalogOverride).values(applied_at=func.now()))

    hidden_total = (await db.execute(
        select(func.count()).select_from(Product).where(Product.is_hidden.is_(True))
    )).scalar_one()

    opened, resolved = await reconcile_kit_conflicts(db)

    if commit:
        await db.commit()

    per_field = {
        f: len([o for o in overrides if o.field == f]) for f in _FIELD_SPECS
    }
    log.info(
        "catalog overrides resolved: %d total %s, %d hidden, kit conflicts +%d/-%d",
        len(overrides), per_field, hidden_total, opened, resolved,
    )
    return ResolveResult(
        overrides=len(overrides),
        hidden_total=hidden_total,
        kit_conflicts_open=opened,
        kit_conflicts_resolved=resolved,
        per_field=per_field,
    )


# Backwards-compatible alias (Phase 1 name).
resolve_effective_hidden = resolve_effective


# --------------------------------------------------------------------------- #
# Kit-conflict reconciliation
# --------------------------------------------------------------------------- #

async def reconcile_kit_conflicts(db: AsyncSession) -> tuple[int, int]:
    """Raise an admin_message for every hidden part that is a component of an
    ACTIVE kit, and auto-resolve messages whose part is no longer hidden.

    Reads Product.is_hidden as already resolved. Does not commit (caller does).
    Returns (opened_or_bumped, resolved)."""
    rows = (await db.execute(
        select(
            Kit.id, Kit.sku, Kit.name,
            Product.id, Product.sku, Product.name,
            KitComponent.quantity,
        )
        .select_from(KitComponent)
        .join(Kit, Kit.id == KitComponent.kit_id)
        .join(Product, Product.id == KitComponent.product_id)
        .where(Kit.is_active.is_(True), Product.is_hidden.is_(True))
    )).all()

    live_keys: set[str] = set()
    opened = 0
    for kit_id, kit_sku, kit_name, pid, psku, pname, qty in rows:
        dk = f"kit_conflict:{kit_id}:{pid}"
        live_keys.add(dk)
        existing = (await db.execute(
            select(AdminMessage).where(AdminMessage.dedupe_key == dk)
        )).scalar_one_or_none()
        title = f"Hidden part {psku} breaks kit {kit_sku}"
        body = (
            f"Part “{pname}” ({psku}) is hidden but is still a component "
            f"(qty {qty}) of the active kit “{kit_name}” ({kit_sku}). "
            f"The package will be incomplete or unbuildable until the part is "
            f"shown again or removed from the kit."
        )
        ctx = {
            "kit_id": kit_id, "kit_sku": kit_sku,
            "product_id": pid, "product_sku": psku, "quantity": qty,
        }
        if existing is None:
            db.add(AdminMessage(
                kind="kit_conflict", severity="warning", status="open",
                title=title, body=body, context=ctx, dedupe_key=dk,
                first_seen=func.now(), last_seen=func.now(), occurrences=1,
            ))
            opened += 1
        else:
            existing.title = title
            existing.body = body
            existing.context = ctx
            existing.last_seen = func.now()
            existing.occurrences = (existing.occurrences or 0) + 1
            if existing.status == "resolved":
                existing.status = "open"
                existing.resolved_by = None
                existing.resolved_at = None
            opened += 1

    open_msgs = (await db.execute(
        select(AdminMessage).where(
            AdminMessage.kind == "kit_conflict",
            AdminMessage.status != "resolved",
        )
    )).scalars().all()
    resolved = 0
    for m in open_msgs:
        if m.dedupe_key not in live_keys:
            m.status = "resolved"
            m.resolved_by = "system"
            m.resolved_at = func.now()
            resolved += 1

    return opened, resolved
