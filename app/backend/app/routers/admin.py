"""Admin router — CMS-side staff operations.

Phase 1 endpoints:
  GET  /api/admin/customers/search?q=    — typeahead for the Shop-as-Customer
                                             impersonation dropdown (A4.28).
                                             Searches the local `customer`
                                             table by customer_number / name /
                                             city. (MySQL `tte_cus190` sync is
                                             a separate workstream — until it
                                             lands the local table may be
                                             sparse.)
  POST /api/admin/impersonate/{customer_id} — re-issues the staff user's JWT
                                             with `imp_cust=customer_id`.
                                             Effective customer context for
                                             downstream requests = this id.
  POST /api/admin/impersonate/exit       — re-issues JWT without imp_cust.
  GET  /api/admin/impersonate/current    — convenience read of the active
                                             impersonation, if any.

Authorization: every endpoint requires ADMIN role.

Follow-ups (separate slices):
  * MySQL sync from `tte_cus190` → local `customer` table
  * Admin approval queue for CustomerLinkRequests
  * Cart/Order/RMA routers need to honor the imp_cust JWT claim — currently
    they read user.customer_id directly. The infrastructure (JWT claim,
    get_impersonating_customer_id helper, audit columns on Order) is in place;
    wiring the readers is the next step.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import (
    get_impersonating_customer_id,
    require_admin,
    set_jwt_cookie,
)
from app.models import (
    AddressType,
    Customer,
    CustomerAddress,
    CustomerLinkRequest,
    CustomerLinkRequestStatus,
    User,
)
from app.services.auth_service import issue_jwt
from app.services.email_service import (
    compose_customer_link_decision_email,
    send_email,
)


router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---- Schemas ----


class CustomerSearchHit(BaseModel):
    id: int
    customer_number: str
    name: str
    tier: str
    default_ship_to: str | None  # one-line formatted shipping address


class ImpersonationState(BaseModel):
    impersonating: bool
    customer_id: int | None
    customer_number: str | None
    customer_name: str | None
    tier: str | None


def _format_ship_to(addr: CustomerAddress | None) -> str | None:
    if addr is None:
        return None
    parts = [
        addr.company or addr.name or "",
        addr.addr1 or "",
        f"{addr.city}, {addr.state} {addr.zip}",
    ]
    return " · ".join(p for p in parts if p)


def _pick_default_ship_to(customer: Customer) -> CustomerAddress | None:
    """Customer's primary shipping address, falling back to any shipping
    address, then any address at all.
    """
    ship_addrs = [a for a in customer.addresses if a.address_type == AddressType.SHIPPING]
    primary_ship = next((a for a in ship_addrs if a.is_primary), None)
    if primary_ship:
        return primary_ship
    if ship_addrs:
        return ship_addrs[0]
    return customer.addresses[0] if customer.addresses else None


# ---- Endpoints ----


@router.get("/customers/search", response_model=list[CustomerSearchHit])
async def search_customers(
    q: str = "",
    limit: int = 50,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[CustomerSearchHit]:
    """Typeahead source for the impersonation dropdown (A4.28).

    Matches q against customer_number (prefix), name (substring), and any
    address's city (substring). Returns up to `limit` rows with one-line
    default ship-to so admin can pick the right customer at a glance.
    """
    q = (q or "").strip()
    if limit < 1 or limit > 200:
        limit = 50

    stmt = (
        select(Customer)
        .options(selectinload(Customer.addresses))
        .where(Customer.is_active.is_(True))
        .order_by(Customer.customer_number)
        .limit(limit)
    )

    if q:
        pattern = f"%{q}%"
        # PG ILIKE for case-insensitive substring matching
        stmt = stmt.where(
            or_(
                Customer.customer_number.ilike(f"{q}%"),
                Customer.name.ilike(pattern),
                # address.city match — correlated subquery via EXISTS
                Customer.id.in_(
                    select(CustomerAddress.customer_id).where(
                        CustomerAddress.city.ilike(pattern)
                    )
                ),
            )
        )

    customers = (await db.execute(stmt)).scalars().unique().all()

    return [
        CustomerSearchHit(
            id=c.id,
            customer_number=c.customer_number,
            name=c.name,
            tier=c.tier.value,
            default_ship_to=_format_ship_to(_pick_default_ship_to(c)),
        )
        for c in customers
    ]


# NOTE: literal-path routes must come BEFORE the parameterized one. FastAPI
# matches in registration order, so /impersonate/exit was being eaten by
# /impersonate/{customer_id} (int-parse on "exit" → 422 validation error,
# which the frontend toast rendered as "[object Object]"). The regex on the
# parameterized route is belt-and-suspenders: it now only matches digits.


@router.post("/impersonate/exit", response_model=ImpersonationState)
async def exit_impersonation(
    response: Response,
    user: User = Depends(require_admin),
) -> ImpersonationState:
    """Re-issue the admin's JWT without the imp_cust claim."""
    token = issue_jwt(
        user_id=user.id,
        role=user.role.value,
        customer_id=user.customer_id,
        impersonating_customer_id=None,
    )
    set_jwt_cookie(response, token)
    return ImpersonationState(
        impersonating=False,
        customer_id=None,
        customer_number=None,
        customer_name=None,
        tier=None,
    )


