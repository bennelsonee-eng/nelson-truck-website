"""check_no_dead_links.py — enforce the no-dead-links rule.

Run after backend changes. Iterates every link the frontend will render
against the public catalog API and fails if any returns 0 products.

Targets:
 - Every MEGA_SECTIONS sub_section href (mirrored from App.tsx)
 - The "View All <Section>" header for each section
 - Every top-level category from /api/catalog/categories/tree
 - Every depth-1 + depth-2 category visible in the live tree
 - Hardcoded footer + home-rail links

Exit code 0 if all links are healthy, non-zero with a report on stderr
otherwise. Wire this into CI so the build fails when somebody adds a
broken filter (the bug Ben caught on Truck Accessories / Interior
Accessories View All).

Usage:
    python app/scripts/check_no_dead_links.py
    python app/scripts/check_no_dead_links.py --base http://localhost:8001
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse
from typing import Iterable

import requests


# Mirrors the frontend MEGA_SECTIONS targets. Each entry is (label,
# {param: value}) — params get urlencoded so labels containing '&' or
# ' > ' (which the frontend correctly encodeURIComponents) don't get
# torn into separate query params by the requests library.
MEGA_SUB_LINKS: list[tuple[str, dict[str, str]]] = [
    ("Truck Accessories",        {"category_top": "Truck Accessories"}),
    ("Truck Equipment",          {"category_top": "Truck Equipment"}),
    ("Trailer & RV",             {"category_top": "Trailer & RV"}),
    ("Van Equipment (label)",    {"category_top": "Van Equipment"}),
    ("Exterior Accessories",     {"category_top": "Exterior"}),
    ("Interior Accessories",     {"category_top": "Interior"}),
    ("Tonneau Covers",           {"category_top": "Truck Bed Covers"}),
    ("Bumpers & Grille Guards",  {"category_top": "Bumpers and Grille Guards"}),
    ("Running Boards & Steps",   {"category_top": "Running Boards and Steps"}),
    ("Cargo Management",         {"category_top": "Cargo Management"}),
    ("Lighting",                 {"category_top": "Automotive Lighting"}),
    ("Suspension & Lift Kits",   {"category_top": "Suspension"}),
    ("Truck Bed & Tailgate",     {"category_top": "Truck Bed and Tailgate"}),
    ("Wheels & Tires",           {"category_top": "Wheels and Tires"}),
    ("Air Intakes",              {"category_top": "Air Intakes"}),
    ("Towing & Hitches",         {"category_top": "Towing and Accessories"}),
    ("Winches",                  {"category_top": "Winches and Accessories"}),
    ("Van Accessories",          {"category_path": "Van Equipment > Van Accessories", "vehicle_type": "Van"}),
    ("Van Shelving",             {"category_path": "Van Equipment > Van Shelving", "vehicle_type": "Van"}),
    ("Van Packages",             {"category_path": "Van Equipment > Van Packages", "vehicle_type": "Van"}),
    ("Cab Partitions & Dividers",{"category_path": "Van Equipment > Cab Partitions and Dividers", "vehicle_type": "Van"}),
    ("Footer: All products",     {}),
    ("Footer: In stock",         {"in_stock": "true"}),
]


def probe(base: str, params: dict[str, str]) -> tuple[int, str]:
    """Returns (product_count, request_url). Raises on HTTP error."""
    p = dict(params)
    p["per_page"] = "1"
    r = requests.get(f"{base}/api/catalog/browse", params=p, timeout=10)
    r.raise_for_status()
    return int(r.json().get("found", 0)), r.url


def tree_links(base: str) -> Iterable[tuple[str, dict[str, str]]]:
    """Pull every category off /categories/tree and yield (label, params)."""
    r = requests.get(f"{base}/api/catalog/categories/tree", timeout=15)
    r.raise_for_status()
    def walk(nodes, depth=0):
        for n in nodes or []:
            if depth == 0:
                params = {"category_top": n["name"]}
            else:
                params = {"category_path": n["full_path"]}
            yield (f"tree[{n['full_path']}]", params)
            yield from walk(n.get("children", []), depth + 1)
    yield from walk(r.json())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://localhost:8001",
                    help="Backend base URL (default: http://localhost:8001)")
    ap.add_argument("--fail-fast", action="store_true", help="Exit on first dead link")
    args = ap.parse_args()

    seen: set[tuple[tuple[str, str], ...]] = set()
    dead: list[tuple[str, dict, str]] = []
    checked = 0
    for label, params in list(MEGA_SUB_LINKS) + list(tree_links(args.base)):
        key = tuple(sorted(params.items()))
        if key in seen:
            continue
        seen.add(key)
        try:
            n, url = probe(args.base, params)
        except Exception as e:
            dead.append((label, params, f"ERROR: {e}"))
            if args.fail_fast:
                break
            continue
        checked += 1
        if n == 0:
            dead.append((label, params, "0 products"))
            if args.fail_fast:
                break

    if dead:
        print(f"\nDEAD LINKS: {len(dead)} out of {checked} probed:", file=sys.stderr)
        for label, params, reason in dead:
            qs = urllib.parse.urlencode(params)
            print(f"  - {label}   /catalog?{qs}   ({reason})", file=sys.stderr)
        return 1

    print(f"OK: all {checked} catalog links resolve to >0 products")
    return 0


if __name__ == "__main__":
    sys.exit(main())
