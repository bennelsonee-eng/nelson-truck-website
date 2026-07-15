"""
Tester activity log — per-identity page views + API access for the
Cloudflare-Access-gated preview site.

Cloudflare's own Access audit log already records *logins* (email, time, IP).
This captures what testers actually *do* once inside: API calls (logged by the
HTTP middleware) and SPA route changes (logged by the /api/signals/pageview
beacon, since client-side navigations never hit the backend otherwise). Each row
is keyed to the Cloudflare-verified email, so feedback filed through the
report-a-problem tool can be lined up with what the tester was viewing.

The table is created out-of-band via idempotent DDL at startup — same pattern as
`error_reports` — so there's no Alembic migration to manage.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.database import async_session, engine

logger = logging.getLogger(__name__)

# Executed once at startup. Each statement is independently idempotent.
_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS tester_activity (
        id          BIGSERIAL PRIMARY KEY,
        email       TEXT        NOT NULL DEFAULT '',
        event       TEXT        NOT NULL DEFAULT '',   -- 'pageview' | 'api'
        path        TEXT        NOT NULL DEFAULT '',
        method      TEXT        NOT NULL DEFAULT '',
        status      INTEGER,
        ip          TEXT        NOT NULL DEFAULT '',
        user_agent  TEXT        NOT NULL DEFAULT '',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_tester_activity_email_created "
    "ON tester_activity (email, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_tester_activity_created "
    "ON tester_activity (created_at DESC)",
]


async def ensure_table() -> None:
    """Create the tester_activity table + indexes if absent. Safe to call repeatedly."""
    async with engine.begin() as conn:
        for stmt in _DDL_STATEMENTS:
            await conn.execute(text(stmt))


async def log(
    *,
    email: str,
    event: str,
    path: str,
    method: str = "",
    status: int | None = None,
    ip: str = "",
    user_agent: str = "",
) -> None:
    """Insert one activity row. Best-effort: never raises into the caller."""
    try:
        async with async_session() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO tester_activity
                        (email, event, path, method, status, ip, user_agent)
                    VALUES
                        (:email, :event, :path, :method, :status, :ip, :ua)
                    """
                ),
                {
                    "email": (email or "")[:320],
                    "event": event,
                    "path": (path or "")[:1000],
                    "method": method,
                    "status": status,
                    "ip": (ip or "")[:64],
                    "ua": (user_agent or "")[:400],
                },
            )
            await session.commit()
    except Exception:  # logging must never break a request
        logger.exception("tester_activity.log failed (email=%s path=%s)", email, path)
