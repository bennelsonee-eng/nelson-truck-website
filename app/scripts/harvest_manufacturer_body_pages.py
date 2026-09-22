"""Fetch and parse the truck-body manufacturer model pages into JSON.

Reads the product -> model-page maps in discovery/manufacturer_data/, fetches
each distinct page (cached under html/, which is git-ignored), and writes
<brand>_parsed.json for import_manufacturer_body_content.py.

Pure read step: nothing touches the database.

Usage:
    python app/scripts/harvest_manufacturer_body_pages.py              # both brands
    python app/scripts/harvest_manufacturer_body_pages.py --refresh    # re-download HTML
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
from manufacturer_pages import PARSERS  # noqa: E402

DATA_DIR = HERE.parent.parent.parent / "discovery" / "manufacturer_data"
HTML_DIR = DATA_DIR / "html"
MAPS = {"knapheide": "kn_model_map.json", "cm": "cm_model_map.json", "rugby": "rugby_model_map.json",
        "duralift": "dal_model_map.json"}
BASES = {"knapheide": "https://www.knapheide.com", "cm": "https://cmtruckbeds.com", "rugby": "https://www.rugbymfg.com",
         "duralift": "https://dur-a-lift.com"}


def merge_models(parts: list[dict]) -> dict:
    """One product that covers several manufacturer models (Rugby's "Medium and
    Heavy Dump Bodies" = Eliminator Medium Duty + Titan + Contractor). Nothing is
    blended: each model keeps its own labelled features, options and spec table,
    so a buyer never reads one body's weight against another's length."""
    out = {"title": " / ".join(p["title"] for p in parts if p.get("title")),
           "intro": [f"{p['title']}: {p['intro'][0]}" for p in parts if p.get("intro")],
           "features": [], "options": [], "spec_kv": [], "spec_tables": [], "spec_note": None,
           "literature": [], "drawings": []}
    seen = set()
    for p in parts:
        name = p.get("title") or ""
        lines = [f["body"] for f in p["features"]]
        if lines:
            out["features"].append({"heading": name, "body": "\n".join(lines)})
        out["options"] += [{"name": f"{name}: {o['name']}", "description": o.get("description")} for o in p["options"]]
        if p["spec_kv"]:
            out["spec_tables"].append({"title": name, "headers": ["Specification", name],
                                       "rows": [{"type": "row", "cells": [k, v]} for k, v in p["spec_kv"]],
                                       "note": None})
        for lit in p["literature"]:
            if lit["url"] not in seen:
                seen.add(lit["url"])
                out["literature"].append(lit)
    return out
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")


def fetch(url: str, refresh: bool) -> str:
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    fp = HTML_DIR / (re.sub(r"[^a-z0-9]+", "_", url.split("//", 1)[1].lower()).strip("_") + ".html")
    if fp.exists() and not refresh:
        return fp.read_text(encoding="utf-8", errors="replace")
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90) as r:
                fp.write_bytes(r.read())
            return fp.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"could not fetch {url}: {last}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", choices=sorted(MAPS), action="append")
    ap.add_argument("--refresh", action="store_true", help="re-download cached HTML")
    args = ap.parse_args()
    for brand in args.brand or sorted(MAPS):
        pages = sorted(set(json.loads((DATA_DIR / MAPS[brand]).read_text(encoding="utf-8")).values()))
        parsed = {}
        for url in pages:
            # "url1 + url2 + url3" = one product covering several models
            parts = [PARSERS[brand](fetch(u.strip(), args.refresh), BASES[brand]) for u in url.split(" + ")]
            data = parts[0] if len(parts) == 1 else merge_models(parts)
            parsed[url] = data
            print(f"  [{brand}] {(data['title'] or '?')[:40]:<42} "
                  f"feat={len(data['features']):<3} opt={len(data['options']):<3} "
                  f"kv={len(data['spec_kv']):<3} tables={len(data['spec_tables'])} "
                  f"pdf={len(data['literature'])} drawings={len(data['drawings'])}")
        out = DATA_DIR / f"{brand}_parsed.json"
        out.write_text(json.dumps(parsed, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out.name}: {len(parsed)} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
