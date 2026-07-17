"""Customer-link request — email-gated User → Customer linkage.

Per the user (2026-05-16): "I want to make sure on the back side that a
customer cannot just choose a customer number and they get that pricing.
That has to be confirmed by sales@nelsontruck.com."

Flow:
  1. A signed-up User (no customer_id) submits a link request via
     /api/auth/request-link with their FACS customer_number + a billing
     zip (or similar verification hint).
  2. Server creates a CustomerLinkRequest row (status=PENDING) and emails
     sales@nelsontruck.com with the request details.
  3. Sales staff confirms ownership out-of-band (phone, in-person, email).
  4. An admin approves the request via the CMS (sets User.customer_id and
     marks the request APPROVED) or rejects it.

Until APPROVED, the user has no customer_id and therefore no jobber pricing
— closing the auto-link exploit that existed in /api/auth/signup and
/api/auth/link-customer before this change.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CustomerLinkRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CustomerLinkRequest(Base):
    __tablename__ = "customer_link_request"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_customer_number: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )

    # Verification hints supplied by the requester. Sales uses these to
    # confirm the requester actually owns the customer record before approval.
    billing_zip: Mapped[str | None] = mapped_column(String(20))
    additional_info: Mapped[str | None] = mapped_column(Text)

    status: Mapped[CustomerLinkRequestStatus] = mapped_column(
        SAEnum(CustomerLinkRequestStatus, name="customer_link_request_status"),
        default=CustomerLinkRequestStatus.PENDING,
        nullable=False,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Outbound email to sales@nelsontruck.com — kept on the row for retry/audit.
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_error: Mapped[str | None] = mapped_column(Text)

    # Admin review (set when APPROVED or REJECTED).
    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(  # noqa: F821
        foreign_keys=[user_id],
    )
    reviewed_by: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[reviewed_by_user_id],
    )
