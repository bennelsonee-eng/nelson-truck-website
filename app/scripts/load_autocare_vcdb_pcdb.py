"""Load Auto Care VCdb + PCdb reference data from Microsoft Access dumps.

The Auto Care Association distributes VCdb (Vehicle Configuration Database) and
PCdb (Product Classification Database) as zipped Microsoft Access (.mdb) files
on a quarterly schedule. Members download from autocare.org.

This script ingests those into our vcdb_* and pcdb_* tables so the YMM picker
shows real "2024 Ford F-150" instead of placeholder "VCdb#3001" labels.

Inputs (place under app/data/autocare/):
    VCdb_<YYYY-MM-DD>.zip   → contains VCdb_<date>.mdb
    PCdb_<YYYY-MM-DD>.zip   → contains PCdb_<date>.mdb

The .mdb files have these key tables we care about:
    VCdb:
      - Make           (MakeID, MakeName)
      - Model          (ModelID, MakeID, ModelName, VehicleTypeID)
      - VehicleType    (VehicleTypeID, VehicleTypeName)  -> "Pickup", "SUV", etc.
      - BaseVehicle    (BaseVehicleID, MakeID, ModelID, YearID)
      - SubModel       (SubModelID, SubModelName)
      - BedLength      (BedLengthID, BedLength, BedLengthMetric)
      - BedType        (BedTypeID, BedTypeName)
      - BodyType       (BodyTypeID, BodyTypeName)
      - DriveType      (DriveTypeID, DriveTypeName)
      - EngineBase     (EngineBaseID, Liter, CC, CID, Cylinders, BlockType)
      - FuelType       (FuelTypeID, FuelTypeName)
      - Aspiration     (AspirationID, AspirationName)
      - Region         (RegionID, RegionName)
    PCdb:
      - Parts          (PartTerminologyID, PartTerminologyName, PartTerminologyMediumName, PartTerminologyLongName)
      - Categories     (CategoryID, CategoryName)
      - SubCategories  (SubCategoryID, SubCategoryName, CategoryID)
      - PartCategory   (PartTerminologyID, SubCategoryID)  -> walk to Categories
      - Position       (PositionID, Position)

Usage (placeholder until we have an .mdb reader):
    python app/scripts/load_autocare_vcdb_pcdb.py --vcdb-csv path/to/extracted.csv ...

For now this script is a STUB — it documents what we need to load and will be
fleshed out once we have the .mdb dumps in hand. Key implementation choice
remaining: use `mdbtools` (Linux/WSL only) or `pyodbc + Access driver`
(Windows-only) to read the .mdb files.

INTERIM PATH: download Auto Care's published JSON/CSV exports of the public
reference subset, OR query the public ACES validation API at
https://api.autocarevip.com/aces-validation/v3 (membership required).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "app" / "data" / "autocare"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vcdb-mdb", help="Path to VCdb .mdb file")
    ap.add_argument("--pcdb-mdb", help="Path to PCdb .mdb file")
    args = ap.parse_args()

    if not args.vcdb_mdb and not args.pcdb_mdb:
        print(__doc__)
        print("\nNo --vcdb-mdb or --pcdb-mdb specified — nothing to do.")
        print(f"\nExpected: place .mdb files in {DATA_DIR}/")
        return 0

    print("STUB: real implementation pending. We need to choose between:")
    print("  (a) mdbtools — Linux/WSL only, free, mature")
    print("  (b) pyodbc + Microsoft Access Database Engine — Windows-only, free, requires admin install")
    print("  (c) ACES Validation API at autocarevip.com — requires Auto Care membership")
    return 0


if __name__ == "__main__":
    sys.exit(main())
