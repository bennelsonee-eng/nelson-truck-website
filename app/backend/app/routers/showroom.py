"""Showroom router — customer-facing retail receipts.

A jobber/dealer in Retail Showroom Mode generates a receipt from their cart at
retail prices to hand the walk-in customer. The jobber collects the money at
their own register and marks the receipt paid/unpaid here. The wholesale order
to Titan is the normal (separate) checkout — these receipts are display/booking
artifacts only, so the line values come from the client; branding is snapshotted
server-side from the Customer record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_user, resolve_effective_customer_id
from app.models import Customer, ShowroomReceipt, User, UserRole

router = APIRouter(prefix="/api/showroom", tags=["showroom"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ReceiptLine(BaseModel):
    sku: str
    name: str
    qty: int = Field(ge=1)
    unit: float = Field(ge=0)
    total: float = Field(ge=0)


class ReceiptCreate(BaseModel):
    lines: list[ReceiptLine] = Field(min_length=1)
    subtotal: float = Field(ge=0)
    tax: float = Field(default=0, ge=0)
    total: float = Field(ge=0)


class ReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    receipt_number: str
    status: str
    display_name: str | None
    logo_url: str | None
    lines: list
    retail_subtotal: float
    retail_tax: float
    retail_total: float
    created_at: datetime


class StatusUpdate(BaseModel):
    status: Literal["paid", "unpaid"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _effective_customer(db: AsyncSession, user: User, request: Request) -> Customer:
    """The (possibly impersonated) jobber/dealer this request acts for."""
    cid = await resolve_effective_customer_id(db, user, request)
    if cid is None:
        raise HTTPException(status_code=400, detail="No customer context")
    cust = (await db.execute(select(Customer).where(Customer.id == cid))).scalar_one_or_none()
    if cust is None:
        raise HTTPException(status_code=400, detail="Customer not found")
    if cust.tier.value not in ("jobber", "dealer"):
        raise HTTPException(status_code=403, detail="Showroom receipts are only for jobber/dealer accounts")
    return cust


async def _owned_receipt(db: AsyncSession, user: User, request: Request, receipt_id: int) -> ShowroomReceipt:
    r = await db.get(ShowroomReceipt, receipt_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    cid = await resolve_effective_customer_id(db, user, request)
    if r.customer_id != cid and user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Not your receipt")
    return r


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/receipts", response_model=ReceiptOut, status_code=201)
async def create_receipt(
    body: ReceiptCreate,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ShowroomReceipt:
    cust = await _effective_customer(db, user, request)
    r = ShowroomReceipt(
        customer_id=cust.id,
        created_by_user_id=user.id,
        status="unpaid",
        display_name=cust.showroom_display_name or cust.name,
        logo_url=cust.showroom_logo_url,
        lines=[ln.model_dump() for ln in body.lines],
        retail_subtotal=round(body.subtotal, 2),
        retail_tax=round(body.tax, 2),
        retail_total=round(body.total, 2),
    )
    db.add(r)
    await db.flush()  # assign id
    r.receipt_number = f"SR-{r.id:05d}"
    await db.commit()
    await db.refresh(r)
    return r


@router.get("/receipts", response_model=list[ReceiptOut])
async def list_receipts(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[ShowroomReceipt]:
    cust = await _effective_customer(db, user, request)
    rows = (await db.execute(
        select(ShowroomReceipt)
        .where(ShowroomReceipt.customer_id == cust.id)
        .order_by(desc(ShowroomReceipt.created_at))
        .limit(200)
    )).scalars().all()
    return list(rows)


@router.get("/receipts/{receipt_id}", response_model=ReceiptOut)
async def get_receipt(
    receipt_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ShowroomReceipt:
    return await _owned_receipt(db, user, request, receipt_id)


@router.patch("/receipts/{receipt_id}", response_model=ReceiptOut)
async def update_receipt_status(
    receipt_id: int,
    body: StatusUpdate,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> ShowroomReceipt:
    r = await _owned_receipt(db, user, request, receipt_id)
    r.status = body.status
    await db.commit()
    await db.refresh(r)
    return r
