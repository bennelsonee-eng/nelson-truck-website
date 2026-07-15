"""Auth domain — user accounts (admin/editor + customer logins) and sessions."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class UserRole(str, Enum):
    """Two-role permission model for Phase 1 (per Q24).

    CUSTOMER role is a third bucket for B2B customer logins (jobber/dealer/muni)
    — they can place orders but not edit content.
    """

    ADMIN = "admin"           # Ben + delegated. Full control.
    EDITOR = "editor"         # Marketing + Accessory Manager. Content + scheduling.
    CUSTOMER = "customer"     # B2B customer login (jobber/dealer/muni).


class User(Base):
    """User account.

    For admin/editor: standalone account.
    For customer: linked to a Customer record via customer_id.
    """

    __tablename__ = "user"

    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"), nullable=False, index=True
    )

    # For customer-tier users — link to their Customer record
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customer.id"), index=True)

    # Display
    display_name: Mapped[str | None] = mapped_column(String(200))

    # B2B multi-user (A4.20): one or more users per Customer account, one of
    # whom is designated admin (can enable/disable peers + toggle consolidation cart).
    is_account_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_disabled_by_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # SMS-capable notification channel (A4.18). Per-user, not per-Customer.
    phone: Mapped[str | None] = mapped_column(String(32))

    # Optional 2FA (TOTP) — strongly recommended for admins
    totp_secret: Mapped[str | None] = mapped_column(String(200))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_token: Mapped[str | None] = mapped_column(String(200))
    password_reset_token: Mapped[str | None] = mapped_column(String(200))
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
