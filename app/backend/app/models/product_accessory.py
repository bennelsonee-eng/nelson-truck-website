"""ProductAccessory — a part (or sized body) listed underneath a truck body.

Filled by app/scripts/link_truck_body_parts.py from truck_body_parts_rules.py;
read by GET /api/catalog/products/{sku}/accessories.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProductAccessory(Base):
    __tablename__ = "product_accessory"
    __table_args__ = (
        UniqueConstraint("body_product_id", "part_product_id", name="uq_product_accessory_pair"),
        Index("ix_product_accessory_body", "body_product_id"),
        Index("ix_product_accessory_part", "part_product_id"),
    )

    body_product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    part_product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"), nullable=False)
    group_name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), index=True)
    rule: Mapped[str | None] = mapped_column(String(80))
