"""Admin message board — the one place an admin sees what needs attention.

Two producers:
  1. Persistent messages in `admin_message` (kit-conflict warnings raised by the
     catalog-visibility resolver; extensible to other kinds). Ack / resolve here.
  2. A LIVE site-health rollup computed on read from the `request_log` telemetry
     (recent 5xx, cart/checkout/payment failures, client JS errors, bot errors).
     Not materialized — surfaced live so the board reflects "right now".

Admin-only on every route.

    GET  /api/admin/messages?status=&kind=        list persistent messages
    POST /api/admin/messages/{id}/ack
    POST /api/admin/messages/{id}/resolve
    GET  /api/admin/messages/site-health?hours=   live request_log rollup
    GET  /api/admin/messages/stats                open count (header badge)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_admin
from app.models import AdminMessage, User

router = APIRouter(prefix="/api/admin/messages", tags=["admin-messages"])

KINDS = ("kit_conflict", "site_error", "cart_failure", "js_error", "page_down", "info")
STATUSES = ("open", "ack", "resolved")


def _serialize(m: AdminMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "kind": m.kind,
        "severity": m.severity,
        "title": m.title,
        "body": m.body,
        "context": m.context,
        "status": m.status,
        "occurrences": m.occurrences,
        "first_seen": m.first_seen.isoformat() if m.first_seen else None,
        "last_seen": m.last_seen.isoformat() if m.last_seen else None,
        "resolved_by": m.resolved_by,
        "resolved_at": m.resolved_at.isoformat() if m.resolved_at else None,
    }


@router.get("/stats")
async def stats(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Open (unresolved) persistent-message count for the header badge."""
    rows = (await db.execute(
        select(AdminMessage.status, func.count()).group_by(AdminMessage.status)
    )).all()
    by_status = {s: n for s, n in rows}
    return {
        "open": by_status.get("open", 0),
        "ack": by_status.get("ack", 0),
        "resolved": by_status.get("resolved", 0),
        "unresolved": by_status.get("open", 0) + by_status.get("ack", 0),
    }


@router.get("")
async def list_messages(
    status_f: str | None = Query(None, alias="status"),
    kind: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    stmt = select(AdminMessage)
    if status_f:
        stmt = stmt.where(AdminMessage.status == status_f)
    if kind:
        stmt = stmt.where(AdminMessage.kind == kind)
    rows = (await db.execute(stmt)).scalars().all()
    # Open first, then ack, then resolved; within a bucket, most recent first.
    rank = {"open": 0, "ack": 1, "resolved": 2}
    sev = {"critical": 0, "warning": 1, "info": 2}
    rows = sorted(rows, key=lambda m: (
        rank.get(m.status, 9), sev.get(m.severity, 9),
        -(m.last_seen.timestamp() if m.last_seen else 0),
    ))
    return {"messages": [_serialize(m) for m in rows], "total": len(rows)}


@router.post("/{message_id}/ack")
async def ack_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    m = (await db.execute(select(AdminMessage).where(AdminMessage.id == message_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "message not found")
    if m.status != "resolved":
        m.status = "ack"
    await db.commit()
    await db.refresh(m)
    return _serialize(m)


@router.post("/{message_id}/resolve")
async def resolve_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    m = (await db.execute(select(AdminMessage).where(AdminMessage.id == message_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "message not found")
    m.status = "resolved"
    m.resolved_by = admin.email or "admin"
    m.resolved_at = func.now()
    await db.commit()
    await db.refresh(m)
    return _serialize(m)


@router.get("/site-health")
async def site_health(
    hours: int = Query(48, ge=1, le=168, description="Look-back window"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> dict[str, Any]:
    """Live rollup from request_log for the last `hours` — major site issues
    (5xx, cart/checkout/payment failures, JS errors, bot errors). Computed on
    read; mirrors the nightly site-health report's Phase-2 signals."""
    W = f"ts > now() - interval '{int(hours)} hours'"

    async def val(sql: str) -> int:
        try:
            return int((await db.execute(text(sql))).scalar() or 0)
        except Exception:
            return 0

    async def rows(sql: str) -> list[dict]:
        try:
            res = (await db.execute(text(sql))).all()
            return [dict(r._mapping) for r in res]
        except Exception:
            return []

    has_data = await val("SELECT count(*) FROM request_log")
    total_err = await val(f"SELECT count(*) FROM request_log WHERE status>=400 AND {W}")
    err_5xx = await val(f"SELECT count(*) FROM request_log WHERE status>=500 AND {W}")
    js_errors = await val(f"SELECT count(*) FROM request_log WHERE kind='js_error' AND {W}")
    cart_fail = await val(
        f"SELECT count(*) FROM request_log WHERE status>=400 AND {W} AND ("
        "path LIKE '/api/cart%' OR path LIKE '/api/checkout%' OR path LIKE '/api/order%' "
        "OR path LIKE '/api/rma%' OR path ILIKE '%payment%')"
    )
    by_status = await rows(
        f"SELECT (status/100)||'xx' AS cls, count(*) AS c FROM request_log "
        f"WHERE status>=400 AND {W} GROUP BY 1 ORDER BY 1"
    )
    top_paths = await rows(
        f"SELECT path, status, count(*) AS c FROM request_log WHERE status>=400 AND {W} "
        "GROUP BY path, status ORDER BY c DESC LIMIT 15"
    )
    cart_paths = await rows(
        f"SELECT path, status, count(*) AS c FROM request_log WHERE status>=400 AND {W} AND ("
        "path LIKE '/api/cart%' OR path LIKE '/api/checkout%' OR path LIKE '/api/order%' "
        "OR path LIKE '/api/rma%' OR path ILIKE '%payment%') GROUP BY path, status ORDER BY c DESC LIMIT 15"
    )
    js_top = await rows(
        f"SELECT left(detail,160) AS detail, count(*) AS c FROM request_log "
        f"WHERE kind='js_error' AND {W} GROUP BY 1 ORDER BY c DESC LIMIT 10"
    )
    bot_errs = await rows(
        f"SELECT bot, count(*) AS c, count(*) FILTER (WHERE status>=400) AS errs FROM request_log "
        f"WHERE bot IS NOT NULL AND {W} GROUP BY bot ORDER BY errs DESC, c DESC LIMIT 12"
    )

    # Overall severity for the panel header.
    if err_5xx or cart_fail:
        severity = "critical"
    elif total_err or js_errors:
        severity = "warning"
    else:
        severity = "ok"

    return {
        "hours": hours,
        "telemetry_active": bool(has_data),
        "severity": severity,
        "counts": {
            "errors_4xx_5xx": total_err, "errors_5xx": err_5xx,
            "js_errors": js_errors, "cart_failures": cart_fail,
        },
        "by_status": by_status,
        "top_error_paths": top_paths,
        "cart_checkout_errors": cart_paths,
        "js_errors_top": js_top,
        "bot_errors": bot_errs,
    }
