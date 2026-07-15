"""Shopping cart — server-side cart for anonymous (session-token) and logged-in customers.

Anonymous: cart keyed by an opaque session_token (issued by backend, stored in
HttpOnly cookie). On login, server merges anonymous cart into the customer's cart.

Logged-in jobbers (A4.6) support multiple concurrent carts per customer/user
so the jobber can build several quotes in parallel. The "consolidation cart"
(A4.20) is a special shared admin cart that all users on the account add into
when admin enables consolidation mode.

Cart converts to Order at checkout — Order is the immutable record of intent.
Each CartLine carries the YMM (A4.1) and source flag the jobber used to land
on it, plus a snapshot of warehouse stock at the moment of add (A4.2) so the
order audit trail preserves what the jobber was actually seeing.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    JSON,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CartLineSource(str, Enum):
    """How a part landed on a cart line, per A4.1.

    YMM_DRILLDOWN — jobber navigated via category/series with YMM set; fitment implied.
    PART_LOOKUP_WITH_YMM — jobber typed/pasted an exact part# while YMM was set; fitment NOT implied (triggers the yellow badge).
    PART_LOOKUP_NO_YMM — jobber typed/pasted a part# with no YMM context at all.
    """

    YMM_DRILLDOWN = "ymm_drilldown"
    PART_LOOKUP_WITH_YMM = "part_lookup_with_ymm"
    PART_LOOKUP_NO_YMM = "part_lookup_no_ymm"


class Cart(Base):
    __tablename__ = "cart"

    # Customer this cart belongs to (logged-in tier). Non-unique: a jobber can
    # have N concurrent carts (A4.6) — uniqueness is anchored on session_token
    # for anonymous shoppers only.
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer.id", ondelete="CASCADE"), index=True
    )

    # Which jobber user owns this cart. NULL for anonymous or shared admin
    # consolidation carts. Multi-user accounts (A4.20) can have one cart per
    # user that's distinct from the shared admin cart.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), index=True
    )

    session_token: Mapped[str | None] = mapped_column(String(64), index=True, unique=True)

    # Free-text cart name so the jobber can identify it in a list, e.g.
    # "Smith F-250 plow build" (A4.6).
    label: Mapped[str | None] = mapped_column(String(100))

    # The shared admin consolidation cart (A4.20). When the account admin
    # enables consolidation mode, all users' adds target this cart instead of
    # their personal carts. Admin reviews + submits end-of-day.
    is_consolidation_cart: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Set when the cart converts to an Order. Non-null = historical/closed cart;
    # NULL = open cart that the active-cart picker can target.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    lines: Mapped[list["CartLine"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan", order_by="CartLine.created_at"
    )


class CartLine(Base):
    __tablename__ = "cart_line"

    cart_id: Mapped[int] = mapped_column(ForeignKey("cart.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True)

    quantity: Mapped[int] = mapped_column(default=1, nullable=False)

    unit_price_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # YMM lock-in (A4.1). Captured at add-time; the same part bought for two
    # different vehicles results in two cart lines (so the unique constraint
    # on (cart_id, product_id) is intentionally absent).
    ymm_year: Mapped[int | None] = mapped_column()
    ymm_make: Mapped[str | None] = mapped_column(String(50))
    ymm_model: Mapped[str | None] = mapped_column(String(100))

    # Where the part-add came from. Drives the yellow "Added via part-# lookup"
    # cart-line badge when set to PART_LOOKUP_WITH_YMM (A4.1).
    source: Mapped[CartLineSource | None] = mapped_column(
        SAEnum(CartLineSource, name="cart_line_source")
    )

    # Per-warehouse stock at add-time. Lets the cart show
    # "Spokane:3 / Boise:0 / Nelson:1 / Factory: ETA Mar 5" (A4.2) and freezes
    # what the jobber was seeing for the order audit trail (A4.5).
    stock_breakdown_at_add: Mapped[dict | None] = mapped_column(JSON)

    # Price-change tracking (A4.4). When the server-side reprice on cart load
    # detects a change, original_price holds the pre-change value and submit
    # is blocked until acknowledged_at is set.
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL")
    )

    cart: Mapped[Cart] = relationship(back_populates="lines")
