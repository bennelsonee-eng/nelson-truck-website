"""Auth router — signup, login, logout, /me, and the email-gated
customer-link-request flow that replaces the old self-link path.

Security note (2026-05-16): the pre-existing /signup auto-linked when a
customer_number was provided, and /link-customer let any logged-in user
claim any Customer row. Both paths were trust-only and let a guesser
pull jobber/dealer pricing. They've been replaced with:

  * /signup: customer_number, if provided, creates a CustomerLinkRequest
    (status=PENDING). The user account is created with customer_id=None.
  * /request-link (new): same flow for already-signed-up users.
  * /link-customer (deprecated): returns 410 Gone with a pointer.

Approval lives in the admin router (next slice).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import (
    COOKIE_JWT,
    COOKIE_SESSION,
    get_cf_identity,
    require_user,
    resolve_effective_customer_id,
    set_jwt_cookie,
)
from app.models import (
    Customer,
    CustomerLinkRequest,
    CustomerLinkRequestStatus,
    User,
    UserRole,
)
from app.services.auth_service import (
    authenticate,
    create_user,
    issue_jwt,
    verify_password,
)
from app.services.cf_access import CfIdentity
from app.services.cart_service import merge_anonymous_into_customer_cart
from app.services.email_service import (
    compose_customer_link_request_email,
    send_email,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/cf-identity")
async def cf_identity(cf: CfIdentity | None = Depends(get_cf_identity)):
    """Return the Cloudflare-Access-verified identity for this request, if any.

    Lets the SPA show the report-a-problem tool to invited preview testers who
    have no app account. Returns authenticated=False when there's no Access
    session (local dev, Tailscale, or the public site with no Access in front).
    """
    if cf is None:
        return {"authenticated": False, "email": None, "can_report": False}
    return {"authenticated": True, "email": cf.email, "can_report": True}


# ---- Schemas ----

class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    # If provided, kicks off a CustomerLinkRequest — does NOT auto-link.
    customer_number: str | None = Field(default=None, max_length=20)
    billing_zip: str | None = Field(default=None, max_length=20,
                                     description="Verification hint sales uses to confirm ownership")
    additional_info: str | None = Field(default=None, max_length=2000)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LinkRequestIn(BaseModel):
    customer_number: str = Field(min_length=1, max_length=20)
    billing_zip: str | None = Field(default=None, max_length=20)
    additional_info: str | None = Field(default=None, max_length=2000)


class LinkRequestOut(BaseModel):
    id: int
    requested_customer_number: str
    status: CustomerLinkRequestStatus
    requested_at: datetime
    email_sent_at: datetime | None
    email_error: str | None


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    display_name: str | None
    customer_id: int | None
    customer_number: str | None = None
    customer_name: str | None = None
    customer_tier: str | None = None
    front_counter_markup_pct: int | None = None
    # Retail Showroom Mode (white-label kiosk) config — account-wide.
    showroom_enabled: bool = False
    showroom_logo_url: str | None = None
    showroom_display_name: str | None = None
    is_verified: bool


class FrontCounterMarkupRequest(BaseModel):
    markup_pct: int = Field(ge=0, le=500, description="Markup percent over wholesale cost")


class ShowroomSettingsRequest(BaseModel):
    enabled: bool = Field(description="Whether Retail Showroom Mode is set up for this account")
    display_name: str | None = Field(None, max_length=200, description="Name shown on showroom receipts")
    markup_pct: int | None = Field(None, ge=0, le=500, description="Optional: also set the retail markup %")


class VerifyPasswordRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


# Default retail markup applied to a jobber/dealer until they set their own.
DEFAULT_B2B_MARKUP_PCT = 25


def _set_jwt_cookie(response: Response, user: User) -> None:
    token = issue_jwt(user_id=user.id, role=user.role.value, customer_id=user.customer_id)
    set_jwt_cookie(response, token)


async def _submit_link_request(
    db: AsyncSession,
    user: User,
    requested_customer_number: str,
    billing_zip: str | None,
    additional_info: str | None,
) -> CustomerLinkRequest:
    """Create a CustomerLinkRequest + dispatch the sales email. Best-effort
    on email; the DB row is persisted either way so sales can be poked
    manually if the SMTP step failed.
    """
    req = CustomerLinkRequest(
        user_id=user.id,
        requested_customer_number=requested_customer_number.strip(),
        billing_zip=(billing_zip.strip() if billing_zip else None),
        additional_info=additional_info,
        status=CustomerLinkRequestStatus.PENDING,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    composed = compose_customer_link_request_email(
        user_email=user.email,
        user_display_name=user.display_name,
        user_id=user.id,
        user_phone=getattr(user, "phone", None),
        requested_customer_number=req.requested_customer_number,
        billing_zip=req.billing_zip,
        additional_info=req.additional_info,
        link_request_id=req.id,
    )
    result = send_email(composed)
    if result.ok:
        req.email_sent_at = datetime.now(timezone.utc)
    else:
        req.email_error = (result.error or "unknown")[:1000]
    await db.commit()
    await db.refresh(req)
    return req


async def _user_out(
    db: AsyncSession,
    user: User,
    effective_customer_id: int | None = None,
) -> UserOut:
    """Serialize a user for the frontend.

    When `effective_customer_id` is provided (e.g. an admin using Shop-as-
    Customer), the customer_* fields reflect THAT customer so the storefront
    renders exactly how the impersonated customer would see it — pricing tier,
    B2B affordances, account identity. The user's own id/email/role are kept
    so the impersonation banner + admin controls still work.
    """
    cust_id = effective_customer_id if effective_customer_id is not None else user.customer_id
    out = UserOut(
        id=user.id,
        email=user.email,
        role=user.role.value,
        display_name=user.display_name,
        customer_id=cust_id,
        is_verified=user.is_verified,
    )
    if cust_id:
        cust = (await db.execute(select(Customer).where(Customer.id == cust_id))).scalar_one_or_none()
        if cust:
            out.customer_number = cust.customer_number
            out.customer_name = cust.name
            out.customer_tier = cust.tier.value
            # All B2B accounts default to a 25% retail markup until the customer
            # sets their own — overridden the moment retail_view_markup_percent is set.
            out.front_counter_markup_pct = (
                cust.retail_view_markup_percent
                if cust.retail_view_markup_percent is not None
                else (DEFAULT_B2B_MARKUP_PCT if cust.tier.value in ("jobber", "dealer") else None)
            )
            out.showroom_enabled = cust.showroom_enabled
            out.showroom_logo_url = cust.showroom_logo_url
            out.showroom_display_name = cust.showroom_display_name
    return out


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    # Reject if email already used
    existing = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    # The user account is ALWAYS created with customer_id=None. If a
    # customer_number was provided, we create a CustomerLinkRequest (PENDING)
    # and email sales — but we never auto-link, regardless of what was sent.
    # See top-of-file security note.
    user = await create_user(
        db,
        email=body.email,
        password=body.password,
        role=UserRole.CUSTOMER,
        customer_id=None,
        display_name=body.display_name,
    )

    if body.customer_number:
        await _submit_link_request(
            db,
            user=user,
            requested_customer_number=body.customer_number,
            billing_zip=body.billing_zip,
            additional_info=body.additional_info,
        )

    _set_jwt_cookie(response, user)
    return await _user_out(db, user)


@router.post("/request-link", response_model=LinkRequestOut, status_code=status.HTTP_202_ACCEPTED)
async def request_customer_link(
    body: LinkRequestIn,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Request a User → Customer link. Creates a CustomerLinkRequest row in
    PENDING state and emails sales@nelsontruck.com. Approval happens via the
    admin/CMS path; until then the user has no customer_id and no jobber
    pricing. This replaces the old /link-customer endpoint which auto-linked
    without verification.
    """
    if user.customer_id is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Account is already linked to customer #{user.customer_id}. "
                "Contact sales@nelsontruck.com to change accounts."
            ),
        )

    req = await _submit_link_request(
        db,
        user=user,
        requested_customer_number=body.customer_number,
        billing_zip=body.billing_zip,
        additional_info=body.additional_info,
    )
    return LinkRequestOut(
        id=req.id,
        requested_customer_number=req.requested_customer_number,
        status=req.status,
        requested_at=req.requested_at,
        email_sent_at=req.email_sent_at,
        email_error=req.email_error,
    )


