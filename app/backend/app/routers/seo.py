"""SEO surface — robots.txt + XML sitemaps.

These live at the site ROOT (not under /api) so search engines find them at the
conventional locations. In dev/preview the Vite dev-server proxy forwards
`/robots.txt` and `/sitemap*.xml` here (see vite.config.ts); in production the
static front (nginx) will route the same paths to this backend.

Every absolute URL is built from `settings.canonical_base_url` — the single
source of truth for the canonical host (the launch domain, nelsontruck.com), NOT
the preview host we build on. See app/config.py.
"""

from __future__ import annotations

import logging
from math import ceil
from urllib.parse import quote
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Category, Product

log = logging.getLogger(__name__)

router = APIRouter(tags=["seo"])

# Keep child sitemaps well under the 50,000-URL / 50 MB protocol ceiling.
PRODUCTS_PER_SITEMAP = 20_000

# Static / landing routes worth indexing (clean paths only). Excludes the SPA's
# transactional + admin + mockup routes, which robots.txt also disallows.
# (priority, changefreq) tune crawl emphasis; home first.
STATIC_ROUTES: list[tuple[str, str, str]] = [
    ("/", "1.0", "daily"),
    ("/catalog", "0.9", "daily"),
    ("/brands", "0.7", "weekly"),
    ("/snow-plows", "0.8", "weekly"),
    ("/snow-plows/compare", "0.5", "monthly"),
    ("/snow-plows/configurator", "0.6", "monthly"),
    ("/aerial-lifts", "0.7", "weekly"),
    ("/vans", "0.7", "weekly"),
    ("/insights/competitive", "0.4", "monthly"),
    ("/faq", "0.6", "monthly"),
    ("/about", "0.5", "monthly"),
    ("/returns", "0.4", "monthly"),
    ("/shipping", "0.4", "monthly"),
]

# Product visibility gate — mirror the storefront's "is this sellable to an
# anonymous visitor" rule so the sitemap never advertises hidden / login-gated
# products (which would render as thin/blocked pages for a crawler). Crawlers
# are anonymous = the RETAIL channel, so use per-channel retail visibility: a
# product hidden only from wholesale/dealer/municipality stays in the sitemap.
def _visible_products():
    return (
        (Product.is_hidden_retail.is_(False))
        & (Product.is_for_sale.is_(True))
        & (Product.login_required.is_(False))
    )


def _xml_response(body: str) -> Response:
    return Response(content=body, media_type="application/xml")


def _urlset(entries: list[str]) -> str:
    """entries are pre-rendered <url>…</url> strings."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(entries)
        + "</urlset>\n"
    )


def _url(loc: str, lastmod: str | None = None, changefreq: str | None = None,
         priority: str | None = None) -> str:
    parts = [f"  <url><loc>{escape(loc)}</loc>"]
    if lastmod:
        parts.append(f"<lastmod>{lastmod}</lastmod>")
    if changefreq:
        parts.append(f"<changefreq>{changefreq}</changefreq>")
    if priority:
        parts.append(f"<priority>{priority}</priority>")
    parts.append("</url>\n")
    return "".join(parts)


def _abs(path: str) -> str:
    """Absolute URL on the canonical host. `path` must start with '/'."""
    base = get_settings().canonical_base_url.rstrip("/")
    return f"{base}{path}"


# --------------------------------------------------------------------------- #
# robots.txt
# --------------------------------------------------------------------------- #

@router.get("/robots.txt")
async def robots_txt() -> Response:
    sitemap = _abs("/sitemap.xml")
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        # Transactional / account / internal surfaces — no SEO value, keep out.
        "Disallow: /cart\n"
        "Disallow: /checkout\n"
        "Disallow: /account\n"
        "Disallow: /orders\n"
        "Disallow: /login\n"
        "Disallow: /signup\n"
        "Disallow: /admin/\n"
        "Disallow: /showroom/\n"
        "Disallow: /mockup/\n"
        "Disallow: /api/\n"
        # Faceted catalog params spawn near-duplicate URLs; let engines crawl the
        # clean category/product/landing pages and skip the sort/paginate noise.
        "Disallow: /*?*sort=\n"
        "Disallow: /*?*page=\n"
        "\n"
        f"Sitemap: {sitemap}\n"
    )
    return Response(content=body, media_type="text/plain")


# --------------------------------------------------------------------------- #
# llms.txt — emerging convention: a curated, LLM-readable map of the site so AI
# answer engines (ChatGPT/Perplexity/Gemini) can find and cite the right pages.
# --------------------------------------------------------------------------- #

@router.get("/llms.txt")
async def llms_txt() -> Response:
    b = get_settings().canonical_base_url.rstrip("/")
    body = f"""# Nelson Truck Equipment

