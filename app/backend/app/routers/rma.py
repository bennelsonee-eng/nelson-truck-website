"""RMA router — jobber-facing endpoints for SOW addendum A4.31.

Endpoints:
  POST /api/rma/orders/{order_id}/request — submit a new RMA (multipart with
                                            photos + JSON payload form field)
  GET  /api/rma                            — list the logged-in user's RMAs
  GET  /api/rma/{rma_id}                   — detail
  POST /api/rma/{rma_id}/cancel            — jobber cancels their own request

Phase 1 photo handling (per addendum):
  * Accepts JPEG + PNG only. HEIC support is a follow-up (requires pillow-heif).
  * Total payload capped at 20 MB across all photos.
  * Photos are NOT persisted server-side — bytes go out as email attachments
    only. Filename / content_type / byte_size land in the rma_request.photo_metadata
    JSON column for audit.

Authorization: require_user + the order's customer_id must match the user's
customer_id. Multi-location (parent_customer_id chain) access is a follow-up.
"""

from __future__ import annotations

import io
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import require_user, resolve_effective_customer_id
from app.models import (
    Customer,
    Order,
    RmaLine,
    RmaReason,
    RmaRequest,
    RmaStatus,
    User,
)
from app.services.email_service import (
    EmailAttachment,
    compose_rma_request_email,
    rma_for_email,
    send_email,
)


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rma", tags=["rma"])


# 20 MB total photo cap per RMA submission (addendum A4.31)
PHOTO_TOTAL_BYTE_CAP = 20 * 1024 * 1024
# Types accepted directly into the email attachment
PHOTO_DIRECT_TYPES = {"image/jpeg", "image/png"}
# Types we accept by transcoding to JPEG server-side (addendum A4.31:
# "JPEG / PNG accepted; HEIC auto-converted server-side")
PHOTO_TRANSCODE_TYPES = {"image/heic", "image/heif"}
PHOTO_ALLOWED_TYPES = PHOTO_DIRECT_TYPES | PHOTO_TRANSCODE_TYPES


def _transcode_heic_to_jpeg(content: bytes, filename: str) -> tuple[bytes, str, str]:
    """Convert HEIC/HEIF bytes to JPEG. Returns (new_bytes, new_filename, content_type).

    Raises HTTPException on decode failure so the API surfaces a useful 400.
    """
    try:
        # pillow-heif registers HEIF as a Pillow plugin on import.
        import pillow_heif  # type: ignore
        from PIL import Image

        pillow_heif.register_heif_opener()
        img = Image.open(io.BytesIO(content))
        # HEIF can have an alpha channel; JPEG can't — flatten to RGB.
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88, optimize=True)
        new_bytes = buf.getvalue()
        # Rename extension to .jpg so the email attachment is recognized
        base = os.path.splitext(filename or "photo")[0] or "photo"
        return new_bytes, f"{base}.jpg", "image/jpeg"
    except Exception as e:
        log.exception("HEIC transcode failed for %s", filename)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Could not decode HEIC photo {filename}: {e}. "
                "Try saving as JPEG on the device and re-uploading."
            ),
        )


# ---- Schemas ----


class RmaLineIn(BaseModel):
    order_line_id: int
    qty_to_return: int = Field(ge=1)
    reason: RmaReason
    line_notes: str | None = Field(default=None, max_length=500)


class RmaSubmitIn(BaseModel):
    lines: list[RmaLineIn] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=2000)


class RmaLineOut(BaseModel):
    id: int
    order_line_id: int
    sku: str
    description: str
    qty_ordered: int
    qty_to_return: int
    reason: RmaReason
    line_notes: str | None


class RmaPhotoOut(BaseModel):
    filename: str
    content_type: str
    byte_size: int


class RmaRequestOut(BaseModel):
    id: int
    order_id: int
    web_order_number: str
    status: RmaStatus
    requested_at: datetime
    notes: str | None
    photos: list[RmaPhotoOut]
    total_photo_bytes: int
    lines: list[RmaLineOut]
    email_sent_at: datetime | None
    email_error: str | None


# ---- Helpers ----


