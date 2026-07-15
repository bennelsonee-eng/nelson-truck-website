"""Pricing domain — per-product baseline price + contract-driven overrides.

Phase 1 launch: pricing engine in the website (replaces Spokane Computer's pricing
logic, which can't handle formula contracts). See SOW Q32 + Q33 + addenda.

Phase 2: pricing engine moves into / unifies with Titan ERP (Nelson ERP codebase).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ProductPrice(Base):
    """Baseline pricing per product (synced nightly at 1am PST from Titan MySQL).

    The contract resolution engine layers on top of this — if no contract matches,
    the customer's tier price falls back to one of these baseline prices.
    """

    __tablename__ = "product_price"

    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"), unique=True, nullable=False)

    # MAP / Suggested Retail (manufacturer-enforced floor; legally constrained)
    map_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    suggested_retail_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Tier defaults (overridden by contracts when applicable)
    retail_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    jobber_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    dealer_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    municipality_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Cost (from Titan MySQL — per Q13, COST is essentially empty in WSM, lives in MySQL)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Sale price (active promo)
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sale_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sale_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Persisted output of the contract/sentinel retail engine (see
    # pricing_service.resolve_retail_for_products). Mirrors what the storefront
    # DISPLAYS as "Retail", so the catalog price sort can ORDER BY a key that
    # matches the visible price instead of the raw retail_price tier (which the
    # sentinel markup diverges from per-brand). NULL until first computed — the
    # browse sort pushes NULLs last and falls back to retail_price/SRP.
    # Recomputed after each price sync and by app.scripts.recompute_resolved_retail.
    resolved_retail_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    resolved_retail_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Contract(Base):
    """Contract-driven pricing rules (FS-035).

    Schema mirrors Titan's existing structure (per Q14 verbatim):
      customer_number, brand, group_code, part_number, priority,
      min_quantity, pricing_formula, expiration_date

    Resolution algorithm (per addendum 003 + Q32):
      1. Query rows where customer_id matches AND scope matches product
         AND qty >= min_quantity AND not expired
      2. Sort by priority DESC
      3. Apply top-priority row's pricing_formula
      4. Falls through to ProductPrice tier default if no contract matches.
    """

    __tablename__ = "contract"

    name: Mapped[str] = mapped_column(String(200), nullable=False)  # e.g., "Sourcewell via NAFG"
    description: Mapped[str | None] = mapped_column(Text)

    # Scope — fields are nullable for "applies to anything in this dimension"
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customer.id", ondelete="SET NULL"), index=True)
    brand: Mapped[str | None] = mapped_column(String(200), index=True)
    group_code: Mapped[str | None] = mapped_column(String(100), index=True)
    part_number: Mapped[str | None] = mapped_column(String(64), index=True)

    # Higher priority wins when multiple rows match a customer/product combo
    priority: Mapped[int] = mapped_column(default=100, nullable=False, index=True)

    # Volume gate
    min_quantity: Mapped[int] = mapped_column(default=1, nullable=False)

    # Formula DSL (e.g., "=$250.00", "cost+12%", "list-25%", "list-25%/main;list-15%/accessory")
    pricing_formula: Mapped[str] = mapped_column(String(500), nullable=False)

    # Validity window
    effective_date: Mapped[date | None] = mapped_column(Date)
    expiration_date: Mapped[date | None] = mapped_column(Date, index=True)

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    # For Sourcewell-via-NAFG and other named partner contracts
    partner_program: Mapped[str | None] = mapped_column(String(100))  # "Sourcewell", "DOT", "GSA" etc
    partner_organization: Mapped[str | None] = mapped_column(String(100))  # "NAFG"

    customer: Mapped["Customer"] = relationship(back_populates="contracts")  # noqa: F821 — forward ref
