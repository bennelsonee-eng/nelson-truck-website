"""Truck render request log — captures customer YMM + plow SKU + render result.

When a customer uses the "see it on my truck" configurator and uploads a photo
of their truck (or picks one of our pre-rendered classes), we log:
  - YMM (Year, Make, Model, Color) — fits-list intelligence + future targeting
  - Truck image URL (uploaded to S3/static)
  - Plow SKU they wanted to see
  - Rendered image URL (output from FLUX Kontext on the llama)
  - Timing + status

This becomes a goldmine for the sales team: "X customers asked to see plow Y
on truck Z this month — let's reach out with a quote."
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TruckRenderStatus(str, Enum):
    PENDING = "pending"      # request received, queued for llama
    RENDERING = "rendering"  # llama is generating the image
    COMPLETE = "complete"    # rendered image saved + URL ready
    FAILED = "failed"        # error during generation
    REJECTED = "rejected"    # NSFW filter, not-a-truck filter, etc.


class TruckRenderRequest(Base):
    """One row per "show me this plow on my truck" request."""

    __tablename__ = "truck_render_request"

    # Who made the request (anonymous-friendly: any of these may be NULL)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), index=True
    )
    session_token: Mapped[str | None] = mapped_column(String(64), index=True)

    # Year / Make / Model / Color — captured from the form even for anonymous users.
    # Used by the sales team for follow-up + builds a "fits this truck" dataset.
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    make: Mapped[str | None] = mapped_column(String(64), index=True)
    model: Mapped[str | None] = mapped_column(String(128), index=True)
    color: Mapped[str | None] = mapped_column(String(64))

    # What they uploaded (if any) vs which preset they picked
    truck_image_url: Mapped[str | None] = mapped_column(String(500))
    truck_class: Mapped[str | None] = mapped_column(String(32))  # "mid-size", "1500", "2500", etc.

    # What plow they wanted to see
    plow_sku: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Result
    rendered_image_url: Mapped[str | None] = mapped_column(String(500))
    render_duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[TruckRenderStatus] = mapped_column(
        SAEnum(
            TruckRenderStatus,
            name="truck_render_status",
            values_callable=lambda enum: [e.value for e in enum],  # use .value not .name
        ),
        default=TruckRenderStatus.PENDING,
        nullable=False,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)

    # Optional analytics
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    # Free-form notes from the customer (e.g., "I plow a 12-stop residential route")
    customer_notes: Mapped[str | None] = mapped_column(Text)