> Pacific Northwest commercial truck-equipment dealer and upfitter, serving the region since 1937, with locations in Portland, OR and Kent, WA. Divisions: snow & ice (plows and spreaders), truck bodies (service, dump, flatbed, stake), tow trucks (wreckers, rollbacks, rotators, recovery, and tow-truck parts), aerial & bucket trucks, Landoll trailers and parts, liftgates and cranes, and truck & van accessories. We also stock steel by the pound and cut small jobs at the counter. B2B and retail, with wholesale pricing for trade accounts.

## What sets Nelson apart
- Pick it up today: parts are on the shelf in Portland and Kent — no waiting on shipping.
- We install everything we sell: plows, bodies, liftgates, and accessories are mounted, wired, and dialed in at our shops.
- Custom fabrication: service bodies, racks, and one-off builds.
- Real people: a counter team that sorts fitment and shows in-stock alternates.

## Key pages
- [Product catalog]({b}/catalog): Faceted search across the full truck & van catalog — accessories, equipment, snow plows, and more.
- [Snow plows & spreaders]({b}/snow-plows): Western, Meyer, Buyers SnowDogg and other commercial snow & ice equipment.
- [Aerial & bucket trucks]({b}/aerial-lifts): Dur-A-Lift bucket trucks and aerial lifts.
- [Shop by vehicle]({b}/catalog): Fitment-aware search — find parts that fit a specific year/make/model truck or van.
- [Brands]({b}/brands): Products organized by manufacturer.

## Fitment pages
- Vehicle-specific in-stock pages follow the pattern `{b}/fits/{{category}}/{{make}}/{{model}}` (e.g. floor mats, running boards, or bed covers that fit a specific truck), enumerated in the fitment sitemap.

## Sitemaps
- [Sitemap index]({b}/sitemap.xml): products, categories, brands, and fitment pages.

## Contact
- Email: sales@nelsontruck.com
- Portland, OR: (503) 548-9300
- Kent, WA: (253) 395-3825
- Locations: Portland, OR and Kent, WA — serving the Pacific Northwest.
"""
    return Response(content=body, media_type="text/plain")


# --------------------------------------------------------------------------- #
# sitemap index + children
# --------------------------------------------------------------------------- #

@router.get("/sitemap.xml")
async def sitemap_index(db: AsyncSession = Depends(get_db)) -> Response:
    count = (await db.execute(
        select(func.count()).select_from(Product).where(_visible_products())
    )).scalar_one()
    n_product_files = max(1, ceil(count / PRODUCTS_PER_SITEMAP))

    children = ["/sitemap-static.xml", "/sitemap-categories.xml", "/sitemap-fitment.xml"]
    children += [f"/sitemap-products-{i}.xml" for i in range(1, n_product_files + 1)]

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(
            f"  <sitemap><loc>{escape(_abs(c))}</loc></sitemap>\n" for c in children
        )
        + "</sitemapindex>\n"
    )
    return _xml_response(body)


@router.get("/sitemap-static.xml")
async def sitemap_static() -> Response:
    entries = [
        _url(_abs(path), changefreq=cf, priority=pri)
        for path, pri, cf in STATIC_ROUTES
    ]
    return _xml_response(_urlset(entries))


@router.get("/sitemap-categories.xml")
async def sitemap_categories(db: AsyncSession = Depends(get_db)) -> Response:
    rows = (await db.execute(
        select(Category.slug, Category.updated_at)
        .where(Category.is_active.is_(True))
        .order_by(Category.id)
    )).all()
    entries = [
        _url(
            _abs(f"/categories/{quote(slug, safe='')}"),
            lastmod=updated.date().isoformat() if updated else None,
            changefreq="weekly",
            priority="0.7",
        )
        for slug, updated in rows
        if slug
    ]
    return _xml_response(_urlset(entries))


@router.get("/sitemap-fitment.xml")
async def sitemap_fitment(db: AsyncSession = Depends(get_db)) -> Response:
    """Programmatic {category}×{vehicle} fitment landing pages (in-stock combos)."""
    from app.routers.fitment import get_combos
    data = await get_combos(db)
    entries = [
        _url(
            _abs(f"/fits/{quote(c['category'], safe='')}/{quote(c['make'], safe='')}/{quote(c['model'], safe='')}"),
            changefreq="weekly",
            priority="0.6",
        )
        for c in data["combos"]
    ]
    return _xml_response(_urlset(entries))


@router.get("/sitemap-products-{page}.xml")
async def sitemap_products(page: int, db: AsyncSession = Depends(get_db)) -> Response:
    if page < 1:
        page = 1
    offset = (page - 1) * PRODUCTS_PER_SITEMAP
    rows = (await db.execute(
        select(Product.sku, Product.updated_at)
        .where(_visible_products())
        .order_by(Product.id)
        .offset(offset)
        .limit(PRODUCTS_PER_SITEMAP)
    )).all()
    entries = [
        _url(
            _abs(f"/product/{quote(sku, safe='')}"),
            lastmod=updated.date().isoformat() if updated else None,
            changefreq="weekly",
            priority="0.6",
        )
        for sku, updated in rows
        if sku
    ]
    return _xml_response(_urlset(entries))
