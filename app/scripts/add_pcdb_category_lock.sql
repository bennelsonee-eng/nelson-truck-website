-- =====================================================================
-- add_pcdb_category_lock.sql — 2026-06-22
--
-- Hardening for the manual taxonomy overrides (issues #13/#14). The PACE
-- category scrapers (scrape_pace_categories_python.py /
-- map_part_types_to_categories.py) UNCONDITIONALLY overwrite
-- pcdb_part_type.category_name / sub_category_name with PACE's own
-- taxonomy. Re-running either would silently revert every manual remap
-- (skid plates, lift kits, shocks/struts). This adds a lock the scrapers
-- honor (WHERE NOT category_locked) so our overrides survive re-scrapes.
--
-- Apply to prod BEFORE deploying the model change (the ORM selects the
-- new columns). Idempotent (IF NOT EXISTS).
-- =====================================================================

ALTER TABLE pcdb_part_type ADD COLUMN IF NOT EXISTS category_locked boolean NOT NULL DEFAULT FALSE;
ALTER TABLE pcdb_part_type ADD COLUMN IF NOT EXISTS category_lock_reason text;

-- Lock every part type we've hand-mapped, so a PACE re-scrape skips them.
UPDATE pcdb_part_type SET category_locked = TRUE,
  category_lock_reason = 'issue #13: skid plates -> Exterior > Body Armor and Protection'
WHERE id = 1421;

UPDATE pcdb_part_type SET category_locked = TRUE,
  category_lock_reason = 'issue #14: lift kits -> Suspension > Lift Kits'
WHERE id = 18833;

UPDATE pcdb_part_type SET category_locked = TRUE,
  category_lock_reason = 'issue #14: shocks/replacement -> Suspension > Shocks and Struts (L4 split by relinker)'
WHERE id = 7556;

UPDATE pcdb_part_type SET category_locked = TRUE,
  category_lock_reason = 'issue #14: coilovers merged -> Suspension > Shocks and Struts (L4 Coilover Kits by relinker)'
WHERE id = 15174;

UPDATE pcdb_part_type SET category_locked = TRUE,
  category_lock_reason = 'issue #14: shocks/struts subtree (L4 split by relinker)'
WHERE id = 19837;

-- Verify:
--   SELECT id, category_name, sub_category_name, category_locked, category_lock_reason
--   FROM pcdb_part_type WHERE category_locked ORDER BY id;
