"""One-off probe: load a Buyers product detail page via Playwright + dump
selectors we'd want to scrape from. Not for production use — diagnostic
only. Run once to discover the page structure, then bake findings into
scrape_buyers_full.py.

Usage:
    backend/.venv/bin/python -m scripts.probe_buyers_pdp                 # default SKU 16063140
    backend/.venv/bin/python -m scripts.probe_buyers_pdp 16063140        # autocomplete then probe
    backend/.venv/bin/python -m scripts.probe_buyers_pdp --slug snowdogg-vehicle-mounts-for-ram-trucks-2299

Reads CF cookies from /tmp/buyers_storage_state.json (same file as the
production scraper) so we don't burn a fresh CF challenge per probe.

Writes:
  * /tmp/probe_buyers_pdp.html              — raw page HTML
  * /tmp/probe_buyers_pdp_screenshot.png    — full-page screenshot (visual record)
  * /tmp/probe_buyers_pdp_categorize.txt    — two-part report:
      1. VISUAL LAYOUT — tabs, headings in doc order, section previews,
         and a "rebuild plan" mapping each section to the DB rows we'd
         write to reproduce it on titan's storefront
      2. CATEGORIZATION — raw selectors, spec-table candidates, parsed
         <table>/<dl> key/value pairs
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


STORAGE_STATE = "/tmp/buyers_storage_state.json"
REPORT_PATH = "/tmp/probe_buyers_pdp_categorize.txt"
HTML_PATH = "/tmp/probe_buyers_pdp.html"
SCREENSHOT_PATH = "/tmp/probe_buyers_pdp_screenshot.png"

DESC_SELECTORS = (
    ".product-detail-info",
    ".product-detail-view",
    ".item-description",
    ".item-card-description",
)

# Candidates within a description container that might hold spec key/value pairs
SPEC_CANDIDATE_SELECTORS = (
    "table",
    "dl",
    "[class*='spec' i]",
    "[class*='feature' i]",
    "[class*='attribute' i]",
    "[class*='property' i]",
)

# Tab / accordion structure — tells us if the PDP segments text into
# Features / Description / Installation / Specs panels (PIES description
# codes would map there).
TAB_SELECTORS = (
    "[role='tablist']",
    "[role='tab']",
    ".nav-tabs",
    ".nav-pills",
    ".accordion",
    "[class*='tab-' i]",
)


def _write(lines: list[str], *parts: str) -> None:
    for p in parts:
        lines.append(p)
    lines.append("")


def _trim(s: str, n: int = 400) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _parse_table_kv(page, table_handle) -> list[tuple[str, str]]:
    """Best-effort key/value extraction from a <table>. Tries two-column
    layouts first (th+td, td+td), falls back to first/last cell."""
    try:
        rows = table_handle.query_selector_all("tr")
    except Exception:
        return []
    out: list[tuple[str, str]] = []
    for tr in rows:
        cells = tr.query_selector_all("th,td")
        if len(cells) < 2:
            continue
        k = (cells[0].inner_text() or "").strip()
        v = (cells[-1].inner_text() or "").strip()
        if not k or not v or k.lower() == v.lower():
            continue
        # Strip trailing colon from key
        k = k.rstrip(":").strip()
        out.append((k, v))
    return out


def _parse_dl_kv(dl_handle) -> list[tuple[str, str]]:
    """Pull <dt>/<dd> pairs as key/value."""
    try:
        dts = dl_handle.query_selector_all("dt")
        dds = dl_handle.query_selector_all("dd")
    except Exception:
        return []
    out: list[tuple[str, str]] = []
    for dt, dd in zip(dts, dds):
        k = (dt.inner_text() or "").strip().rstrip(":").strip()
        v = (dd.inner_text() or "").strip()
        if k and v:
            out.append((k, v))
    return out


def _maybe_split_uom(value: str) -> tuple[str, str | None]:
    """ '8 ft' → ('8','ft'); '10,000 lbs' → ('10,000','lbs'); '8' → ('8',None)."""
    m = re.match(r"^([\d.,\-]+)\s*([A-Za-z][A-Za-z./]{0,8})?$", value.strip())
    if not m:
        return value, None
    num, uom = m.group(1), m.group(2)
    return num, (uom if uom else None)


# Heading text → (display kind, target DB row(s)).
# Buyers PDPs vary product-to-product so we match by keyword, not exact text.
# Order matters — first hit wins (more specific keywords first).
HEADING_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bparts?\s*list\b", re.I),           "parts_list",   "ProductResource kind=PARTS_LIST"),
    (re.compile(r"\binstall(ation)?\b", re.I),         "installation", "ProductDescription code=INL"),
    (re.compile(r"\b(owner'?s\s+)?manual\b", re.I),    "manual",       "ProductResource kind=MANUAL"),
    (re.compile(r"\bdatasheet|spec\s*sheet\b", re.I),  "datasheet",    "ProductResource kind=DATASHEET"),
    (re.compile(r"\bbrochure\b", re.I),                "brochure",     "ProductResource kind=BROCHURE"),
    (re.compile(r"\bwiring|diagram\b", re.I),          "diagram",      "ProductResource kind=DIAGRAM"),
    (re.compile(r"\bspec(ification)?s?\b", re.I),      "specs",        "ProductAttribute rows (key/value/uom)"),
    (re.compile(r"\bfeatures?|benefits?|highlights?\b", re.I),
                                                       "features",     "ProductDescription code=FEA"),
    (re.compile(r"\b(fitment|compat|vehicle|applicat)", re.I),
                                                       "fitment",      "Fitment/compat table (model needed)"),
    (re.compile(r"\bwarrant", re.I),                   "warranty",     "ProductDescription code=WAR"),
    (re.compile(r"\bdownload|resource|document\b", re.I),
                                                       "downloads",    "ProductResource (mixed kinds)"),
    (re.compile(r"\bvideo\b", re.I),                   "videos",       "ProductResource kind=VIDEO"),
    (re.compile(r"\b(descript|overview|about|details)\b", re.I),
                                                       "description",  "ProductDescription code=DES"),
    (re.compile(r"\brelated|you\s+may\s+also|similar\b", re.I),
                                                       "related",      "(skip — handled by storefront)"),
    (re.compile(r"\breview", re.I),                    "reviews",      "(skip — out of scope)"),
]


def classify_heading(text: str) -> tuple[str, str]:
    """Return (kind_slug, db_target_description). 'other' if nothing matches."""
    for pat, kind, target in HEADING_RULES:
        if pat.search(text):
            return kind, target
    return "other", "(unclassified — review manually)"


def visual_layout_dump(page) -> str:
    """Walk the page as the viewer experiences it: tabs, headings, section
    contents, in document order. Output groups what the human sees with what
    we'd write to the DB to reproduce it on titan."""
    lines: list[str] = []
    _write(lines, "=" * 78, "VISUAL LAYOUT (as the viewer sees it)", "=" * 78)

    # ---- 1. Tab / accordion enumeration
    _write(lines, "--- presentation pattern detection ---")
    try:
        tab_handles = page.query_selector_all(
            "[role='tab'], .nav-tabs .nav-link, .nav-pills .nav-link, "
            ".accordion-button, .accordion-header button"
        )
    except Exception:
        tab_handles = []
    if tab_handles:
        _write(lines, f"  TABS / ACCORDION detected: {len(tab_handles)} item(s)")
        _write(lines, "  (the storefront should mirror this segmentation — each tab below"
                       " maps to one rendered section on our PDP)")
        for i, tab in enumerate(tab_handles, 1):
            try:
                label = _trim((tab.inner_text() or ""), 80)
                role = tab.get_attribute("role") or ""
                controls = tab.get_attribute("aria-controls") or ""
                href = tab.get_attribute("href") or ""
            except Exception:
                continue
            if not label:
                continue
            kind, target = classify_heading(label)
            _write(lines,
                   f"  [tab {i}] {label!r}",
                   f"        role={role!r}  aria-controls={controls!r}  href={href!r}",
                   f"        → kind={kind}  |  DB: {target}")
    else:
        _write(lines, "  No tabs/accordion — page likely uses heading-based segmentation")

    # ---- 2. All headings in document order, classified
    _write(lines, "", "--- heading walk (document order, h1-h4) ---")
    try:
        heading_handles = page.query_selector_all("h1, h2, h3, h4")
    except Exception:
        heading_handles = []
    headings_seen: list[tuple[str, str, str, str]] = []  # (tag, text, kind, target)
    for h in heading_handles:
        try:
            tag = h.evaluate("e => e.tagName") or "?"
            text = _trim((h.inner_text() or "").strip(), 120)
        except Exception:
            continue
        if not text or len(text) < 2:
            continue
        # Skip navigation/UI headings
        if re.search(r"^(menu|cart|search|account|sign\s*in|home)$", text, re.I):
            continue
        kind, target = classify_heading(text)
        headings_seen.append((tag, text, kind, target))
        _write(lines, f"  [{tag}] {text!r}",
                       f"        → kind={kind}  |  DB: {target}")

    # ---- 3. Per-heading preview: what content lives directly under each?
    _write(lines, "", "--- section contents (heading → next sibling text preview) ---")
    for tag, text, kind, target in headings_seen:
        if kind in ("related", "reviews", "other"):
            continue
        # Walk JS-side to handle nested DOM gracefully
        try:
            preview = page.evaluate(
                """(headingText) => {
                    const all = Array.from(document.querySelectorAll('h1,h2,h3,h4'));
                    const h = all.find(e => (e.innerText || '').trim().startsWith(headingText));
                    if (!h) return '';
                    let n = h.nextElementSibling;
                    // walk forward up to 8 siblings, accumulating text
                    let buf = '';
                    let count = 0;
                    while (n && count < 8) {
                        const t = (n.innerText || '').trim();
                        if (t && t.length > 5) { buf += t + '\\n'; count++; }
                        n = n.nextElementSibling;
                    }
                    // If no siblings yielded text, try parent's text minus heading
                    if (!buf && h.parentElement) {
                        const ptxt = (h.parentElement.innerText || '').trim();
                        buf = ptxt.replace(h.innerText, '').trim();
                    }
                    return buf.slice(0, 600);
                }""",
                text[:60],
            ) or ""
        except Exception:
            preview = ""
        if not preview:
            continue
        _write(lines, f"  [{text}]   ({kind})")
        for line in preview.splitlines()[:6]:
            _write(lines, f"      {line[:160]}")

    # ---- 4. Rebuild plan summary — what DB writes would mirror this layout
    _write(lines, "", "--- REBUILD PLAN (what DB writes reproduce this page) ---")
    by_kind: dict[str, list[str]] = {}
    for _, text, kind, target in headings_seen:
        by_kind.setdefault(kind, []).append(text)
    if not by_kind:
        _write(lines, "  (no classified headings — fall back to single extended_description blob)")
    else:
        for kind, headings in by_kind.items():
            if kind in ("related", "reviews", "other"):
                continue
            _, target = classify_heading(headings[0])
            _write(lines, f"  {kind} → {target}")
            for h_text in headings:
                _write(lines, f"      from heading: {h_text!r}")

    # ---- 5. Hero / above-the-fold structure (gallery, title, key facts)
    _write(lines, "", "--- hero / above-the-fold structure ---")
    for sel, label in [
        ("h1", "title (h1)"),
        ("[class*='gallery' i], [class*='carousel' i]", "image gallery"),
        ("[class*='price' i]", "price area"),
        ("button[class*='cart' i], a[class*='cart' i]", "CTA / cart"),
        ("[class*='breadcrumb' i]", "breadcrumb"),
        ("[class*='sku' i], [class*='part-number' i]", "SKU / part number display"),
    ]:
        try:
            el = page.query_selector(sel)
        except Exception:
            el = None
        if el is None:
            _write(lines, f"  {label}: (not found via {sel})")
            continue
        try:
            txt = _trim((el.inner_text() or "").strip(), 160)
            cls = (el.get_attribute("class") or "")[:80]
        except Exception:
            continue
        _write(lines, f"  {label}: {txt!r}  (class={cls!r})")

    return "\n".join(lines)


