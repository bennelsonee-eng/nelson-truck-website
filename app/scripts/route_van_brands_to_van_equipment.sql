-- =====================================================================
-- route_van_brands_to_van_equipment.sql — 2026-05-11
--
-- Two van-specific brands shipped without proper category routing,
-- making Van Equipment look near-empty (482 SKUs, all Weatherguard)
-- when it should be the home for ~1,800 SKUs:
--
--   Flatline Van Co.       (300 active, 248 uncategorized)
--   Legend Fleet Solutions (1,044 active, 0 categorized)
--
-- Plus the May-10 split_van_accessories_by_name.sql move shifted 21
-- Weatherguard rack SKUs into Truck Accessories > Cargo Management >
-- Truck and Van Racks.  Those products are van-specific or
-- cross-vehicle (All-Purpose Steel Van Rack, Conduit Carrier, Cab
-- Protector Ladder Mount...).  They should show up under Van
-- Equipment too — we add a NON-primary product_category row pointing
-- at Van Equipment > Van Accessories so the browse + nav surface
-- them in both parents.
--
-- Category IDs (verified live):
--   393 — Van Equipment (parent)
--    59 — Van Equipment > Cab Partitions and Dividers
--   373 — Van Equipment > Van Accessories
--    70 — Van Equipment > Van Packages
--    71 — Van Equipment > Van Shelving
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Cross-list Weatherguard "Truck and Van Racks" + "Cargo Racks"
-- under Van Equipment > Van Accessories.  These were correctly
-- categorized under Cargo Management for truck-side discovery, but
-- they're also van-applicable and a van buyer browsing Van Equipment
-- should see them.  Add as non-primary product_category (keeps the
-- truck-side categorization intact).
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT DISTINCT p.id, 373, FALSE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN product_category pc ON pc.product_id = p.id
JOIN category c ON c.id = pc.category_id
WHERE b.name = 'Weatherguard'
  AND c.full_path IN (
    'Truck Accessories > Cargo Management > Truck and Van Racks',
    'Truck Accessories > Cargo Management > Cargo Racks'
  )
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK B: Flatline Van Co. — categorize the 248 uncategorized SKUs.
-- Name patterns split into 2 buckets:
--   - bed system / bed mount → Van Packages (turnkey camper builds)
--   - everything else → Van Accessories
-- The 52 already-categorized Flatline SKUs (40 in Cargo Racks, 7 Front
-- Bumpers, 5 Lift Kit Accessories) get a non-primary Van Accessories
-- cross-listing so van buyers find them too.
-- ---------------------------------------------------------------------

-- B.1: Bed systems → Van Packages (primary)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 70, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'Flatline Van Co.'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND (p.name ILIKE '%bed system%' OR p.name ILIKE '%bed mount%')
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- B.2: Everything else uncategorized → Van Accessories (primary)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 373, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'Flatline Van Co.'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- B.3: Cross-list already-categorized Flatline rack/bumper/lift products
-- under Van Accessories (non-primary)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT DISTINCT p.id, 373, FALSE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'Flatline Van Co.'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK C: Legend Fleet Solutions — categorize all 1,044 active SKUs.
-- Name patterns split into 2 buckets:
--   - Bulkhead / Partition → Cab Partitions and Dividers (primary)
--   - everything else → Van Accessories (primary)
-- Legend Fleet's product lines (DuraTherm, EconoLite, StabiliGrip,
-- AutoMat, TempShield) are all interior outfitting — floor mats, wall
-- liners, thermal insulation, partitions.  All belong in Van Equipment.
-- ---------------------------------------------------------------------

-- C.1: Partitions / Bulkheads → Cab Partitions and Dividers (primary)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 59, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'Legend Fleet Solutions'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND (p.name ILIKE '%bulkhead%' OR p.name ILIKE '%partition%' OR p.name ILIKE '%divider%')
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- C.2: Everything else → Van Accessories (primary)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 373, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'Legend Fleet Solutions'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Verification: counts under Van Equipment by sub-cat after this script
-- ---------------------------------------------------------------------
SELECT c.full_path, COUNT(DISTINCT pc.product_id) AS sellable_products
FROM category c
LEFT JOIN product_category pc ON pc.category_id = c.id
LEFT JOIN product p ON p.id = pc.product_id
LEFT JOIN brand b ON b.id = p.brand_id
WHERE c.full_path = 'Van Equipment' OR c.full_path LIKE 'Van Equipment > %'
  AND (p.is_for_sale = TRUE AND p.is_hidden = FALSE AND b.is_active = TRUE)
GROUP BY c.full_path
ORDER BY c.full_path;
