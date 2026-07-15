-- =====================================================================
-- add_lippert_dometic_categories.sql — 2026-05-10
--
-- Re-activate Lippert + Dometic brands and route their products to the
-- right categories. Lippert is 70% trailer axles/brakes and 30% RV
-- appliances (mostly its Furrion sub-brand). Dometic is mostly RV
-- appliances (awnings, AC, fridges, toilets).
--
-- Approach:
--   1. Make sure brands are active.
--   2. Create a new "RV Accessories" top-level with sub-categories for
--      Awnings, Air Conditioning, Refrigerators, Furnaces & Water
--      Heaters, Cooktops & Ranges, Toilets, Slide-Outs, Interior, and
--      a catch-all RV Accessories sub-bucket.
--   3. Backfill product_category for Lippert + Dometic by product-name
--      pattern. Priority order: more specific patterns first.
--
-- Idempotent — uses NOT EXISTS / ON CONFLICT.
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Activate brands
-- ---------------------------------------------------------------------
UPDATE brand SET is_active = TRUE
WHERE name IN ('Lippert Components', 'Dometic') AND is_active = FALSE;


-- ---------------------------------------------------------------------
-- BLOCK B: Create RV Accessories top-level + sub-categories
-- ---------------------------------------------------------------------
-- Top-level
INSERT INTO category (name, slug, parent_id, full_path, depth, sort_order, is_featured, is_active, created_at, updated_at)
SELECT 'RV Accessories', 'rv-accessories', NULL, 'RV Accessories', 0, 1000, FALSE, TRUE, NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM category WHERE full_path = 'RV Accessories');

-- Sub-categories
INSERT INTO category (name, slug, parent_id, full_path, depth, sort_order, is_featured, is_active, created_at, updated_at)
SELECT sub.name, sub.slug, p.id, 'RV Accessories > ' || sub.name, 1, 1000, FALSE, TRUE, NOW(), NOW()
FROM (SELECT id FROM category WHERE full_path = 'RV Accessories') p
CROSS JOIN (VALUES
  ('RV Awnings', 'rv-awnings'),
  ('RV Air Conditioning', 'rv-air-conditioning'),
  ('RV Refrigerators', 'rv-refrigerators'),
  ('RV Furnaces and Water Heaters', 'rv-furnaces-and-water-heaters'),
  ('RV Cooktops and Ranges', 'rv-cooktops-and-ranges'),
  ('RV Toilets', 'rv-toilets'),
  ('RV Slide-Outs', 'rv-slide-outs'),
  ('RV Interior', 'rv-interior'),
  ('RV Coolers', 'rv-coolers'),
  ('RV Vents and Fans', 'rv-vents-and-fans'),
  ('RV Bumpers and Body', 'rv-bumpers-and-body'),
  ('Misc RV Accessories', 'misc-rv-accessories')
) AS sub(name, slug)
WHERE NOT EXISTS (
  SELECT 1 FROM category WHERE full_path = 'RV Accessories > ' || sub.name
);


-- ---------------------------------------------------------------------
-- BLOCK C: Helper - target category IDs by full_path
-- We do all the inserts in one big query with a name-pattern CASE.
-- The first matching pattern wins (priority order is via CASE structure).
-- ---------------------------------------------------------------------

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT
  p.id,
  cat_target.id,
  TRUE,
  NOW(),
  NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
