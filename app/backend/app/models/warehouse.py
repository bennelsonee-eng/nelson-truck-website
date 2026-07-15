"""Warehouse domain — physical stocking locations + per-product inventory."""

from __future__ import annotations

from datetime import datetime

from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Warehouse(Base):
    """Physical stocking location.

    Phase 1 codes (per addendum 003):
      10 — Spokane HQ (default)
      19 — Boise warehouse
       1 — Portland (rolls up to NELSON file routing per user 2026-04-25)
      0  — Nelson Kent (logical — all NELSON-routed orders combined)
    """

    __tablename__ = "warehouse"

    code: Mapped[int] = mapped_column(unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    short_name: Mapped[str] = mapped_column(String(20), nullable=False)  # SPO, BOISE, NELSON, PORTLAND

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Whether this warehouse generates its own FACS file (vs rolling up under another).
    # Portland (code=1) rolls up under NELSON, so emits_own_facs_file=False.
    emits_own_facs_file: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    facs_route_label: Mapped[str] = mapped_column(String(20), nullable=False)  # "SPO" | "BOISE" | "NELSON"

    # Default Ship Via for this warehouse's IMS315 export
    ship_via_default: Mapped[str | None] = mapped_column(String(64))

    # Optional address
    address1: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))
    zip: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(32))

    inventory: Mapped[list[ProductInventory]] = relationship(back_populates="warehouse")


class ProductInventory(Base):
    """Per-product, per-warehouse on-hand stock.

    Synced from Titan MySQL (15-min full sync + delta-push, per Q14).
    Loaded from `parts_onhands` table columns: spokane, boise, kent (Nelson), portland.
    """

    __tablename__ = "product_inventory"

    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouse.id"), nullable=False, index=True)

    on_hand: Mapped[int] = mapped_column(default=0, nullable=False)
    # Reservable stock (on_hand minus open allocations).  May be lower than
    # on_hand if there are pending picks.  Nullable for legacy rows.
    available: Mapped[int | None] = mapped_column(nullable=True)
    # Per-unit GL cost — drives our cost-floor in the pricing engine when
    # stocked-cost beats the parts-master P5 fallback.  Nullable.
    gl_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    warehouse: Mapped[Warehouse] = relationship(back_populates="inventory")

    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uq_inventory_product_warehouse"),
    )
