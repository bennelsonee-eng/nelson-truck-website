"""One-off: print western_plow_heroes/_index.json in human-readable form."""
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

idx = json.loads(
    (Path(__file__).resolve().parent.parent.parent / "refs" / "western_plow_heroes"
     / "_index.json").read_text(encoding="utf-8")
)
print(f"Total plow lines: {len(idx)}")
total = 0
for e in idx:
    n = e["sku_count"]
    total += n
    name = e["plow_line_slug"]
    if n > 0:
        print(f"  {name:<25} {n:>2} SKUs   ->   {e['skus']}")
print(f"Total SKUs covered: {total}")
print()
print("Lines without captured SKUs (hero saved, no blade data yet):")
for e in idx:
    if e["sku_count"] == 0:
        print(f"  {e['plow_line_slug']}")
