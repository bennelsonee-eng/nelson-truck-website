"""Catalog domain — Brand, Category, Product, ProductImage."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Boolean,
    Enum as SAEnum,
    ForeignKey,
    Index,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class CTAMode(str, Enum):
    """Per-product call-to-action mode (FS-043).

    Mapped from WSM SHIP QUOTE flag during import + admin overrides afterward.
    """

    ADD_TO_CART = "add_to_cart"
    QUOTE_SHIPPING = "quote_shipping"
    BROWSE_ONLY = "browse_only"


class ShippingMode(str, Enum):
    """How a product is fulfilled when shipped/picked up (owner ask 2026-07-16).

    Toggleable per product (and by manufacturer line / category / filter) via
    the admin catalog tree, exactly like `is_hidden` — see
    app.services.catalog_visibility. Drives the storefront badge + checkout.

    Note: WILL_CALL means pickup-ONLY (not shippable). Separately, will-call
    pickup is offered on ANY in-stock product at its stocking branch — that is
    checkout behavior, not this field.
    """

    SHIP = "ship"                    # normal parcel / ground
    TRUCK_FREIGHT = "truck_freight"  # LTL freight — shippable, heavy; "Truck Freight" badge
    WILL_CALL = "will_call"          # pickup only, from current stocking area; "Will Call" badge


class GroupRequirement(str, Enum):
    """Tier visibility restriction (mirrors WSM GROUPREQUIRED column).

    None = visible to all tiers. Specific value = visible only to that tier(s).
    """

    JOBBER = "jobber"
    JOBBER_MUNICIPALITY = "jobber_municipality"


# --------------------------------------------------------------------------- #
# Brand
# --------------------------------------------------------------------------- #


class Brand(Base):
    __tablename__ = "brand"

    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)

    # WSM legacy STOCKID prefix (e.g., "BGND" for Superchips, "DVPF" for Currie).
    # Used during migration to map WSM SKUs back to brand.
    legacy_wsm_prefix: Mapped[str | None] = mapped_column(String(8), index=True)

    # PACE / Auto Care Association brand codes (added 2026-05-09).
    # Lookup matches against AAM_<aaia_code>_*.zip filenames AND PIES <BrandAAIAID>.
    aaia_code: Mapped[str | None] = mapped_column(String(10), unique=True, index=True)
    # PIES <ParentAAIAID> — distributor's parent brand (e.g. Bestop's parent is HSQS).
    parent_aaia_id: Mapped[str | None] = mapped_column(String(10))

    logo_url: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(String(500))

    # Featured-product priority. Titan heavily stocks ~38 brands; those get is_featured=true.
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(default=1000, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Manufacturer lead-time on a special order (OOS but still orderable).
    # Owner ask 2026-05-17 (L9). Render as "Special order — typically X-Y
    # business days" on the buy box / list rows. Both nullable: a brand
    # with no lead-time set just shows the generic "Special order" label.
    special_order_lead_time_min_days: Mapped[int | None] = mapped_column()
    special_order_lead_time_max_days: Mapped[int | None] = mapped_column()

    products: Mapped[list[Product]] = relationship(back_populates="brand")


# --------------------------------------------------------------------------- #
# Category (self-referential tree, arbitrary depth)
# --------------------------------------------------------------------------- #


class Category(Base):
    __tablename__ = "category"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category.id", ondelete="SET NULL"), index=True)

    # Materialized full path (e.g., "Truck > Make > Model > Floor Mats")
    # Useful for breadcrumb display + faster lookups vs recursive parent walk.
    full_path: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    depth: Mapped[int] = mapped_column(default=0, nullable=False, index=True)

    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=1000, nullable=False)
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Admin-curated representative image. Wins over the algorithmic name-match
    # / own-direct / descendant / brand-logo tier chain in the catalog router.
    curated_image_url: Mapped[str | None] = mapped_column(String(1000))

    parent: Mapped[Category | None] = relationship(
        "Category", remote_side="Category.id", back_populates="children"
    )
    children: Mapped[list[Category]] = relationship(back_populates="parent")

    __table_args__ = (
        UniqueConstraint("full_path", name="uq_category_full_path"),
    )


# --------------------------------------------------------------------------- #
# Product
# --------------------------------------------------------------------------- #


class Product(Base):
    __tablename__ = "product"

    # Internal Titan SKU (clean, generated). Used as the canonical product ID
    # in URLs, FACS exports, etc.
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    # Legacy IDs preserved for migration traceability + 301-redirect logic
    legacy_wsm_id: Mapped[int | None] = mapped_column(unique=True, index=True)
    legacy_wsm_stockid: Mapped[str | None] = mapped_column(String(64), index=True)
    legacy_wsm_dealerid: Mapped[str | None] = mapped_column(String(64), index=True)
    # TigerTech internal SKU (the `ourparts_num` column from tte_parts_master /
    # tte_inv_days).  Populated by scripts/link_tte_inventory.py via brand
    # prod_code + supplier-part-suffix matching.  Used to join inventory
    # rows from the TTE feed onto our catalog products.  Non-unique because
    # the same product can legitimately have multiple legacy ourparts_num
    # entries (aliases, consolidations).
    tte_ourparts_num: Mapped[str | None] = mapped_column(String(64), index=True)

    # Identity
    brand_id: Mapped[int] = mapped_column(ForeignKey("brand.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)

    # Internal Titan brand/product code (3-4 letters; matches contracts.prod_code).
    # Used by the pricing engine for contract scope matching.
    prod_code: Mapped[str | None] = mapped_column(String(16), index=True)

    # Content (most populated >94% in WSM data)
    description: Mapped[str | None] = mapped_column(Text)
    extended_description: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    series: Mapped[str | None] = mapped_column(String(200), index=True)
    tags: Mapped[list[str] | None] = mapped_column(JSON)
    upc: Mapped[str | None] = mapped_column(String(32), index=True)

    # SEO (94%+ populated in WSM)
    meta_title: Mapped[str | None] = mapped_column(String(500))
    meta_description: Mapped[str | None] = mapped_column(Text)
    meta_keywords: Mapped[str | None] = mapped_column(Text)
    google_category: Mapped[str | None] = mapped_column(String(500))

    # Physical attributes
    weight_lb: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    length_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    width_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    height_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    freight_class: Mapped[str | None] = mapped_column(String(32), index=True)

    # Behavior flags
    cta_mode: Mapped[CTAMode] = mapped_column(
        SAEnum(CTAMode, name="cta_mode"), default=CTAMode.ADD_TO_CART, nullable=False, index=True
    )
    requires_shipping: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    taxable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    own_box: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ship_quote: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    free_ground: Mapped[int] = mapped_column(default=0, nullable=False)  # WSM uses 0/1/2/3
    handling_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    shipping_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    # Visibility
    # `is_hidden` is the EFFECTIVE flag every surface reads (search, browse,
    # sitemap, PDP noindex). It is DERIVED by the catalog-visibility resolver
    # (app.services.catalog_visibility) from `base_hidden` + admin overrides —
    # do not hand-set it in import scripts; set `base_hidden` instead.
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # Baseline "hidden for non-override reasons" (import defaults like the
    # Buyers 13k, discontinued, never-stocked). Importers write THIS; the
    # resolver falls back to it for any product with no applicable override.
    base_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_for_sale: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # Shipping fulfillment mode — ship | truck_freight | will_call (see
    # ShippingMode). `shipping_mode` is the EFFECTIVE value (drives badge +
    # checkout), DERIVED by the catalog resolver from `base_shipping_mode` +
    # admin overrides — same pattern as is_hidden/base_hidden. Importers /
    # seeds write `base_shipping_mode`; the resolver falls back to it.
    shipping_mode: Mapped[str] = mapped_column(String(20), default="ship", nullable=False, index=True)
    base_shipping_mode: Mapped[str] = mapped_column(String(20), default="ship", nullable=False, index=True)

    # Flat-rate shipping override (owner ask 2026-07-16). NULL = use the normal
    # weight-tiered freight calc; 0.00 = free shipping; > 0 = charge that flat
    # amount. `flat_ship_amount` is the EFFECTIVE value (freight_service reads
    # it), DERIVED by the resolver from `base_flat_ship_amount` + overrides —
    # same pattern as is_hidden / shipping_mode. will_call items ignore it.
    flat_ship_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    base_flat_ship_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    login_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    group_required: Mapped[GroupRequirement | None] = mapped_column(
        SAEnum(GroupRequirement, name="group_requirement"), index=True
    )
    saleprice_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Denormalized "universal fit" flag: True when this product has ZERO
    # pace_fitment rows reachable via any of its pace_part rows (covers both
    # "no pace_part at all" and "has pace_part(s) but none carry an ACES
    # fitment"). Lets the vehicle / vehicle_type browse filter collapse two
    # catalog-wide OR-subquery scans into one indexed boolean check — the
    # product surfaces under a YMM/class filter if it either has a matching
    # fitment OR is universal. Maintained by the PACE ingest (recompute at
    # end of run) and backfilled in the migration. Default True so a freshly
    # inserted product (no fitment yet) reads as universal until proven
    # otherwise. See _browse_via_pace in routers/catalog.py.
    # server_default mirrors the migration (constant `true`) so a freshly added
    # row is universal until ingest recomputes, and autogenerate sees no drift.
    # No index: a 2-value boolean the planner ignores once "true" dominates; the
    # browse filter is already narrowed by category before this is consulted.
    has_no_fitment: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    # Sourcing
    legacy_wsm_availability: Mapped[str | None] = mapped_column(String(32), index=True)  # "Limited Supply" etc.
    legacy_wsm_url: Mapped[str | None] = mapped_column(String(1000))
    legacy_wsm_owner: Mapped[str | None] = mapped_column(String(200))
    admin_notes: Mapped[str | None] = mapped_column(Text)
    email_notes: Mapped[str | None] = mapped_column(Text)
    available_remarks: Mapped[str | None] = mapped_column(Text)
    shipping_remarks: Mapped[str | None] = mapped_column(Text)

    # Relationships
    brand: Mapped[Brand] = relationship(back_populates="products")
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", order_by="ProductImage.sort_order", cascade="all, delete-orphan"
    )
    categories: Mapped[list[ProductCategory]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_product_brand_active", "brand_id", "is_hidden", "is_for_sale"),
        Index("ix_product_search", "name", "sku"),  # for fallback DB search if Typesense down
    )


# --------------------------------------------------------------------------- #
# Product ↔ Category (many-to-many; primary category flag for breadcrumb)
# --------------------------------------------------------------------------- #


class ProductCategory(Base):
    __tablename__ = "product_category"

    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id", ondelete="CASCADE"), nullable=False, index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    product: Mapped[Product] = relationship(back_populates="categories")
    category: Mapped[Category] = relationship()

    __table_args__ = (
        UniqueConstraint("product_id", "category_id", name="uq_product_category"),
    )


# --------------------------------------------------------------------------- #
# Product images
# --------------------------------------------------------------------------- #


class ProductImage(Base):
    __tablename__ = "product_image"

    product_id: Mapped[int] = mapped_column(ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Phase 1 launch: url points to nelsontruck.com cross-domain.
    # Pre-launch: rewrite to titantruck.com self-hosted (DI-029).
    legacy_origin: Mapped[str | None] = mapped_column(String(64))  # e.g., "nelsontruck.com"

    product: Mapped[Product] = relationship(back_populates="images")


# --------------------------------------------------------------------------- #
# Product fitment — scraped (non-ACES) vehicle compatibility
# --------------------------------------------------------------------------- #


class ProductFitment(Base):
    """One row per (product × vehicle year-range) fitment claim, sourced from
    scraped vendor PDPs.

    Distinct from `PaceFitment` in pace_catalog.py:
      * PaceFitment is the ACES/VCDB industry-standard fitment with rich
        qualifiers + VCDB base_vehicle_id, populated from ACES XML feeds.
      * ProductFitment is plain-text make/model + year range, populated
        from PDP scraping (e.g. Buyers mount-family year/model grids).
        Used as a low-resolution fallback when no PaceFitment rows exist
        for a SKU — the /products/{sku}/fitments endpoint queries
        PaceFitment first and falls through to this table when empty.

    Buyers mount-family example: SKU 16063120 → start_year=2002,
    end_year=2005, make='RAM', model='1500', source='buyersproducts.com'.
    """

    __tablename__ = "product_fitment"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    year_start: Mapped[int | None] = mapped_column(SmallInteger)
    year_end: Mapped[int | None] = mapped_column(SmallInteger)
    make: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model: Mapped[str | None] = mapped_column(String(120), index=True)
    # Free-text qualifier (e.g. "with Plow Prep", "Crew Cab", "diesel only")
    note: Mapped[str | None] = mapped_column(Text)
    # Where this fitment came from — useful for dedupe + selective re-scrape
    source: Mapped[str] = mapped_column(
        String(60), nullable=False, default="buyersproducts.com",
    )

    __table_args__ = (
        # Reverse lookup: "what products fit a 2002 RAM 1500?"
        Index("ix_product_fitment_make_model", "make", "model"),
        # Dedupe per (product × vehicle × source). NULLs in year_start /
        # year_end are accepted as not-equal by Postgres, so the scraper
        # should populate years whenever possible (the Buyers fitment
        # grid always has them).
        UniqueConstraint(
            "product_id", "make", "model", "year_start", "year_end", "source",
            name="uq_product_fitment_unique",
        ),
    )
