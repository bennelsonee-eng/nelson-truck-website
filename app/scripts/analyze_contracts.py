"""Analyze the contracts_copy.csv export from Titan MySQL.

Streams through with semicolon-delimited CSV reader. Outputs distinct counts
+ formula-pattern stats + per-company splits.

Usage: python -m scripts.analyze_contracts
"""

from __future__ import annotations

import csv
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_FILE = SCRIPT_DIR.parent / "data" / "contracts" / "contracts_copy.csv"

# Patterns to classify pricing formulas
PRICE_TIER_RE = re.compile(r"P\d+")
NUMERIC_RE = re.compile(r"^[\d.]+$")
COMPLEX_RE = re.compile(r"[+\-]")


def classify_formula(s: str) -> str:
    """Return a category label for a pricing formula."""
    s = s.strip()
    if not s:
        return "(empty)"
    if PRICE_TIER_RE.fullmatch(s):
        return "tier_only"  # e.g., "P3"
    if "*" in s and PRICE_TIER_RE.match(s):
        return "tier_x_factor"  # e.g., "P3*.83"
    if "/" in s and PRICE_TIER_RE.match(s):
        return "tier_div_factor"
    if COMPLEX_RE.search(s) and PRICE_TIER_RE.search(s):
        return "tier_with_op"  # e.g., "P5+50"
    if s.startswith("$") or NUMERIC_RE.match(s):
        return "fixed_price"
    if PRICE_TIER_RE.search(s):
        return "tier_other"
    return "other"


def main() -> int:
    if not DATA_FILE.exists():
        print(f"NOT FOUND: {DATA_FILE}", file=sys.stderr)
        return 1
    print(f"Analyzing: {DATA_FILE}  ({DATA_FILE.stat().st_size:,} bytes)\n")

    rows = 0
    company_counts: Counter[str] = Counter()
    distinct_customers: dict[str, set] = {}     # company -> set of cust_ids
    distinct_contracts: dict[str, set] = {}     # company -> set of contract IDs
    distinct_prod_codes: dict[str, Counter] = {}
    distinct_brands_partnumbers: dict[str, Counter] = {}
    formula_classes: Counter[str] = Counter()
    formula_samples: dict[str, list[str]] = {}
    priority_dist: Counter[int] = Counter()
    min_qty_dist: Counter[int] = Counter()
    has_expiry: int = 0
    has_part_number: int = 0
    has_prod_code: int = 0
    has_group_code: int = 0
    titan_only_samples: list[dict] = []

    with DATA_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for r in reader:
            rows += 1
            company = (r.get("company") or "").strip()
            company_counts[company] += 1

            distinct_customers.setdefault(company, set()).add(r.get("cust_id") or "")
            distinct_contracts.setdefault(company, set()).add(r.get("contract") or "")

            pc = (r.get("prod_code") or "").strip()
            pn = (r.get("ourparts_num") or "").strip()
            gc = (r.get("group_code") or "").strip()
            if pc:
                distinct_prod_codes.setdefault(company, Counter())[pc] += 1
                has_prod_code += 1
            if pn:
                distinct_brands_partnumbers.setdefault(company, Counter())[pn] += 1
                has_part_number += 1
            if gc and gc != "0":
                has_group_code += 1
            if r.get("exp_date"):
                has_expiry += 1

            d = (r.get("discount") or "").strip()
            cls = classify_formula(d)
            formula_classes[cls] += 1
            if d and len(formula_samples.get(cls, [])) < 8:
                formula_samples.setdefault(cls, []).append(d)

            try:
                priority_dist[int(r.get("priority") or 0)] += 1
            except ValueError:
                pass
            try:
                min_qty_dist[int(r.get("min_quantity") or 0)] += 1
            except ValueError:
                pass

            if company == "titan" and len(titan_only_samples) < 10:
                titan_only_samples.append(r)

    print(f"Total rows: {rows:,}\n")

    print("BY COMPANY:")
    for c, n in company_counts.most_common():
        print(f"  {c or '(blank)'}: {n:,}")
    print()

    print("DISTINCT CUSTOMERS PER COMPANY:")
    for c, s in distinct_customers.items():
        print(f"  {c or '(blank)'}: {len(s):,} unique customers")
    print()

    print("DISTINCT CONTRACT IDs PER COMPANY:")
    for c, s in distinct_contracts.items():
        print(f"  {c or '(blank)'}: {len(s):,} unique contract numbers")
    print()

    print("RULE SCOPE BREAKDOWN:")
    print(f"  rows with prod_code populated: {has_prod_code:,} ({has_prod_code/rows*100:.1f}%)")
    print(f"  rows with ourparts_num populated: {has_part_number:,} ({has_part_number/rows*100:.1f}%)")
    print(f"  rows with group_code != 0: {has_group_code:,} ({has_group_code/rows*100:.1f}%)")
    print(f"  rows with exp_date set: {has_expiry:,} ({has_expiry/rows*100:.1f}%)")
    print()

    print("PRICING FORMULA CLASSES:")
    for cls, n in formula_classes.most_common():
        print(f"  {cls}: {n:,} ({n/rows*100:.1f}%)")
        for sample in formula_samples.get(cls, [])[:5]:
            print(f"     e.g.  {sample}")
    print()

    print("TOP 25 PRIORITIES (most rows):")
    for p, n in priority_dist.most_common(25):
        print(f"  priority {p}: {n:,}")
    print()

    print("MIN QUANTITY DISTRIBUTION:")
    for q, n in sorted(min_qty_dist.items())[:15]:
        print(f"  min_qty {q}: {n:,}")
    print()

    if "titan" in distinct_prod_codes:
        print("TOP 30 PROD_CODES for titan:")
        for code, n in distinct_prod_codes["titan"].most_common(30):
            print(f"  {n:>8,}  {code}")
        print()

    print("SAMPLE TITAN ROWS:")
    for r in titan_only_samples:
        print(f"  {r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
