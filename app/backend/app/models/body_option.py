"""Factory options a truck body can be ordered with.

Knapheide and CM publish an options set per body family — grain sides, swing-out
rear gates, contractor packages, cargo tie downs, rope hooks and so on. They are
ordered WITH the body, not bought separately, so the storefront lists them as
content next to the body and invites a call (Ben, 2026-09-24).

`BodyOption` is the option itself, held once per family. `ProductBodyOption`
attaches it to each body product of that family, so the ported marketing records
and the ERP-sourced bodies both show the same set. Links carry `source` so a
rebuild replaces only the rows a rule made.
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BodyOption(Base):
    __tablename__ = "body_option"
    __table_args__ = (
        UniqueConstraint("brand", "family", "slug", name="uq_body_option_brand_family_slug"),
        Index("ix_body_option_brand", "brand"),
        Index("ix_body_option_family", "family"),
    )

    brand: Mapped[str] = mapped_column(String(60), nullable=False)
    # The manufacturer's family the option belongs to: PVMX, PGND, ALSK…
    family: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Our own copy of the maker's render — assets stay on our server.
    image_url: Mapped[str | None] = mapped_column(String(400))
    thumb_url: Mapped[str | None] = mapped_column(String(400))
    source_url: Mapped[str | None] = mapped_column(String(600))
    model_name: Mapped[str | None] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ProductBodyOption(Base):
    __tablename__ = "product_body_option"
    __table_args__ = (
        UniqueConstraint("product_id", "body_option_id", name="uq_product_body_option"),
        Index("ix_product_body_option_product", "product_id"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    body_option_id: Mapped[int] = mapped_column(
        ForeignKey("body_option.id", ondelete="CASCADE"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="body-option-rules", nullable=False)
