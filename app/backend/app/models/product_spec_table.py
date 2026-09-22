"""ProductSpecTable — a manufacturer's specification table, kept as a table.

`product_attribute` is one key and one value, which is right for "Deck: 11-gauge
tread plate" but cannot hold what a truck-body maker actually publishes: a model
matrix. Knapheide's steel service body page is 58 rows of model number x body
length x height x width x compartment depth x weight, grouped under cab-to-axle
headings ("56\" CA, Dual Wheel - ..."). Flattening that into key/value pairs
throws away the one thing a buyer needs from it -- which model fits their
chassis -- so it is stored as the table it is.

`headers` is a list of column labels. `rows` is a list of row objects, either
    {"type": "row",   "cells": ["580", "680", ...]}
    {"type": "group", "label": "40\" CA, Single Wheel - 1999 or later Ford ..."}
so a group heading can span the full width when rendered.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ProductSpecTable(Base):
    __tablename__ = "product_spec_table"
    __table_args__ = (
        Index("ix_product_spec_table_product_sort", "product_id", "sort_order"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    title: Mapped[str | None] = mapped_column(String(200))
    headers: Mapped[list] = mapped_column(JSONB, nullable=False)
    rows: Mapped[list] = mapped_column(JSONB, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), index=True)
