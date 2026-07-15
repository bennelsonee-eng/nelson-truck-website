-- =====================================================================
-- fix_part_type_99999_misclassification.sql — 2026-05-10
--
-- PCDB part_type 99999 is PACE's "miscellaneous / unclassified" catch-all
-- that brands use when no real part type fits. A previous mapping pass
-- assigned it to "Bumpers and Grille Guards > Grille Guards", which
-- dumped 5,721 mis-categorized rows into Grille Guards:
--   - Lippert Components: 2,726 (RV brake drums, bath tubs, doors,
--     grease seals, slide-outs, gearmotors — none are grille guards)
--   - WeatherTech: 2,324 (side window deflectors, floor mats)
--   - Yakima Products: 509 (end caps, replacement keys)
--   - Dometic: 162 (RV components)
--
-- Fix:
--   1. Revert pcdb_part_type.id=99999 category mapping back to NULL so
--      future ingests don't repeat this mistake.
--   2. Delete the bad product_category rows so Grille Guards stops
--      showing RV bath tubs and replacement keys.
--   3. Brand-level hiding (Lippert + Dometic — pure RV brands Titan
--      doesn't carry) is left to a separate brand-strategy decision.
-- =====================================================================

UPDATE pcdb_part_type
SET category_name = NULL, sub_category_name = NULL
WHERE id = 99999;

DELETE FROM product_category pc
WHERE pc.category_id = (SELECT id FROM category WHERE full_path = 'Bumpers and Grille Guards > Grille Guards')
  AND pc.product_id IN (
    SELECT p.id FROM product p
    JOIN pace_part pp ON pp.product_id = p.id
    WHERE pp.part_terminology_id = 99999
  );

-- =====================================================================
-- Hide Lippert + Dometic brands entirely
-- =====================================================================
-- Both brands have zero Titan legacy_wsm_id products — Titan never carried
-- them. They're pure RV-OEM brands (brake drums, slide-outs, bath tubs,
-- entrance doors, awnings, etc.) that snuck in via PACE feeds. Mark
-- inactive so they disappear from brand facets / browse and their
-- products stop appearing in the catalog.

UPDATE brand SET is_active = FALSE
WHERE name IN ('Lippert Components', 'Dometic');

-- Sanity-check after running:
--   SELECT COUNT(*) FROM product p
--   JOIN product_category pc ON pc.product_id = p.id
--   JOIN category c ON c.id = pc.category_id
--   WHERE c.full_path = 'Bumpers and Grille Guards > Grille Guards';
-- Should drop by ~6,167. Real grille-guard SKUs (part_type 1044 etc.) remain.
