"""Customer inquiries (quote requests, contact form) and newsletter sign-ups.

Launch audit 2026-09-22: the "Get Quote" button on every quote-only product
(truck bodies, aerial lifts, liftgates) had no handler, "Tell us about your
project" and "Contact sales" were mailto: links, and the footer newsletter
only saved the address in the visitor's own browser. Nothing a shopper sent
reached Nelson. Every inquiry is now stored here first (so it is never lost
to a mail outage) and then emailed to `settings.inquiry_alert_email`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

INQUIRY_KINDS = ("quote", "contact", "project")
INQUIRY_STATUSES = ("new", "handled")


class Inquiry(Base):
    __tablename__ = "inquiry"

    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="contact", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new", index=True)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    company: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    # Which counter should answer: Portland, Kent, or either.
    branch: Mapped[str | None] = mapped_column(String(20))

    # Set when the inquiry came from a product page.
    product_sku: Mapped[str | None] = mapped_column(String(80), index=True)
    product_name: Mapped[str | None] = mapped_column(String(300))
    quantity: Mapped[int | None] = mapped_column(Integer)

    message: Mapped[str | None] = mapped_column(Text)
    page_url: Mapped[str | None] = mapped_column(String(500))

    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_by: Mapped[str | None] = mapped_column(String(254))
    notes: Mapped[str | None] = mapped_column(Text)


class NewsletterSubscriber(Base):
    __tablename__ = "newsletter_subscriber"

    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    source: Mapped[str | None] = mapped_column(String(60))
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
