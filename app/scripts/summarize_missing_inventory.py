"""summarize_missing_inventory.py — turn the 10K-row missing-products CSV
into something a human can scan.

Reads tte_inventory_missing_from_website.csv and prints:

  Section A — Manufacturers that ARE on the website but have stocked SKUs
              not yet imported.  These are the highest-leverage gaps —
              one product enrich pass per brand should resolve them.

  Section B — Manufacturers with stock but NO brand row on the website
              at all (WEST, BUY, SNOW, MYP, etc.).  Each needs a brand
              row created + a catalog enrich pass before its inventory
              can be linked.

For each section, prints:
  • The brand (prod_code + display name)
  • Total stocked SKUs missing from the site
  • Total units on hand
  • Per-warehouse breakdown (10=Spokane, 1=Portland, 2=Kent)
  • 5 sample SKUs

Usage:
    python app/scripts/summarize_missing_inventory.py
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


REPORT = Path(__file__).resolve().parent.parent / "data" / "reports" / "tte_inventory_missing_from_website.csv"


def main() -> None:
    if not REPORT.exists():
        print(f"missing report: {REPORT}")
        return

    # Group by brand_prod_code: { 'on_website' : True/False,
    #                             'brand_name': str,
    #                             'rows': [list] }
    by_brand: dict[str, dict] = defaultdict(lambda: {
        "on_website": False,
        "brand_name": "",
        "rows": [],
        "wh_units": defaultdict(int),
        "wh_skus": defaultdict(int),
    })

    with REPORT.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for r in reader:
            pc = r["prod_code"]
            entry = by_brand[pc]
            entry["on_website"] = (r["brand_on_website"] == "YES")
            entry["brand_name"] = r["brand_name"]
            entry["rows"].append(r)
            try:
                wh = int(r["warehouse"])
                onhand = int(r["onhand"] or 0)
            except (ValueError, TypeError):
                wh = -1
                onhand = 0
            entry["wh_units"][wh] += onhand
            entry["wh_skus"][wh] += 1

    on_site = [(pc, e) for pc, e in by_brand.items() if e["on_website"]]
    off_site = [(pc, e) for pc, e in by_brand.items() if not e["on_website"]]

    on_site.sort(key=lambda x: -sum(x[1]["wh_units"].values()))
    off_site.sort(key=lambda x: -sum(x[1]["wh_units"].values()))

    def fmt_brand(pc, e, max_samples=5):
        units = sum(e["wh_units"].values())
        skus = len(e["rows"])
        wh_str = ", ".join(
            f"wh{wh}={u} units / {e['wh_skus'][wh]} SKUs"
            for wh, u in sorted(e["wh_units"].items()) if u > 0
        )
        samples = [r["parts_num"] or r["ourparts_num"] for r in e["rows"][:max_samples]]
        return (
            f"\n  [{pc}]  {e['brand_name']:<30s}  {skus} stocked SKUs · "
            f"{units} total units\n"
            f"     {wh_str}\n"
            f"     samples: {', '.join(samples)}"
        )

    print("=" * 78)
    print("SECTION A — Manufacturers ON the website with stocked SKUs not yet imported")
    print("=" * 78)
    print(f"\n{len(on_site)} brands · {sum(len(e['rows']) for _, e in on_site)} missing SKUs · "
          f"{sum(sum(e['wh_units'].values()) for _, e in on_site)} units")
    for pc, e in on_site:
        print(fmt_brand(pc, e))

    print()
    print("=" * 78)
    print("SECTION B — Manufacturers with stock but NOT YET on the website at all")
    print("=" * 78)
    print(f"\n{len(off_site)} brands · {sum(len(e['rows']) for _, e in off_site)} missing SKUs · "
          f"{sum(sum(e['wh_units'].values()) for _, e in off_site)} units")
    for pc, e in off_site:
        print(fmt_brand(pc, e))


if __name__ == "__main__":
    main()
