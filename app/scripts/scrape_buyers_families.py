"""Buyers / SnowDogg family-page scraper — extract ALL child parts per page.

Companion to scrape_buyers_full.py which probes each SKU individually via
the autocomplete API (82% timeout rate on 13k products). This script takes
the opposite approach: visit the 658 already-discovered family pages and
extract every child part from each page in a single visit.

Three phases:
  1. Load known slugs from the checkpoint file → unique family page URLs.
  2. For each family page, extract the parts grid, open each part's modal
     for spec attributes, and collect images / PDFs / videos / features.
  3. Match extracted parts to DB products by stripped SKU and persist
     ProductAttribute, ProductFitment, ProductResource, ProductImage,
     ProductDescription, and Product.extended_description.

Run from app/ with the backend venv:
    cd /home/titan/titan-truck-website/app
    backend/.venv/bin/python -m scripts.scrape_buyers_families --limit 5
    backend/.venv/bin/python -m scripts.scrape_buyers_families
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


log = logging.getLogger("scrape_buyers_families")

BASE = "https://www.buyersproducts.com"
STORAGE_STATE = "/tmp/buyers_storage_state.json"
CHECKPOINT_PATH = "/tmp/buyers_slug_checkpoint.txt"

# ---------------------------------------------------------------------------
# Regex extractors — page is server-rendered HTML so regex is fine.
# ---------------------------------------------------------------------------

IMG_RE = re.compile(
    r'https?://pimimages\.buyersproducts\.com/products/[A-Z]+/[^"\'\s>]+\.(?:jpg|jpeg|png|webp)',
    re.IGNORECASE,
)
PDF_RE = re.compile(
    r'https?://pimimages\.buyersproducts\.com/products/Documents/[^"\'\s>]+\.pdf',
    re.IGNORECASE,
)
PDF_FALLBACK_RE = re.compile(r'https?://[^"\'\s>]+\.pdf', re.IGNORECASE)
YT_RE = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com/watch\?[^"\'\s>]+|youtu\.be/[A-Za-z0-9_-]+)',
    re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(r"(placeholder|coming-?soon|noimage|no-image)", re.IGNORECASE)

# Cross-link regex for Accessories section
ACCESSORY_SLUG_RE = re.compile(r'/product/([^/?#"\'>\s]+)')

# ---------------------------------------------------------------------------
# Helper functions (copied from scrape_buyers_full.py — scripts run as modules)
# ---------------------------------------------------------------------------


def _strip_prefix(sku: str) -> str:
    """ECCO-EW2403 -> EW2403; BBUY-12345 -> 12345; SNOW-16063140 -> 16063140."""
    return re.sub(r"^(?:[A-Z]{2,5}-)", "", sku)


def _to_large_url(u: str) -> str:
    """Buyers serves /SM/, /MD/, /LG/ variants of the same file. Prefer LG."""
    return re.sub(r"/products/(?:SM|MD|XS)/", "/products/LG/", u, count=1, flags=re.I)


def _is_sku_image(u: str, pn: str) -> bool:
    """Return True if image filename matches our product's part number."""
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
    cleaned = re.sub(r'\s+on[a-z]+="[^"]*"', "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+style=\"[^\"]*\"", "", cleaned)
    return cleaned[:max_len].strip()


_VALUE_UOM_RE = re.compile(
    r"^(\d[\d.,\s/\-+x]*?)\s*([A-Za-z\"'][\w./\"']{0,8})?\s*$"
)


def _split_value_uom(value: str) -> tuple[str, str | None]:
    """Best-effort split of a Buyers spec value into (value, uom)."""
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


