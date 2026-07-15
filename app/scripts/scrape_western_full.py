"""Full content + media scrape of westernplows.com — every catalog plow.

User insight Apr 27 2026: "we should see if there is better data than what
we have on our website.  I would grab all of the content as well and all
of the pictures to bring into our website."

For each of the 6 Western catalog plows:
  1. Save raw HTML for archival / re-processing
  2. Extract structured data:
       - title (page <title>, h1)
       - meta description, OG image
       - body description / overview text (the "About" / hero copy)
       - feature bullets (the highlighted callouts)
       - spec table rows (blade height/width/weight/mount/hydraulics/etc.)
       - downloadable assets (PDF spec sheets, brochures)
       - YouTube / video embeds
  3. Save EVERY wp-content/uploads image referenced on the page,
     full-resolution (un-suffixed original, not the -640x360 / -1024 variants)
  4. Classify each image by filename heuristic:
       - hero / front / main view (best candidate for configurator)
       - lifestyle / scene shots
       - features cutaways / details
       - mount / harness / hardware
       - logos / icons (filtered out)

Output structure:
  app/backend/static/snow-plows/manufacturer_data/western/
    <plow_slug>/
      page.html                     # raw scrape
      data.json                     # structured extraction
      media/
        hero/<images>               # primary product views
        lifestyle/<images>          # in-action / context shots
        features/<images>           # detail / cutaway shots
        misc/<images>               # everything else

After this is done, a downstream wiring step picks the best hero image
per plow and runs rembg for transparent versions (the existing
fetch_western_plow_images.py does part of this — to be merged).

Usage:
    python -m app.scripts.scrape_western_full
    python -m app.scripts.scrape_western_full --plow pro-plus
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path


OUT_ROOT = (
    Path(__file__).resolve().parent.parent
    / "backend" / "static" / "snow-plows" / "manufacturer_data" / "western"
)

# Catalog plow_id -> westernplows.com /products/<slug>/
PLOW_SLUGS: dict[str, str] = {
    "pro-plus":            "western-pro-plus",
    "pro-plow-3":          "western-pro-plow-3",
    "mvp-3":               "western-mvp-3",
    "hts":                 "western-hts",
    "wide-out-wide-out-xl": "western-wideout",
    "defender":            "western-defender",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537"
THROTTLE_SEC = 0.5

# Heuristics for classifying image files by filename
HERO_KEYWORDS     = ("front", "hero", "studio", "_LED", "ProductImage", "_Nav")
LIFESTYLE_KEYWORDS = ("lifestyle", "scene", "snow", "truck", "application", "in-action", "in_action")
FEATURE_KEYWORDS  = ("cutaway", "detail", "edge", "moldboard", "mount", "harness", "control", "wing")
LOGO_KEYWORDS     = ("logo", "icon", "badge", "favicon", "sprite")


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def http_get_text(url: str) -> str:
    return http_get(url).decode("utf-8", errors="replace")


def extract_image_urls(page_html: str, base_url: str = "https://westernplows.com") -> list[str]:
    """Pull every wp-content/uploads asset referenced on the page.  Returns
    full URLs to ORIGINAL (un-suffixed) versions only."""
    found: set[str] = set()
    for m in re.finditer(r'(?:src|data-src|content|href)\s*=\s*["\'][^"\']*?(/wp-content/uploads/[^"\'?\s]+\.(jpe?g|png|webp))', page_html, flags=re.I):
        path = m.group(1)
        # Strip WordPress's resize suffix to get the original
        clean = re.sub(r"-\d{2,4}x\d{2,4}(?=\.(jpe?g|png|webp))", "", path, flags=re.I)
        full = base_url + clean
        found.add(full)
    return sorted(found)


def extract_pdfs(page_html: str, base_url: str = "https://westernplows.com") -> list[str]:
    found: set[str] = set()
    for m in re.finditer(r'href\s*=\s*["\']([^"\']+\.pdf)["\']', page_html, flags=re.I):
        href = m.group(1)
        if href.startswith("//"):
            href = "https:" + href
        elif href.startswith("/"):
            href = base_url + href
        elif not href.startswith("http"):
            continue
        found.add(href)
    return sorted(found)


def extract_videos(page_html: str) -> list[str]:
    found: set[str] = set()
    for pat in [
        r'(https?://(?:www\.)?youtube\.com/(?:watch\?v=|embed/)[A-Za-z0-9_-]+)',
        r'(https?://youtu\.be/[A-Za-z0-9_-]+)',
        r'(https?://player\.vimeo\.com/video/\d+)',
    ]:
        for m in re.finditer(pat, page_html):
            found.add(m.group(1))
    return sorted(found)


def strip_tags(s: str) -> str:
    s = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", "", s, flags=re.I | re.S)
    s = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", "", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_meta(page_html: str) -> dict:
    meta = {}
    m = re.search(r"<title>([^<]+)</title>", page_html, flags=re.I)
    if m:
        meta["title"] = html.unescape(m.group(1)).strip()
    for prop in ["og:title", "og:description", "og:image", "description"]:
        m = re.search(
            rf'<meta\s+(?:name|property)\s*=\s*["\']({re.escape(prop)})["\']\s+content\s*=\s*["\']([^"\']+)',
            page_html, flags=re.I,
        )
        if m:
            meta[m.group(1).replace(":", "_")] = html.unescape(m.group(2))
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page_html, flags=re.I | re.S)
    if h1:
        meta["h1"] = strip_tags(h1.group(1))
    return meta


def extract_body_paragraphs(page_html: str, max_paragraphs: int = 30) -> list[str]:
    """Grab the long-form description copy.  Western uses standard <p> tags
    inside the post-content area."""
    paragraphs = []
    # Confine to the main content region if we can find it
    main = re.search(
        r'<(?:main|article|div)[^>]*\bclass\s*=\s*["\'][^"\']*(?:entry-content|post-content|main-content|content-area|elementor-widget-container|product-content)[^"\']*["\'][^>]*>(.*?)</(?:main|article|div)>',
        page_html, flags=re.I | re.S,
    )
    body = main.group(1) if main else page_html
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", body, flags=re.I | re.S):
        text = strip_tags(m.group(1))
        if 40 <= len(text) <= 800 and not text.startswith("Copyright"):
            paragraphs.append(text)
        if len(paragraphs) >= max_paragraphs:
            break
    return paragraphs


def extract_bullets(page_html: str) -> list[str]:
    """Pull <li> items that look like real feature bullets."""
    bullets: list[str] = []
    for m in re.finditer(r"<li[^>]*>(.*?)</li>", page_html, flags=re.I | re.S):
        text = strip_tags(m.group(1))
        if 10 <= len(text) <= 240 and not any(skip in text.lower() for skip in
            ("home", "products", "blog", "dealer locator", "contact us", "©", "copyright",
             "privacy", "terms", "cookie", "menu", "search", "login", "site map")):
            bullets.append(text)
    # Dedupe preserving order
    seen = set()
    out = []
    for b in bullets:
        if b not in seen:
            seen.add(b)
            out.append(b)
    return out[:80]


def extract_spec_table(page_html: str) -> dict[str, str]:
    """Best-effort extract of a key/value spec table.  Western product pages
    tend to use either an HTML <table> or a definition list <dl>."""
    specs: dict[str, str] = {}
    # <table> rows
    for m in re.finditer(
        r"<tr[^>]*>\s*<t[hd][^>]*>(.*?)</t[hd]>\s*<t[hd][^>]*>(.*?)</t[hd]>\s*</tr>",
        page_html, flags=re.I | re.S,
    ):
        k = strip_tags(m.group(1))
        v = strip_tags(m.group(2))
        if k and v and len(k) < 80:
            specs[k] = v
    # <dl><dt>k</dt><dd>v</dd>
    for m in re.finditer(
        r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>",
        page_html, flags=re.I | re.S,
    ):
        k = strip_tags(m.group(1))
        v = strip_tags(m.group(2))
        if k and v and len(k) < 80:
            specs[k] = v
    return specs


def classify_image(filename: str) -> str:
    f = filename.lower()
    if any(k.lower() in f for k in LOGO_KEYWORDS):
        return "_skip"
    if any(k.lower() in f for k in HERO_KEYWORDS):
        return "hero"
    if any(k.lower() in f for k in LIFESTYLE_KEYWORDS):
        return "lifestyle"
    if any(k.lower() in f for k in FEATURE_KEYWORDS):
        return "features"
    return "misc"


def process_plow(slug: str, plow_id: str, dry_run: bool) -> dict:
    url = f"https://westernplows.com/products/{slug}/"
    print(f"\n[{plow_id}]  {url}")
    plow_dir = OUT_ROOT / slug
    media_dir = plow_dir / "media"
    if not dry_run:
        plow_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("hero", "lifestyle", "features", "misc"):
            (media_dir / sub).mkdir(parents=True, exist_ok=True)

    # Fetch page
    try:
        page = http_get_text(url)
    except Exception as e:
        return {"plow_id": plow_id, "ok": False, "error": f"fetch failed: {e}"}

    if not dry_run:
        (plow_dir / "page.html").write_text(page, encoding="utf-8")

    # Extract structured content
    meta = extract_meta(page)
    paragraphs = extract_body_paragraphs(page)
    bullets = extract_bullets(page)
    specs = extract_spec_table(page)
    images = extract_image_urls(page)
    pdfs = extract_pdfs(page)
    videos = extract_videos(page)

    print(f"  meta: title={meta.get('title','')[:60]!r}")
    print(f"  paragraphs: {len(paragraphs)}, bullets: {len(bullets)}, specs: {len(specs)}")
    print(f"  images: {len(images)}, pdfs: {len(pdfs)}, videos: {len(videos)}")

    # Download images
    image_records = []
    for img_url in images:
        filename = img_url.rsplit("/", 1)[-1]
        bucket = classify_image(filename)
        if bucket == "_skip":
            continue
        dest = media_dir / bucket / filename
        rec = {
            "url": img_url,
            "filename": filename,
            "bucket": bucket,
            "saved_to": str(dest.relative_to(OUT_ROOT.parent.parent.parent.parent)) if not dry_run else None,
            "size": 0,
            "error": None,
        }
        if dry_run:
            image_records.append(rec)
            continue
        if dest.exists() and dest.stat().st_size > 0:
            rec["size"] = dest.stat().st_size
            image_records.append(rec)
            continue
        try:
            time.sleep(THROTTLE_SEC)
            data = http_get(img_url)
            dest.write_bytes(data)
            rec["size"] = len(data)
        except Exception as e:
            rec["error"] = str(e)
        image_records.append(rec)

    by_bucket = {}
    for r in image_records:
        by_bucket.setdefault(r["bucket"], 0)
        if not r.get("error"):
            by_bucket[r["bucket"]] += 1
    print(f"  saved by bucket: {by_bucket}")

    data = {
        "plow_id": plow_id,
        "western_slug": slug,
        "source_url": url,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "meta": meta,
        "description_paragraphs": paragraphs,
        "feature_bullets": bullets,
        "specs": specs,
        "images": image_records,
        "pdf_assets": pdfs,
        "videos": videos,
    }
    if not dry_run:
        (plow_dir / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"plow_id": plow_id, "ok": True, "by_bucket": by_bucket, "data": data}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plow", help="Single Western slug (e.g. pro-plus)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    targets = (
        {args.plow: PLOW_SLUGS[args.plow]} if args.plow else PLOW_SLUGS
    )
    if args.plow and args.plow not in PLOW_SLUGS:
        print(f"Unknown slug: {args.plow}")
        return 2

    print(f"Output root: {OUT_ROOT}")
    print(f"Targets: {len(targets)} plow(s)")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")

    results = [process_plow(slug, pid, args.dry_run) for slug, pid in targets.items()]
    print()
    print("=== SUMMARY ===")
    for r in results:
        if r["ok"]:
            print(f"  OK   {r['plow_id']:<22s}  bucket counts: {r['by_bucket']}")
        else:
            print(f"  FAIL {r['plow_id']:<22s}  {r.get('error')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
