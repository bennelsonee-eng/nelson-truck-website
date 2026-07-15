"""Save user-grabbed truck photos as canonical 1024x576 per-make canny refs.

Reads originals from C:/Users/Ben/Pictures/, applies optional corner masks,
mirrors when needed, letterboxes onto a 1024x576 grey canvas, and writes to
C:/Users/Ben/titan truck website/refs/<slug>_<angle>.png.

The renderer (render_truck_lineup_flux_dev.py) consults this folder first
in build_canny_for_angle() before falling back to class-level cannys.
"""
from __future__ import annotations

import pillow_avif  # noqa: F401  registers AVIF opener
from PIL import Image
from pathlib import Path

PIX = Path("C:/Users/Ben/Pictures")
OUT = Path("C:/Users/Ben/titan truck website/refs")
OUT.mkdir(parents=True, exist_ok=True)

CANVAS_W, CANVAS_H = 1024, 576
BG = (200, 200, 200)

# (slug, angle, source_filename, crop_top_pct, mirror)
#   crop_top_pct: fraction of source height to chop off the top BEFORE letterbox
#                 (used to drop watermark/banner bands cleanly without creating
#                 horizontal edges that canny would falsely emphasize)
#   mirror: flip left-right (used when only one 3Q photo exists, derive the other)
REF_PICKS: list[tuple[str, str, str, float, bool]] = [
    # --- Ram 1500: user pre-labeled all 3 angles ---
    # All 3 cropped equally so the truck sits at the same scale across angles.
    # The -30deg shot has an inspection-notice banner top + ASE badge — 18% crop kills both.
    ("ram_1500", "0deg",   "ram 1500 0 degree front facing.avif", 0.18, False),
    ("ram_1500", "-30deg", "ram 1500 -30 degree.webp",            0.18, False),
    ("ram_1500", "+30deg", "ram 1500 +30 facing front.png",       0.18, False),

    # --- Toyota Tundra: head-on (small) + 3Q (mirror to get opposite) ---
    ("toyota_tundra", "0deg",   "imgbin-2016-toyota-tundra-2018-toyota-tundra-toyota-sequoia-toyota-tacoma-toyota-Fg7jKffDayTjMvPcScq0qt5wE.jpg", 0.0, False),
    # tundra_a: cab points up-right in frame -> -30deg in user convention
    ("toyota_tundra", "-30deg", "imgbin-2016-toyota-tundra-pickup-truck-2015-toyota-tundra-2017-toyota-tundra-pickup-truck-9cLFC7nGafuFQmGgPNcbTKELL.jpg", 0.0, False),
    ("toyota_tundra", "+30deg", "imgbin-2016-toyota-tundra-pickup-truck-2015-toyota-tundra-2017-toyota-tundra-pickup-truck-9cLFC7nGafuFQmGgPNcbTKELL.jpg", 0.0, True),

    # --- Isuzu NPR: head-on box-truck + 3Q cab-chassis (mirror) ---
    ("isuzu_npr", "0deg",   "imgbin-compact-van-isuzu-elf-isuzu-motors-ltd-isuzu-elf-riXyi4PdY14bQW41eJRGbk4xV.jpg", 0.0, False),
    # isuzu_a: cab points up-right -> -30deg
    ("isuzu_npr", "-30deg", "imgbin-isuzu-elf-nissan-atlas-isuzu-motors-ltd-isuzu-forward-trucks-XCP1VxM8AzR9fn80r6prwsUJu.jpg", 0.0, False),
    ("isuzu_npr", "+30deg", "imgbin-isuzu-elf-nissan-atlas-isuzu-motors-ltd-isuzu-forward-trucks-XCP1VxM8AzR9fn80r6prwsUJu.jpg", 0.0, True),

    # --- Jeep Liberty: 3Q only (no head-on grab) ---
    # jeep_i: cab points up-left -> +30deg
    ("jeep_liberty", "+30deg", "2010-jeep-liberty-2008-jeep-liberty-2009-jeep-liberty-2012-jeep-liberty-jeep.jpg", 0.0, False),
    ("jeep_liberty", "-30deg", "2010-jeep-liberty-2008-jeep-liberty-2009-jeep-liberty-2012-jeep-liberty-jeep.jpg", 0.0, True),
    # 0deg intentionally omitted: falls back to class-level mid-size canny
]


def composite_on_grey(img: Image.Image) -> Image.Image:
    """If image has alpha (transparent BG checkerboard from imgbin), composite onto grey."""
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, BG)
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def crop_top(img: Image.Image, pct: float) -> Image.Image:
    """Chop pct fraction off the top of img (removes watermark bands cleanly,
    without creating a horizontal edge that canny would emphasize)."""
    if pct <= 0:
        return img
    w, h = img.size
    return img.crop((0, int(h * pct), w, h))


def letterbox_to_canvas(img: Image.Image) -> Image.Image:
    """Scale img to fit inside CANVAS_WxCANVAS_H, center on grey canvas."""
    src_w, src_h = img.size
    scale = min(CANVAS_W / src_w, CANVAS_H / src_h)
    new_w, new_h = int(src_w * scale), int(src_h * scale)
    resized = img.resize((new_w, new_h), Image.LANCZOS)
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BG)
    x = (CANVAS_W - new_w) // 2
    y = (CANVAS_H - new_h) // 2
    canvas.paste(resized, (x, y))
    return canvas


def main() -> int:
    print(f"Saving {len(REF_PICKS)} per-make refs -> {OUT}")
    written = 0
    for slug, angle, fname, crop_pct, mirror in REF_PICKS:
        src = PIX / fname
        if not src.exists():
            print(f"  MISS {slug}@{angle}: {fname}")
            continue
        try:
            img = Image.open(src)
            img = composite_on_grey(img)
            img = crop_top(img, crop_pct)
            if mirror:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            img = letterbox_to_canvas(img)
            out_path = OUT / f"{slug}_{angle}.png"
            img.save(out_path, "PNG")
            written += 1
            print(f"  OK   {slug}@{angle} -> {out_path.name}")
        except Exception as e:
            print(f"  FAIL {slug}@{angle}: {e}")
    print(f"Done. {written}/{len(REF_PICKS)} written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
