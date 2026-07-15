"""Normalize the messy multi-line titles in refs/western_posters/_index.json.

Each raw title is the textContent of the result-table row.  Extract:
  product_name   — "Tornado", "Striker (0.35 & 0.7 cu yd)", "MVP 3", ...
  doc_type       — "Poster"
  lit_no         — "96341"
  date           — "February 15, 2023"
  legacy         — true if "Legacy" appears in the row
  related_parts  — list of part #s after "/"  (e.g., ["98805", "98810"])
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
INDEX_PATH = REPO_ROOT / "refs" / "western_posters" / "_index.json"


DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"
)


def parse_title(raw: str) -> dict:
    # Collapse repeated whitespace into single spaces but keep newlines as separators
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]

    # row number is the first short token if numeric
    row_no = ""
    if lines and lines[0].isdigit() and len(lines[0]) <= 3:
        row_no = lines[0]
        lines = lines[1:]

    # product name = the line ending with "- Service Parts"
    product_name = ""
    for ln in lines:
        if ln.lower().endswith("service parts"):
            product_name = re.sub(r"\s*-\s*Service\s+Parts\s*$", "", ln, flags=re.I).strip()
            break

    # legacy?
    legacy = any(ln.lower() == "legacy" for ln in lines)

    # doc type
    doc_type = ""
    for ln in lines:
        if ln.lower() in ("poster", "brochure", "sell sheet", "service literature"):
            doc_type = ln
            break

    # lit_no: typically a 4-6 digit number that appears AFTER the doc-type line
    lit_no = ""
    if doc_type:
        try:
            idx = lines.index(doc_type)
            for cand in lines[idx + 1:idx + 4]:
                if re.fullmatch(r"\d{4,6}", cand):
                    lit_no = cand
                    break
        except ValueError:
            pass

    # date
    date = ""
    for ln in lines:
        m = DATE_RE.search(ln)
        if m:
            date = m.group(0)
            break

    # related parts after "/" in the warning line
    related: list[str] = []
    for ln in lines:
        if ln.startswith("#Part poster may be outdated"):
            # Take text after "/", split on commas
            if "/" in ln:
                tail = ln.split("/", 1)[1].strip()
                related = [p.strip() for p in re.split(r"[,\s]+", tail) if re.match(r"^\d", p)]
            break

    return {
        "row_no": row_no,
        "product_name": product_name,
        "doc_type": doc_type or "Poster",
        "lit_no": lit_no,
        "date": date,
        "legacy": legacy,
        "related_parts": related,
    }


def main() -> int:
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    cleaned: list[dict] = []
    for entry in data:
        parsed = parse_title(entry.get("title", ""))
        out = {
            "product_name": parsed["product_name"],
            "lit_no": parsed["lit_no"],
            "doc_type": parsed["doc_type"],
            "date": parsed["date"],
            "legacy": parsed["legacy"],
            "related_parts": parsed["related_parts"],
            "url": entry.get("url", ""),
            "local_path": entry.get("local_path", ""),
            "size": entry.get("size", 0),
            "downloaded": entry.get("downloaded", False),
            "raw_title_preview": (entry.get("title", "")[:200]
                                  .replace("\n", " ")
                                  .replace("  ", " ")),
        }
        cleaned.append(out)

    # Stable sort: by product_name then lit_no
    cleaned.sort(key=lambda e: (e["product_name"].lower(), e["lit_no"]))

    INDEX_PATH.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    print(f"[clean] rewrote {INDEX_PATH} with {len(cleaned)} entries", flush=True)
    print(f"[clean] sample:", flush=True)
    for e in cleaned[:5]:
        print(f"  - {e['product_name']:<45} lit_no={e['lit_no']:<8} "
              f"date={e['date']:<20} legacy={e['legacy']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
