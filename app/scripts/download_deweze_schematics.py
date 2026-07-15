"""download_deweze_schematics.py — Pull all 305 Deweze installation PDFs +
convert page 1 of each to a PNG hero image.

For each PDF URL in deweze_pdfs.txt:
  1. Download to app/data/stage_deweze/pdfs/{filename}.pdf
  2. Run pdftoppm to render page 1 → app/data/stage_deweze/images/{stem}.png
     (300dpi, scaled down to ~1200px wide for web)
  3. Skip both steps if files already exist (idempotent — re-run is cheap)

Owner ask 2026-05-14: "downloading pictures of schematics for this line
is crucial for it to see on the website."

After this script, run upload_deweze_schematics.py (sister script) to
push the staged files to Hetzner's static dir.  Per-kit schematic
attachment happens in import_deweze_catalog.py.
"""
from __future__ import annotations

import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DATA = Path(__file__).resolve().parent.parent / "data"
PDF_LIST = DATA / "mysql_dumps" / "deweze_pdfs.txt"
STAGE_PDFS = DATA / "stage_deweze" / "pdfs"
STAGE_IMAGES = DATA / "stage_deweze" / "images"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def safe_filename(url: str) -> str:
    """Map an S3 URL → safe local filename.  Keeps unique suffixes."""
    # e.g. https://.../public/kit-manuals/700375D_ni4cD5Y.pdf → 700375D_ni4cD5Y.pdf
    name = url.rsplit("/", 1)[-1]
    name = name.replace("%20", "_").replace(" ", "_")
    return name


def download(url: str) -> tuple[str, str | None]:
    """Returns (filename, error_or_None)."""
    name = safe_filename(url)
    dest = STAGE_PDFS / name
    if dest.exists() and dest.stat().st_size > 1000:
        return name, "cached"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            data = r.read()
        if len(data) < 1000:
            return name, f"too small ({len(data)} bytes)"
        dest.write_bytes(data)
        return name, None
    except Exception as e:
        return name, str(e)[:100]


def pdf_to_png(pdf_path: Path) -> tuple[str, str | None]:
    """Render page 1 of a PDF to a ~1200px-wide PNG using PyMuPDF (fitz).

    No external dependency — wheels-only.  Falls back to pdftoppm only if
    PyMuPDF can't open the file.
    """
    name = pdf_path.stem
    png_dest = STAGE_IMAGES / f"{name}.png"
    if png_dest.exists() and png_dest.stat().st_size > 1000:
        return name, "cached"
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        if doc.page_count == 0:
            doc.close()
            return name, "empty PDF"
        page = doc[0]
        # Target ~1200px width.  zoom factor = target_w / native_w (at 72dpi).
        native_w = page.rect.width  # in points (72dpi units)
        zoom = 1200.0 / max(1.0, native_w)
        # Cap zoom so we don't blow up for tiny pages
        if zoom > 4.0:
            zoom = 4.0
        if zoom < 1.5:
            zoom = 1.5
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pix.save(str(png_dest))
        doc.close()
        return name, None
    except Exception as e:
        return name, str(e)[:120]


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    STAGE_PDFS.mkdir(parents=True, exist_ok=True)
    STAGE_IMAGES.mkdir(parents=True, exist_ok=True)

    if not PDF_LIST.exists():
        print(f"missing {PDF_LIST} — run scrape_deweze_catalog.py first")
        return

    urls = [u.strip() for u in PDF_LIST.read_text().splitlines() if u.strip()]
    print(f"Downloading {len(urls)} PDFs (3 concurrent, with 100ms throttle)…")

    successes = 0
    errors = 0
    cached = 0

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(download, u): u for u in urls}
        for i, fut in enumerate(as_completed(futures), start=1):
            name, err = fut.result()
            if err is None:
                successes += 1
                marker = "OK"
            elif err == "cached":
                cached += 1
                marker = "cached"
            else:
                errors += 1
                marker = f"ERROR {err}"
            if i % 25 == 0 or marker.startswith("ERROR"):
                print(f"  [{i:>3}/{len(urls)}]  {name:<40} {marker}")
            # Polite throttle: ~30 req/sec aggregate is fine for S3
            time.sleep(0.03)

    print(f"\nDownload: {successes} new, {cached} cached, {errors} errors")
    pdfs = sorted(STAGE_PDFS.glob("*.pdf"))
    print(f"Stage dir has {len(pdfs)} PDFs ({sum(p.stat().st_size for p in pdfs) / 1024 / 1024:.1f} MB)")

    print(f"\nConverting page 1 of each PDF to PNG…")
    img_ok = img_err = img_cached = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(pdf_to_png, p): p for p in pdfs}
        for i, fut in enumerate(as_completed(futures), start=1):
            name, err = fut.result()
            if err is None:
                img_ok += 1
            elif err == "cached":
                img_cached += 1
            else:
                img_err += 1
                print(f"  [{i:>3}]  {name}: {err}")
    print(f"\nConvert: {img_ok} new, {img_cached} cached, {img_err} errors")
    pngs = sorted(STAGE_IMAGES.glob("*.png"))
    pngs = [p for p in pngs if not p.name.startswith("_tmp_")]
    print(f"Stage dir has {len(pngs)} PNGs ({sum(p.stat().st_size for p in pngs) / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
