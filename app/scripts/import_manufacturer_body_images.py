"""Replace the truck-body catalog images with the manufacturer's own photography.

Why: the images these products carried came from the old titantruck.com and are
300x165 -- they were never big enough for a product page, and the transparent
ones were being flattened onto black. Knapheide publishes a model-specific
studio shot at 2000x1500 for every body it builds; CM Truck Beds publishes
lifestyle photography at 1400-3840px. This points each body at its own.

Every image is downloaded and resized here, with the same code the site-wide
localizer uses (localize_product_images.make_sizes), and the row is written
with OUR /static/product-images/... path. Nothing on the product page points
at knapheide.com or cmtruckbeds.com; `source_url` keeps the origin for audit
only. An image that fails to download is skipped rather than hotlinked.

`excluded_images.json` ({url: reason}) is never imported -- e.g. photos from a
manufacturer's customer stories, which we don't show.

Existing rows for the affected products are written to a JSON backup before
anything is deleted, so the swap is reversible.

Usage:
    python app/scripts/import_manufacturer_body_images.py --brand knapheide
    python app/scripts/import_manufacturer_body_images.py --brand cm --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
from localize_product_images import make_sizes, paths_for  # noqa: E402

ENV_FILE = HERE.parent.parent / ".env"
DATA_DIR = Path(os.environ.get("KN_IMPORT_DATA", HERE.parent.parent.parent / "discovery" / "manufacturer_data"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0 Safari/537.36")

BRANDS = {
    "knapheide": {
        "origin": "knapheide.com",
        "map": "kn_model_map.json",
        "featured": "kn_body_featured.json",
        "gallery": "kn_gallery.json",
        "studio": True,
        "gallery_caption": "installed",
    },
    "cm": {
        "origin": "cmtruckbeds.com",
        "map": "cm_model_map.json",
        "featured": "cm_bed_featured.json",
        "gallery": "cm_gallery.json",
        "studio": False,
        "gallery_caption": "photo",
    },
    # Dur-A-Lift: hero + gallery chosen per product (dal_featured/gallery.json);
    # customer build collages and photos showing other companies are excluded.
    "duralift": {
        "origin": "dur-a-lift.com",
        "map": "dal_model_map.json",
        "featured": "dal_featured.json",
        "gallery": "dal_gallery.json",
        "studio": False,
        "gallery_caption": "photo",
    },
    # Rugby's page images are hand-picked (rugby_featured/gallery.json): several
    # of its photos are distributors' trucks with their names on the mud flaps.
    "rugby": {
        "origin": "rugbymfg.com",
        "map": "rugby_model_map.json",
        "featured": "rugby_featured.json",
        "gallery": "rugby_gallery.json",
        "studio": False,
        "gallery_caption": "photo",
    },
}


def trim_transparent_margin(data: bytes) -> bytes:
    """A cut-out on a mostly empty transparent canvas (Rugby's Eliminator MD sits
    small in 2560px) is cropped to the truck plus a 4% border before resizing,
    so the product fills the frame. Opaque images are returned unchanged."""
    from io import BytesIO
    from PIL import Image
    im = Image.open(BytesIO(data))
    if im.mode not in ("RGBA", "LA") and not (im.mode == "P" and "transparency" in im.info):
        return data
    im = im.convert("RGBA")
    box = im.getchannel("A").point(lambda a: 255 if a > 16 else 0).getbbox()
    if not box:
        return data
    pad = int(max(box[2] - box[0], box[3] - box[1]) * 0.04)
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad))
    if (box[2] - box[0]) * (box[3] - box[1]) > 0.9 * im.width * im.height:
        return data
    out = BytesIO()
    im.crop(box).save(out, "PNG")
    return out.getvalue()


def db_dsn() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().replace("postgresql+asyncpg://", "postgresql://")
    raise SystemExit("DATABASE_URL not found in app/.env")


def load(name: str, default=None):
    p = DATA_DIR / name
    if not p.exists() and default is not None:
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def fetchable(url: str) -> str:
    """Percent-encode what urllib can't send: Dur-A-Lift's spec charts are named
    like "Screenshot ... 10.20.42 AM.png" (a narrow no-break space)."""
    import urllib.parse
    return urllib.parse.quote(url, safe=":/?&=%#+,;@~")


def localize(src: str) -> tuple[str, str] | None:
    """Download `src` and write our 1280/400 JPEGs. Returns (big_url, thumb_url)."""
    _, big_p, thumb_p, big_url, thumb_url = paths_for(src)
    if big_p.exists() and thumb_p.exists():
        return big_url, thumb_url
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(fetchable(src), headers={"User-Agent": UA}), timeout=120) as r:
                data = r.read()
            make_sizes(src, trim_transparent_margin(data))
            return big_url, thumb_url
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="download + write (default: dry run)")
    ap.add_argument("--gallery-max", type=int, default=6)
    ap.add_argument("--brand", choices=sorted(BRANDS), default="knapheide")
    args = ap.parse_args()

    cfg = BRANDS[args.brand]
    origin = cfg["origin"]
    model_map = load(cfg["map"])        # product_id -> manufacturer model page
    featured = load(cfg["featured"])    # page -> the model's own hero image
    gallery = load(cfg["gallery"])      # page -> supporting photos
    excluded = load("excluded_images.json", {})
    hero_kind = "studio photo" if cfg["studio"] else "photo"

    conn = await asyncpg.connect(db_dsn())
    try:
        pids = [int(p) for p in model_map]
        existing = await conn.fetch(
            "SELECT id, product_id, url, source_url, thumb_url, is_primary, sort_order, alt_text, "
            "legacy_origin FROM product_image WHERE product_id = ANY($1::int[]) ORDER BY product_id, sort_order",
            pids,
        )
        names = {r["id"]: r["name"] for r in await conn.fetch(
            "SELECT id, name FROM product WHERE id = ANY($1::int[])", pids)}

        planned, skipped, dropped = [], [], 0
        for pid_s, page in model_map.items():
            pid = int(pid_s)
            f = featured.get(page) or {}
            if not f.get("url") or f["url"] in excluded:
                skipped.append((pid, page, "no usable featured image"))
                continue
            rows = [{"url": f["url"], "primary": True,
                     "alt": f'{names.get(pid, "")} — {args.brand.title()} {hero_kind}'}]
            for g in (gallery.get(page) or []):
                if g["url"] in excluded:
                    dropped += 1
                    continue
                if g.get("chart"):                  # spec charts always make the gallery, last
                    continue
                if len(rows) > args.gallery_max:
                    break
                rows.append({"url": g["url"], "primary": False,
                             "alt": f'{names.get(pid, "")} — {cfg["gallery_caption"]}'})
            for g in (gallery.get(page) or []):
                if g.get("chart") and g["url"] not in excluded:
                    rows.append({"url": g["url"], "primary": False,
                                 "alt": f'{names.get(pid, "")} — specification chart'})
            planned.append((pid, page, f, rows))

        distinct = sorted({r["url"] for _, _, _, rows in planned for r in rows})
        print(f"products targeted : {len(planned)}")
        print(f"skipped           : {len(skipped)}")
        print(f"excluded images   : {dropped} (excluded_images.json)")
        print(f"existing rows     : {len(existing)} (will be backed up then replaced)")
        print(f"new rows          : {sum(len(r[3]) for r in planned)} ({len(distinct)} distinct images)")
        for pid, page, why in skipped:
            print(f"  SKIP {pid} {page} -> {why}")

        if not args.apply:
            print("\nDRY RUN - nothing downloaded or written. Re-run with --apply.")
            return 0

        # Download + resize first: only an image we actually hold gets a row.
        local: dict[str, tuple[str, str]] = {}
        for i, src in enumerate(distinct, 1):
            got = localize(src)
            if got:
                local[src] = got
            else:
                print(f"  image FAIL {src}")
            if i % 25 == 0 or i == len(distinct):
                print(f"  localized {i}/{len(distinct)}")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = DATA_DIR / f"product_image_backup_{args.brand}_{stamp}.json"
        backup.write_text(json.dumps([dict(r) for r in existing], indent=1, default=str), encoding="utf-8")
        print(f"\nbacked up {len(existing)} existing rows -> {backup.name}")

        n = 0
        async with conn.transaction():
            await conn.execute("DELETE FROM product_image WHERE product_id = ANY($1::int[])", pids)
            for pid, page, f, rows in planned:
                kept = [r for r in rows if r["url"] in local]
                if not kept:
                    continue
                if not any(r["primary"] for r in kept):      # hero failed: promote the next photo
                    kept[0] = {**kept[0], "primary": True}
                for i, r in enumerate(kept):
                    big_url, thumb_url = local[r["url"]]
                    await conn.execute(
                        "INSERT INTO product_image "
                        "(product_id, url, thumb_url, source_url, alt_text, sort_order, is_primary, legacy_origin) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
                        pid, big_url, thumb_url, r["url"], r["alt"], i, r["primary"], origin,
                    )
                    n += 1
        print(f"inserted {n} rows across {len(planned)} products")

        chk = await conn.fetchrow(
            "SELECT count(*) FILTER (WHERE is_primary) AS primaries, count(*) AS total, "
            "count(*) FILTER (WHERE url LIKE 'http%') AS remote "
            "FROM product_image WHERE product_id = ANY($1::int[])", pids)
        print(f"verify: {chk['primaries']} primaries / {chk['total']} rows / {chk['remote']} pointing off-site")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
