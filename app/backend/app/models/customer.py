"""Customer domain — accounts, addresses, tier pricing relationship."""

from __future__ import annotations

from enum import Enum

from sqlalchemy import Boolean, Enum as SAEnum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CustomerTier(str, Enum):
    """Pricing/UX tier per Q1, Q7, Q9, Q10."""

    RETAIL = "retail"               # anonymous; no login
    JOBBER = "jobber"               # ~100 known, ~20-30 active
    DEALER = "dealer"               # car dealerships (Honda, GMC, etc.)
    MUNICIPALITY = "municipality"   # state/county/mass transit/federal


class AddressType(str, Enum):
    BILLING = "billing"
    SHIPPING = "shipping"


class Customer(Base):
    """Customer account record. Maps 1:1 to FACS customer_number for B2B tiers.

    Anonymous retail orders use the sentinel customer_number `106415`
    (per addendum 003 reverse-engineered from PHP — line 233-235).
    """

    __tablename__ = "customer"

    # FACS customer number — primary identifier for IMS315 order export
    customer_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)

    tier: Mapped[CustomerTier] = mapped_column(
        SAEnum(CustomerTier, name="customer_tier"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200), index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    fax: Mapped[str | None] = mapped_column(String(32))

    # Sales rep assignment (legacy WSM stored in checkout question; we make it explicit)
    sales_rep_code: Mapped[str | None] = mapped_column(String(20))

    # Tax-exempt status (FS-023 — for muni / resale)
    is_tax_exempt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tax_exempt_cert_number: Mapped[str | None] = mapped_column(String(100))
    tax_exempt_state: Mapped[str | None] = mapped_column(String(2))

    # Net-terms billing (typical for muni / dealer / large jobber)
    payment_terms: Mapped[str | None] = mapped_column(String(20))  # "net30", "net45", "cod", etc.
    credit_limit_usd: Mapped[int | None] = mapped_column()

    # Front Counter / Retail View default markup (FS-069)
    # Jobbers can set a default markup % to apply when in Retail View mode
    retail_view_markup_percent: Mapped[int | None] = mapped_column()

    # Retail Showroom Mode (white-label kiosk) — a jobber/dealer can turn the
    # storefront into their own branded, Truck-Accessories-only catalog to use
    # with a walk-in customer. Config is account-wide (here); the active kiosk
    # lock is per-device (frontend localStorage). Pricing reuses
    # retail_view_markup_percent via front_counter_quote().
    showroom_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    showroom_logo_url: Mapped[str | None] = mapped_column(String(1000))
    showroom_display_name: Mapped[str | None] = mapped_column(String(200))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Bill-to parent for B2B account hierarchies (A4.10, A4.20). Each physical
    # location of a jobber gets its own Customer row + FACS customer#, all
    # pointing at the same parent bill-to. NULL for top-level customers.
    parent_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customer.id", ondelete="SET NULL"), index=True
    )

    addresses: Mapped[list[CustomerAddress]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )
    contracts: Mapped[list["Contract"]] = relationship(back_populates="customer")  # noqa: F821

    parent_customer: Mapped["Customer | None"] = relationship(
        "Customer",
        remote_side="Customer.id",
        back_populates="child_locations",
        foreign_keys="Customer.parent_customer_id",
    )
    child_locations: Mapped[list["Customer"]] = relationship(
        "Customer",
        back_populates="parent_customer",
        foreign_keys="Customer.parent_customer_id",
    )


class CustomerAddress(Base):
    __tablename__ = "customer_address"

    customer_id: Mapped[int] = mapped_column(ForeignKey("customer.id", ondelete="CASCADE"), nullable=False, index=True)
    address_type: Mapped[AddressType] = mapped_column(
        SAEnum(AddressType, name="address_type"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    name: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    addr1: Mapped[str] = mapped_column(String(200), nullable=False)
    addr2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    country: Mapped[str] = mapped_column(String(2), default="US", nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="addresses")
