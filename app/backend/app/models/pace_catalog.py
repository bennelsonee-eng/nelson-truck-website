"""PACE ACES + PIES catalog tables.

Sourced from Auto Care Association ACES 4.2 (vehicle fitment) + PIES 7.2
(product information) XML feeds delivered by AAM.

Design notes
------------
* `vcdb_*` and `pcdb_*` tables hold reference data we either ingest from the
  Auto Care Association VCdb/PCdb releases OR backfill incrementally from the
  ID/value pairs we see in the brand feeds (see backfill strategy in the
  ingester).  IDs come from the published databases — do NOT re-key.
* `pace_part_fitment` is the row-explosion table.  Bestop alone is 33K rows;
  full catalog will likely be millions.  Indexed for the YMM lookup pattern
  (BaseVehicle + PartType => parts).
* `pace_part` is the brand-scoped bridge between an ACES `Part` value
  (raw manufacturer SKU) and our internal `Product` row.  We keep them
  separate because (a) ACES can reference a PartNumber that PIES never
  describes, (b) Product is the canonical record once enriched.
* `product_attribute`, `product_description`, `product_pricing`,
  `product_package` are normalized PIES side tables — multiple rows per
  Product, each captures one PIES sub-record.

Naming
------
We prefix new shared-reference tables with `vcdb_` / `pcdb_` (Auto Care names)
and brand-specific data tables with `pace_` so a future tenant could swap
in a different catalog source without table-name collisions.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


# --------------------------------------------------------------------------- #
# VCdb (Vehicle Configuration Database) reference tables
# --------------------------------------------------------------------------- #


class VcdbMake(Base):
    __tablename__ = "vcdb_make"

    # The id IS the Auto Care MakeID — do not auto-increment
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)


class VcdbModel(Base):
    __tablename__ = "vcdb_model"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    make_id: Mapped[int] = mapped_column(ForeignKey("vcdb_make.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    vehicle_type: Mapped[str | None] = mapped_column(String(80), index=True)


class VcdbBaseVehicle(Base):
    """A Year + Make + Model triple — the core of the YMM picker."""

    __tablename__ = "vcdb_base_vehicle"

    # The id IS BaseVehicle.id from ACES App records
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True)
    make_id: Mapped[int] = mapped_column(ForeignKey("vcdb_make.id"), nullable=False, index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("vcdb_model.id"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("year", "make_id", "model_id", name="uq_base_vehicle_ymm"),
        Index("ix_base_vehicle_ym", "year", "make_id"),
    )


class VcdbSubModel(Base):
    """Sub-trim — Crew Cab, Sport, etc."""

    __tablename__ = "vcdb_sub_model"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)


class VcdbBedLength(Base):
    __tablename__ = "vcdb_bed_length"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    length_inches: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    label: Mapped[str | None] = mapped_column(String(80))


class VcdbBedType(Base):
    __tablename__ = "vcdb_bed_type"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class VcdbBodyType(Base):
    __tablename__ = "vcdb_body_type"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class VcdbDriveType(Base):
    __tablename__ = "vcdb_drive_type"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class VcdbEngineBase(Base):
    """Engine displacement / cylinders — minimal columns to start."""

    __tablename__ = "vcdb_engine_base"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    label: Mapped[str | None] = mapped_column(String(120))


class VcdbFuelType(Base):
    __tablename__ = "vcdb_fuel_type"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class VcdbAspiration(Base):
    __tablename__ = "vcdb_aspiration"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


class VcdbRegion(Base):
    __tablename__ = "vcdb_region"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


# --------------------------------------------------------------------------- #
# PCdb (Product Classification Database) reference tables
# --------------------------------------------------------------------------- #


class PcdbPartType(Base):
    """e.g. PartType.id=1188 → 'Tonneau Cover'."""

    __tablename__ = "pcdb_part_type"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category_name: Mapped[str | None] = mapped_column(String(200), index=True)
    sub_category_name: Mapped[str | None] = mapped_column(String(200), index=True)
    # When TRUE, the PACE category scrapers skip this part type so a manual
    # taxonomy override (issues #13/#14) survives a re-scrape. See
    # scripts/add_pcdb_category_lock.sql + relink_product_categories.py.
    category_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    category_lock_reason: Mapped[str | None] = mapped_column(Text, default=None)


class PcdbPosition(Base):
    """e.g. Position.id=1 → 'Front'."""

    __tablename__ = "pcdb_position"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)


# --------------------------------------------------------------------------- #
# PACE — brand-scoped Part + Fitment
# --------------------------------------------------------------------------- #


class PacePart(Base):
    """One row per (brand, part_number) seen in either ACES or PIES.

    Acts as the bridge between PACE source data and our internal Product.
    A Product may not yet exist when ACES first creates this row; the
    PIES ingester or a later reconciliation step links them.
    """

    __tablename__ = "pace_part"

    brand_id: Mapped[int] = mapped_column(ForeignKey("brand.id", ondelete="CASCADE"),
                                           nullable=False, index=True)
    part_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Linked to the canonical Product row once PIES is ingested
    product_id: Mapped[int | None] = mapped_column(ForeignKey("product.id", ondelete="SET NULL"),
                                                    index=True)

    # Quick metadata copied from PIES for fast list rendering
    primary_image_url: Mapped[str | None] = mapped_column(String(1000))
    short_description: Mapped[str | None] = mapped_column(String(500))
    part_terminology_id: Mapped[int | None] = mapped_column(ForeignKey("pcdb_part_type.id"),
                                                              index=True)

    __table_args__ = (
        UniqueConstraint("brand_id", "part_number", name="uq_pace_part_brand_pn"),
    )


class PaceFitment(Base):
    """One row per ACES `<App>` record. Many rows per pace_part."""

    __tablename__ = "pace_fitment"

    pace_part_id: Mapped[int] = mapped_column(ForeignKey("pace_part.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    base_vehicle_id: Mapped[int] = mapped_column(ForeignKey("vcdb_base_vehicle.id"),
                                                  nullable=False, index=True)
    part_type_id: Mapped[int] = mapped_column(ForeignKey("pcdb_part_type.id"),
                                                nullable=False, index=True)

    # Common qualifiers — nullable
    sub_model_id: Mapped[int | None] = mapped_column(ForeignKey("vcdb_sub_model.id"), index=True)
    position_id: Mapped[int | None] = mapped_column(ForeignKey("pcdb_position.id"), index=True)
    bed_length_id: Mapped[int | None] = mapped_column(ForeignKey("vcdb_bed_length.id"))
    bed_type_id: Mapped[int | None] = mapped_column(ForeignKey("vcdb_bed_type.id"))
    body_type_id: Mapped[int | None] = mapped_column(ForeignKey("vcdb_body_type.id"))
    body_num_doors: Mapped[int | None] = mapped_column(SmallInteger)
    drive_type_id: Mapped[int | None] = mapped_column(ForeignKey("vcdb_drive_type.id"))
    engine_base_id: Mapped[int | None] = mapped_column(ForeignKey("vcdb_engine_base.id"))
    fuel_type_id: Mapped[int | None] = mapped_column(ForeignKey("vcdb_fuel_type.id"))
    aspiration_id: Mapped[int | None] = mapped_column(ForeignKey("vcdb_aspiration.id"))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("vcdb_region.id"))

    # Catch-all for qualifier types we haven't promoted to first-class columns yet
    extra_qualifiers: Mapped[dict | None] = mapped_column(JSON)

    qty: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    mfr_label: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # Critical lookup: "what parts of type X fit vehicle Y?"
        Index("ix_fitment_lookup", "base_vehicle_id", "part_type_id"),
        # Reverse lookup: "what vehicles does this part fit?"
        Index("ix_fitment_part_lookup", "pace_part_id"),
    )


# --------------------------------------------------------------------------- #
# PIES side tables (rich product info for the canonical Product row)
# --------------------------------------------------------------------------- #


class ProductAttribute(Base):
    """One row per PIES `<ProductAttribute>` (key/value/uom)."""

    __tablename__ = "product_attribute"

    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"),
                                             nullable=False, index=True)
    attribute_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    attribute_value: Mapped[str | None] = mapped_column(Text)
    attribute_uom: Mapped[str | None] = mapped_column(String(20))

    __table_args__ = (
        Index("ix_product_attr_kv", "attribute_key", "attribute_value"),
    )


class ProductDescription(Base):
    """One row per PIES `<Description DescriptionCode="X">` element."""

    __tablename__ = "product_description"

    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"),
                                             nullable=False, index=True)
    description_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    language_code: Mapped[str] = mapped_column(String(10), default="EN", nullable=False)
    sequence: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("ix_product_desc_code", "product_id", "description_code"),
    )


class ProductPackage(Base):
    """One row per PIES `<Package>` element (each package config a part ships in)."""

    __tablename__ = "product_package"

    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"),
                                             nullable=False, index=True)
    package_uom: Mapped[str | None] = mapped_column(String(20))
    quantity_of_eaches: Mapped[int | None] = mapped_column()
    package_gtin: Mapped[str | None] = mapped_column(String(20), index=True)
    container_type: Mapped[str | None] = mapped_column(String(20))
    weight_lb: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    length_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    width_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    height_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))


class ProductPricing(Base):
    """One row per PIES `<Pricing>` element. PriceType X PriceSheet pivot."""

    __tablename__ = "product_pricing"

    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"),
                                             nullable=False, index=True)
    price_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # LST/JBR/MSR/WD1
    price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(5), default="USD", nullable=False)
    effective_date: Mapped[date | None] = mapped_column(Date, index=True)
    price_sheet_number: Mapped[str | None] = mapped_column(String(50))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    __table_args__ = (
        # Look up the current price tier for a product fast
        Index("ix_pricing_current_lookup", "product_id", "price_type", "is_current"),
    )


class AttributeValueAlias(Base):
    """Maps a raw PIES attribute value to its display canonical.

    Catalog left-rail filters bucket on `canonical_value` so that variants
    of the same physical attribute ("TPE - Thermoplastic Elastomer" and
    "Thermoplastic Elastomer (TPE)") collapse into a single customer-facing
    checkbox.  Rows are created by the admin curator at
    /admin/attribute-curator.

    `source` flags whether the row was inserted by the auto-rules
    (case-fold + trim + plural-fold) or by a human merge.  Manual rows
    take precedence and never get rewritten by the auto pass.
    """

    __tablename__ = "attribute_value_alias"

    attribute_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_value: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)

    __table_args__ = (
        UniqueConstraint("attribute_key", "raw_value",
                          name="uq_attribute_value_alias_key_raw"),
        Index("ix_attribute_value_alias_key_canonical",
              "attribute_key", "canonical_value"),
    )


class AttributeValueDecomposition(Base):
    """Multi-output decomposition of one raw PIES value into many (key, canonical) pairs.

    PIES suppliers commonly cram two attributes into one column — e.g.
    Finish="Black Powdercoated" actually carries (Finish=Powder Coated,
    Color=Black). One AttributeValueAlias row can't express this fan-out:
    a single raw value mapping to N target rows. AttributeValueDecomposition
    fills the gap. Each input (raw_key, raw_value) produces one row per
    output (target_key, target_canonical) pair.

    Owner ask 2026-05-17 (A1).

    Example for "Black Powdercoated" under Finish:
      (Finish, "Black Powdercoated") → (Color, "Black")
      (Finish, "Black Powdercoated") → (Finish, "Powder Coated")

    The unique constraint pins one row per
    (raw_key, raw_value, target_key, target_canonical) so re-running the
    curator UI's save is idempotent.

    Canonicalization rules confirmed by owner:
      - Strip color/finish words from Material canonicals.
      - Keep multi-material values combined (don't auto-split
        "Aluminum + Stainless").
      - "Black" vs "Matte Black" are distinct colors — no auto-split
        on substring.
    """

    __tablename__ = "attribute_value_decomposition"

    raw_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    target_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_canonical: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "raw_key", "raw_value", "target_key", "target_canonical",
            name="uq_attribute_value_decomposition_full",
        ),
    )


class AttributeKeyReview(Base):
    """Marker row recording that a curator has reviewed an attribute_key.

    Lets the curator UI drop a "done" key off the queue without having to
    infer it from "no clusters left." If the underlying values shift
    later (new SKUs come in with new spellings), the curator can clear
    the row to push the key back into the review queue.
    """

    __tablename__ = "attribute_key_review"

    attribute_key: Mapped[str] = mapped_column(String(120), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("attribute_key", name="uq_attribute_key_review_key"),
    )


class AttributeKeyAlias(Base):
    """Maps a member attribute_key to its merged-group display label.

    One level up from AttributeValueAlias (which merges VALUES within a single
    key), this merges whole KEYS that describe the same physical attribute
    under different names — e.g. "Volume", "Gallon Capacity", "Liquid Storage
    Capacity", and "WEB: Box Width/Tank Capacity" all describe tank gallons and
    should render as ONE facet group on the catalog rail.

    Rows are curator-confirmed (source='manual') via /admin/attribute-key-merges.
    Every member of a group — including the one whose name becomes the
    `group_label` — gets a row, so resolving a group is a single
    `WHERE group_label = :label` lookup from either direction.

    This handles the SYNONYM case (names genuinely differ). The LABEL_VARIANT
    case (names differ only by formatting: "Overall Length" vs
    "Overall Length (in.)") is folded deterministically at render time by
    `attribute_key_merge.normalize_key_name` and needs no rows here.
    """

    __tablename__ = "attribute_key_alias"

    member_key: Mapped[str] = mapped_column(String(120), nullable=False)
    group_label: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)

    __table_args__ = (
        # A key belongs to at most one merged group.
        UniqueConstraint("member_key", name="uq_attribute_key_alias_member"),
    )
