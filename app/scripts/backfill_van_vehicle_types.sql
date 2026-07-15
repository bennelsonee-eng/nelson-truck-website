-- =====================================================================
-- backfill_van_vehicle_types.sql — 2026-05-10
--
-- The Auto Care VCDB ships a VehicleType lookup (Pickup / SUV / Van /
-- Sedan etc.) but our VCDB loader is a stub so vcdb_model.vehicle_type
-- is empty across all 1,735 models. That makes it impossible to ask
-- "give me Van Equipment products that actually fit a van."
--
-- This script seeds the column for the model names we know are vans,
-- so the catalog router can apply a vehicle_type='Van' filter when
-- a user browses Van Equipment or selects a van as their YMM.
--
-- Coverage is intentionally focused on COMMERCIAL VANS (the Weather
-- Guard target market — Titan doesn't currently carry Adrian Steel
-- or Ranger Design) plus minivans so existing PIES fitments line up.
-- Once we get the real VCDB MDB import working, this hand-list can
-- be retired.
--
-- Idempotent: only updates rows whose vehicle_type is NULL.
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Commercial vans (Weather Guard target list)
-- ---------------------------------------------------------------------
UPDATE vcdb_model SET vehicle_type = 'Van'
WHERE vehicle_type IS NULL
  AND name ~* '(Sprinter(\s|$)|eSprinter|ProMaster(\s|City|EV)?|Transit-\d|Transit Connect|Transit Custom|^E-Transit$|^Metris$|^Express \d|^Savana \d|^E-1[56]0|^E-250|^E-350|Econoline|Club Wagon|^NV\d{3,4}|NV200|MetroVan|MV-1|Vandura|Crafter|Movano|^Master$)';

-- Defensive: clean up known false positives if the regex catches them
UPDATE vcdb_model SET vehicle_type = NULL WHERE name = 'Roadmaster';

-- ---------------------------------------------------------------------
-- BLOCK B: Consumer / passenger minivans (still get van-fitment products)
-- ---------------------------------------------------------------------
UPDATE vcdb_model SET vehicle_type = 'Van'
WHERE vehicle_type IS NULL
  AND name IN (
    'Caravan',                       -- Dodge
    'Grand Caravan',                 -- Dodge
    'Town & Country',                -- Chrysler
    'Pacifica',                      -- Chrysler (replacement for T&C)
    'Voyager',                       -- Chrysler
    'Sienna',                        -- Toyota
    'Odyssey',                       -- Honda
    'Quest',                         -- Nissan
    'Sedona',                        -- Kia
    'Routan'                         -- VW
  );

-- =====================================================================
-- Verify
-- =====================================================================

-- Run after:
--   SELECT vehicle_type, COUNT(*) AS n FROM vcdb_model
--     WHERE vehicle_type IS NOT NULL GROUP BY vehicle_type;
--
-- Expected: vehicle_type=Van with ~45-55 rows.
