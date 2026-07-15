"""Scrape every Poster (LitDocType=P) from westernplows.com/document-library.

The search result table is rendered by JS, so we attach to the user's
existing debug Chrome over CDP (port 9222), open the search URL in a new
tab, wait for the table to populate, click "Load More" until exhausted,
then harvest every poster row.

Outputs:
  refs/western_posters/_index.json   — {title, url, lit_no, date, local_path}
  refs/western_posters/<filename>.pdf

Prereq: chrome.exe is running with --remote-debugging-port=9222.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Response, sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = REPO_ROOT / "refs" / "western_posters"
OUT_DIR.mkdir(parents=True, exist_ok=True)
INDEX_PATH = OUT_DIR / "_index.json"

CDP_URL = "http://localhost:9222"
SEARCH_URL = (
    "https://westernplows.com/document-library/search-results/"
    "?LitDocType=P&LitLanguage=EN"
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


def harvest_rows(page) -> list[dict]:
    """Pull every visible result row from the table.  Try a few selectors —
    we don't know the exact markup until we see it."""
    return page.evaluate(
        """() => {
            const out = [];
            const rows = document.querySelectorAll('tr, .result-row, .doc-row, [class*="result"], [class*="row"]');
            for (const row of rows) {
                const a = row.querySelector('a[href$=".pdf"], a[href*="cloudinary"], a[href*=".pdf"]');
                if (!a) continue;
                const cells = Array.from(row.querySelectorAll('td, th, .cell'))
                    .map(c => (c.textContent || '').trim());
                out.push({
                    title: (a.textContent || '').trim() || cells.join(' | '),
                    href: a.href,
                    cells,
                });
            }
            // Fallback: ANY <a href="*.pdf"> on the page
            if (out.length === 0) {
                for (const a of document.querySelectorAll('a[href$=".pdf"], a[href*=".pdf"]')) {
                    out.push({
                        title: (a.textContent || '').trim(),
                        href: a.href,
                        cells: [],
                    });
                }
            }
            return out;
        }"""
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true",
                    help="Capture the index but skip PDF downloads")
    ap.add_argument("--max-load-more", type=int, default=20,
                    help="Click Load More up to this many times")
    args = ap.parse_args()

    captured_xhrs: list[dict] = []

    with sync_playwright() as p:
        print(f"[posters] connecting to {CDP_URL}", flush=True)
        browser = p.chromium.connect_over_cdp(CDP_URL)
        if not browser.contexts:
            print("[posters] no browser contexts via CDP", flush=True)
            return 2
        ctx = browser.contexts[0]
        page = ctx.new_page()

        def on_response(resp: Response) -> None:
            url = resp.url
            host = url.split("/", 3)[2] if "://" in url else ""
            if "westernplows.com" not in host:
                return
            ct = (resp.headers or {}).get("content-type", "").lower()
            if "json" in ct or "/api/" in url.lower() or "search" in url.lower():
                try:
                    body = resp.text()
                except Exception:
                    body = "(failed to read)"
                captured_xhrs.append({
                    "url": url, "status": resp.status, "content_type": ct,
                    "body": body[:200_000],
                })

        page.on("response", on_response)

        print(f"[posters] opening {SEARCH_URL}", flush=True)
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(5000)

        # Click "Load More" until it disappears or we hit the cap
        for i in range(args.max_load_more):
            try:
                btn = page.locator("button:has-text('Load More'), a:has-text('Load More')").first
                if btn.count() == 0 or not btn.is_visible():
                    print(f"[posters] no Load More button after {i} clicks", flush=True)
                    break
                btn.scroll_into_view_if_needed()
                btn.click()
                print(f"[posters] clicked Load More x{i+1}", flush=True)
                page.wait_for_timeout(2500)
            except Exception as e:
                print(f"[posters] Load More stopped at iter {i}: {e}", flush=True)
                break

        rows = harvest_rows(page)
        print(f"[posters] harvested {len(rows)} rows", flush=True)

        # Dump raw HTML for debugging
        debug_dir = OUT_DIR / "_debug"
        debug_dir.mkdir(exist_ok=True)
        (debug_dir / "results_page.html").write_text(page.content(), encoding="utf-8")
        (debug_dir / "captured_xhrs.jsonl").write_text(
            "\n".join(json.dumps(x) for x in captured_xhrs) + "\n",
            encoding="utf-8",
        )
        try:
            page.screenshot(path=str(debug_dir / "results_page.png"), full_page=True)
        except Exception:
            pass

        # Dedup
        seen = set()
        unique = []
        for r in rows:
            h = r.get("href", "")
            if not h or h in seen:
                continue
            seen.add(h)
            unique.append(r)
        print(f"[posters] unique poster URLs: {len(unique)}", flush=True)

        index = []
        for r in unique:
            url = r["href"]
            fname = url.rsplit("/", 1)[-1].split("?", 1)[0]
            fname = re.sub(r"[^A-Za-z0-9._-]+", "_", fname)
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
            local = OUT_DIR / fname
            entry = {
                "title": r.get("title", "") or fname,
                "url": url,
                "cells": r.get("cells", []),
                "local_path": str(local.relative_to(REPO_ROOT)).replace("\\", "/"),
                "downloaded": False,
                "size": 0,
            }
            if not args.no_download:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        data = resp.read()
                    local.write_bytes(data)
                    entry["downloaded"] = True
                    entry["size"] = len(data)
                    print(f"[posters] saved {fname} ({len(data)//1024} KB)", flush=True)
                    time.sleep(0.4)  # polite throttle
                except Exception as e:
                    entry["error"] = repr(e)
                    print(f"[posters] DOWNLOAD FAIL {url}: {e}", flush=True)
            index.append(entry)

        INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")
        print(f"[posters] index -> {INDEX_PATH}", flush=True)

        try:
            page.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
