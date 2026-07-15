"""Scrape arbitrary Western document-library searches via CDP.

The document-library result table is JavaScript-rendered.  We attach to
the user's debug Chrome (port 9222), open the search URL in a NEW tab so
we don't clobber whatever is running in other tabs (e.g. the Quick Match
walker), click "Load More" until exhausted, then harvest every visible
result row + extract title / category / lit_no / year-ranges / make / PDF
href / preview image / detail href.

Designed to scrape mount-kit instructions filtered by make, but the URL
is configurable — the same script works for any doc-library search.

Examples:
    # Ford mount kit instructions (URL the owner shared on 2026-05-20)
    python -m app.scripts.scrape_western_doc_library \
        --url 'https://westernplows.com/document-library/search-results/?nhfzznev2izjx8qf6ubr=mpn8gmudl5hcb1yrclgk&LitModelYears=&LitVehicleMake=Ford&LitLanguage=EN' \
        --out-dir refs/western_doc_library/mount_kits_ford

    # Iterate every make for mount kits — drives the per-make URL
    python -m app.scripts.scrape_western_doc_library --all-makes-mount-kits

Output:
    <out_dir>/_index.json
    <out_dir>/<filename>.pdf
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import Response, sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = REPO_ROOT / "refs" / "western_doc_library"
CDP_URL = "http://localhost:9222"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# Doc-library makes shown in the Vehicle Make filter (per Western's UI as of 2026-05).
# Source: westernplows.com Quick Match makes for current year, minus low-volume
# brands we don't expect docs for.
ALL_TRUCK_MAKES = [
    "Chevy_GMC", "Dodge_Ram", "Ford", "Daihatsu", "Freightliner", "Hino",
    "International", "Isuzu", "Jeep", "Mack", "Mazda", "Mitsubishi_Fuso",
    "Nissan", "Sterling", "Toyota",
]

# Filter key for Mount Kit installation instructions (owner-supplied URL).
MOUNT_KITS_FILTER_KEY = "nhfzznev2izjx8qf6ubr=mpn8gmudl5hcb1yrclgk"


def safe_slug(s: str, maxlen: int = 80) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_").strip(".")
    return s[:maxlen]


def harvest_rows(page) -> list[dict]:
    """Pull every result row.  Try a few selectors and shapes."""
    return page.evaluate(
        """() => {
            const out = [];
            // Each result tile typically has a PDF link + descriptive text
            const tiles = document.querySelectorAll(
                'tr, .result-row, .doc-row, [class*="result"], '
                + '.document-result, .literature-result, .doc-item'
            );
            for (const row of tiles) {
                const a = row.querySelector('a[href$=".pdf"], a[href*=".pdf"], a[href*="cloudinary"]');
                if (!a) continue;
                const cells = Array.from(row.querySelectorAll('td, th, .cell, .col, p, span'))
                    .map(c => (c.textContent || '').trim())
                    .filter(t => t);
                const img = row.querySelector('img');
                out.push({
                    title: (a.textContent || '').trim() || cells.slice(0, 3).join(' | '),
                    href: a.href,
                    cells: cells.slice(0, 10),
                    image: img ? img.src : '',
                });
            }
            // Fallback: any anchor pointing to a PDF, paired with its parent's text
            if (out.length === 0) {
                for (const a of document.querySelectorAll('a[href$=".pdf"], a[href*=".pdf"]')) {
                    const par = a.closest('div, li, tr') || a.parentElement;
                    out.push({
                        title: (a.textContent || '').trim() || (par && par.textContent || '').trim().slice(0, 200),
                        href: a.href,
                        cells: [],
                        image: '',
                    });
                }
            }
            return out;
        }"""
    )


# Extractors for cell text → structured fields
PRODUCT_NAME_RE = re.compile(r"^([^#]+?)\s*(?:#|$)")
LIT_NO_RE = re.compile(r"\b(\d{4,6}(?:[-]\d)?)\b")
DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"
)
YEAR_RANGE_RE = re.compile(r"\b(\d{4})\s*[-–to]+\s*(\d{4}|present|_+|\s)?\b", re.I)


def normalize_row(raw: dict) -> dict:
    """Pull product_name / lit_no / date / year_range out of the row text."""
    title = (raw.get("title") or "").strip()
    cells = raw.get("cells") or []
    blob = "\n".join([title] + cells)

    # Strip leading numeric row index ("1\n", "23\n" etc.) and "Installation Instructions" line
    lines = [ln.strip() for ln in blob.split("\n") if ln.strip()]
    cleaned_lines = []
    for ln in lines:
        if ln.isdigit() and len(ln) <= 3:
            continue  # row counter
        if ln.lower() == "installation instructions":
            cleaned_lines.append(ln)
            continue
        cleaned_lines.append(ln)

    # Heuristic: product name = first non-numeric line; doc_type = "Installation Instructions"
    product_name = ""
    for ln in cleaned_lines:
        if ln.lower() != "installation instructions" and not DATE_RE.search(ln):
            product_name = ln
            break

    lit_m = LIT_NO_RE.search(blob)
    lit_no = lit_m.group(1) if lit_m else ""

    date_m = DATE_RE.search(blob)
    date = date_m.group(0) if date_m else ""

    year_m = YEAR_RANGE_RE.search(product_name)
    yr_start = int(year_m.group(1)) if year_m else None
    yr_end_raw = (year_m.group(2) or "").strip() if year_m else ""
    yr_end = int(yr_end_raw) if yr_end_raw.isdigit() else None

    return {
        "product_name": product_name,
        "lit_no": lit_no,
        "date": date,
        "year_start": yr_start,
        "year_end": yr_end,
        "url": raw.get("href", ""),
        "image": raw.get("image", ""),
        "raw_blob": "  ".join(cleaned_lines)[:400],
    }


def scrape_one_url(p, url: str, out_dir: Path, no_download: bool = False,
                   max_load_more: int = 30) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[doc-lib] {url}", flush=True)
    browser = p.chromium.connect_over_cdp(CDP_URL)
    if not browser.contexts:
        print("[doc-lib] no CDP context", flush=True)
        return []
    ctx = browser.contexts[0]
    page = ctx.new_page()  # always a fresh tab so we don't disrupt others

    captured_xhrs: list[dict] = []

    def on_response(resp: Response) -> None:
        try:
            host = resp.url.split("/", 3)[2]
        except Exception:
            return
        if "westernplows.com" not in host:
            return
        ct = (resp.headers or {}).get("content-type", "").lower()
        if "json" in ct or "/api/" in resp.url.lower() or "search" in resp.url.lower():
            try:
                body = resp.text()
            except Exception:
                body = "(no body)"
            captured_xhrs.append({
                "url": resp.url, "status": resp.status,
                "content_type": ct, "body": body[:200_000],
            })

    page.on("response", on_response)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    except Exception as e:
        print(f"[doc-lib] goto failed: {e}", flush=True)
    page.wait_for_timeout(6000)

    # Click Load More until exhausted
    for i in range(max_load_more):
        try:
            btn = page.locator("button:has-text('Load More'), a:has-text('Load More')").first
            if btn.count() == 0 or not btn.is_visible():
                print(f"[doc-lib] no more Load More after {i} clicks", flush=True)
                break
            btn.scroll_into_view_if_needed()
            btn.click()
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[doc-lib] Load More stopped: {e}", flush=True)
            break

    rows = harvest_rows(page)
    print(f"[doc-lib] harvested {len(rows)} rows", flush=True)

    # Dedup + normalize
    seen_urls = set()
    index: list[dict] = []
    for r in rows:
        h = r.get("href", "")
        if not h or h in seen_urls:
            continue
        seen_urls.add(h)
        entry = normalize_row(r)
        fname = h.rsplit("/", 1)[-1].split("?", 1)[0]
        fname = re.sub(r"[^A-Za-z0-9._-]+", "_", fname)
        if not fname.lower().endswith(".pdf"):
            fname += ".pdf"
        local = out_dir / fname
        entry["local_path"] = str(local.relative_to(REPO_ROOT)).replace("\\", "/")
        entry["downloaded"] = False
        entry["size"] = 0
        if not no_download and not local.exists():
            try:
                req = urllib.request.Request(h, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = resp.read()
                local.write_bytes(data)
                entry["downloaded"] = True
                entry["size"] = len(data)
                print(f"[doc-lib]   saved {fname} ({len(data)//1024} KB)", flush=True)
                time.sleep(0.3)
            except Exception as e:
                entry["error"] = repr(e)
                print(f"[doc-lib]   FAIL {h}: {e}", flush=True)
        else:
            entry["downloaded"] = local.exists()
            entry["size"] = local.stat().st_size if local.exists() else 0
        index.append(entry)

    # Save xhrs for debugging
    debug_dir = out_dir / "_debug"
    debug_dir.mkdir(exist_ok=True)
    (debug_dir / "captured_xhrs.jsonl").write_text(
        "\n".join(json.dumps(x) for x in captured_xhrs) + "\n",
        encoding="utf-8",
    )
    try:
        (debug_dir / "page.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(debug_dir / "page.png"), full_page=True)
    except Exception:
        pass

    try:
        page.close()
    except Exception:
        pass

    return index


def make_mount_kit_url(make: str) -> str:
    base = "https://westernplows.com/document-library/search-results/"
    q = {
        "nhfzznev2izjx8qf6ubr": "mpn8gmudl5hcb1yrclgk",
        "LitModelYears": "",
        "LitVehicleMake": make,
        "LitLanguage": "EN",
    }
    return f"{base}?{urllib.parse.urlencode(q, quote_via=urllib.parse.quote)}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="Specific search URL to scrape")
    ap.add_argument("--out-dir", help="Output directory (default uses URL/make)")
    ap.add_argument("--all-makes-mount-kits", action="store_true",
                    help="Loop ALL_TRUCK_MAKES and scrape Mount Kit installs per make")
    ap.add_argument("--no-download", action="store_true", help="Skip PDF downloads")
    args = ap.parse_args()

    with sync_playwright() as p:
        if args.all_makes_mount_kits:
            for make in ALL_TRUCK_MAKES:
                url = make_mount_kit_url(make)
                out = DEFAULT_OUT / f"mount_kits_{safe_slug(make.lower())}"
                index = scrape_one_url(p, url, out, args.no_download)
                (out / "_index.json").write_text(
                    json.dumps(index, indent=2), encoding="utf-8"
                )
                print(f"[doc-lib] {make}: {len(index)} docs -> {out / '_index.json'}",
                      flush=True)
        elif args.url:
            out = Path(args.out_dir) if args.out_dir else (DEFAULT_OUT / "custom")
            if not out.is_absolute():
                out = REPO_ROOT / out
            index = scrape_one_url(p, args.url, out, args.no_download)
            (out / "_index.json").write_text(
                json.dumps(index, indent=2), encoding="utf-8"
            )
            print(f"[doc-lib] {len(index)} docs -> {out / '_index.json'}", flush=True)
        else:
            ap.error("Pass --url or --all-makes-mount-kits")

    return 0


if __name__ == "__main__":
    sys.exit(main())
