-- =====================================================================
-- set_brand_tiers.sql — 2026-05-10
--
-- Encodes the brand-tier model Ben described 2026-05-10:
--
--   ACTIVELY SOLD (is_featured=TRUE, low sort_order) — gets featured-brand
--   home-page rail + brand-promo callouts. These are Titan's bread and
--   butter.
--
--   ON SITE / NOT PUSHED (is_active=TRUE, is_featured=FALSE) — listed but
--   no marketing emphasis. Avoid featuring on home page or brand-tile rails.
--
--   NEVER CARRY — see project_titan_brand_strategy.md memory file; these
--   are kept inactive via is_active=FALSE (e.g. some trailer-side
--   competitor brands).
--
-- Idempotent.
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Featured tier (sort_order=250 puts them at top of A-Z featured list)
-- ---------------------------------------------------------------------
UPDATE brand SET is_featured = TRUE, sort_order = 250
WHERE name IN (
  'CURT Manufacturing',  -- 7,278 SKUs — Hitches, Brake Controllers, Tow Bars
  'WeatherTech',         -- 38,093 SKUs — Floor mats, deflectors, mud flaps
  'Husky Liners',        -- floor liners, mud guards
  'ARB 4x4 Accessories', -- 4x4 / overland
  'K&N Filters',         -- air intakes + filters
  'Weatherguard',        -- van shelving + truck toolboxes (HWZD)
  'Lund',
  'Aries Offroad',
  'Go Rhino',
  'Rigid Industries',
  'FIA',
  'Rugged Ridge'
  -- Note: Western, Meyer, Buyers, Federal Signal aren't in the PACE-side
  -- brand table yet (snow plows live on the dedicated snow site; the
  -- others need PACE feeds — see project_titan_brand_strategy.md).
);

-- ---------------------------------------------------------------------
-- BLOCK B: On-site-but-not-pushed (stay unfeatured, default sort)
-- ---------------------------------------------------------------------
UPDATE brand SET is_featured = FALSE, sort_order = 1000
WHERE name IN (
  'Lippert Components',  -- 5,339 SKUs — "not big on Lippert" (Ben 2026-05-10)
  'Dometic'              -- 9,725 SKUs — "sells from time to time"
);

-- Verify:
--   SELECT name, is_active, is_featured, sort_order
--   FROM brand WHERE is_featured ORDER BY sort_order, name;
