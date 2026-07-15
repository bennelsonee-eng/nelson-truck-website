-- =====================================================================
-- backfill_weatherguard_categories.sql — 2026-05-10
--
-- Weatherguard (HWZD, brand_id=71) had 1,219 PIES products ingested but
-- only 572 had category mappings. The other 647 fell through because their
-- PCDB part_terminology_id wasn't in our pcdb_part_type.category_name
-- coverage. This script fills the gap.
--
-- Each block:
--   1. Sets pcdb_part_type.category_name + sub_category_name for the
--      missing part_types, based on the product-name signals we saw
--      when sampling the unmapped SKUs.
--   2. Inserts product_category rows for every affected product so they
--      surface in the right Cargo Management / Truck Bed and Tailgate
--      sub-tree on the website.
--
-- All inserts use ON CONFLICT DO NOTHING so this script is idempotent.
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Update pcdb_part_type with the correct category mapping
-- Sample-product evidence for each pt_id is in the comment.
-- ---------------------------------------------------------------------

-- 18397 (369 products): "Accessory Cross Member", "Accessory Divider Tray",
--   "Accessory Mirror", "Accessory Mirror Holder" — PACK RAT van-drawer
--   accessories. Belongs under Van Shelving.
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Shelving'
WHERE id = 18397;

-- 1262 (113): "Tool Box Replacement Cover" — truck-bed toolbox parts.
UPDATE pcdb_part_type SET category_name='Truck Bed and Tailgate', sub_category_name='Truck Bed Toolboxes and Accessories'
WHERE id = 1262;

-- 17488 (36): "Bolt Kit For PACK RAT Drawer Units", "Drawer Bearing",
--   "Drawer Roller Kit" — PACK RAT van drawer parts.
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Shelving'
WHERE id = 17488;

-- 48264 (28): "Latch Rod Kit", "Latch Rod Kit Cover" — toolbox latches.
UPDATE pcdb_part_type SET category_name='Truck Bed and Tailgate', sub_category_name='Truck Bed Toolboxes and Accessories'
WHERE id = 48264;

-- 18387 (23): "Cab Protector Mounting Kit", "Compact Cab Protector Mounting Kit"
--   — cab-divider hardware. Belongs under Cab Partitions and Dividers.
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Cab Partitions and Dividers'
WHERE id = 18387;

-- 1328 (21): "Window Screen", "Window Screens" — cab-divider window screens.
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Cab Partitions and Dividers'
WHERE id = 1328;

-- 48637 (19): "Bolt Kit", "Replacement Bolt Kit", "Underbed Striker Bolt Kit"
--   — generic toolbox bolt kits.
UPDATE pcdb_part_type SET category_name='Truck Bed and Tailgate', sub_category_name='Truck Bed Toolboxes and Accessories'
WHERE id = 48637;

-- 12393 (12): "Van Floor Mats" — van cargo-area floor protection.
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Shelving'
WHERE id = 12393;

-- 49389 (3): "Ratchet Straps w/Mounting Brackets", "Replacement Tie Down Kit"
--   — cargo tie-downs.
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Tie Downs and Anchors'
WHERE id = 49389;

-- 19895 (3): "Composite Bulkhead Accessory Template", "Leveling Spacer"
--   — cab-divider install hardware.
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Cab Partitions and Dividers'
WHERE id = 19895;

-- 15437 (2): "Cabinet Tray" — van cabinet/shelving accessory.
UPDATE pcdb_part_type SET category_name='Cargo Management', sub_category_name='Van Shelving'
WHERE id = 15437;

-- ---------------------------------------------------------------------
-- BLOCK B: Backfill product_category rows for every Weatherguard product
-- whose part_type now has a category mapping (covers BOTH the part_types
-- we just updated AND any that were already mapped but missed during
-- the initial ingest run).
-- ---------------------------------------------------------------------

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT
  p.id            AS product_id,
  c.id            AS category_id,
  TRUE            AS is_primary,
  NOW()           AS created_at,
  NOW()           AS updated_at
FROM product p
JOIN pace_part pp        ON pp.product_id = p.id
JOIN pcdb_part_type pt   ON pt.id = pp.part_terminology_id
JOIN category c          ON c.name = pt.sub_category_name
                         AND c.full_path = pt.category_name || ' > ' || pt.sub_category_name
WHERE p.brand_id = 71
  AND pt.category_name IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM product_category pc
    WHERE pc.product_id = p.id AND pc.category_id = c.id
  )
ON CONFLICT DO NOTHING;

-- =====================================================================
-- Verify coverage
-- =====================================================================

-- Run after the script to confirm:
--   SELECT COUNT(*) AS still_unmapped FROM product p
--   WHERE p.brand_id = 71
--     AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);
--
--   SELECT cat.full_path, COUNT(*) AS n FROM product p
--   JOIN product_category pc ON pc.product_id = p.id
--   JOIN category cat ON cat.id = pc.category_id
--   WHERE p.brand_id = 71
--   GROUP BY cat.full_path ORDER BY n DESC;
