"""ProductResource — PDFs, videos, and other supplementary product files.

Holds anything that lives alongside the product detail page on the
manufacturer's site: install manuals, spec/datasheets, brochures, parts
lists, install videos, demo videos, etc. Owner ask 2026-05-18 after
the first image-only Buyers Products scrape — wanted us to keep pulling
the richer content while we already had a working session against the
brand site.

Image URLs stay in `product_image` (existing). This table is for
non-image attachments + media URLs.
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SAEnum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ResourceKind(str, Enum):
    """Kind of thing a row represents. Open list — `OTHER` is the catch-all
    for resources that don't fit cleanly elsewhere."""

    MANUAL = "manual"               # Install / owner / service manual
    DATASHEET = "datasheet"         # Spec sheet, datasheet
    BROCHURE = "brochure"           # Marketing brochure / catalog
    INSTALLATION = "installation"   # Installation guide / fitment kit
    PARTS_LIST = "parts_list"       # Exploded parts diagram, parts list
    SPEC_SHEET = "spec_sheet"       # Technical spec sheet
    VIDEO = "video"                 # YouTube watch URL or direct mp4
    DIAGRAM = "diagram"             # Wiring diagram, schematic
    OTHER = "other"


class ProductResource(Base):
    """One supplementary file/video per row.

    Unique on (product_id, url) so the same URL can't be added twice.
    `source` records where we scraped it from for audit + re-run safety
    (e.g. "buyersproducts.com", "fedsig.com").
    """

    __tablename__ = "product_resource"
    __table_args__ = (
        UniqueConstraint("product_id", "url", name="uq_product_resource_url"),
        Index("ix_product_resource_kind", "kind"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    kind: Mapped[ResourceKind] = mapped_column(
        SAEnum(
            ResourceKind, name="resource_kind",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), index=True)