def categorize_dump(page, html: str) -> str:
    lines: list[str] = []
    _write(lines, "=" * 78, "CATEGORIZATION PROBE", "=" * 78)

    # 1. Description containers — which selectors hit, how big, dump outerHTML
    _write(lines, "--- description container candidates ---")
    for sel in DESC_SELECTORS:
        try:
            el = page.query_selector(sel)
        except Exception as e:
            _write(lines, f"  {sel} → query error: {e}")
            continue
        if el is None:
            _write(lines, f"  {sel} → no match")
            continue
        try:
            inner = el.inner_html() or ""
            outer = el.evaluate("e => e.outerHTML") or ""
        except Exception as e:
            _write(lines, f"  {sel} → read error: {e}")
            continue
        _write(lines,
               f"  {sel} → HIT  inner_html_len={len(inner)}  outer_html_len={len(outer)}",
               f"    text_preview: {_trim(el.inner_text(), 240)}",
               "    outerHTML (first 1200 chars):",
               "    " + _trim(outer, 1200).replace("\n", "\n    "))

    # 2. Spec-candidate elements globally (not just inside description container —
    #    Buyers sometimes hangs specs in a sibling block)
    _write(lines, "", "--- spec candidate elements (global) ---")
    for sel in SPEC_CANDIDATE_SELECTORS:
        try:
            els = page.query_selector_all(sel)
        except Exception as e:
            _write(lines, f"  {sel} → query error: {e}")
            continue
        if not els:
            _write(lines, f"  {sel} → 0 matches")
            continue
        _write(lines, f"  {sel} → {len(els)} match(es)")
        for i, el in enumerate(els[:4], 1):  # first 4 per selector
            try:
                cls = el.get_attribute("class") or "(no class)"
                txt = _trim(el.inner_text(), 200)
                outer = _trim(el.evaluate("e => e.outerHTML"), 600)
            except Exception as e:
                _write(lines, f"    [{i}] read error: {e}")
                continue
            _write(lines,
                   f"    [{i}] class={cls[:80]}",
                   f"        text: {txt}",
                   f"        outerHTML: {outer}".replace("\n", " "))

    # 3. Tab / accordion structure
    _write(lines, "", "--- tab / accordion structure ---")
    for sel in TAB_SELECTORS:
        try:
            els = page.query_selector_all(sel)
        except Exception as e:
            _write(lines, f"  {sel} → query error: {e}")
            continue
        if not els:
            continue
        _write(lines, f"  {sel} → {len(els)} match(es)")
        for i, el in enumerate(els[:8], 1):
            try:
                cls = el.get_attribute("class") or ""
                role = el.get_attribute("role") or ""
                aria_controls = el.get_attribute("aria-controls") or ""
                txt = _trim(el.inner_text(), 80)
            except Exception:
                continue
            _write(lines, f"    [{i}] role={role!r} aria-controls={aria_controls!r}",
                   f"        class={cls[:80]}",
                   f"        text: {txt}")

    # 4. Best-effort parsed key/value pairs from any <table>
    _write(lines, "", "--- parsed table key/value candidates (first 30) ---")
    try:
        tables = page.query_selector_all("table")
    except Exception:
        tables = []
    pair_count = 0
    for t_idx, t in enumerate(tables, 1):
        kvs = _parse_table_kv(page, t)
        if not kvs:
            continue
        cls = t.get_attribute("class") or "(no class)"
        _write(lines, f"  table[{t_idx}] class={cls[:80]} → {len(kvs)} candidate pairs:")
        for k, v in kvs[:30]:
            num, uom = _maybe_split_uom(v)
            uom_note = f" [uom={uom}]" if uom else ""
            _write(lines, f"    {k!r:40} → {num!r}{uom_note}")
            pair_count += 1
            if pair_count >= 30:
                break
        if pair_count >= 30:
            break

    # 5. Best-effort parsed key/value pairs from any <dl>
    _write(lines, "", "--- parsed <dl> key/value candidates ---")
    try:
        dls = page.query_selector_all("dl")
    except Exception:
        dls = []
    for d_idx, d in enumerate(dls, 1):
        kvs = _parse_dl_kv(d)
        if not kvs:
            continue
        cls = d.get_attribute("class") or "(no class)"
        _write(lines, f"  dl[{d_idx}] class={cls[:80]} → {len(kvs)} pairs:")
        for k, v in kvs[:20]:
            _write(lines, f"    {k!r:40} → {v!r}")

    # 6. Raw class-name index (legacy diagnostic, kept for reference)
    _write(lines, "", "--- candidate description/spec class names (regex on raw HTML) ---")
    classes = sorted(set(re.findall(
        r'class="([^"]*(?:description|product-desc|product-detail|features|specs|specifications|tabbed|attribute|property)[^"]*)"',
        html, re.I,
    )))
    for c in classes[:30]:
        _write(lines, f"  {c[:120]}")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sku", nargs="?", default="16063140",
                        help="SKU to autocomplete + visit (ignored if --slug is given)")
    parser.add_argument("--slug", default=None,
                        help="Skip autocomplete and visit /product/{slug} directly")
    args = parser.parse_args()

    stealth = Stealth()
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chromium",
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx_kwargs = dict(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}, locale="en-US",
        )
        if Path(STORAGE_STATE).exists():
            ctx_kwargs["storage_state"] = STORAGE_STATE
            print(f"loaded CF storage state from {STORAGE_STATE}")
        ctx = browser.new_context(**ctx_kwargs)
        stealth.apply_stealth_sync(ctx)
        page = ctx.new_page()
        page.goto("https://www.buyersproducts.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        print("HOME title:", page.title()[:80])
        if "Just a moment" in page.title():
            print("CF BLOCKED at homepage — aborting")
            browser.close()
            return 1

        slug = args.slug
        if not slug:
            try:
                with page.expect_response(
                    lambda r: f"/api/v2/search/autocomplete/{args.sku}/" in r.url and r.status == 200,
                    timeout=20000,
                ) as ri:
                    page.goto(f"https://www.buyersproducts.com/search?criteria={args.sku}",
                              wait_until="domcontentloaded", timeout=30000)
                data = ri.value.json()
            except Exception as e:
                print("autocomplete timeout:", e)
                browser.close()
                return 1
            items = data.get("products", []) or []
            print("autocomplete found:", len(items))
            if not items:
                browser.close()
                return 0
            slug = items[0].get("url") or ""
        print("slug:", slug)

        page.goto(f"https://www.buyersproducts.com/product/{slug}",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        print("PDP title:", page.title()[:120])
        html = page.content()
        print("HTML len:", len(html))
        Path(HTML_PATH).write_text(html, encoding="utf-8")
        print(f"dumped {HTML_PATH}")

        # Legacy image / pdf / video preview (kept for parity)
        print("--- product images (pimimages CDN):")
        imgs = sorted(set(re.findall(
            r'https?://pimimages\.buyersproducts\.com/products/[A-Z]+/[^"\'\s>]+\.(?:jpg|jpeg|png|webp)',
            html, re.I,
        )))
        for u in imgs[:12]:
            print(" ", u)
        print("--- pdf links:")
        pdfs = sorted(set(re.findall(r'https?://[^"\'\s>]+\.pdf', html, re.I)))
        for u in pdfs[:12]:
            print(" ", u)
        print("--- youtube/vimeo:")
        yt = sorted(set(re.findall(
            r'https?://(?:www\.)?(?:youtube\.com|youtu\.be|vimeo\.com)/[^"\'\s>]+',
            html,
        )))
        for u in yt[:8]:
            print(" ", u)
        m = re.search(
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{40,500})',
            html,
        )
        print("--- og:description:", (m.group(1)[:300] if m else "(none)"))

        # Full-page screenshot — visual record of what the viewer sees
        try:
            page.screenshot(path=SCREENSHOT_PATH, full_page=True)
            print(f"saved screenshot → {SCREENSHOT_PATH}")
        except Exception as e:
            print(f"(could not save screenshot: {e})")

        # Two-part report: visual layout (how it's presented) + categorization
        # (what selectors/DB shapes would extract it). Order matters — read
        # the visual layout first to understand the page, then the categorization
        # section tells you which selectors line up with which DB rows.
        report = visual_layout_dump(page) + "\n\n" + categorize_dump(page, html)
        Path(REPORT_PATH).write_text(report, encoding="utf-8")
        print(f"\nwrote categorization + layout report → {REPORT_PATH}")
        print(f"  (head -120 {REPORT_PATH} for a quick scan of the visual layout)")

        # Try to save fresh storage state back (in case CF refreshed cookies)
        try:
            ctx.storage_state(path=STORAGE_STATE)
            print(f"refreshed CF storage state → {STORAGE_STATE}")
        except Exception as e:
            print(f"(could not save storage state: {e})")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
