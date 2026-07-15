"""Extract brand logos from PIES files into brand.logo_url.

Walks every PIES XML under wan_test_output/pace_poc/<BRAND>/, finds the first
DigitalAssets entry with AssetType=LGO, and updates the matching Brand row.

Usage:
    python app/scripts/extract_brand_logos.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings  # noqa: E402
from app.models import Brand  # noqa: E402


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("extract_brand_logos")


POC_BASE = REPO / "wan_test_output" / "pace_poc"
LOGO_ASSET_TYPES = {"LGO", "LOGO", "BLG", "BLO"}  # variations seen in PIES


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def find_logo_and_brand_in_pies(xml_path: Path) -> tuple[str | None, str | None]:
    """Stream-parse PIES looking for:
      - first DigitalAssets entry of type LGO/LOGO/BLG → (logo_uri)
      - the BrandLabel from any Item (== the canonical brand name)
    Returns (logo_uri, brand_label). Either may be None.
    """
    logo: str | None = None
    brand_label: str | None = None
    for ev, elem in ET.iterparse(str(xml_path), events=("end",)):
        tag = strip_ns(elem.tag)
        if tag == "Item":
            for child in elem:
                ctag = strip_ns(child.tag)
                if ctag == "BrandLabel" and not brand_label:
                    val = (child.text or "").strip()
                    if val:
                        brand_label = val
                if ctag == "DigitalAssets" and not logo:
                    for asset in child:
                        if strip_ns(asset.tag) != "DigitalFileInformation":
                            continue
                        atype = ""
                        uri = ""
                        for ac in asset:
                            act = strip_ns(ac.tag)
                            if act == "AssetType":
                                atype = (ac.text or "").strip().upper()
                            elif act == "URI":
                                uri = (ac.text or "").strip()
                        if atype in LOGO_ASSET_TYPES and uri:
                            if uri.lower().endswith((".pdf", ".doc", ".docx")):
                                continue
                            logo = uri
                            break
            elem.clear()
            if logo and brand_label:
                return logo, brand_label
    return logo, brand_label


async def main() -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        # Walk every brand directory
        brand_dirs = sorted([d for d in POC_BASE.iterdir() if d.is_dir()])
        log.info("Scanning %d brand directories", len(brand_dirs))

        updates = 0
        skipped = 0
        for d in brand_dirs:
            aaia = d.name
            pies = next(d.glob(f"AAM_{aaia}_PIES_*.xml"), None)
            if not pies:
                continue
            try:
                logo_url, brand_label = find_logo_and_brand_in_pies(pies)
            except Exception as e:
                log.warning("  %s: parse failed: %s", aaia, e)
                continue
            if not logo_url and not brand_label:
                skipped += 1
                continue

            # Pull current brand row to decide if we should rename
            existing = (await db.execute(
                select(Brand).where(Brand.aaia_code == aaia)
            )).scalar_one_or_none()
            if not existing:
                skipped += 1
                continue

            update_vals: dict = {}
            if logo_url:
                update_vals["logo_url"] = logo_url
            # Only rename if the current name is a placeholder ("Unknown (XXXX)")
            if brand_label and existing.name.startswith("Unknown ("):
                update_vals["name"] = brand_label
                # Also update slug from new name
                import re as _re
                slug = _re.sub(r"[^a-z0-9]+", "-",
                               brand_label.lower()).strip("-") or aaia.lower()
                update_vals["slug"] = slug[:200]

            if update_vals:
                await db.execute(
                    update(Brand).where(Brand.id == existing.id).values(**update_vals)
                )
                updates += 1
                renamed = "->" + update_vals.get("name", "") if "name" in update_vals else ""
                log.info("  %s [%s%s]: logo=%s",
                         aaia, existing.name, renamed,
                         (logo_url or "(none)")[-50:])
            else:
                skipped += 1

        await db.commit()
        log.info("Updated %d brands with logos, skipped %d", updates, skipped)

        # Coverage
        total = (await db.execute(
            select(Brand).where(Brand.aaia_code.is_not(None))
        )).all()
        with_logo = (await db.execute(
            select(Brand).where(Brand.aaia_code.is_not(None), Brand.logo_url.is_not(None))
        )).all()
        log.info("Coverage: %d of %d AAIA-coded brands have logos (%.0f%%)",
                 len(with_logo), len(total),
                 100 * len(with_logo) / max(1, len(total)))

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