async def _load_order_for_effective_customer(
    db: AsyncSession, order_id: int, effective_customer_id: int | None
) -> Order:
    """Fetch order with lines + verify the resolved customer owns it.

    `effective_customer_id` honors admin Shop-as-Customer impersonation —
    an admin acting as customer X can file RMAs on X's orders.
    """
    if effective_customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not linked to a customer account",
        )
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.lines))
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.customer_id != effective_customer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This order does not belong to your account",
        )
    return order


def _serialize_rma(rma: RmaRequest, order: Order) -> RmaRequestOut:
    order_lines_by_id = {ol.id: ol for ol in order.lines}
    photo_payload = rma.photo_metadata or []
    return RmaRequestOut(
        id=rma.id,
        order_id=rma.order_id,
        web_order_number=order.web_order_number,
        status=rma.status,
        requested_at=rma.requested_at,
        notes=rma.notes,
        photos=[
            RmaPhotoOut(
                filename=p.get("filename", "?"),
                content_type=p.get("content_type", "?"),
                byte_size=int(p.get("byte_size", 0)),
            )
            for p in photo_payload
        ],
        total_photo_bytes=rma.total_photo_bytes or 0,
        lines=[
            RmaLineOut(
                id=rl.id,
                order_line_id=rl.order_line_id,
                sku=(order_lines_by_id[rl.order_line_id].sku
                     if rl.order_line_id in order_lines_by_id else "?"),
                description=(order_lines_by_id[rl.order_line_id].description
                             if rl.order_line_id in order_lines_by_id else "") or "",
                qty_ordered=(order_lines_by_id[rl.order_line_id].quantity
                             if rl.order_line_id in order_lines_by_id else 0),
                qty_to_return=rl.qty_to_return,
                reason=rl.reason,
                line_notes=rl.line_notes,
            )
            for rl in rma.lines
        ],
        email_sent_at=rma.email_sent_at,
        email_error=rma.email_error,
    )


# ---- Endpoints ----


@router.post(
    "/orders/{order_id}/request",
    status_code=status.HTTP_201_CREATED,
    response_model=RmaRequestOut,
)
async def submit_rma(
    order_id: int,
    request: Request,
    payload: str = Form(...),
    photos: list[UploadFile] | None = File(default=None),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> RmaRequestOut:
    """File an RMA against a past order. Multipart form: `payload` is a JSON
    string matching RmaSubmitIn; `photos` is zero or more image files.

    Honors admin Shop-as-Customer impersonation (A4.28) — the order's
    customer must match the effective customer id from the JWT.
    """
    # Parse + validate payload
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {e}")
    try:
        submit_in = RmaSubmitIn.model_validate(parsed)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload shape: {e}")

    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    order = await _load_order_for_effective_customer(db, order_id, effective_customer_id)

    # Validate that each requested line is on the order and qty is within bounds
    order_lines_by_id = {ol.id: ol for ol in order.lines}
    for line_in in submit_in.lines:
        ol = order_lines_by_id.get(line_in.order_line_id)
        if ol is None:
            raise HTTPException(
                status_code=400,
                detail=f"Line {line_in.order_line_id} is not on order {order_id}",
            )
        if line_in.qty_to_return > ol.quantity:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"qty_to_return {line_in.qty_to_return} exceeds ordered "
                    f"qty {ol.quantity} for line {ol.id} ({ol.sku})"
                ),
            )

    # Read + validate photos (in-memory; we don't persist bytes in Phase 1)
    attachments: list[EmailAttachment] = []
    photo_metadata: list[dict[str, Any]] = []
    total_bytes = 0
    for upload in photos or []:
        ctype = (upload.content_type or "").lower()
        if ctype not in PHOTO_ALLOWED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Photo {upload.filename} has type {ctype or '?'}; "
                    "accepted: JPEG, PNG, HEIC/HEIF"
                ),
            )
        content = await upload.read()
        filename = upload.filename or "photo"

        # HEIC/HEIF → transcode to JPEG before attaching to the email
        if ctype in PHOTO_TRANSCODE_TYPES:
            content, filename, ctype = _transcode_heic_to_jpeg(content, filename)

        total_bytes += len(content)
        if total_bytes > PHOTO_TOTAL_BYTE_CAP:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Total photo upload {total_bytes} bytes exceeds the "
                    f"{PHOTO_TOTAL_BYTE_CAP // (1024 * 1024)} MB cap"
                ),
            )
        attachments.append(
            EmailAttachment(
                filename=filename,
                content_type=ctype,
                content=content,
            )
        )
        photo_metadata.append({
            "filename": filename,
            "content_type": ctype,
            "byte_size": len(content),
        })

    # Persist the RMA + lines
    rma = RmaRequest(
        order_id=order.id,
        requested_by_user_id=user.id,
        status=RmaStatus.SUBMITTED,
        notes=submit_in.notes,
        photo_metadata=photo_metadata or None,
        total_photo_bytes=total_bytes or None,
    )
    db.add(rma)
    await db.flush()

    for line_in in submit_in.lines:
        db.add(
            RmaLine(
                rma_request_id=rma.id,
                order_line_id=line_in.order_line_id,
                qty_to_return=line_in.qty_to_return,
                reason=line_in.reason,
                line_notes=line_in.line_notes,
            )
        )

    await db.commit()

    # Re-load with the lines relationship populated for serialization + email
    rma = (
        await db.execute(
            select(RmaRequest)
            .where(RmaRequest.id == rma.id)
            .options(selectinload(RmaRequest.lines))
        )
    ).scalar_one()

    customer = (
        await db.execute(select(Customer).where(Customer.id == order.customer_id))
    ).scalar_one_or_none()

    # Compose and dispatch the email. Email failures do NOT roll back the
    # RMA — the jobber sees their request either way, and Titan staff can
    # retry from the CMS if email_error is set.
    email_view = rma_for_email(
        rma=rma,
        order=order,
        customer=customer,
        user=user,
        location_label=None,
    )
    composed = compose_rma_request_email(email_view, attachments=tuple(attachments))
    result = send_email(composed)
    if result.ok:
        rma.email_sent_at = datetime.now(timezone.utc)
    else:
        rma.email_error = (result.error or "unknown")[:1000]
    await db.commit()
    await db.refresh(rma)

    return _serialize_rma(rma, order)


