"""
Analyze the WSM catalog CSV export(s).

Streams through each file (no full-load — handles 366 MB without blowing memory),
collects distinct-value counts + numeric distributions + sample rows, and prints
a structured summary you can paste into design notes.

Usage:
    python -m scripts.analyze_wsm_export                       # analyze all CSVs in app/data/wsm_export/
    python -m scripts.analyze_wsm_export path/to/file.csv      # analyze a specific file

Run from app/backend/ with venv activated, OR from app/ directory.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

# Force UTF-8 stdout so we can print → and other non-CP1252 characters on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# Resolve data directory relative to this script
SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = APP_DIR / "data" / "wsm_export"


# Increase CSV field size limit (some columns have multi-paragraph descriptions).
# sys.maxsize on Windows-64 can overflow C long, so step down until accepted.
_max = sys.maxsize
while True:
    try:
        csv.field_size_limit(_max)
        break
    except OverflowError:
        _max = int(_max / 10)
        if _max < 1_000_000:
            csv.field_size_limit(1_000_000)
            break


def _to_float(s: str) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(str(s).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def analyze_file(path: Path, max_distinct: int = 50, sample_count: int = 3) -> dict:
    """Stream a CSV and return summary stats."""
    summary: dict = {
        "file": str(path),
        "size_bytes": path.stat().st_size,
        "rows": 0,
        "columns": [],
        "distinct_value_counts": {},  # column -> total distinct
        "top_values": {},               # column -> [(value, count)]
        "numeric_stats": {},            # column -> {n, zeros, mean, median, max, min}
        "samples": [],
    }

    # Per-column accumulators
    distinct: dict[str, Counter] = defaultdict(Counter)
    numeric_buckets: dict[str, list[float]] = defaultdict(list)
    populated: dict[str, int] = defaultdict(int)

    # Columns we care about for distinct-value tracking (memory-bounded)
    distinct_cols = {
        "BRAND", "CATEGORYNAME", "WAREHOUSE", "HIDDEN", "AVAILABILITY",
        "TAXABLE", "REQUIRESSHIPPING", "FREE GROUND", "FREIGHT CLASS",
        "LOGIN REQUIRED", "GROUPREQUIRED", "PRIORITY", "OWN BOX",
        "OWNER", "REMOTELYUPDATE", "SALEPRICEHIDDEN", "SHIP QUOTE",
        "CONDITION",
    }
    # Columns we treat as numeric distributions
    numeric_cols = {"PRICE", "COST", "SALE", "INVENTORY", "WEIGHT",
                    "HEIGHT", "WIDTH", "LENGTH", "HANDLING", "SHIPPINGAMOUNT", "WSMID"}
    # Columns we treat as "populated yes/no"
    populated_cols = {"UPC", "IMAGE", "TIER PRICE", "GOOGLECATEGORY",
                      "METADESCRIPTION", "EXTENDEDDESCRIPTION", "DESCRIPTION",
                      "PRODUCTSERIES", "TAG", "URL", "ATTACHMENT", "OPTIONS",
                      "DETAIL", "SHIPPINGREMARKS", "AVAILABLEREMARKS",
                      "ADMIN NOTES", "EMAIL NOTES", "CATEGORYTREE"}

    image_url_domains: Counter = Counter()
    image_count_per_product: list[int] = []
    stockid_prefixes: Counter = Counter()
    category_first_parts: Counter = Counter()
    categorytree_depths: Counter = Counter()

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        summary["columns"] = list(reader.fieldnames or [])
        for i, row in enumerate(reader):
            summary["rows"] += 1
            if i < sample_count:
                summary["samples"].append({k: (v or "")[:200] for k, v in row.items()})
            for col, val in row.items():
                v = (val or "").strip()
                if col in distinct_cols and v:
                    distinct[col][v] += 1
                if col in numeric_cols:
                    n = _to_float(v)
                    if n is not None:
                        numeric_buckets[col].append(n)
                if col in populated_cols and v:
                    populated[col] += 1
                if col == "STOCKID" and v:
                    if ":" in v:
                        stockid_prefixes[v.split(":", 1)[0]] += 1
                    else:
                        stockid_prefixes["(no-colon)"] += 1
                if col == "CATEGORYNAME" and v:
                    category_first_parts[v.split(",", 1)[0].split(">", 1)[0].strip()] += 1
                if col == "CATEGORYTREE" and v:
                    depth = v.count(">")
                    categorytree_depths[depth] += 1
                if col == "IMAGE" and v:
                    urls = [u.strip() for u in v.split(";") if u.strip()]
                    image_count_per_product.append(len(urls))
                    for u in urls:
                        # Extract domain
                        if "://" in u:
                            try:
                                d = u.split("://", 1)[1].split("/", 1)[0]
                                image_url_domains[d] += 1
                            except IndexError:
                                pass

    # Summarize distincts
    for col, ctr in distinct.items():
        summary["distinct_value_counts"][col] = len(ctr)
        summary["top_values"][col] = ctr.most_common(max_distinct)

    # Numeric stats
    for col, vals in numeric_buckets.items():
        if not vals:
            continue
        zeros = sum(1 for v in vals if v == 0)
        nonzero = [v for v in vals if v > 0]
        summary["numeric_stats"][col] = {
            "count_total": len(vals),
            "count_zero": zeros,
            "count_nonzero": len(nonzero),
            "mean_nonzero": round(statistics.mean(nonzero), 2) if nonzero else 0,
            "median_nonzero": round(statistics.median(nonzero), 2) if nonzero else 0,
            "min_nonzero": min(nonzero) if nonzero else 0,
            "max_nonzero": max(nonzero) if nonzero else 0,
            "p95_nonzero": round(statistics.quantiles(nonzero, n=20)[-1], 2) if len(nonzero) > 20 else None,
        }

    summary["populated_counts"] = dict(populated)
    summary["image_domains"] = image_url_domains.most_common(10)
    if image_count_per_product:
        summary["image_count_per_product"] = {
            "products_with_images": len(image_count_per_product),
            "total_images": sum(image_count_per_product),
            "mean_per_product": round(statistics.mean(image_count_per_product), 2),
            "median_per_product": int(statistics.median(image_count_per_product)),
            "max_per_product": max(image_count_per_product),
        }
    summary["stockid_prefix_top"] = stockid_prefixes.most_common(20)
    summary["category_first_top"] = category_first_parts.most_common(30)
    summary["categorytree_depth_distribution"] = sorted(categorytree_depths.items())

    return summary


def print_summary(s: dict) -> None:
    print("=" * 80)
    print(f"FILE: {s['file']}")
    print(f"  Size: {s['size_bytes']:,} bytes ({s['size_bytes'] / 1024 / 1024:.1f} MB)")
    print(f"  Rows: {s['rows']:,}")
    print(f"  Columns: {len(s['columns'])} → {s['columns']}")

    if s["distinct_value_counts"]:
        print("\n  DISTINCT VALUE COUNTS:")
        for col, n in sorted(s["distinct_value_counts"].items()):
            print(f"    {col}: {n}")
        print("\n  TOP VALUES (top 15 per column):")
        for col, top in sorted(s["top_values"].items()):
            print(f"    {col}:")
            for v, c in top[:15]:
                v_str = (v[:60] + "...") if len(v) > 60 else v
                print(f"      {c:>8,}  {v_str}")

    if s["numeric_stats"]:
        print("\n  NUMERIC STATS:")
        for col, st in sorted(s["numeric_stats"].items()):
            print(f"    {col}:  n={st['count_total']:,}  zeros={st['count_zero']:,}  "
                  f"mean={st['mean_nonzero']}  median={st['median_nonzero']}  "
                  f"max={st['max_nonzero']}  p95={st['p95_nonzero']}")

    if s.get("populated_counts"):
        print(f"\n  POPULATED (non-empty) COUNTS:")
        for col, n in sorted(s["populated_counts"].items(), key=lambda x: -x[1]):
            pct = (n / s["rows"] * 100) if s["rows"] else 0
            print(f"    {col}:  {n:,} ({pct:.1f}%)")

    if s.get("image_domains"):
        print(f"\n  IMAGE URL DOMAINS:")
        for d, c in s["image_domains"]:
            print(f"    {c:>8,}  {d}")
    if s.get("image_count_per_product"):
        ic = s["image_count_per_product"]
        print(f"\n  IMAGES PER PRODUCT: products={ic['products_with_images']:,}  "
              f"total={ic['total_images']:,}  mean={ic['mean_per_product']}  "
              f"median={ic['median_per_product']}  max={ic['max_per_product']}")

    if s.get("stockid_prefix_top"):
        print(f"\n  STOCKID PREFIX (before colon, top 15):")
        for p, c in s["stockid_prefix_top"][:15]:
            print(f"    {c:>8,}  {p}")

    if s.get("category_first_top"):
        print(f"\n  CATEGORYNAME first-part (top 20):")
        for p, c in s["category_first_top"][:20]:
            print(f"    {c:>8,}  {p}")

    if s.get("categorytree_depth_distribution"):
        print(f"\n  CATEGORYTREE depth distribution ('>' counts):")
        for d, c in s["categorytree_depth_distribution"]:
            print(f"    depth {d}: {c:,}")


def main() -> int:
    if len(sys.argv) > 1:
        files = [Path(p) for p in sys.argv[1:]]
    else:
        if not DEFAULT_DATA_DIR.exists():
            print(f"No files specified and {DEFAULT_DATA_DIR} doesn't exist.", file=sys.stderr)
            return 1
        files = sorted(DEFAULT_DATA_DIR.glob("*.csv"))

    if not files:
        print("No CSV files to analyze.", file=sys.stderr)
        return 1

    all_summaries: list[dict] = []
    for f in files:
        if not f.exists():
            print(f"Skipping (not found): {f}", file=sys.stderr)
            continue
        # Skip the header-only files (< 1 KB) — they have nothing to analyze
        if f.stat().st_size < 2000:
            print(f"Skipping (too small / header-only): {f.name} ({f.stat().st_size} bytes)")
            continue
        try:
            s = analyze_file(f)
            print_summary(s)
            all_summaries.append(s)
        except Exception as e:
            print(f"\nERROR analyzing {f}: {e}", file=sys.stderr)

    # Save JSON output for programmatic use
    out_path = DEFAULT_DATA_DIR / "_analysis_summary.json"
    out_path.write_text(json.dumps(all_summaries, indent=2, default=str), encoding="utf-8")
    print(f"\n\nJSON summary saved to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
