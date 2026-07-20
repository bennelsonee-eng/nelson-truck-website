"""AdminMessage — the admin-only message board.

A single feed of things an admin needs to know about, surfaced in the admin
control panel (and folded into the header issues badge). Two producers today:

  1. Catalog visibility — when a hidden part is still a component of an active
     kit, hiding it silently breaks the package. The resolver raises a
     `kit_conflict` message (deduped per kit+part) and auto-resolves it when the
     part is shown again.
  2. Site health — major site problems (page 5xx, cart/checkout failures, JS
     errors, page-down) read from the `request_log` telemetry. These are
     surfaced live by the messages router rather than materialized here, but the
     table can also hold pinned/acknowledged ones.

kind / severity / status are plain strings validated at the API layer (same
pattern as build_idea). `dedupe_key` lets a recurring condition upsert (bump
`occurrences` + `last_seen`) instead of spamming new rows.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AdminMessage(Base):
    """One entry on the admin message board."""

    __tablename__ = "admin_message"

    # kit_conflict | site_error | cart_failure | js_error | page_down | info
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # info | warning | critical
    severity: Mapped[str] = mapped_column(String(10), default="warning", nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # Structured payload (kit_id, product_id/sku, route, status, counts, …).
    context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # open | ack | resolved
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False, index=True)

    # Deterministic identity for a recurring condition, so it upserts.
    # e.g. "kit_conflict:{kit_id}:{product_id}"
    dedupe_key: Mapped[str | None] = mapped_column(String(400), nullable=True, unique=True)

    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    resolved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
