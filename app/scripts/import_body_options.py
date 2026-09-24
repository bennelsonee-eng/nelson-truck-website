"""Load harvested factory body options and attach them to the bodies they fit.

Knapheide and CM publish an options set per body family -- grain sides, swing-out
rear gates, contractor packages, cargo tie downs. Ben, 2026-09-24: none of it was
on our site, so a customer had no way to see what a body can be built with.

Input is one harvest directory per brand:

    <dir>/options.csv     brand,family,model_page_url,model_name,option_name,
                          option_slug,description,image_url,image_file,sort_order,notes
    <dir>/images/<file>   the maker's render, already downloaded

Images are copied onto our own server (never hotlinked) under
``backend/static/body-options/<brand>/<family>/`` with a 600px thumb beside the
full-size file. Options are keyed on (brand, family, slug), so a re-run updates
in place instead of duplicating.

Linking is by FAMILY_RULES below: each harvested family names the SKU prefixes
and product-name patterns of the bodies it belongs to. Only links stamped
``body-option-rules`` are rebuilt, so anything attached by hand in the app
survives a re-run.

    PYTHONPATH=/home/titan/nelson-truck-website/app/backend \
      /home/titan/nelson-truck-website/app/backend/.venv/bin/python \
      -m scripts.import_body_options --dir ../data/body_options/cm --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select

from app.database import async_session
from app.models import BodyOption, Brand, Product, ProductBodyOption

log = logging.getLogger("body_options")

STATIC_ROOT = Path(__file__).resolve().parent.parent / "backend" / "static" / "body-options"
THUMB_WIDTH = 600


@dataclass(frozen=True)
class FamilyRule:
    """Which body products a harvested option family belongs to.

    ``sku_prefixes`` match the SKU after its brand prefix (and after a repeated
    prod code, e.g. ``KNP-KNPPVMX-95``). ``name_patterns`` are regexes against
    the product name, for the ported marketing records whose SKU is a
    meaningless S-number -- which is every CM body we carry.
    """

    brand: str
    family: str
    sku_prefixes: tuple[str, ...] = ()
    name_patterns: tuple[str, ...] = field(default=())


# Knapheide and CM sell options by body LINE, not by individual model: every
# 600-series service body takes the same option set, every PVMX platform the
# same one. The rules below follow those lines.
#
# CM's families are read off the product name because our CM SKUs are ported
# S-numbers with nothing model-ish in them ("CMT-S17870" = "SK Steel Utility
# Body"). The deluxe variants are deliberately narrower than the base ones so a
# deluxe body gets its own set rather than both.
FAMILY_RULES: tuple[FamilyRule, ...] = (
    # --- Knapheide -------------------------------------------------------
    # Knapheide's steel and aluminum bodies really do differ: the steel service
    # body carries 12 options the aluminum one doesn't (torsion box floor, cab
    # guard, canopy roof, crane reinforcement), so they stay separate families.
    FamilyRule("Knapheide", "SERVICE_STEEL", ("696", "682", "698", "6108", "6132"),
               # the combo body has its own set, so it must not read as steel too
               (r"(?<!combo )\bsteel service body\b", r"\blow profile steel\b")),
    FamilyRule("Knapheide", "SERVICE_ALUMINUM", (),
               (r"\baluminum (fliptop|standard|low pro)\b",)),
    FamilyRule("Knapheide", "SERVICE_COMBO", (), (r"\bcombo steel\b",)),
    FamilyRule("Knapheide", "SERVICE_LINE", (), (r"\bline body\b",)),
    FamilyRule("Knapheide", "MECHANICS", ("KMT", "KMS"), (r"\bmechanic",)),
    FamilyRule("Knapheide", "KUV", (), (r"\bKUV\b(?!.*(cab chassis|chassis cab))",)),
    FamilyRule("Knapheide", "KUVCC", (), (r"\bKUV\b.*(cab chassis|chassis cab)",)),
    # PX/PXS are the legacy steel platform bodies Knapheide replaced with the
    # Value-Master X, so they take the PVMX set (harvest note, 2026-09-24).
    FamilyRule("Knapheide", "PVMX", ("PVMX", "PVMXS", "PVMXT", "PX", "PXS"),
               (r"value-master-x", r"\bflatbed\b")),
    FamilyRule("Knapheide", "PLATFORM_ALUMINUM", (), (r"\baluminum platform body\b",)),
    # PGNA has no page of its own; it maps onto the PGT pages the harvest read.
    FamilyRule("Knapheide", "GOOSENECK",
               ("PGTB", "PGTC", "PGTD", "PGTE", "PGNA", "PGNB", "PGNC", "PGND", "NGB"),
               (r"\bgooseneck\b",)),
    FamilyRule("Knapheide", "CARGO_HAULER", (), (r"cargo[- ]hauler",)),
    FamilyRule("Knapheide", "HEAVY_HAULER", (), (r"heavy[- ]hauler",)),
    FamilyRule("Knapheide", "DUMP", ("PDUMP",), (r"\bdump body\b",)),
    FamilyRule("Knapheide", "CONTRACTOR", ("PCON",), (r"\bcontractor body\b",)),
    FamilyRule("Knapheide", "CONCRETE", (), (r"\bconcrete body\b",)),
    FamilyRule("Knapheide", "LANDSCAPE", (), (r"\blandscaper? body\b",)),
    FamilyRule("Knapheide", "FORESTRY", (), (r"\bforestry body\b",)),
    FamilyRule("Knapheide", "SERVICE_CRANE", (), (r"\bcrane body\b",)),
    FamilyRule("Knapheide", "FUEL_LUBE", (), (r"fuel[- ]lube",)),
    FamilyRule("Knapheide", "WATER", (), (r"\bwater (body|truck)\b",)),
    # --- CM Truck Beds ---------------------------------------------------
    FamilyRule("CM Truck Beds", "RD", name_patterns=(r"^RD\b",)),
    FamilyRule("CM Truck Beds", "ALRD", name_patterns=(r"^AL RD\b",)),
    FamilyRule("CM Truck Beds", "SK", name_patterns=(r"^SK\b", r"^SB\b")),
    FamilyRule("CM Truck Beds", "ALSK", name_patterns=(r"^AL SK\b", r"^SBA\b")),
    # "TM/TMX Steel Tradesmen" is the base line; "TM Deluxe" is the TMX one.
    FamilyRule("CM Truck Beds", "TM", name_patterns=(r"^TM(?! Deluxe)\b",)),
    FamilyRule("CM Truck Beds", "TMX", name_patterns=(r"^TMX\b", r"^TM Deluxe\b")),
    FamilyRule("CM Truck Beds", "ER", name_patterns=(r"^ER\b", r"^WD\b")),
    FamilyRule("CM Truck Beds", "ALER", name_patterns=(r"^AL ER\b",)),
    # CM's "CB Component Body" page is really the CMG Convertible -- Nelson's G
    # -- and Nelson's CB (12ft contractor bed) is CM's CT Contractor Body. The
    # harvest mapped on ERP descriptions, not on CM's slugs (harvest note,
    # 2026-09-24), so G deliberately does NOT match "GP Steel Gin Pole Body".
    FamilyRule("CM Truck Beds", "G", name_patterns=(r"\bgenesis\b", r"\bconvertible\b")),
    FamilyRule("CM Truck Beds", "CB", name_patterns=(r"^CB\b", r"\bcontractor body\b")),
)

SLUG_RE = re.compile(r"[^a-z0-9]+")

# Column-name variants a harvest might use, mapped to what we store.
ALIASES = {
    "name": ("option_name", "name", "option", "title"),
    "slug": ("option_slug", "slug"),
    "description": ("description", "desc", "copy"),
    "image_file": ("image_file", "image", "local_image"),
    "source_url": ("model_page_url", "source_url", "url", "page_url"),
    "model_name": ("model_name", "model"),
    "sort_order": ("sort_order", "order", "position"),
    "notes": ("notes", "note"),
}


def slugify(text: str) -> str:
    return SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")[:190] or "option"


def pick(row: dict[str, str], key: str) -> str:
    for candidate in ALIASES[key]:
        if row.get(candidate):
            return row[candidate]
    return ""


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        raw = list(csv.DictReader(fh))
    out: list[dict[str, str]] = []
    for r in raw:
        row = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip()
               for k, v in r.items() if k}
        rec = {
            "brand": row.get("brand", ""),
            "family": row.get("family") or row.get("series") or "",
            "name": pick(row, "name"),
            "description": pick(row, "description"),
            "image_file": pick(row, "image_file"),
            "source_url": pick(row, "source_url"),
            "model_name": pick(row, "model_name"),
            "sort_order": pick(row, "sort_order"),
            "notes": pick(row, "notes"),
        }
        if not (rec["brand"] and rec["family"] and rec["name"]):
            log.warning("skipping row with no brand/family/name: %r", row)
            continue
        rec["slug"] = pick(row, "slug") or slugify(rec["name"])
        out.append(rec)
    return out


def place_image(row: dict[str, str], src_dir: Path, static_root: Path,
                dry_run: bool) -> tuple[str | None, str | None]:
    """Copy the harvested render under /static and return (full_url, thumb_url)."""
    rel = (row.get("image_file") or "").replace("\\", "/")
    if not rel or rel.startswith("http"):
        # A URL we never downloaded is not ours to serve -- leave the option
        # without a picture rather than hotlinking the manufacturer.
        return None, None
    src = (src_dir / rel).resolve()
    if not src.exists():
        log.warning("image missing for %s / %s: %s", row["family"], row["name"], rel)
        return None, None

    ext = src.suffix.lower() or ".jpg"
    brand_dir, fam_dir, stem = slugify(row["brand"]), slugify(row["family"]), row["slug"]
    dest_dir = static_root / brand_dir / fam_dir
    dest = dest_dir / f"{stem}{ext}"
    thumb = dest_dir / f"{stem}_{THUMB_WIDTH}{ext}"
    url = f"/static/body-options/{brand_dir}/{fam_dir}/{dest.name}"
    thumb_url = f"/static/body-options/{brand_dir}/{fam_dir}/{thumb.name}"
    if dry_run:
        return url, thumb_url

    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    try:
        from PIL import Image

        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.width > THUMB_WIDTH:
                im = im.resize((THUMB_WIDTH, round(im.height * THUMB_WIDTH / im.width)),
                               Image.LANCZOS)
            im.save(thumb, quality=86)
    except Exception as exc:  # noqa: BLE001 -- a thumb is a nicety; the full image still shows
        log.warning("thumb failed for %s (%s); serving the full image", dest.name, exc)
        thumb_url = url
    return url, thumb_url


def model_code(sku: str) -> str:
    """The manufacturer's model out of our SKU: KNP-KNPPVMX-95 -> PVMX-95."""
    body = sku.split("-", 1)[1] if "-" in sku else sku
    # Several ERP SKUs repeat the prod code inside the part number.
    for pc in ("KNP", "CMT", "CM"):
        if body.upper().startswith(pc):
            body = body[len(pc):]
            break
    return body.upper().lstrip("-")


