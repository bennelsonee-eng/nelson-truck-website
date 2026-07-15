"""Combine all per-make doc-library indexes into a master file keyed by mount kit SKU.

Reads:
  refs/western_doc_library/mount_kits_<make>/_index.json (all of them)

Writes:
  refs/western_doc_library/_master_index.json — list of {mount_kit_sku, makes,
      docs:[{make, doc_type, lit_no, ...}], year_ranges, ...}
  refs/western_doc_library/_summary.md — human-readable per-make counts
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROOT = REPO_ROOT / "refs" / "western_doc_library"


def main() -> int:
    by_sku: dict[str, dict] = defaultdict(lambda: {
        "mount_kit_sku": "",
        "makes": set(),
        "product_names": set(),
        "year_starts": set(),
        "year_ends": set(),
        "legacy": False,
        "docs": [],
    })
    per_make_stats = []

    for make_dir in sorted(ROOT.glob("mount_kits_*")):
        if not (make_dir / "_index.json").exists():
            continue
        make_label = make_dir.name.removeprefix("mount_kits_")
        if make_label == "all":
            continue
        rows = json.loads((make_dir / "_index.json").read_text(encoding="utf-8"))
        per_make_stats.append((make_label, len(rows)))
        for r in rows:
            sku = (r.get("mount_kit_sku") or "").strip()
            if not sku:
                continue
            entry = by_sku[sku]
            entry["mount_kit_sku"] = sku
            entry["makes"].add(make_label)
            if r.get("product_name"):
                entry["product_names"].add(r["product_name"])
            if r.get("year_start") is not None:
                entry["year_starts"].add(r["year_start"])
            if r.get("year_end") is not None:
                entry["year_ends"].add(r["year_end"])
            if r.get("legacy"):
                entry["legacy"] = True
            entry["docs"].append({
                "make": make_label,
                "doc_type": r.get("doc_type", ""),
                "lit_no": r.get("lit_no", ""),
                "date": r.get("date", ""),
                "url": r.get("url", ""),
                "local_path": r.get("local_path", ""),
                "product_name": r.get("product_name", ""),
                "year_start": r.get("year_start"),
                "year_end": r.get("year_end"),
            })

    # Convert sets to sorted lists for JSON
    master = []
    for sku, e in by_sku.items():
        year_starts = sorted(e["year_starts"])
        year_ends = sorted([y for y in e["year_ends"] if y is not None])
        master.append({
            "mount_kit_sku": sku,
            "makes": sorted(e["makes"]),
            "product_names": sorted(e["product_names"]),
            "year_start_min": year_starts[0] if year_starts else None,
            "year_end_max": year_ends[-1] if year_ends else None,
            "year_start_values": year_starts,
            "year_end_values": year_ends,
            "legacy": e["legacy"],
            "docs": e["docs"],
            "doc_count": len(e["docs"]),
        })
    # Stable sort: alphabetical by SKU
    master.sort(key=lambda r: r["mount_kit_sku"])

    out_json = ROOT / "_master_index.json"
    out_json.write_text(json.dumps(master, indent=2), encoding="utf-8")
    print(f"wrote {out_json}", flush=True)
    print(f"  unique mount-kit SKUs: {len(master)}", flush=True)
    print(f"  total doc entries: {sum(r['doc_count'] for r in master)}", flush=True)

    # Human-readable summary
    summary_lines = [
        "# Western doc-library — per-make summary",
        "",
        f"- Unique mount-kit SKUs across all makes: **{len(master)}**",
        f"- Total per-make doc entries: **{sum(r['doc_count'] for r in master)}**",
        "",
        "## Per-make doc counts",
        "",
        "| Make | Docs |",
        "|---|---|",
    ]
    for make, n in sorted(per_make_stats, key=lambda x: -x[1]):
        summary_lines.append(f"| {make} | {n} |")
    summary_lines += [
        "",
        "## SKUs that span multiple makes",
        "",
    ]
    multi = [r for r in master if len(r["makes"]) > 1]
    for r in multi[:30]:
        names = "; ".join(r["product_names"][:1])[:80]
        summary_lines.append(
            f"- `{r['mount_kit_sku']}` — {', '.join(r['makes'])} — {names!r}"
        )
    if len(multi) > 30:
        summary_lines.append(f"- ... and {len(multi)-30} more")

    (ROOT / "_summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"wrote {ROOT / '_summary.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