@router.get("", response_model=list[RmaRequestOut])
async def list_my_rmas(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> list[RmaRequestOut]:
    """List all RMAs the resolved customer has submitted. Honors Shop-as-Customer."""
    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    if effective_customer_id is None:
        return []
    stmt = (
        select(RmaRequest)
        .join(Order, Order.id == RmaRequest.order_id)
        .where(Order.customer_id == effective_customer_id)
        .options(
            selectinload(RmaRequest.lines),
            selectinload(RmaRequest.order).selectinload(Order.lines),
        )
        .order_by(desc(RmaRequest.requested_at))
    )
    rmas = (await db.execute(stmt)).scalars().all()
    return [_serialize_rma(r, r.order) for r in rmas]


@router.get("/{rma_id}", response_model=RmaRequestOut)
async def get_rma(
    rma_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> RmaRequestOut:
    stmt = (
        select(RmaRequest)
        .where(RmaRequest.id == rma_id)
        .options(
            selectinload(RmaRequest.lines),
            selectinload(RmaRequest.order).selectinload(Order.lines),
        )
    )
    rma = (await db.execute(stmt)).scalar_one_or_none()
    if rma is None:
        raise HTTPException(status_code=404, detail="RMA not found")
    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    if rma.order.customer_id != effective_customer_id:
        raise HTTPException(status_code=403, detail="Not your RMA")
    return _serialize_rma(rma, rma.order)


@router.post("/{rma_id}/cancel", response_model=RmaRequestOut)
async def cancel_rma(
    rma_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
) -> RmaRequestOut:
    """Jobber cancels a submitted RMA before Titan staff has acted on it.

    Only allowed when status is SUBMITTED. Later Phase 2 statuses are
    staff-managed and out of the jobber's reach.
    """
    stmt = (
        select(RmaRequest)
        .where(RmaRequest.id == rma_id)
        .options(
            selectinload(RmaRequest.lines),
            selectinload(RmaRequest.order).selectinload(Order.lines),
        )
    )
    rma = (await db.execute(stmt)).scalar_one_or_none()
    if rma is None:
        raise HTTPException(status_code=404, detail="RMA not found")
    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    if rma.order.customer_id != effective_customer_id:
        raise HTTPException(status_code=403, detail="Not your RMA")
    if rma.status != RmaStatus.SUBMITTED:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel: status is {rma.status.value}",
        )
    rma.status = RmaStatus.CANCELLED
    await db.commit()
    await db.refresh(rma)
    return _serialize_rma(rma, rma.order)
