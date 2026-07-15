"""Profile a single PACE brand pair (ACES + PIES) to plan the persistent schema.

Streams the XML so it scales to multi-GB files. Outputs a markdown report
under wan_test_output/pace_poc/<BRAND>/profile.md plus distinct-value CSVs.

Usage:
    python app/scripts/profile_pace_brand.py BDKW
    python app/scripts/profile_pace_brand.py BDKW --max-samples 50
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET


REPO = Path(__file__).resolve().parents[2]
POC_BASE = REPO / "wan_test_output" / "pace_poc"


def strip_ns(tag: str) -> str:
    """`{http://www.autocare.org}Item` → `Item`."""
    return tag.rsplit("}", 1)[-1]


def profile_aces(xml_path: Path, out_dir: Path, max_samples: int) -> dict:
    """Stream ACES, return summary dict + write distinct-value CSVs."""
    parts: Counter = Counter()
    base_vehicles: Counter = Counter()
    part_types: Counter = Counter()
    sub_models: Counter = Counter()
    actions: Counter = Counter()

    # Track every child-tag name that ever appears under <App> so we know
    # the full qualifier vocabulary (BedType, BedLength, Engine, DriveType, ...)
    app_child_tags: Counter = Counter()
    sample_apps: list[dict] = []

    header: dict[str, str] = {}
    in_header = False
    app_count = 0

    for ev, elem in ET.iterparse(str(xml_path), events=("start", "end")):
        tag = strip_ns(elem.tag)
        if ev == "start":
            if tag == "Header":
                in_header = True
            continue

        # ev == "end"
        if tag == "Header":
            for child in elem:
                header[strip_ns(child.tag)] = (child.text or "").strip()
            in_header = False
            elem.clear()
            continue

        if tag == "App":
            app_count += 1
            actions[elem.attrib.get("action", "")] += 1
            app: dict = {"id": elem.attrib.get("id")}
            for child in elem:
                ctag = strip_ns(child.tag)
                app_child_tags[ctag] += 1
                cid = child.attrib.get("id")
                cval = (child.text or "").strip() if child.text else ""
                app[ctag] = cid if cid else cval
                if ctag == "Part" and cval:
                    parts[cval] += 1
                elif ctag == "BaseVehicle" and cid:
                    base_vehicles[cid] += 1
                elif ctag == "PartType" and cid:
                    part_types[cid] += 1
                elif ctag == "SubModel" and cid:
                    sub_models[cid] += 1
            if len(sample_apps) < max_samples:
                sample_apps.append(app)
            elem.clear()

    # Write distinct-value CSVs for inspection
    def dump_counter(counter: Counter, name: str, key_label: str):
        with open(out_dir / f"aces_{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([key_label, "fitment_count"])
            for k, v in counter.most_common():
                w.writerow([k, v])

    dump_counter(parts, "parts", "PartNumber")
    dump_counter(base_vehicles, "base_vehicles", "BaseVehicleID")
    dump_counter(part_types, "part_types", "PartTypeID")
    dump_counter(sub_models, "sub_models", "SubModelID")

    return {
        "header": header,
        "app_count": app_count,
        "distinct_parts": len(parts),
        "distinct_base_vehicles": len(base_vehicles),
        "distinct_part_types": len(part_types),
        "distinct_sub_models": len(sub_models),
        "actions": dict(actions),
        "app_child_tags": dict(app_child_tags),
        "sample_apps": sample_apps[:10],
    }


def profile_pies(xml_path: Path, out_dir: Path, max_samples: int) -> dict:
    """Stream PIES, return summary dict + write samples."""
    items_seen = 0
    item_child_tags: Counter = Counter()
    description_codes: Counter = Counter()
    attribute_keys: Counter = Counter()
    asset_types: Counter = Counter()
    package_uoms: Counter = Counter()
    price_types: Counter = Counter()
    price_sheets: list[dict] = []

    sample_items: list[dict] = []
    header: dict[str, str] = {}

    for ev, elem in ET.iterparse(str(xml_path), events=("end",)):
        tag = strip_ns(elem.tag)

        if tag == "Header":
            for child in elem:
                header[strip_ns(child.tag)] = (child.text or "").strip()
            elem.clear()
            continue

        if tag == "PriceSheet":
            ps = {strip_ns(c.tag): (c.text or "").strip() for c in elem}
            ps["MaintenanceType"] = elem.attrib.get("MaintenanceType", "")
            price_sheets.append(ps)
            elem.clear()
            continue

        if tag == "Item":
            items_seen += 1
            item: dict = {}
            for child in elem:
                ctag = strip_ns(child.tag)
                item_child_tags[ctag] += 1
                if ctag == "PartNumber":
                    item["PartNumber"] = (child.text or "").strip()
                elif ctag == "Descriptions":
                    descs = []
                    for d in child:
                        if strip_ns(d.tag) == "Description":
                            code = d.attrib.get("DescriptionCode", "")
                            description_codes[code] += 1
                            descs.append({"code": code, "lang": d.attrib.get("LanguageCode", ""),
                                          "text": (d.text or "").strip()})
                    item["Descriptions"] = descs
                elif ctag == "ProductAttributes":
                    attrs = []
                    for a in child:
                        if strip_ns(a.tag) == "ProductAttribute":
                            key = a.attrib.get("AttributeID", "")
                            attribute_keys[key] += 1
                            attrs.append({"key": key, "uom": a.attrib.get("AttributeUOM", ""),
                                          "val": (a.text or "").strip()})
                    item["ProductAttributes"] = attrs
                elif ctag == "Packages":
                    pkgs = []
                    for p in child:
                        if strip_ns(p.tag) == "Package":
                            pkg = {strip_ns(pc.tag): (pc.text or "").strip() for pc in p}
                            uom = pkg.get("DimensionsUOM") or pkg.get("WeightUOM") or ""
                            package_uoms[uom] += 1
                            pkgs.append(pkg)
                    item["Packages"] = pkgs
                elif ctag == "DigitalAssets":
                    assets = []
                    for a in child:
                        if strip_ns(a.tag) == "DigitalFileInformation":
                            atype = ""
                            uri = ""
                            for ac in a:
                                act = strip_ns(ac.tag)
                                if act == "AssetType":
                                    atype = (ac.text or "").strip()
                                elif act == "URI":
                                    uri = (ac.text or "").strip()
                            asset_types[atype] += 1
                            assets.append({"type": atype, "uri": uri})
                    item["DigitalAssets"] = assets
                elif ctag == "Prices":
                    prices = []
                    for p in child:
                        if strip_ns(p.tag) == "Pricing":
                            pt = p.attrib.get("PriceType", "")
                            price_types[pt] += 1
                            price = {"PriceType": pt}
                            for pc in p:
                                price[strip_ns(pc.tag)] = (pc.text or "").strip()
                            prices.append(price)
                    item["Prices"] = prices
                else:
                    # generic capture for everything else (HazardousMaterialCode,
                    # ItemLevelGTIN, BrandAAIAID per-item, PartTerminologyID, etc.)
                    item[ctag] = (child.text or "").strip()
            if len(sample_items) < max_samples:
                sample_items.append(item)
            elem.clear()

    # Dump distinct-value CSVs
    def dump_counter(counter: Counter, name: str, key_label: str):
        with open(out_dir / f"pies_{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([key_label, "occurrence_count"])
            for k, v in counter.most_common():
                w.writerow([k, v])

    dump_counter(description_codes, "description_codes", "DescriptionCode")
    dump_counter(attribute_keys, "attribute_keys", "AttributeID")
    dump_counter(asset_types, "asset_types", "AssetType")
    dump_counter(price_types, "price_types", "PriceType")

    return {
        "header": header,
        "item_count": items_seen,
        "item_child_tags": dict(item_child_tags),
        "distinct_description_codes": len(description_codes),
        "distinct_attribute_keys": len(attribute_keys),
        "distinct_asset_types": len(asset_types),
        "distinct_price_types": len(price_types),
        "price_sheet_count": len(price_sheets),
        "sample_items": sample_items[:5],
    }


def write_report(brand: str, aces: dict, pies: dict, out_dir: Path):
    md = []
    md.append(f"# PACE Brand Profile — {brand}\n")
    md.append("Generated by `app/scripts/profile_pace_brand.py`\n")

    md.append("## ACES (vehicle fitment)\n")
    md.append("### Header\n")
    md.append("| Key | Value |\n|---|---|")
    for k, v in aces["header"].items():
        md.append(f"| {k} | {v} |")
    md.append("")
    md.append("### Counts\n")
    md.append(f"- **Total `<App>` fitment records:** {aces['app_count']:,}")
    md.append(f"- **Distinct PartNumbers:** {aces['distinct_parts']:,}")
    md.append(f"- **Distinct BaseVehicleIDs:** {aces['distinct_base_vehicles']:,}  (each = a Year+Make+Model row in VCdb)")
    md.append(f"- **Distinct PartTypeIDs:** {aces['distinct_part_types']:,}  (categories per PCdb)")
    md.append(f"- **Distinct SubModelIDs:** {aces['distinct_sub_models']:,}")
    md.append(f"- **App actions:** {aces['actions']}")
    md.append("")
    md.append("### `<App>` child-tag vocabulary (qualifiers used for THIS brand)\n")
    md.append("| Tag | Occurrences | % of apps |\n|---|---|---|")
    total = aces["app_count"] or 1
    for tag, n in sorted(aces["app_child_tags"].items(), key=lambda kv: -kv[1]):
        md.append(f"| {tag} | {n:,} | {100*n/total:.1f}% |")
    md.append("")
    md.append("### Sample `<App>` records (first 10)\n")
    md.append("```json")
    import json
    md.append(json.dumps(aces["sample_apps"], indent=2))
    md.append("```\n")

    md.append("## PIES (product information)\n")
    md.append("### Header\n")
    md.append("| Key | Value |\n|---|---|")
    for k, v in pies["header"].items():
        md.append(f"| {k} | {v} |")
    md.append("")
    md.append("### Counts\n")
    md.append(f"- **Total `<Item>` records:** {pies['item_count']:,}")
    md.append(f"- **Distinct DescriptionCodes:** {pies['distinct_description_codes']}  (e.g. SHO, EXT, DES, MKT, FAB, INV — different description fields)")
    md.append(f"- **Distinct AttributeIDs:** {pies['distinct_attribute_keys']}  (e.g. Color, Material, Length, Width)")
    md.append(f"- **Distinct AssetTypes:** {pies['distinct_asset_types']}  (P04 = primary photo, INS = installation guide, etc.)")
    md.append(f"- **Distinct PriceTypes:** {pies['distinct_price_types']}  (LST = list, JBR = jobber, MSR = MSRP, etc.)")
    md.append(f"- **Historical PriceSheet revisions:** {pies['price_sheet_count']}")
    md.append("")
    md.append("### `<Item>` child-tag vocabulary\n")
    md.append("| Tag | Occurrences | % of items |\n|---|---|---|")
    total = pies["item_count"] or 1
    for tag, n in sorted(pies["item_child_tags"].items(), key=lambda kv: -kv[1]):
        md.append(f"| {tag} | {n:,} | {100*n/total:.1f}% |")
    md.append("")
    md.append("### Sample `<Item>` records (first 5, key sections only)\n")
    md.append("```json")
    md.append(json.dumps(pies["sample_items"], indent=2)[:6000])
    md.append("```\n")

    (out_dir / "profile.md").write_text("\n".join(md), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("brand", help="AAM brand code, e.g. BDKW")
    ap.add_argument("--max-samples", type=int, default=10)
    args = ap.parse_args()

    brand = args.brand.upper()
    brand_dir = POC_BASE / brand
    if not brand_dir.exists():
        print(f"No directory at {brand_dir}; unzip the AAM_{brand}_*.zip pair first", file=sys.stderr)
        return 1

    aces_xml = next(brand_dir.glob(f"AAM_{brand}_ACES_*.xml"), None)
    pies_xml = next(brand_dir.glob(f"AAM_{brand}_PIES_*.xml"), None)
    if not aces_xml:
        print(f"No ACES XML in {brand_dir}", file=sys.stderr)
        return 1
    if not pies_xml:
        print(f"No PIES XML in {brand_dir}", file=sys.stderr)
        return 1

    print(f"Profiling ACES: {aces_xml.name}  ({aces_xml.stat().st_size / 1e6:.1f} MB)")
    aces = profile_aces(aces_xml, brand_dir, args.max_samples)
    print(f"  apps={aces['app_count']:,}  parts={aces['distinct_parts']:,}  base_vehicles={aces['distinct_base_vehicles']:,}")

    print(f"Profiling PIES: {pies_xml.name}  ({pies_xml.stat().st_size / 1e6:.1f} MB)")
    pies = profile_pies(pies_xml, brand_dir, args.max_samples)
    print(f"  items={pies['item_count']:,}  attr_keys={pies['distinct_attribute_keys']}  asset_types={pies['distinct_asset_types']}")

    write_report(brand, aces, pies, brand_dir)
    print(f"Report: {brand_dir / 'profile.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
