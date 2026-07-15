-- =====================================================================
-- fix_van_accessories_overreach.sql — 2026-05-10
--
-- The first pass at the Van Accessories migration mapped a handful of
-- PCDB part_types globally to Van Accessories. Several of those part_types
-- (12393 "Van Floor Mats", 1081 "Aerosol Touch-Up Paint", 1152 "Replacement
-- Airfoil", 17488 "PACK RAT Drawer parts" etc.) turn out to be used by
-- many brands, not just Weather Guard — so the global mapping pulled
-- 18K WeatherTech / Aries / Husky Liners / Rough Country / Roll-N-Lock
-- floor mats and accessories into Van Accessories when those should
-- stay in their existing buckets.
--
-- This script:
--   A) Removes non-Weatherguard product_category rows that point at
--      Van Accessories.
--   B) Reverts pcdb_part_type.sub_category_name on the over-broad
--      part_types (12393, 1081, 1152, 22264, 21242, 17347, 2404, 14135).
--      They go back to NULL since we don't have a clean global home.
--      The remaining WG-specific ones (18397, 18387, 19895, 15437,
--      48637) keep their Van Accessories mapping because their names
--      really are WG accessory-line specific.
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Delete non-Weatherguard rows from Van Accessories
-- ---------------------------------------------------------------------
DELETE FROM product_category pc
WHERE pc.category_id = (SELECT id FROM category WHERE full_path = 'Cargo Management > Van Accessories')
  AND pc.product_id IN (
    SELECT p.id FROM product p
    WHERE p.brand_id <> (SELECT id FROM brand WHERE aaia_code = 'HWZD')  -- not Weatherguard
  );

-- ---------------------------------------------------------------------
-- BLOCK B: Revert pcdb_part_type mappings that are too broadly used.
-- These all go back to NULL — they don't have a clean cross-brand home.
-- (Future PCDB-name backfill from Auto Care will give them proper labels.)
-- ---------------------------------------------------------------------

-- 12393 (Van Floor Mats) — used by WeatherTech (16K), Aries (1.2K),
--   Husky Liners (446) etc. These are interior floor liners for the
--   van cargo area. Re-route to the established Floor Mats category
--   instead of letting them sit in Van Accessories.
UPDATE pcdb_part_type
SET category_name='Interior', sub_category_name='Floor Mats and Cargo Liners'
WHERE id = 12393;

-- 1081 (Aerosol Touch-Up Paint) — used by VHT etc. Leave unmapped;
--   Paint & Finishing top-level is hidden (no Titan inventory).
UPDATE pcdb_part_type SET category_name=NULL, sub_category_name=NULL WHERE id = 1081;

-- 1152 (Replacement Airfoil) — sunroof wind deflectors (WeatherTech). Leave unmapped.
UPDATE pcdb_part_type SET category_name=NULL, sub_category_name=NULL WHERE id = 1152;

-- 22264 (Wiring Harness) — generic. Leave unmapped.
UPDATE pcdb_part_type SET category_name=NULL, sub_category_name=NULL WHERE id = 22264;

-- 21242 (Grab Handle) — generic interior accessory. Leave unmapped.
UPDATE pcdb_part_type SET category_name=NULL, sub_category_name=NULL WHERE id = 21242;

-- 17347 (Replacement E-Clip) — generic. Leave unmapped.
UPDATE pcdb_part_type SET category_name=NULL, sub_category_name=NULL WHERE id = 17347;

-- 2404 (Replacement Universal Clamp) — generic. Leave unmapped.
UPDATE pcdb_part_type SET category_name=NULL, sub_category_name=NULL WHERE id = 2404;

-- 14135 (Fire Extinguisher / Roller Track) — half WG drawer parts, half
--   fire extinguishers. The WG products keep their Van Accessories row
--   via Block A's exclusion (Weatherguard kept). Just leave the part_type
--   unmapped so future ingests don't pile non-WG products into Van Acc.
UPDATE pcdb_part_type SET category_name=NULL, sub_category_name=NULL WHERE id = 14135;

-- 15437 (Cabinet Tray) — UWS uses this for toolbox trays too. Switch
--   to Truck Bed Toolboxes which is where it belongs for non-WG brands.
UPDATE pcdb_part_type SET sub_category_name='Truck Bed Toolboxes and Accessories', category_name='Truck Bed and Tailgate' WHERE id = 15437;

-- 17488 (PACK RAT Drawer parts / Roll-N-Lock parts) — keep at WG side.
--   Map the part_type back to Van Accessories since WG products still
--   need a home, but Roll-N-Lock products were already removed by Block A.

-- ---------------------------------------------------------------------
-- BLOCK C: Move WeatherTech / Husky Liners / Aries floor mats from
-- Van Accessories to Interior > Floor Mats and Cargo Liners.
-- (Block A deleted their Van Acc rows; this re-files them.)
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT
  p.id,
  (SELECT id FROM category WHERE full_path = 'Interior > Floor Mats and Cargo Liners'),
  TRUE,
  NOW(), NOW()
FROM product p
JOIN pace_part pp ON pp.product_id = p.id
WHERE pp.part_terminology_id = 12393
  AND NOT EXISTS (
    SELECT 1 FROM product_category pc
    WHERE pc.product_id = p.id
      AND pc.category_id = (SELECT id FROM category WHERE full_path = 'Interior > Floor Mats and Cargo Liners')
  )
ON CONFLICT DO NOTHING;

-- =====================================================================
-- END
-- =====================================================================
