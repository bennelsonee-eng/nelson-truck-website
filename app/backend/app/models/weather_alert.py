"""Weather-alert subscriber model.

Powers the snow-forecast email alerts on /snow-plows.  User-facing flow:
  1. User submits email + ZIP on the snow-plows page (and optionally opts in
     to promotional emails about snow & ice gear)
  2. We send a confirmation email with a tokenised URL — double-opt-in
  3. They click the link, `confirmed_at` gets stamped, they go active
  4. Daily cron walks active subscribers, fetches NWS forecast for each
     subscriber's gridpoint, sends an alert email if snow appears in the
     next 10 days (subject to a 3-day dampening window so we don't spam
     during a single sustained storm)
  5. Every email carries a one-click unsubscribe URL with a separate
     `unsubscribe_token` so leaking the confirmation_token doesn't open
     an unsubscribe vector

Compliance:
  - Double-opt-in (CAN-SPAM doesn't require it but it's the gold standard
    for transactional alert lists, and CASL/GDPR effectively do)
  - Separate consent for alert vs promotional email (granular per CAN-SPAM)
  - One-click unsubscribe per RFC 8058 / CAN-SPAM
  - All tokens are URL-safe random 32-byte hex
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WeatherAlertSubscriber(Base):
    """One row per email address subscribed to snow forecast alerts."""

    __tablename__ = "weather_alert_subscriber"

    # Identity --------------------------------------------------------------
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    # Resolved location.  Populated on signup via Zippopotam.us (ZIP -> lat/lon)
    # then NWS /points/{lat,lon} -> office + grid.  Pinned per subscriber so we
    # don't re-resolve every alert run.  If ZIP changes we re-resolve.
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    nws_office: Mapped[str | None] = mapped_column(String(8))
    nws_grid_x: Mapped[int | None] = mapped_column(Integer)
    nws_grid_y: Mapped[int | None] = mapped_column(Integer)
    location_label: Mapped[str | None] = mapped_column(String(80))  # "Spokane Valley, WA"
    nws_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Consent flags (granular per CAN-SPAM)
    alert_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    promo_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Double-opt-in: NULL until they click the confirmation link
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    confirmation_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    # Unsubscribe (separate from confirmation_token so a leaked confirm link
    # can't be used to unsubscribe other people)
    unsubscribe_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    unsubscribe_reason: Mapped[str | None] = mapped_column(String(200))

    # Send-frequency dampening — last alert sent + total count
    last_alert_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_alert_subject: Mapped[str | None] = mapped_column(String(200))
    total_alerts_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Bookkeeping
    source_url: Mapped[str | None] = mapped_column(String(200))   # where the signup came from
    user_agent: Mapped[str | None] = mapped_column(String(400))   # for fraud detection / debugging

    @property
    def is_active(self) -> bool:
        """Confirmed and not unsubscribed.  Only active subs receive alerts."""
        return self.confirmed_at is not None and self.unsubscribed_at is None

    @property
    def has_location(self) -> bool:
        return all([self.latitude, self.longitude, self.nws_office, self.nws_grid_x, self.nws_grid_y])

    def __repr__(self) -> str:  # pragma: no cover
        status = (
            "unsub" if self.unsubscribed_at else
            "active" if self.confirmed_at else
            "pending"
        )
        return f"<WeatherAlertSubscriber {self.email} {self.zip_code} {status}>"
