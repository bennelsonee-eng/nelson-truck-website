"""Common FastAPI dependencies — auth, cart-owner resolution, impersonation."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.models import Customer, User, UserRole
from app.services.auth_service import decode_jwt, new_session_token
from app.services.cf_access import CfIdentity, verify_request


# Cookie names
COOKIE_JWT = "titan_jwt"
COOKIE_SESSION = "titan_session"


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Returns the User from the JWT cookie, or None if anonymous/invalid."""
    token = request.cookies.get(COOKIE_JWT)
    if not token:
        return None
    payload = decode_jwt(token)
    if not payload:
        return None
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError, TypeError):
        return None
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


async def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    return user


async def require_admin(user: User = Depends(require_user)) -> User:
    """Admin gate. ADMIN role required."""
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


async def require_editor(user: User = Depends(require_user)) -> User:
    """Content gate. ADMIN or EDITOR — for content/scheduling surfaces like the
    banner CMS, deals, and rebates."""
    if user.role not in (UserRole.ADMIN, UserRole.EDITOR):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or editor role required")
    return user


# ---------------------------------------------------------------------------
# Cloudflare Access (preview-site tester identity)
# ---------------------------------------------------------------------------

async def get_cf_identity(request: Request) -> CfIdentity | None:
    """The Cloudflare-Access-verified identity for this request, or None.

    The HTTP middleware populates request.state.cf_identity on every request; we
    fall back to verifying the header directly when state isn't set (e.g. tests).
    """
    ident = getattr(request.state, "cf_identity", None)
    if ident is not None:
        return ident
    return await verify_request(request)


@dataclass(frozen=True)
class ReporterIdentity:
    """Who is filing an error report: an app admin/editor, or a CF-verified tester."""

    user_id: int | None   # app User.id, or None for a Cloudflare-only tester
    username: str          # name/email stamped onto the report
    is_admin: bool


async def require_reporter(
    user: User | None = Depends(get_current_user),
    cf: CfIdentity | None = Depends(get_cf_identity),
) -> ReporterIdentity:
    """Anyone can file an issue report.

    Attribution comes off whatever identity the request carries, best first:
      * a logged-in app user (any role) → their EMAIL + user FK,
      * else a Cloudflare-Access-verified email (invited tester / OTP visitor),
      * else anonymous (user_id=NULL, username="anonymous").
    Admins/editors are flagged is_admin so they can attach a video to any report
    (others only to one they just filed). The admin Reports queue + resolve stay
    gated separately by require_admin.
    """
    if user is not None:
        return ReporterIdentity(
            user_id=user.id,
            username=user.email or user.display_name or f"user#{user.id}",
            is_admin=user.role in (UserRole.ADMIN, UserRole.EDITOR),
        )
    if cf is not None:
        return ReporterIdentity(user_id=None, username=cf.email, is_admin=False)
    return ReporterIdentity(user_id=None, username="anonymous", is_admin=False)


def get_impersonating_customer_id(request: Request) -> int | None:
    """Returns the customer_id the current JWT is impersonating, or None.

    Per A4.28 (Shop as Customer), an admin can carry an `imp_cust` JWT claim
    that marks them as acting on behalf of a specific customer.
    """
    token = request.cookies.get(COOKIE_JWT)
    if not token:
        return None
    payload = decode_jwt(token)
    if not payload:
        return None
    imp = payload.get("imp_cust")
    if imp is None:
        return None
    try:
        return int(imp)
    except (TypeError, ValueError):
        return None


async def resolve_effective_customer_id(
    db: AsyncSession,
    user: User,
    request: Request,
) -> int | None:
    """Returns the customer_id this request should act on:

      * If the JWT carries an `imp_cust` claim AND the user is an ADMIN
        AND that Customer exists and is active → the impersonated id.
      * Otherwise → user.customer_id (which may itself be None for a
        customer-role user who hasn't been linked yet).

    Non-admin users with a stale imp_cust claim in their cookie are
    ignored — the claim only takes effect for admins.
    """
    imp = get_impersonating_customer_id(request)
    if imp is None or user.role != UserRole.ADMIN:
        return user.customer_id
    cust = (
        await db.execute(
            select(Customer).where(
                Customer.id == imp, Customer.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    return cust.id if cust else user.customer_id


def is_acting_as_impersonator(user: User, request: Request) -> bool:
    """True when an admin is currently impersonating someone — i.e. the JWT
    carries `imp_cust` and the user is the right role to make it effective.
    Used by the orders router to populate Order.acting_as_* audit columns.
    """
    return user.role == UserRole.ADMIN and get_impersonating_customer_id(request) is not None


def set_jwt_cookie(response: Response, token: str) -> None:
    """Issue the JWT HttpOnly cookie. Shared by auth + admin routers."""
    settings = get_settings()
    response.set_cookie(
        key=COOKIE_JWT,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=int(timedelta(hours=settings.jwt_expire_hours).total_seconds()),
        secure=False,  # True in production
    )


def get_or_issue_session_token(request: Request, response: Response) -> str:
    """Return existing anon-session token or issue a new one (set HttpOnly cookie)."""
    existing = request.cookies.get(COOKIE_SESSION)
    if existing:
        return existing
    token = new_session_token()
    response.set_cookie(
        key=COOKIE_SESSION,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 365,  # 1 year
        secure=False,  # set True in production behind HTTPS
    )
    return token
