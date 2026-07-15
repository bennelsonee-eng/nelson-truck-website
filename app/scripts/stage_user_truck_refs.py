"""Stage user-provided truck reference photos as clean PNG thumbnails for picking.

Reads files the user dropped in C:/Users/Ben/Pictures/ and writes 800px-wide
PNG thumbnails to refs/_candidates/ so Claude can Read them safely (avoiding the
AVIF→PNG mismatch that caused the API 400 last session).
"""
from __future__ import annotations

import pillow_avif  # noqa: F401  (registers AVIF opener)
from PIL import Image
from pathlib import Path

PIX = Path("C:/Users/Ben/Pictures")
OUT = Path("C:/Users/Ben/titan truck website/refs/_candidates")
OUT.mkdir(parents=True, exist_ok=True)

# Map: candidate slug -> source filename (relative to Pictures)
# These are the photos the user grabbed on 2026-05-10 ~22:30–22:42
CANDIDATES: dict[str, str] = {
    # Ram 1500 — already angle-labeled by user, take all 3 verbatim
    "ram_1500_m30": "ram 1500 -30 degree.webp",
    "ram_1500_0":   "ram 1500 0 degree front facing.avif",
    "ram_1500_p30": "ram 1500 +30 facing front.png",

    # Toyota Tundra (4 candidates)
    "tundra_a": "imgbin-2016-toyota-tundra-pickup-truck-2015-toyota-tundra-2017-toyota-tundra-pickup-truck-9cLFC7nGafuFQmGgPNcbTKELL.jpg",
    "tundra_b": "imgbin-2018-toyota-tundra-car-2017-toyota-tundra-sr5-2016-toyota-tundra-sr5-2018-toyota-tundra-buVmZx4vHyzMAPrUNQFMYU3X7.jpg",
    "tundra_c": "imgbin-2016-toyota-tundra-2018-toyota-tundra-toyota-sequoia-toyota-tacoma-toyota-Fg7jKffDayTjMvPcScq0qt5wE.jpg",
    "tundra_d": "imgbin-2018-toyota-tundra-limited-crewmax-2018-toyota-tundra-limited-double-cab-car-2018-toyota-tundra-sr5-toyota-W1sXGZhuhfuvsfAd9sSbLkp1V.jpg",

    # Isuzu NPR / Elf cab-over (5 candidates)
    "isuzu_a": "imgbin-isuzu-elf-nissan-atlas-isuzu-motors-ltd-isuzu-forward-trucks-XCP1VxM8AzR9fn80r6prwsUJu.jpg",
    "isuzu_b": "imgbin-car-isuzu-elf-isuzu-motors-ltd-nissan-atlas-car-PmEAiPsWYMvFuyiQAfudVQsEN.jpg",
    "isuzu_c": "imgbin-compact-van-isuzu-elf-isuzu-d-max-isuzu-motors-ltd-isuzu-truck-PtNkh896Js8B9XxTc2fP2qY5p.jpg",
    "isuzu_d": "imgbin-compact-van-isuzu-elf-isuzu-motors-ltd-isuzu-elf-riXyi4PdY14bQW41eJRGbk4xV.jpg",
    "isuzu_e": "imgbin-isuzu-motors-ltd-isuzu-forward-isuzu-elf-isuzu-i-series-adv-asDMeWPxL89zTTAsqCp0M7RfA.jpg",

    # Jeep Liberty + Renegade + Wrangler (8 candidates — name disambiguation needed)
    "jeep_a": "imgbin-jeep-trailhawk-car-sport-utility-vehicle-jeep-liberty-jeep-trailhawk-N7b0sJj7Hru9V6xNw6qqJEjXw.jpg",
    "jeep_b": "imgbin-jeep-cherokee-kl-jeep-grand-cherokee-chrysler-jeep-liberty-jeep-KCNWAQcUfvZgNnc8wzE2L593g.jpg",
    "jeep_c": "imgbin-2013-jeep-grand-cherokee-2012-jeep-grand-cherokee-jeep-liberty-car-jeep-MDh4SA59hG37sap6cbQzcgNaq.jpg",
    "jeep_d": "png-transparent-compact-sport-utility-vehicle-jeep-liberty-car-jeep-car-off-road-vehicle-vehicle.png",
    "jeep_e": "png-clipart-2015-jeep-wrangler-army-jeep-car-off-road-vehicle-thumbnail.png",
    "jeep_f": "png-clipart-jeep-liberty-chrysler-sport-utility-vehicle-2017-jeep-grand-cherokee-limited-jeep-car-vehicle.png",
    "jeep_g": "2005-jeep-liberty-2006-jeep-liberty-2008-jeep-liberty-car-png-favpng-cQT3keXEmhN2QSHjnEp6gYSNH_t.jpg",
    "jeep_h": "png-clipart-jeep-liberty-sport-utility-vehicle-2018-jeep-grand-cherokee-laredo-jeep-cherokee-jeep-car-off-road-vehicle.png",
    "jeep_i": "2010-jeep-liberty-2008-jeep-liberty-2009-jeep-liberty-2012-jeep-liberty-jeep.jpg",
}


def main() -> int:
    print(f"Staging {len(CANDIDATES)} candidates -> {OUT}")
    for slug, fname in CANDIDATES.items():
        src = PIX / fname
        if not src.exists():
            print(f"  MISS {slug}: {src.name}")
            continue
        try:
            img = Image.open(src)
        except Exception as e:
            print(f"  FAIL {slug}: {e}")
            continue
        img = img.convert("RGB")
        w, h = img.size
        max_w = 800
        if w > max_w:
            new_h = int(h * max_w / w)
            img = img.resize((max_w, new_h), Image.LANCZOS)
        out = OUT / f"{slug}.png"
        img.save(out, "PNG")
        print(f"  OK   {slug}: {w}x{h} -> {img.size[0]}x{img.size[1]}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
