"""Deals layer — the "Today's Deals" collection that powers the Deal Warehouse
homepage: a scheduled, audience-scoped promo (countdown via ends_at) plus its
items — featured PRODUCT cards (with badges) for the grid and HIGHLIGHT rows
(category links) for the sidebar. Admin-managed in /admin/deals.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class DealAudience(str, Enum):
    RETAIL = "retail"
    WHOLESALE = "wholesale"
    BOTH = "both"


class DealItemKind(str, Enum):
    PRODUCT = "product"      # featured product card in the grid (sku + badge)
    HIGHLIGHT = "highlight"  # sidebar row (label/sublabel/icon/link)


def _audience_col(name: str):
    return mapped_column(
        SAEnum(DealAudience, name=name, values_callable=lambda x: [e.value for e in x]),
        default=DealAudience.BOTH, nullable=False, index=True,
    )


class DealCollection(Base):
    """A scheduled promo set (usually one active per placement)."""

    __tablename__ = "deal_collection"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    placement: Mapped[str] = mapped_column(String(50), default="home", nullable=False, index=True)
    audience: Mapped[DealAudience] = _audience_col("deal_audience")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # countdown target
    sort_order: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)

    items: Mapped[list["DealItem"]] = relationship(
        back_populates="collection", cascade="all, delete-orphan",
    )


class DealItem(Base):
    """A product card or a sidebar highlight within a collection."""

    __tablename__ = "deal_item"

    collection_id: Mapped[int] = mapped_column(
        ForeignKey("deal_collection.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    kind: Mapped[DealItemKind] = mapped_column(
        SAEnum(DealItemKind, name="deal_item_kind", values_callable=lambda x: [e.value for e in x]),
        nullable=False, index=True,
    )
    audience: Mapped[DealAudience] = _audience_col("deal_item_audience")
    sort_order: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # kind=product
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    badge_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    badge_tone: Mapped[str | None] = mapped_column(String(20), nullable=True)  # rebate|clearance|free_shipping|pro_price|limited|sale

    # kind=highlight
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sublabel: Mapped[str | None] = mapped_column(String(120), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(16), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    collection: Mapped[DealCollection] = relationship(back_populates="items")
