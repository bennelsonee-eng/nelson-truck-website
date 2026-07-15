-- =====================================================================
-- restructure_suspension_subcategories.sql — 2026-06-22
--
-- Issue #14 (jaredl@titantruck.com): clean up the Suspension subcategory
-- tiles for shoppers. Three changes (chosen with Ben 2026-06-22):
--
--   1. MERGE the two shock tiles into one. "Coilover Shocks and Struts"
--      (cat 280, part type 15174, 289 products) folds into "Shocks and
--      Struts" (cat 291, part type 19837, 266) -> one ~555-product tile.
--      The Coilover tile is retired (is_active=false).
--
--   2. EXTRACT the real lift kits. Category 286 "Lift Kit Accessories" is
--      really two things post-#13: part type 18833 = actual lift kits
--      (4,491: "6 Inch Lift Kit", series Suspension/SST/Coilover-Conversion
--      Lift Kits) and part type 7556 = shocks / replacement components
--      (2,979: N3 / RS9000XL / V2 shock absorbers). Move 18833 into the
--      existing-but-empty "Lift Kits" tile (cat 287) so it sits next to
--      Leveling Kits.
--
--   3. RENAME the leftover. Category 286 (now only part type 7556) becomes
--      "Suspension Parts" — its own tile, as Jared asked.
--
-- Data is a clean partition: 4491 + 2979 = 7470 = all of cat 286, zero
-- overlap, every product carries exactly one of the two part types. Uses
-- UPDATE category_id (preserves is_primary) with a dupe-guard, not
-- delete+insert. pcdb_part_type sub_category_name is remapped on every
-- moved part type so future PACE ingests file products the new way.
-- =====================================================================

BEGIN;

-- ---- Change 1: merge Coilover Shocks and Struts (280) -> Shocks and Struts (291)
UPDATE pcdb_part_type SET sub_category_name = 'Shocks and Struts' WHERE id = 15174;

UPDATE product_category SET category_id = 291, updated_at = now()
WHERE category_id = 280
  AND product_id NOT IN (SELECT product_id FROM product_category WHERE category_id = 291);
DELETE FROM product_category WHERE category_id = 280;  -- any that already sat in 291

UPDATE category SET is_active = FALSE, updated_at = now() WHERE id = 280;

-- ---- Change 2: extract lift kits (part type 18833) from 286 -> Lift Kits (287)
UPDATE pcdb_part_type SET sub_category_name = 'Lift Kits' WHERE id = 18833;

UPDATE product_category SET category_id = 287, updated_at = now()
WHERE category_id = 286
  AND product_id IN (SELECT product_id FROM pace_part WHERE part_terminology_id = 18833)
  AND product_id NOT IN (SELECT product_id FROM product_category WHERE category_id = 287);
DELETE FROM product_category
WHERE category_id = 286
  AND product_id IN (SELECT product_id FROM pace_part WHERE part_terminology_id = 18833);

-- ---- Change 3: rename leftover 286 (part type 7556) -> "Suspension Parts"
UPDATE pcdb_part_type SET sub_category_name = 'Suspension Parts' WHERE id = 7556;
UPDATE category
SET name = 'Suspension Parts',
    slug = 'suspension/suspension-parts',
    full_path = 'Truck Accessories > Suspension > Suspension Parts',
    updated_at = now()
WHERE id = 286;

COMMIT;

-- Sanity checks after running (expected):
--   280 Coilover  -> 0 products, is_active=false
--   291 Shocks    -> ~555
--   287 Lift Kits -> 4,491
--   286 (now Suspension Parts) -> 2,979
--   No orphans among the moved products.
-- Then clear the tree cache + reindex Typesense:
--   curl -XPOST localhost:8001/api/admin/... (or restart) ; reindex_typesense.py
