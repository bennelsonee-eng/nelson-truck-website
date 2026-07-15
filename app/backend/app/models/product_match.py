"""ProductMatch — candidate "this product = that product, different label" pairs.

A confirmed match means Brand A's SKU and Brand B's SKU represent the same
physical part (private-label / OEM reseller relationship). The
auto-scorer (`scripts/find_reseller_pairs.py`) generates pending pairs
within shared categories; an admin walks the queue confirming /
rejecting each pair from `/admin/reseller-finder`.

Owner ask 2026-05-17 (S1).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProductMatchStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ProductMatchSource(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class ProductMatch(Base):
    """One row per (canonical, alias) pair. Canonical = the product whose
    id is numerically lower; alias = the higher-id sibling. The split is
    arbitrary but stable — admins can flip via the UI without dropping
    the row.
    """

    __tablename__ = "product_match"
    __table_args__ = (
        UniqueConstraint(
            "canonical_product_id", "alias_product_id",
            name="uq_product_match_pair",
        ),
    )

    canonical_product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    alias_product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    status: Mapped[ProductMatchStatus] = mapped_column(
        SAEnum(
            ProductMatchStatus, name="product_match_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ProductMatchStatus.PENDING, nullable=False, index=True,
    )
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[ProductMatchSource] = mapped_column(
        SAEnum(
            ProductMatchSource, name="product_match_source",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ProductMatchSource.AUTO, nullable=False,
    )
    # Which signals fired and at what strength — keeps the queue UX
    # informative without re-running the scorer.
    signals: Mapped[dict | None] = mapped_column(JSON)
    decided_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
