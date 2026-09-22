"""Quote requests, contact form, newsletter sign-ups (launch audit 2026-09-22).

Public:
  POST /api/inquiries   — quote / contact / project request. Stored first, then
                          emailed to settings.inquiry_alert_email in the background,
                          so a mail outage never loses a customer's request.
  POST /api/newsletter  — newsletter sign-up (idempotent per address).
Admin:
  GET   /api/admin/inquiries        — newest first, filter by status/kind.
  PATCH /api/admin/inquiries/{id}   — mark handled / add notes.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models import User
from app.models.inquiry import INQUIRY_KINDS, INQUIRY_STATUSES, Inquiry, NewsletterSubscriber
from app.services.email_service import AuthSmtpSender, ComposedEmail, send_email

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inquiries"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_KIND_LABEL = {"quote": "Quote request", "contact": "Contact form", "project": "Custom project"}


def _clean(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    # Drop NULs and lone surrogates (they break Postgres text / SMTP), trim, cap.
    value = value.replace("\x00", "")
    value = value.encode("utf-8", "replace").decode("utf-8").strip()
    return value[:limit] or None


class InquiryIn(BaseModel):
    kind: str = Field("contact")
    name: str = Field(..., max_length=120)
    company: str | None = Field(None, max_length=160)
    email: str | None = Field(None, max_length=254)
    phone: str | None = Field(None, max_length=40)
    branch: str | None = Field(None, max_length=20)
    product_sku: str | None = Field(None, max_length=80)
    product_name: str | None = Field(None, max_length=300)
    quantity: int | None = Field(None, ge=1, le=100000)
    message: str | None = Field(None, max_length=5000)
    page_url: str | None = Field(None, max_length=500)
    # Honeypot: a hidden field real people never fill. Bots that fill every
    # input get a normal-looking 200 and nothing is stored or sent.
    website: str | None = None


class NewsletterIn(BaseModel):
    email: str = Field(..., max_length=254)
    source: str | None = Field(None, max_length=60)
    website: str | None = None  # honeypot


def _send_inquiry_alert(inq: dict[str, Any]) -> None:
    """Email the alert address about a new inquiry. Background task; swallows
    every error -- the inquiry is already committed.

    Uses the issue-alert SMTP channel when one is configured (the pre-launch
    site runs EMAIL_PROVIDER=maildev, which delivers nothing), else the site's
    own provider. Gets a plain dict, never the request's DB session.
    """
    inquiry_id = inq.get("id")
    try:
        settings = get_settings()
        to = (settings.inquiry_alert_email or "").strip()
        if not to:
            logger.info("inquiry %s: no alert address configured", inquiry_id)
            return
        from types import SimpleNamespace
        inq = SimpleNamespace(**inq)
        label = _KIND_LABEL.get(inq.kind, "Inquiry")
        lines = [
            f"{label} #{inq.id} from the {settings.app_name} website.",
            "",
            f"  Name:     {inq.name}",
        ]
        if inq.company:
            lines.append(f"  Company:  {inq.company}")
        if inq.email:
            lines.append(f"  Email:    {inq.email}")
        if inq.phone:
            lines.append(f"  Phone:    {inq.phone}")
        if inq.branch:
            lines.append(f"  Branch:   {inq.branch}")
        if inq.product_sku:
            prod = f"{inq.product_sku} — {inq.product_name}" if inq.product_name else inq.product_sku
            lines.append(f"  Product:  {prod}")
        if inq.quantity:
            lines.append(f"  Quantity: {inq.quantity}")
        if inq.page_url:
            lines.append(f"  Page:     {inq.page_url}")
        lines += ["", "Message:", inq.message or "(none)", "",
                  "Reply to the customer directly; replying to this email goes to them.",
                  "All inquiries are listed on the site under Admin > Inquiries."]
        subject_bits = [label]
        if inq.product_sku:
            subject_bits.append(inq.product_sku)
        subject_bits.append(inq.company or inq.name)
        email = ComposedEmail(
            to_email=to,
            to_name=None,
            subject=f"[{settings.app_name}] " + " · ".join(subject_bits)[:150],
            text_body="\n".join(lines),
            reply_to=inq.email if inq.email and _EMAIL_RE.match(inq.email) else None,
        )
        if settings.error_report_smtp_host and settings.error_report_smtp_user:
            sender = AuthSmtpSender(
                host=settings.error_report_smtp_host,
                port=settings.error_report_smtp_port,
                user=settings.error_report_smtp_user,
                password=settings.error_report_smtp_password,
                from_addr=settings.error_report_smtp_from or settings.error_report_smtp_user,
            )
            result = sender.send(email)
        else:
            result = send_email(email)
        if result.ok:
            logger.info("inquiry %s: alert emailed to %s", inquiry_id, to)
        else:
            logger.warning("inquiry %s: alert email failed: %s", inquiry_id, result.error)
    except Exception:
        logger.exception("inquiry %s: alert email raised", inquiry_id)


@router.post("/api/inquiries")
async def create_inquiry(
    body: InquiryIn,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user),
) -> dict[str, Any]:
    if body.website:  # honeypot tripped
        return {"ok": True, "id": None}
    kind = body.kind if body.kind in INQUIRY_KINDS else "contact"
    name = _clean(body.name, 120)
    email = _clean(body.email, 254)
    phone = _clean(body.phone, 40)
    if not name:
        raise HTTPException(status_code=422, detail="Please tell us your name.")
    if not email and not phone:
        raise HTTPException(status_code=422, detail="Please give us an email address or a phone number so we can reply.")
    if email and not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="That email address doesn't look right.")
    ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else None)

    # Light flood guard: at most 10 inquiries per address per hour.
    if ip:
        recent = (await db.execute(
            select(func.count()).select_from(Inquiry)
            .where(Inquiry.source_ip == ip, Inquiry.created_at > func.now() - func.make_interval(0, 0, 0, 0, 1))
        )).scalar_one()
        if recent >= 10:
            raise HTTPException(status_code=429, detail="Too many requests from this network. Please call us instead.")

    inq = Inquiry(
        kind=kind,
        status="new",
        name=name,
        company=_clean(body.company, 160),
        email=email,
        phone=phone,
        branch=_clean(body.branch, 20),
        product_sku=_clean(body.product_sku, 80),
        product_name=_clean(body.product_name, 300),
        quantity=body.quantity,
        message=_clean(body.message, 5000),
        page_url=_clean(body.page_url, 500),
        user_id=user.id if user else None,
        source_ip=(ip or "")[:64] or None,
        user_agent=_clean(request.headers.get("user-agent"), 300),
    )
    db.add(inq)
    await db.commit()
    await db.refresh(inq)
    background.add_task(_send_inquiry_alert, _inquiry_out(inq))
    return {"ok": True, "id": inq.id}


@router.post("/api/newsletter")
async def newsletter_signup(body: NewsletterIn, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if body.website:
        return {"ok": True}
    email = (_clean(body.email, 254) or "").lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="That email address doesn't look right.")
    stmt = pg_insert(NewsletterSubscriber).values(email=email, source=_clean(body.source, 60) or "footer")
    stmt = stmt.on_conflict_do_update(
        index_elements=[NewsletterSubscriber.email],
        set_={"unsubscribed_at": None, "updated_at": func.now()},
    )
    await db.execute(stmt)
    await db.commit()
    return {"ok": True}


def _inquiry_out(i: Inquiry) -> dict[str, Any]:
    return {
        "id": i.id, "created_at": i.created_at.isoformat() if i.created_at else None,
        "kind": i.kind, "status": i.status, "name": i.name, "company": i.company,
        "email": i.email, "phone": i.phone, "branch": i.branch,
        "product_sku": i.product_sku, "product_name": i.product_name, "quantity": i.quantity,
        "message": i.message, "page_url": i.page_url,
        "handled_at": i.handled_at.isoformat() if i.handled_at else None,
        "handled_by": i.handled_by, "notes": i.notes,
    }


@router.get("/api/admin/inquiries")
async def list_inquiries(
    status: str | None = Query(None),
    kind: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict[str, Any]:
    q = select(Inquiry).order_by(Inquiry.created_at.desc(), Inquiry.id.desc()).limit(limit)
    if status in INQUIRY_STATUSES:
        q = q.where(Inquiry.status == status)
    if kind in INQUIRY_KINDS:
        q = q.where(Inquiry.kind == kind)
    rows = (await db.execute(q)).scalars().all()
    open_count = (await db.execute(
        select(func.count()).select_from(Inquiry).where(Inquiry.status == "new")
    )).scalar_one()
    subscribers = (await db.execute(
        select(func.count()).select_from(NewsletterSubscriber).where(NewsletterSubscriber.unsubscribed_at.is_(None))
    )).scalar_one()
    return {"items": [_inquiry_out(i) for i in rows], "open": open_count, "newsletter_subscribers": subscribers}


class InquiryPatch(BaseModel):
    status: str | None = None
    notes: str | None = Field(None, max_length=5000)


@router.patch("/api/admin/inquiries/{inquiry_id}")
async def update_inquiry(
    inquiry_id: int,
    body: InquiryPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    inq = await db.get(Inquiry, inquiry_id)
    if inq is None:
        raise HTTPException(status_code=404, detail="Inquiry not found")
    if body.status is not None:
        if body.status not in INQUIRY_STATUSES:
            raise HTTPException(status_code=422, detail="status must be 'new' or 'handled'")
        inq.status = body.status
        if body.status == "handled":
            inq.handled_at = datetime.now(timezone.utc)
            inq.handled_by = admin.email
        else:
            inq.handled_at = None
            inq.handled_by = None
    if body.notes is not None:
        inq.notes = _clean(body.notes, 5000)
    await db.commit()
    await db.refresh(inq)
    return _inquiry_out(inq)
