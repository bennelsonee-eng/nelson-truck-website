-- =====================================================================
-- reparent_top_level_categories.sql — 2026-05-10
--
-- Ben asked: "Truck Accessories should be a parent to the categories.
-- Same with [Truck Equipment, Trailer & RV, Van Equipment]."
--
-- Today these four labels are UI-only groupings in MEGA_SECTIONS, not
-- real DB categories. Clicking "View All Truck Accessories" returned
-- 0 products because no DB category named "Truck Accessories" exists.
-- A previous commit papered over the bug with a view_all_route hack;
-- this script fixes it at the data layer instead.
--
-- After this migration:
--   Truck Accessories  parent of:
--     Air Intakes, Automotive Lighting, Bumpers and Grille Guards,
--     Cargo Management, Exterior, Interior, Running Boards and Steps,
--     Suspension, Truck Bed and Tailgate, Truck Bed Covers,
--     Wheels and Tires
--   Truck Equipment    parent of:
--     Towing and Accessories, Winches and Accessories
--   Trailer & RV       parent of:
--     Trailer Parts, RV Accessories
--   Van Equipment      parent of (moved from Cargo Management):
--     Van Accessories, Van Shelving, Van Packages,
--     Cab Partitions and Dividers
--
-- Each re-parent updates parent_id, depth + full_path. Descendants
-- get their full_path rewritten via a recursive UPDATE.
--
-- Idempotent: only inserts parents that don't exist, only re-parents
-- categories whose parent_id is currently NULL or points at the old
-- top.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- BLOCK A: Insert the 4 new parent categories
-- ---------------------------------------------------------------------
INSERT INTO category (name, slug, parent_id, full_path, depth, sort_order, is_featured, is_active, created_at, updated_at)
SELECT name, slug, NULL, name, 0, ord, FALSE, TRUE, NOW(), NOW()
FROM (VALUES
  ('Truck Accessories', 'truck-accessories', 100),
  ('Truck Equipment',   'truck-equipment',   200),
  ('Trailer & RV',      'trailer-rv',        300),
  ('Van Equipment',     'van-equipment',     400)
) AS new_parents(name, slug, ord)
WHERE NOT EXISTS (SELECT 1 FROM category c WHERE c.name = new_parents.name);

-- ---------------------------------------------------------------------
-- BLOCK B: Re-parent existing top-level cats under their new parents.
-- We do this in three steps for each cat:
--   1. UPDATE the cat's parent_id, depth, full_path
--   2. Recursively UPDATE every descendant's full_path + depth
--
-- For descendants we use a single WITH RECURSIVE UPDATE that prefixes
-- the parent's new path to each descendant's tail.
-- ---------------------------------------------------------------------

-- Helper: a function-free approach. We capture each old top's id, its
-- new parent id, and let a recursive CTE rebuild full_path / depth for
-- the entire subtree.

-- Build the re-parent plan as a CTE then apply.
WITH new_parents AS (
  SELECT id, name FROM category WHERE name IN
    ('Truck Accessories','Truck Equipment','Trailer & RV','Van Equipment')
    AND parent_id IS NULL
),
plan AS (
  -- (old_top_id, new_parent_id)
  SELECT c.id AS top_id, p.id AS new_parent_id
  FROM category c
  JOIN new_parents p ON p.name = (
    CASE c.name
      WHEN 'Air Intakes'                 THEN 'Truck Accessories'
      WHEN 'Automotive Lighting'         THEN 'Truck Accessories'
      WHEN 'Bumpers and Grille Guards'   THEN 'Truck Accessories'
      WHEN 'Cargo Management'            THEN 'Truck Accessories'
      WHEN 'Exterior'                    THEN 'Truck Accessories'
      WHEN 'Interior'                    THEN 'Truck Accessories'
      WHEN 'Running Boards and Steps'    THEN 'Truck Accessories'
      WHEN 'Suspension'                  THEN 'Truck Accessories'
      WHEN 'Truck Bed and Tailgate'      THEN 'Truck Accessories'
      WHEN 'Truck Bed Covers'            THEN 'Truck Accessories'
      WHEN 'Wheels and Tires'            THEN 'Truck Accessories'
      WHEN 'Towing and Accessories'      THEN 'Truck Equipment'
      WHEN 'Winches and Accessories'     THEN 'Truck Equipment'
      WHEN 'Trailer Parts'               THEN 'Trailer & RV'
      WHEN 'RV Accessories'              THEN 'Trailer & RV'
      ELSE NULL
    END
  )
  WHERE c.parent_id IS NULL
)
UPDATE category c
SET parent_id = plan.new_parent_id,
    depth = 1,
    full_path = (SELECT name FROM category WHERE id = plan.new_parent_id) || ' > ' || c.name,
    updated_at = NOW()
