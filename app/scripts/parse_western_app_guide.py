"""Parse the per-combo summary HTMLs scraped by scrape_western_app_guide.py
into a clean JSON suitable for downstream import into vehicle_application +
plow_application_part.

Reads:
  app/data/wsm_export/western_app_guide_raw.jsonl
  app/data/wsm_export/_western_summaries/*.html

Writes:
  app/data/wsm_export/western_app_guide.json
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_ROOT = REPO_ROOT / "app" / "data" / "wsm_export"
RAW_JSONL = OUT_ROOT / "western_app_guide_raw.jsonl"
OUT_JSON = OUT_ROOT / "western_app_guide.json"


# ---- HTML parsing ----------------------------------------------------------

# Find each plowLineItem section.  We process them one at a time to keep the
# regex bounded — the original DOTALL regex jumped across sections when a row
# had multiple SKU strongs (e.g. Mount Kit listing alternates).
LINEITEM_SPLIT_RE = re.compile(
    r'<div class="plowLineItem(?:\s+print-plowCompName)?\s+row">',
)
SECTION_RE = re.compile(
    r'<strong><span class="[^"]*">([^<:]+?):?\s*</span></strong>',
    re.DOTALL,
)
# Inside a single plowLineItem we look for the FIRST <p>description</p> and
# the FIRST <strong>#SKU</strong> that follows it.
DESC_SKU_RE = re.compile(
    r'<p>([^<]*)</p>\s*<strong>#([A-Za-z0-9\-./_]+)</strong>',
    re.DOTALL,
)
# Some plowLineItem rows wrap their description in extra spans.  Fallback
# regex that walks all #SKU strongs inside the block.
ANY_SKU_RE = re.compile(r'<strong>#([A-Za-z0-9\-./_]+)</strong>')

# Selection summary text (year/make/model + refinements)
SUMMARY_TEXT_RE = re.compile(
    r'Truck,\s*(\d{4}),\s*([^,]+?),\s*([^.<]+?)\.<br><br>'
    r'The vehicle has a (.*?)\.</?(?:span|p|/)',
    re.DOTALL,
)

# Required ballast
BALLAST_RE = re.compile(
    r'required ballast is\s*<?[^>]*?>?(\d+)\s*lbs', re.IGNORECASE
)

# Year range pulled out of mount/harness description text
# Matches: "(2017-2024)", "2021-__", "(2008-2016)", "(2023-____)", "(2024-)",
#   "(2008–16)", "(1999–10)"  (2-digit end years, en-dash U+2013),
#   "(2019__ )"  (missing dash before underscores)
YEAR_RANGE_RE = re.compile(
    r'(?:\()?(\d{4})\s*[-–—]?\s*(\d{4}|\d{2}(?!\d)|_+|present)(?:\s*\))?',
    re.IGNORECASE,
)

# Notes Summary: pdf links for mount-kit parts list / install instructions
NOTES_PDF_RE = re.compile(
    r'(Mount kit (?:parts list|Install Instructions))\.\s*'
    r'<a[^>]*href="([^"]+\.pdf)"',
    re.IGNORECASE,
)


def decode(s: str) -> str:
    return html_lib.unescape(s or "").strip()


def parse_year_range(description: str) -> dict | None:
    """Pull (year_start, year_end_or_None) from a description like
    'Personal Plow Mount Ford Bronco (2021-__ )' or
    'Truck Harness Kit - 12 pin 2021-__ CHEVY/GMC 1500'.
    Handles 2-digit end years: '(2008–16)' → 2008-2016, '(1999–10)' → 1999-2010."""
    m = YEAR_RANGE_RE.search(description or "")
    if not m:
        return None
    start = int(m.group(1))
    end_raw = (m.group(2) or "").strip()
    if not end_raw or "_" in end_raw or "present" in end_raw.lower():
        end = None
    elif end_raw.isdigit():
        end = int(end_raw)
        # Expand 2-digit year: use start's century, bump century if end < start's decade
        if end < 100:
            century = (start // 100) * 100
            end = century + end
            if end < start:
                end += 100  # e.g. start=1999, raw=10 → 2010
    else:
        end = None
    if not (1970 <= start <= 2030):
        return None
    return {"start": start, "end": end}


def parse_summary_html(html: str) -> dict:
    """Extract the BOM + metadata from one summary page.

    Summary pages render the BOM 3 times (desktop, mobile collapse, print).
    We process the FIRST occurrence per (section, sku) pair to avoid
    triplicate components.  Each plowLineItem div contains exactly one
    section heading, one description <p>, and one or more SKU strongs
    (multi-SKU is normal for Mount Kit alternates).
    """
    components: list[dict] = []
    seen: set[tuple[str, str]] = set()

    # Split HTML into per-plowLineItem chunks.  The first split fragment
    # is everything before the first plowLineItem — discard it.
    chunks = LINEITEM_SPLIT_RE.split(html)
    for chunk in chunks[1:]:
        sec_m = SECTION_RE.search(chunk)
        if not sec_m:
            continue
        section = decode(sec_m.group(1))
        # Try the canonical pattern first
        pair = DESC_SKU_RE.search(chunk)
        if pair:
            descr = decode(pair.group(1))
            sku = decode(pair.group(2))
        else:
            # Fallback: pick the first SKU strong inside this chunk
            sku_m = ANY_SKU_RE.search(chunk)
            if not sku_m:
                continue
            sku = decode(sku_m.group(1))
            descr = ""
        if not sku:
            continue
        key = (section, sku)
        if key in seen:
            continue
        seen.add(key)
        comp = {"section": section, "sku": sku, "description": descr}
        yr = parse_year_range(descr)
        if yr:
            comp["year_range"] = yr
        components.append(comp)

    # Selection summary
    sel_m = SUMMARY_TEXT_RE.search(html)
    sel = {}
    if sel_m:
        sel = {
            "year": int(sel_m.group(1)),
            "make": decode(sel_m.group(2)),
            "model": decode(sel_m.group(3)),
            "refinement_text": decode(sel_m.group(4)),
        }

    # Ballast
    b_m = BALLAST_RE.search(html)
    ballast_lbs = int(b_m.group(1)) if b_m else None

    # Notes PDFs
    notes_pdfs = []
    for nm in NOTES_PDF_RE.finditer(html):
        notes_pdfs.append({"label": decode(nm.group(1)), "url": decode(nm.group(2))})

    return {
        "components": components,
        "selection": sel,
        "ballast_lbs": ballast_lbs,
        "notes_pdfs": notes_pdfs,
    }


# ---- Section -> role mapping ----------------------------------------------

SECTION_TO_ROLE = {
    "blade assembly": "blade",
    "attachment": "blade_attachment",
    "mount kit": "mount",
    "headlight harness": "harness",
    "headlamp kit": "headlamps",
    "handheld control": "control",
    "joystick control": "control",
    "isolation module": "isolation_module",
}


def role_for(section: str) -> str:
    return SECTION_TO_ROLE.get((section or "").strip().lower(), section.lower().replace(" ", "_"))


# ---- Driver ---------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-jsonl", default=str(RAW_JSONL))
    ap.add_argument("--out-json", default=str(OUT_JSON))
    args = ap.parse_args()

    raw_path = Path(args.raw_jsonl)
    out_path = Path(args.out_json)

    if not raw_path.exists():
        print(f"raw file not found: {raw_path}", file=sys.stderr)
        return 1

    rows: list[dict] = []
    raw_count = 0
    skipped = 0
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw_count += 1
        try:
            meta = json.loads(line)
        except Exception:
            skipped += 1
            continue
        html_path = REPO_ROOT / meta["summary_html_path"]
        if not html_path.exists():
            skipped += 1
            continue
        try:
            html = html_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            skipped += 1
            continue
        parsed = parse_summary_html(html)
        if not parsed["components"]:
            # No BOM rows means parser missed structure or summary was empty
            skipped += 1
            continue

        # Index components by role for convenience
        by_role: dict[str, dict] = {}
        for c in parsed["components"]:
            r = role_for(c["section"])
            # Take first occurrence per role; rest go into 'other'
            if r not in by_role:
                by_role[r] = c

        rows.append({
            "key": meta["key"],
            "year": meta["year"],
            "make": meta["make"],
            "model": meta["model"],
            "mount_blade_label": meta.get("mount_blade", {}).get("data_value", ""),
            "mount_blade_sku": meta.get("mount_blade", {}).get("sku", ""),
            "headlamp_type": meta.get("headlamp_type", ""),
            "step2_refinements": meta.get("step2_refinements", {}),
            "ballast_lbs": parsed["ballast_lbs"],
            "selection": parsed["selection"],
            "components": parsed["components"],
            "by_role": by_role,
            "notes_pdfs": parsed["notes_pdfs"],
            "mount_sku": by_role.get("mount", {}).get("sku", ""),
            "mount_description": by_role.get("mount", {}).get("description", ""),
            "mount_year_range": by_role.get("mount", {}).get("year_range"),
            "harness_sku": by_role.get("harness", {}).get("sku", ""),
            "harness_description": by_role.get("harness", {}).get("description", ""),
            "harness_year_range": by_role.get("harness", {}).get("year_range"),
            "blade_sku": by_role.get("blade", {}).get("sku", ""),
            "blade_description": by_role.get("blade", {}).get("description", ""),
            "control_sku": by_role.get("control", {}).get("sku", ""),
            "isolation_module_sku": by_role.get("isolation_module", {}).get("sku", ""),
            "headlamps_sku": by_role.get("headlamps", {}).get("sku", ""),
            "summary_html_path": meta["summary_html_path"],
        })

    # Stable sort: year DESC then make / model
    rows.sort(key=lambda r: (-r["year"], r["make"], r["model"],
                              r["mount_blade_sku"], r["headlamp_type"]))

    out = {
        "metadata": {
            "source": "https://resources.westernplows.com/quick-match/plow/",
            "raw_rows": raw_count,
            "parsed_rows": len(rows),
            "skipped": skipped,
            "anchor_years": sorted({r["year"] for r in rows}),
            "makes": sorted({r["make"] for r in rows}),
            "models_count": len({(r["make"], r["model"]) for r in rows}),
        },
        "rows": rows,
    }
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {out_path}", flush=True)
    print(f"  raw_rows={raw_count}  parsed={len(rows)}  skipped={skipped}", flush=True)
    print(f"  anchor_years={out['metadata']['anchor_years']}", flush=True)
    print(f"  makes={out['metadata']['makes']}", flush=True)
    print(f"  unique (make,model)={out['metadata']['models_count']}", flush=True)

    # Print a sample row for sanity
    if rows:
        sample = rows[0]
        print(f"\n  sample row:", flush=True)
        print(f"    {sample['year']} {sample['make']} {sample['model']}", flush=True)
        print(f"    mount: {sample['mount_sku']!r} '{sample['mount_description']}' "
              f"yr={sample['mount_year_range']}", flush=True)
        print(f"    harness ({sample['headlamp_type']}): {sample['harness_sku']!r} "
              f"'{sample['harness_description']}' yr={sample['harness_year_range']}",
              flush=True)
        print(f"    blade: {sample['blade_sku']!r}  ballast: {sample['ballast_lbs']} lbs",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
