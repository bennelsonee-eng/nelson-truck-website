"""Customer-signal endpoints — Lost Sale + Price Match.

Both endpoints write a single record and return it.  Admin-side moderation
lands in Phase 1.5.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import COOKIE_SESSION, get_cf_identity, get_current_user
from app.services import tester_activity
from app.services.cf_access import CfIdentity
from app.models import (
    BackInStockAlert,
    LostSale,
    LostSaleReason,
    PriceMatchRequest,
    PriceMatchStatus,
    Product,
    User,
)


router = APIRouter(prefix="/api/signals", tags=["signals"])


# ---- Schemas ----

class LostSaleIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    reason: LostSaleReason
    note: str | None = Field(default=None, max_length=2000)


class LostSaleOut(BaseModel):
    id: int
    sku: str
    reason: str
    note: str | None


class PriceMatchIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    competitor_name: str = Field(min_length=1, max_length=200)
    competitor_url: HttpUrl | None = None
    competitor_price_usd: str = Field(min_length=1, max_length=32)
    notes: str | None = Field(default=None, max_length=2000)


class PriceMatchOut(BaseModel):
    id: int
    sku: str
    competitor_name: str
    competitor_url: str | None
    competitor_price_usd: str
    status: str


# ---- Routes ----


@router.post("/lost-sale", response_model=LostSaleOut, status_code=status.HTTP_201_CREATED)
async def record_lost_sale(
    body: LostSaleIn,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    product = (await db.execute(select(Product).where(Product.sku == body.sku))).scalar_one_or_none()
    rec = LostSale(
        product_id=product.id if product else None,
        sku=body.sku,
        customer_id=user.customer_id if user else None,
        user_id=user.id if user else None,
        session_token=request.cookies.get(COOKIE_SESSION),
        reason=body.reason,
        note=body.note,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return LostSaleOut(
        id=rec.id, sku=rec.sku,
        reason=rec.reason.value if hasattr(rec.reason, "value") else str(rec.reason),
        note=rec.note,
    )


class BackInStockIn(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    email: EmailStr


class BackInStockOut(BaseModel):
    id: int
    sku: str
    email: str


@router.post("/back-in-stock", response_model=BackInStockOut, status_code=status.HTTP_201_CREATED)
async def subscribe_back_in_stock(
    body: BackInStockIn,
    request: Request,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Notify-when-back-in-stock subscription. Dedup'd at (sku, email).

    Owner ask 2026-05-17 (L7). Captures recoverable demand on OOS rows.
    Nightly notifier (`scripts/notify_back_in_stock.py`) emails + marks
    `notified_at` once `product_inventory.on_hand` flips positive.
    """
    product = (await db.execute(select(Product).where(Product.sku == body.sku))).scalar_one_or_none()
    email_lc = body.email.strip().lower()
    # Upsert keyed on (sku, email): re-subscribing during the OOS window is
    # a no-op; if a previous alert was already notified, we leave that row
    # alone (don't reopen it — the caller can just wait for the next 0→>0
    # transition once it ships again).
    stmt = pg_insert(BackInStockAlert).values(
        product_id=product.id if product else None,
        sku=body.sku,
        email=email_lc,
        user_id=user.id if user else None,
        session_token=request.cookies.get(COOKIE_SESSION),
    ).on_conflict_do_nothing(index_elements=["sku", "email"]).returning(
        BackInStockAlert.id, BackInStockAlert.sku, BackInStockAlert.email
    )
    result = (await db.execute(stmt)).first()
    if result is None:
        # Already subscribed — return the existing row so the UI can
        # confirm "you're already on the list" without a 409.
        existing = (await db.execute(
            select(BackInStockAlert.id, BackInStockAlert.sku, BackInStockAlert.email)
            .where(BackInStockAlert.sku == body.sku, BackInStockAlert.email == email_lc)
        )).first()
        if existing is None:
            raise HTTPException(status_code=500, detail="Subscription upsert failed")
        await db.commit()
        return BackInStockOut(id=existing.id, sku=existing.sku, email=existing.email)
    await db.commit()
    return BackInStockOut(id=result.id, sku=result.sku, email=result.email)


@router.post("/price-match", response_model=PriceMatchOut, status_code=status.HTTP_201_CREATED)
async def record_price_match(
    body: PriceMatchIn,
    user: User | None = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    product = (await db.execute(select(Product).where(Product.sku == body.sku))).scalar_one_or_none()
    rec = PriceMatchRequest(
        product_id=product.id if product else None,
        sku=body.sku,
        customer_id=user.customer_id if user else None,
        user_id=user.id if user else None,
        competitor_name=body.competitor_name,
        competitor_url=str(body.competitor_url) if body.competitor_url else None,
        competitor_price_usd=body.competitor_price_usd,
        notes=body.notes,
        status=PriceMatchStatus.PENDING,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return PriceMatchOut(
        id=rec.id, sku=rec.sku,
        competitor_name=rec.competitor_name,
        competitor_url=rec.competitor_url,
        competitor_price_usd=rec.competitor_price_usd,
        status=rec.status.value if hasattr(rec.status, "value") else str(rec.status),
    )


# ---- Cloudflare Access page-view beacon ----

class PageViewIn(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


@router.post("/pageview", status_code=status.HTTP_202_ACCEPTED)
async def record_pageview(
    body: PageViewIn,
    request: Request,
    cf: CfIdentity | None = Depends(get_cf_identity),
):
    """SPA page-view beacon for Cloudflare-Access preview testers.

    Client-side route changes never hit the backend (Vite serves the SPA shell),
    so the frontend posts here on each navigation. No-op when there's no Access
    identity — we only track invited testers, not anonymous public traffic.
    """
    if cf is None:
        return {"logged": False}
    await tester_activity.log(
        email=cf.email,
        event="pageview",
        path=body.path,
        method="GET",
        ip=request.headers.get("cf-connecting-ip", "")
        or (request.client.host if request.client else ""),
        user_agent=request.headers.get("user-agent", ""),
    )
    return {"logged": True}
