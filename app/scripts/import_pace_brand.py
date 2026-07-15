"""Ingest one PACE brand's ACES + PIES XML pair into Postgres.

Streaming, memory-efficient (uses ElementTree.iterparse + element.clear()).
Idempotent at the brand level: re-running deletes the brand's pace_part
+ pace_fitment rows and re-inserts. PIES side tables (product_attribute,
product_description, etc.) similarly refreshed for products owned by this
brand.

VCdb + PCdb reference rows are upserted as we encounter unknown IDs — so
running brands one after another incrementally builds out the reference
catalog without needing the Auto Care VCdb/PCdb dumps separately.

Usage:
    python app/scripts/import_pace_brand.py BDKW
    python app/scripts/import_pace_brand.py BDKW --aces-only
    python app/scripts/import_pace_brand.py BDKW --pies-only
    python app/scripts/import_pace_brand.py --all-discovered     # ingest every brand pair under wan_test_output/pace_poc/
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# Make the backend package importable when run as a script
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app" / "backend"))

from app.config import get_settings  # noqa: E402
from app.models import (  # noqa: E402
    Brand,
    PacePart,
    PaceFitment,
    PcdbPartType,
    PcdbPosition,
    Product,
    ProductAttribute,
    ProductDescription,
    ProductImage,
    ProductPackage,
    ProductPricing,
    VcdbAspiration,
    VcdbBaseVehicle,
    VcdbBedLength,
    VcdbBedType,
    VcdbBodyType,
    VcdbDriveType,
    VcdbEngineBase,
    VcdbFuelType,
    VcdbMake,
    VcdbModel,
    VcdbRegion,
    VcdbSubModel,
)
from app.models.catalog import CTAMode  # noqa: E402


logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("import_pace")
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


POC_BASE = REPO / "wan_test_output" / "pace_poc"
DCI_CSV = REPO / "app" / "data" / "mysql_dumps" / "dci_codes.csv"


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# --------------------------------------------------------------------------- #
# Brand identity
# --------------------------------------------------------------------------- #


def load_dci_brand_lookup() -> dict[str, dict[str, str]]:
    """Returns {aaia_code: {dci_code, prod_code, manu_title, cat_id}}."""
    import csv
    out: dict[str, dict[str, str]] = {}
    if not DCI_CSV.exists():
        log.warning("DCI CSV not found at %s — brand names will fall back to AAIA code", DCI_CSV)
        return out
    with open(DCI_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ac = row.get("aaia_code", "").strip()
            if ac:
                out[ac] = row
    return out


async def upsert_brand(db: AsyncSession, aaia_code: str, parent_aaia_id: str | None,
                       brand_label: str | None, dci_lookup: dict) -> int:
    """Upsert Brand row. Prefers DCI manu_title for the human name."""
    info = dci_lookup.get(aaia_code, {})
    name = info.get("manu_title") or brand_label or f"Unknown ({aaia_code})"
    prod_code = info.get("prod_code") or aaia_code
    slug = name.lower().replace(" ", "-").replace("/", "-")[:200] or aaia_code.lower()

    # Try by aaia_code first, then by name
    existing = (await db.execute(
        select(Brand).where(Brand.aaia_code == aaia_code)
    )).scalar_one_or_none()
    if not existing:
        existing = (await db.execute(
            select(Brand).where(Brand.name == name)
        )).scalar_one_or_none()

    if existing:
        existing.aaia_code = aaia_code
        existing.parent_aaia_id = parent_aaia_id
        await db.flush()
        return existing.id

    brand = Brand(
        name=name,
        slug=slug,
        aaia_code=aaia_code,
        parent_aaia_id=parent_aaia_id,
        is_active=True,
        is_featured=False,
        sort_order=1000,
    )
    db.add(brand)
    await db.flush()
    log.info("Created Brand id=%s name=%s aaia=%s", brand.id, brand.name, aaia_code)
    return brand.id


# --------------------------------------------------------------------------- #
# VCdb / PCdb upserts (cached in-memory per run for speed)
# --------------------------------------------------------------------------- #


class RefTableCache:
    """Tracks IDs we've already ensured exist this run, to avoid round-trips."""

    def __init__(self):
        self.seen: dict[str, set[int]] = defaultdict(set)

    async def ensure(self, db: AsyncSession, model, id_value: int,
                     defaults: dict | None = None) -> None:
        """INSERT ... ON CONFLICT DO NOTHING for any reference table."""
        if id_value is None:
            return
        key = model.__tablename__
        if id_value in self.seen[key]:
            return
        self.seen[key].add(id_value)

        cols = {"id": id_value}
        if defaults:
            cols.update(defaults)
        else:
            cols["name"] = f"VCdb#{id_value}"  # placeholder until real VCdb load

        stmt = pg_insert(model.__table__).values(**cols)
        stmt = stmt.on_conflict_do_nothing(index_elements=["id"])
        await db.execute(stmt)


