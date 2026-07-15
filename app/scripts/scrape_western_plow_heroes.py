"""Grab Western hero images per plow line from westernplows.com (the public
marketing site — no captcha needed).

Two passes:
  1. For each plow LINE slug (defender, pro-plow-3, mvp-3, ...) fetch the
     /products/<slug>/ page, regex out the hero image URL, download it.
  2. Map every Blade Assembly SKU captured by the Quick Match walker
     (western_app_guide.json) to a plow line slug via name matching on
     data_value (e.g. "9'6\" MVP 3™ (Mild Steel)" -> "mvp-3"), so the
     storefront kit-builder can look up sku -> hero image.

Output:
    refs/western_plow_heroes/<slug>.jpg
    refs/western_plow_heroes/_index.json
        [
          {
            "plow_line_slug": "defender",
            "plow_line_label": "DEFENDER",
            "hero_image_url": "https://westernplows.com/wp-content/uploads/...",
            "local_path": "refs/western_plow_heroes/defender.jpg",
            "skus": ["85270", "85275"],
            "sku_labels": {"85270": "6'8\\" Defender", ...},
          }, ...
        ]

Also grabs accessory page images for headlamps + controllers (the owner's
"2 headlight pics, 2-3 controller pics" requirement) via /accessories/.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
APP_GUIDE_JSON = REPO_ROOT / "app" / "data" / "wsm_export" / "western_app_guide.json"
OUT_ROOT = REPO_ROOT / "refs" / "western_plow_heroes"
OUT_ROOT.mkdir(parents=True, exist_ok=True)
INDEX_PATH = OUT_ROOT / "_index.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# Hand-curated overrides for plow lines where the page lacks a clear
# product-hero filename (the auto-regex picks up mega-menu images from
# the page header instead).  Sourced 2026-05-21 via vision-fetch.
HERO_OVERRIDES = {
    "prodigy":          "https://westernplows.com/wp-content/uploads/2021/05/PRODIGY_Winged_Plow_hero.jpeg",
    "pile-driver":      "https://westernplows.com/wp-content/uploads/2022/06/WSTRN_PILE-DRIVER.jpg",
    "pile-driver-xl":   "https://westernplows.com/wp-content/uploads/2024/05/PILE-DRIVER_final.png",
    "impact-vplow":     "https://westernplows.com/wp-content/uploads/2021/05/western-hd-vplow-impact-scaled.jpg",
    "wide-out-wide-out-xl": "https://westernplows.com/wp-content/uploads/2021/05/WSTRN_New-Wideout_WideoutXL_LED_2019_v0r1_1920x767_72.jpeg",
    "mvp-plus":         "https://westernplows.com/wp-content/uploads/2021/05/MVP_PLUS_V-Plow_hero.jpeg",
}

# Slugs sourced from westernplows.com mega-menu 2026-05-21.
PLOW_LINES = [
    ("defender", "DEFENDER"),
    ("hts", "HTS"),
    ("pro-plow-3", "PRO-PLOW 3"),
    ("pro-plus", "PRO PLUS"),
    ("pro-plus-hd", "PRO PLUS HD"),
    ("impact-md-utv", "IMPACT MD UTV"),
    ("impact-straightblade", "IMPACT Heavy-Duty Straight Blade"),
    ("impact-vplow", "IMPACT Heavy-Duty V-Plow"),
    ("enforcer", "ENFORCER"),
    ("mvp-plus", "MVP PLUS"),
    ("mvp-3", "MVP 3"),
    ("prodigy", "PRODIGY"),
    ("wide-out-wide-out-xl", "WIDE-OUT / WIDE-OUT XL"),
    ("pile-driver", "PILE DRIVER"),
    ("pile-driver-xl", "PILE DRIVER XL"),
    # Legacy plows likely captured by older-year walks:
    ("midweight", "MIDWEIGHT"),
    ("pro-plow-series-2", "PRO-PLOW Series 2"),
]


def http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_get_text(url: str) -> str:
    return http_get(url).decode("utf-8", errors="replace")


GENERIC_BRAND_FILES = (
    "WES-OG-Image", "western-og-image", "WES_OG_Image",
    "default", "placeholder",
)


def _is_generic(url: str) -> bool:
    return any(g.lower() in url.lower() for g in GENERIC_BRAND_FILES)


CROP_SUFFIX_RE = re.compile(r"-\d{2,4}x\d{2,4}(?=\.(?:jpe?g|png|webp))", re.IGNORECASE)


def _is_cropped(url: str) -> bool:
    return bool(CROP_SUFFIX_RE.search(url))


def _decrop(url: str) -> str:
    """Strip the WordPress -NNNxNNN crop suffix to get the original-size URL."""
    return CROP_SUFFIX_RE.sub("", url)


def find_hero_image(html: str, slug: str = "") -> str:
    """Return the best candidate hero image URL from a product page.

    Strategy: walk patterns in priority order, prefer ORIGINAL-resolution
    images (no -NNNxNNN crop suffix).  WordPress mega-menu thumbnails are
    cropped to 640x363 — those leak into every page header and were
    causing wrong heroes (e.g. MVP Plus picking up Pro Plus HD's nav
    thumbnail).  Skipping crop-suffixed URLs is the cleanest fix.
    """
    patterns = [
        # Strongest signal: filename literally calls itself a hero
        r'https://westernplows\.com/wp-content/uploads/[^"\'\s>]*?'
        r'(?:product[-_]?hero|HeroImage|_hero[_-]|-hero[_-]|hero\.jp|hero-image)'
        r'[^"\'\s>]*?\.(?:jpe?g|png|webp)',
        # Plow line slug appears in the filename
        rf'https://westernplows\.com/wp-content/uploads/[^"\'\s>]*?'
        rf'{re.escape(slug.replace("-", "[-_]?"))}'
        r'[^"\'\s>]*?\.(?:jpe?g|png|webp)' if slug else None,
        # Old "Front Nav" / "FrontStudio" / gallery markers
        r'https://westernplows\.com/wp-content/uploads/[^"\'\s>]*?'
        r'(?:ProductGalleryFront|GalleryFront|_Front_Nav|_FrontStudio|_scaled)'
        r'[^"\'\s>]*?\.(?:jpe?g|png|webp)',
    ]

    for pat in patterns:
        if not pat:
            continue
        # First pass: prefer ORIGINAL (no crop suffix) and non-mobile
        for m in re.finditer(pat, html, re.IGNORECASE):
            url = m.group(0)
            if _is_generic(url) or "mobile" in url.lower():
                continue
            if _is_cropped(url):
                continue
            return url
        # Second pass: cropped is OK if we can decrop to a real URL
        for m in re.finditer(pat, html, re.IGNORECASE):
            url = m.group(0)
            if _is_generic(url) or "mobile" in url.lower():
                continue
            if _is_cropped(url):
                return _decrop(url)
            return url

    # og:image fallback (sometimes a real product hero, sometimes generic)
    og = re.search(
        r'<meta\s+property="og:image"\s+content="(https://westernplows\.com/wp-content/uploads/[^"]+)"',
        html, re.IGNORECASE,
    )
    if og and not _is_generic(og.group(1)):
        return og.group(1)

    # Last fallback: first non-generic, non-cropped /wp-content/uploads/ image
    for m in re.finditer(
        r'https://westernplows\.com/wp-content/uploads/[^"\'\s>]+\.(?:jpe?g|png|webp)',
        html,
    ):
        url = m.group(0)
        if _is_generic(url) or _is_cropped(url) or "mobile" in url.lower():
            continue
        return url
    return ""


def slug_for_label(label: str) -> str | None:
    """Map a Blade Assembly data_value (e.g. "7'6\" PRO-PLOW® 3 (Stainless Steel)")
    to one of our known plow line slugs.  Returns slug or None."""
    s = re.sub(r"[^A-Z0-9 ]+", " ", (label or "").upper())
    s = re.sub(r"\s+", " ", s).strip()
    # Walk slugs in length-descending order so 'PRO PLUS HD' beats 'PRO PLUS'
    candidates = [
        ("PRO PLUS HD", "pro-plus-hd"),
        ("WIDE OUT XL", "wide-out-wide-out-xl"),
        ("WIDE OUT", "wide-out-wide-out-xl"),
        ("PRO PLOW 3", "pro-plow-3"),
        ("PRO PLOW SERIES 2", "pro-plow-series-2"),
        ("PRO PLOW", "pro-plow-3"),  # generic Pro-Plow falls to current generation
        ("PRO PLUS", "pro-plus"),
        ("MVP PLUS", "mvp-plus"),
        ("MVP 3", "mvp-3"),
        ("MVP", "mvp-plus"),
        ("MIDWEIGHT", "midweight"),
        ("PRODIGY", "prodigy"),
        ("DEFENDER", "defender"),
        ("ENFORCER", "enforcer"),
        ("HTS", "hts"),
        ("IMPACT V PLOW", "impact-vplow"),
        ("IMPACT", "impact-straightblade"),
        ("PILE DRIVER XL", "pile-driver-xl"),
        ("PILE DRIVER", "pile-driver"),
    ]
    for needle, slug in candidates:
        if needle in s:
            return slug
    return None


def collect_blade_skus() -> dict[str, list[tuple[str, str]]]:
    """{slug: [(sku, label), ...]} from the RAW JSONL (preserves mount_blade)."""
    raw_path = APP_GUIDE_JSON.parent / "western_app_guide_raw.jsonl"
    by_slug: dict[str, dict[str, str]] = defaultdict(dict)
    unmapped: list[tuple[str, str]] = []
    with raw_path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                meta = json.loads(line)
            except Exception:
                continue
            mb = meta.get("mount_blade") or {}
            sku = mb.get("sku") or ""
            label = mb.get("data_value") or ""
            if not sku:
                continue
            slug = slug_for_label(label)
            if slug:
                if sku not in by_slug[slug]:
                    by_slug[slug][sku] = label
            else:
                unmapped.append((sku, label))
    if unmapped:
        seen = set()
        for sku, lab in unmapped:
            if sku in seen:
                continue
            seen.add(sku)
            print(f"  WARN unmapped blade: {sku}  {lab!r}", flush=True)
    return {slug: sorted(items.items()) for slug, items in by_slug.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", default="",
                    help="comma-separated subset of plow line slugs")
    args = ap.parse_args()

    filter_slugs = {s.strip() for s in args.lines.split(",") if s.strip()}
    by_slug = collect_blade_skus()
    print(f"Blade SKUs grouped into {len(by_slug)} plow lines", flush=True)

    index: list[dict] = []
    for slug, label in PLOW_LINES:
        if filter_slugs and slug not in filter_slugs:
            continue
        product_url = f"https://westernplows.com/products/{slug}/"
        print(f"\n[{slug}] {product_url}", flush=True)
        try:
            html = http_get_text(product_url)
        except Exception as e:
            print(f"  page fetch failed: {e}", flush=True)
            continue
        if slug in HERO_OVERRIDES:
            hero_url = HERO_OVERRIDES[slug]
            print(f"  hero (override): {hero_url}", flush=True)
        else:
            hero_url = find_hero_image(html, slug)
        if not hero_url:
            print(f"  no hero image found in page", flush=True)
            continue
        print(f"  hero: {hero_url}", flush=True)

        ext = re.search(r"\.(jpe?g|png|webp)", hero_url, re.IGNORECASE)
        ext = ext.group(0).lower() if ext else ".jpg"
        local = OUT_ROOT / f"{slug}{ext}"
        try:
            data = http_get(hero_url, timeout=60)
            local.write_bytes(data)
            print(f"  saved {local.name} ({len(data)//1024} KB)", flush=True)
        except Exception as e:
            print(f"  download failed: {e}", flush=True)
            continue

        skus_for_line = by_slug.get(slug, [])
        entry = {
            "plow_line_slug": slug,
            "plow_line_label": label,
            "product_page_url": product_url,
            "hero_image_url": hero_url,
            "local_path": str(local.relative_to(REPO_ROOT)).replace("\\", "/"),
            "size_bytes": local.stat().st_size,
            "skus": [s for s, _ in skus_for_line],
            "sku_labels": {s: l for s, l in skus_for_line},
            "sku_count": len(skus_for_line),
        }
        index.append(entry)
        time.sleep(0.5)

    INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")
    have_hero = sum(1 for e in index if e.get("local_path"))
    total_skus = sum(e["sku_count"] for e in index)
    print(f"\n=== done.  {have_hero} plow lines, {total_skus} SKUs covered ===",
          flush=True)
    print(f"  index: {INDEX_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
