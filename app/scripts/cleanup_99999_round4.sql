-- =====================================================================
-- cleanup_99999_round4.sql — 2026-05-11
--
-- Fourth-pass cleanup of the 99999 misc bucket.  Three previous rounds
-- (cleanup_99999_stragglers.sql + cleanup_99999_remaining_brands.sql +
-- cleanup_99999_round3.sql) reduced the bucket from ~3,100 SKUs to 102
-- uncategorized active SKUs.
--
-- This script handles the remaining 102 by either:
--   (a) name-pattern categorizing into existing categories
--       (Westin tonneau covers, OVS camping, Husky floor mats, Aries
--       grille guards, Retrax rails, Firestone air springs, Arc lights),
--   (b) DEACTIVATING items that aren't real consumer products at all
--       (B&W display stands, Rigid POP/swag/catalog/banner/hat items,
--       Big Country catalogs/banners, etc.).  These were probably
--       seeded from PIES feeds that include dealer/retailer materials
--       alongside actual SKUs.
--
-- "Deactivate" here means setting product.is_for_sale = FALSE so the
-- product hides from /browse + /search (which filter on is_for_sale =
-- TRUE) but stays in the DB for restoration if needed.  SKU-only items
-- with no descriptive names ("GH-12011", "395030879") are intentionally
-- left as-is — without information, we can't make a judgment call.
-- =====================================================================

-- (a) Categorize the SKUs we have clear pattern matches for.

-- Westin Hard Roll-Up Tonneau Covers (10 SKUs) -> Hard Rolling Truck Bed Covers
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 340, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'Westin'
  AND p.name ILIKE '%Hard Roll-Up Tonneau%'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- OVS Wild Land + camping gear (25 SKUs) -> Camping and Outdoor Gear
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 205, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'OVERLAND VEHICLE SYSTEMS'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- Husky floor liners (2) -> Floor Mats and Cargo Liners
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 182, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'Husky Liners'
  AND (p.name ILIKE '%floor liner%' OR p.name ILIKE '%floor mat%')
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- Aries grille guards (2) -> Grille Guards (id=55)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 55, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'Aries Offroad'
  AND p.name ILIKE '%grille guard%'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- Retrax replacement rails (2) -> Truck Bed Cover Parts and Accessories (id=347)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 347, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'Retrax'
  AND p.name ILIKE '%Rpl Rails%'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- Firestone AirRide air-spring service parts (4) -> Air Spring Kits (id=274)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 274, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'Firestone AirRide'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- Arc Lighting grille kit (1) -> LED Light Bars (id=33)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 33, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'Arc Lighting'
  AND p.name ILIKE '%Grille Kit%'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- Go Rhino Rigid Lights (1) -> LED Light Bars (id=33)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 33, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'Go Rhino'
  AND p.name ILIKE '%Rigid Lights%'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- GEN-Y named items (2 of 14)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 306, TRUE, NOW(), NOW()  -- Hitch Accessories
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'GEN-Y Hitch'
  AND p.name ILIKE '%Stabilizer Bars%'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 304, TRUE, NOW(), NOW()  -- Gooseneck Hitches and Accessories
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 99999
  AND b.name = 'GEN-Y Hitch'
  AND p.name ILIKE '%Gooseneck Coupler%'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- (b) Deactivate dealer-only / POP / merch / catalog / display items.
-- These are PIES entries for dealer-facing materials, not consumer SKUs.

-- B&W display stands (all 7 items have "Display Stand" or are
-- "*Center" point-of-sale fixtures rather than products)
UPDATE product
SET is_for_sale = FALSE
WHERE id IN (
  SELECT p.id FROM product p
  JOIN brand b ON b.id = p.brand_id
  JOIN pace_part pp ON pp.product_id = p.id
  WHERE pp.part_terminology_id = 99999
    AND b.name = 'B&W Towing'
    AND (p.name ILIKE '%Display Stand%' OR p.name ILIKE '%Center%')
);

-- Rigid Industries POP / hats / stickers / swag / sales-case items.
-- Identified by SKU prefix FLWB-99xxx (POP+display) or by name keywords.
UPDATE product
SET is_for_sale = FALSE
WHERE id IN (
  SELECT p.id FROM product p
  JOIN brand b ON b.id = p.brand_id
  JOIN pace_part pp ON pp.product_id = p.id
  WHERE pp.part_terminology_id = 99999
    AND b.name = 'Rigid Industries'
    AND (
      p.name ILIKE '%Display%'
      OR p.name ILIKE '%POP%'
      OR p.name ILIKE '%Hat %' OR p.name ILIKE '% Hat'
      OR p.name ILIKE '%Sticker%'
      OR p.name ILIKE '%Swag%'
      OR p.name ILIKE '%Apparel%'
      OR p.name ILIKE '%Sales Case%'
    )
);

-- Big Country catalog + banner items
UPDATE product
SET is_for_sale = FALSE
WHERE id IN (
  SELECT p.id FROM product p
  JOIN brand b ON b.id = p.brand_id
  JOIN pace_part pp ON pp.product_id = p.id
  WHERE pp.part_terminology_id = 99999
    AND b.name = 'Big Country'
    AND (p.name ILIKE '%Catalog%' OR p.name ILIKE '%Banner%')
);

-- Rough Country "Other Finished Goods" (1) -- a placeholder PIES entry,
-- not a real product
UPDATE product
SET is_for_sale = FALSE
WHERE id IN (
  SELECT p.id FROM product p
  JOIN brand b ON b.id = p.brand_id
  JOIN pace_part pp ON pp.product_id = p.id
  WHERE pp.part_terminology_id = 99999
    AND b.name = 'Rough Country'
    AND p.name = 'Other Finished Goods'
);

-- Summary
SELECT 'After round 4' AS stage,
  COUNT(DISTINCT pp.product_id) AS remaining_uncategorized_99999_active
FROM pace_part pp
JOIN product p ON p.id = pp.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pp.part_terminology_id = 99999
  AND p.is_for_sale = TRUE AND p.is_hidden = FALSE AND b.is_active = TRUE
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);
