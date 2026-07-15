"""Admin audit trail.

Records one `audit_log` row for every state-mutating request made by a
privileged user (ADMIN or EDITOR). Wired as an HTTP middleware in main.py so
coverage is automatic — every current and future admin endpoint is captured
without instrumenting each handler.

Gating is cheap, in this order so ordinary traffic pays almost nothing:
  1. non-mutating method (GET/HEAD/OPTIONS) → bail
  2. non-/api path, or a known telemetry/health/boot endpoint → bail
  3. no JWT cookie → bail (anonymous)
  4. JWT `role` claim not admin/editor → bail (no DB hit for shoppers)
Only a confirmed admin/editor mutation opens a short-lived session to snapshot
the actor's email and write the row.

Best-effort: any failure here is logged and swallowed so auditing can never
break the underlying request.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.database import async_session
from app.models import User, UserRole
from app.models.audit import AuditLog
from app.services.auth_service import decode_jwt

logger = logging.getLogger(__name__)

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_PRIVILEGED = {UserRole.ADMIN.value, UserRole.EDITOR.value}
# Telemetry / health / boot-time endpoints that aren't meaningful admin actions.
_SKIP_PREFIXES = ("/api/signals", "/api/health", "/api/auth/cf-login")


def _entity(path: str) -> tuple[str | None, str | None]:
    """Derive (entity_type, entity_id) from a request path.

    /api/admin/banners/12 -> ("admin/banners", "12")
    /api/admin/banners    -> ("admin/banners", None)
    """
    p = path[len("/api/"):] if path.startswith("/api/") else path
    segs = [s for s in p.split("/") if s]
    entity_id: str | None = None
    if segs and segs[-1].isdigit():
        entity_id = segs[-1]
        segs = segs[:-1]
    return ("/".join(segs)[:50] or None), entity_id


async def audit_admin_request(request: Any, response: Any) -> None:
    """Middleware hook: record this request iff it's a privileged mutation."""
    try:
        if request.method not in _MUTATING:
            return
        path = request.url.path
        if not path.startswith("/api/") or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return
        token = request.cookies.get("titan_jwt")
        if not token:
            return
        payload = decode_jwt(token)
        if not payload or str(payload.get("role", "")).lower() not in _PRIVILEGED:
            return
        try:
            user_id = int(payload["sub"])
        except (KeyError, ValueError, TypeError):
            return

        imp = payload.get("imp_cust")
        qs = f"?{request.url.query}" if request.url.query else ""
        summary = f"{request.method} {path}{qs} → {response.status_code}"
        if imp is not None:
            summary += f" (shopping as customer #{imp})"
        entity_type, entity_id = _entity(path)
        ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else None)
        ua = (request.headers.get("user-agent") or "")[:500] or None

        async with async_session() as db:
            email = (await db.execute(
                select(User.email).where(User.id == user_id)
            )).scalar_one_or_none()
            db.add(AuditLog(
                user_id=user_id,
                user_email=email,
                action=request.method,
                entity_type=entity_type,
                entity_id=entity_id,
                summary=summary,
                ip_address=ip,
                user_agent=ua,
            ))
            await db.commit()
    except Exception:
        logger.exception("admin audit logging failed")


async def record_admin_action(
    db,
    *,
    user: Any,
    action: str,
    entity_type: str | None = None,
    entity_id: Any = None,
    before: dict | None = None,
    after: dict | None = None,
    summary: str | None = None,
    request: Any = None,
) -> None:
    """Explicit, semantic audit entry (with optional before/after diff) for
    handlers that want richer detail than the middleware's generic record.

    Does NOT commit — the caller commits as part of its own transaction.
    """
    ip = ua = None
    if request is not None:
        ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else None)
        ua = (request.headers.get("user-agent") or "")[:500] or None
    db.add(AuditLog(
        user_id=getattr(user, "id", None),
        user_email=getattr(user, "email", None),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before,
        after=after,
        summary=summary,
        ip_address=ip,
        user_agent=ua,
    ))
