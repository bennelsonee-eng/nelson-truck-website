"""Re-parse refs/western_doc_library/*/_index.json with cleaner field
extraction.  The original scraper conflated year-in-product-name with the
literature number; this pulls them apart and adds:

  mount_kit_sku   — the part number after "#"  (e.g. "31283", "33284", "31271-1")
  doc_type        — "Installation Instructions" | "Parts List"
  lit_no          — the document literature number (4-6 digits, NOT a year)
  legacy          — true if "Legacy" present in the row
  year_start/end  — parsed from "(2017-__)", "2019-23", "(2020-23)" etc.

Also dedups per (mount_kit_sku, doc_type) so we get one row per actual
mount kit + doc type.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOC_LIB_ROOT = REPO_ROOT / "refs" / "western_doc_library"


SKU_RE = re.compile(r"#\s*([A-Z0-9][A-Z0-9\-./]{2,20})")
DOC_TYPE_RE = re.compile(
    r"\b(Installation Instructions|Parts List|Operating Instructions|"
    r"Mechanic's Guide|Service Bulletin|Safety Data Sheet|Brochure|Poster)\b",
    re.I,
)
DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2},?\s+\d{4}"
)
# A lit_no is a 5-6 digit number adjacent to the doc-type / date.  Build a
# regex against the cleaned blob that picks numbers between doc-type and date.
LIT_NO_NEAR_DOCTYPE_RE = re.compile(
    r"(?:Installation Instructions|Parts List|Operating Instructions|"
    r"Mechanic's Guide|Brochure|Poster)\s+(\d{4,6})\b",
    re.I,
)
LEGACY_RE = re.compile(r"\bLegacy\b", re.I)
# Year ranges: "2019-23", "(2017-__)", "(2020-__)", "2008-15", "2024-__ "
YEAR_RANGE_RE = re.compile(
    r"\(?\s*(\d{4})\s*[-–to]+\s*((?:\d{2,4}|_+|present|\s)?)\s*\)?",
    re.IGNORECASE,
)


def parse_year_range(text: str) -> dict:
    m = YEAR_RANGE_RE.search(text or "")
    if not m:
        return {"start": None, "end": None}
    start = int(m.group(1))
    if not (1970 <= start <= 2030):
        return {"start": None, "end": None}
    end_raw = (m.group(2) or "").strip()
    end = None
    if end_raw.isdigit():
        if len(end_raw) == 2:
            # Expand 2-digit year using start's century
            century = (start // 100) * 100
            end = century + int(end_raw)
        else:
            end = int(end_raw)
        if not (1970 <= end <= 2030):
            end = None
    return {"start": start, "end": end}


def normalize(entry: dict) -> dict:
    raw = entry.get("raw_blob") or ""
    name = entry.get("product_name") or ""

    sku_m = SKU_RE.search(raw)
    mount_sku = sku_m.group(1) if sku_m else ""

    doc_m = DOC_TYPE_RE.search(raw)
    doc_type = doc_m.group(1).title() if doc_m else ""

    lit_m = LIT_NO_NEAR_DOCTYPE_RE.search(raw)
    lit_no = lit_m.group(1) if lit_m else ""

    legacy = bool(LEGACY_RE.search(raw))
    date_m = DATE_RE.search(raw)
    date = date_m.group(0) if date_m else entry.get("date", "")

    yr = parse_year_range(name)

    return {
        "product_name": name,
        "mount_kit_sku": mount_sku,
        "doc_type": doc_type or "Installation Instructions",
        "lit_no": lit_no,
        "legacy": legacy,
        "year_start": yr["start"],
        "year_end": yr["end"],
        "date": date,
        "url": entry.get("url", ""),
        "image": entry.get("image", ""),
        "local_path": entry.get("local_path", ""),
        "size": entry.get("size", 0),
        "downloaded": entry.get("downloaded", False),
    }


def process_index(index_path: Path) -> None:
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    # Skip if already cleaned — entries lose raw_blob after first pass.
    if raw and "mount_kit_sku" in raw[0] and "raw_blob" not in raw[0]:
        have_sku = sum(1 for e in raw if e.get("mount_kit_sku"))
        have_year = sum(1 for e in raw if e.get("year_start"))
        print(f"  {index_path.relative_to(REPO_ROOT)}: already cleaned "
              f"({len(raw)} rows, sku={have_sku}, year={have_year}) — skip",
              flush=True)
        return
    cleaned = [normalize(e) for e in raw]

    # Dedup by (mount_kit_sku, doc_type) — keep latest by date if duplicate
    by_key: dict[tuple, dict] = {}
    for e in cleaned:
        key = (e["mount_kit_sku"], e["doc_type"])
        cur = by_key.get(key)
        if cur is None or e.get("date", "") > cur.get("date", ""):
            by_key[key] = e
    deduped = list(by_key.values())
    deduped.sort(key=lambda e: (e["mount_kit_sku"], e["doc_type"]))

    index_path.write_text(json.dumps(deduped, indent=2), encoding="utf-8")
    print(f"  {index_path.relative_to(REPO_ROOT)}: "
          f"raw={len(raw)} cleaned={len(deduped)}", flush=True)

    # Quick stats
    have_sku = sum(1 for e in deduped if e["mount_kit_sku"])
    have_year = sum(1 for e in deduped if e["year_start"])
    print(f"    with mount_kit_sku: {have_sku}/{len(deduped)}  "
          f"with year_start: {have_year}/{len(deduped)}", flush=True)


def main() -> int:
    found = 0
    for idx in DOC_LIB_ROOT.rglob("_index.json"):
        process_index(idx)
        found += 1
    if found == 0:
        print(f"No _index.json files found under {DOC_LIB_ROOT}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