@router.post("/link-customer", status_code=status.HTTP_410_GONE)
async def link_customer_deprecated():
    """DEPRECATED — the self-link endpoint was a trust-only path that let
    any user claim any customer_number and inherit that pricing tier. Replaced
    by /api/auth/request-link which routes through sales for verification.
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "POST /api/auth/link-customer has been retired for security. "
            "Use POST /api/auth/request-link to submit a verification request; "
            "sales@nelsontruck.com confirms ownership before the link is made."
        ),
    )


@router.get("/link-requests", response_model=list[LinkRequestOut])
async def list_my_link_requests(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns the requester's own link requests (any status), most recent first."""
    stmt = (
        select(CustomerLinkRequest)
        .where(CustomerLinkRequest.user_id == user.id)
        .order_by(desc(CustomerLinkRequest.requested_at))
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        LinkRequestOut(
            id=r.id,
            requested_customer_number=r.requested_customer_number,
            status=r.status,
            requested_at=r.requested_at,
            email_sent_at=r.email_sent_at,
            email_error=r.email_error,
        )
        for r in rows
    ]


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await authenticate(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Merge anonymous cart into the user's customer cart (only if linked)
    if user.customer_id is not None:
        anon_token = request.cookies.get(COOKIE_SESSION)
        if anon_token:
            await merge_anonymous_into_customer_cart(db, session_token=anon_token, customer_id=user.customer_id)
            await db.commit()

    _set_jwt_cookie(response, user)
    return await _user_out(db, user)


@router.post("/cf-login", response_model=UserOut)
async def cf_login(
    response: Response,
    cf: CfIdentity | None = Depends(get_cf_identity),
    db: AsyncSession = Depends(get_db),
):
    """Passwordless admin sign-in via Cloudflare Access (email OTP).

    When a request arrives carrying a Cloudflare-Access-verified identity whose
    email is in settings.cf_admin_emails, just-in-time provision (or reuse) an
    ADMIN app user for that email and issue the normal app JWT. The visitor
    never types an app password — Cloudflare's one-time passcode is the only
    credential. Double-gated: the Cloudflare Access policy must allow the email
    to reach us at all, and our allowlist decides who becomes admin.

    Returns 401 when there's no Access session (e.g. the Tailscale URL or local
    dev), and 403 when the verified email isn't on the admin allowlist.
    """
    if cf is None:
        raise HTTPException(status_code=401, detail="No Cloudflare Access session")

    settings = get_settings()
    allow = {e.strip().lower() for e in settings.cf_admin_emails.split(",") if e.strip()}
    email = cf.email.strip().lower()
    if email not in allow:
        raise HTTPException(status_code=403, detail="This email is not provisioned for admin access")

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        # No password is ever used for these accounts; set an unguessable one so
        # the password-login path can never authenticate as them.
        user = await create_user(
            db,
            email=email,
            password=secrets.token_urlsafe(32),
            role=UserRole.ADMIN,
            display_name=None,
        )
    else:
        changed = False
        if user.role != UserRole.ADMIN:
            user.role = UserRole.ADMIN
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if changed:
            await db.commit()
            await db.refresh(user)

    _set_jwt_cookie(response, user)
    return await _user_out(db, user)


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(COOKIE_JWT)
    return None


@router.get("/me", response_model=UserOut)
async def me(
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    # Honor admin Shop-as-Customer impersonation so the storefront renders
    # exactly how the impersonated customer would see it.
    effective_customer_id = await resolve_effective_customer_id(db, user, request)
    return await _user_out(db, user, effective_customer_id)


@router.post("/front-counter-markup", response_model=UserOut)
async def set_front_counter_markup(
    body: FrontCounterMarkupRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the jobber/dealer's default markup percent for Front Counter Mode.

    Markup is applied to the wholesale cost when the toggle is ON to compute
    the walk-in retail price (always floored by MAP).  Set to 0 to revert to
    the default behavior (just show MAP Retail).
    """
    if user.customer_id is None:
        raise HTTPException(status_code=400, detail="Account is not linked to a Nelson customer")

    cust = (await db.execute(
        select(Customer).where(Customer.id == user.customer_id)
    )).scalar_one_or_none()
    if cust is None:
        raise HTTPException(status_code=400, detail="Linked customer no longer exists")
    if cust.tier.value not in ("jobber", "dealer"):
        raise HTTPException(status_code=403, detail="Front Counter is only available for jobber and dealer accounts")

    cust.retail_view_markup_percent = body.markup_pct
    await db.commit()
    return await _user_out(db, user)


# ---------------------------------------------------------------------------
# Retail Showroom Mode (white-label kiosk)
# ---------------------------------------------------------------------------
_SHOWROOM_LOGO_DIR = (
    Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "showroom-logos"
)
_SHOWROOM_LOGO_DIR.mkdir(parents=True, exist_ok=True)
_LOGO_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


async def _require_showroom_customer(user: User, db: AsyncSession) -> Customer:
    """The jobber/dealer Customer behind the current user (showroom is B2B-only)."""
    if user.customer_id is None:
        raise HTTPException(status_code=400, detail="Account is not linked to a Nelson customer")
    cust = (await db.execute(
        select(Customer).where(Customer.id == user.customer_id)
    )).scalar_one_or_none()
    if cust is None:
        raise HTTPException(status_code=400, detail="Linked customer no longer exists")
    if cust.tier.value not in ("jobber", "dealer"):
        raise HTTPException(status_code=403, detail="Retail Showroom Mode is only available for jobber and dealer accounts")
    return cust


@router.post("/showroom-settings", response_model=UserOut)
async def set_showroom_settings(
    body: ShowroomSettingsRequest,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Configure Retail Showroom Mode for the jobber/dealer account (account-wide)."""
    cust = await _require_showroom_customer(user, db)
    cust.showroom_enabled = body.enabled
    cust.showroom_display_name = (body.display_name or "").strip() or None
    if body.markup_pct is not None:
        cust.retail_view_markup_percent = body.markup_pct
    await db.commit()
    return await _user_out(db, user)


@router.post("/showroom-logo", response_model=UserOut)
async def upload_showroom_logo(
    image: UploadFile = File(...),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload the account's white-label showroom logo; store its URL on the Customer."""
    cust = await _require_showroom_customer(user, db)
    ext = Path(image.filename or "").suffix.lower()
    if ext not in _LOGO_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported image type '{ext}'")
    contents = await image.read()
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 8 MB)")
    name = f"{uuid.uuid4().hex}{ext}"
    (_SHOWROOM_LOGO_DIR / name).write_bytes(contents)
    cust.showroom_logo_url = f"/static/uploads/showroom-logos/{name}"
    await db.commit()
    return await _user_out(db, user)


@router.post("/verify-password")
async def verify_current_password(
    body: VerifyPasswordRequest,
    user: User = Depends(require_user),
) -> dict[str, bool]:
    """Verify the CURRENT user's password — powers security gates like the
    password-protected exit from a locked showroom kiosk."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=403, detail="Incorrect password")
    return {"verified": True}
