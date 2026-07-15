-- =====================================================================
-- cleanup_99999_remaining_brands.sql — 2026-05-10
--
-- Round 2 of the 99999 stragglers cleanup. Covers the remaining brands
-- whose products fell through the WeatherTech+Yakima first pass.
--
-- Approach: a single LATERAL-CTE INSERT routes by (brand, product-name
-- pattern) into the right category. Each pattern is priority-ordered
-- via a CASE expression; first match wins.
--
-- Coverage (uncategorized 99999 product counts as of run):
--   FIA              127  Seat-cover armrests + bucket seat covers
--   Overland Veh Sys 108  Roof rack systems + cargo boxes + RTT awnings
--   Husky Liners      41  Bed Rail Caps / Tailgate Caps / Cargo Liners /
--                         Ventvisor (Aeroskin) deflectors
--   Big Country       32  WIDESIDER step bars + Dakar PRO front guards
--   Auto Ventshade    25  Ventvisor / Aerovisor deflectors
--   GEN-Y Hitch       20  Pintle hitches + shanks + hitch hardware
--   Rugged Ridge      16  Window Rain Deflectors / Front Window Visors
--   Firestone AirRide 11  Air spring kit components
--   (Rigid Industries 24 deliberately left uncategorized — apparel /
--    POP displays, not products that ship to customers)
--
-- Idempotent — INSERT...WHERE NOT EXISTS.
-- =====================================================================

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT
  p.id, cat_target.id, TRUE, NOW(), NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
JOIN pace_part pp ON pp.product_id = p.id
CROSS JOIN LATERAL (
  SELECT id FROM category WHERE name = (
    CASE
      -- FIA: seat-cover armrest accessories + seat covers
      WHEN b.name = 'FIA'
        AND (p.name ILIKE '%armrest cover%' OR p.name ILIKE '%seat cover%'
             OR p.name ILIKE '%bucket seat%')
        THEN 'Seat Covers'

      -- Overland Vehicle Systems: roof rack systems, rooftop tents,
      --   cargo boxes — most fit Rack Accessories. Rooftop tent
      --   awnings/annexes could go in a dedicated cat once one exists.
      WHEN b.name = 'OVERLAND VEHICLE SYSTEMS'
        AND (p.name ILIKE '%rack%' OR p.name ILIKE '%cargo box%'
             OR p.name ILIKE '%awning%' OR p.name ILIKE '%annex%'
             OR p.name ILIKE '%tent%')
        THEN 'Rack Accessories'

      -- Husky Liners
      WHEN b.name = 'Husky Liners' AND
           (p.name ILIKE '%bed rail cap%' OR p.name ILIKE '%tailgate cap%')
        THEN 'Truck Bed Cap Accessories'
      WHEN b.name = 'Husky Liners' AND p.name ILIKE '%cargo liner%'
        THEN 'Floor Mats and Cargo Liners'
      WHEN b.name = 'Husky Liners' AND
           (p.name ILIKE '%aeroskin%' OR p.name ILIKE '%ventvisor%')
        THEN 'Side Window Deflectors'

      -- Big Country: step bars + bumper systems
      WHEN b.name = 'Big Country' AND p.name ILIKE '%widesider%'
        THEN 'Step Bars'
      WHEN b.name = 'Big Country' AND
           (p.name ILIKE '%dakar%' OR p.name ILIKE '%front guard%')
        THEN 'Grille Guards'

      -- Auto Ventshade: window deflectors
      WHEN b.name = 'Auto Ventshade' AND
           (p.name ILIKE '%ventvisor%' OR p.name ILIKE '%aerovisor%'
            OR p.name ILIKE '%ventshade deflector%' OR p.name ILIKE '%wind deflector%')
        THEN 'Side Window Deflectors'

      -- GEN-Y Hitch: pintle hitches + shanks + hitch hardware
      WHEN b.name = 'GEN-Y Hitch' AND p.name ILIKE '%pintle%'
        THEN 'Pintle Hooks and Mounts'
      WHEN b.name = 'GEN-Y Hitch' AND
           (p.name ILIKE '%hitch%' OR p.name ILIKE '%shank%'
            OR p.name ILIKE '%king pin%')
        THEN 'Hitches'

      -- Rugged Ridge: window deflectors / visors
      WHEN b.name = 'Rugged Ridge' AND
           (p.name ILIKE '%window%' OR p.name ILIKE '%visor%'
            OR p.name ILIKE '%rain deflector%')
        THEN 'Side Window Deflectors'

      -- Firestone AirRide: air-spring components
      WHEN b.name = 'Firestone AirRide' AND
           (p.name ILIKE '%air spring%' OR p.name ILIKE '%ride-rite%'
            OR p.name ILIKE '%spring%')
        THEN 'Air Spring Kits'

      ELSE NULL
    END
  )
  -- For Air Spring Kits there are TWO matching categories (Suspension
  -- side + Towing side). Prefer the Towing one for Firestone (their
  -- Ride-Rite product line is towing-focused).
  ORDER BY id LIMIT 1
) cat_target
WHERE pp.part_terminology_id = 99999
  AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id);

-- =====================================================================
-- Verify counts:
--   SELECT b.name, COUNT(DISTINCT p.id) AS still_uncat FROM product p
--   JOIN brand b ON b.id = p.brand_id
--   JOIN pace_part pp ON pp.product_id = p.id
--   WHERE pp.part_terminology_id = 99999
--     AND NOT EXISTS (SELECT 1 FROM product_category pc WHERE pc.product_id = p.id)
--   GROUP BY b.name ORDER BY still_uncat DESC LIMIT 10;
