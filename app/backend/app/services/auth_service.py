"""Auth service — password hashing, JWT, user lookup.

Phase 1: simple email + password login. Argon2 hashing. Short-lived JWT
in HttpOnly cookie. 2FA wired but optional.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Customer, User, UserRole


__all__ = [
    "hash_password",
    "verify_password",
    "issue_jwt",
    "decode_jwt",
    "create_user",
    "authenticate",
    "new_session_token",
    "PasswordContext",
]


PasswordContext = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(plain: str) -> str:
    return PasswordContext.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return PasswordContext.verify(plain, hashed)
    except Exception:
        return False


def issue_jwt(
    *,
    user_id: int,
    role: str,
    customer_id: int | None = None,
    impersonating_customer_id: int | None = None,
) -> str:
    """Issue a JWT for the user. `impersonating_customer_id`, when set, marks
    this token as an admin-impersonation session — the staff user's own
    customer_id stays in `cid` (likely null) while `imp_cust` carries the
    customer they're currently acting as. See A4.28 (Shop as Customer).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "cid": customer_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
    }
    if impersonating_customer_id is not None:
        payload["imp_cust"] = impersonating_customer_id
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def new_session_token() -> str:
    """Anonymous session cart token (used until the user logs in)."""
    return secrets.token_urlsafe(32)


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    role: UserRole = UserRole.CUSTOMER,
    customer_id: int | None = None,
    display_name: str | None = None,
) -> User:
    user = User(
        email=email.strip().lower(),
        password_hash=hash_password(password),
        role=role,
        customer_id=customer_id,
        display_name=display_name,
        is_active=True,
        is_verified=True,  # Phase 1: skip email verification (add Week 2 if needed)
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> User | None:
    """Return the User if credentials match + account active. None otherwise."""
    stmt = select(User).where(User.email == email.strip().lower())
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return user
