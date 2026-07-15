"""Banner CMS endpoints.

Public:
    GET  /api/banners?audience=retail|wholesale&placement=home_hero
        Active, in-window slides for an audience (audience match OR 'both').

Admin (ADMIN or EDITOR — banners are content/scheduling):
    GET    /api/admin/banners
    POST   /api/admin/banners
    PUT    /api/admin/banners/{slide_id}
    DELETE /api/admin/banners/{slide_id}
    POST   /api/admin/banners/upload   (multipart image -> {url})
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_user
from app.models import BannerAudience, BannerSlide, User, UserRole
from app.models.base import utc_now

router = APIRouter(tags=["banners"])

UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "uploads" / "banners"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}


async def require_banner_editor(user: User = Depends(require_user)) -> User:
    """Banner management is allowed for ADMIN and EDITOR (content + scheduling)."""
    if user.role not in (UserRole.ADMIN, UserRole.EDITOR):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or editor role required")
    return user


# ---------------------------------------------------------------------------
# Field validation (shared by create + update)
# ---------------------------------------------------------------------------
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _validate_link(value: str | None) -> str | None:
    """A slide link must be blank, an on-site path ('/…'), or a full http(s) URL.

    Returns the trimmed value (empty -> None). Raises ValueError otherwise so the
    admin can't save a malformed destination (e.g. 'catalog?brand=Yakima' without
    a leading slash, or 'javascript:…').
    """
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    if v.startswith("/"):
        if v.startswith("//"):  # protocol-relative -> ambiguous, reject
            raise ValueError("Link must not start with '//'. Use a single '/' for on-site paths.")
        return v
    if re.match(r"^https?://[^\s/]+", v, re.IGNORECASE):
        return v
    raise ValueError("Link must start with '/' (on-site path) or be a full http(s):// URL.")


def _validate_color(value: str | None) -> str | None:
    """Fill color must be a hex color (#rgb, #rrggbb, or #rrggbbaa) or blank."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    if not _HEX_COLOR.match(v):
        raise ValueError("Fill color must be a hex value like #0b1f3a.")
    return v


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class BannerSlideOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_url: str
    alt: str
    link_url: str | None
    audience: BannerAudience
    placement: str
    sort_order: int
    is_active: bool
    starts_at: datetime | None
    ends_at: datetime | None
    fill_color: str | None
    edge_fade: bool
    link_status: str | None
    link_checked_at: datetime | None
    link_error: str | None
    auto_hidden: bool


class BannerSlideCreate(BaseModel):
    image_url: str
    alt: str = ""
    link_url: str | None = None
    audience: BannerAudience = BannerAudience.BOTH
    placement: str = "home_hero"
    sort_order: int = 1000
    is_active: bool = True
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    fill_color: str | None = None
    edge_fade: bool = False

    @field_validator("link_url")
    @classmethod
    def _ck_link(cls, v: str | None) -> str | None:
        return _validate_link(v)

    @field_validator("fill_color")
    @classmethod
    def _ck_color(cls, v: str | None) -> str | None:
        return _validate_color(v)


class BannerSlideUpdate(BaseModel):
    image_url: str | None = None
    alt: str | None = None
    link_url: str | None = None
    audience: BannerAudience | None = None
    placement: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    fill_color: str | None = None
    edge_fade: bool | None = None

    @field_validator("link_url")
    @classmethod
    def _ck_link(cls, v: str | None) -> str | None:
        return _validate_link(v)

    @field_validator("fill_color")
    @classmethod
    def _ck_color(cls, v: str | None) -> str | None:
        return _validate_color(v)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------
@router.get("/api/banners", response_model=list[BannerSlideOut])
async def list_active_banners(
    audience: str = "retail",
    placement: str = "home_hero",
    db: AsyncSession = Depends(get_db),
) -> list[BannerSlide]:
    """Active, in-window slides for the given audience (matches it or 'both')."""
    try:
        aud = BannerAudience(audience)
    except ValueError:
        aud = BannerAudience.RETAIL
    match = [BannerAudience.BOTH]
    if aud is not BannerAudience.BOTH:
        match.append(aud)

    now = utc_now()
    stmt = (
        select(BannerSlide)
        .where(
            BannerSlide.is_active.is_(True),
            BannerSlide.placement == placement,
            BannerSlide.audience.in_(match),
            or_(BannerSlide.starts_at.is_(None), BannerSlide.starts_at <= now),
            or_(BannerSlide.ends_at.is_(None), BannerSlide.ends_at >= now),
        )
        .order_by(BannerSlide.sort_order, BannerSlide.id)
    )
    return list((await db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@router.get("/api/admin/banners", response_model=list[BannerSlideOut])
async def admin_list_banners(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_banner_editor),
) -> list[BannerSlide]:
    stmt = select(BannerSlide).order_by(BannerSlide.placement, BannerSlide.sort_order, BannerSlide.id)
    return list((await db.execute(stmt)).scalars().all())


@router.post("/api/admin/banners", response_model=BannerSlideOut, status_code=201)
async def admin_create_banner(
    payload: BannerSlideCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_banner_editor),
) -> BannerSlide:
    slide = BannerSlide(**payload.model_dump())
    db.add(slide)
    await db.commit()
    await db.refresh(slide)
    return slide


@router.put("/api/admin/banners/{slide_id}", response_model=BannerSlideOut)
async def admin_update_banner(
    slide_id: int,
    payload: BannerSlideUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_banner_editor),
) -> BannerSlide:
    slide = await db.get(BannerSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(slide, field, value)
    # An admin edit overrides the auto-hide bookkeeping: changing the link
    # invalidates the stale health verdict (re-checked on the next sweep), and
    # explicitly toggling visibility hands control back to the admin.
    if "link_url" in data:
        slide.link_status = None
        slide.link_error = None
        slide.link_checked_at = None
    if "is_active" in data:
        slide.auto_hidden = False
    await db.commit()
    await db.refresh(slide)
    return slide


@router.post("/api/admin/banners/check-links")
async def admin_check_banner_links(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_banner_editor),
) -> dict[str, object]:
    """Run the banner link health check now (same logic as the nightly sweep)."""
    from app.services.banner_link_checker import check_all_banner_links
    summary = await check_all_banner_links(db)
    return {
        "total": summary.total, "ok": summary.ok, "broken": summary.broken,
        "unknown": summary.unknown, "auto_hidden": summary.auto_hidden,
        "restored": summary.restored, "broken_details": summary.broken_details,
    }


@router.delete("/api/admin/banners/{slide_id}")
async def admin_delete_banner(
    slide_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_banner_editor),
) -> dict[str, int]:
    slide = await db.get(BannerSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found")
    await db.delete(slide)
    await db.commit()
    return {"deleted": slide_id}


@router.post("/api/admin/banners/upload")
async def admin_upload_banner_image(
    image: UploadFile = File(...),
    _: User = Depends(require_banner_editor),
) -> dict[str, str]:
    """Save an uploaded image to /static/uploads/banners and return its URL."""
    ext = Path(image.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported image type '{ext}'")
    contents = await image.read()
    if len(contents) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 8 MB)")
    name = f"{uuid.uuid4().hex}{ext}"
    (UPLOADS_DIR / name).write_bytes(contents)
    return {"url": f"/static/uploads/banners/{name}"}