# --------------------------------------------------------------------------- #
# ACES ingest
# --------------------------------------------------------------------------- #


def _int_or_none(s: str | None) -> int | None:
    if s is None or s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None


async def ingest_aces(db: AsyncSession, xml_path: Path, dci_lookup: dict) -> dict:
    """Stream-parse ACES, ensure VCdb/PCdb refs exist, insert pace_part + pace_fitment."""
    log.info("ACES: parsing %s (%.1f MB)", xml_path.name, xml_path.stat().st_size / 1e6)
    cache = RefTableCache()
    header: dict[str, str] = {}
    aaia_code: str | None = None
    brand_id: int | None = None
    parent_aaia_id: str | None = None

    # part_number -> pace_part_id (built up lazily as we encounter parts)
    part_id_map: dict[str, int] = {}
    fitment_buffer: list[dict] = []
    BUFFER_SIZE = 5000

    apps_seen = 0
    apps_inserted = 0
    skipped_orphan_basevehicle = 0

    t0 = time.time()
    for ev, elem in ET.iterparse(str(xml_path), events=("end",)):
        tag = strip_ns(elem.tag)

        if tag == "Header":
            for c in elem:
                header[strip_ns(c.tag)] = (c.text or "").strip()
            aaia_code = header.get("BrandAAIAID")
            if not aaia_code:
                raise RuntimeError("ACES Header missing BrandAAIAID")
            brand_id = await upsert_brand(db, aaia_code, parent_aaia_id, None, dci_lookup)

            # Wipe this brand's existing pace_part + fitments so re-ingest is clean
            await db.execute(text(
                "DELETE FROM pace_fitment WHERE pace_part_id IN "
                "(SELECT id FROM pace_part WHERE brand_id = :bid)"
            ), {"bid": brand_id})
            await db.execute(delete(PacePart).where(PacePart.brand_id == brand_id))
            await db.flush()
            elem.clear()
            continue

        if tag != "App":
            continue

        apps_seen += 1
        # Pull every child + attribute of <App>
        d: dict[str, str] = {"_action": elem.attrib.get("action", "")}
        for c in elem:
            ctag = strip_ns(c.tag)
            cid = c.attrib.get("id")
            cval = (c.text or "").strip() if c.text else ""
            d[ctag] = cid if cid else cval

        part_number = d.get("Part")
        base_vehicle_id = _int_or_none(d.get("BaseVehicle"))
        part_type_id = _int_or_none(d.get("PartType"))

        if not part_number or base_vehicle_id is None or part_type_id is None:
            skipped_orphan_basevehicle += 1
            elem.clear()
            continue

        # ---- Ensure all reference-table targets exist BEFORE inserting pace_part ----
        # PartType (referenced by pace_part.part_terminology_id AND pace_fitment.part_type_id)
        await db.execute(pg_insert(PcdbPartType.__table__).values(
            id=part_type_id, name=f"PartType#{part_type_id}"
        ).on_conflict_do_nothing(index_elements=["id"]))
        # Make/Model placeholder (id=0) for the year=0 stub BaseVehicle
        await db.execute(pg_insert(VcdbMake.__table__).values(
            id=0, name="UNKNOWN"
        ).on_conflict_do_nothing(index_elements=["id"]))
        await db.execute(pg_insert(VcdbModel.__table__).values(
            id=0, make_id=0, name="UNKNOWN"
        ).on_conflict_do_nothing(index_elements=["id"]))
        # BaseVehicle stub (year=0 until real VCdb is loaded)
        await db.execute(pg_insert(VcdbBaseVehicle.__table__).values(
            id=base_vehicle_id, year=0, make_id=0, model_id=0
        ).on_conflict_do_nothing(index_elements=["id"]))

        # ---- Now safe to upsert pace_part ----
        if part_number not in part_id_map:
            stmt = pg_insert(PacePart.__table__).values(
                brand_id=brand_id,
                part_number=part_number,
                short_description=d.get("MfrLabel", "")[:500] or None,
                part_terminology_id=part_type_id,
            ).on_conflict_do_update(
                constraint="uq_pace_part_brand_pn",
                set_={"short_description": d.get("MfrLabel", "")[:500] or None,
                      "part_terminology_id": part_type_id},
            ).returning(PacePart.id)
            res = await db.execute(stmt)
            part_id_map[part_number] = res.scalar_one()

        # Optional qualifiers — ensure each ref row before fitment insert
        sub_model_id = _int_or_none(d.get("SubModel"))
        if sub_model_id is not None:
            await cache.ensure(db, VcdbSubModel, sub_model_id, {"name": f"SubModel#{sub_model_id}"})
        position_id = _int_or_none(d.get("Position"))
        if position_id is not None:
            await cache.ensure(db, PcdbPosition, position_id, {"name": f"Position#{position_id}"})
        bed_length_id = _int_or_none(d.get("BedLength"))
        if bed_length_id is not None:
            await cache.ensure(db, VcdbBedLength, bed_length_id, {"label": f"BedLength#{bed_length_id}"})
        bed_type_id = _int_or_none(d.get("BedType"))
        if bed_type_id is not None:
            await cache.ensure(db, VcdbBedType, bed_type_id, {"name": f"BedType#{bed_type_id}"})
        body_type_id = _int_or_none(d.get("BodyType"))
        if body_type_id is not None:
            await cache.ensure(db, VcdbBodyType, body_type_id, {"name": f"BodyType#{body_type_id}"})
        drive_type_id = _int_or_none(d.get("DriveType"))
        if drive_type_id is not None:
            await cache.ensure(db, VcdbDriveType, drive_type_id, {"name": f"DriveType#{drive_type_id}"})
        engine_base_id = _int_or_none(d.get("EngineBase"))
        if engine_base_id is not None:
            await cache.ensure(db, VcdbEngineBase, engine_base_id, {"label": f"EngineBase#{engine_base_id}"})
        fuel_type_id = _int_or_none(d.get("FuelType"))
        if fuel_type_id is not None:
            await cache.ensure(db, VcdbFuelType, fuel_type_id, {"name": f"FuelType#{fuel_type_id}"})
        aspiration_id = _int_or_none(d.get("Aspiration"))
        if aspiration_id is not None:
            await cache.ensure(db, VcdbAspiration, aspiration_id, {"name": f"Aspiration#{aspiration_id}"})
        region_id = _int_or_none(d.get("Region"))
        if region_id is not None:
            await cache.ensure(db, VcdbRegion, region_id, {"name": f"Region#{region_id}"})

        # Anything else that isn't a first-class column goes into extra_qualifiers
        FIRST_CLASS = {
            "BaseVehicle", "PartType", "Part", "SubModel", "Position", "BedLength",
            "BedType", "BodyType", "BodyNumDoors", "DriveType", "EngineBase",
            "FuelType", "Aspiration", "Region", "Note", "Qty", "MfrLabel", "_action",
        }
        extra = {k: v for k, v in d.items() if k not in FIRST_CLASS}

        fitment_buffer.append({
            "pace_part_id": part_id_map[part_number],
            "base_vehicle_id": base_vehicle_id,
            "part_type_id": part_type_id,
            "sub_model_id": sub_model_id,
            "position_id": position_id,
            "bed_length_id": bed_length_id,
            "bed_type_id": bed_type_id,
            "body_type_id": body_type_id,
            "body_num_doors": _int_or_none(d.get("BodyNumDoors")),
            "drive_type_id": drive_type_id,
            "engine_base_id": engine_base_id,
            "fuel_type_id": fuel_type_id,
            "aspiration_id": aspiration_id,
            "region_id": region_id,
            "extra_qualifiers": extra or None,
            "qty": _int_or_none(d.get("Qty")) or 1,
            "mfr_label": (d.get("MfrLabel") or "")[:500] or None,
            "note": d.get("Note") or None,
        })
        elem.clear()

        if len(fitment_buffer) >= BUFFER_SIZE:
            await db.execute(pg_insert(PaceFitment.__table__), fitment_buffer)
            apps_inserted += len(fitment_buffer)
            fitment_buffer.clear()
            if apps_seen % 25000 == 0:
                log.info("  ACES progress: %s apps seen, %s fitments inserted (%.1fs)",
                         f"{apps_seen:,}", f"{apps_inserted:,}", time.time() - t0)

    if fitment_buffer:
        await db.execute(pg_insert(PaceFitment.__table__), fitment_buffer)
        apps_inserted += len(fitment_buffer)

    await db.commit()
    log.info("ACES done: %s apps -> %s fitments inserted, %s skipped, %.1fs",
             f"{apps_seen:,}", f"{apps_inserted:,}", skipped_orphan_basevehicle, time.time() - t0)
    return {"apps_seen": apps_seen, "fitments_inserted": apps_inserted, "brand_id": brand_id}


