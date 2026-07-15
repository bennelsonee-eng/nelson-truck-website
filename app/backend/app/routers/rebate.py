"""Rebate endpoints.

Public:
    GET /api/rebates?audience=retail|wholesale
        Active, in-window rebate programs for an audience (matches it or 'both').

Admin (ADMIN or EDITOR):
    GET/POST /api/admin/rebates
    PUT/DELETE /api/admin/rebates/{rid}
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_editor
from app.models import RebateAudience, RebateClaimMethod, RebateProgram, RebateType, User
from app.models.base import utc_now

router = APIRouter(tags=["rebates"])


class RebateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    brand: str | None
    amount_label: str
    rebate_type: RebateType
    terms: str | None
    threshold_label: str | None
    fine_print: str | None
    link_url: str | None
    audience: RebateAudience
    claim_method: RebateClaimMethod
    is_active: bool
    starts_at: datetime | None
    ends_at: datetime | None
    sort_order: int


class RebateIn(BaseModel):
    name: str
    brand: str | None = None
    amount_label: str
    rebate_type: RebateType = RebateType.FIXED
    terms: str | None = None
    threshold_label: str | None = None
    fine_print: str | None = None
    link_url: str | None = None
    audience: RebateAudience = RebateAudience.BOTH
    claim_method: RebateClaimMethod = RebateClaimMethod.MAIL_IN
    is_active: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    sort_order: int = 1000


class RebateUpdate(BaseModel):
    name: str | None = None
    brand: str | None = None
    amount_label: str | None = None
    rebate_type: RebateType | None = None
    terms: str | None = None
    threshold_label: str | None = None
    fine_print: str | None = None
    link_url: str | None = None
    audience: RebateAudience | None = None
    claim_method: RebateClaimMethod | None = None
    is_active: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    sort_order: int | None = None


def _aud_match(audience: str) -> list[RebateAudience]:
    try:
        aud = RebateAudience(audience)
    except ValueError:
        aud = RebateAudience.RETAIL
    return [RebateAudience.BOTH] if aud is RebateAudience.BOTH else [RebateAudience.BOTH, aud]


@router.get("/api/rebates", response_model=list[RebateOut])
async def list_active_rebates(
    audience: str = "retail",
    db: AsyncSession = Depends(get_db),
) -> list[RebateProgram]:
    now = utc_now()
    stmt = (
        select(RebateProgram)
        .where(
            RebateProgram.is_active.is_(True),
            RebateProgram.audience.in_(_aud_match(audience)),
            or_(RebateProgram.starts_at.is_(None), RebateProgram.starts_at <= now),
            or_(RebateProgram.ends_at.is_(None), RebateProgram.ends_at >= now),
        )
        .order_by(RebateProgram.sort_order, RebateProgram.id)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get("/api/admin/rebates", response_model=list[RebateOut])
async def admin_list_rebates(db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    stmt = select(RebateProgram).order_by(RebateProgram.sort_order, RebateProgram.id)
    return list((await db.execute(stmt)).scalars().all())


@router.post("/api/admin/rebates", response_model=RebateOut, status_code=201)
async def admin_create_rebate(payload: RebateIn, db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    prog = RebateProgram(**payload.model_dump())
    db.add(prog)
    await db.commit()
    await db.refresh(prog)
    return prog


@router.put("/api/admin/rebates/{rid}", response_model=RebateOut)
async def admin_update_rebate(rid: int, payload: RebateUpdate, db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    prog = await db.get(RebateProgram, rid)
    if prog is None:
        raise HTTPException(404, "Rebate not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(prog, k, v)
    await db.commit()
    await db.refresh(prog)
    return prog


@router.delete("/api/admin/rebates/{rid}")
async def admin_delete_rebate(rid: int, db: AsyncSession = Depends(get_db), _: User = Depends(require_editor)):
    prog = await db.get(RebateProgram, rid)
    if prog is None:
        raise HTTPException(404, "Rebate not found")
    await db.delete(prog)
    await db.commit()
    return {"deleted": rid}
