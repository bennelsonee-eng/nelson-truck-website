-- =====================================================================
-- populate_exterior_subcategories.sql — 2026-05-14
--
-- 32 of the 39 Truck Accessories > Exterior > * subcategories are empty
-- in our DB even though we have products that obviously belong in them
-- (Bestop soft tops, AVS headlight covers, hood scoops, fender liners,
-- spare tire covers, vehicle covers, etc.).  Audit shows ~1,200 SKUs
-- with clear name matches are sitting uncategorized or in the wrong
-- bucket entirely.
--
-- Strategy: for each target subcategory, INSERT a product_category row
-- (with ON CONFLICT DO NOTHING) when a product name matches one of a
-- short, conservative pattern list.  Products that were uncategorized
-- finally get a home; products that were already cross-listed somewhere
-- else get a second listing (only minor noise — accessories often
-- legitimately belong in multiple categories).
--
-- For one known-bad case (Soft Tops mis-routed to Hard Folding Tonneau,
-- 11 SKUs) we ALSO delete the wrong row.
--
-- Conservative scope: only the 8 cleanest cases this pass.  The harder
-- ones (Spoilers — 39 are tonneau-cap spoilers not vehicle spoilers;
-- Trim/Dress-Up — 106 are window-deflector trim) need refined patterns
-- and are left for a follow-up.
--
-- Target category IDs (verified):
--    80 — Emblems, Graphics and Decals
--    82 — Fender Liners and Accessories
--    86 — Grilles
--    88 — Headlight Covers
--    91 — Hood Scoops and Vents
--    95 — Mirrors
--   103 — Soft Tops and Accessories
--   104 — Spare Tire Covers
--   111 — Vehicle Covers
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Soft Tops and Accessories (id=103)
-- Bestop Sunrider / Trektop / Sailcloth, Rugged Ridge soft top
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 103, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Soft Top%'
    OR p.name ILIKE '%Sunrider%'
    OR p.name ILIKE '%Trektop%'
    OR p.name ILIKE '%Sailcloth%'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- Soft Top SKUs mis-routed to Hard Folding Tonneau (337) — remove those
DELETE FROM product_category pc
USING product p, brand b
WHERE pc.category_id = 337
  AND pc.product_id = p.id AND b.id = p.brand_id
  AND p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Soft Top%'
    OR p.name ILIKE '%Sunrider%'
    OR p.name ILIKE '%Trektop%'
    OR p.name ILIKE '%Sailcloth%'
  );

-- ---------------------------------------------------------------------
-- BLOCK B: Headlight Covers (id=88)
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 88, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (p.name ILIKE '%Headlight Cover%' OR p.name ILIKE '%Headlamp Cover%')
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK C: Hood Scoops and Vents (id=91)
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 91, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Hood Scoop%'
    OR p.name ILIKE '%Hood Vent%'
    OR p.name ILIKE '%Cowl Hood%'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK D: Emblems, Graphics and Decals (id=80)
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 80, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Emblem%'
    OR p.name ILIKE '%Decal%'
    OR p.name ILIKE '%Graphics Kit%'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK E: Spare Tire Covers (id=104)
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 104, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Spare Tire Cover%'
    -- "Tire Cover" alone is broad — only match if it's clearly a tire cover
    -- (not "Tire Carrier Cover" or similar): use phrase boundary heuristics
    OR p.name ~* '\mTire Cover\M'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK F: Fender Liners and Accessories (id=82)
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 82, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Fender Liner%'
    OR p.name ILIKE '%Inner Fender%'
    OR p.name ILIKE '%Wheel Well Liner%'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK G: Mirrors (id=95)
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 95, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Towing Mirror%'
    OR p.name ILIKE '%Manual Mirror%'
    OR p.name ILIKE '%Power Mirror%'
    OR p.name ILIKE '%Replacement Mirror%'
    OR p.name ILIKE '%Tow Mirror%'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK H: Vehicle Covers (id=111)
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 111, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Vehicle Cover%'
    OR p.name ILIKE '%Car Cover%'
    OR p.name ILIKE '%Truck Cover%'
    OR p.name ILIKE '%Custom-Fit Outdoor%'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK I: Grilles (id=86)
-- Conservative: only specific named-line grilles to avoid false positives
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 86, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Grille Insert%'
    OR p.name ILIKE '%Mesh Grille%'
    OR p.name ILIKE '%Billet Grille%'
    OR p.name ILIKE '%Stealth Grille%'
    OR p.name ILIKE '%Z-Series Grille%'
    OR p.name ILIKE '%LED Grille%'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- =====================================================================
-- Verification
-- =====================================================================
SELECT c.full_path, COUNT(DISTINCT pc.product_id) AS n
FROM category c
LEFT JOIN product_category pc ON pc.category_id = c.id
LEFT JOIN product p ON p.id = pc.product_id
LEFT JOIN brand b ON b.id = p.brand_id
WHERE c.id IN (80, 82, 86, 88, 91, 95, 103, 104, 111)
  AND (p.is_for_sale IS NULL OR (p.is_for_sale AND NOT p.is_hidden AND b.is_active))
GROUP BY c.full_path ORDER BY c.full_path;