FROM plan
WHERE c.id = plan.top_id;

-- Recursively rewrite every descendant's full_path + depth.
-- For each row, full_path = parent.full_path || ' > ' || self.name
-- and depth = parent.depth + 1.
WITH RECURSIVE descendants AS (
  -- Anchors: the newly-re-parented top-level cats
  SELECT c.id, c.name, c.parent_id, c.full_path::text AS new_path, 1 AS new_depth
  FROM category c
  WHERE c.parent_id IN (SELECT id FROM category WHERE name IN
    ('Truck Accessories','Truck Equipment','Trailer & RV','Van Equipment')
    AND parent_id IS NULL)
  UNION ALL
  SELECT c.id, c.name, c.parent_id, (d.new_path || ' > ' || c.name)::text, d.new_depth + 1
  FROM category c JOIN descendants d ON c.parent_id = d.id
)
UPDATE category SET full_path = descendants.new_path, depth = descendants.new_depth, updated_at = NOW()
FROM descendants WHERE category.id = descendants.id;


-- ---------------------------------------------------------------------
-- BLOCK C: Move 4 van-specific Cargo Management leaves to Van Equipment
-- ---------------------------------------------------------------------
-- These are children of Cargo Management today (with full_path like
-- "Truck Accessories > Cargo Management > Van Accessories" after Block B).
-- We move them up to be direct children of Van Equipment instead, since
-- they're van-fleet outfitting products, not truck cargo accessories.

WITH targets AS (
  SELECT id, name FROM category WHERE name IN
    ('Van Accessories','Van Shelving','Van Packages','Cab Partitions and Dividers')
    AND parent_id = (SELECT id FROM category WHERE name = 'Cargo Management')
),
van_parent AS (
  SELECT id, name FROM category WHERE name = 'Van Equipment' AND parent_id IS NULL
)
UPDATE category c
SET parent_id = van_parent.id,
    depth = 1,
    full_path = van_parent.name || ' > ' || c.name,
    updated_at = NOW()
FROM targets, van_parent
WHERE c.id = targets.id;

-- Recursively fix any descendants of the moved categories (probably none,
-- but defensive).
WITH RECURSIVE descendants AS (
  SELECT c.id, c.name, c.parent_id, c.full_path::text AS new_path, c.depth AS new_depth
  FROM category c
  WHERE c.parent_id IN (SELECT id FROM category WHERE name IN
    ('Van Accessories','Van Shelving','Van Packages','Cab Partitions and Dividers'))
  UNION ALL
  SELECT c.id, c.name, c.parent_id, (d.new_path || ' > ' || c.name)::text, d.new_depth + 1
  FROM category c JOIN descendants d ON c.parent_id = d.id
)
UPDATE category SET full_path = descendants.new_path, depth = descendants.new_depth, updated_at = NOW()
FROM descendants WHERE category.id = descendants.id;


-- ---------------------------------------------------------------------
-- BLOCK D: Verify
-- ---------------------------------------------------------------------
-- Run after:
--   SELECT id, name, depth, full_path FROM category WHERE parent_id IS NULL ORDER BY sort_order, name;
--   -- should show 4 new parents (+ legacy dead top-levels like Gauges that the
--   -- runtime prune still hides because they have 0 products)

COMMIT;