CROSS JOIN LATERAL (
  -- Match the product name against a priority-ordered list of category
  -- buckets. First match wins; if no match, this LATERAL returns nothing
  -- and the product stays uncategorized.
  SELECT id FROM category WHERE full_path = (
    CASE
      -- TRAILER PARTS (Lippert axle/brake/suspension product lines)
      WHEN p.name ILIKE '%axle%'              THEN 'Trailer Parts > Trailer Axles'
      WHEN p.name ILIKE '%brake assembly%'
        OR p.name ILIKE '%brake drum%'
        OR p.name ILIKE '%disc brake%'
        OR p.name ILIKE '%brake rotor%'
        OR p.name ILIKE '%brake conversion%'  THEN 'Trailer Parts > Trailer Brakes'
      WHEN p.name ILIKE '%hub assembly%'
        OR p.name ILIKE '%grease seal%'
        OR p.name ILIKE '%brake mounting%'
        OR p.name ILIKE '%wheel bolt%'
        OR p.name ILIKE '%bearing%'           THEN 'Trailer Parts > Trailer Axle Components'
      WHEN p.name ILIKE '%spring%'
        OR p.name ILIKE '%spindle%'
        OR p.name ILIKE '%shackle%'
        OR p.name ILIKE '%equalizer%'
        OR p.name ILIKE '%bushing%'           THEN 'Trailer Parts > Trailer Suspension'
      WHEN p.name ILIKE '%coupler%'
        OR p.name ILIKE '%jack%'
        OR p.name ILIKE '%trailer winch%'     THEN 'Trailer Parts > Trailer Jacks, Couplers, and Winches'

      -- RV ACCESSORIES
      WHEN p.name ILIKE '%awning%'
        OR p.name ILIKE '%screen room%'
        OR p.name ILIKE '%slidetopper%'       THEN 'RV Accessories > RV Awnings'
      WHEN p.name ILIKE '%air condition%'
        OR p.name ILIKE '%rooftop%'
        OR p.name ILIKE '%distribution box%'
        OR p.name ILIKE '% AC %'
        OR p.name ILIKE '%T-STAT%'
        OR p.name ILIKE '%thermostat%'
        OR p.name ILIKE '%penguin%'
        OR p.name ILIKE '%polar%'
        OR p.name ILIKE '%brisk%'             THEN 'RV Accessories > RV Air Conditioning'
      WHEN p.name ILIKE '%refrigerator%'
        OR p.name ILIKE '%fridge%'            THEN 'RV Accessories > RV Refrigerators'
      WHEN p.name ILIKE '%furnace%'
        OR p.name ILIKE '%water heater%'      THEN 'RV Accessories > RV Furnaces and Water Heaters'
      WHEN p.name ILIKE '%cooktop%'
        OR p.name ILIKE '%stove%'
        OR p.name ILIKE '%oven%'
        OR (p.name ILIKE '%range%' AND p.name NOT ILIKE '%long range%')
                                              THEN 'RV Accessories > RV Cooktops and Ranges'
      WHEN p.name ILIKE '%toilet%'
        OR p.name ILIKE '%pedal flush%'       THEN 'RV Accessories > RV Toilets'
      WHEN p.name ILIKE '%slide-out%'
        OR p.name ILIKE '%slide out%'
        OR p.name ILIKE '%gearmotor%'
        OR p.name ILIKE '%gear motor%'
        OR p.name ILIKE '%schwintek%'         THEN 'RV Accessories > RV Slide-Outs'
      WHEN p.name ILIKE '%cooler%'
        OR p.name ILIKE '%CFX%'
        OR p.name ILIKE '%CFF%'               THEN 'RV Accessories > RV Coolers'
      WHEN p.name ILIKE '%entrance door%'
        OR p.name ILIKE '%bath tub%'
        OR p.name ILIKE '%shower%'
        OR p.name ILIKE '%wall surround%'
        OR p.name ILIKE '%bunk%'              THEN 'RV Accessories > RV Interior'
      WHEN p.name ILIKE '%vent%'
        OR p.name ILIKE '%fan%'
        OR p.name ILIKE '%fantastic vent%'    THEN 'RV Accessories > RV Vents and Fans'
      WHEN p.name ILIKE '%bumper brace%'
        OR p.name ILIKE '%anchor plate%'
        OR p.name ILIKE '%trailer bumper%'    THEN 'RV Accessories > RV Bumpers and Body'

      -- Everything else with a real Lippert/Dometic-style name goes
      -- to the Misc bucket so it still appears somewhere; SKU-only
      -- names (e.g. "9600025400") are deliberately left uncategorized.
      WHEN p.name !~ '^[0-9A-Z\-\.]+$'        THEN 'RV Accessories > Misc RV Accessories'
      ELSE NULL
    END
  )
) AS cat_target
WHERE b.name IN ('Lippert Components', 'Dometic')
  AND NOT EXISTS (
    SELECT 1 FROM product_category pc
    WHERE pc.product_id = p.id AND pc.category_id = cat_target.id
  )
ON CONFLICT DO NOTHING;


-- =====================================================================
-- Verification (uncomment after running):
--   SELECT cat.full_path, b.name AS brand, COUNT(DISTINCT p.id) AS n
--   FROM product p
--   JOIN brand b ON b.id = p.brand_id
--   JOIN product_category pc ON pc.product_id = p.id
--   JOIN category cat ON cat.id = pc.category_id
--   WHERE b.name IN ('Lippert Components','Dometic')
--   GROUP BY cat.full_path, b.name
--   ORDER BY cat.full_path, b.name;
-- =====================================================================
