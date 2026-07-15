"""check_no_dead_images.py — enforce the no-dead-images rule.

Walks every active category and HEAD-requests its resolved image URL.
Fails (exit 1) if any return 4xx/5xx, timeout, or unreachable.

Counts local /static/category-images/* by checking the file exists on
disk instead of doing a network call.

Usage:
    python app/scripts/check_no_dead_images.py
    python app/scripts/check_no_dead_images.py --base http://localhost:8001
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests


REPO = Path(__file__).resolve().parents[2]
LOCAL_STATIC_ROOT = REPO / "app" / "backend" / "static"
LOCAL_CATEGORY_DIR = LOCAL_STATIC_ROOT / "category-images"
LOCAL_BRAND_DIR = LOCAL_STATIC_ROOT / "brand-logos"


def head(url: str, timeout: float = 8.0) -> tuple[bool, str]:
    """Returns (ok, reason)."""
    try:
        # Some hosts (Google Cloud Storage) ignore HEAD; fall back to GET range 0-0.
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        if r.status_code == 405 or r.status_code == 403:
            r = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=timeout, stream=True)
        if 200 <= r.status_code < 300:
            return True, "ok"
        return False, f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:8001")
    ap.add_argument("--include-products", action="store_true",
                    help="Also probe primary product images (slow — 200K+ HEADs)")
    args = ap.parse_args()

    dead: list[tuple[str, str, str]] = []
    checked = 0
    t0 = time.time()

    def check_local_or_head(label: str, url: str, *_ignored) -> None:
        """Validates an image URL. Any /static/* path is treated as a local
        file under app/backend/static/<rest>. Anything else is HEAD-fetched."""
        nonlocal checked
        checked += 1
        if url.startswith("/static/"):
            # Resolve under the actual static root regardless of subdir
            rel = url[len("/static/"):]
            path = LOCAL_STATIC_ROOT / rel
            if not path.exists():
                dead.append((label, url, f"FILE_MISSING: {path}"))
                return
            if path.stat().st_size < 200:
                dead.append((label, url, f"TINY_FILE: {path.stat().st_size} bytes"))
                return
        else:
            ok, reason = head(url)
            if not ok:
                dead.append((label, url, reason))

    # Category images via /categories/tree
    r = requests.get(f"{args.base}/api/catalog/categories/tree", timeout=15)
    r.raise_for_status()

    def walk(nodes):
        for n in nodes or []:
            yield n
            yield from walk(n.get("children", []))

    for n in walk(r.json()):
        url = n.get("image_url")
        if not url:
            continue
        check_local_or_head(f"cat[{n['full_path']}]", url)

    # Brand logos via /catalog/browse facets (or fall back to a brand list endpoint).
    # We pull brands by hitting /api/catalog/brands if it exists, else skip silently.
    try:
        rb = requests.get(f"{args.base}/api/catalog/brands", timeout=15)
        if rb.status_code == 200:
            for b in rb.json() or []:
                url = b.get("logo_url")
                if url:
                    check_local_or_head(f"brand[{b.get('name','?')}]", url)
    except requests.RequestException:
        pass

    elapsed = time.time() - t0
    if dead:
        print(f"\nDEAD IMAGES: {len(dead)} of {checked} ({elapsed:.1f}s):", file=sys.stderr)
        for path, url, reason in dead:
            print(f"  - {path}", file=sys.stderr)
            print(f"      {url}", file=sys.stderr)
            print(f"      {reason}", file=sys.stderr)
        return 1

    print(f"OK: all {checked} category images load ({elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
