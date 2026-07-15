"""Install user-curated truck picks into a clean production folder.

Reads `~/Downloads/truck_curation_flux_dev_picks.json`, copies the chosen
seed per (slug, angle) cell to `app/backend/static/trucks/renders_curated/`,
and prints a coverage report (what's missing).
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1].parent
SOURCE_DIR = REPO / "app" / "backend" / "static" / "trucks" / "renders_flux_dev"
DEST_DIR = REPO / "app" / "backend" / "static" / "trucks" / "renders_curated"
PICKS = Path.home() / "Downloads" / "truck_curation_flux_dev_picks.json"

# Expected universe — must match the renderer/curation script
EXPECTED = {
    "mid-size": ["toyota_tacoma", "chevy_colorado", "ford_ranger",
                 "jeep_liberty", "jeep_renegade", "chevy_tahoe"],
    "1500": ["chevy_1500", "ford_f150", "toyota_tundra",
             "ram_1500", "nissan_titan", "gmc_1500"],
    "2500": ["chevy_2500", "ford_f250", "ram_2500", "gmc_2500"],
    "3500": ["chevy_3500", "ford_f350", "ram_3500", "gmc_3500"],
    "4500": ["ford_f450", "chevy_4500", "isuzu_npr"],
    "5500": ["ford_f550", "ford_f650", "chevy_6500", "isuzu_nrr"],
}
ANGLES = ["-30deg", "0deg", "+30deg"]


def main() -> int:
    if not PICKS.exists():
        print(f"! missing {PICKS}")
        return 1
    data = json.loads(PICKS.read_text(encoding="utf-8"))
    picks = data.get("picks", {})
    print(f"Loaded {len(picks)} picks")

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    for angle in ANGLES:
        (DEST_DIR / angle).mkdir(parents=True, exist_ok=True)

    n_copied = 0
    n_missing_source = 0
    coverage = defaultdict(set)
    for key, seed in picks.items():
        if "__" not in key:
            continue
        slug, angle = key.split("__", 1)
        src = SOURCE_DIR / angle / f"{slug}_seed{seed}.png"
        if not src.exists():
            print(f"  ! missing source: {src.name}")
            n_missing_source += 1
            continue
        dst = DEST_DIR / angle / f"{slug}.png"
        shutil.copy2(src, dst)
        coverage[slug].add(angle)
        n_copied += 1

    print(f"\nCopied {n_copied} files into {DEST_DIR}")
    if n_missing_source:
        print(f"  ({n_missing_source} picks pointed at non-existent source files)")

    # Coverage report — what's still missing
    print("\n=== Coverage report ===")
    fully_covered = []
    partially_covered = []
    not_covered = []
    for cls, makes in EXPECTED.items():
        for slug in makes:
            got = coverage.get(slug, set())
            missing = [a for a in ANGLES if a not in got]
            if not missing:
                fully_covered.append((cls, slug))
            elif len(got) > 0:
                partially_covered.append((cls, slug, missing))
            else:
                not_covered.append((cls, slug))

    print(f"\nFully covered ({len(fully_covered)}/{sum(len(m) for m in EXPECTED.values())}):")
    for cls, slug in fully_covered:
        print(f"  {cls:9s}  {slug}")

    if partially_covered:
        print(f"\nPartial coverage ({len(partially_covered)}):")
        for cls, slug, missing in partially_covered:
            print(f"  {cls:9s}  {slug:20s} missing: {', '.join(missing)}")

    if not_covered:
        print(f"\nNot covered at all ({len(not_covered)}):")
        for cls, slug in not_covered:
            print(f"  {cls:9s}  {slug}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
