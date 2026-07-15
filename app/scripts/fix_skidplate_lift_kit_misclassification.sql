-- =====================================================================
-- fix_skidplate_lift_kit_misclassification.sql — 2026-06-22
--
-- Issue #13 (jaredl@titantruck.com): the "Truck Accessories > Suspension >
-- Lift Kit Accessories" subcategory (category id 286) is polluted with
-- products that have nothing to do with suspension — skid plates, glide
-- plates, bumper skid plates, etc. The brand rail under that subcategory
-- consequently lists non-lift brands (Warn, Westin, Titan Fuel Tanks,
-- Go Rhino, CURT...). The brand rail is auto-derived from the products in
-- the category, so it self-corrects once the products are re-homed.
--
-- Root cause: PACE part_terminology_id 1421 is the "Skid Plates" part type,
-- but the PACE category-mapping pass (map_part_types_to_categories.py) filed
-- it under Suspension > Lift Kit Accessories. All 264 of its products in
-- category 286 are skid plates / glide plates / differential plates (a
-- handful of Go Rhino brackets + Bestop bumpers are strays inside the same
-- PACE part type). Their CORRECT home is Truck Accessories > Exterior >
-- Body Armor and Protection (category id 76).
--
-- NOTE: 259 of the 264 products have category 286 as their ONLY category, so
-- a plain DELETE (the 99999 precedent) would orphan them out of browse
-- entirely. They are legitimate SKUs — they must be MOVED, not deleted.
--
-- Fix:
--   1. Remap pcdb_part_type.id=1421 to Exterior > Body Armor and Protection
--      so future PACE ingests file skid plates correctly.
--   2. Add a product_category row (category 76) for every part-type-1421
--      product currently in 286 that isn't already in 76.
--   3. Delete the stale category-286 rows for those products.
--
-- Part types 7556 and 18833 (the real lift/leveling kits, ~96% of the
-- subcategory) are left untouched.
-- =====================================================================

BEGIN;

-- 1. Durable remap so re-ingests stop repeating the mistake.
UPDATE pcdb_part_type
SET category_name = 'Exterior', sub_category_name = 'Body Armor and Protection'
WHERE id = 1421;

-- 2. Link the skid plates to Body Armor and Protection (76), skipping any
--    that already carry that category (respects uq_category_product).
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT DISTINCT pp.product_id, 76, FALSE, now(), now()
FROM pace_part pp
JOIN product_category pc ON pc.product_id = pp.product_id AND pc.category_id = 286
WHERE pp.part_terminology_id = 1421
  AND NOT EXISTS (
    SELECT 1 FROM product_category x
    WHERE x.product_id = pp.product_id AND x.category_id = 76
  );

-- 3. Remove the wrong Lift Kit Accessories (286) links for those products.
DELETE FROM product_category pc
WHERE pc.category_id = 286
  AND pc.product_id IN (
    SELECT pp.product_id FROM pace_part pp WHERE pp.part_terminology_id = 1421
  );

COMMIT;

-- Sanity checks after running:
--   -- Lift Kit Accessories should drop ~264 (7734 -> ~7470):
--   SELECT count(*) FROM product_category WHERE category_id = 286;
--   -- Body Armor and Protection should gain the skid plates:
--   SELECT count(*) FROM product_category WHERE category_id = 76;
--   -- No orphans: every moved product still has >=1 category:
--   SELECT count(*) FROM pace_part pp
--   WHERE pp.part_terminology_id = 1421
--     AND NOT EXISTS (SELECT 1 FROM product_category x WHERE x.product_id = pp.product_id);
-- After verifying, REINDEX TYPESENSE so search facets match browse:
--   cd app/backend && .venv/bin/python ../scripts/reindex_typesense.py