# Modal spec keys that should go to ProductFitment, not ProductAttribute
_FITMENT_KEYS = {"start year", "end year", "make", "model"}


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
        """Try the known description containers and return inner HTML."""
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
    # Layout detection + content extractors (from scrape_buyers_full)
    # ------------------------------------------------------------------

    def detect_layout(self) -> str:
        """Return 'A' | 'B' | 'C' | 'D' based on heading + DOM signals."""
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
        """Layout B: extract spec key/value/uom triples."""
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
        """Layout B: return ordered list of feature panel texts."""
        try:
            panels = self.page.evaluate(
                """() => Array.from(document.querySelectorAll('.ui-accordion-content'))
                    .map(p => (p.innerText || '').trim())
                    .filter(t => t.length > 30)"""
            ) or []
        except Exception as e:
            log.warning("extract_features failed: %s", e)
            return []
        return [p[:4000] for p in panels if isinstance(p, str)]

    def extract_hero_bullets(self) -> list[str]:
        """Layout C/D: find the first <ul> with 2-12 sentence-like <li> items."""
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

    # ------------------------------------------------------------------
    # NEW: Family grid + modal extractors
    # ------------------------------------------------------------------

    def extract_family_grid(self) -> list[dict]:
        """Extract the parts grid from a family page.

        Returns a list of dicts:
          {part_number, description, year_start, year_end, model}

        CSS: .product-row:not(.col-title) are data rows.
        Each row has .product-col children in order:
          [0] .product-col.part-desc — part number + description
          [1] Start year
          [2] End year
          [3] Model
          [4] Action (WHERE TO BUY — ignored)
        """
        try:
            rows = self.page.evaluate(
                """() => {
                    const dataRows = Array.from(
                        document.querySelectorAll('.product-row:not(.col-title)')
                    );
                    return dataRows.map(row => {
                        const cols = Array.from(row.querySelectorAll('.product-col'));
                        if (cols.length < 4) return null;

                        // Column 0: part number + description
                        const partCol = cols[0];
                        const skuLink = partCol.querySelector('.sku-link');
                        let partNumber = '';
                        if (skuLink) {
                            partNumber = (skuLink.innerText || '').trim();
                        } else {
                            // Fall back to first text node
                            const walker = document.createTreeWalker(
                                partCol, NodeFilter.SHOW_TEXT, null, false
                            );
                            const firstText = walker.nextNode();
                            if (firstText) {
                                partNumber = (firstText.textContent || '').trim();
                            }
                        }
                        if (!partNumber) return null;

                        // Full text for description
                        const fullText = (partCol.innerText || '').trim();
                        // Description is everything after the part number
                        let description = fullText;
                        const pnIdx = fullText.indexOf(partNumber);
                        if (pnIdx >= 0) {
                            description = fullText.slice(pnIdx + partNumber.length).trim();
                        }

                        // Columns 1-3: years + model
                        const startYear = (cols[1].innerText || '').trim();
                        const endYear = (cols[2].innerText || '').trim();
                        const model = (cols[3].innerText || '').trim();

                        return {
                            part_number: partNumber,
                            description: description.slice(0, 500) || null,
                            year_start: /^\\d{4}$/.test(startYear)
                                ? parseInt(startYear, 10) : null,
                            year_end: /^\\d{4}$/.test(endYear)
                                ? parseInt(endYear, 10) : null,
                            model: model || null
                        };
                    }).filter(Boolean);
                }"""
            ) or []
        except Exception as e:
            log.warning("extract_family_grid failed: %s", e)
            return []
        return rows if isinstance(rows, list) else []

    def extract_part_modal(self, modal_sleep_ms: int = 1500) -> list[dict]:
        """Click each .sku-link in the grid, read modal specs, close modal.

        Returns a list of dicts, one per part:
          {part_number: str, specs: {key: value, ...}}

        Each .sku-link has ng-click="vm.showStyledProductImages(styledProduct)"
        which opens a .bpc-detail-gallery.reveal-modal modal with per-part
        attribute specs in li.attribute-list-item elements.

        Uses JS-dispatched clicks (page.evaluate) instead of Playwright's
        .click() because the modal overlay (.reveal-modal-bg) intercepts
        Playwright pointer events for subsequent links.
        """
        results: list[dict] = []

        # Count links via JS to avoid holding stale ElementHandles
        try:
            link_count = self.page.evaluate(
                "() => document.querySelectorAll('.sku-link').length"
            )
        except Exception as e:
            log.warning("count .sku-link failed: %s", e)
            return results

        if not link_count:
            return results

        for i in range(link_count):
            try:
                # Read part number and trigger click via JS (bypasses overlay)
                part_number = self.page.evaluate(
                    """(idx) => {
                        const links = document.querySelectorAll('.sku-link');
                        if (idx >= links.length) return null;
                        const link = links[idx];
                        const pn = (link.innerText || '').trim();
                        link.click();  // AngularJS ng-click fires in page context
                        return pn;
                    }""",
                    i,
                )
                if not part_number:
                    continue

                self.page.wait_for_timeout(1200)

                # Check if the modal appeared
                modal_visible = self.page.evaluate(
                    """() => {
                        const m = document.querySelector(
                            '.bpc-detail-gallery.reveal-modal'
                        );
                        return m && m.classList.contains('open');
                    }"""
                )
                if not modal_visible:
                    log.info("  modal did not appear for %s, skipping", part_number)
                    continue

                # Extract attribute key/value pairs from the modal
                specs = self.page.evaluate(
                    """() => {
                        const modal = document.querySelector(
                            '.bpc-detail-gallery.reveal-modal.open'
                        );
                        if (!modal) return {};
                        const items = Array.from(
                            modal.querySelectorAll('li.attribute-list-item')
                        );
                        const out = {};
                        for (const li of items) {
                            // The structure is typically:
                            //   <span class="attrib-name">Key</span>
                            //   <span class="attrib-value">Value</span>
                            const nameEl = li.querySelector('.attrib-name');
                            const valEl = li.querySelector('.attrib-value');
                            if (nameEl && valEl) {
                                const k = (nameEl.textContent || '').trim();
                                const v = (valEl.textContent || '').trim();
                                if (k && v) { out[k] = v; continue; }
                            }
                            // Fallback: children-based extraction
                            const children = Array.from(li.childNodes).filter(
                                n => (n.nodeType === 1 || n.nodeType === 3)
                                     && (n.textContent || '').trim().length > 0
                            );
                            if (children.length >= 2) {
                                const k = (children[0].textContent || '').trim();
                                const v = (children[1].textContent || '').trim();
                                if (k && v) out[k] = v;
                            } else {
                                // Last resort: split on tab/newline
                                const text = (li.innerText || '').trim();
                                const parts = text.split(/[\\t\\n]+/);
                                if (parts.length >= 2) {
                                    const k = parts[0].trim();
                                    const v = parts.slice(1).join(' ').trim();
                                    if (k && v) out[k] = v;
                                }
                            }
                        }
                        return out;
                    }"""
                ) or {}

                results.append({
                    "part_number": part_number,
                    "specs": specs,
                })

                # Close the modal via JS (bypasses overlay interception)
                self.page.evaluate(
                    """() => {
                        const btn = document.querySelector(
                            '.bpc-detail-gallery.reveal-modal.open .close-reveal-modal'
                        );
                        if (btn) btn.click();
                    }"""
                )
                self.page.wait_for_timeout(600)

                # Verify modal is closed; force-close if stuck
                still_open = self.page.evaluate(
                    """() => {
                        const m = document.querySelector(
                            '.bpc-detail-gallery.reveal-modal'
                        );
                        if (m && m.classList.contains('open')) {
                            // Force-remove the open class and hide overlay
                            m.classList.remove('open');
                            m.style.display = 'none';
                            const bg = document.querySelector('.reveal-modal-bg');
                            if (bg) bg.style.display = 'none';
                            return true;
                        }
                        return false;
                    }"""
                )
                if still_open:
                    log.info("  force-closed stuck modal after %s", part_number)

                # Pace between modal clicks
                self.page.wait_for_timeout(modal_sleep_ms)

            except Exception as e:
                log.warning("  modal extraction failed for part #%d: %s", i, e)
                # Force-dismiss any stuck modal
                try:
                    self.page.evaluate(
                        """() => {
                            document.querySelectorAll(
                                '.reveal-modal.open, .reveal-modal-bg'
                            ).forEach(el => {
                                el.classList.remove('open');
                                el.style.display = 'none';
                            });
                        }"""
                    )
                except Exception:
                    pass
                self.page.wait_for_timeout(modal_sleep_ms)
                continue

        return results

    def extract_accessory_slugs(self) -> list[str]:
        """Extract cross-link slugs from the Accessories section."""
        try:
            slugs = self.page.evaluate(
                """() => {
                    // Find the Accessories heading
                    const h3s = Array.from(document.querySelectorAll('h3'));
                    const accH3 = h3s.find(
                        h => /^accessories$/i.test((h.innerText||'').trim())
                    );
                    if (!accH3) return [];

                    // Walk up to find the accessories container
                    let container = accH3.parentElement;
                    for (let i = 0; i < 4 && container; i++) {
                        if (container.querySelectorAll('a[href*="/product/"]').length > 0)
                            break;
                        container = container.parentElement;
                    }
                    if (!container) return [];

                    const links = Array.from(
                        container.querySelectorAll('a[href*="/product/"]')
                    );
                    const out = [];
                    for (const a of links) {
                        const m = (a.getAttribute('href') || '').match(
                            /\\/product\\/([^/?#]+)/
                        );
                        if (m && m[1] && !out.includes(m[1])) out.push(m[1]);
                    }
                    return out;
                }"""
            ) or []
        except Exception as e:
            log.info("extract_accessory_slugs: %s", e)
            return []
        return slugs if isinstance(slugs, list) else []


