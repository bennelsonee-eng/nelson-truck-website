"""Admin-editable content pages (FAQ + trust pages).

Public reads the effective override (if any); admins list/edit via require_admin.
Content model + storage live in services/content_store.py.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import require_admin
from app.models import User
from app.services import content_store

router = APIRouter(tags=["content"])


class ContentIn(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    body: str | None = None
    data: Any = None
    noindex: bool = False
    is_published: bool = True


@router.get("/api/content/{slug}")
async def public_content(slug: str) -> dict[str, Any]:
    """The admin override for a page, if published. 404 → the frontend renders
    its built-in default."""
    page = await content_store.get(slug, published_only=True)
    if not page:
        raise HTTPException(status_code=404, detail="no override")
    return page


@router.get("/api/admin/content")
async def admin_list(admin: User = Depends(require_admin)) -> list[dict[str, Any]]:
    return await content_store.list_all()


@router.get("/api/admin/content/{slug}")
async def admin_get(slug: str, admin: User = Depends(require_admin)) -> dict[str, Any]:
    page = await content_store.get(slug)
    return page or {"slug": slug, "override": False}


@router.put("/api/admin/content/{slug}")
async def admin_upsert(slug: str, payload: ContentIn,
                       admin: User = Depends(require_admin)) -> dict[str, Any]:
    if slug not in content_store.ALLOWED_SLUGS:
        raise HTTPException(status_code=400, detail=f"Unknown content slug: {slug}")
    return await content_store.upsert(
        slug,
        title=payload.title, subtitle=payload.subtitle, body=payload.body,
        data=payload.data, noindex=payload.noindex, is_published=payload.is_published,
        updated_by=getattr(admin, "username", None) or getattr(admin, "email", None),
    )
