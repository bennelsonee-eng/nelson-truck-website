"""Trucks & equipment for sale — whole-unit listings, their leads, and the ERP on-hand mirror.

Nelson carries roughly $900K of whole units at any time: cab-chassis, Jerr-Dan
wreckers and carriers, Dur-A-Lift bucket trucks, Landoll trailers, now and then a
crane truck. Only a handful ever reached CommercialTruckTrader and none reached
this site (Ben, 2026-09-25: "front and center, in your face").

  unit_listing        one row per unit for sale (or future build), Nelson's own
                      or consigned by a customer (a used knuckle-boom crane, a
                      dump bed -- equipment as well as whole trucks).
  unit_listing_part   the ERP part numbers a listing is built from -- a chassis,
                      a body, a trailer -- down to the serial, since eight MPL40
                      bodies share one part number. A stocked listing needs at
                      least one part that is on hand.
  unit_listing_media  photos (10+ to publish), videos and documents.
  unit_lead           every price-range request, quote, call-back and offer.
  unit_listing_stat   views per listing per day, for Reports.
  unit_price_guide    the Build & Price quote builder's price book: base configs
                      and option adders per category. A customer who specs the
                      truck they want gets a deliberately wide range from it and
                      a salesperson follows up (Ben, 2026-09-25).
  erp_onhand          the legacy nte_inv_days feed joined to the parts master,
                      refreshed with the 15-minute inventory job, so a part
                      number can be checked without a round trip to MySQL.

Revision ID: h3c6d0e4f8a2
Revises: g2b5c9d3e7f1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h3c6d0e4f8a2"
down_revision: Union[str, None] = "g2b5c9d3e7f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "unit_listing",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        # draft | active | pending (sale pending) | sold | archived
        sa.Column("status", sa.String(16), nullable=False, server_default="draft", index=True),
        # in_stock | future_build
        sa.Column("availability", sa.String(16), nullable=False, server_default="in_stock", index=True),
        sa.Column("available_date", sa.Date, nullable=True),
        sa.Column("available_note", sa.String(120), nullable=True),
        # wrecker | carrier | aerial | trailer | crane | cab-chassis | service | dump | other
        sa.Column("category", sa.String(24), nullable=False, server_default="other", index=True),
        sa.Column("condition", sa.String(12), nullable=False, server_default="new"),
        # truck | trailer | equipment. Equipment (a knuckle-boom crane, a dump
        # bed) has no chassis, so the form and the page drop the chassis fields.
        sa.Column("unit_type", sa.String(12), nullable=False, server_default="truck"),
        # nelson | consignment. A consigned unit belongs to a customer and is
        # not in Nelson's on-hand, so it is the one kind that needs no ERP part
        # number. Consignor details are internal and never leave the admin.
        sa.Column("ownership", sa.String(16), nullable=False, server_default="nelson", index=True),
        sa.Column("consignor_name", sa.String(160), nullable=True),
        sa.Column("consignor_contact", sa.String(200), nullable=True),
        sa.Column("consignor_customer_number", sa.String(20), nullable=True),
        sa.Column("consignor_notes", sa.Text, nullable=True),
        # chassis
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("make", sa.String(60), nullable=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("trim", sa.String(60), nullable=True),
        sa.Column("vin", sa.String(17), nullable=True, index=True),
        sa.Column("stock_number", sa.String(40), nullable=True),
        sa.Column("mileage", sa.Integer, nullable=True),
        sa.Column("engine_hours", sa.Integer, nullable=True),
        sa.Column("cab_type", sa.String(30), nullable=True),
        sa.Column("drive", sa.String(10), nullable=True),
        sa.Column("fuel", sa.String(20), nullable=True),
        sa.Column("engine", sa.String(120), nullable=True),
        sa.Column("horsepower", sa.Integer, nullable=True),
        sa.Column("transmission", sa.String(120), nullable=True),
        sa.Column("gvwr_lbs", sa.Integer, nullable=True),
        sa.Column("wheelbase_in", sa.Numeric(6, 1), nullable=True),
        sa.Column("cab_to_axle_in", sa.Numeric(6, 1), nullable=True),
        sa.Column("front_axle_lbs", sa.Integer, nullable=True),
        sa.Column("rear_axle_lbs", sa.Integer, nullable=True),
        sa.Column("suspension", sa.String(60), nullable=True),
        sa.Column("brakes", sa.String(40), nullable=True),
        sa.Column("color", sa.String(40), nullable=True),
        sa.Column("tires", sa.String(60), nullable=True),
        sa.Column("fuel_capacity", sa.String(30), nullable=True),
        sa.Column("cdl_required", sa.Boolean, nullable=True),
        # upfit -- what Nelson installed on the chassis
        sa.Column("upfit_make", sa.String(60), nullable=True),
        sa.Column("upfit_model", sa.String(120), nullable=True),
        sa.Column("upfit_description", sa.Text, nullable=True),
        # [{"label": "Deck length", "value": "22 ft"}, ...] -- category-specific
        sa.Column("specs", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("features", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        # the full chassis spec sheet, pasted as-is
        sa.Column("spec_sheet", sa.Text, nullable=True),
        sa.Column("headline", sa.String(160), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        # portland | kent | spokane
        sa.Column("location", sa.String(20), nullable=True),
        # show | call | range. Jerr-Dan may not advertise a price, so it is never
        # "show" for a Jerr-Dan upfit -- enforced on save AND on output.
        sa.Column("price_mode", sa.String(12), nullable=False, server_default="range"),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("sale_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("range_low", sa.Numeric(12, 2), nullable=True),
        sa.Column("range_high", sa.Numeric(12, 2), nullable=True),
        # screen_email | email_only
        sa.Column("range_delivery", sa.String(16), nullable=False, server_default="screen_email"),
        # [{"label": ..., "value": ...}] a customer confirms before a range is given
        sa.Column("qualify_specs", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("featured", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("featured_rank", sa.Integer, nullable=False, server_default="0"),
        sa.Column("video_urls", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("ctt_ad_id", sa.String(20), nullable=True),
        sa.Column("created_by", sa.String(254), nullable=True),
        sa.Column("updated_by", sa.String(254), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
    )

    op.create_table(
        "unit_listing_part",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("listing_id", sa.Integer, sa.ForeignKey("unit_listing.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("part_number", sa.String(60), nullable=False, index=True),
        sa.Column("serial", sa.String(40), nullable=True),
        # chassis | body | trailer | equipment | unit
        sa.Column("role", sa.String(20), nullable=False, server_default="unit"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_ts(),
    )
    op.create_index("uq_unit_listing_part", "unit_listing_part",
                    ["listing_id", "part_number", sa.text("coalesce(serial, '')")], unique=True)

    op.create_table(
        "unit_listing_media",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("listing_id", sa.Integer, sa.ForeignKey("unit_listing.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        # photo | video | document
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("url", sa.String(400), nullable=False),
        sa.Column("thumb_url", sa.String(400), nullable=True),
        sa.Column("poster_url", sa.String(400), nullable=True),
        sa.Column("width", sa.Integer, nullable=True),
        sa.Column("height", sa.Integer, nullable=True),
        sa.Column("bytes", sa.BigInteger, nullable=True),
        sa.Column("original_name", sa.String(200), nullable=True),
        sa.Column("caption", sa.String(200), nullable=True),
        # spec_sheet | window_sticker | inspection | brochure | other (documents only)
        sa.Column("doc_type", sa.String(20), nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        *_ts(),
    )

    op.create_table(
        "unit_lead",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("listing_id", sa.Integer, sa.ForeignKey("unit_listing.id", ondelete="SET NULL"),
                  nullable=True, index=True),
        # price_range | quote | call | question | offer
        sa.Column("kind", sa.String(20), nullable=False, index=True),
        # new | contacted | quoted | won | lost | spam
        sa.Column("status", sa.String(16), nullable=False, server_default="new", index=True),
        sa.Column("listing_title", sa.String(200), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("company", sa.String(160), nullable=True),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("phone", sa.String(40), nullable=True),
        sa.Column("zip", sa.String(12), nullable=True),
        sa.Column("message", sa.Text, nullable=True),
        # the qualifier's answers: use, timeline, trade-in, financing, confirmed specs
        sa.Column("answers", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("specs_confirmed", sa.Boolean, nullable=True),
        sa.Column("range_low", sa.Numeric(12, 2), nullable=True),
        sa.Column("range_high", sa.Numeric(12, 2), nullable=True),
        sa.Column("range_shown", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("range_emailed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("offer_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("page_url", sa.String(500), nullable=True),
        sa.Column("source_ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
        sa.Column("handled_by", sa.String(254), nullable=True),
        sa.Column("contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        *_ts(),
    )

    op.create_table(
        "unit_listing_stat",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("listing_id", sa.Integer, sa.ForeignKey("unit_listing.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("views", sa.Integer, nullable=False, server_default="0"),
        *_ts(),
        sa.UniqueConstraint("listing_id", "day", name="uq_unit_listing_stat_day"),
    )

    op.create_table(
        "unit_price_guide",
        sa.Column("id", sa.Integer, primary_key=True),
        # wrecker | carrier | aerial | trailer | crane | cab-chassis | service | dump
        sa.Column("category", sa.String(24), nullable=False, index=True),
        # one builder step: "Wrecker", "Chassis", "Options" ...
        sa.Column("group_name", sa.String(60), nullable=False),
        sa.Column("group_order", sa.Integer, nullable=False, server_default="0"),
        # a step is pick-one unless multi (options you can stack)
        sa.Column("multi", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("required", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("detail", sa.String(300), nullable=True),
        # what this choice adds to the price, low and high
        sa.Column("price_low", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("price_high", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        # where the number came from, so a person can judge it
        sa.Column("basis", sa.String(300), nullable=True),
        *_ts(),
    )

    op.create_table(
        "erp_onhand",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("part_number", sa.String(60), nullable=False, index=True),
        sa.Column("prod_code", sa.String(12), nullable=True, index=True),
        sa.Column("warehouse", sa.Integer, nullable=True),
        sa.Column("onhand", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("available", sa.Numeric(12, 2), nullable=True),
        sa.Column("gl_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("days", sa.Integer, nullable=True),
        sa.Column("serial", sa.String(40), nullable=True, index=True),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("extra_desc", sa.String(200), nullable=True),
        sa.Column("p1", sa.Numeric(12, 2), nullable=True),
        sa.Column("p2", sa.Numeric(12, 2), nullable=True),
        sa.Column("p3", sa.Numeric(12, 2), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *_ts(),
    )


def downgrade() -> None:
    op.drop_table("erp_onhand")
    op.drop_table("unit_price_guide")
    op.drop_table("unit_listing_stat")
    op.drop_table("unit_lead")
    op.drop_table("unit_listing_media")
    op.drop_index("uq_unit_listing_part", table_name="unit_listing_part")
    op.drop_table("unit_listing_part")
    op.drop_table("unit_listing")
