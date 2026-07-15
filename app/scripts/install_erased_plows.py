"""Install user-erased plow PNGs from Downloads into the SKU folders.

The eraser tool downloads files named `<SKU>__hero_transparent.png` (or
`_x4.png`). This script moves each file into the matching SKU folder,
renamed to the canonical filename, and backs up the previous version as
`hero_transparent_PRE_ERASE.png` (only if no backup already exists).
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

DOWNLOADS = Path.home() / "Downloads"
SKUS = (
    Path(__file__).resolve().parents[1] / "backend" / "static" / "snow-plows" / "skus"
)

PATTERN = re.compile(r"^(?P<sku>(WEST|SNOW|MYP)-[A-Z0-9-]+)__(?P<name>hero_transparent(?:_x4)?\.png)$")


def main() -> int:
    if not DOWNLOADS.exists():
        print(f"missing: {DOWNLOADS}")
        return 1

    candidates = []
    for f in DOWNLOADS.iterdir():
        if not f.is_file():
            continue
        m = PATTERN.match(f.name)
        if m:
            candidates.append((f, m.group("sku"), m.group("name")))

    if not candidates:
        print("No erased PNGs found in Downloads (looking for <SKU>__hero_transparent*.png)")
        return 0

    print(f"Found {len(candidates)} erased PNGs to install")
    n_done = 0
    n_skipped = 0
    for src, sku, name in candidates:
        sku_dir = SKUS / sku
        if not sku_dir.exists():
            print(f"  ! {sku}: SKU folder not found, skip")
            n_skipped += 1
            continue
        dst = sku_dir / name
        backup = sku_dir / name.replace(".png", "_PRE_ERASE.png")
        # Backup the existing file (only first time)
        if dst.exists() and not backup.exists():
            shutil.copy2(dst, backup)
            print(f"  {sku}: backed up existing -> {backup.name}")
        # Move the new file into place
        shutil.move(str(src), str(dst))
        print(f"  {sku}: installed {name} ({dst.stat().st_size:,}B)")
        n_done += 1

    print(f"\nInstalled {n_done}, skipped {n_skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
