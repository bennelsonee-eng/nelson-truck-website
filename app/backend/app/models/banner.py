"""Banner CMS — homepage ad-banner slides, audience-scoped & scheduled.

Slides are managed in /admin/banners and served by GET /api/banners. Each slide
targets an audience (retail | wholesale | both) and an optional active window
(starts_at / ends_at), mirroring the rebate model so the storefront can show
different promos to retail shoppers vs B2B wholesale accounts. Phase 1 of the
homepage redesign (Deal Warehouse direction).
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BannerAudience(str, Enum):
    """Who a slide is shown to. Admin-controlled. `both` is the all-channels
    catch-all; retail / wholesale(=jobber) / dealer / municipality target one
    customer channel (mirrors services.channels.ALL_CHANNELS)."""

    RETAIL = "retail"
    WHOLESALE = "wholesale"
    DEALER = "dealer"
    MUNICIPALITY = "municipality"
    BOTH = "both"


class BannerSlide(Base):
    """One slide in a rotating homepage banner."""

    __tablename__ = "banner_slide"

    # The image to display (uploaded to /static/uploads/banners or an external URL).
    image_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    # Accessible alt / internal label.
    alt: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    # Optional click-through destination.
    link_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Audience scoping — retail shoppers vs B2B wholesale accounts vs everyone.
    audience: Mapped[BannerAudience] = mapped_column(
        SAEnum(
            BannerAudience,
            name="banner_audience",
            values_callable=lambda x: [e.value for e in x],  # store .value (lowercase)
        ),
        default=BannerAudience.BOTH,
        nullable=False,
        index=True,
    )
    # Where the slide appears (future-proofing for multiple carousels).
    placement: Mapped[str] = mapped_column(String(50), default="home_hero", nullable=False, index=True)

    sort_order: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Display fill for art smaller than the 3.7:1 hero frame. When fill_color is
    # set (e.g. "#0b1f3a"), the storefront renders the image at natural size
    # centered, filling the surrounding banner space with this solid color
    # instead of the default blurred backdrop. NULL = blurred-backdrop fill.
    fill_color: Mapped[str | None] = mapped_column(String(9), nullable=True)
    # Feather the image's outer edges into the fill so a small banner melts into
    # the layout to the edge of the banner space (only meaningful with fill_color).
    edge_fade: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Optional scheduling window (timed / seasonal). NULL = unbounded.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Link health — maintained by the nightly banner-link checker.
    # status: 'ok' | 'broken' | 'unknown' | None (never checked).
    link_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    link_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    link_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # True when the checker auto-hid this slide for a broken link, so it can be
    # auto-restored on recovery without clobbering an admin's manual hide.
    auto_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