def families_for(sku: str, name: str, rules: list[FamilyRule]) -> list[FamilyRule]:
    """The option families a body product belongs to.

    A model code in the SKU is the stronger signal and wins outright: without
    that precedence "BODY, FLATBED 8'GOOSENECK" (KNP-KNPPGTB-868-F) would take
    the platform options too, because its name says flatbed. Names are the
    fallback for the ported marketing records, whose SKU is a meaningless
    S-number -- which is every CM body we carry.
    """
    code = model_code(sku)
    by_sku = [r for r in rules if any(code.startswith(p.upper()) for p in r.sku_prefixes)]
    if by_sku:
        return by_sku
    clean = (name or "").strip()
    return [r for r in rules if any(re.search(p, clean, re.I) for p in r.name_patterns)]


async def run(dirs: list[Path], static_root: Path, dry_run: bool) -> int:
    rows: list[dict[str, str]] = []
    for d in dirs:
        csv_path = d / "options.csv"
        if not csv_path.exists():
            log.error("no options.csv in %s", d)
            return 2
        found = read_rows(csv_path)
        for r in found:
            r["_dir"] = str(d)
        log.info("%s: %d options", d.name, len(found))
        rows.extend(found)
    if not rows:
        log.error("nothing to import")
        return 2

    flagged = [r for r in rows if re.search(r"VERIFY|CAUTION", r.get("notes", ""), re.I)]
    if flagged:
        log.warning("%d options carry a harvest VERIFY/CAUTION note; first few:", len(flagged))
        for r in flagged[:5]:
            log.warning("  %s %s / %s -- %s", r["brand"], r["family"], r["name"], r["notes"][:120])

    async with async_session() as db:
        brands = {b.name for b in (await db.execute(select(Brand))).scalars()}
        unknown = {r["brand"] for r in rows} - brands
        if unknown:
            log.warning("options name brands the site doesn't have: %s", sorted(unknown))

        # --- upsert the options themselves --------------------------------
        existing = {(o.brand, o.family, o.slug): o
                    for o in (await db.execute(select(BodyOption))).scalars()}
        added = updated = 0
        by_key: dict[tuple[str, str, str], BodyOption] = {}
        for i, r in enumerate(rows):
            url, thumb = place_image(r, Path(r["_dir"]), static_root, dry_run)
            key = (r["brand"], r["family"], r["slug"])
            fields = {
                "name": r["name"][:200],
                "description": r["description"] or None,
                "image_url": url,
                "thumb_url": thumb,
                "source_url": (r["source_url"] or None) and r["source_url"][:600],
                "model_name": r["model_name"] or None,
                "sort_order": int(r["sort_order"]) if r["sort_order"].isdigit() else i,
            }
            opt = existing.get(key)
            if opt is None:
                opt = BodyOption(brand=key[0], family=key[1], slug=key[2], **fields)
                if not dry_run:
                    db.add(opt)
                added += 1
            else:
                for k, v in fields.items():
                    setattr(opt, k, v)
                updated += 1
            by_key[key] = opt
        if not dry_run:
            await db.flush()

        # --- attach them to the bodies ------------------------------------
        products = (await db.execute(
            select(Product.id, Product.sku, Product.name, Brand.name)
            .join(Brand, Brand.id == Product.brand_id)
            .where(Brand.name.in_({r["brand"] for r in rows}),
                   Product.show_all_branch_stock.is_(True))
        )).all()

        # Only the families we actually harvested can be linked.
        harvested = {(k[0], k[1]) for k in by_key}
        live_rules = [r for r in FAMILY_RULES if (r.brand, r.family) in harvested]
        options_by_family = {
            (b, f): sorted((o for k, o in by_key.items() if k[0] == b and k[1] == f),
                           key=lambda o: o.sort_order)
            for b, f in harvested
        }

        links: list[tuple[int, int, int]] = []
        per_family: dict[tuple[str, str], int] = {k: 0 for k in harvested}
        for pid, sku, pname, pbrand in products:
            brand_rules = [r for r in live_rules if r.brand == pbrand]
            for rule in families_for(sku, pname, brand_rules):
                per_family[(rule.brand, rule.family)] += 1
                for n, o in enumerate(options_by_family[(rule.brand, rule.family)]):
                    links.append((pid, 0 if dry_run else o.id, n))

        for key, n in sorted(per_family.items()):
            if n == 0:
                log.warning("%s family %s has options but matched no body product", *key)

        if dry_run:
            log.info("DRY RUN: would add %d options, update %d", added, updated)
            for (brand, fam), n in sorted(per_family.items()):
                log.info("  %s %s -> %d bodies", brand, fam, n)
            log.info("  %d product/option links in total", len(links))
            return 0

        await db.execute(
            delete(ProductBodyOption).where(ProductBodyOption.source == "body-option-rules"))
        seen: set[tuple[int, int]] = set()
        for pid, oid, order in links:
            if (pid, oid) in seen:
                continue
            seen.add((pid, oid))
            db.add(ProductBodyOption(product_id=pid, body_option_id=oid, sort_order=order,
                                     source="body-option-rules"))
        await db.commit()

    log.info("options: %d added, %d updated; %d links across %d bodies",
             added, updated, len(seen), len({p for p, _ in seen}))
    for (brand, fam), n in sorted(per_family.items()):
        log.info("  %s %s -> %d bodies", brand, fam, n)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", required=True, type=Path,
                    help="a harvest directory holding options.csv and images/ (repeatable)")
    ap.add_argument("--static-root", type=Path, default=STATIC_ROOT)
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return asyncio.run(run(args.dir, args.static_root, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
