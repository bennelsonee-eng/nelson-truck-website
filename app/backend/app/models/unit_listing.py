"""Trucks & equipment for sale: whole-unit listings and everything hung off them.

Nelson carries roughly $900K of whole units at any time -- cab-chassis, Jerr-Dan
wreckers and carriers, Dur-A-Lift bucket trucks, Landoll trailers, the odd crane
truck -- and until 2026-09-25 none of it was on this site. Ben wanted it "front
and center" and posted the way CommercialTruckTrader's dealer backend does it,
organised as Inventory, Leads and Reports.

Pricing has one hard rule: Jerr-Dan does not let dealers advertise a retail
price for its wreckers and carriers. Such a listing never shows its price;
instead a customer can confirm the unit's specs, leave contact details and get
a price range -- a one-to-one quote, delivered by email as well. See
`app/services/unit_listings.py` for where that is enforced.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (BigInteger, Boolean, Date, DateTime, ForeignKey, Integer,
                        Numeric, String, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

UNIT_STATUSES = ("draft", "active", "pending", "sold", "archived")
UNIT_AVAILABILITY = ("in_stock", "future_build")
UNIT_CATEGORIES = ("wrecker", "carrier", "aerial", "trailer", "crane",
                   "cab-chassis", "service", "dump", "equipment", "other")
UNIT_CONDITIONS = ("new", "used", "demo")
UNIT_TYPES = ("truck", "trailer", "equipment")
OWNERSHIP = ("nelson", "consignment")
UNIT_LOCATIONS = ("portland", "kent", "spokane")
PRICE_MODES = ("show", "call", "range")
RANGE_DELIVERY = ("screen_email", "email_only")
PART_ROLES = ("unit", "chassis", "body", "trailer", "equipment")
MEDIA_KINDS = ("photo", "video", "document")
DOC_TYPES = ("spec_sheet", "window_sticker", "inspection", "brochure", "other")
LEAD_KINDS = ("price_range", "build_quote", "quote", "call", "question", "offer")
LEAD_STATUSES = ("new", "contacted", "quoted", "won", "lost", "spam")


class UnitListing(Base):
    __tablename__ = "unit_listing"

    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", index=True)
    availability: Mapped[str] = mapped_column(String(16), nullable=False, default="in_stock", index=True)
    available_date: Mapped[date | None] = mapped_column(Date)
    available_note: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(24), nullable=False, default="other", index=True)
    condition: Mapped[str] = mapped_column(String(12), nullable=False, default="new")
    unit_type: Mapped[str] = mapped_column(String(12), nullable=False, default="truck")
    # A consigned unit belongs to a customer: no ERP part number needed, and the
    # consignor fields are admin-only.
    ownership: Mapped[str] = mapped_column(String(16), nullable=False, default="nelson", index=True)
    consignor_name: Mapped[str | None] = mapped_column(String(160))
    consignor_contact: Mapped[str | None] = mapped_column(String(200))
    consignor_customer_number: Mapped[str | None] = mapped_column(String(20))
    consignor_notes: Mapped[str | None] = mapped_column(Text)

    year: Mapped[int | None] = mapped_column(Integer)
    make: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(80))
    trim: Mapped[str | None] = mapped_column(String(60))
    vin: Mapped[str | None] = mapped_column(String(17), index=True)
    stock_number: Mapped[str | None] = mapped_column(String(40))
    mileage: Mapped[int | None] = mapped_column(Integer)
    engine_hours: Mapped[int | None] = mapped_column(Integer)
    cab_type: Mapped[str | None] = mapped_column(String(30))
    drive: Mapped[str | None] = mapped_column(String(10))
    fuel: Mapped[str | None] = mapped_column(String(20))
    engine: Mapped[str | None] = mapped_column(String(120))
    horsepower: Mapped[int | None] = mapped_column(Integer)
    transmission: Mapped[str | None] = mapped_column(String(120))
    gvwr_lbs: Mapped[int | None] = mapped_column(Integer)
    wheelbase_in: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    cab_to_axle_in: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    front_axle_lbs: Mapped[int | None] = mapped_column(Integer)
    rear_axle_lbs: Mapped[int | None] = mapped_column(Integer)
    suspension: Mapped[str | None] = mapped_column(String(60))
    brakes: Mapped[str | None] = mapped_column(String(40))
    color: Mapped[str | None] = mapped_column(String(40))
    tires: Mapped[str | None] = mapped_column(String(60))
    fuel_capacity: Mapped[str | None] = mapped_column(String(30))
    cdl_required: Mapped[bool | None] = mapped_column(Boolean)

    upfit_make: Mapped[str | None] = mapped_column(String(60))
    upfit_model: Mapped[str | None] = mapped_column(String(120))
    upfit_description: Mapped[str | None] = mapped_column(Text)

    specs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    features: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    spec_sheet: Mapped[str | None] = mapped_column(Text)
    headline: Mapped[str | None] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(20))

    price_mode: Mapped[str] = mapped_column(String(12), nullable=False, default="range")
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    range_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    range_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    range_delivery: Mapped[str] = mapped_column(String(16), nullable=False, default="screen_email")
    qualify_specs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    featured_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    video_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    ctt_ad_id: Mapped[str | None] = mapped_column(String(20))
    created_by: Mapped[str | None] = mapped_column(String(254))
    updated_by: Mapped[str | None] = mapped_column(String(254))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UnitListingPart(Base):
    __tablename__ = "unit_listing_part"

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("unit_listing.id", ondelete="CASCADE"), nullable=False, index=True)
    part_number: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    # Eight MPL40 bodies share one part number; the serial says which one.
    serial: Mapped[str | None] = mapped_column(String(40))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="unit")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UnitListingMedia(Base):
    __tablename__ = "unit_listing_media"

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("unit_listing.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str] = mapped_column(String(400), nullable=False)
    thumb_url: Mapped[str | None] = mapped_column(String(400))
    poster_url: Mapped[str | None] = mapped_column(String(400))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    bytes: Mapped[int | None] = mapped_column(BigInteger)
    original_name: Mapped[str | None] = mapped_column(String(200))
    caption: Mapped[str | None] = mapped_column(String(200))
    doc_type: Mapped[str | None] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UnitLead(Base):
    __tablename__ = "unit_lead"

    listing_id: Mapped[int | None] = mapped_column(
        ForeignKey("unit_listing.id", ondelete="SET NULL"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="new", index=True)
    # Snapshot, so a lead still reads right after its listing is edited or sold.
    listing_title: Mapped[str | None] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    company: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    zip: Mapped[str | None] = mapped_column(String(12))
    message: Mapped[str | None] = mapped_column(Text)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    specs_confirmed: Mapped[bool | None] = mapped_column(Boolean)
    range_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    range_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    range_shown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    range_emailed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    offer_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    page_url: Mapped[str | None] = mapped_column(String(500))
    source_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    handled_by: Mapped[str | None] = mapped_column(String(254))
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class UnitListingStat(Base):
    __tablename__ = "unit_listing_stat"
    __table_args__ = (UniqueConstraint("listing_id", "day", name="uq_unit_listing_stat_day"),)

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("unit_listing.id", ondelete="CASCADE"), nullable=False)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class UnitPriceGuide(Base):
    """One choice in the Build & Price quote builder, with what it adds to the price."""

    __tablename__ = "unit_price_guide"

    category: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String(60), nullable=False)
    group_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    multi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(300))
    price_low: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    price_high: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    basis: Mapped[str | None] = mapped_column(String(300))


class ErpOnhand(Base):
    """nte_inv_days joined to nte_parts_master, refreshed every 15 minutes.

    Lets the unit admin check a part number, find what is in stock but not
    listed, and show cost and days-in-stock -- all admin-only; none of it is
    ever serialised to a public endpoint.
    """

    __tablename__ = "erp_onhand"

    part_number: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    prod_code: Mapped[str | None] = mapped_column(String(12), index=True)
    warehouse: Mapped[int | None] = mapped_column(Integer)
    onhand: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    available: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    gl_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    days: Mapped[int | None] = mapped_column(Integer)
    serial: Mapped[str | None] = mapped_column(String(40), index=True)
    description: Mapped[str | None] = mapped_column(String(200))
    extra_desc: Mapped[str | None] = mapped_column(String(200))
    p1: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    p2: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    p3: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
