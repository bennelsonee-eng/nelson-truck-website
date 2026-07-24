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
    ProductInventory,
)
from app.services.attribute_canonical import auto_canonical
from app.services.channels import ALL_CHANNELS

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


def _bool_cast(v) -> bool:
    return str(v).lower() in ("1", "true", "t", "yes")


# Each overridable field maps to the (effective column, baseline column) it
# materializes, plus a caster turning the stored string `value` into the
# column's Python type. The four hidden_<channel> fields materialize onto the
# per-customer-channel visibility columns; legacy Product.is_hidden is NOT a
# field here — it's recomputed as the AND of the four in resolve_effective.
_FIELD_SPECS = {
    "hidden_retail": {
        "col": Product.is_hidden_retail,
        "base": Product.base_hidden,
        "cast": _bool_cast,
    },
    "hidden_wholesale": {
        "col": Product.is_hidden_wholesale,
        "base": Product.base_hidden,
        "cast": _bool_cast,
    },
    "hidden_dealer": {
        "col": Product.is_hidden_dealer,
        "base": Product.base_hidden,
        "cast": _bool_cast,
    },
    "hidden_municipality": {
        "col": Product.is_hidden_municipality,
        "base": Product.base_hidden,
        "cast": _bool_cast,
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
    changed_pids: set = dc_field(default_factory=set)  # product ids whose derived cols moved


def _cast_instock_only(v) -> bool:
    """True when an override value selects 'Hidden except in-stock' mode."""
    return str(v).strip().lower() == "in_stock_only"


async def _apply_field(db: AsyncSession, field_name: str, col, base, cast, overrides: list[CatalogOverride],
                       extra_where=None) -> set[int]:
    """Materialize one (col, base, cast) from the overrides carrying `field_name`.
    `base` may be a Product column (per-field baseline) or a literal (e.g. False).
    `extra_where`, if given, restricts BOTH the reset and the applies to a subset
    of products (used to leave in-stock-only rows to refresh_instock_only, which
    owns their is_hidden — otherwise this step and the refresh churn each other).
    Returns the set of product ids whose value actually changed (via RETURNING),
    so callers can re-index only what moved.

    The reset step SKIPS rows already covered by a current override — step 2 sets
    those to their exact value, so resetting them to baseline just to re-apply is
    pure wasted writes. That reset→re-apply churn dominated resolve time for large
    hidden / in-stock lines and grew with every line added."""
    changed: set[int] = set()

    field_ovs = [o for o in overrides if o.field == field_name]

    # Resolve each override's scope predicate ONCE (reused by the reset guard and
    # the apply loop), ordered least→most specific so a deeper override wins.
    cat_ids = [o.category_id for o in field_ovs if o.category_id]
    depths = dict((await db.execute(
        select(Category.id, Category.depth).where(Category.id.in_(cat_ids or [-1]))
    )).all()) if cat_ids else {}

    def sort_key(o: CatalogOverride):
        return (_specificity(o), depths.get(o.category_id, 0) if o.category_id else 0)

    scoped = [(ov, await _scope_predicate(db, ov)) for ov in sorted(field_ovs, key=sort_key)]
    covered = [p for _, p in scoped if p is not None]

    # 1. Reset drifted rows to baseline — but NOT rows an override covers (those
    #    are set exactly in step 2; a value already correct there stays put).
    reset_where = [col.is_distinct_from(base)]
    if extra_where is not None:
        reset_where.append(extra_where)
    if covered:
        reset_where.append(~or_(*covered))
    res = await db.execute(
        update(Product).where(*reset_where).values({col: base}).returning(Product.id)
    )
    changed.update(r[0] for r in res)

    # 2. Apply overrides (least→most specific), writing only where the value moves.
    #    is_distinct_from = NULL-safe "not equal", valid for bool/str/numeric alike.
    for ov, pred in scoped:
        if pred is None:
            continue
        target = cast(ov.value)
        apply_where = [pred, col.is_distinct_from(target)]
        if extra_where is not None:
            apply_where.append(extra_where)
        res = await db.execute(
            update(Product).where(*apply_where).values({col: target}).returning(Product.id)
        )
        changed.update(r[0] for r in res)
    return changed


async def refresh_instock_only(db: AsyncSession, product_ids=None) -> set[int]:
    """For products in 'Hidden except in-stock' mode on a channel, set
    is_hidden_<channel> to reflect LIVE stock — hidden iff on_hand <= 0 — so a
    blowout item shows only while in stock and auto-hides when it sells out.

    Optionally scoped to `product_ids` (the inventory sync passes the stock-
    changed set). Does NOT commit (callers do). Returns the ids whose
    is_hidden_<channel> flipped, so the caller can re-index them.
    """
    changed: set[int] = set()
    in_stock = select(ProductInventory.product_id).where(ProductInventory.on_hand > 0)
    ids = list(product_ids) if product_ids is not None else None
    if ids is not None and not ids:
        return changed
    for ch in ALL_CHANNELS:
        col = getattr(Product, f"is_hidden_{ch}")
        oc = getattr(Product, f"instock_only_{ch}")
        target = ~Product.id.in_(in_stock)  # hidden when NOT in stock
        stmt = (
            update(Product)
            .where(oc.is_(True), col.is_distinct_from(target))
            .values({col: target})
            .returning(Product.id)
        )
        if ids is not None:
            stmt = stmt.where(Product.id.in_(ids))
        res = await db.execute(stmt)
        changed.update(r[0] for r in res)
    return changed


async def resolve_effective(db: AsyncSession, *, commit: bool = True) -> ResolveResult:
    """Recompute every derived product column from baselines + overrides, then
    reconcile kit-conflict messages. Commits by default (batch job)."""
    overrides = (await db.execute(select(CatalogOverride))).scalars().all()

    changed_pids: set[int] = set()

    # 1. "Hidden except in-stock" MODE flag per channel FIRST — the is_hidden
    #    materialization below reads it to leave those rows to refresh_instock_only.
    for ch in ALL_CHANNELS:
        changed_pids |= await _apply_field(
            db, f"hidden_{ch}", getattr(Product, f"instock_only_{ch}"),
            False, _cast_instock_only, overrides,
        )

    # 2. Every field: is_hidden_<channel> (EXCLUDING in_stock_only rows, whose
    #    is_hidden is owned by refresh_instock_only below — otherwise this step
    #    sets them false and the refresh sets them true, churning every resolve),
    #    plus the global shipping_mode / flat_ship_amount.
    for field_name, spec in _FIELD_SPECS.items():
        extra = None
        if field_name.startswith("hidden_"):
            extra = ~getattr(Product, f"instock_only_{field_name[len('hidden_'):]}")
        changed_pids |= await _apply_field(
            db, field_name, spec["col"], spec["base"], spec["cast"], overrides, extra_where=extra
        )

    # 3. Fold LIVE stock into is_hidden_<channel> for in_stock_only products
    #    (hidden iff on_hand<=0) so a blowout item shows only while in stock.
    changed_pids |= await refresh_instock_only(db)

    # Recompute legacy Product.is_hidden = "hidden from EVERY channel" (AND of
    # the four per-channel columns) so admin/internal "fully hidden" reads
    # (kit-conflict, admin tree) stay correct. Only touch rows that changed.
    fully_hidden = and_(
        Product.is_hidden_retail,
        Product.is_hidden_wholesale,
        Product.is_hidden_dealer,
        Product.is_hidden_municipality,
    )
    _legacy = await db.execute(
        update(Product)
        .where(Product.is_hidden.is_distinct_from(fully_hidden))
        .values(is_hidden=fully_hidden)
        .returning(Product.id)
    )
    changed_pids.update(r[0] for r in _legacy)

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
        changed_pids=changed_pids,
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
