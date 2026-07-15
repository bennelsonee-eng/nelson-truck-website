"""Admin-editable content for the static/trust pages (FAQ, About, Returns,
Shipping, Privacy).

The DB stores ADMIN OVERRIDES only; the frontend ships the drafted defaults, so
an empty table = the built-in content shows and nothing breaks. When an admin
saves a page it becomes an override that wins. Structured content (the FAQ's
sections/Q&A) rides in the `data` JSONB column; prose pages use `body`.

Self-applying like tester_activity — ensure_table() runs at startup, no manual
migration on deploy.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.database import async_session, engine

# Slugs the admin may edit (must match the frontend content routes).
ALLOWED_SLUGS = {"faq", "about", "returns", "shipping", "privacy"}

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS content_page (
        slug         TEXT PRIMARY KEY,
        title        TEXT,
        subtitle     TEXT,
        body         TEXT,
        data         JSONB,
        noindex      BOOLEAN NOT NULL DEFAULT FALSE,
        is_published BOOLEAN NOT NULL DEFAULT TRUE,
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_by   TEXT
    )
    """,
]


async def ensure_table() -> None:
    async with engine.begin() as conn:
        for stmt in _DDL:
            await conn.execute(text(stmt))


def _row_to_dict(r) -> dict[str, Any]:
    return {
        "slug": r.slug,
        "title": r.title,
        "subtitle": r.subtitle,
        "body": r.body,
        "data": r.data,
        "noindex": r.noindex,
        "is_published": r.is_published,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "updated_by": r.updated_by,
    }


async def get(slug: str, published_only: bool = False) -> dict[str, Any] | None:
    async with async_session() as s:
        r = (await s.execute(text("SELECT * FROM content_page WHERE slug = :slug"),
                             {"slug": slug})).first()
    if not r:
        return None
    d = _row_to_dict(r)
    if published_only and not d["is_published"]:
        return None
    return d


async def list_all() -> list[dict[str, Any]]:
    async with async_session() as s:
        rows = (await s.execute(text("SELECT * FROM content_page ORDER BY slug"))).all()
    return [_row_to_dict(r) for r in rows]


async def upsert(slug: str, *, title: str | None, subtitle: str | None,
                 body: str | None, data: Any, noindex: bool, is_published: bool,
                 updated_by: str | None) -> dict[str, Any]:
    async with async_session() as s:
        await s.execute(text("""
            INSERT INTO content_page (slug, title, subtitle, body, data, noindex, is_published, updated_by, updated_at)
            VALUES (:slug, :title, :subtitle, :body, CAST(:data AS JSONB), :noindex, :is_published, :updated_by, now())
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title, subtitle = EXCLUDED.subtitle, body = EXCLUDED.body,
                data = EXCLUDED.data, noindex = EXCLUDED.noindex, is_published = EXCLUDED.is_published,
                updated_by = EXCLUDED.updated_by, updated_at = now()
        """), {
            "slug": slug, "title": title, "subtitle": subtitle, "body": body,
            "data": json.dumps(data) if data is not None else None,
            "noindex": noindex, "is_published": is_published,
            "updated_by": updated_by,
        })
        await s.commit()
    return await get(slug)  # type: ignore[return-value]
