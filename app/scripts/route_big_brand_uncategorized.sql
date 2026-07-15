-- =====================================================================
-- route_big_brand_uncategorized.sql — 2026-05-11
--
-- Six major brands shipped to the catalog with thousands of products
-- that have NO product_category row at all.  Effect: a customer
-- browsing /catalog?brand=Lund sees 7,648 products, but navigating to
-- Floor Mats and Cargo Liners only sees what's been categorized — the
-- 1,469 Lund CATCH-IT mats and 1,295 CATCH-ALL mats don't show up
-- under Floor Mats even though they obviously belong there.
--
-- Audit from /api/catalog/brands vs product_category coverage:
--   WeatherTech    38,093 total / 16,817 uncategorized (44%)
--   Dometic         9,725 total /  9,226 uncategorized (95%)  ← left alone
--                                                              (SKU-only
--                                                               replacement
--                                                               parts, no
--                                                               name to
--                                                               pattern-
--                                                               match)
--   Lund            7,648 total /  4,911 uncategorized (64%)
--   Rugged Ridge    5,951 total /  4,627 uncategorized (78%)
--   K&N Filters     8,296 total /  6,822 uncategorized (82%)
--   DECKED          1,239 total /  1,220 uncategorized (98%)
--
-- This script routes by name-pattern.  Cumulative reach: ~15,000 SKUs
-- newly visible in their natural category.
--
-- Category IDs (verified):
--   182 — Truck Accessories > Interior > Floor Mats and Cargo Liners
--    98 — Truck Accessories > Exterior > Mud Guards and Mud Flaps
--   336 — Truck Accessories > Truck Bed and Tailgate > Truck Bed Toolboxes
--     1 — Truck Accessories > Air Intakes
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: WeatherTech floor mats / cargo liners (~7,700 SKUs)
-- Name patterns: "Cargo*" "Front*" all the way through.
-- Confirmed via uncat-first-word audit: Cargo (5,368), Front (2,355).
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 182, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'WeatherTech'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND (
    p.name ILIKE 'Cargo%'
    OR p.name ILIKE 'Front%'
    OR p.name ILIKE 'FloorLiner%'
    OR p.name ILIKE 'AVM %'
    OR p.name ILIKE 'All-Weather%'
    OR p.name ILIKE 'Rear FloorLiner%'
  )
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK B: WeatherTech mud flaps + lamp guards (smaller categories
-- but obvious placement).
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 98, TRUE, NOW(), NOW()  -- Mud Guards and Mud Flaps
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'WeatherTech'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND (
    p.name ILIKE 'MudFlap%'
    OR p.name ILIKE 'No Drill MudFlap%'
    OR p.name ILIKE 'No-Drill MudFlap%'
  )
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK C: Lund Catch-It / Catch-All / Proline floor mats (~3,200 SKUs)
-- These are floor mat product LINES, all belong in Floor Mats.
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 182, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'Lund'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND (
    p.name ILIKE 'Catch-It%'
    OR p.name ILIKE 'CATCH-IT%'
    OR p.name ILIKE 'Catch-All%'
    OR p.name ILIKE 'CATCH-ALL%'
    OR p.name ILIKE 'Proline%'
    OR p.name ILIKE '%FLOORMAT%'
    OR p.name ILIKE '%Floor Mat%'
  )
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK D: Rugged Ridge "All Terrain Floor Liners" (~1,100 SKUs).
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 182, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'Rugged Ridge'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND (
    p.name ILIKE 'All Terrain Floor Liner%'
    OR p.name ILIKE 'All-Terrain Floor Liner%'
    OR p.name ILIKE '%Floor Liner%'
    OR p.name ILIKE '%Floor Mat%'
  )
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK E: DECKED drawer / slide / wallslide systems (~700 SKUs)
-- These are truck-bed organization products.
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 336, TRUE, NOW(), NOW()  -- Truck Bed Toolboxes and Accessories
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'DECKED'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND (
    p.name ILIKE 'Slide%'
    OR p.name ILIKE 'WallSlide%'
    OR p.name ILIKE 'CargoGlide%'
    OR p.name ILIKE 'Sliding%'
    OR p.name ILIKE 'DECKED%'
    OR p.name ILIKE 'Bulkhead%'
    OR p.name ILIKE '%Drawer%'
    OR p.name ILIKE '%Tool Box%'
    OR p.name ILIKE '%Tool-Box%'
  )
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK F: K&N Filters replacement filters + oil products (~4,500 SKUs)
-- "Replacement Air Filter", "Universal Panel Filter", "Air Filter
-- Gasket" all go to Air Intakes (where the existing 1,474 K&N cold-air-
-- intake kits already live).  Motor oils stay uncategorized — no
-- appropriate motor-oil category exists.
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 1, TRUE, NOW(), NOW()  -- Air Intakes
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE b.name = 'K&N Filters'
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE
  AND (
    p.name ILIKE 'Replacement Air Filter%'
    OR p.name ILIKE 'Universal Panel Filter%'
    OR p.name ILIKE 'Air Filter%'
    OR p.name ILIKE 'Performance Air Filter%'
    OR p.name ILIKE 'Round Air Filter%'
    OR p.name ILIKE 'Universal Air Filter%'
    OR p.name ILIKE 'Cold Air Intake%'
    OR p.name ILIKE 'Cabin Air Filter%'
  )
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- Verification: counts after script applies
-- ---------------------------------------------------------------------
SELECT 'Floor Mats and Cargo Liners' AS cat,
       (SELECT COUNT(DISTINCT pc.product_id)
        FROM product_category pc JOIN product p ON p.id = pc.product_id
        JOIN brand b ON b.id = p.brand_id
        WHERE pc.category_id = 182 AND p.is_for_sale = TRUE AND p.is_hidden = FALSE AND b.is_active = TRUE) AS count
UNION ALL SELECT 'Mud Guards and Mud Flaps',
       (SELECT COUNT(DISTINCT pc.product_id) FROM product_category pc JOIN product p ON p.id = pc.product_id JOIN brand b ON b.id = p.brand_id
        WHERE pc.category_id = 98 AND p.is_for_sale = TRUE AND p.is_hidden = FALSE AND b.is_active = TRUE)
UNION ALL SELECT 'Truck Bed Toolboxes',
       (SELECT COUNT(DISTINCT pc.product_id) FROM product_category pc JOIN product p ON p.id = pc.product_id JOIN brand b ON b.id = p.brand_id
        WHERE pc.category_id = 336 AND p.is_for_sale = TRUE AND p.is_hidden = FALSE AND b.is_active = TRUE)
UNION ALL SELECT 'Air Intakes',
       (SELECT COUNT(DISTINCT pc.product_id) FROM product_category pc JOIN product p ON p.id = pc.product_id JOIN brand b ON b.id = p.brand_id
        WHERE pc.category_id = 1 AND p.is_for_sale = TRUE AND p.is_hidden = FALSE AND b.is_active = TRUE);
