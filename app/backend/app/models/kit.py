"""Kit + KitComponent — bundle/package kits with a bill of materials.

A kit is a sellable package (e.g. a WeatherGuard van package, SKU
HWZD-600-8214L) made up of component products with quantities. Used by the
admin "Create a kit package" wizard and the storefront package-contents
display. `product_id` points at the sellable package product; each component
resolves to its own product (`KitComponent.product_id`) for the sub-part link
when that part exists in our catalog. Vehicle fitment (make/model/wheelbase/
roof/hand) lives on the kit header for the fitment guide.

Generalizes the unused plow_kit/plow_kit_component pattern. Resources (install
PDFs) live in `product_resource` on the package product; images/description/
specs live in the usual product fields.
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Kit(Base):
    """A package kit: header + fitment, with a list of components."""

    __tablename__ = "kit"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_kit_sku"),
        Index("ix_kit_type", "kit_type"),
    )

    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    kit_type: Mapped[str] = mapped_column(String(40), nullable=False, default="van_package")
    trade: Mapped[str | None] = mapped_column(String(80))
    vehicle_make: Mapped[str | None] = mapped_column(String(80))
    vehicle_model: Mapped[str | None] = mapped_column(String(120))
    wheelbase: Mapped[str | None] = mapped_column(String(40))
    roof_height: Mapped[str | None] = mapped_column(String(40))
    hand: Mapped[str | None] = mapped_column(String(8))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str | None] = mapped_column(String(50))

    # Channel availability — admin dictates which customer channels may see/buy
    # the kit. A visitor whose channel isn't enabled is shown nothing (the kit
    # 404s on the PDP and is filtered out of catalog/search). Maps to the four
    # pricing tiers: retail / wholesale(=jobber) / dealer / municipality.
    avail_retail: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    avail_wholesale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    avail_dealer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    avail_municipality: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # True once an admin set the package product's prices on this kit (vs prices
    # arriving from an ERP sync) — lets the suggester offer a component-sum default.
    price_is_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Availability window (inclusive dates; null = open-ended). Outside the
    # window the kit is treated as not-live and hides everywhere — same path as
    # an inactive or channel-disallowed kit.
    available_from: Mapped[datetime.date | None] = mapped_column(Date)
    available_until: Mapped[datetime.date | None] = mapped_column(Date)

    components: Mapped[list["KitComponent"]] = relationship(
        back_populates="kit", cascade="all, delete-orphan",
        order_by="KitComponent.sort_order",
    )


class KitComponent(Base):
    """One line of a kit's bill of materials: a part number + quantity."""

    __tablename__ = "kit_component"
    __table_args__ = (
        Index("ix_kit_component_kit_id", "kit_id"),
        Index("ix_kit_component_part_number", "part_number"),
    )

    kit_id: Mapped[int] = mapped_column(
        ForeignKey("kit.id", ondelete="CASCADE"), nullable=False,
    )
    part_number: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    kit: Mapped["Kit"] = relationship(back_populates="components")
