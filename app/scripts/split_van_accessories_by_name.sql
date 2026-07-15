-- =====================================================================
-- split_van_accessories_by_name.sql — 2026-05-10
--
-- PCDB part_type 18397 ("Accessory ..." per Weather Guard's PIES feed)
-- turned out to be a catch-all for *all* WG van-equipment products,
-- not just accessories. Inspecting the 369 distinct product names
-- under that part_type reveals at least four distinct product families
-- lumped together:
--   1. Actual Van Shelving (Shelf Unit, Drawer Unit, Cabinet, Bin Set,
--      Storage Module, Door Organizer, Catalog File ...) — should be
--      in Cargo Management > Van Shelving.
--   2. Turnkey Van Packages (Plumber Van Package, Electrical
--      Contractor Van Package, Commercial Shelving Van Package ...) —
--      should be in Cargo Management > Van Packages (currently empty).
--   3. Cab partitions / bulkheads (Full Bulkhead Window, Composite
--      Bulkhead, Compact Bulkhead Mesh, High Bulkhead Screen ...) —
--      should be in Cargo Management > Cab Partitions and Dividers.
--   4. Van Racks (All-Purpose Steel Van Rack, Safari Rack, Service
--      Body Rack, Conduit Carrier) — should be in Cargo Management >
--      Truck and Van Racks.
--
-- Van Accessories then becomes what it should be: mounting hardware,
-- bolt kits, replacement parts, organizer hooks/holders, PACK RAT /
-- ITEMIZER drawer hardware — the "long-tail" SKUs.
--
-- This script MOVEs product_category rows (UPDATE instead of INSERT)
-- so each product keeps a single primary category.
-- Idempotent — running twice has no effect after the first pass.
-- =====================================================================

-- Capture target category IDs once
WITH ids AS (
  SELECT
    (SELECT id FROM category WHERE full_path = 'Cargo Management > Van Accessories')        AS van_acc_id,
    (SELECT id FROM category WHERE full_path = 'Cargo Management > Van Shelving')           AS van_shelv_id,
    (SELECT id FROM category WHERE full_path = 'Cargo Management > Van Packages')           AS van_pkg_id,
    (SELECT id FROM category WHERE full_path = 'Cargo Management > Cab Partitions and Dividers') AS cab_part_id,
    (SELECT id FROM category WHERE full_path = 'Cargo Management > Truck and Van Racks')    AS van_rack_id
)
-- ---------------------------------------------------------------------
-- BLOCK A: -> Van Shelving (actual storage units)
-- ---------------------------------------------------------------------
, move_shelving AS (
  UPDATE product_category pc
  SET category_id = (SELECT van_shelv_id FROM ids)
  FROM product p, ids
  WHERE pc.product_id = p.id
    AND pc.category_id = ids.van_acc_id
    AND p.brand_id = 71
    AND (
      p.name ILIKE '%Shelf Unit%'
      OR p.name ILIKE '%Drawer Unit%'
      OR p.name ILIKE '%Cabinet%'
      OR p.name ILIKE '%Cabinets And Drawers%'
      OR p.name ILIKE '%Storage Module%'
      OR p.name ILIKE '%Bin Set%'
      OR p.name = 'Accessory Shelf'
      OR p.name = 'Accessory Panel Unit'
      OR p.name = 'Door Organizer Closed Trays'
      OR p.name = 'Catalog File Unit'
      OR p.name ILIKE '%Cab Command Center%'
      OR p.name = 'Cabinet Tray'
      OR p.name = 'Bulkhead Panel'
      OR p.name = 'Tapered End Panel Set'
    )
  RETURNING pc.product_id
)
-- ---------------------------------------------------------------------
-- BLOCK B: -> Van Packages (turnkey contractor van builds)
-- ---------------------------------------------------------------------
, move_packages AS (
  UPDATE product_category pc
  SET category_id = (SELECT van_pkg_id FROM ids)
  FROM product p, ids
  WHERE pc.product_id = p.id
    AND pc.category_id = ids.van_acc_id
    AND p.brand_id = 71
    AND p.name ILIKE '%Van Package%'
  RETURNING pc.product_id
)
-- ---------------------------------------------------------------------
-- BLOCK C: -> Cab Partitions and Dividers (bulkheads + cab protector mounts)
-- ---------------------------------------------------------------------
, move_partitions AS (
  UPDATE product_category pc
  SET category_id = (SELECT cab_part_id FROM ids)
  FROM product p, ids
  WHERE pc.product_id = p.id
    AND pc.category_id = ids.van_acc_id
    AND p.brand_id = 71
    AND (
      p.name ILIKE '%Bulkhead%'
      OR p.name ILIKE '%Cab Protector%'
      OR p.name = 'Window Screen'
      OR p.name = 'Window Screens'
    )
  RETURNING pc.product_id
)
-- ---------------------------------------------------------------------
-- BLOCK D: -> Truck and Van Racks (actual rack systems)
-- ---------------------------------------------------------------------
, move_racks AS (
  UPDATE product_category pc
  SET category_id = (SELECT van_rack_id FROM ids)
  FROM product p, ids
  WHERE pc.product_id = p.id
    AND pc.category_id = ids.van_acc_id
    AND p.brand_id = 71
    AND (
      p.name = 'All-Purpose Steel Van Rack'
      OR p.name = 'Safari Rack'
      OR p.name = 'Safari Van Rack'
      OR p.name = 'Service Body Rack'
      OR p.name = 'Quick Clamp Rack'
      OR p.name = 'Refrigerant Tank Rack'
      OR p.name ILIKE 'Conduit Carrier%'
    )
  RETURNING pc.product_id
)
SELECT
  (SELECT COUNT(*) FROM move_shelving)   AS to_shelving,
  (SELECT COUNT(*) FROM move_packages)   AS to_packages,
  (SELECT COUNT(*) FROM move_partitions) AS to_partitions,
  (SELECT COUNT(*) FROM move_racks)      AS to_racks;

-- =====================================================================
-- Verify after running:
--   SELECT cat.full_path, COUNT(DISTINCT p.id) AS n FROM product p
--   JOIN product_category pc ON pc.product_id = p.id
--   JOIN category cat ON cat.id = pc.category_id
--   WHERE p.brand_id = 71 AND cat.full_path LIKE 'Cargo Management%'
--   GROUP BY cat.full_path ORDER BY n DESC;
-- =====================================================================
