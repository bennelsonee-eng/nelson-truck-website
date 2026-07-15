-- =====================================================================
-- split_shocks_and_struts_L4.sql — 2026-06-22
--
-- Issue #14 deepening (Ben): turn the flat "Shocks and Struts" tile
-- (cat 291, 3,534 products) into a PARENT with three drill-down children
-- (level 4), mirroring Rough Country:
--     Suspension > Shocks and Struts > { Shocks, Struts, Coilover Kits }
--
-- Browsing the parent rolls up all descendants (the browse resolver matches
-- `full_path LIKE 'X > %'`), so "shop all 3,534" + the Series/Brand/Position
-- filters still work; each child shows just its slice.
--
-- Classification (per-product — shock/strut is NOT a clean part-type
-- boundary; the hardening relinker reproduces this exact logic to stay
-- durable on new feeds):
--   Coilover Kits : part type 15174  OR name/series ~ 'coil-over'
--   Struts        : (else) name/series ~ 'strut'
--   Shocks        : everything else
-- Expected: Shocks 2,364 · Struts 841 · Coilover Kits 329  (= 3,534)
--
-- Stop at level 4 — the finer product-line split is handled by the existing
-- left-rail facets (Series/Brand/Position), not more category nodes.
-- =====================================================================

BEGIN;

-- 1. Create the three child categories under Shocks and Struts (291, depth 3).
INSERT INTO category (name, slug, parent_id, full_path, depth, sort_order, is_featured, is_active, created_at, updated_at)
VALUES
  ('Shocks',        'suspension/shocks-and-struts/shocks',        291, 'Truck Accessories > Suspension > Shocks and Struts > Shocks',        3, 10, FALSE, TRUE, now(), now()),
  ('Struts',        'suspension/shocks-and-struts/struts',        291, 'Truck Accessories > Suspension > Shocks and Struts > Struts',        3, 20, FALSE, TRUE, now(), now()),
  ('Coilover Kits', 'suspension/shocks-and-struts/coilover-kits', 291, 'Truck Accessories > Suspension > Shocks and Struts > Coilover Kits', 3, 30, FALSE, TRUE, now(), now());

-- 2. Classify + move the 3,534 products out of the parent into the children.
--    Order matters (coilover, then strut, then the rest) — each UPDATE only
--    sees rows still on 291, so a product lands in exactly one child.

-- 2a. Coilover Kits
UPDATE product_category pc
SET category_id = (SELECT id FROM category WHERE full_path = 'Truck Accessories > Suspension > Shocks and Struts > Coilover Kits'),
    updated_at = now()
WHERE pc.category_id = 291
  AND (
    EXISTS (SELECT 1 FROM pace_part pp WHERE pp.product_id = pc.product_id AND pp.part_terminology_id = 15174)
    OR EXISTS (SELECT 1 FROM product p WHERE p.id = pc.product_id AND p.name ~* 'coil.?over')
    OR EXISTS (SELECT 1 FROM product_attribute pa WHERE pa.product_id = pc.product_id
               AND lower(pa.attribute_key) = 'series' AND pa.attribute_value ~* 'coil.?over')
  );

-- 2b. Struts (whatever is left on 291 that reads as a strut)
UPDATE product_category pc
SET category_id = (SELECT id FROM category WHERE full_path = 'Truck Accessories > Suspension > Shocks and Struts > Struts'),
    updated_at = now()
WHERE pc.category_id = 291
  AND (
    EXISTS (SELECT 1 FROM product p WHERE p.id = pc.product_id AND p.name ~* 'strut')
    OR EXISTS (SELECT 1 FROM product_attribute pa WHERE pa.product_id = pc.product_id
               AND lower(pa.attribute_key) = 'series' AND pa.attribute_value ~* 'strut')
  );

-- 2c. Shocks (everything still on 291)
UPDATE product_category pc
SET category_id = (SELECT id FROM category WHERE full_path = 'Truck Accessories > Suspension > Shocks and Struts > Shocks'),
    updated_at = now()
WHERE pc.category_id = 291;

COMMIT;

-- Sanity checks after running (expected):
--   291 (parent) direct products -> 0 (rolls up 3,534 from children)
--   Shocks ~2,364 · Struts ~841 · Coilover Kits ~329
-- Then: backend restart (clears tree cache) + reindex Typesense.
