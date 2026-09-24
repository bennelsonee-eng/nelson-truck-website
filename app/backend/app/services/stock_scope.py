"""Which warehouses count as stock for the Nelson storefront.

Nelson's site sells what Portland (warehouse code 1) and Kent (code 2) have on
the shelf. Spokane (SPO) and Boise stock belongs to titantruck.com: whichever
site holds the stock gets the customer, so the two sites never compete for the
same unit (Ben, 2026-09-22).

Spokane-only products still appear on nelsontruck.com, priced and orderable —
they just don't claim to be in stock, which also keeps the "pick it up today in
Portland or Kent" promise on the cards honest.

Everything a shopper sees — search's in_stock flag, catalog filters, the
product page's location table, cart quantity caps — goes through
``nelson_stock_only()``. Admin and fulfillment still see every warehouse.
"""
from __future__ import annotations

from sqlalchemy import select

# warehouse.code values, not ids: 1 = Portland (Nelson), 2 = Kent (Nelson).
NELSON_WAREHOUSE_CODES = (1, 2)


def nelson_stock_only():
    """SQLAlchemy condition limiting ProductInventory rows to Nelson's branches.

    Products flagged ``show_all_branch_stock`` are exempt: truck bodies and
    other equipment the two companies sell together count every branch,
    Spokane included (Ben, 2026-09-24).
    """
    from app.models import Product, ProductInventory, Warehouse

    at_nelson = ProductInventory.warehouse_id.in_(
        select(Warehouse.id).where(Warehouse.code.in_(NELSON_WAREHOUSE_CODES))
    )
    every_branch = ProductInventory.product_id.in_(
        select(Product.id).where(Product.show_all_branch_stock.is_(True))
    )
    return at_nelson | every_branch