@router.post(
    "/impersonate/{customer_id:int}",
    response_model=ImpersonationState,
)
async def start_impersonation(
    customer_id: int,
    response: Response,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ImpersonationState:
    """Re-issue the admin's JWT with `imp_cust=customer_id`. From this point
    until /impersonate/exit, the admin acts on behalf of that customer.

    The `:int` path converter forces this to only match numeric customer_id
    values — defense in depth so a literal path like /impersonate/exit can
    never get misrouted here.
    """
    customer = (
        await db.execute(select(Customer).where(Customer.id == customer_id))
    ).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not customer.is_active:
        raise HTTPException(status_code=409, detail="Customer is inactive")

    token = issue_jwt(
        user_id=user.id,
        role=user.role.value,
        customer_id=user.customer_id,
        impersonating_customer_id=customer.id,
    )
    set_jwt_cookie(response, token)

    return ImpersonationState(
        impersonating=True,
        customer_id=customer.id,
        customer_number=customer.customer_number,
        customer_name=customer.name,
        tier=customer.tier.value,
    )


# ---- Customer link-request approval queue ----


class LinkRequestAdminOut(BaseModel):
    id: int
    user_id: int
    user_email: str
    user_display_name: str | None
    requested_customer_number: str
    billing_zip: str | None
    additional_info: str | None
    status: CustomerLinkRequestStatus
    requested_at: datetime
    email_sent_at: datetime | None
    email_error: str | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    review_notes: str | None
    # Resolved info to help the reviewer eyeball the match
    matched_customer_id: int | None
    matched_customer_name: str | None
    matched_customer_billing_zip: str | None


class ReviewDecisionIn(BaseModel):
    review_notes: str | None = Field(default=None, max_length=2000)


async def _serialize_link_request(
    db: AsyncSession, req: CustomerLinkRequest
) -> LinkRequestAdminOut:
    # Load the requesting user
    requester = (
        await db.execute(select(User).where(User.id == req.user_id))
    ).scalar_one_or_none()
    # Look up the customer-on-file matching the requested number
    matched_cust = (
        await db.execute(
            select(Customer)
            .where(Customer.customer_number == req.requested_customer_number)
            .options(selectinload(Customer.addresses))
        )
    ).scalar_one_or_none()
    matched_billing_zip = None
    if matched_cust is not None:
        billing_addr = next(
            (a for a in matched_cust.addresses if a.address_type == AddressType.BILLING and a.is_primary),
            None,
        ) or next(
            (a for a in matched_cust.addresses if a.address_type == AddressType.BILLING),
            None,
        )
        matched_billing_zip = billing_addr.zip if billing_addr else None
    return LinkRequestAdminOut(
        id=req.id,
        user_id=req.user_id,
        user_email=requester.email if requester else "(deleted user)",
        user_display_name=(requester.display_name if requester else None),
        requested_customer_number=req.requested_customer_number,
        billing_zip=req.billing_zip,
        additional_info=req.additional_info,
        status=req.status,
        requested_at=req.requested_at,
        email_sent_at=req.email_sent_at,
        email_error=req.email_error,
        reviewed_by_user_id=req.reviewed_by_user_id,
        reviewed_at=req.reviewed_at,
        review_notes=req.review_notes,
        matched_customer_id=(matched_cust.id if matched_cust else None),
        matched_customer_name=(matched_cust.name if matched_cust else None),
        matched_customer_billing_zip=matched_billing_zip,
    )


@router.get(
    "/customer-link-requests", response_model=list[LinkRequestAdminOut]
)
async def list_link_requests(
    status_filter: CustomerLinkRequestStatus | None = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[LinkRequestAdminOut]:
    """List customer-link requests, newest first. Pass ?status_filter=pending
    (or approved/rejected) to filter."""
    stmt = select(CustomerLinkRequest).order_by(desc(CustomerLinkRequest.requested_at))
    if status_filter is not None:
        stmt = stmt.where(CustomerLinkRequest.status == status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    return [await _serialize_link_request(db, r) for r in rows]


@router.get(
    "/customer-link-requests/{request_id}", response_model=LinkRequestAdminOut
)
async def get_link_request(
    request_id: int,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LinkRequestAdminOut:
    req = (
        await db.execute(
            select(CustomerLinkRequest).where(CustomerLinkRequest.id == request_id)
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="Link request not found")
    return await _serialize_link_request(db, req)


@router.post(
    "/customer-link-requests/{request_id}/approve",
    response_model=LinkRequestAdminOut,
)
async def approve_link_request(
    request_id: int,
    body: ReviewDecisionIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LinkRequestAdminOut:
    """Approve the request: sets User.customer_id to the matching Customer row
    + marks the request APPROVED. Fails if status is not PENDING or no
    Customer matches `requested_customer_number` (sync MySQL → Customer first).
    """
    req = (
        await db.execute(
            select(CustomerLinkRequest).where(CustomerLinkRequest.id == request_id)
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="Link request not found")
    if req.status != CustomerLinkRequestStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot approve: status is {req.status.value}",
        )

    matched_cust = (
        await db.execute(
            select(Customer).where(
                Customer.customer_number == req.requested_customer_number
            )
        )
    ).scalar_one_or_none()
    if matched_cust is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"No Customer with number {req.requested_customer_number} "
                "in our local table. Sync tte_cus190 first, then retry."
            ),
        )

    requester = (
        await db.execute(select(User).where(User.id == req.user_id))
    ).scalar_one_or_none()
    if requester is None:
        raise HTTPException(status_code=409, detail="Requesting user no longer exists")

    requester.customer_id = matched_cust.id
    req.status = CustomerLinkRequestStatus.APPROVED
    req.reviewed_by_user_id = admin.id
    req.reviewed_at = datetime.now(timezone.utc)
    req.review_notes = body.review_notes
    await db.commit()
    await db.refresh(req)

    # Notify the requester (best-effort)
    composed = compose_customer_link_decision_email(
        user_email=requester.email,
        user_display_name=requester.display_name,
        requested_customer_number=req.requested_customer_number,
        link_request_id=req.id,
        approved=True,
        review_notes=req.review_notes,
    )
    send_email(composed)

    return await _serialize_link_request(db, req)


@router.post(
    "/customer-link-requests/{request_id}/reject",
    response_model=LinkRequestAdminOut,
)
async def reject_link_request(
    request_id: int,
    body: ReviewDecisionIn,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LinkRequestAdminOut:
    req = (
        await db.execute(
            select(CustomerLinkRequest).where(CustomerLinkRequest.id == request_id)
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status_code=404, detail="Link request not found")
    if req.status != CustomerLinkRequestStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot reject: status is {req.status.value}",
        )

    req.status = CustomerLinkRequestStatus.REJECTED
    req.reviewed_by_user_id = admin.id
    req.reviewed_at = datetime.now(timezone.utc)
    req.review_notes = body.review_notes
    await db.commit()
    await db.refresh(req)

    requester = (
        await db.execute(select(User).where(User.id == req.user_id))
    ).scalar_one_or_none()
    if requester is not None:
        composed = compose_customer_link_decision_email(
            user_email=requester.email,
            user_display_name=requester.display_name,
            requested_customer_number=req.requested_customer_number,
            link_request_id=req.id,
            approved=False,
            review_notes=req.review_notes,
        )
        send_email(composed)

    return await _serialize_link_request(db, req)


# ---- Impersonation state read (must stay below all decorated handlers above) ----


@router.get("/impersonate/current", response_model=ImpersonationState)
async def current_impersonation(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ImpersonationState:
    """Read the current impersonation state from the admin's JWT cookie."""
    imp_cust_id = get_impersonating_customer_id(request)
    if imp_cust_id is None:
        return ImpersonationState(
            impersonating=False,
            customer_id=None,
            customer_number=None,
            customer_name=None,
            tier=None,
        )
    customer = (
        await db.execute(select(Customer).where(Customer.id == imp_cust_id))
    ).scalar_one_or_none()
    if customer is None:
        return ImpersonationState(
            impersonating=False,
            customer_id=None,
            customer_number=None,
            customer_name=None,
            tier=None,
        )
    return ImpersonationState(
        impersonating=True,
        customer_id=customer.id,
        customer_number=customer.customer_number,
        customer_name=customer.name,
        tier=customer.tier.value,
    )


# ---------------------------------------------------------------------------
# Audit log viewer — every privileged action, filterable per user.
# ---------------------------------------------------------------------------
class AuditLogRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    user_id: int | None
    user_email: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    summary: str | None
    ip_address: str | None


class AuditActor(BaseModel):
    user_id: int | None
    user_email: str | None
    count: int


class AuditLogPage(BaseModel):
    rows: list[AuditLogRow]
    total: int
    actors: list[AuditActor]


@router.get("/audit-log", response_model=AuditLogPage)
async def get_audit_log(
    user_id: int | None = Query(None, description="Filter to one actor"),
    action: str | None = Query(None, description="Filter by HTTP verb / action"),
    q: str | None = Query(None, description="Search summary / email / entity"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AuditLogPage:
    """Paginated admin audit trail. Newest first; filter per user / action / text."""
    from app.models.audit import AuditLog

    stmt = select(AuditLog)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            AuditLog.summary.ilike(like),
            AuditLog.user_email.ilike(like),
            AuditLog.entity_type.ilike(like),
            AuditLog.entity_id.ilike(like),
        ))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(
        stmt.order_by(desc(AuditLog.created_at), desc(AuditLog.id)).limit(limit).offset(offset)
    )).scalars().all()

    # Distinct actors (for the per-user filter dropdown), busiest first.
    actor_rows = (await db.execute(
        select(AuditLog.user_id, AuditLog.user_email, func.count().label("n"))
        .group_by(AuditLog.user_id, AuditLog.user_email)
        .order_by(desc(func.count()))
    )).all()
    actors = [AuditActor(user_id=r.user_id, user_email=r.user_email, count=int(r.n)) for r in actor_rows]

    return AuditLogPage(rows=list(rows), total=total, actors=actors)


# ---------------------------------------------------------------------------
# Special Rules — admin-visible registry of non-obvious storefront rules.
# ---------------------------------------------------------------------------
class SpecialRule(BaseModel):
    id: str
    category: str
    title: str
    summary: str
    detail: str
    scope: str
    source: str
    since: str | None = None
    status: str


@router.get("/special-rules", response_model=list[SpecialRule])
async def get_special_rules(_: User = Depends(require_admin)) -> list[dict]:
    """The active special display/business rules, derived from live config."""
    from app.services.special_rules import list_special_rules
    return list_special_rules()