# --------------------------------------------------------------------------- #
# PIES ingest
# --------------------------------------------------------------------------- #


def _decimal_or_none(s: str | None) -> Decimal | None:
    if not s:
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _date_or_none(s: str | None):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


async def ingest_pies(db: AsyncSession, xml_path: Path, dci_lookup: dict) -> dict:
    log.info("PIES: parsing %s (%.1f MB)", xml_path.name, xml_path.stat().st_size / 1e6)

    header: dict[str, str] = {}
    items_seen = 0
    items_inserted = 0
    aaia_code: str | None = None
    brand_id: int | None = None

    t0 = time.time()
    for ev, elem in ET.iterparse(str(xml_path), events=("end",)):
        tag = strip_ns(elem.tag)

        if tag == "Header":
            for c in elem:
                header[strip_ns(c.tag)] = (c.text or "").strip()
            elem.clear()
            continue

        if tag == "PriceSheets":
            elem.clear()
            continue

        if tag != "Item":
            continue

        items_seen += 1
        # Item-level fields
        item_brand: str | None = None
        item_brand_label: str | None = None
        part_number: str | None = None
        part_terminology_id: int | None = None
        item_level_gtin: str | None = None   # UPC equivalent (I2)
        descriptions: list[dict] = []
        attributes: list[dict] = []
        packages: list[dict] = []
        digital_assets: list[dict] = []
        prices: list[dict] = []

        for c in elem:
            ctag = strip_ns(c.tag)
            if ctag == "PartNumber":
                part_number = (c.text or "").strip()
            elif ctag == "BrandAAIAID":
                item_brand = (c.text or "").strip()
            elif ctag == "BrandLabel":
                item_brand_label = (c.text or "").strip()
            elif ctag == "PartTerminologyID":
                part_terminology_id = _int_or_none(c.text)
            elif ctag == "ItemLevelGTIN":
                item_level_gtin = (c.text or "").strip() or None
            elif ctag == "Descriptions":
                for d in c:
                    if strip_ns(d.tag) == "Description":
                        descriptions.append({
                            "code": d.attrib.get("DescriptionCode", ""),
                            "lang": d.attrib.get("LanguageCode", "EN"),
                            "seq": _int_or_none(d.attrib.get("Sequence")) or 1,
                            "text": (d.text or "").strip(),
                        })
            elif ctag == "ProductAttributes":
                for a in c:
                    if strip_ns(a.tag) == "ProductAttribute":
                        attributes.append({
                            "key": a.attrib.get("AttributeID", "")[:120],
                            "uom": a.attrib.get("AttributeUOM", "")[:20],
                            "val": (a.text or "").strip(),
                        })
            elif ctag == "Packages":
                for p in c:
                    if strip_ns(p.tag) == "Package":
                        pkg = {strip_ns(pc.tag): (pc.text or "").strip() for pc in p}
                        packages.append(pkg)
            elif ctag == "DigitalAssets":
                for a in c:
                    if strip_ns(a.tag) == "DigitalFileInformation":
                        atype = ""
                        uri = ""
                        for ac in a:
                            act = strip_ns(ac.tag)
                            if act == "AssetType":
                                atype = (ac.text or "").strip()
                            elif act == "URI":
                                uri = (ac.text or "").strip()
                        digital_assets.append({"type": atype, "uri": uri})
            elif ctag == "Prices":
                for p in c:
                    if strip_ns(p.tag) == "Pricing":
                        price = {"PriceType": p.attrib.get("PriceType", "")}
                        for pc in p:
                            price[strip_ns(pc.tag)] = (pc.text or "").strip()
                        prices.append(price)

        if not part_number or not item_brand:
            elem.clear()
            continue

        if brand_id is None:
            aaia_code = item_brand
            parent = header.get("ParentAAIAID")
            brand_id = await upsert_brand(db, aaia_code, parent, item_brand_label, dci_lookup)

        # Find / create the Product (canonical), reusing existing if SKU matches
        sku = f"{item_brand}-{part_number}"
        product = (await db.execute(select(Product).where(Product.sku == sku))).scalar_one_or_none()
        primary_image = next((a["uri"] for a in digital_assets if a["type"] == "P04"), None)

        # Best description for product.name + .description
        name_text = next((dx["text"] for dx in descriptions if dx["code"] == "DES"), None) \
                 or next((dx["text"] for dx in descriptions if dx["code"] == "EXT"), None) \
                 or next((dx["text"] for dx in descriptions if dx["code"] == "SHO"), None) \
                 or part_number
        long_desc = next((dx["text"] for dx in descriptions if dx["code"] == "EXT"), None)
        marketing = next((dx["text"] for dx in descriptions if dx["code"] == "MKT"), None)

        # I2: representative per-each weight. PIES Packages typically include
        # the master pack + the each. Pick the package with QuantityofEaches=1
        # if present, else the smallest non-null weight. Owner ask 2026-05-17 —
        # both product.upc and product.weight_lb were 0% populated and that
        # broke downstream signals (reseller-finder GTIN match, freight class).
        def _pick_each_weight() -> "Decimal | None":
            best = None
            for pp in packages:
                w = _decimal_or_none(pp.get("Weight"))
                if w is None:
                    continue
                qe = _int_or_none(pp.get("QuantityofEaches")) or 0
                if qe == 1:
                    return w  # per-each weight wins outright
                if best is None or w < best:
                    best = w
            return best
        each_weight = _pick_each_weight()
        upc_value = (item_level_gtin or "")[:32] or None

        if not product:
            product = Product(
                sku=sku,
                brand_id=brand_id,
                name=name_text[:500],
                description=long_desc,
                extended_description=marketing,
                cta_mode=CTAMode.ADD_TO_CART,
                requires_shipping=True,
                taxable=True,
                is_hidden=False,
                is_for_sale=True,
                upc=upc_value,
                weight_lb=each_weight,
            )
            db.add(product)
            await db.flush()
        else:
            product.name = name_text[:500]
            if long_desc:
                product.description = long_desc
            if marketing:
                product.extended_description = marketing
            # Only fill UPC/weight if currently null — don't overwrite a
            # value an admin may have manually corrected.
            if product.upc is None and upc_value:
                product.upc = upc_value
            if product.weight_lb is None and each_weight is not None:
                product.weight_lb = each_weight

        # Wipe this product's PIES side rows for clean re-insert
        await db.execute(delete(ProductAttribute).where(ProductAttribute.product_id == product.id))
        await db.execute(delete(ProductDescription).where(ProductDescription.product_id == product.id))
        await db.execute(delete(ProductPackage).where(ProductPackage.product_id == product.id))
        await db.execute(delete(ProductPricing).where(ProductPricing.product_id == product.id))

        # Insert descriptions
        if descriptions:
            db.add_all([ProductDescription(
                product_id=product.id,
                description_code=d["code"],
                language_code=d["lang"] or "EN",
                sequence=d["seq"],
                text=d["text"],
            ) for d in descriptions if d["text"]])

        # Insert attributes (de-dup by key+val to respect uniqueness intent)
        seen_attr = set()
        for a in attributes:
            k = (a["key"], a["val"])
            if k in seen_attr or not a["key"]:
                continue
            seen_attr.add(k)
            db.add(ProductAttribute(
                product_id=product.id,
                attribute_key=a["key"],
                attribute_value=a["val"][:8000] if a["val"] else None,
                attribute_uom=a["uom"] or None,
            ))

        # Insert packages
        for p in packages:
            db.add(ProductPackage(
                product_id=product.id,
                package_uom=(p.get("PackageUOM") or "")[:20] or None,
                quantity_of_eaches=_int_or_none(p.get("QuantityofEaches")),
                package_gtin=(p.get("PackageLevelGTIN") or "")[:20] or None,
                container_type=(p.get("ContainerType") or "")[:20] or None,
                weight_lb=_decimal_or_none(p.get("Weight")),
                length_in=_decimal_or_none(p.get("DimensionsLength")),
                width_in=_decimal_or_none(p.get("DimensionsWidth")),
                height_in=_decimal_or_none(p.get("DimensionsHeight")),
            ))

        # Insert prices — keep most recent per (price_type) flagged as is_current
        latest_per_type: dict[str, dict] = {}
        for pr in prices:
            pt = pr.get("PriceType", "")
            edate = _date_or_none(pr.get("EffectiveDate"))
            if pt not in latest_per_type or (edate and (latest_per_type[pt].get("d") or datetime.min.date()) < edate):
                latest_per_type[pt] = {"d": edate, "row": pr}
        for pt, payload in latest_per_type.items():
            pr = payload["row"]
            price_val = _decimal_or_none(pr.get("Price"))
            if price_val is None:
                continue
            db.add(ProductPricing(
                product_id=product.id,
                price_type=pt[:10],
                price=price_val,
                currency_code=(pr.get("CurrencyCode") or "USD")[:5],
                effective_date=payload["d"],
                price_sheet_number=(pr.get("PriceSheetNumber") or "")[:50] or None,
                is_current=True,
            ))

        # Insert primary image as ProductImage if not already present
        if primary_image:
            existing_img = (await db.execute(
                select(ProductImage).where(
                    ProductImage.product_id == product.id,
                    ProductImage.url == primary_image
                )
            )).scalar_one_or_none()
            if not existing_img:
                db.add(ProductImage(
                    product_id=product.id,
                    url=primary_image,
                    is_primary=True,
                    sort_order=0,
                ))

        # Ensure the PartTerminologyID this PIES Item references actually exists
        # in pcdb_part_type — PIES sometimes references part-types that the brand's
        # ACES feed never used (e.g. cleaning supplies that aren't fitment-bound).
        if part_terminology_id is not None:
            await db.execute(pg_insert(PcdbPartType.__table__).values(
                id=part_terminology_id, name=f"PartType#{part_terminology_id}"
            ).on_conflict_do_nothing(index_elements=["id"]))

        # Link the pace_part to this Product (UPSERT on conflict)
        stmt = pg_insert(PacePart.__table__).values(
            brand_id=brand_id,
            part_number=part_number,
            product_id=product.id,
            primary_image_url=primary_image,
            short_description=name_text[:500],
            part_terminology_id=part_terminology_id,
        ).on_conflict_do_update(
            constraint="uq_pace_part_brand_pn",
            set_={
                "product_id": product.id,
                "primary_image_url": primary_image,
                "short_description": name_text[:500],
                "part_terminology_id": part_terminology_id,
            },
        )
        await db.execute(stmt)

        items_inserted += 1
        elem.clear()

        if items_seen % 250 == 0:
            log.info("  PIES progress: %s items processed (%.1fs)",
                     f"{items_seen:,}", time.time() - t0)
            await db.commit()

    await db.commit()
    log.info("PIES done: %s items, %.1fs", items_inserted, time.time() - t0)
    return {"items_seen": items_seen, "items_inserted": items_inserted, "brand_id": brand_id}


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #


