"""RMA Return Request — email-based Phase 1 per SOW addendum A4.31.

A jobber files an RMA against a past order from My Orders detail. The website
records the request, attaches photos to an email to sales@nelsontruck.com, and
shows the jobber an "RMA Requested" badge on the order detail. Titan staff
process the actual return out-of-band in legacy FACS / AR; the website does
NOT track approved / denied / received / refunded status in Phase 1.

Photos: per addendum's Phase 2 deferral, we DO NOT persist photo bytes in
Phase 1 — they go out as email attachments only. We do record metadata
(filename, content_type, byte_size) on the request for audit, and enforce the
20 MB total cap at the API layer before saving the request.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    JSON,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class RmaReason(str, Enum):
    """Why the jobber is returning this line (A4.31)."""

    DEFECTIVE_DOA = "defective_doa"
    WRONG_PART_SHIPPED = "wrong_part_shipped"
    DAMAGED_SHIPPING = "damaged_shipping"
    CUSTOMER_ERROR = "customer_error"
    OTHER = "other"


class RmaStatus(str, Enum):
    """RMA lifecycle.

    Phase 1 uses only SUBMITTED + CANCELLED (jobber-side states). The rest are
    declared up-front for forward-compat so Phase 2 (Titan ERP wiring) doesn't
    need a fresh enum-type migration.
    """

    # Phase 1 (jobber-side, website-managed)
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"

    # Phase 2 (Titan ERP / staff-managed — out of scope for Phase 1)
    APPROVED = "approved"
    DENIED = "denied"
    RECEIVED = "received"
    REFUNDED = "refunded"
    CLOSED = "closed"


class RmaRequest(Base):
    """One row per RMA submission. Lives on our website's order record."""

    __tablename__ = "rma_request"

    order_id: Mapped[int] = mapped_column(
        ForeignKey("order.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), index=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    status: Mapped[RmaStatus] = mapped_column(
        SAEnum(RmaStatus, name="rma_status"),
        default=RmaStatus.SUBMITTED,
        nullable=False,
        index=True,
    )

    # Free-text from the jobber (the form's optional "Notes" field).
    notes: Mapped[str | None] = mapped_column(Text)

    # Metadata-only photo audit (no bytes persisted in Phase 1). Shape:
    # [{"filename": "img.jpg", "content_type": "image/jpeg", "byte_size": 1234567}, ...]
    photo_metadata: Mapped[list | None] = mapped_column(JSON)
    # Sum of photo byte_size, kept separate for the 20 MB cap check on read.
    total_photo_bytes: Mapped[int | None] = mapped_column()

    # Outbound email dispatch tracking.
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_error: Mapped[str | None] = mapped_column(Text)

    order: Mapped["Order"] = relationship(back_populates="rma_requests")  # noqa: F821
    lines: Mapped[list["RmaLine"]] = relationship(
        back_populates="rma_request",
        cascade="all, delete-orphan",
        order_by="RmaLine.id",
    )


class RmaLine(Base):
    """One per OrderLine the jobber is returning. qty_to_return capped at the
    OrderLine's ordered qty by the API layer."""

    __tablename__ = "rma_line"

    rma_request_id: Mapped[int] = mapped_column(
        ForeignKey("rma_request.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_line_id: Mapped[int] = mapped_column(
        ForeignKey("order_line.id"), nullable=False, index=True
    )
    qty_to_return: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[RmaReason] = mapped_column(
        SAEnum(RmaReason, name="rma_reason"), nullable=False
    )
    line_notes: Mapped[str | None] = mapped_column(Text)

    rma_request: Mapped[RmaRequest] = relationship(back_populates="lines")
