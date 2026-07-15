"""Download all Buyers Products install PDFs from the CDN to /tmp/buyers_pdfs/.

Reads ProductResource rows from the DB, downloads each PDF that isn't already local.
"""
from __future__ import annotations
import asyncio, sys, os, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import select, or_
from app.database import async_session, engine
engine.echo = False
engine.sync_engine.echo = False
from app.models import Brand, Product, ProductResource

PDF_DIR = Path("/tmp/buyers_pdfs")
CDN_BASE = "https://pimimages.buyersproducts.com/products/Documents/"


async def get_pdf_urls():
    """Get all PDF resource URLs from the DB for Buyers/SnowDogg products."""
    async with async_session() as db:
        brand_filter = or_(Brand.name.ilike("%buyers%"), Brand.name.ilike("%snowdogg%"))
        rows = (await db.execute(
            select(ProductResource.url, ProductResource.description, Product.sku)
            .join(Product).join(Brand)
            .where(brand_filter, ProductResource.url.ilike("%.pdf"))
        )).all()
        return rows


async def download_pdfs():
    import urllib.request, ssl

    PDF_DIR.mkdir(parents=True, exist_ok=True)

    rows = await get_pdf_urls()
    print(f"Found {len(rows)} PDF resources in DB")

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for url, desc, sku in rows:
        if url not in seen_urls:
            seen_urls.add(url)
            unique.append((url, desc, sku))
    print(f"Unique URLs: {len(unique)}")

    # Check what's already downloaded
    existing = {f.name for f in PDF_DIR.glob("*.pdf")}
    to_download = []
    for url, desc, sku in unique:
        filename = url.rsplit("/", 1)[-1] if "/" in url else url
        if filename not in existing:
            to_download.append((url, filename, desc, sku))

    print(f"Already downloaded: {len(existing)}")
    print(f"To download: {len(to_download)}")

    if not to_download:
        print("Nothing to download!")
        return

    # Download with urllib (no aiohttp needed)
    downloaded = 0
    failed = 0
    ctx = ssl.create_default_context()

    for i, (url, filename, desc, sku) in enumerate(to_download):
        if not url.startswith("http"):
            full_url = CDN_BASE + url
        else:
            full_url = url

        try:
            req = urllib.request.Request(full_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            })
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                content = resp.read()
                out_path = PDF_DIR / filename
                out_path.write_bytes(content)
                size_kb = len(content) / 1024
                downloaded += 1
                print(f"  [{i+1}/{len(to_download)}] {filename} ({size_kb:.0f} KB)")
        except Exception as e:
            failed += 1
            print(f"  [{i+1}/{len(to_download)}] FAIL {filename}: {e}")

        # Rate limit
        if i < len(to_download) - 1:
            time.sleep(0.15)

    print(f"\nDone: {downloaded} downloaded, {failed} failed")
    print(f"Total PDFs on disk: {len(list(PDF_DIR.glob('*.pdf')))}")


if __name__ == "__main__":
    asyncio.run(download_pdfs())
