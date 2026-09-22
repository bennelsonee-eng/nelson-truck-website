"""Attach self-hosted walkaround videos to the truck-body products.

Reads discovery/manufacturer_data/kn_videos.json. Each entry names a file that
must already sit in app/backend/static/product-videos/<source>/ -- this script
never links an outside player. A video whose file isn't there is reported and
skipped, so the product page can only ever show a video we are serving.

For each file present it:
  * remuxes to "faststart" MP4 (moov atom first) so playback starts before the
    whole file downloads -- stream copy, no re-encode, no quality change;
  * writes a poster frame beside it (clip.mp4 -> clip.jpg), which the product
    page shows until the customer presses play;
  * replaces this source's video rows on each listed product (product_resource,
    kind='video', url=/static/product-videos/...).

Needs ffmpeg on PATH (or FFMPEG=<path>). Dry run unless --apply.

Usage:
    python app/scripts/import_manufacturer_body_videos.py
    python app/scripts/import_manufacturer_body_videos.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import asyncpg

HERE = Path(__file__).resolve()
APP_DIR = HERE.parent.parent
ENV_FILE = APP_DIR / ".env"
DATA_DIR = APP_DIR.parent / "discovery" / "manufacturer_data"
SOURCE = "knapheide.com"
VIDEO_DIR = APP_DIR / "backend" / "static" / "product-videos" / SOURCE
URL_BASE = f"/static/product-videos/{SOURCE}"


def db_dsn() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().replace("postgresql+asyncpg://", "postgresql://")
    raise SystemExit("DATABASE_URL not found in app/.env")


def ffmpeg_bin() -> str:
    exe = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("ffmpeg not found (install it or set FFMPEG=<path>)")
    return exe


def is_faststart(path: Path) -> bool:
    """True when the 'moov' box comes before 'mdat' in the first few MB."""
    with path.open("rb") as f:
        head = f.read(8 * 1024 * 1024)
    m, d = head.find(b"moov"), head.find(b"mdat")
    return m != -1 and (d == -1 or m < d)


def prepare(ff: str, path: Path) -> Path:
    """Faststart remux (in place) + poster frame. Returns the poster path."""
    if not is_faststart(path):
        tmp = path.with_suffix(".faststart.mp4")
        subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(path), "-c", "copy",
                        "-movflags", "+faststart", str(tmp)], check=True)
        tmp.replace(path)
    poster = path.with_suffix(".jpg")
    if not poster.exists():
        # 3 s in skips a black lead-in / logo sting; 1280 wide matches our product images.
        subprocess.run([ff, "-y", "-loglevel", "error", "-ss", "3", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(poster)], check=True)
    return poster


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="prepare files + write rows (default: dry run)")
    args = ap.parse_args()

    spec = json.loads((DATA_DIR / "kn_videos.json").read_text(encoding="utf-8"))["videos"]
    present = [v for v in spec if (VIDEO_DIR / v["file"]).exists()]
    missing = [v for v in spec if v not in present]
    pids = sorted({p for v in spec for p in v["products"]})

    print(f"videos listed    : {len(spec)}")
    print(f"files present    : {len(present)}  in {VIDEO_DIR}")
    for v in missing:
        print(f"  MISSING (skipped, not linked): {v['file']}  <- {v['youtube_title']}")
    print(f"products touched : {len(pids)}")

    if not args.apply:
        print("\nDRY RUN - nothing prepared or written. Re-run with --apply.")
        return 0

    ff = ffmpeg_bin()
    for v in present:
        path = VIDEO_DIR / v["file"]
        prepare(ff, path)
        print(f"  ready  {v['file']}  ({path.stat().st_size / 1e6:.0f} MB)")

    conn = await asyncpg.connect(db_dsn())
    try:
        before = [dict(r) for r in await conn.fetch(
            "SELECT * FROM product_resource WHERE product_id = ANY($1::int[]) AND source=$2 AND kind='video'",
            pids, SOURCE)]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (DATA_DIR / f"video_backup_{stamp}.json").write_text(
            json.dumps(before, indent=1, default=str), encoding="utf-8")
        n = 0
        async with conn.transaction():
            await conn.execute("DELETE FROM product_resource WHERE product_id = ANY($1::int[]) "
                               "AND source=$2 AND kind='video'", pids, SOURCE)
            for pid in pids:
                for i, v in enumerate(x for x in present if pid in x["products"]):
                    await conn.execute(
                        "INSERT INTO product_resource (product_id, kind, url, title, description, sort_order, source) "
                        "VALUES ($1,'video',$2,$3,$4,$5,$6) ON CONFLICT (product_id, url) DO NOTHING",
                        pid, f"{URL_BASE}/{v['file']}", v["title"],
                        f"Source: Knapheide, youtube {v['youtube_id']}", 100 + i, SOURCE)
                    n += 1
        print(f"\nwrote {n} video rows across {len(pids)} products (backup: video_backup_{stamp}.json)")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
