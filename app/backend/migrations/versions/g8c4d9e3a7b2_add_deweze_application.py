"""Add deweze_application table — YMM applicability per DewEze kit

Owner ask 2026-05-14: "I would also like to bring in their Year, Make,
Model sorting for a side navigation drill down like what we do for van
interiors and snow plows."

Each DewEze kit in our catalog (293 rows in product, brand_id=91)
applies to a specific (make, engine_or_model, year_range) combination.
The catalog scrape from dur-a-lift.com /hydraulics/find-kit/ has this
data inline — this table normalizes it so the front-end sidebar can do
a clean drill-down (Make → Year → Engine → Pump).

One product can have multiple applications (some kits fit a year range
that splits across engine sub-options).

Revision ID: g8c4d9e3a7b2
Revises: f7a3b8e2c9d1
Create Date: 2026-05-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g8c4d9e3a7b2"
down_revision: Union[str, None] = "f7a3b8e2c9d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deweze_application",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        # Vehicle dimensions
        sa.Column("make", sa.String(length=50), nullable=False),
        sa.Column("engine_or_model", sa.String(length=200), nullable=True),
        sa.Column("engine_size", sa.String(length=20), nullable=True),
        sa.Column("engine_fuel", sa.String(length=20), nullable=True),
        sa.Column("year_start", sa.Integer(), nullable=True),
        sa.Column("year_end", sa.Integer(), nullable=True),
        # Pump dimensions
        sa.Column("pump_type_short", sa.String(length=10), nullable=True),
        sa.Column("pump_type_name", sa.String(length=200), nullable=True),
        sa.Column("pump_port", sa.String(length=30), nullable=True),
        sa.Column("belt", sa.String(length=80), nullable=True),
        sa.Column("clutch_configuration", sa.String(length=80), nullable=True),
        sa.Column("obsolete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_deweze_app_product", "deweze_application", ["product_id"])
    op.create_index("ix_deweze_app_make", "deweze_application", ["make"])
    op.create_index("ix_deweze_app_make_year", "deweze_application",
                    ["make", "year_start", "year_end"])
    op.create_index("ix_deweze_app_pump", "deweze_application", ["pump_type_short"])


def downgrade() -> None:
    op.drop_index("ix_deweze_app_pump", table_name="deweze_application")
    op.drop_index("ix_deweze_app_make_year", table_name="deweze_application")
    op.drop_index("ix_deweze_app_make", table_name="deweze_application")
    op.drop_index("ix_deweze_app_product", table_name="deweze_application")
    op.drop_table("deweze_application")
