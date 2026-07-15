"""Stitch the scraped manufacturer_data/ dumps into a single Python content
module that snow_plow_catalog.py can load at import time.

Reads:
    backend/static/snow-plows/manufacturer_data/{western,meyer,snowdogg}/<plow>/data.json
Writes:
    backend/app/services/snow_plow_manufacturer_content.py

Output module exposes MANUFACTURER_CONTENT: dict[plow_id, ContentBlock]:
    {
        "<catalog_plow_id>": {
            "manufacturer": "Western Products",
            "product_name": "PRO PLUS",
            "tagline": "Heavy-Duty Commercial Snow Plow",
            "source_url": "https://...",
            "pdf_spec_sheet": "https://...",
            "videos": [...],
            "description": "Cleaned 1-2 paragraph overview...",
            "key_features": ["...", "...", ...],
            "manufacturer_specs": {"Plow Type": "V-Plow", ...},
            "spec_variants": [   # for Meyer's per-blade-size detail
                {
                    "model_number": "09402",
                    "label": "8'6\" Lot Pro",
                    "fields": {"Moldboard Length": "8'6\" 259 cm", ...}
                },
                ...
            ],
        }
    }

Re-run after any new manufacturer scrape to refresh the catalog.

Usage:
    python -m app.scripts.build_manufacturer_content
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DATA_ROOT = SCRIPT_DIR.parent / "backend" / "static" / "snow-plows" / "manufacturer_data"
OUT_FILE = SCRIPT_DIR.parent / "backend" / "app" / "services" / "snow_plow_manufacturer_content.py"

# Catalog plow_id -> (manufacturer, scraped_dir_name) tuple
WESTERN_MAP = {
    "western-defender":   "defender",
    "western-hts":        "hts",
    "western-mvp-3":      "mvp-3",
    "western-pro-plow-3": "pro-plow-3",
    "western-pro-plus":   "pro-plus",
    "western-wideout":    "wide-out-wide-out-xl",
}
MEYER_MAP = {
    "meyer-drive-pro":  "drive-pro-homeowner",
    "meyer-ez-plus":    "diamond-edge-(1)",        # rebranded
    "meyer-lot-pro":    "lot-pro-(1)",
    "meyer-super-v2":   "super-v3-(1)",            # current = V3
    "meyer-xls":        "super-blade",             # closest current model
}

# SnowDogg comes from the consolidated _all_plows.json
SNOWDOGG_CATALOG_MAP = {
    "snowdogg-md-series":  "snowdogg-mdii",
    "snowdogg-ex-series":  "snowdogg-exii",
    "snowdogg-vx-series":  "snowdogg-vmxii",
    "snowdogg-vxf-series": "snowdogg-vxfii",
    "snowdogg-xp-series":  "snowdogg-xpii",
}

WESTERN_TAGLINES = {
    "western-defender":   "Right-sized contractor blade for mid-size pickups",
    "western-hts":        "Half-Ton Straight Blade",
    "western-mvp-3":      "Versatile V-Plow with Center-link Strength",
    "western-pro-plow-3": "Mid-weight commercial straight-blade",
    "western-pro-plus":   "Heavy-Duty Commercial Snow Plow",
    "western-wideout":    "Adjustable Winged Blade for Open Lots",
}


def clean_para(p: str) -> str:
    """Tighten whitespace and strip noise."""
    p = re.sub(r"\s+", " ", p).strip()
    return p


def is_garbage_para(p: str) -> bool:
    pl = p.lower()
    bads = (
        "search literature", "enter a keyword", "cookies", "privacy policy",
        "document library", "quick match", "warranty & registration",
        "about our company", "parts finder", "resource articles",
        "flatbed", "side-by-side", "online ordering", "added to wish list",
        "your session has expired", "double click to toggle",
    )
    return any(b in pl for b in bads)


def is_useful_bullet(b: str) -> bool:
    bl = b.lower()
    bads = (
        "home", "snow plow", "salt spreader", "configure", "about us",
        "dealer locator", "support", "contact", "legal", "press",
        "privacy", "warranty", "news & blog", "menu", "search", "cart",
        "items in cart", "employment", "registration", "distributor",
        "find your part", "plow configuration", "financing", "sourcewell",
        "walk behinds", "tailgates", "insert spreaders", "dump trucks",
        "english", "español", "new products", "owner's manual",
        "have the lot pro", "accessories",
    )
    return not any(bl == b or bl.startswith(b + " ") or b in bl for b in bads)


def extract_western(plow_id: str, slug: str) -> dict[str, Any]:
    p = DATA_ROOT / "western" / slug / "data.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    block: dict[str, Any] = {
        "manufacturer": "Western Products",
        "product_name": (d.get("meta", {}).get("h1") or "").replace("®", "").strip(),
        "tagline": WESTERN_TAGLINES.get(plow_id, ""),
        "source_url": d.get("source_url"),
        "pdf_spec_sheet": d.get("pdf_assets", [None])[0] if d.get("pdf_assets") else None,
        "videos": d.get("videos", []),
        "description": "",   # Western copy didn't survive paragraph filtering
        "key_features": [],
        "manufacturer_specs": dict(d.get("specs") or {}),
        "spec_variants": [],
    }
    return block


def extract_meyer(plow_id: str, slug: str) -> dict[str, Any]:
    p = DATA_ROOT / "meyer" / slug / "data.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    paras = [clean_para(x) for x in d.get("description_paragraphs", []) if not is_garbage_para(x)]
    paras = [p for p in paras if 100 <= len(p) <= 700]
    bullets = [clean_para(b) for b in d.get("feature_bullets", []) if is_useful_bullet(b)]
    bullets = [b for b in bullets if 10 <= len(b) <= 200]

    # Take 2 best paragraphs (longest non-redundant)
    seen, top_paras = set(), []
    for para in sorted(paras, key=lambda x: -len(x)):
        sig = para[:80]
        if sig in seen:
            continue
        seen.add(sig)
        top_paras.append(para)
        if len(top_paras) >= 2:
            break

    # Per-SKU spec variants
    variants = []
    for v in d.get("spec_variants", []):
        fields = v.get("fields") or {}
        clean_fields: dict[str, str] = {}
        # Meyer's table parsing duplicated keys; the clean way: take the
        # last/most-specific value when duplicated.  Just keep all.
        for k, val in fields.items():
            if k.endswith(":"):
                k = k[:-1]
            clean_fields[k.strip()] = clean_para(val)
        if not clean_fields:
            continue
        variants.append({
            "model_number": v.get("model_number") or fields.get("Part #:"),
            "fields": clean_fields,
        })

    block: dict[str, Any] = {
        "manufacturer": "Meyer Products",
        "product_name": (d.get("meta", {}).get("h1") or slug).strip(),
        "tagline": "",  # Meyer puts the tagline in a separate "subtitle" we didn't capture
        "source_url": d.get("source_url"),
        "pdf_spec_sheet": d.get("pdf_assets", [None])[0] if d.get("pdf_assets") else None,
        "videos": d.get("videos", []),
        "description": " ".join(top_paras)[:1200] if top_paras else "",
        "key_features": bullets[:8],
        "manufacturer_specs": {},
        "spec_variants": variants,
    }
    return block


def extract_snowdogg(plow_id: str, slug: str, all_plows: dict) -> dict[str, Any]:
    info = all_plows.get(slug, {})
    if not info:
        return {}
    return {
        "manufacturer": "SnowDogg (Buyers Products)",
        "product_name": info.get("title", "").replace("SnowDogg®", "").replace("with RapidLink™", "").strip(" |"),
        "tagline": "",
        "source_url": f"https://www.buyersproducts.com/product/{slug}",
        "pdf_spec_sheet": None,
        "videos": [],
        "description": "",
        "key_features": [],
        "manufacturer_specs": dict(info.get("specs") or {}),
        "spec_variants": [],
        "vehicle_class": info.get("vehicle_class", ""),
    }


def main() -> int:
    content: dict[str, dict] = {}

    for plow_id, slug in WESTERN_MAP.items():
        block = extract_western(plow_id, slug)
        if block:
            content[plow_id] = block
            print(f"  western {plow_id}: {len(block.get('manufacturer_specs', {}))} specs")

    for plow_id, slug in MEYER_MAP.items():
        block = extract_meyer(plow_id, slug)
        if block:
            content[plow_id] = block
            print(f"  meyer   {plow_id}: {len(block.get('spec_variants', []))} variants, "
                  f"{len(block.get('description', ''))}c desc, "
                  f"{len(block.get('key_features', []))} features")

    snowdogg_root = DATA_ROOT / "snowdogg" / "_all_plows.json"
    if snowdogg_root.exists():
        all_plows = json.loads(snowdogg_root.read_text(encoding="utf-8")).get("plows", {})
        for plow_id, slug in SNOWDOGG_CATALOG_MAP.items():
            block = extract_snowdogg(plow_id, slug, all_plows)
            if block:
                content[plow_id] = block
                print(f"  snowdogg {plow_id}: {len(block.get('manufacturer_specs', {}))} specs")

    print(f"\nWriting {OUT_FILE}")
    print(f"  Total entries: {len(content)}")

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Use pprint for valid Python literals (None / True / False) instead of
    # json.dumps which emits null/true/false (JSON-only).
    import pprint
    body = pprint.pformat(content, indent=2, width=110, sort_dicts=False)
    OUT_FILE.write_text(
        '"""Manufacturer content scraped from Western/Meyer/SnowDogg sites.\n\n'
        "Auto-generated by app/scripts/build_manufacturer_content.py — re-run\n"
        "any time the manufacturer_data/ scrapes are refreshed.  Do not edit by\n"
        'hand; changes will be overwritten.\n"""\n\n'
        "from __future__ import annotations\n\n"
        "MANUFACTURER_CONTENT: dict[str, dict] = " + body + "\n",
        encoding="utf-8",
    )
    print(f"  Wrote {OUT_FILE.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
