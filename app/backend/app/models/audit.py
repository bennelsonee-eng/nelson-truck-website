"""Audit log — every admin/editor action is recorded for accountability.

Per Q24: 'Audit log on all admin actions' is a Phase 1 requirement.
Useful for: compliance, debugging "who changed pricing?", forensics, accountability.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """One row per audited action (CRUD on contracts, prices, products, users, settings)."""

    __tablename__ = "audit_log"

    # Who did it
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), index=True)
    user_email: Mapped[str | None] = mapped_column(String(200))  # Snapshot in case user is deleted

    # What
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # create / update / delete / login / etc.
    entity_type: Mapped[str | None] = mapped_column(String(50), index=True)       # "Product" / "Contract" / etc.
    entity_id: Mapped[str | None] = mapped_column(String(100), index=True)         # Stringified PK

    # Optional change detail
    before: Mapped[dict | None] = mapped_column(JSON)   # field values pre-change
    after: Mapped[dict | None] = mapped_column(JSON)    # field values post-change
    summary: Mapped[str | None] = mapped_column(Text)   # human-readable description

    # Request context
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))
