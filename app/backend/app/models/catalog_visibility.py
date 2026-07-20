"""Catalog overrides — the admin show/hide + shipping-mode tree's storage.

An admin turns manufacturer lines, categories, curated filter-values, or
individual parts on/off — and sets their shipping mode — from the admin control
panel. Each toggle is one `CatalogOverride` row. A resolver
(`app.services.catalog_visibility`) folds the whole override set down onto the
derived product columns (`Product.is_hidden`, `Product.shipping_mode`) at the
nightly re-index (and on "Apply now"), so every existing surface keeps working
unchanged.

Each row targets one FIELD (see OVERRIDABLE_FIELDS) with one VALUE, at one
scope. Precedence (most specific wins): product > filter > category > brand.
Per field, a scope with no override inherits from the parent scope, and
ultimately from the product's baseline (`base_hidden` / `base_shipping_mode`).
For the `hidden` field, value "false" is an explicit SHOW that punches through a
broader hide.

scope_type / field / value are plain strings validated at the API layer (same
pattern as build_idea). `scope_key` is a deterministic scope identity the
service computes; uniqueness is (scope_key, field) so a scope can carry one
override per field.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


# field -> (product column it materializes, allowed values). "hidden" stores
# "true"/"false"; "shipping_mode" stores a ShippingMode value.
OVERRIDABLE_FIELDS = ("hidden", "shipping_mode", "flat_ship_amount")


class CatalogOverride(Base):
    """One admin decision (a field=value) at a brand / category / filter / product scope."""

    __tablename__ = "catalog_override"
    __table_args__ = (
        UniqueConstraint("scope_key", "field", name="uq_catalog_override_scope_field"),
    )

    # brand | category | product | filter
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Deterministic identity for this scope so a repeat toggle upserts.
    #   brand:{id} | category:{id} | product:{id}
    #   filter:{brand_id|*}:{category_id|*}:{attr_key}={attr_value}
    scope_key: Mapped[str] = mapped_column(String(400), nullable=False, index=True)

    # What this override sets. See OVERRIDABLE_FIELDS.
    field: Mapped[str] = mapped_column(String(30), nullable=False, default="hidden")
    # The value for `field` as text: hidden -> "true"/"false"; shipping_mode ->
    # "ship"/"truck_freight"/"will_call".
    value: Mapped[str] = mapped_column(String(50), nullable=False)

    # Structured scope targets (only the ones relevant to scope_type are set).
    brand_id: Mapped[int | None] = mapped_column(
        ForeignKey("brand.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="CASCADE"), nullable=True, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Filter scope only — the CURATED attribute key + canonical value (matches
    # the storefront left rail: attribute_value_alias.canonical_value). The
    # resolver maps canonical -> raw PIES values, bounded by brand_id/category_id.
    attr_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attr_value: Mapped[str | None] = mapped_column(String(400), nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When the resolver last materialized this override onto products. NULL or
    # < updated_at => pending (not yet reflected on the site until the next
    # nightly re-index or "Apply now").
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit breadcrumb — admin email + id that last set this override.
    updated_by: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    updated_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
