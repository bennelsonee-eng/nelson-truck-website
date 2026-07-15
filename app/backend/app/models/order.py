"""Order domain — web orders + line items.

Source of truth: this DB. Orders push to FACS via FTP using IMS315 CSV format
(see SOW addendum 003 for full algorithm). Each order can produce up to 4 CSVs
based on multi-warehouse fulfillment routing.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.cart import CartLineSource


class OrderStatus(str, Enum):
    PENDING = "pending"               # In cart, not yet placed
    PLACED = "placed"                 # Customer confirmed order
    PUSHED_TO_FACS = "pushed_to_facs"  # IMS315 CSV(s) written, awaiting FACS pickup
    ACKNOWLEDGED = "acknowledged"     # FACS picked up file
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    QUOTE = "quote"                   # Muni quote workflow (FS-071) — not a real order


class PaymentType(str, Enum):
    CREDIT_CARD = "credit_card"
    PURCHASE_ORDER = "purchase_order"


class QuoteIntent(str, Enum):
    """Required qualifier for muni quote workflow (FS-071, per Q32)."""

    BUDGET = "budget"
    COMPETITIVE = "competitive"


class FACSPushStatus(str, Enum):
    """Per-warehouse-file push status to FACS FTP."""

    PENDING = "pending"
    PUSHED = "pushed"
    PICKED_UP = "picked_up"  # File disappeared from FTP folder = FACS grabbed it
    FAILED = "failed"
    REPLAYED = "replayed"


class Order(Base):
    """Web order header. Mirrors IMS315 Type-1 fields (per addendum 002).

    Each Order can spawn multiple OrderFulfillment records — one per warehouse
    that contributes stock — each producing its own CSV file.
    """

    __tablename__ = "order"

    # Web order number — used in FACS file naming and as confirmation number
    web_order_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)

    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id"), nullable=False, index=True)

    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status"), default=OrderStatus.PENDING, nullable=False, index=True
    )
    payment_type: Mapped[PaymentType] = mapped_column(
        SAEnum(PaymentType, name="payment_type"), nullable=False
    )

    # Quote workflow (muni; FS-071)
    is_quote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quote_intent: Mapped[QuoteIntent | None] = mapped_column(SAEnum(QuoteIntent, name="quote_intent"))

    # Customer-supplied PO (preferred for muni per Q33 follow-up)
    customer_po_number: Mapped[str | None] = mapped_column(String(100), index=True)

    # Snapshot of customer + addresses at order time (so historical orders preserve
    # the address that was actually used, even if customer record changes later)
    billing_name: Mapped[str | None] = mapped_column(String(200))
    billing_company: Mapped[str | None] = mapped_column(String(200))
    billing_addr1: Mapped[str | None] = mapped_column(String(200))
    billing_addr2: Mapped[str | None] = mapped_column(String(200))
    billing_city: Mapped[str | None] = mapped_column(String(100))
    billing_state: Mapped[str | None] = mapped_column(String(2))
    billing_zip: Mapped[str | None] = mapped_column(String(20))

    shipping_name: Mapped[str | None] = mapped_column(String(200))
    shipping_company: Mapped[str | None] = mapped_column(String(200))
    shipping_addr1: Mapped[str | None] = mapped_column(String(200))
    shipping_addr2: Mapped[str | None] = mapped_column(String(200))
    shipping_city: Mapped[str | None] = mapped_column(String(100))
    shipping_state: Mapped[str | None] = mapped_column(String(2))
    shipping_zip: Mapped[str | None] = mapped_column(String(20), index=True)

    contact_email: Mapped[str | None] = mapped_column(String(200))
    contact_phone: Mapped[str | None] = mapped_column(String(32))

    # Sales attribution
    sales_rep_code: Mapped[str | None] = mapped_column(String(20))
    referral_source: Mapped[str | None] = mapped_column(String(100))  # UTM source etc.

    # Money totals (in USD; we store decimals with 2-place precision)
    item_total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    shipping_total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    handling_total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    discount_total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    tax_total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    tax_rate_x1000: Mapped[int] = mapped_column(default=0, nullable=False)  # WSM-style integer tax rate
    tax_code: Mapped[str | None] = mapped_column(String(20))
    grand_total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    # Dates
    order_date: Mapped[date | None] = mapped_column(Date, index=True)
    required_date: Mapped[date | None] = mapped_column(Date)

    # Free-form
    comments: Mapped[str | None] = mapped_column(Text)
    ship_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Payment processor reference (Authorize.net transaction id)
    authnet_transaction_id: Mapped[str | None] = mapped_column(String(64))

    # Jobber-flow tracking (A4.15, A4.17, A4.24, A4.28).
    # Which logged-in user clicked "Submit"; useful for multi-user accounts.
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), index=True)
    # Shop-as-Customer audit: when CMS staff places an order on behalf of a
    # jobber, acting_as_customer_id holds the impersonated customer and
    # acting_as_staff_user_id holds the staff user who acted. NULL on
    # self-service jobber orders.
    acting_as_customer_id: Mapped[int | None] = mapped_column(ForeignKey("customer.id"))
    acting_as_staff_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))

    # Staff-fired "Mark as Shipped" toggle (A4.17). ONE shipped email per order
    # regardless of warehouse splits in Phase 1.
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    shipped_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    shipped_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Jobber-internal reference (A4.24). Distinct from `comments` above —
    # `comments` flows into the IMS315 CSV; `internal_notes` stays on our record only.
    internal_notes: Mapped[str | None] = mapped_column(Text)

    # Audit link back to the source Cart (A4.5). SET NULL on cart delete so the
    # order survives independently.
    source_cart_id: Mapped[int | None] = mapped_column(ForeignKey("cart.id", ondelete="SET NULL"))

    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderLine.line_number"
    )
    fulfillments: Mapped[list[OrderFulfillment]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    rma_requests: Mapped[list["RmaRequest"]] = relationship(  # noqa: F821
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="RmaRequest.requested_at.desc()",
    )


class OrderLine(Base):
    """Line item — one per (product, warehouse) split.

    Mirrors IMS315 Type-2 detail fields. Special line types use synthetic
    SKUs (FREIGHT, DISCOUNT, HANDLING) per the existing PHP convention.
    """

    __tablename__ = "order_line"

    order_id: Mapped[int] = mapped_column(ForeignKey("order.id", ondelete="CASCADE"), nullable=False, index=True)
    line_number: Mapped[int] = mapped_column(nullable=False)

    # Optional product link — null for FREIGHT / DISCOUNT / HANDLING synthetic lines
    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id"), index=True)

    sku: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500))

    quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    backorder_quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    unit_price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    # Which warehouse fulfills this line (null for synthetic lines)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse.id"), index=True)

    # Special line markers — synthetic items get these flags
    is_freight: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_discount: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_handling: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Snapshot of contract that priced this (if applicable) — useful for audit
    contract_id: Mapped[int | None] = mapped_column(ForeignKey("contract.id"))

    # Frozen from CartLine at submit (A4.5 — cart snapshot at submit). These let
    # us replay "what the jobber was looking at" on the order detail view even
    # if the catalog or stock state has changed since.
    ymm_year: Mapped[int | None] = mapped_column()
    ymm_make: Mapped[str | None] = mapped_column(String(50))
    ymm_model: Mapped[str | None] = mapped_column(String(100))

    # Reuses the enum owned by cart_line.source; create_type=False keeps Alembic
    # from trying to create the postgres ENUM twice.
    source: Mapped[CartLineSource | None] = mapped_column(
        SAEnum(CartLineSource, name="cart_line_source", create_type=False)
    )

    stock_breakdown_at_add: Mapped[dict | None] = mapped_column(JSON)

    # If price-change-on-cart-load (A4.4) fired and the jobber acknowledged,
    # original_price preserves the pre-change value for audit.
    original_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL")
    )

    order: Mapped[Order] = relationship(back_populates="lines")

    __table_args__ = (
        UniqueConstraint("order_id", "line_number", name="uq_order_line_number"),
    )


class OrderFulfillment(Base):
    """One per warehouse-routed CSV file generated for an order.

    A single Order can produce up to 4 OrderFulfillment records:
    SPO (Spokane), BOISE, NELSON (Kent + Portland), BO (back-order).
    Each represents one IMS315 CSV file pushed to FACS.
    """

    __tablename__ = "order_fulfillment"

    order_id: Mapped[int] = mapped_column(ForeignKey("order.id", ondelete="CASCADE"), nullable=False, index=True)
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouse.id"))

    # Filename pattern: ORDERS_TITAN_{TYPE}_{ORDER#}_{WAREHOUSE#}.CSV
    file_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    routing_type: Mapped[str] = mapped_column(String(20), nullable=False)  # SPO, BOISE, NELSON, BO
    facs_warehouse_code: Mapped[int] = mapped_column(nullable=False)       # 10 or 19

    # Money allocated to this fulfillment portion (proportional split)
    item_subtotal_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    shipping_share_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    handling_share_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    discount_share_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    # FACS push tracking (FS-077)
    push_status: Mapped[FACSPushStatus] = mapped_column(
        SAEnum(FACSPushStatus, name="facs_push_status"),
        default=FACSPushStatus.PENDING, nullable=False, index=True
    )
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    push_attempts: Mapped[int] = mapped_column(default=0, nullable=False)

    # Raw CSV content for replay/audit
    csv_content: Mapped[str | None] = mapped_column(Text)

    order: Mapped[Order] = relationship(back_populates="fulfillments")