async def run(brand: str, aces_only: bool, pies_only: bool):
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    brand_dir = POC_BASE / brand
    if not brand_dir.exists():
        log.error("No directory %s — unzip the AAM_%s_*.zip pair first", brand_dir, brand)
        return

    aces_xml = next(brand_dir.glob(f"AAM_{brand}_ACES_*.xml"), None)
    pies_xml = next(brand_dir.glob(f"AAM_{brand}_PIES_*.xml"), None)

    dci_lookup = load_dci_brand_lookup()
    log.info("DCI lookup loaded: %d AAIA codes", len(dci_lookup))

    async with Session() as db:
        brand_id: int | None = None
        if aces_xml and not pies_only:
            res = await ingest_aces(db, aces_xml, dci_lookup)
            brand_id = (res or {}).get("brand_id") or brand_id
        elif not aces_xml:
            log.warning("No ACES XML for %s — skipping ACES", brand)
        if pies_xml and not aces_only:
            res = await ingest_pies(db, pies_xml, dci_lookup)
            brand_id = (res or {}).get("brand_id") or brand_id
        elif not pies_xml:
            log.warning("No PIES XML for %s — skipping PIES", brand)

        # Recompute the denormalized universal-fit flag for the products this
        # brand touched. The browse vehicle/vehicle_type filter reads
        # Product.has_no_fitment instead of OR'ing catalog-wide fitment scans,
        # so it must stay in sync whenever pace_fitment rows are wiped + re-
        # inserted. Scoped to this brand's products so --all-discovered doesn't
        # rescan the whole ~296K-product catalog once per brand.
        if brand_id is not None:
            await db.execute(text(
                """
                UPDATE product p
                SET has_no_fitment = NOT EXISTS (
                    SELECT 1
                    FROM pace_part pp
                    JOIN pace_fitment f ON f.pace_part_id = pp.id
                    WHERE pp.product_id = p.id
                )
                WHERE p.id IN (
                    SELECT DISTINCT pp.product_id
                    FROM pace_part pp
                    WHERE pp.brand_id = :bid AND pp.product_id IS NOT NULL
                )
                """
            ), {"bid": brand_id})
            await db.commit()
            log.info("Recomputed has_no_fitment for brand_id=%s products", brand_id)

    await engine.dispose()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("brand", nargs="?", help="AAM brand code (e.g. BDKW)")
    ap.add_argument("--all-discovered", action="store_true",
                    help="Ingest every brand pair found under wan_test_output/pace_poc/")
    ap.add_argument("--aces-only", action="store_true")
    ap.add_argument("--pies-only", action="store_true")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Skip brands that already have pace_part rows (for resume after crash)")
    args = ap.parse_args()

    if args.all_discovered:
        brands = sorted([d.name for d in POC_BASE.iterdir() if d.is_dir()])
        log.info("Will ingest %d brands: %s", len(brands), brands)

        # Optional skip-existing: query DB for brands that already have rows
        skip_set: set[str] = set()
        if args.skip_existing:
            async def _load_existing():
                eng = create_async_engine(get_settings().database_url, echo=False)
                async with eng.connect() as conn:
                    rows = await conn.execute(text(
                        "SELECT aaia_code FROM brand WHERE aaia_code IS NOT NULL "
                        "AND id IN (SELECT DISTINCT brand_id FROM pace_part)"
                    ))
                    return {r[0] for r in rows.all()}
            skip_set = asyncio.run(_load_existing())
            log.info("--skip-existing: %d brands already have data, will skip", len(skip_set))

        for b in brands:
            if b in skip_set:
                log.info("SKIP %s (already has pace_part rows)", b)
                continue
            log.info("=" * 60)
            log.info("BRAND %s", b)
            log.info("=" * 60)
            try:
                asyncio.run(run(b, args.aces_only, args.pies_only))
            except Exception as e:
                # Deadlock or transient DB error — log and continue with next brand.
                # Brand wasn't committed, so re-run later picks it up.
                log.error("BRAND %s FAILED: %s — continuing to next", b, e)
        return 0

    if not args.brand:
        ap.print_help()
        return 1
    asyncio.run(run(args.brand.upper(), args.aces_only, args.pies_only))
    return 0


if __name__ == "__main__":
    sys.exit(main())
