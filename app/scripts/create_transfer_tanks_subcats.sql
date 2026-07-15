-- =====================================================================
-- create_transfer_tanks_subcats.sql — 2026-05-14
--
-- Owner asked for "Transfer Tanks" to be its own subcategory under
-- BOTH Truck Accessories and Truck Equipment.
--
-- Current state:
--   * id 335 = "Transfer Tanks and Accessories" — lives buried inside
--     "Truck Accessories > Truck Bed and Tailgate", 317 active SKUs.
--   * id 334 = "Transfer Tank and Toolbox Combinations" — also under
--     Truck Bed and Tailgate, currently EMPTY (0 SKUs).  Left alone.
--   * Truck Equipment has no Transfer Tanks subcategory at all.
--
-- Strategy:
--   STEP 1: Promote id 335 to a top-level Truck Accessories subcat
--           (sibling of Exterior / Interior / Truck Bed Covers).
--           Also rename to the cleaner "Transfer Tanks" and re-slug.
--   STEP 2: Create a NEW top-level "Transfer Tanks" subcategory under
--           Truck Equipment.
--   STEP 3: Cross-list every product currently in id 335 into the
--           new Truck Equipment cat (same 317 SKUs visible in both
--           menus, ON CONFLICT DO NOTHING keeps it idempotent).
--
-- Mega-menu references in App.tsx use the cleaner full_path:
--   Truck Accessories > Transfer Tanks
--   Truck Equipment   > Transfer Tanks
-- =====================================================================

-- ---------------------------------------------------------------------
-- STEP 1: Promote cat 335 to top-level Truck Accessories
-- ---------------------------------------------------------------------
UPDATE category
SET parent_id = 394,                          -- Truck Accessories root
    depth     = 1,                            -- was 2 (nested under Truck Bed and Tailgate)
    name      = 'Transfer Tanks',             -- was 'Transfer Tanks and Accessories'
    slug      = 'transfer-tanks',             -- was 'truck-bed-and-tailgate/transfer-tanks-and-accessories'
    full_path = 'Truck Accessories > Transfer Tanks',
    updated_at = NOW()
WHERE id = 335;

-- ---------------------------------------------------------------------
-- STEP 2: Create a new Transfer Tanks subcategory under Truck Equipment
-- ---------------------------------------------------------------------
INSERT INTO category (name, slug, parent_id, full_path, depth,
                      sort_order, is_featured, is_active, created_at, updated_at)
VALUES ('Transfer Tanks',
        'transfer-tanks',
        391,                                  -- Truck Equipment root
        'Truck Equipment > Transfer Tanks',
        1,
        1000,
        FALSE,
        TRUE,
        NOW(), NOW())
ON CONFLICT (full_path) DO NOTHING;

-- ---------------------------------------------------------------------
-- STEP 3: Cross-list all products from cat 335 into the new
--         Truck Equipment > Transfer Tanks cat.  is_primary=FALSE
--         since cat 335 stays the primary listing.
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id,
       (SELECT id FROM category WHERE full_path = 'Truck Equipment > Transfer Tanks'),
       FALSE,
       NOW(), NOW()
FROM product_category pc
JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 335
  AND p.is_for_sale AND NOT p.is_hidden AND b.is_active
ON CONFLICT (product_id, category_id) DO NOTHING;

-- =====================================================================
-- Verification
-- =====================================================================
SELECT c.id, c.full_path, c.depth, COUNT(DISTINCT pc.product_id) AS n
FROM category c
LEFT JOIN product_category pc ON pc.category_id = c.id
LEFT JOIN product p ON p.id = pc.product_id
LEFT JOIN brand b ON b.id = p.brand_id
WHERE c.full_path ILIKE '%Transfer Tank%'
  AND (p.is_for_sale IS NULL OR (p.is_for_sale AND NOT p.is_hidden AND b.is_active))
GROUP BY c.id, c.full_path, c.depth
ORDER BY c.full_path;
