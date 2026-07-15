"""Extended Buyers / SnowDogg scrape — multi-image + description + PDFs + videos.

Builds on scrape_buyers_images.py but loads the actual product detail
pages (not just the autocomplete API thumbnail) so we can capture:

  * Multiple images per product (carousel angles, lifestyle shots)
  * Long-form description HTML (sanitized, paragraphs / lists preserved)
  * PDF resources — install manuals, datasheets, brochures
  * YouTube video URLs
  * Spec key/value pairs (when present)

Architecture
------------
Buyers PDPs are FAMILY pages — a single page like
/product/snowdogg-vehicle-mounts-for-ram-trucks-2299 lists many of
our SKUs. The probe found that one page covered 9 of our 241 missing
SKUs. So we visit each unique FAMILY page once and attribute the
extracted resources to whichever of our SKUs match by filename
(e.g. 16063140INST_C.pdf → product with sku ending in 16063140).

Three phases per run:
  1. For each missing SKU, hit /api/v2/search/autocomplete/{pn} → slug
     (paced 4-7 sec each, single persistent browser session). Build a
     {sku → slug} map.
  2. Dedupe slugs, then load each unique /product/{slug} page once
     (paced 8-12 sec each). For each, extract images, PDFs, videos,
     description HTML.
  3. Attribute resources to our SKUs by filename match, write rows
     incrementally to ProductImage, ProductResource, ProductAttribute,
     and update Product.extended_description.

CF mitigations
--------------
  * ONE persistent browser session, ONE persistent storage_state file
    so CF cookies survive across runs
  * Stealth + Chromium "automation-controlled" flag off
  * Human-paced jitter (4-7s between autocomplete, 8-12s between PDP)
  * If a navigation lands on "Just a moment..." we sleep 60s and retry
    once; second failure = abort and pick up next run
  * Idempotent — skip products that already have an image+resource set

Run from app/ with the backend venv:
    cd /home/titan/titan-truck-website/app
    backend/.venv/bin/python -m scripts.scrape_buyers_full --limit 10
    backend/.venv/bin/python -m scripts.scrape_buyers_full

Owner ask 2026-05-18 (option C from the description-conflict question:
both kept, scraped goes to extended_description, PIES stays in
description if already set).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
BACKEND_DIR = APP_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import or_, select  # noqa: E402

from app.database import async_session, engine  # noqa: E402
engine.echo = False
engine.sync_engine.echo = False

from app.models import (  # noqa: E402
    Brand, Product, ProductAttribute, ProductDescription, ProductFitment,
    ProductImage, ProductResource, ResourceKind,
)
from playwright.sync_api import sync_playwright  # noqa: E402
from playwright_stealth import Stealth  # noqa: E402


log = logging.getLogger("scrape_buyers_full")

BASE = "https://www.buyersproducts.com"
STORAGE_STATE = "/tmp/buyers_storage_state.json"  # CF cookies survive across runs
CHECKPOINT_PATH = "/tmp/buyers_slug_checkpoint.txt"  # Phase-1 sku→slug, survives across runs


def _load_checkpoint() -> dict[str, str]:
    """Read prior {sku → slug} mappings. Malformed lines are skipped with a warning.

    Format: one mapping per line, any-whitespace-separated:  SKU<ws>SLUG
    Both pre-existing checkpoints (single space, from before this loader
    was written) and new ones written by `_append_checkpoint` (TAB) are
    accepted. Returns an empty dict if the file is missing.
    """
    path = Path(CHECKPOINT_PATH)
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # split(None, 1) collapses any whitespace run (tab OR space OR mixed)
            # into a single delimiter and yields at most 2 fields — exactly what
            # we want since slugs themselves never contain whitespace.
            parts = line.split(None, 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                log.warning("checkpoint:%d malformed, skipping: %r", lineno, raw)
                continue
            out[parts[0]] = parts[1]
    except Exception as e:  # pragma: no cover — defensive
        log.warning("checkpoint load failed: %s (continuing with empty map)", e)
        return {}
    return out


def _append_checkpoint(sku: str, slug: str) -> None:
    """Append a single mapping to the checkpoint file. POSIX small-line appends
    are atomic, so concurrent runs (shouldn't happen but) won't tear lines."""
    try:
        with open(CHECKPOINT_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{sku}\t{slug}\n")
            fh.flush()
    except Exception as e:
        log.warning("checkpoint append failed for %s: %s", sku, e)

# Regex extractors — page is server-rendered HTML so regex is fine.
IMG_RE = re.compile(
    r'https?://pimimages\.buyersproducts\.com/products/[A-Z]+/[^"\'\s>]+\.(?:jpg|jpeg|png|webp)',
    re.IGNORECASE,
)
PDF_RE = re.compile(
    r'https?://pimimages\.buyersproducts\.com/products/Documents/[^"\'\s>]+\.pdf',
    re.IGNORECASE,
)
# Catch other product-related PDFs not on pimimages too
PDF_FALLBACK_RE = re.compile(r'https?://[^"\'\s>]+\.pdf', re.IGNORECASE)
# YouTube watch URLs (skip the brand channel /user/ links)
YT_RE = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com/watch\?[^"\'\s>]+|youtu\.be/[A-Za-z0-9_-]+)',
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(r"(placeholder|coming-?soon|noimage|no-image)", re.IGNORECASE)


def _strip_prefix(sku: str) -> str:
    """ECCO-EW2403 → EW2403; BBUY-12345 → 12345; SNOW-16063140 → 16063140."""
    return re.sub(r"^(?:[A-Z]{2,5}-)", "", sku)


def _to_large_url(u: str) -> str:
    """Buyers serves /SM/, /MD/, /LG/ variants of the same file. Prefer LG."""
    return re.sub(r"/products/(?:SM|MD|XS)/", "/products/LG/", u, count=1, flags=re.I)


def _is_sku_image(u: str, pn: str) -> bool:
    """Return True if image filename matches our product's part number.
    Buyers names images like 16063140_45.jpg, 16063140_top.jpg etc.
    """
    fname = u.rsplit("/", 1)[-1]
    return fname.lower().startswith(pn.lower())


def _is_sku_pdf(u: str, pn: str) -> bool:
    """Same idea for PDFs — 16063140INST_C.pdf belongs to product 16063140."""
    fname = u.rsplit("/", 1)[-1]
    return fname.lower().startswith(pn.lower())


def _classify_pdf(url: str) -> ResourceKind:
    """Heuristic — Buyers uses naming conventions for resource types."""
    fname = url.rsplit("/", 1)[-1].lower()
    if "inst" in fname:
        return ResourceKind.INSTALLATION
    if "manual" in fname or "om" in fname:
        return ResourceKind.MANUAL
    if "spec" in fname or "datasheet" in fname:
        return ResourceKind.DATASHEET
    if "brochure" in fname or "cat" in fname:
        return ResourceKind.BROCHURE
    if "parts" in fname:
        return ResourceKind.PARTS_LIST
    if "wiring" in fname or "diagram" in fname:
        return ResourceKind.DIAGRAM
    return ResourceKind.MANUAL  # safest fallback


# Allowed HTML tags / attrs for description sanitization. Conservative —
# we want paragraphs + lists + emphasis, nothing more. No <a> by default
# so we can't get tricked into rendering a phishing link.
ALLOWED_TAGS = {
    "p", "br", "ul", "ol", "li", "strong", "b", "em", "i", "u",
    "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr", "td", "th",
    "div", "span",
}
TAG_RE = re.compile(r"</?([a-z0-9]+)(?:\s[^>]*)?>", re.IGNORECASE)


def _sanitize_html(html: str, max_len: int = 8000) -> str:
    """Strip tags not in ALLOWED_TAGS; keep text content. Cap at max_len."""
    def repl(m: re.Match[str]) -> str:
        tag = m.group(1).lower()
        if tag in ALLOWED_TAGS:
            return m.group(0)
        return ""
    cleaned = TAG_RE.sub(repl, html)
    # Strip on* event handlers if any slipped through (paranoid)
    cleaned = re.sub(r'\s+on[a-z]+="[^"]*"', "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+style=\"[^\"]*\"", "", cleaned)
    return cleaned[:max_len].strip()


# Regex for splitting a spec value into (numeric/dimension portion, unit-of-measure).
# Matches patterns like:
#   "114 \""           → ("114", "\"")
#   "12 Ga"            → ("12", "Ga")
#   "29/37 \""         → ("29/37", "\"")
#   "1 1/2 x 1 3/4 x 12 \"" → ("1 1/2 x 1 3/4 x 12", "\"")
#   "6"                → ("6", None)
#   "V Plow"           → ("V Plow", None)         (no digit prefix → returns whole)
#   "304 Stainless Steel" → ("304 Stainless Steel", None)  (UoM too long → returns whole)
_VALUE_UOM_RE = re.compile(
    r"^(\d[\d.,\s/\-+x]*?)\s*([A-Za-z\"'][\w./\"']{0,8})?\s*$"
)


def _split_value_uom(value: str) -> tuple[str, str | None]:
    """Best-effort split of a Buyers spec value into (value, uom). Falls back to
    returning the whole string with UoM=None if the pattern doesn't fit."""
    s = (value or "").strip()
    if not s:
        return s, None
    m = _VALUE_UOM_RE.match(s)
    if not m:
        return s, None
    num = (m.group(1) or "").strip()
    uom = m.group(2)
    if not num:
        return s, None
    return num, uom if uom else None


def _filter_modal_headings(text: str) -> bool:
    """Return True if a heading is real content (not modal/UI noise)."""
    if not text or len(text.strip()) < 2:
        return False
    return not re.search(
        r"^(added to wish list|warning|reentered password|notification center"
        r"|please sign in|-|menu|cart|search|account)$",
        text.strip(),
        re.IGNORECASE,
    )


# ============================================================================
# Playwright session wrapper
# ============================================================================

class BuyersSession:
    """Encapsulates the persistent Playwright browser + helpers."""

    def __init__(self, headless: bool = True):
        self._p = None
        self._browser = None
        self._ctx = None
        self.page = None
        self._stealth = Stealth()
        self.headless = headless

    def __enter__(self):
        self._p = sync_playwright().start()
        self._browser = self._p.chromium.launch(
            channel="chromium",
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        storage = Path(STORAGE_STATE)
        ctx_kwargs = dict(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        if storage.exists():
            ctx_kwargs["storage_state"] = str(storage)
            log.info("loaded storage state from %s", storage)
        self._ctx = self._browser.new_context(**ctx_kwargs)
        self._stealth.apply_stealth_sync(self._ctx)
        self.page = self._ctx.new_page()
        return self

    def __exit__(self, *exc):
        try:
            # Save storage state for next run
            self._ctx.storage_state(path=STORAGE_STATE)
            log.info("saved storage state to %s", STORAGE_STATE)
        except Exception:
            pass
        try: self._browser.close()
        except Exception: pass
        try: self._p.stop()
        except Exception: pass

    def warm_home(self) -> bool:
        """Land on homepage. Returns False if CF is still challenging."""
        try:
            self.page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(5000)
            if "Just a moment" in self.page.title():
                log.warning("CF challenge active on homepage")
                return False
            return True
        except Exception as e:
            log.warning("homepage navigation failed: %s", e)
            return False

    def get_slug(self, pn: str) -> str | None:
        """Resolve a part number to a Buyers product slug.

        Two-tier strategy (each is best-effort, falls through on miss):

          1. **Autocomplete API**: navigate to /search?criteria={pn} and
             wait briefly for ANY /api/v2/search/autocomplete/ response.
             The matcher is intentionally loosened (no {pn} in the URL)
             so we capture Buyers' pattern of mapping variant SKUs to a
             parent product — e.g. typing 'B2589BZ' may trigger an
             autocomplete request for the parent 'B2589' that doesn't
             match the strict-URL matcher and times out instead.

          2. **HTML fallback**: if the API yields nothing (or never fires
             a matching response), parse the rendered search results page
             for the first /product/{slug} anchor. Catches cases where
             Buyers' search engine returns results but the autocomplete
             API does not.

        Safe even when HTML fallback picks a sidebar/cross-sell slug:
        downstream Phase-3 attribution filters images/PDFs by filename
        prefix match against the original PN, so a wrong slug yields no
        data rather than corrupted attribution.

        Returns None if neither tier yields a slug or CF blocked us.
        """
        api_data: dict | None = None
        try:
            with self.page.expect_response(
                lambda r: "/api/v2/search/autocomplete/" in r.url and r.status == 200,
                timeout=12000,
            ) as resp_info:
                self.page.goto(
                    f"{BASE}/search?criteria={pn}",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
            try:
                j = resp_info.value.json()
                if isinstance(j, dict):
                    api_data = j
            except Exception:
                pass
        except Exception as e:
            log.info("  autocomplete %s → %s (trying HTML fallback)", pn, type(e).__name__)
            # Ensure we're on the search page even if expect_response timed out
            try:
                if "/search" not in (self.page.url or ""):
                    self.page.goto(
                        f"{BASE}/search?criteria={pn}",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
            except Exception:
                return None

        if "Just a moment" in (self.page.title() or ""):
            return None

        # Tier 1 — autocomplete API JSON
        items = (api_data or {}).get("products") or []
        if items:
            url = items[0].get("url")
            if url:
                return url

        # Tier 2 — HTML scrape of the rendered search results page
        try:
            self.page.wait_for_timeout(1500)  # let client-side render settle
            slugs = self.page.evaluate(
                """() => {
                    const links = Array.from(document.querySelectorAll('a[href*="/product/"]'));
                    const out = [];
                    for (const a of links) {
                        const m = (a.getAttribute('href') || '').match(/\\/product\\/([^/?#]+)/);
                        if (m && m[1] && !out.includes(m[1])) out.push(m[1]);
                        if (out.length >= 5) break;
                    }
                    return out;
                }"""
            ) or []
            if slugs:
                log.info("  %s → HTML fallback slug=%s", pn, slugs[0])
                return slugs[0]
        except Exception as e:
            log.info("  HTML fallback failed for %s: %s", pn, e)
        return None

    def fetch_pdp(self, slug: str) -> str | None:
        """Navigate to /product/{slug}; return page HTML or None on CF block."""
        try:
            self.page.goto(
                f"{BASE}/product/{slug}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            self.page.wait_for_timeout(6000)
            if "Just a moment" in (self.page.title() or ""):
                log.warning("CF on PDP %s, pausing 60s + retry", slug)
                self.page.wait_for_timeout(60000)
                self.page.reload(wait_until="domcontentloaded", timeout=60000)
                self.page.wait_for_timeout(5000)
                if "Just a moment" in (self.page.title() or ""):
                    return None
            return self.page.content()
        except Exception as e:
            log.warning("PDP fetch failed for %s: %s", slug, e)
            return None

    def description_html(self) -> str | None:
        """Try the known description containers (per probe) and return inner HTML
        of the most likely one, or None."""
        for sel in (
            ".product-detail-info",
            ".product-detail-view",
            ".item-description",
            ".item-card-description",
        ):
            try:
                el = self.page.query_selector(sel)
                if el is not None:
                    inner = el.inner_html()
                    if inner and len(inner.strip()) > 60:
                        return inner
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------
    # Categorized extractors (per layout discovery via probe — see
    # refs/buyers_layout_probes/LAYOUT_NOTES.md). All four extractors run
    # JS in-page via page.evaluate() against confirmed selectors.
    # ------------------------------------------------------------------

    def detect_layout(self) -> str:
        """Return 'A' | 'B' | 'C' | 'D' based on heading + DOM signals.

          A — Mount family page (fitment grid, no specs, no features)
          B — Premium plow (PRODUCT SPECIFICATIONS H2 + feature carousel)
          C — Spreader / utility box (ACCESSORIES H3 + 1 doc tab, hero bullets)
          D — Minimal product (no tabs, only hero bullets)
        """
        try:
            return self.page.evaluate(
                """() => {
                    const h2s = Array.from(document.querySelectorAll('h2'));
                    const h3s = Array.from(document.querySelectorAll('h3'));
                    const divs = Array.from(document.querySelectorAll('div'));
                    if (h2s.some(h => /product specifications/i.test(h.innerText||''))) return 'B';
                    if (divs.some(e => (e.innerText||'').trim() === 'START YEAR'
                                       && e.children.length === 0)) return 'A';
                    const hasAcc  = h3s.some(h => /^accessories$/i.test((h.innerText||'').trim()));
                    const hasDocs = h2s.some(h => /additional documentation/i.test(h.innerText||''));
                    if (hasAcc && hasDocs) return 'C';
                    return 'D';
                }"""
            )
        except Exception as e:
            log.warning("detect_layout failed: %s — defaulting to D", e)
            return "D"

    def extract_specs(self) -> list[tuple[str, str, str | None]]:
        """Layout B: extract spec key/value/uom triples from the
        PRODUCT SPECIFICATIONS section. Returns [] if no spec section.

        Structure: <ul> of <li> elements, each with 2 <span> children
        (span 1 = key, span 2 = value). UoM is split heuristically.
        """
        try:
            pairs = self.page.evaluate(
                """() => {
                    const h = Array.from(document.querySelectorAll('h2'))
                        .find(x => /product specifications/i.test(x.innerText||''));
                    if (!h) return [];
                    let c = h.parentElement;
                    for (let i = 0; i < 6 && c; i++) {
                        if ((c.innerText||'').length > 200) break;
                        c = c.parentElement;
                    }
                    if (!c) return [];
                    return Array.from(c.querySelectorAll('li')).map(li => {
                        const spans = Array.from(li.querySelectorAll(':scope > span'));
                        if (spans.length < 2) return null;
                        const key = (spans[0].innerText || '').trim();
                        const value = (spans[1].innerText || '').trim();
                        return (key && value) ? [key, value] : null;
                    }).filter(Boolean);
                }"""
            ) or []
        except Exception as e:
            log.warning("extract_specs failed: %s", e)
            return []
        out: list[tuple[str, str, str | None]] = []
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            key, raw_value = pair[0], pair[1]
            num, uom = _split_value_uom(raw_value)
            out.append((key, num, uom))
        return out

    def extract_features(self) -> list[str]:
        """Layout B: return ordered list of feature panel texts from
        .ui-accordion-content nodes. Each panel's innerText includes the
        feature heading + paragraph body (newline-separated). All 8 panels
        are in the DOM at once (hidden via ng-hide) — no tab clicks needed.
        """
        try:
            panels = self.page.evaluate(
                """() => Array.from(document.querySelectorAll('.ui-accordion-content'))
                    .map(p => (p.innerText || '').trim())
                    .filter(t => t.length > 30)"""
            ) or []
        except Exception as e:
            log.warning("extract_features failed: %s", e)
            return []
        # Cap each panel at 4000 chars to avoid runaway storage if Buyers ever
        # ships a giant feature panel.
        return [p[:4000] for p in panels if isinstance(p, str)]

    def extract_fitment(self) -> list[dict]:
        """Layout A: extract the fitment grid as a list of per-SKU rows.

        Returns [{sku, year_start, year_end, model, description}, ...]
        where sku is the stripped Buyers part number from the first cell.
        Empty list when not a Layout A page or grid is missing.

        Confirmed selector strategy (probe in LAYOUT_NOTES.md):
          * The leaf <div> whose text is exactly 'START YEAR' is the
            year-start column header.
          * Walk up two levels to the grid container.
          * Each direct child <div> except the header row is a data row.
          * Each data row's direct child <div>s are the cells, in the
            column order: PART NO. & DESCRIPTION | START YEAR |
            END YEAR | MODEL | INFORMATION | (action col).
          * The first cell's innerText starts with the SKU/part number.
        """
        try:
            rows = self.page.evaluate(
                """() => {
                    const headers = Array.from(document.querySelectorAll('div'));
                    const startYearHeader = headers.find(e =>
                        (e.innerText||'').trim() === 'START YEAR'
                        && e.children.length === 0
                    );
                    if (!startYearHeader) return [];
                    const headerRow = startYearHeader.parentElement;
                    if (!headerRow) return [];
                    const grid = headerRow.parentElement;
                    if (!grid) return [];
                    const dataRows = Array.from(grid.children).filter(c => c !== headerRow);
                    return dataRows.map(row => {
                        const cells = Array.from(row.children);
                        if (cells.length < 5) return null;
                        const skuText = (cells[0].innerText||'').trim();
                        // First whitespace-bounded token is the SKU/part number
                        const sku = (skuText.split(/\\s+/)[0] || '').trim();
                        if (!sku) return null;
                        const startTxt = (cells[1].innerText||'').trim();
                        const endTxt = (cells[2].innerText||'').trim();
                        const model = (cells[3].innerText||'').trim();
                        return {
                            sku: sku,
                            description: skuText.slice(0, 500),
                            year_start: /^\\d{4}$/.test(startTxt) ? parseInt(startTxt, 10) : null,
                            year_end: /^\\d{4}$/.test(endTxt) ? parseInt(endTxt, 10) : null,
                            model: model || null
                        };
                    }).filter(Boolean);
                }"""
            ) or []
        except Exception as e:
            log.warning("extract_fitment failed: %s", e)
            return []
        return rows if isinstance(rows, list) else []

    def extract_hero_bullets(self) -> list[str]:
        """Layout C/D: find the first <ul> with 2-12 sentence-like <li>
        items where each text is 20-300 chars and the first ends with
        period/exclam/question mark. Returns [] if no bullets found.

        The bullet UL has no class / id / attrs, so structural heuristics
        are the only reliable selector. Confirmed by probe against the
        RV bumper hitch and SaltDogg SHPE spreader.
        """
        try:
            bullets = self.page.evaluate(
                """() => {
                    const uls = Array.from(document.querySelectorAll('ul'));
                    for (const ul of uls) {
                        const lis = Array.from(ul.querySelectorAll(':scope > li'));
                        if (lis.length < 2 || lis.length > 12) continue;
                        const texts = lis.map(l => (l.innerText||'').trim());
                        if (texts.every(t => t.length >= 20 && t.length <= 300)
                            && /[.!?]\\s*$/.test(texts[0])) {
                            return texts;
                        }
                    }
                    return [];
                }"""
            ) or []
        except Exception as e:
            log.warning("extract_hero_bullets failed: %s", e)
            return []
        return [b for b in bullets if isinstance(b, str)]


# ============================================================================
# Main scrape driver
# ============================================================================

async def run(*, limit: int | None, dry_run: bool, fresh_sleep_ms: int = 5000,
              include_hidden: bool = False) -> int:
    loop = asyncio.get_running_loop()

    async with async_session() as db:
        # Products to (re-)scrape: any Buyers/SnowDogg product that doesn't
        # already have BOTH a primary image AND at least one ProductResource
        # from this source — that's the marker we've done a full pass.
        #
        # By default we exclude is_hidden=True products (consistent with the
        # storefront's public-query convention). With --include-hidden the
        # filter is dropped — used after a parts-master import that creates
        # thousands of products hidden-by-default and we want to enrich them
        # via scrape BEFORE deciding which ones to unhide.
        where_clauses = [
            Product.is_for_sale.is_(True),
            or_(Brand.name.ilike("%buyers%"), Brand.name.ilike("%snowdogg%")),
            # Filter to products lacking either an image or buyers resource
            ~(
                select(ProductImage.id)
                .where(ProductImage.product_id == Product.id)
                .exists()
            ) | ~(
                select(ProductResource.id)
                .where(
                    ProductResource.product_id == Product.id,
                    ProductResource.source == "buyersproducts.com",
                )
                .exists()
            ),
        ]
        if not include_hidden:
            where_clauses.insert(1, Product.is_hidden.is_(False))
        stmt = (
            select(Product)
            .join(Brand, Brand.id == Product.brand_id)
            .where(*where_clauses)
            .order_by(Product.id)
        )
        if limit:
            stmt = stmt.limit(limit)
        products = (await db.execute(stmt)).scalars().all()
        log.info("products to process: %d (limit=%s)", len(products), limit)

        if not products:
            return 0

        # Phase 1 + 2 happen in the Playwright thread; results stream back to
        # async land for DB writes (we can't easily share the AsyncSession
        # across thread boundaries, so we accumulate and write at end-of-phase).
        def phase_scrape() -> dict:
            """Returns {
                'sku_to_slug': {sku: slug},
                'slug_to_data': {slug: {images, pdfs, videos, desc}},
                'errors': [(sku, reason)],
            }"""
            out = {"sku_to_slug": {}, "slug_to_data": {}, "errors": []}
            with BuyersSession() as sess:
                if not sess.warm_home():
                    log.warning("aborting: CF block at homepage")
                    return out

                # ---- Phase 1: autocomplete → slug per SKU
                # Seed from on-disk checkpoint so a wedge mid-Phase-1 doesn't
                # force a full re-run of the autocomplete API (4-7s each).
                # The checkpoint may have been written with either full SKUs
                # (e.g. "BBUY-1312000") OR stripped part numbers (e.g.
                # "1312000") depending on whether the line came from this
                # script's _append_checkpoint or was hand-populated by an
                # earlier process. Match both: build a {pn → full_sku} map
                # for current products, then try the checkpoint key against
                # full_sku first and pn second. Only keep mappings for SKUs
                # in the CURRENT products list — completed-elsewhere SKUs
                # are already filtered out by the main DB query.
                checkpoint = _load_checkpoint()
                current_skus = {p.sku for p in products}
                pn_to_sku = {_strip_prefix(p.sku): p.sku for p in products}
                seeded = 0
                for cp_key, slug in checkpoint.items():
                    if cp_key in current_skus:
                        out["sku_to_slug"][cp_key] = slug
                        seeded += 1
                    elif cp_key in pn_to_sku:
                        out["sku_to_slug"][pn_to_sku[cp_key]] = slug
                        seeded += 1
                log.info(
                    "=== Phase 1: autocomplete (sku→slug) — seeded %d/%d from checkpoint ===",
                    seeded, len(checkpoint),
                )
                for i, prod in enumerate(products, 1):
                    if prod.sku in out["sku_to_slug"]:
                        log.info("[%d/%d] %s → cached slug=%s",
                                 i, len(products), prod.sku, out["sku_to_slug"][prod.sku])
                        continue
                    pn = _strip_prefix(prod.sku)
                    slug = sess.get_slug(pn)
                    if slug:
                        out["sku_to_slug"][prod.sku] = slug
                        _append_checkpoint(prod.sku, slug)
                        log.info("[%d/%d] %s → slug=%s",
                                 i, len(products), pn, slug)
                    else:
                        out["errors"].append((prod.sku, "no slug"))
                        log.info("[%d/%d] %s → no slug", i, len(products), pn)
                    # human-paced jitter
                    time.sleep((fresh_sleep_ms + random.randint(-1000, 2000)) / 1000.0)

                # ---- Phase 2: dedupe slugs, fetch each family PDP once.
                # Per-PDP we also run the categorized extractors (specs,
                # feature carousel panels, hero bullets) keyed by the
                # detected layout. See LAYOUT_NOTES.md for the four
                # layout patterns and which extractors apply to each.
                unique_slugs = sorted(set(out["sku_to_slug"].values()))
                log.info("=== Phase 2: PDPs (%d unique slugs from %d SKUs) ===",
                         len(unique_slugs), len(out["sku_to_slug"]))
                for j, slug in enumerate(unique_slugs, 1):
                    html = sess.fetch_pdp(slug)
                    if html is None:
                        log.warning("[%d/%d] %s → PDP fetch failed", j, len(unique_slugs), slug)
                        continue
                    images = sorted(set(IMG_RE.findall(html)))
                    pdfs = sorted(set(PDF_RE.findall(html)))
                    if not pdfs:
                        pdfs = sorted(set(PDF_FALLBACK_RE.findall(html)))
                    videos = sorted(set(YT_RE.findall(html)))
                    desc = sess.description_html()

                    # Categorized extraction — layout-aware
                    layout = sess.detect_layout()
                    specs    = sess.extract_specs()         if layout == "B" else []
                    features = sess.extract_features()      if layout == "B" else []
                    bullets  = sess.extract_hero_bullets()  if layout in ("C", "D") else []
                    fitment  = sess.extract_fitment()       if layout == "A" else []

                    out["slug_to_data"][slug] = {
                        "images": images, "pdfs": pdfs,
                        "videos": videos, "desc": desc,
                        "layout": layout, "specs": specs,
                        "features": features, "bullets": bullets,
                        "fitment": fitment,
                    }
                    log.info(
                        "[%d/%d] %s → layout=%s imgs=%d pdfs=%d vids=%d desc=%s specs=%d feat=%d bullets=%d fitment=%d",
                        j, len(unique_slugs), slug, layout,
                        len(images), len(pdfs), len(videos),
                        "yes" if desc else "no",
                        len(specs), len(features), len(bullets), len(fitment),
                    )
                    time.sleep((9000 + random.randint(-2000, 4000)) / 1000.0)
            return out

        scout = await loop.run_in_executor(None, phase_scrape)

        # ---- Phase 3: attribute and persist (in async land)
        # Per-SKU commit: if a later SKU's commit fails (DB hiccup, dead
        # connection after long Phase-1/2 idle), prior SKUs are already
        # durable and we just log + rollback + continue.
        log.info("=== Phase 3: persist ===")
        total_imgs = 0
        total_pdfs = 0
        total_vids = 0
        total_descs = 0
        total_attrs = 0       # NEW
        total_desc_rows = 0   # NEW
        total_fitments = 0    # NEW
        committed = 0
        commit_failures = 0
        for prod in products:
            slug = scout["sku_to_slug"].get(prod.sku)
            if not slug or slug not in scout["slug_to_data"]:
                continue
            data = scout["slug_to_data"][slug]
            pn = _strip_prefix(prod.sku)

            # Per-SKU counters (rolled into totals only after a successful commit)
            sku_imgs = 0
            sku_pdfs = 0
            sku_vids = 0
            sku_desc = False
            sku_attrs = 0       # NEW: ProductAttribute rows (Layout B specs)
            sku_desc_rows = 0   # NEW: ProductDescription rows (Layout B features + C/D bullets)
            sku_fitments = 0    # NEW: ProductFitment rows (Layout A year/make/model grid)

            # Images attributed by filename match (prefer LG variant)
            sku_imgs_lg: list[str] = []
            seen_basenames: set[str] = set()
            for u in data["images"]:
                if not _is_sku_image(u, pn): continue
                lg = _to_large_url(u)
                base = lg.rsplit("/", 1)[-1].lower()
                if base in seen_basenames: continue
                seen_basenames.add(base)
                sku_imgs_lg.append(lg)
            if sku_imgs_lg and not dry_run:
                # Wipe stale ProductImage rows from this source before re-writing
                existing = (await db.execute(
                    select(ProductImage).where(ProductImage.product_id == prod.id)
                )).scalars().all()
                existing_urls = {e.url for e in existing}
                for i, url in enumerate(sku_imgs_lg):
                    if url in existing_urls: continue
                    db.add(ProductImage(
                        product_id=prod.id,
                        url=url,
                        alt_text=prod.name[:200] if prod.name else None,
                        sort_order=i,
                        is_primary=(i == 0 and not any(e.is_primary for e in existing)),
                    ))
                    sku_imgs += 1
            elif sku_imgs_lg and dry_run:
                sku_imgs = len(sku_imgs_lg)

            # PDFs attributed by filename match
            for u in data["pdfs"]:
                if not _is_sku_pdf(u, pn): continue
                if dry_run:
                    sku_pdfs += 1
                    continue
                # Idempotent via uq_product_resource_url
                exists_q = await db.execute(
                    select(ProductResource.id).where(
                        ProductResource.product_id == prod.id,
                        ProductResource.url == u,
                    )
                )
                if exists_q.scalar_one_or_none() is not None: continue
                db.add(ProductResource(
                    product_id=prod.id,
                    kind=_classify_pdf(u),
                    url=u,
                    title=u.rsplit("/", 1)[-1],
                    sort_order=0,
                    source="buyersproducts.com",
                ))
                sku_pdfs += 1

            # Videos — family-level (no per-SKU filter)
            for u in data["videos"]:
                if "/user/" in u:  # skip brand channel
                    continue
                if dry_run:
                    sku_vids += 1
                    continue
                exists_q = await db.execute(
                    select(ProductResource.id).where(
                        ProductResource.product_id == prod.id,
                        ProductResource.url == u,
                    )
                )
                if exists_q.scalar_one_or_none() is not None: continue
                db.add(ProductResource(
                    product_id=prod.id,
                    kind=ResourceKind.VIDEO,
                    url=u,
                    title=None,
                    sort_order=0,
                    source="buyersproducts.com",
                ))
                sku_vids += 1

            # Description — family-level. Per owner option C: scraped goes
            # to extended_description; existing PIES `description` stays.
            if data["desc"]:
                sanitized = _sanitize_html(data["desc"])
                if sanitized and (not prod.extended_description or len(prod.extended_description) < 100):
                    if not dry_run:
                        prod.extended_description = sanitized
                    sku_desc = True

            # ----------------------------------------------------------------
            # Categorized text writes (the layout-aware extraction). Each
            # SKU in a family gets the same family-level spec / feature /
            # bullet set — Buyers PDPs are family pages so a single page's
            # data applies to all our SKUs that share that slug.
            # Idempotent: skip when a row with the same key/code+sequence
            # already exists for this product.
            # ----------------------------------------------------------------
            layout = data.get("layout", "?")

            # Layout B: PRODUCT SPECIFICATIONS → ProductAttribute rows.
            for key, value, uom in data.get("specs", []) or []:
                if not key or not value:
                    continue
                if dry_run:
                    sku_attrs += 1
                    continue
                exists_q = await db.execute(
                    select(ProductAttribute.id).where(
                        ProductAttribute.product_id == prod.id,
                        ProductAttribute.attribute_key == key,
                    )
                )
                if exists_q.scalar_one_or_none() is not None:
                    continue
                db.add(ProductAttribute(
                    product_id=prod.id,
                    attribute_key=key[:120],
                    attribute_value=value,
                    attribute_uom=(uom[:20] if uom else None),
                ))
                sku_attrs += 1

            # Layout B: feature carousel panels → ProductDescription FEA rows.
            for seq, text in enumerate(data.get("features", []) or [], start=1):
                if not text or len(text.strip()) < 20:
                    continue
                if dry_run:
                    sku_desc_rows += 1
                    continue
                exists_q = await db.execute(
                    select(ProductDescription.id).where(
                        ProductDescription.product_id == prod.id,
                        ProductDescription.description_code == "FEA",
                        ProductDescription.sequence == seq,
                    )
                )
                if exists_q.scalar_one_or_none() is not None:
                    continue
                db.add(ProductDescription(
                    product_id=prod.id,
                    description_code="FEA",
                    sequence=seq,
                    text=text.strip(),
                ))
                sku_desc_rows += 1

            # Layout A: fitment grid rows for THIS SKU → ProductFitment rows.
            # A family page's grid contains rows for ALL family SKUs; we match
            # by stripped PN (cell 0 text == pn). The MODEL cell typically
            # carries "RAM 1500" / "FORD F-150" — first whitespace-bounded
            # token is the make, remainder is the model.
            if layout == "A":
                for row in data.get("fitment") or []:
                    if (row.get("sku") or "") != pn:
                        continue  # row is for a different family SKU
                    raw_model = (row.get("model") or "").strip()
                    if not raw_model:
                        continue
                    parts = raw_model.split(None, 1)
                    make = parts[0].strip()
                    model = parts[1].strip() if len(parts) > 1 else None
                    if not make:
                        continue
                    year_start = row.get("year_start")
                    year_end = row.get("year_end")
                    if dry_run:
                        sku_fitments += 1
                        continue
                    # Idempotent via uq_product_fitment_unique
                    exists_q = await db.execute(
                        select(ProductFitment.id).where(
                            ProductFitment.product_id == prod.id,
                            ProductFitment.make == make,
                            ProductFitment.model == model,
                            ProductFitment.year_start == year_start,
                            ProductFitment.year_end == year_end,
                            ProductFitment.source == "buyersproducts.com",
                        )
                    )
                    if exists_q.scalar_one_or_none() is not None:
                        continue
                    db.add(ProductFitment(
                        product_id=prod.id,
                        year_start=year_start,
                        year_end=year_end,
                        make=make[:80],
                        model=(model[:120] if model else None),
                        source="buyersproducts.com",
                    ))
                    sku_fitments += 1

            # Layout C / D: hero bullet list → ProductDescription FEA rows
            # (same code as carousel; bullets are short-form features).
            for seq, bullet in enumerate(data.get("bullets", []) or [], start=1):
                if not bullet or len(bullet.strip()) < 10:
                    continue
                if dry_run:
                    sku_desc_rows += 1
                    continue
                exists_q = await db.execute(
                    select(ProductDescription.id).where(
                        ProductDescription.product_id == prod.id,
                        ProductDescription.description_code == "FEA",
                        ProductDescription.sequence == seq,
                    )
                )
                if exists_q.scalar_one_or_none() is not None:
                    continue
                db.add(ProductDescription(
                    product_id=prod.id,
                    description_code="FEA",
                    sequence=seq,
                    text=bullet.strip(),
                ))
                sku_desc_rows += 1

            # Per-SKU commit. dry_run path skips the DB round-trip but we
            # still roll the counters into totals so the final report is
            # comparable to a real run.
            if dry_run:
                total_imgs += sku_imgs
                total_pdfs += sku_pdfs
                total_vids += sku_vids
                total_attrs += sku_attrs
                total_desc_rows += sku_desc_rows
                total_fitments += sku_fitments
                if sku_desc:
                    total_descs += 1
                continue

            if (sku_imgs == 0 and sku_pdfs == 0 and sku_vids == 0
                    and not sku_desc and sku_attrs == 0 and sku_desc_rows == 0
                    and sku_fitments == 0):
                # Nothing changed for this SKU — no need to commit.
                continue

            try:
                await db.commit()
                committed += 1
                total_imgs += sku_imgs
                total_pdfs += sku_pdfs
                total_vids += sku_vids
                total_attrs += sku_attrs
                total_desc_rows += sku_desc_rows
                total_fitments += sku_fitments
                if sku_desc:
                    total_descs += 1
                log.info(
                    "  committed %s [layout=%s]: imgs=%d pdfs=%d vids=%d desc=%s attrs=%d descRows=%d fit=%d"
                    "  [running: %d SKUs / imgs=%d pdfs=%d vids=%d descs=%d attrs=%d descRows=%d fit=%d]",
                    prod.sku, layout, sku_imgs, sku_pdfs, sku_vids,
                    "y" if sku_desc else "n", sku_attrs, sku_desc_rows, sku_fitments,
                    committed, total_imgs, total_pdfs, total_vids,
                    total_descs, total_attrs, total_desc_rows, total_fitments,
                )
            except Exception as e:
                commit_failures += 1
                log.warning("commit failed for %s: %s — rolling back, continuing", prod.sku, e)
                try:
                    await db.rollback()
                except Exception as rb:
                    log.error("rollback also failed for %s: %s", prod.sku, rb)

        log.info(
            "done: products=%d  committed=%d  failures=%d  imgs=%d  pdfs=%d  vids=%d  descs=%d"
            "  attrs=%d  descRows=%d  fitments=%d",
            len(products), committed, commit_failures,
            total_imgs, total_pdfs, total_vids, total_descs,
            total_attrs, total_desc_rows, total_fitments,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of products to attempt this run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write DB rows; just report what would happen")
    parser.add_argument("--sleep-ms", type=int, default=5000,
                        help="Base delay between autocomplete calls (jittered)")
    parser.add_argument("--include-hidden", action="store_true",
                        help="Also scrape products with is_hidden=true. Used after "
                             "the parts-master import created thousands of new "
                             "products hidden-by-default that we want to enrich "
                             "before deciding which ones to unhide.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(run(limit=args.limit, dry_run=args.dry_run,
                           fresh_sleep_ms=args.sleep_ms,
                           include_hidden=args.include_hidden))


if __name__ == "__main__":
    sys.exit(main())
