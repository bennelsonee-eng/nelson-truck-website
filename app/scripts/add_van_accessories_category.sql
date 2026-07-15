-- =====================================================================
-- add_van_accessories_category.sql — 2026-05-10
--
-- Create "Cargo Management > Van Accessories" as a catch-all for the
-- Weather Guard accessory/replacement-part SKUs that don't fit cleanly
-- in Van Shelving (actual shelves) or Cab Partitions (actual panels):
--   - Accessory cross members, divider trays, mirrors + holders
--   - PACK RAT drawer bolt kits, bearings, rollers
--   - Cab Protector mounting kits (the hardware, not the protector)
--   - Generic bolt kits, leveling spacers, install templates
--   - Cabinet trays
--   - Plus the 18 uncategorized stragglers (paint, grab handles, wiring,
--     fire extinguisher, e-clips, universal clamps, replacement airfoil)
--
-- After this script: Van Shelving and Cab Partitions reflect actual
-- shelving / partition products only, and the Van Accessories tile
-- becomes the home for parts customers go looking for by name.
--
-- Idempotent: each block uses IF NOT EXISTS / WHERE pattern that skips
-- rows already in their final state.
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Create the category
-- ---------------------------------------------------------------------
INSERT INTO category (name, slug, parent_id, full_path, depth, sort_order, is_featured, is_active, created_at, updated_at)
SELECT
  'Van Accessories',
  'van-accessories',
  c.id,
  'Cargo Management > Van Accessories',
  c.depth + 1,
  1000,
  FALSE,
  TRUE,
  NOW(),
  NOW()
FROM category c
WHERE c.full_path = 'Cargo Management'
  AND NOT EXISTS (
    SELECT 1 FROM category WHERE full_path = 'Cargo Management > Van Accessories'
  );

-- ---------------------------------------------------------------------
-- BLOCK B: Re-map PCDB part_types from current target to Van Accessories
-- Sample-product evidence for each pt_id is in the comment.
-- ---------------------------------------------------------------------

-- 18397 (369): "Accessory Cross Member", "Accessory Divider Tray",
--   "Accessory Mirror", "Accessory Mirror Holder" — clearly accessories
UPDATE pcdb_part_type SET sub_category_name='Van Accessories' WHERE id = 18397;

-- 17488 (36): "Bolt Kit For PACK RAT Drawer Units", "Drawer Bearing",
--   "Drawer Roller Kit" — PACK RAT replacement parts
UPDATE pcdb_part_type SET sub_category_name='Van Accessories' WHERE id = 17488;

-- 18387 (23): "Cab Protector Mounting Kit", "Compact Cab Protector
--   Mounting Kit" — mounting hardware, not the partition panel itself
UPDATE pcdb_part_type SET sub_category_name='Van Accessories' WHERE id = 18387;

-- 48637 (19): "Bolt Kit", "Replacement Bolt Kit", "Underbed Striker
--   Bolt Kit" — generic bolt kits
UPDATE pcdb_part_type SET sub_category_name='Van Accessories' WHERE id = 48637;

-- 19895 (3): "Composite Bulkhead Accessory Template", "Leveling Spacer"
--   — install hardware
UPDATE pcdb_part_type SET sub_category_name='Van Accessories' WHERE id = 19895;

-- 15437 (2): "Cabinet Tray"
UPDATE pcdb_part_type SET sub_category_name='Van Accessories' WHERE id = 15437;

-- 12393 (12): "Van Floor Mats" — van cargo-area protection, more accessory
--   than shelving (these are interior floor liners for the cargo bay)
UPDATE pcdb_part_type SET sub_category_name='Van Accessories' WHERE id = 12393;

-- ---------------------------------------------------------------------
-- BLOCK C: Map the 18 previously-uncategorized stragglers to Van Accessories
-- ---------------------------------------------------------------------

-- 1081 (6): "Aerosol Touch-Up Paint"
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Accessories' WHERE id = 1081 AND category_name IS NULL;

-- 21242 (4): "Grab Handle"
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Accessories' WHERE id = 21242 AND category_name IS NULL;

-- 22264 (2): "Wiring Harness"
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Accessories' WHERE id = 22264 AND category_name IS NULL;

-- 1152 (2): "Replacement Airfoil"
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Accessories' WHERE id = 1152 AND category_name IS NULL;

-- 14135 (2): "Fire Extinguisher", "Roller Track For ITEMIZER Drawer Units"
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Accessories' WHERE id = 14135 AND category_name IS NULL;

-- 17347 (1): "Replacement E-Clip"
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Accessories' WHERE id = 17347 AND category_name IS NULL;

-- 2404 (1): "Replacement Universal Clamp"
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Accessories' WHERE id = 2404 AND category_name IS NULL;

-- ---------------------------------------------------------------------
-- BLOCK D: MOVE existing product_category rows from old target -> Van Accessories
-- For each re-mapped part_type, the products were already filed under the
-- old category (Van Shelving / Cab Partitions / Truck Bed Toolboxes).
-- Switch the category_id on those rows so we don't end up with the same
-- product showing in two places.
-- ---------------------------------------------------------------------

UPDATE product_category pc
SET category_id = (SELECT id FROM category WHERE full_path = 'Cargo Management > Van Accessories')
WHERE pc.category_id IN (
        SELECT id FROM category WHERE full_path IN (
          'Cargo Management > Van Shelving',
          'Cargo Management > Cab Partitions and Dividers',
          'Truck Bed and Tailgate > Truck Bed Toolboxes and Accessories'
        )
      )
  AND pc.product_id IN (
        SELECT p.id FROM product p
        JOIN pace_part pp ON pp.product_id = p.id
        WHERE pp.part_terminology_id IN (18397, 17488, 18387, 48637, 19895, 15437, 12393)
      );

-- ---------------------------------------------------------------------
-- BLOCK E: INSERT product_category rows for the 18 stragglers + any
-- product whose part_type was re-mapped but had no existing row to move.
-- (ON CONFLICT keeps this safe to re-run.)
-- ---------------------------------------------------------------------

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT
  p.id,
  (SELECT id FROM category WHERE full_path = 'Cargo Management > Van Accessories'),
  TRUE,
  NOW(),
  NOW()
FROM product p
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id IN (
        18397, 17488, 18387, 48637, 19895, 15437, 12393,  -- re-mapped
        1081, 21242, 22264, 1152, 14135, 17347, 2404      -- stragglers
      )
  AND NOT EXISTS (
    SELECT 1 FROM product_category pc
    WHERE pc.product_id = p.id
      AND pc.category_id = (SELECT id FROM category WHERE full_path = 'Cargo Management > Van Accessories')
  )
ON CONFLICT DO NOTHING;

-- =====================================================================
-- Verify
-- =====================================================================
--   SELECT cat.full_path, COUNT(DISTINCT p.id) AS n FROM product p
--   JOIN product_category pc ON pc.product_id = p.id
--   JOIN category cat ON cat.id = pc.category_id
--   WHERE p.brand_id = 71 GROUP BY cat.full_path ORDER BY n DESC;
