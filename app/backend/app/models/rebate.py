"""Rebate engine — audience-scoped, scheduled manufacturer/Titan rebate programs
shown in the Deal Warehouse Rebate Center. Admin-managed in /admin/rebates.

v1 covers the homepage Rebate Center: list active programs by audience with
amount, qualifying-threshold text, claim method, and expiry. Structured
eligibility rules (min order / qty / series) + cart-level evaluation and
progress nudges come with the cart/PDP phase.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RebateAudience(str, Enum):
    RETAIL = "retail"
    WHOLESALE = "wholesale"
    BOTH = "both"


class RebateClaimMethod(str, Enum):
    INSTANT = "instant"    # Titan-funded: applied as a discount at checkout
    MAIL_IN = "mail_in"    # mfr-funded: surface eligibility + generate claim; price unchanged


class RebateType(str, Enum):
    FIXED = "fixed"          # flat dollar amount
    PERCENT = "percent"      # percentage back
    PER_UNIT = "per_unit"    # dollar amount per unit


class RebateProgram(Base):
    __tablename__ = "rebate_program"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)        # display brand, e.g. "WESTERN"
    amount_label: Mapped[str] = mapped_column(String(40), nullable=False)        # "$500", "10% back", "$75 / unit"
    rebate_type: Mapped[RebateType] = mapped_column(
        SAEnum(RebateType, name="rebate_type", values_callable=lambda x: [e.value for e in x]),
        default=RebateType.FIXED, nullable=False,
    )
    terms: Mapped[str | None] = mapped_column(String(200), nullable=True)        # "PRO-PLUS plow systems"
    threshold_label: Mapped[str | None] = mapped_column(String(160), nullable=True)  # "Complete plow purchase" / "$15,000+ order"
    fine_print: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)    # terms / claim portal

    audience: Mapped[RebateAudience] = mapped_column(
        SAEnum(RebateAudience, name="rebate_audience", values_callable=lambda x: [e.value for e in x]),
        default=RebateAudience.BOTH, nullable=False, index=True,
    )
    claim_method: Mapped[RebateClaimMethod] = mapped_column(
        SAEnum(RebateClaimMethod, name="rebate_claim_method", values_callable=lambda x: [e.value for e in x]),
        default=RebateClaimMethod.MAIL_IN, nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
