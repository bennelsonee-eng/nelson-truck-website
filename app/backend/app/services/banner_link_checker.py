"""Banner link health checker.

Validates each banner slide's click-through link and records the result on the
row (link_status / link_checked_at / link_error). A broken link auto-hides the
slide (is_active=False, auto_hidden=True); a recovered link auto-restores a
slide we previously auto-hid. A slide the admin hid by hand is left alone.

Link types:
  * empty / None         -> ok   (non-clickable; nothing to break)
  * /catalog?...         -> category/brand exist AND the filters resolve to >0
                            products (ignoring in_stock so a momentary
                            out-of-stock doesn't auto-hide a structurally-valid
                            banner)
  * /product/<sku>       -> a sellable product with that SKU exists
  * /categories/<slug>   -> a category with that slug exists
  * known landing route  -> ok
  * external http(s)://  -> URL responds 2xx/3xx (network error / bot-block /
                            timeout -> unknown, never auto-hidden)
  * anything else        -> unknown (don't auto-hide a path we don't model)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlsplit

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BannerSlide, Brand, Category, Product
from app.models.base import utc_now

log = logging.getLogger(__name__)

# Client-side React Router routes with no DB backing — valid if the frontend
# builds them. Keep in sync with the <Route> table in App.tsx.
VALID_LANDING_ROUTES = {
    "/", "/catalog", "/brands", "/snow-plows", "/snow-plows/compare",
    "/snow-plows/configurator", "/vans", "/aerial-lifts", "/compare", "/cart",
}


@dataclass
class BannerLinkCheckSummary:
    total: int = 0
    ok: int = 0
    broken: int = 0
    unknown: int = 0
    auto_hidden: int = 0
    restored: int = 0
    broken_details: list[dict] = field(default_factory=list)


async def check_one_link(db: AsyncSession, link: str | None) -> tuple[str, str | None]:
    """Return (status, error) for a single link without persisting anything."""
    v = (link or "").strip()
    if not v:
        return ("ok", None)
    low = v.lower()
    if low.startswith("http://") or low.startswith("https://"):
        return await _check_external(v)
    if not v.startswith("/"):
        return ("unknown", f"Unrecognized link form: {v[:80]}")

    parts = urlsplit(v)
    path = parts.path
    qs = parse_qs(parts.query)
    if path == "/catalog":
        return await _check_catalog(db, qs)
    if path.startswith("/product/"):
        return await _check_product(db, unquote(path[len("/product/"):]))
    if path.startswith("/categories/"):
        return await _check_category_slug(db, unquote(path[len("/categories/"):]))
    if path in VALID_LANDING_ROUTES:
        return ("ok", None)
    return ("unknown", f"Unknown route: {path}")


async def _check_catalog(db: AsyncSession, qs: dict[str, list[str]]) -> tuple[str, str | None]:
    category_path = (qs.get("category_path") or [None])[0]
    category_top = (qs.get("category_top") or [None])[0]
    q = (qs.get("q") or [None])[0]
    attrs = qs.get("attr") or []
    brands_raw = [b for b in (qs.get("brand") or []) if b]

    if category_path:
        like = f"{category_path} > %"
        exists = await db.scalar(
            select(Category.id)
            .where((Category.full_path == category_path) | (Category.full_path.like(like)))
            .limit(1)
        )
        if not exists:
            return ("broken", f"Category not found: {category_path}")

    canonical: list[str] = []
    for raw in brands_raw:
        bn = await db.scalar(
            select(Brand.name)
            .where(or_(func.lower(Brand.name) == raw.lower(), Brand.slug == raw.lower()),
                   Brand.is_active.is_(True))
            .limit(1)
        )
        if not bn:
            return ("broken", f"Brand not found or inactive: {raw}")
        canonical.append(bn)

    # Reuse the storefront's DB-direct browse to count matches. Ignore in_stock
    # on purpose — a structurally-valid banner shouldn't auto-hide just because
    # the matched products are momentarily out of stock.
    from app.routers.catalog import _browse_via_pace
    res = await _browse_via_pace(
        db, None, q=q, brands=canonical, category_top=category_top,
        category_path=category_path, attrs=attrs, in_stock_only=False,
        page=1, per_page=1,
    )
    if int(res.get("found", 0)) == 0:
        return ("broken", "Resolves to 0 products")
    return ("ok", None)


async def _check_product(db: AsyncSession, sku: str) -> tuple[str, str | None]:
    p = (await db.execute(select(Product).where(Product.sku == sku).limit(1))).scalar_one_or_none()
    if p is None:
        return ("broken", f"Product not found: {sku}")
    if getattr(p, "is_hidden", False) or not getattr(p, "is_for_sale", True):
        return ("broken", f"Product not available: {sku}")
    return ("ok", None)


async def _check_category_slug(db: AsyncSession, slug: str) -> tuple[str, str | None]:
    exists = await db.scalar(select(Category.id).where(Category.slug == slug).limit(1))
    return ("ok", None) if exists else ("broken", f"Category page not found: /categories/{slug}")


async def _check_external(url: str) -> tuple[str, str | None]:
    try:
        import httpx
    except Exception:
        return ("unknown", "External check unavailable (httpx missing)")
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "TitanLinkCheck/1.0"})
        status = r.status_code
        if status < 400:
            return ("ok", None)
        # Only treat clear "gone" + server errors as broken. 401/403/405/429
        # are usually bot-blocking on a live page, so don't auto-hide on those.
        if status in (404, 410) or 500 <= status < 600:
            return ("broken", f"HTTP {status}")
        return ("unknown", f"HTTP {status}")
    except Exception as e:
        return ("unknown", f"Could not reach: {type(e).__name__}")


async def check_all_banner_links(db: AsyncSession) -> BannerLinkCheckSummary:
    """Check every banner slide, persist status, and auto-hide/restore."""
    summary = BannerLinkCheckSummary()
    slides = (await db.execute(select(BannerSlide))).scalars().all()
    for s in slides:
        summary.total += 1
        try:
            status, error = await check_one_link(db, s.link_url)
        except Exception as e:  # never let one slide kill the sweep
            log.exception("Banner link check crashed for slide %s", s.id)
            status, error = ("unknown", f"checker error: {type(e).__name__}")

        s.link_status = status
        s.link_checked_at = utc_now()
        s.link_error = (error[:500] if error else None)

        if status == "broken":
            summary.broken += 1
            summary.broken_details.append({"id": s.id, "link_url": s.link_url, "error": error})
            if s.is_active and not s.auto_hidden:
                s.is_active = False
                s.auto_hidden = True
                summary.auto_hidden += 1
            elif s.is_active and s.auto_hidden:
                s.is_active = False  # stayed broken — keep it hidden
        elif status == "ok":
            summary.ok += 1
            if s.auto_hidden:  # link recovered → restore what we hid
                s.is_active = True
                s.auto_hidden = False
                summary.restored += 1
        else:
            summary.unknown += 1

    await db.commit()
    return summary
