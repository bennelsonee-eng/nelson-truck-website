"""Full content + media scrape of meyerproducts.com snow plows.

Mirror of scrape_western_full.py but adapted for Meyer's structure:
  - Detail pages are SSR'd at /snow-plows/contractor-truck-plows/<slug>
  - Spec data is RICHER than Western (per-SKU model #s + dims + weights)
  - Hero images are LIFESTYLE shots (truck + snow scenes), NOT clean studio
  - BUT every plow has an Object2VR widget with 400 pre-rendered studio
    frames hidden behind the "View in 3D" button.  The 360-frame library
    is at:
        /CMSTemplates/MeyerProducts/o2vr-360/<o2vr_name>/page/images/
            img_0_<vert>_<tilt>.jpg     (vert,tilt 0-19, 521x521)
    Front view = img_0_10_0.jpg.  The o2vr_name is found in the page HTML
    as data-o2vr-name="..." on .product-o2vr-modal-button.

For each catalog Meyer plow, this script:
  1. Fetch the SSR'd HTML
  2. Extract:
       - title / meta
       - description paragraphs
       - feature bullets
       - per-SKU spec tables (model # + moldboard dims + weight + cutting edge)
       - PDFs / videos
       - o2vr_name + lifestyle-thumb image refs
  3. Download the o2vr front frame (img_0_10_0.jpg) AND 7 more rotation
     samples (every other column) into a /360/ folder for the future
     gallery feature
  4. Run rembg isnet on the front frame
  5. Save manufacturer_data/meyer/<slug>/data.json + media/

Usage:
    python -m app.scripts.scrape_meyer_full
    python -m app.scripts.scrape_meyer_full --plow lot-pro-(1)
    python -m app.scripts.scrape_meyer_full --no-images   # data-only pass
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image
from rembg import new_session, remove


OUT_ROOT = (
    Path(__file__).resolve().parent.parent
    / "backend" / "static" / "snow-plows" / "manufacturer_data" / "meyer"
)
SKUS_ROOT = (
    Path(__file__).resolve().parent.parent
    / "backend" / "static" / "snow-plows" / "skus"
)

# Catalog plow_id -> Meyer URL slug under /snow-plows/contractor-truck-plows/
# Plus optional list of Titan stockids these images should propagate to.
MEYER_PLOWS: dict[str, dict] = {
    # Direct catalog matches
    "lot-pro-(1)": {
        "catalog_id": "meyer-lot-pro",
        "skus": [
            "MYP:09402-EQP", "MYP:09401-EQP", "MYP:09403-EQP", "MYP:09400-EQP",
            "MYP:09405-EQP", "MYP:09406-EQP", "MYP:09407-EQP", "MYP:09404-EQP",
            "MYP:09275-EQP",
        ],
    },
    "lot-pro-ld-(1)": {"catalog_id": None, "skus": []},   # extra, no catalog match yet
    "super-v3-(1)": {
        # Replaces our older catalog "Super V2" mapping
        "catalog_id": "meyer-super-v2",
        "skus": ["MYP:09446-EQP", "MYP:09447-EQP", "MYP:09494-EQP", "MYP:09495-EQP"],
    },
    "super-v-ld-(1)": {"catalog_id": None, "skus": []},
    "drive-pro-homeowner": {
        "catalog_id": "meyer-drive-pro",
        "skus": ["MYP:09499-EQP", "MYP:09507-EQP", "MYP:09473-EQP", "MYP:09472-EQP"],
        # Override: the Drive Pro page references the Lot Pro card before its
        # own o2vr trigger, so the data-o2vr-name regex picks up "lotpro" first.
        # Force the correct slug.
        "o2vr_override": "drivepro",
    },
    "super-blade": {
        # Best current match for the discontinued XLS / Wingman catalog entry
        "catalog_id": "meyer-xls",
        "skus": ["MYP:09478-EQP"],
    },
    "diamond-edge-(1)": {
        # Replaces discontinued EZ Plus catalog entry
        "catalog_id": "meyer-ez-plus",
        "skus": ["MYP:84352-EQP", "MYP:84351-EQP", "MYP:84350-EQP", "MYP:84353-EQP"],
    },
    "road-pro-32-series": {"catalog_id": None, "skus": []},
    "road-pro-36-series": {"catalog_id": None, "skus": []},
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537"
THROTTLE_SEC = 0.5
BASE_URL = "https://www.meyerproducts.com"
O2VR_ROOT = "/CMSTemplates/MeyerProducts/o2vr-360"
# Indices to grab: column 10 = front view, plus 7 other angles spaced 45° apart
# for the future configurator-style gallery.
FRONT_FRAME = (0, 10, 0)              # img_0_10_0.jpg
GALLERY_FRAMES = [
    (0, 0,  0),  # rear
    (0, 2,  0),  # rear-left 3/4
    (0, 5,  0),  # left side
    (0, 7,  0),  # front-left 3/4
    (0, 10, 0),  # front (= FRONT_FRAME)
    (0, 12, 0),  # front-right 3/4
    (0, 15, 0),  # right side
    (0, 17, 0),  # rear-right 3/4
]


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def http_get_text(url: str) -> str:
    return http_get(url).decode("utf-8", errors="replace")


def strip_tags(s: str) -> str:
    s = re.sub(r"<script\b[^<]*(?:(?!</script>)<[^<]*)*</script>", "", s, flags=re.I | re.S)
    s = re.sub(r"<style\b[^<]*(?:(?!</style>)<[^<]*)*</style>", "", s, flags=re.I | re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_meta(page: str) -> dict:
    meta: dict = {}
    m = re.search(r"<title>([^<]+)</title>", page, flags=re.I)
    if m:
        meta["title"] = html.unescape(m.group(1)).strip()
    for prop in ["og:title", "og:description", "og:image", "description"]:
        m = re.search(
            rf'<meta\s+(?:name|property)\s*=\s*["\']({re.escape(prop)})["\']\s+content\s*=\s*["\']([^"\']+)',
            page, flags=re.I,
        )
        if m:
            meta[m.group(1).replace(":", "_")] = html.unescape(m.group(2))
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, flags=re.I | re.S)
    if h1:
        meta["h1"] = strip_tags(h1.group(1))
    return meta


def extract_o2vr_name(page: str) -> str | None:
    m = re.search(r'data-o2vr-name=["\']([^"\']+)', page, flags=re.I)
    return m.group(1) if m else None


def extract_paragraphs(page: str) -> list[str]:
    """Pull description paragraphs.  Meyer wraps real product copy in
    <p class="..."> tags inside .product-overview / section regions.  Filter
    out site-chrome boilerplate (privacy, search prompts, etc.)."""
    out = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", page, flags=re.I | re.S):
        text = strip_tags(m.group(1))
        if 40 <= len(text) <= 1000 and not any(s in text.lower() for s in
            ("copyright", "all rights reserved", "search literature",
             "enter a keyword", "please enter", "you must enter",
             "online ordering")):
            out.append(text)
    # Dedupe preserving order
    seen, dedup = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            dedup.append(t)
    return dedup[:40]


def extract_bullets(page: str) -> list[str]:
    out = []
    for m in re.finditer(r"<li[^>]*>(.*?)</li>", page, flags=re.I | re.S):
        text = strip_tags(m.group(1))
        if 10 <= len(text) <= 240 and not any(s in text.lower() for s in
            ("home", "snow plows", "salt spreaders", "parts &", "configure",
             "about us", "dealer locator", "support", "contact", "legal",
             "press", "privacy", "warranty", "news & blog", "menu", "search",
             "cart", "items in cart", "employment", "product registration",
             "distributor sign in", "find your part", "plow configuration",
             "financing", "sourcewell", "walk behinds", "tailgates",
             "insert spreaders", "dump trucks", "english", "español")):
            out.append(text)
    seen, dedup = set(), []
    for b in out:
        if b not in seen:
            seen.add(b)
            dedup.append(b)
    return dedup[:80]


def extract_specs(page: str) -> list[dict]:
    """Meyer detail pages have a SPECS section with one accordion per SKU
    variant (8'6" Lot Pro, 7'6" Lot Pro, etc).  Each contains a <table> with
    Part #, Blade Type, Moldboard Length/Height/Gauge, Cutting Edge, etc.

    Return a list of {variant_name, model_number, fields: {key: value}} dicts.
    """
    variants = []
    # Split page on listitem boundaries — each variant is a list item with
    # an h3/h4 heading + table.
    # Simpler approach: find each <table> and walk back to find the nearest
    # heading (variant name).  For now, just dump all tables with their rows.
    for tm in re.finditer(r"<table[^>]*>(.*?)</table>", page, flags=re.I | re.S):
        rows = {}
        for rm in re.finditer(
            r"<t[hd][^>]*>(.*?)</t[hd]>\s*<t[hd][^>]*>(.*?)</t[hd]>",
            tm.group(1), flags=re.I | re.S,
        ):
            k = strip_tags(rm.group(1))
            v = strip_tags(rm.group(2))
            if k and v and len(k) < 80:
                rows[k] = v
        if rows:
            # Try to extract a model #/part #
            model_no = rows.get("Part #:") or rows.get("Part #") or rows.get("Model")
            variants.append({"model_number": model_no, "fields": rows})
    return variants


def extract_pdfs(page: str) -> list[str]:
    out = set()
    for m in re.finditer(r'href\s*=\s*["\']([^"\']+\.pdf)["\']', page, flags=re.I):
        href = m.group(1)
        if href.startswith("/"):
            href = BASE_URL + href
        elif not href.startswith("http"):
            continue
        out.add(href)
    return sorted(out)


def extract_videos(page: str) -> list[str]:
    out = set()
    for pat in [
        r'(https?://(?:www\.)?youtube\.com/(?:watch\?v=|embed/)[A-Za-z0-9_-]+)',
        r'(https?://youtu\.be/[A-Za-z0-9_-]+)',
    ]:
        for m in re.finditer(pat, page):
            out.add(m.group(1))
    return sorted(out)


def extract_inline_image_refs(page: str) -> list[str]:
    """Pull every MeyerMediaLibrary image referenced on the page (full-res
    base path; resize suffixes stripped where present)."""
    out = set()
    for m in re.finditer(
        r'(?:src|href)\s*=\s*["\'](/MeyerProducts/media/MeyerMediaLibrary/[^"\']+\.(jpe?g|png|webp))',
        page, flags=re.I,
    ):
        path = m.group(1)
        out.add(BASE_URL + path)
    return sorted(out)


def fetch_o2vr_frames(o2vr_name: str, dest_dir: Path, dry_run: bool) -> list[dict]:
    """Download the gallery rotation set for a plow's o2vr."""
    out = []
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
    for (i, j, k) in GALLERY_FRAMES:
        url = f"{BASE_URL}{O2VR_ROOT}/{o2vr_name}/page/images/img_{i}_{j}_{k}.jpg"
        rec = {"index": (i, j, k), "url": url, "size": 0, "error": None}
        if dry_run:
            out.append(rec)
            continue
        try:
            time.sleep(THROTTLE_SEC)
            data = http_get(url)
            (dest_dir / f"img_{i}_{j}_{k}.jpg").write_bytes(data)
            rec["size"] = len(data)
        except Exception as e:
            rec["error"] = str(e)
        out.append(rec)
    return out


def process_plow(slug: str, info: dict, session, args) -> dict:
    url = f"{BASE_URL}/snow-plows/contractor-truck-plows/{slug}"
    print(f"\n[{slug}]  {url}")
    plow_dir = OUT_ROOT / slug
    if not args.dry_run:
        plow_dir.mkdir(parents=True, exist_ok=True)

    try:
        page = http_get_text(url)
    except Exception as e:
        return {"slug": slug, "ok": False, "error": f"fetch failed: {e}"}

    if not args.dry_run:
        (plow_dir / "page.html").write_text(page, encoding="utf-8")

    meta = extract_meta(page)
    o2vr_name = info.get("o2vr_override") or extract_o2vr_name(page)
    paragraphs = extract_paragraphs(page)
    bullets = extract_bullets(page)
    specs = extract_specs(page)
    pdfs = extract_pdfs(page)
    videos = extract_videos(page)
    inline_imgs = extract_inline_image_refs(page)

    print(f"  o2vr_name: {o2vr_name}")
    print(f"  meta title: {meta.get('title','')[:60]!r}")
    print(f"  paragraphs: {len(paragraphs)}, bullets: {len(bullets)}, "
          f"spec variants: {len(specs)}")
    print(f"  inline images: {len(inline_imgs)}, pdfs: {len(pdfs)}, videos: {len(videos)}")

    # Download o2vr gallery frames
    frame_records = []
    front_path = None
    if o2vr_name and not args.no_images:
        frame_dir = plow_dir / "360"
        frame_records = fetch_o2vr_frames(o2vr_name, frame_dir, args.dry_run)
        good = [f for f in frame_records if not f["error"]]
        print(f"  o2vr frames: {len(good)}/{len(frame_records)} downloaded")
        if not args.dry_run:
            front_path = frame_dir / f"img_{FRONT_FRAME[0]}_{FRONT_FRAME[1]}_{FRONT_FRAME[2]}.jpg"
            if not front_path.exists():
                front_path = None

    # rembg the front frame + push to SKU folders
    sku_results = []
    if front_path and front_path.exists() and not args.no_images:
        print(f"  running rembg isnet on front frame...")
        t0 = time.time()
        img = Image.open(front_path).convert("RGB")
        transparent = remove(
            img, session=session,
            alpha_matting=True,
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=20,
            alpha_matting_erode_size=10,
        )
        print(f"    isnet: {time.time() - t0:.1f}s")
        # Save the front transparent + raw to plow_dir/media/
        media_hero = plow_dir / "media" / "hero"
        media_hero.mkdir(parents=True, exist_ok=True)
        transparent.save(media_hero / "front_transparent.png", "PNG")
        img.save(media_hero / "front_manufacturer.jpg", "JPEG", quality=92)
        # Replicate to each catalog SKU folder
        for sku in info.get("skus", []):
            sku_dir = SKUS_ROOT / sku.replace(":", "-")
            sku_dir.mkdir(parents=True, exist_ok=True)
            transparent.save(sku_dir / "hero_transparent.png", "PNG")
            img.save(sku_dir / "hero_manufacturer.jpg", "JPEG", quality=92)
            sku_results.append(sku)
        print(f"  wrote {len(sku_results)} SKU folder(s)")

    data = {
        "slug": slug,
        "catalog_id": info.get("catalog_id"),
        "source_url": url,
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "meta": meta,
        "o2vr_name": o2vr_name,
        "description_paragraphs": paragraphs,
        "feature_bullets": bullets,
        "spec_variants": specs,
        "pdf_assets": pdfs,
        "videos": videos,
        "inline_image_refs": inline_imgs,
        "o2vr_frames_downloaded": frame_records,
        "skus_written": sku_results,
    }
    if not args.dry_run:
        (plow_dir / "data.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
    return {"slug": slug, "ok": True, "stats": {
        "specs": len(specs), "paragraphs": len(paragraphs), "bullets": len(bullets),
        "o2vr_frames": sum(1 for f in frame_records if not f["error"]),
        "skus_written": len(sku_results),
    }}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plow", help="Single Meyer slug")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-images", action="store_true",
                   help="Skip image downloads / rembg (data-only pass)")
    args = p.parse_args(argv)

    targets = (
        {args.plow: MEYER_PLOWS[args.plow]} if args.plow else MEYER_PLOWS
    )
    if args.plow and args.plow not in MEYER_PLOWS:
        print(f"Unknown slug: {args.plow}")
        return 2

    print(f"Targets: {len(targets)} plow(s)")
    print(f"Mode: {'DRY' if args.dry_run else 'LIVE'} "
          f"{'(no images)' if args.no_images else ''}")

    session = None
    if not args.no_images and not args.dry_run:
        print("Loading rembg isnet session...")
        session = new_session("isnet-general-use")
        print("Ready.\n")

    results = [process_plow(s, info, session, args) for s, info in targets.items()]
    print()
    print("=== SUMMARY ===")
    for r in results:
        if r["ok"]:
            print(f"  OK   {r['slug']:<25s}  {r.get('stats')}")
        else:
            print(f"  FAIL {r['slug']:<25s}  {r.get('error')}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
