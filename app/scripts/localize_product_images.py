#!/usr/bin/env python3
"""Localize remote product images onto titan-prod and serve them from /static.

WHY: 168k of the 170k product_image rows hot-link external hosts (mostly
storage.googleapis.com/aam-files). If a vendor pulls an image or a CDN hiccups,
the storefront dead-links. This downloads each distinct remote image, makes TWO
local sizes (1280px display + 400px grid thumb), writes them under
app/backend/static/product-images/, and repoints the DB at the local copies.

DISK-SAFE: images are fetched into MEMORY (BytesIO) and resized on the fly — the
full-size original is NEVER written to disk, so peak disk use is just the two
small outputs. (Originals would be ~60GB; the box only has ~33GB free. The two
resized sizes total ~20GB.) The script aborts if free disk drops below
--min-disk-gb so it can never fill the volume.

RESUMABLE + IDEMPOTENT: a row is "done" once its url points at /static/...;
re-running only processes rows still on http(s). The original remote URL is
preserved in a new `source_url` column (GCS stays the source of truth and we can
re-localize anytime). If output files already exist, the download is skipped and
only the DB is updated.

SCHEMA (added idempotently on first run):
  product_image.source_url TEXT  -- original remote URL
  product_image.thumb_url  TEXT  -- /static path to the 400px thumbnail
  product_image.url is rewritten to the /static path of the 1280px image, so the
  existing frontend (reads url / image_url) serves local with no code change.

USAGE (run ON titan-prod):
  cd /home/titan/titan-truck-website/app/backend
  .venv/bin/python ../scripts/localize_product_images.py --limit 30      # test
  .venv/bin/python ../scripts/localize_product_images.py                 # full
  nohup .venv/bin/python ../scripts/localize_product_images.py \
        > /home/titan/localize-images.log 2>&1 &                         # bg run
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import asyncpg
import httpx
from PIL import Image

# ---------------------------------------------------------------- config
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
STATIC_ROOT = BACKEND_DIR / "static" / "product-images"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

SIZE_BIG = 1280       # display (PDP). Measured: ~71KB/image-pair, full run ~10GB.
SIZE_THUMB = 400      # grid card
Q_BIG = 85
Q_THUMB = 82

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("localize")


def db_dsn() -> str:
    """Read DATABASE_URL from app/.env and return a plain asyncpg DSN."""
    url = None
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            url = line.split("=", 1)[1].strip()
            break
    if not url:
        raise SystemExit("DATABASE_URL not found in app/.env")
    # asyncpg wants plain postgresql://, not the SQLAlchemy +asyncpg dialect
    return url.replace("postgresql+asyncpg://", "postgresql://")


def paths_for(source_url: str) -> tuple[str, Path, Path, str, str]:
    """Return (hash, big_path, thumb_path, big_url, thumb_url) for a source URL."""
    h = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
    shard = h[:2]
    d = STATIC_ROOT / shard
    big_p = d / f"{h}_{SIZE_BIG}.jpg"
    thumb_p = d / f"{h}_{SIZE_THUMB}.jpg"
    big_url = f"/static/product-images/{shard}/{h}_{SIZE_BIG}.jpg"
    thumb_url = f"/static/product-images/{shard}/{h}_{SIZE_THUMB}.jpg"
    return h, big_p, thumb_p, big_url, thumb_url


def flatten_onto_white(im: Image.Image) -> Image.Image:
    """Return an RGB copy, compositing any transparency onto white.

    `Image.convert("RGB")` on an RGBA image just drops the alpha channel and
    keeps whatever RGB sat underneath it. Manufacturer cut-outs are exported
    with black under the transparent pixels, so the plain convert turned every
    cut-out into a truck on a black rectangle. Compositing first is what makes
    a transparent PNG land on white the way it does in a browser.
    """
    has_alpha = im.mode in ("RGBA", "LA") or (
        im.mode == "P" and "transparency" in im.info
    )
    if not has_alpha:
        return im if im.mode == "RGB" else im.convert("RGB")
    im = im.convert("RGBA")
    canvas = Image.new("RGB", im.size, (255, 255, 255))
    canvas.paste(im, mask=im.split()[-1])
    return canvas


def make_sizes(source_url: str, data: bytes) -> None:
    """Resize `data` into the two local JPEGs. Runs in a thread (blocking)."""
    _, big_p, thumb_p, _, _ = paths_for(source_url)
    if big_p.exists() and thumb_p.exists():
        return
    big_p.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(BytesIO(data))
    im = flatten_onto_white(im)
    big = im.copy()
    big.thumbnail((SIZE_BIG, SIZE_BIG), Image.LANCZOS)
    big.save(big_p, "JPEG", quality=Q_BIG, optimize=True, progressive=True)
    small = im.copy()
    small.thumbnail((SIZE_THUMB, SIZE_THUMB), Image.LANCZOS)
    small.save(thumb_p, "JPEG", quality=Q_THUMB, optimize=True)


async def ensure_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "ALTER TABLE product_image ADD COLUMN IF NOT EXISTS source_url TEXT;"
    )
    await conn.execute(
        "ALTER TABLE product_image ADD COLUMN IF NOT EXISTS thumb_url TEXT;"
    )
    # Backfill source_url for every remote row so it survives the url rewrite.
    n = await conn.execute(
        "UPDATE product_image SET source_url = url "
        "WHERE source_url IS NULL AND url LIKE 'http%';"
    )
    log.info("schema ready; source_url backfill: %s", n)


async def pending_urls(conn: asyncpg.Connection, limit: int | None) -> list[str]:
    q = (
        "SELECT DISTINCT source_url FROM product_image "
        "WHERE url LIKE 'http%' AND source_url IS NOT NULL"
    )
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = await conn.fetch(q)
    return [r["source_url"] for r in rows]


def disk_free_gb() -> float:
    return shutil.disk_usage(STATIC_ROOT.parent).free / (1024 ** 3)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="process at most N distinct URLs (for testing)")
    ap.add_argument("--workers", type=int, default=12,
                    help="concurrent downloads (default 12)")
    ap.add_argument("--min-disk-gb", type=float, default=4.0,
                    help="abort if free disk drops below this (default 4)")
    args = ap.parse_args()

    STATIC_ROOT.mkdir(parents=True, exist_ok=True)
    dsn = db_dsn()
    conn = await asyncpg.connect(dsn)
    await ensure_schema(conn)
    urls = await pending_urls(conn, args.limit)
    total = len(urls)
    log.info("%d distinct remote URLs to localize. disk free: %.1f GB",
             total, disk_free_gb())
    if total == 0:
        await conn.close()
        log.info("nothing to do — all images already local.")
        return 0

    sem = asyncio.Semaphore(args.workers)
    pool = ThreadPoolExecutor(max_workers=args.workers)
    loop = asyncio.get_event_loop()
    done = failed = 0
    fail_log = open("/home/titan/localize-images.failures", "a")
    t0 = time.time()
    update_batch: list[tuple[str, str, str]] = []  # (big_url, thumb_url, source_url)
    abort = False

    async with httpx.AsyncClient(
        follow_redirects=True, timeout=httpx.Timeout(25.0),
        headers={"User-Agent": "TitanTruck-image-localizer/1.0"},
        limits=httpx.Limits(max_connections=args.workers + 4),
    ) as client:

        async def worker(src: str):
            nonlocal done, failed
            _, big_p, thumb_p, big_url, thumb_url = paths_for(src)
            try:
                if not (big_p.exists() and thumb_p.exists()):
                    async with sem:
                        r = await client.get(src)
                        r.raise_for_status()
                        data = r.content
                    await loop.run_in_executor(pool, make_sizes, src, data)
                update_batch.append((big_url, thumb_url, src))
                done += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                fail_log.write(f"{src}\t{type(e).__name__}: {e}\n")

        async def flush():
            if not update_batch:
                return
            await conn.executemany(
                "UPDATE product_image SET url=$1, thumb_url=$2 "
                "WHERE source_url=$3 AND url LIKE 'http%';",
                update_batch,
            )
            update_batch.clear()

        # Process in chunks so we can flush DB + check disk periodically.
        CHUNK = 400
        for i in range(0, total, CHUNK):
            if disk_free_gb() < args.min_disk_gb:
                log.error("ABORT: free disk %.1f GB < min %.1f GB. "
                          "Resume after freeing/expanding disk.",
                          disk_free_gb(), args.min_disk_gb)
                abort = True
                break
            chunk = urls[i:i + CHUNK]
            await asyncio.gather(*(worker(u) for u in chunk))
            await flush()
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0
            eta_min = ((total - done - failed) / rate / 60) if rate else 0
            log.info("…%d/%d done, %d failed | %.1f img/s | ETA %.0f min | disk %.1f GB",
                     done, total, failed, rate, eta_min, disk_free_gb())

        await flush()

    fail_log.close()
    pool.shutdown(wait=True)
    await conn.close()
    log.info("DONE: %d localized, %d failed%s. disk free %.1f GB. elapsed %.0f min.",
             done, failed, " (ABORTED early)" if abort else "",
             disk_free_gb(), (time.time() - t0) / 60)
    if failed:
        log.info("failures logged to /home/titan/localize-images.failures")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(asyncio.run(main()))
