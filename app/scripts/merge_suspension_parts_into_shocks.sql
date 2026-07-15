-- =====================================================================
-- merge_suspension_parts_into_shocks.sql — 2026-06-22
--
-- Follow-up to issue #14. After the Suspension restructure, the
-- "Suspension Parts" tile (cat 286, PACE part type 7556, 2,979 products)
-- turned out to be 99.2% shocks and struts (2,954 of 2,979 by name:
-- N3 / M1 / RS5000X / V2 / RS9000XL / Vertex / Fox / Bilstein shock
-- lines). Ben's call browsing the live site: all shocks and struts
-- belong in the dedicated "Shocks and Struts" tile, not a separate
-- Suspension Parts bucket.
--
-- Fix:
--   1. Remap part type 7556 -> 'Shocks and Struts' (durable; future PACE
--      ingests file these with the standalone shocks, not lift-kit parts).
--   2. Move 7556's product_category rows from 286 -> 291 (Shocks and
--      Struts), preserving is_primary, dupe-guarded.
--   3. Retire the now-empty "Suspension Parts" tile (is_active=false).
--
-- ~25 stray non-shocks mis-typed as 7556 by PACE (a few mufflers /
-- trailer-axle accessories) ride along; negligible (0.7%) and a separate
-- per-product cleanup. Shocks and Struts: 555 -> ~3,534.
-- =====================================================================

BEGIN;

-- 1. Durable remap.
UPDATE pcdb_part_type SET sub_category_name = 'Shocks and Struts' WHERE id = 7556;

-- 2. Move the product links 286 -> 291 (preserve is_primary, dupe-guard).
UPDATE product_category SET category_id = 291, updated_at = now()
WHERE category_id = 286
  AND product_id IN (SELECT product_id FROM pace_part WHERE part_terminology_id = 7556)
  AND product_id NOT IN (SELECT product_id FROM product_category WHERE category_id = 291);
DELETE FROM product_category
WHERE category_id = 286
  AND product_id IN (SELECT product_id FROM pace_part WHERE part_terminology_id = 7556);

-- 3. Retire the emptied Suspension Parts tile.
UPDATE category SET is_active = FALSE, updated_at = now() WHERE id = 286;

COMMIT;

-- Sanity checks after running (expected):
--   291 Shocks and Struts -> ~3,534
--   286 Suspension Parts  -> 0 products, is_active=false
--   No orphans among the moved products.
-- Then: backend restart (clears tree cache) + reindex Typesense.
