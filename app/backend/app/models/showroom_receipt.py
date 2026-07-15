"""Showroom receipt — a customer-facing retail receipt a jobber/dealer hands to
their walk-in customer.

Generated from the cart at retail prices while in Retail Showroom Mode. The
jobber collects the money at their own register; `status` (paid/unpaid) is the
jobber's own bookkeeping. Branding (logo + display name) is snapshotted at
creation so a later logo change doesn't rewrite past receipts.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ShowroomReceipt(Base):
    __tablename__ = "showroom_receipt"

    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), index=True, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))

    receipt_number: Mapped[str] = mapped_column(String(32), index=True, default="")
    status: Mapped[str] = mapped_column(String(16), default="unpaid", nullable=False)

    # Branding snapshot at time of sale.
    display_name: Mapped[str | None] = mapped_column(String(200))
    logo_url: Mapped[str | None] = mapped_column(String(1000))

    # Line items: [{sku, name, qty, unit, total}] at retail prices.
    lines: Mapped[list] = mapped_column(JSON, default=list)
    retail_subtotal: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    retail_tax: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    retail_total: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
