"""per-channel catalog visibility (retail/wholesale/dealer/municipality).

Adds four per-customer-channel EFFECTIVE visibility columns so the admin catalog
tree can hide a product independently per channel (owner ask 2026-07-22). The
baseline stays the single `base_hidden` (a discontinued/never-stocked product is
hidden from everyone — importers keep writing only base_hidden); per-channel
divergence comes solely from admin overrides. Legacy `is_hidden` is KEPT
(= "hidden from every channel") and the resolver recomputes it = AND of the four
channel columns, so admin/internal "fully hidden" checks stay correct.

  - product.is_hidden_{retail,wholesale,dealer,municipality} (effective),
    backfilled from is_hidden so the site is byte-identical on day one. No new
    baseline columns — the resolver overlays each channel on shared base_hidden.
  - catalog_override rows with field='hidden' fan out to four rows
    (hidden_retail / hidden_wholesale / hidden_dealer / hidden_municipality),
    preserving hidden-from-everyone; the unique key is (scope_key, field) so the
    four coexist per scope. The bare 'hidden' rows are then removed.

Revision ID: k9n3p7q1r5s8
Revises: j8m2n6p0q4r7
Create Date: 2026-07-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k9n3p7q1r5s8"
down_revision: Union[str, None] = "j8m2n6p0q4r7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Canonical customer channels (mirrors search.ALL_CHANNELS; "wholesale" = jobber).
_CHANNELS = ("retail", "wholesale", "dealer", "municipality")

# The full column list copied when fanning override rows out/in (id + timestamps
# are handled separately: id auto-generates, created_at/updated_at are carried).
_OV_COLS = (
    "created_at, updated_at, scope_type, scope_key, brand_id, category_id, "
    "product_id, attr_key, attr_value, note, applied_at, updated_by, updated_by_id"
)


def upgrade() -> None:
    # 1. Per-channel EFFECTIVE visibility columns, backfilled from the single
    #    is_hidden so nothing changes until the tree is used. The baseline stays
    #    the shared base_hidden (no per-channel baseline columns).
    for ch in _CHANNELS:
        op.add_column(
            "product",
            sa.Column(f"is_hidden_{ch}", sa.Boolean(), server_default=sa.false(), nullable=False),
        )
    op.execute(
        "UPDATE product SET " + ", ".join(f"is_hidden_{ch} = is_hidden" for ch in _CHANNELS)
    )
    # Index the effective columns (storefront WHERE clauses filter these).
    for ch in _CHANNELS:
        op.create_index(f"ix_product_is_hidden_{ch}", "product", [f"is_hidden_{ch}"])

    # 2. Fan out existing field='hidden' overrides into one row per channel,
    #    preserving hidden-from-everyone, then drop the originals.
    for ch in _CHANNELS:
        op.execute(
            f"INSERT INTO catalog_override ({_OV_COLS}, field, value) "
            f"SELECT {_OV_COLS}, 'hidden_{ch}', value "
            "FROM catalog_override WHERE field = 'hidden'"
        )
    op.execute("DELETE FROM catalog_override WHERE field = 'hidden'")


def downgrade() -> None:
    # Collapse the four channel overrides back to a single field='hidden' row per
    # scope (the fan-out wrote identical values per channel, so any one is
    # representative; DISTINCT ON dedupes to one per scope_key).
    op.execute(
        f"INSERT INTO catalog_override ({_OV_COLS}, field, value) "
        f"SELECT DISTINCT ON (scope_key) {_OV_COLS}, 'hidden', value "
        "FROM catalog_override WHERE field LIKE 'hidden\\_%' ESCAPE '\\' "
        "ORDER BY scope_key, field"
    )
    op.execute("DELETE FROM catalog_override WHERE field LIKE 'hidden\\_%' ESCAPE '\\'")

    for ch in _CHANNELS:
        op.drop_index(f"ix_product_is_hidden_{ch}", table_name="product")
        op.drop_column("product", f"is_hidden_{ch}")
