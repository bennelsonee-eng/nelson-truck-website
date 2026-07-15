-- =====================================================================
-- cleanup_99999_stragglers.sql — 2026-05-10
--
-- After fix_part_type_99999_misclassification.sql deleted the bogus
-- Grille Guards rows, several brands' products that had ONLY part_type
-- 99999 (PACE's "miscellaneous" catch-all) became uncategorized. This
-- script routes them by product-name pattern + brand into the right
-- buckets.
--
-- Coverage:
--   WeatherTech: 2,324 Side Window Deflector variants -> Exterior > SWD
--   Yakima Products: 509 roof-rack accessories
--                    (Clip, BaseClip, RidgeClip, SKS Lock Cores, Jet
--                     Stream, CrossBar, Core Bar, Control Tower, Roof
--                     Tracks, Wind Fairing, ...)
--                    -> Cargo Management > Rack Accessories
--   FIA: 127 (mostly seat covers / accessories — left for later)
--   Overland Vehicle Systems: 108 (mostly off-road / rooftop accessories — later)
--   Husky Liners: 41 (mostly mud guards / liners — later)
--
-- Idempotent: each INSERT uses NOT EXISTS.
-- =====================================================================

-- WeatherTech window deflectors -> Side Window Deflectors
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id,
       (SELECT id FROM category WHERE name = 'Side Window Deflectors'),
       TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE b.name = 'WeatherTech'
  AND pp.part_terminology_id = 99999
  AND p.name ILIKE '%Window Deflector%'
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- Yakima rack accessories -> Rack Accessories
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id,
       (SELECT id FROM category WHERE name = 'Rack Accessories'),
       TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
WHERE b.name = 'Yakima Products'
  AND pp.part_terminology_id = 99999
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);
