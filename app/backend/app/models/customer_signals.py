"""Customer-signal records — Lost Sales, Price Match requests, Back-in-stock alerts.

Lost Sale + Price Match are write-once event tables. Back-in-stock alerts
are write-once-per-(sku,email) subscription rows that the nightly notifier
job marks `notified_at` on once stock returns.

Admin tools (Phase 1.5) will surface Lost Sale / Price Match for the sales
team to follow up.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LostSaleReason(str, Enum):
    PRICE_TOO_HIGH = "price_too_high"
    OUT_OF_STOCK = "out_of_stock"
    SHIPPING_TIME = "shipping_time"
    FOUND_ELSEWHERE = "found_elsewhere"
    WRONG_FITMENT = "wrong_fitment"
    OTHER = "other"


class PriceMatchStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    EXPIRED = "expired"


class LostSale(Base):
    """A "Did not buy" record — captured from the PDP modal."""

    __tablename__ = "lost_sale"

    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id", ondelete="SET NULL"), index=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customer.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), index=True)
    session_token: Mapped[str | None] = mapped_column(String(64), index=True)

    reason: Mapped[LostSaleReason] = mapped_column(
        SAEnum(
            LostSaleReason, name="lost_sale_reason",
            # Persist the lowercase enum VALUE ("out_of_stock") instead of
            # the Python member NAME ("OUT_OF_STOCK"). The DB enum type was
            # created with the lowercase variants per the migration.
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text)


class PriceMatchRequest(Base):
    """A "Price Match" request — Phase 1 just records; Phase 1.5 admin can
    approve and create a customer-specific override price.
    """

    __tablename__ = "price_match_request"

    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id", ondelete="SET NULL"), index=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customer.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), index=True)

    competitor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    competitor_url: Mapped[str | None] = mapped_column(String(1000))
    competitor_price_usd: Mapped[str] = mapped_column(String(32), nullable=False)
    screenshot_url: Mapped[str | None] = mapped_column(String(1000))  # uploaded to /uploads/ later
    notes: Mapped[str | None] = mapped_column(Text)

    status: Mapped[PriceMatchStatus] = mapped_column(
        SAEnum(
            PriceMatchStatus, name="price_match_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=PriceMatchStatus.PENDING, nullable=False, index=True,
    )


class BackInStockAlert(Base):
    """Subscription row: notify (email) when sku transitions to in-stock.

    Nightly job (`scripts/notify_back_in_stock.py`) sweeps unsent rows,
    checks current `product_inventory.on_hand` total per SKU, and emails
    + marks `notified_at` for any row whose product is now positive.

    De-dup'd at the (sku, email) layer so re-clicks during the OOS
    window are idempotent. Owner ask 2026-05-17 (L7).
    """

    __tablename__ = "back_in_stock_alert"
    __table_args__ = (UniqueConstraint("sku", "email", name="uq_bis_sku_email"),)

    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id", ondelete="SET NULL"), index=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), index=True)
    session_token: Mapped[str | None] = mapped_column(String(64), index=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
