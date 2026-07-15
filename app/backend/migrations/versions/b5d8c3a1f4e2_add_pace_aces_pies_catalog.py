"""Add PACE ACES + PIES catalog tables.

Adds the schema needed to ingest Auto Care ACES 4.2 (vehicle fitment)
and PIES 7.2 (product information) feeds delivered by AAM.

Tables:
  - vcdb_*: Vehicle Configuration DB reference (Make, Model, BaseVehicle, SubModel,
            BedLength, BedType, BodyType, DriveType, EngineBase, FuelType,
            Aspiration, Region)
  - pcdb_*: Product Classification DB reference (PartType, Position)
  - pace_part: brand-scoped bridge between ACES PartNumber and our Product
  - pace_fitment: row-explosion table — one row per ACES <App> record
  - product_attribute / product_description / product_package / product_pricing:
            normalized PIES side tables (multiple rows per Product)

Also extends Brand with aaia_code + parent_aaia_id for PACE brand identification.

Revision ID: b5d8c3a1f4e2
Revises: a7f3b21e9c4d
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d8c3a1f4e2'
down_revision: Union[str, None] = 'a7f3b21e9c4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Extend Brand with PACE brand identifiers ----
    op.add_column('brand', sa.Column('aaia_code', sa.String(length=10), nullable=True))
    op.add_column('brand', sa.Column('parent_aaia_id', sa.String(length=10), nullable=True))
    op.create_index('ix_brand_aaia_code', 'brand', ['aaia_code'], unique=True)

    # ---- VCdb reference tables ----
    op.create_table(
        'vcdb_make',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'vcdb_model',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('make_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('vehicle_type', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['make_id'], ['vcdb_make.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vcdb_model_make_id', 'vcdb_model', ['make_id'])
    op.create_index('ix_vcdb_model_name', 'vcdb_model', ['name'])
    op.create_index('ix_vcdb_model_vehicle_type', 'vcdb_model', ['vehicle_type'])

    op.create_table(
        'vcdb_base_vehicle',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('year', sa.SmallInteger(), nullable=False),
        sa.Column('make_id', sa.Integer(), nullable=False),
        sa.Column('model_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['make_id'], ['vcdb_make.id']),
        sa.ForeignKeyConstraint(['model_id'], ['vcdb_model.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    # Partial unique index — only enforce uniqueness on real VCdb rows, not
    # the year=0 placeholder rows we create when ingesting brand feeds before
    # the canonical VCdb dump is loaded.
    op.create_index('uq_base_vehicle_ymm', 'vcdb_base_vehicle',
                    ['year', 'make_id', 'model_id'],
                    unique=True, postgresql_where=sa.text('year > 0'))
    op.create_index('ix_vcdb_base_vehicle_year', 'vcdb_base_vehicle', ['year'])
    op.create_index('ix_vcdb_base_vehicle_make_id', 'vcdb_base_vehicle', ['make_id'])
    op.create_index('ix_vcdb_base_vehicle_model_id', 'vcdb_base_vehicle', ['model_id'])
    op.create_index('ix_base_vehicle_ym', 'vcdb_base_vehicle', ['year', 'make_id'])

    # Generic id+name reference tables (one factory function would be nicer
    # but explicit is clearer for migration audit)
    for tbl, name_len in [
        ('vcdb_sub_model', 100),
        ('vcdb_bed_type', 100),
        ('vcdb_body_type', 100),
        ('vcdb_drive_type', 50),
        ('vcdb_fuel_type', 50),
        ('vcdb_aspiration', 50),
        ('vcdb_region', 50),
        ('pcdb_position', 50),
    ]:
        op.create_table(
            tbl,
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
            sa.Column('name', sa.String(length=name_len), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
    op.create_index('ix_vcdb_sub_model_name', 'vcdb_sub_model', ['name'])

    op.create_table(
        'vcdb_bed_length',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('length_inches', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('label', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'vcdb_engine_base',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('label', sa.String(length=120), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # ---- PCdb part type ----
    op.create_table(
        'pcdb_part_type',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('category_name', sa.String(length=200), nullable=True),
        sa.Column('sub_category_name', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pcdb_part_type_name', 'pcdb_part_type', ['name'])
    op.create_index('ix_pcdb_part_type_category_name', 'pcdb_part_type', ['category_name'])
    op.create_index('ix_pcdb_part_type_sub_category_name', 'pcdb_part_type', ['sub_category_name'])

    # ---- PACE part bridge ----
    op.create_table(
        'pace_part',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('brand_id', sa.Integer(), nullable=False),
        sa.Column('part_number', sa.String(length=64), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=True),
        sa.Column('primary_image_url', sa.String(length=1000), nullable=True),
        sa.Column('short_description', sa.String(length=500), nullable=True),
        sa.Column('part_terminology_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['brand_id'], ['brand.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['part_terminology_id'], ['pcdb_part_type.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('brand_id', 'part_number', name='uq_pace_part_brand_pn'),
    )
    op.create_index('ix_pace_part_brand_id', 'pace_part', ['brand_id'])
    op.create_index('ix_pace_part_part_number', 'pace_part', ['part_number'])
    op.create_index('ix_pace_part_product_id', 'pace_part', ['product_id'])
    op.create_index('ix_pace_part_part_terminology_id', 'pace_part', ['part_terminology_id'])

    # ---- PACE fitment ----
    op.create_table(
        'pace_fitment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pace_part_id', sa.Integer(), nullable=False),
        sa.Column('base_vehicle_id', sa.Integer(), nullable=False),
        sa.Column('part_type_id', sa.Integer(), nullable=False),
        sa.Column('sub_model_id', sa.Integer(), nullable=True),
        sa.Column('position_id', sa.Integer(), nullable=True),
        sa.Column('bed_length_id', sa.Integer(), nullable=True),
        sa.Column('bed_type_id', sa.Integer(), nullable=True),
        sa.Column('body_type_id', sa.Integer(), nullable=True),
        sa.Column('body_num_doors', sa.SmallInteger(), nullable=True),
        sa.Column('drive_type_id', sa.Integer(), nullable=True),
        sa.Column('engine_base_id', sa.Integer(), nullable=True),
        sa.Column('fuel_type_id', sa.Integer(), nullable=True),
        sa.Column('aspiration_id', sa.Integer(), nullable=True),
        sa.Column('region_id', sa.Integer(), nullable=True),
        sa.Column('extra_qualifiers', sa.JSON(), nullable=True),
        sa.Column('qty', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('mfr_label', sa.String(length=500), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['pace_part_id'], ['pace_part.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['base_vehicle_id'], ['vcdb_base_vehicle.id']),
        sa.ForeignKeyConstraint(['part_type_id'], ['pcdb_part_type.id']),
        sa.ForeignKeyConstraint(['sub_model_id'], ['vcdb_sub_model.id']),
        sa.ForeignKeyConstraint(['position_id'], ['pcdb_position.id']),
        sa.ForeignKeyConstraint(['bed_length_id'], ['vcdb_bed_length.id']),
        sa.ForeignKeyConstraint(['bed_type_id'], ['vcdb_bed_type.id']),
        sa.ForeignKeyConstraint(['body_type_id'], ['vcdb_body_type.id']),
        sa.ForeignKeyConstraint(['drive_type_id'], ['vcdb_drive_type.id']),
        sa.ForeignKeyConstraint(['engine_base_id'], ['vcdb_engine_base.id']),
        sa.ForeignKeyConstraint(['fuel_type_id'], ['vcdb_fuel_type.id']),
        sa.ForeignKeyConstraint(['aspiration_id'], ['vcdb_aspiration.id']),
        sa.ForeignKeyConstraint(['region_id'], ['vcdb_region.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_pace_fitment_pace_part_id', 'pace_fitment', ['pace_part_id'])
    op.create_index('ix_pace_fitment_base_vehicle_id', 'pace_fitment', ['base_vehicle_id'])
    op.create_index('ix_pace_fitment_part_type_id', 'pace_fitment', ['part_type_id'])
    op.create_index('ix_pace_fitment_sub_model_id', 'pace_fitment', ['sub_model_id'])
    op.create_index('ix_pace_fitment_position_id', 'pace_fitment', ['position_id'])
    # The killer YMM lookup index — "what parts of type X fit vehicle Y"
    op.create_index('ix_fitment_lookup', 'pace_fitment', ['base_vehicle_id', 'part_type_id'])
    # Reverse — "what vehicles does this part fit"
    op.create_index('ix_fitment_part_lookup', 'pace_fitment', ['pace_part_id'])

    # ---- PIES side tables ----
    op.create_table(
        'product_attribute',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('attribute_key', sa.String(length=120), nullable=False),
        sa.Column('attribute_value', sa.Text(), nullable=True),
        sa.Column('attribute_uom', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_product_attribute_product_id', 'product_attribute', ['product_id'])
    op.create_index('ix_product_attribute_attribute_key', 'product_attribute', ['attribute_key'])
    op.create_index('ix_product_attr_kv', 'product_attribute', ['attribute_key', 'attribute_value'])

    op.create_table(
        'product_description',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('description_code', sa.String(length=10), nullable=False),
        sa.Column('language_code', sa.String(length=10), nullable=False, server_default='EN'),
        sa.Column('sequence', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_product_description_product_id', 'product_description', ['product_id'])
    op.create_index('ix_product_description_description_code', 'product_description', ['description_code'])
    op.create_index('ix_product_desc_code', 'product_description', ['product_id', 'description_code'])

    op.create_table(
        'product_package',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('package_uom', sa.String(length=20), nullable=True),
        sa.Column('quantity_of_eaches', sa.Integer(), nullable=True),
        sa.Column('package_gtin', sa.String(length=20), nullable=True),
        sa.Column('container_type', sa.String(length=20), nullable=True),
        sa.Column('weight_lb', sa.Numeric(precision=10, scale=3), nullable=True),
        sa.Column('length_in', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('width_in', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('height_in', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_product_package_product_id', 'product_package', ['product_id'])
    op.create_index('ix_product_package_package_gtin', 'product_package', ['package_gtin'])

    op.create_table(
        'product_pricing',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('price_type', sa.String(length=10), nullable=False),
        sa.Column('price', sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column('currency_code', sa.String(length=5), nullable=False, server_default='USD'),
        sa.Column('effective_date', sa.Date(), nullable=True),
        sa.Column('price_sheet_number', sa.String(length=50), nullable=True),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_product_pricing_product_id', 'product_pricing', ['product_id'])
    op.create_index('ix_product_pricing_price_type', 'product_pricing', ['price_type'])
    op.create_index('ix_product_pricing_effective_date', 'product_pricing', ['effective_date'])
    op.create_index('ix_product_pricing_is_current', 'product_pricing', ['is_current'])
    op.create_index('ix_pricing_current_lookup', 'product_pricing', ['product_id', 'price_type', 'is_current'])


def downgrade() -> None:
    op.drop_table('product_pricing')
    op.drop_table('product_package')
    op.drop_table('product_description')
    op.drop_table('product_attribute')
    op.drop_table('pace_fitment')
    op.drop_table('pace_part')
    op.drop_table('pcdb_part_type')
    op.drop_table('pcdb_position')
    op.drop_table('vcdb_region')
    op.drop_table('vcdb_aspiration')
    op.drop_table('vcdb_fuel_type')
    op.drop_table('vcdb_engine_base')
    op.drop_table('vcdb_drive_type')
    op.drop_table('vcdb_body_type')
    op.drop_table('vcdb_bed_type')
    op.drop_table('vcdb_bed_length')
    op.drop_table('vcdb_sub_model')
    op.drop_table('vcdb_base_vehicle')
    op.drop_table('vcdb_model')
    op.drop_table('vcdb_make')
    op.drop_index('ix_brand_aaia_code', table_name='brand')
    op.drop_column('brand', 'parent_aaia_id')
    op.drop_column('brand', 'aaia_code')
