"""Account endpoints — self-service data for the logged-in shopper.

Phase 1 surface: a single lightweight endpoint returning the customer's
recently-purchased SKUs. The frontend uses it to render a "Reordered"
chip on grid + list rows so B2B repeat shoppers can spot what they've
bought before at a glance. Owner ask 2026-05-17 (L8).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, resolve_effective_customer_id
from app.models import Order, OrderLine, User


router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/recent-skus")
async def recent_skus(
    request: Request,
    days: int = Query(365, ge=1, le=3650, description="Look-back window in days"),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the SKUs this customer has ordered within the look-back window.

    Honors admin "Shop as Customer" impersonation. Anonymous shoppers and
    users with no linked customer get an empty list — the frontend uses
    that as the "no Reordered chips" signal.

    Excludes synthetic line types (FREIGHT, DISCOUNT, HANDLING) by filtering
    on product_id IS NOT NULL — those flags don't represent SKUs the
    customer would re-order.
    """
    if user is None:
        return {"customer_id": None, "skus": []}
    cust_id = await resolve_effective_customer_id(db, user, request)
    if cust_id is None:
        return {"customer_id": None, "skus": []}

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(distinct(OrderLine.sku))
        .join(Order, Order.id == OrderLine.order_id)
        .where(
            Order.customer_id == cust_id,
            Order.created_at >= cutoff,
            OrderLine.product_id.is_not(None),
        )
    )).scalars().all()
    return {"customer_id": cust_id, "skus": rows}
