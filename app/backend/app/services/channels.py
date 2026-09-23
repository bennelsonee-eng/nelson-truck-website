"""Customer-channel helpers shared across the storefront.

A "channel" is the visibility/pricing audience a viewer belongs to — one of
``ALL_CHANNELS``. It is resolved server-side from the viewer's customer tier
(honoring admin "Shop as Customer" impersonation); anonymous/bot traffic is
``retail``.

Per-channel product visibility lives on ``Product.is_hidden_<channel>``
(materialized by the catalog-visibility resolver from ``base_hidden_<channel>``
+ per-channel overrides). ``visible_to_channel_clause()`` is the storefront read
predicate every customer-facing query ANDs into its WHERE; ``tier_to_channel`` /
``viewer_channel`` classify the current request.

This module is the single home for the channel vocabulary so routers
(catalog, seo, deweze, fitment, pace) don't import it from each other.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models import Customer, CustomerTier, Product, ProductInventory, User

# Canonical customer channels. "wholesale" IS the jobber channel. Keep in sync
# with search.ALL_CHANNELS (kit availability), the four Product.is_hidden_*
# columns, and the hidden_<channel> override fields.
ALL_CHANNELS: tuple[str, ...] = ("retail", "wholesale", "dealer", "municipality")

# channel -> the Product column carrying its effective visibility.
_CHANNEL_HIDDEN_COL = {
    "retail": Product.is_hidden_retail,
    "wholesale": Product.is_hidden_wholesale,
    "dealer": Product.is_hidden_dealer,
    "municipality": Product.is_hidden_municipality,
}

# channel -> the Product column marking "Hidden except in-stock" mode.
_CHANNEL_INSTOCK_ONLY_COL = {
    "retail": Product.instock_only_retail,
    "wholesale": Product.instock_only_wholesale,
    "dealer": Product.instock_only_dealer,
    "municipality": Product.instock_only_municipality,
}


def tier_to_channel(tier) -> str:
    """Map a ``CustomerTier`` to its channel. Anonymous/retail and any unknown
    tier fall back to 'retail'. (JOBBER is the 'wholesale' channel.)"""
    if tier == CustomerTier.JOBBER:
        return "wholesale"
    if tier == CustomerTier.DEALER:
        return "dealer"
    if tier == CustomerTier.MUNICIPALITY:
        return "municipality"
    return "retail"


async def viewer_channel(db: AsyncSession, user: User | None, request: Request) -> str:
    """The viewer's channel — honors admin 'Shop as Customer' impersonation.
    Anonymous requests (and therefore bots) resolve to 'retail'."""
    # Lazy import: app.dependencies imports app.models, so importing it at module
    # top would risk an import cycle when models are still loading.
    from app.dependencies import resolve_effective_customer_id

    if user is None:
        return "retail"
    eff_id = await resolve_effective_customer_id(db, user, request)
    if not eff_id:
        return "retail"
    tier = (
        await db.execute(select(Customer.tier).where(Customer.id == eff_id))
    ).scalar_one_or_none()
    return tier_to_channel(tier)


def hidden_col_for(channel: str):
    """The ``Product.is_hidden_<channel>`` column for a channel (retail if the
    channel string is unrecognized)."""
    return _CHANNEL_HIDDEN_COL.get(channel, Product.is_hidden_retail)


def hidden_col_name(channel: str) -> str:
    """The ``is_hidden_<channel>`` column NAME for use in raw SQL. Validated
    against ALL_CHANNELS (retail fallback) so it's always a safe identifier."""
    ch = channel if channel in ALL_CHANNELS else "retail"
    return f"is_hidden_{ch}"


def visible_to_channel_clause(channel: str) -> ColumnElement[bool]:
    """SQLAlchemy predicate: this product is visible to ``channel`` (i.e. not
    hidden for that channel). Callers AND this into their existing WHERE and keep
    their own ``is_for_sale`` / brand-active checks."""
    return hidden_col_for(channel) == False  # noqa: E712


def product_hidden_for(product, channel: str) -> bool:
    """Is a loaded Product ORM object hidden for ``channel``? Reads the matching
    is_hidden_<channel> attribute, falling back to legacy is_hidden."""
    return bool(getattr(product, f"is_hidden_{channel}", getattr(product, "is_hidden", False)))


# --------------------------------------------------------------------------- #
# "Hidden except in-stock" (blowout/clearance) helpers
# --------------------------------------------------------------------------- #

def instock_only_col_for(channel: str):
    """The ``Product.instock_only_<channel>`` column (retail if unrecognized)."""
    return _CHANNEL_INSTOCK_ONLY_COL.get(channel, Product.instock_only_retail)


def product_instock_only_for(product, channel: str) -> bool:
    """Is a loaded Product ORM object in 'Hidden except in-stock' mode for
    ``channel``? (True → cart/checkout must cap qty at live on-hand.)"""
    ch = channel if channel in ALL_CHANNELS else "retail"
    return bool(getattr(product, f"instock_only_{ch}", False))


async def total_on_hand(db: AsyncSession, product_id: int) -> int:
    """Live on-hand at Nelson's branches for one product (0 if none).

    Portland + Kent only — Spokane stock is titantruck.com's (stock_scope.py)."""
    from app.services.stock_scope import nelson_stock_only

    return int((await db.execute(
        select(func.coalesce(func.sum(ProductInventory.on_hand), 0))
        .where(ProductInventory.product_id == product_id, nelson_stock_only())
    )).scalar_one() or 0)


async def on_hand_map(db: AsyncSession, product_ids) -> dict[int, int]:
    """Live on-hand per product at Nelson's branches (missing → absent)."""
    from app.services.stock_scope import nelson_stock_only

    if not product_ids:
        return {}
    rows = (await db.execute(
        select(ProductInventory.product_id, func.coalesce(func.sum(ProductInventory.on_hand), 0))
        .where(ProductInventory.product_id.in_(list(product_ids)), nelson_stock_only())
        .group_by(ProductInventory.product_id)
    )).all()
    return {pid: int(t or 0) for pid, t in rows}
