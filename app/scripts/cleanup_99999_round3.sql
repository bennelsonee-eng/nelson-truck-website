-- =====================================================================
-- cleanup_99999_round3.sql — 2026-05-11
--
-- Final small-volume cleanup of the 99999 misc bucket. Inspection of
-- remaining brands shows most stragglers are either:
--   (a) Addressable by an obvious brand+name rule (Westin Roll-Up,
--       Bak BAKFlip, Firestone bellows, DECKED drawer system)
--   (b) Non-product items — display stands / banners / catalogs /
--       camping accessories that aren't part of the parts catalog
--   (c) SKU-only names ("GH-13013X", "395030879") with no descriptive
--       name to pattern-match
--
-- This script handles (a). Total covered: ~30 SKUs across 4 brands.
-- (b) and (c) are deliberately left uncategorized.
-- =====================================================================

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, cat_target.id, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
CROSS JOIN LATERAL (
  SELECT id FROM category WHERE name = (
    CASE
      WHEN b.name = 'Westin' AND p.name ILIKE '%roll-up tonneau%'
        THEN 'Soft Roll-Up Truck Bed Covers'
      WHEN b.name = 'Bak Industries' AND p.name ILIKE '%BAKFlip%'
        THEN 'Hard Folding Truck Bed Covers'
      WHEN b.name = 'Firestone AirRide' AND
           (p.name ILIKE '%bellows%' OR p.name ILIKE '%spring%' OR p.name ILIKE '%ride-rite%')
        THEN 'Air Spring Kits'
      WHEN b.name = 'DECKED' AND p.name ILIKE '%drawer system%'
        THEN 'Truck Bed Toolboxes and Accessories'
      WHEN b.name = 'Big Country' AND p.name ILIKE '%side bar%'
        THEN 'Step Bars'
      WHEN b.name = 'B&W Towing' AND
           (p.name ILIKE '%hitch lock%' OR p.name ILIKE '%accessory tray%')
        THEN 'Hitch Accessories'
      ELSE NULL
    END
  )
  ORDER BY id LIMIT 1
) cat_target
WHERE pp.part_terminology_id = 99999
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);