# ============================================================================
# Main scrape driver
# ============================================================================

async def run(
    *,
    limit: int | None,
    dry_run: bool,
    sleep_ms: int = 8000,
    modal_sleep_ms: int = 1500,
) -> int:
    loop = asyncio.get_running_loop()

    async with async_session() as db:
        # ---- Phase 1: Load known slugs + build product lookup ----
        log.info("=== Phase 1: load slugs + build product lookup ===")

        checkpoint_path = Path(CHECKPOINT_PATH)
        if not checkpoint_path.exists():
            log.error("checkpoint file not found: %s", CHECKPOINT_PATH)
            return 1

        # Read checkpoint: SKU\tSLUG per line
        slug_set: set[str] = set()
        sku_slug_map: dict[str, str] = {}  # full map for reference
        for lineno, raw in enumerate(
            checkpoint_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                continue
            sku, slug = parts[0], parts[1]
            sku_slug_map[sku] = slug
            slug_set.add(slug)

        unique_slugs = sorted(slug_set)
        log.info("checkpoint loaded: %d mappings, %d unique slugs",
                 len(sku_slug_map), len(unique_slugs))

        if limit:
            unique_slugs = unique_slugs[:limit]
            log.info("limited to %d slugs", limit)

        # Load ALL Buyers/SnowDogg products from DB (including hidden)
        stmt = (
            select(Product)
            .join(Brand, Brand.id == Product.brand_id)
            .where(
                Product.is_for_sale.is_(True),
                or_(Brand.name.ilike("%buyers%"), Brand.name.ilike("%snowdogg%")),
            )
            .order_by(Product.id)
        )
        all_products = (await db.execute(stmt)).scalars().all()

        # Build lookup: {stripped_part_number: Product}
        pn_to_product: dict[str, Product] = {}
        for prod in all_products:
            pn = _strip_prefix(prod.sku)
            pn_to_product[pn] = prod
        log.info("DB products loaded: %d total, %d unique stripped PNs",
                 len(all_products), len(pn_to_product))

        # ---- Phase 2: Crawl each family page (in Playwright thread) ----
        def phase_crawl() -> list[dict]:
            """Returns list of per-slug data dicts."""
            all_page_data: list[dict] = []

            with BuyersSession() as sess:
                if not sess.warm_home():
                    log.warning("aborting: CF block at homepage")
                    return all_page_data

                total_slugs = len(unique_slugs)
                for idx, slug in enumerate(unique_slugs, 1):
                    page_data: dict = {
                        "slug": slug,
                        "grid_parts": [],
                        "modal_specs": [],
                        "images": [],
                        "pdfs": [],
                        "videos": [],
                        "desc": None,
                        "layout": "?",
                        "specs": [],
                        "features": [],
                        "bullets": [],
                        "accessory_slugs": [],
                    }

                    html = sess.fetch_pdp(slug)
                    if html is None:
                        log.warning("[page %d/%d] %s -> PDP fetch failed",
                                    idx, total_slugs, slug)
                        all_page_data.append(page_data)
                        continue

                    # Detect layout
                    layout = sess.detect_layout()
                    page_data["layout"] = layout

                    # Extract parts grid
                    grid_parts = sess.extract_family_grid()
                    page_data["grid_parts"] = grid_parts

                    # Extract modal specs for each part
                    modal_specs = sess.extract_part_modal(
                        modal_sleep_ms=modal_sleep_ms
                    )
                    page_data["modal_specs"] = modal_specs

                    # Extract page-level resources from HTML
                    images = sorted(set(IMG_RE.findall(html)))
                    pdfs = sorted(set(PDF_RE.findall(html)))
                    if not pdfs:
                        pdfs = sorted(set(PDF_FALLBACK_RE.findall(html)))
                    videos = sorted(set(YT_RE.findall(html)))

                    page_data["images"] = images
                    page_data["pdfs"] = pdfs
                    page_data["videos"] = videos

                    # Description HTML
                    page_data["desc"] = sess.description_html()

                    # Layout-specific extraction
                    if layout == "B":
                        page_data["specs"] = sess.extract_specs()
                        page_data["features"] = sess.extract_features()
                    elif layout in ("C", "D"):
                        page_data["bullets"] = sess.extract_hero_bullets()

                    # Accessories cross-links
                    page_data["accessory_slugs"] = sess.extract_accessory_slugs()

                    # Count how many grid parts match our DB
                    matched = sum(
                        1 for gp in grid_parts
                        if gp.get("part_number", "") in pn_to_product
                    )

                    log.info(
                        "[page %d/%d] %s -> layout=%s grid_parts=%d "
                        "modal_specs=%d matched=%d",
                        idx, total_slugs, slug, layout,
                        len(grid_parts), len(modal_specs), matched,
                    )

                    all_page_data.append(page_data)

                    # Human-paced jitter between pages
                    jitter = random.randint(-3000, 3000)
                    time.sleep(max(2000, sleep_ms + jitter) / 1000.0)

            return all_page_data

        log.info("=== Phase 2: crawl %d family pages ===", len(unique_slugs))
        crawl_results = await loop.run_in_executor(None, phase_crawl)

        # ---- Phase 3: Persist to DB ----
        log.info("=== Phase 3: persist ===")

        # Build a modal specs lookup: {part_number: {key: value}}
        # across all pages
        total_parts_found = 0
        total_matched = 0
        committed = 0
        commit_failures = 0
        total_imgs = 0
        total_pdfs = 0
        total_attrs = 0
        total_fitments = 0
        total_desc_rows = 0
        total_descs = 0

        for page_data in crawl_results:
            slug = page_data["slug"]
            grid_parts = page_data["grid_parts"]
            modal_specs_list = page_data["modal_specs"]
            images = page_data["images"]
            pdfs = page_data["pdfs"]
            layout = page_data["layout"]

            # Build modal spec lookup for this page: {pn: {key: val}}
            modal_by_pn: dict[str, dict[str, str]] = {}
            for ms in modal_specs_list:
                pn = (ms.get("part_number") or "").strip()
                if pn:
                    modal_by_pn[pn] = ms.get("specs") or {}

            total_parts_found += len(grid_parts)

            # Process each part found in the grid
            for gp in grid_parts:
                pn = (gp.get("part_number") or "").strip()
                if not pn:
                    continue

                prod = pn_to_product.get(pn)
                if not prod:
                    continue

                total_matched += 1

                # Per-SKU counters
                sku_imgs = 0
                sku_pdfs = 0
                sku_attrs = 0
                sku_fitments = 0
                sku_desc_rows = 0
                sku_desc = False

                modal_specs = modal_by_pn.get(pn, {})

                # --- ProductAttribute from modal specs ---
                for spec_key, spec_val in modal_specs.items():
                    if not spec_key or not spec_val:
                        continue
                    # Skip fitment keys — those go to ProductFitment
                    if spec_key.lower().strip() in _FITMENT_KEYS:
                        continue
                    if dry_run:
                        sku_attrs += 1
                        continue
                    exists_q = await db.execute(
                        select(ProductAttribute.id).where(
                            ProductAttribute.product_id == prod.id,
                            ProductAttribute.attribute_key == spec_key,
                        )
                    )
                    if exists_q.scalar_one_or_none() is not None:
                        continue
                    num, uom = _split_value_uom(spec_val)
                    db.add(ProductAttribute(
                        product_id=prod.id,
                        attribute_key=spec_key[:120],
                        attribute_value=num,
                        attribute_uom=(uom[:20] if uom else None),
                    ))
                    sku_attrs += 1

                # --- ProductFitment from grid row + modal make ---
                raw_model_col = (gp.get("model") or "").strip()
                year_start = gp.get("year_start")
                year_end = gp.get("year_end")

                if raw_model_col:
                    # Get Make from modal specs if available
                    modal_make = (modal_specs.get("Make") or "").strip()

                    # Parse model column — may contain "/" for multi-model
                    # e.g. "F250/F350/F450/F550"
                    # Or may be "Ford SuperDuty" where make is embedded
                    if "/" in raw_model_col:
                        model_variants = [
                            m.strip() for m in raw_model_col.split("/")
                            if m.strip()
                        ]
                    else:
                        model_variants = [raw_model_col]

                    for model_text in model_variants:
                        make = modal_make
                        model = model_text

                        # If no make from modal, try to infer from model text
                        # e.g. "Ford SuperDuty" -> make="Ford", model="SuperDuty"
                        if not make and " " in model_text:
                            parts_split = model_text.split(None, 1)
                            make = parts_split[0].strip()
                            model = parts_split[1].strip() if len(parts_split) > 1 else None
                        elif not make:
                            # Single token model with no make — skip fitment
                            continue

                        if not make:
                            continue

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

                # --- ProductResource: PDFs matched by part number ---
                for u in pdfs:
                    if not _is_sku_pdf(u, pn):
                        continue
                    if dry_run:
                        sku_pdfs += 1
                        continue
                    exists_q = await db.execute(
                        select(ProductResource.id).where(
                            ProductResource.product_id == prod.id,
                            ProductResource.url == u,
                        )
                    )
                    if exists_q.scalar_one_or_none() is not None:
                        continue
                    db.add(ProductResource(
                        product_id=prod.id,
                        kind=_classify_pdf(u),
                        url=u,
                        title=u.rsplit("/", 1)[-1],
                        sort_order=0,
                        source="buyersproducts.com",
                    ))
                    sku_pdfs += 1

                # --- ProductImage: images matched by part number ---
                sku_imgs_lg: list[str] = []
                seen_basenames: set[str] = set()
                for u in images:
                    if PLACEHOLDER_RE.search(u):
                        continue
                    if _is_sku_image(u, pn):
                        lg = _to_large_url(u)
                        base = lg.rsplit("/", 1)[-1].lower()
                        if base not in seen_basenames:
                            seen_basenames.add(base)
                            sku_imgs_lg.append(lg)

                # If no per-part images, use the first non-placeholder
                # image from the page as a hero fallback
                if not sku_imgs_lg:
                    for u in images:
                        if PLACEHOLDER_RE.search(u):
                            continue
                        lg = _to_large_url(u)
                        base = lg.rsplit("/", 1)[-1].lower()
                        if base not in seen_basenames:
                            seen_basenames.add(base)
                            sku_imgs_lg.append(lg)
                            break  # only one hero fallback

                if sku_imgs_lg and not dry_run:
                    existing = (await db.execute(
                        select(ProductImage).where(
                            ProductImage.product_id == prod.id
                        )
                    )).scalars().all()
                    existing_urls = {e.url for e in existing}
                    for i, url in enumerate(sku_imgs_lg):
                        if url in existing_urls:
                            continue
                        db.add(ProductImage(
                            product_id=prod.id,
                            url=url,
                            alt_text=prod.name[:200] if prod.name else None,
                            sort_order=i,
                            is_primary=(
                                i == 0
                                and not any(e.is_primary for e in existing)
                            ),
                        ))
                        sku_imgs += 1
                elif sku_imgs_lg and dry_run:
                    sku_imgs = len(sku_imgs_lg)

                # --- ProductDescription from features / bullets ---
                feature_texts = page_data.get("features") or []
                bullet_texts = page_data.get("bullets") or []
                desc_texts = feature_texts or bullet_texts
                for seq, text in enumerate(desc_texts, start=1):
                    if not text or len(text.strip()) < 10:
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

                # --- Product.extended_description ---
                desc_html = page_data.get("desc")
                if desc_html:
                    sanitized = _sanitize_html(desc_html)
                    if sanitized and (
                        not prod.extended_description
                        or len(prod.extended_description) < 100
                    ):
                        if not dry_run:
                            prod.extended_description = sanitized
                        sku_desc = True

                # --- Per-SKU commit ---
                if dry_run:
                    total_imgs += sku_imgs
                    total_pdfs += sku_pdfs
                    total_attrs += sku_attrs
                    total_fitments += sku_fitments
                    total_desc_rows += sku_desc_rows
                    if sku_desc:
                        total_descs += 1
                    continue

                if (sku_imgs == 0 and sku_pdfs == 0 and sku_attrs == 0
                        and sku_fitments == 0 and sku_desc_rows == 0
                        and not sku_desc):
                    continue

                try:
                    await db.commit()
                    committed += 1
                    total_imgs += sku_imgs
                    total_pdfs += sku_pdfs
                    total_attrs += sku_attrs
                    total_fitments += sku_fitments
                    total_desc_rows += sku_desc_rows
                    if sku_desc:
                        total_descs += 1
                except Exception as e:
                    commit_failures += 1
                    log.warning(
                        "commit failed for %s (%s): %s — rolling back",
                        prod.sku, pn, e,
                    )
                    try:
                        await db.rollback()
                    except Exception as rb:
                        log.error("rollback also failed for %s: %s", prod.sku, rb)

        log.info(
            "done: pages=%d total_parts_found=%d matched_to_db=%d "
            "committed=%d imgs=%d pdfs=%d attrs=%d fitments=%d "
            "desc_rows=%d descs=%d failures=%d",
            len(crawl_results), total_parts_found, total_matched,
            committed, total_imgs, total_pdfs, total_attrs, total_fitments,
            total_desc_rows, total_descs, commit_failures,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Buyers/SnowDogg family-page scraper — extract child parts "
                    "from each family page."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max number of family pages to visit (for testing)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Don't write to DB, just report counts",
    )
    parser.add_argument(
        "--sleep-ms", type=int, default=8000,
        help="Base delay between page visits in ms (default 8000, jittered +/-3000)",
    )
    parser.add_argument(
        "--modal-sleep-ms", type=int, default=1500,
        help="Delay between modal clicks within a page in ms (default 1500)",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return asyncio.run(
        run(
            limit=args.limit,
            dry_run=args.dry_run,
            sleep_ms=args.sleep_ms,
            modal_sleep_ms=args.modal_sleep_ms,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
