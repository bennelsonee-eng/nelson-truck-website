-- ===========================================================================
-- Catalog browse perf verification — "Van Equipment > Van Accessories" + Van
-- ===========================================================================
-- Confirms the win from the has_no_fitment change (commit perf(catalog)).
--
-- The browse endpoint runs this filter ~4x per request (total count, in-stock
-- count, page slice, brand facets). The count below is representative of that
-- filter's cost, so its Execution Time tracks the page's slowness directly.
--
-- HOW TO RUN (on titan-prod, against the live titan DB):
--   psql "$DATABASE_URL" -f app/scripts/perf_explain_van_browse.sql
-- or paste each block into psql interactively.
--
-- WHAT TO LOOK FOR:
--   * "Execution Time:" at the bottom of each plan (ms).
--   * In the OLD plan: a Seq Scan on `product` and/or large hash/anti-joins
--     feeding the OR — that's the catalog-wide scan we removed.
--   * In the NEW plan: the OR collapses to an Index Scan / Bitmap on
--     ix_product_has_no_fitment. Execution Time should drop sharply.
--
-- ORDER OF OPERATIONS:
--   1. BEFORE deploying the migration, run BLOCK A (the OLD shape still works
--      on the current schema) to capture the baseline.
--   2. `alembic upgrade head` to add + backfill has_no_fitment.
--   3. Run BLOCK B (the NEW shape) and compare Execution Time.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- BLOCK A — OLD shape (three-way OR with two catalog-wide scans). Baseline.
-- Runs on the pre-migration schema (does not reference has_no_fitment).
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE p.is_hidden = false
  AND p.is_for_sale = true
  AND b.is_active = true
  AND (
    -- (1) has a fitment to a Van-class model
    p.id IN (
      SELECT DISTINCT pp.product_id
      FROM pace_part pp
      JOIN pace_fitment f ON f.pace_part_id = pp.id
      JOIN vcdb_base_vehicle bv ON bv.id = f.base_vehicle_id
      JOIN vcdb_model m ON m.id = bv.model_id
      WHERE m.vehicle_type = 'Van' AND pp.product_id IS NOT NULL
    )
    -- (2) has no pace_part at all  [CATALOG-WIDE SCAN]
    OR p.id IN (
      SELECT DISTINCT pr.id
      FROM product pr
      LEFT JOIN pace_part pp2 ON pp2.product_id = pr.id
      WHERE pp2.id IS NULL
    )
    -- (3) has pace_part(s) but none carry a fitment  [CATALOG-WIDE SCAN]
    OR p.id IN (
      SELECT pp3.product_id
      FROM pace_part pp3
      LEFT JOIN pace_fitment f3 ON f3.pace_part_id = pp3.id
      WHERE pp3.product_id IS NOT NULL
      GROUP BY pp3.product_id
      HAVING count(f3.id) = 0
    )
  )
  AND p.id IN (
    SELECT pc.product_id
    FROM product_category pc
    WHERE pc.category_id IN (
      SELECT c.id FROM category c
      WHERE c.full_path = 'Van Equipment > Van Accessories'
         OR c.full_path LIKE 'Van Equipment > Van Accessories > %'
    )
  );


-- ---------------------------------------------------------------------------
-- BLOCK B — NEW shape (cases 2+3 collapsed into indexed has_no_fitment).
-- Run only AFTER `alembic upgrade head`.
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*)
FROM product p
JOIN brand b ON b.id = p.brand_id
WHERE p.is_hidden = false
  AND p.is_for_sale = true
  AND b.is_active = true
  AND (
    p.id IN (
      SELECT DISTINCT pp.product_id
      FROM pace_part pp
      JOIN pace_fitment f ON f.pace_part_id = pp.id
      JOIN vcdb_base_vehicle bv ON bv.id = f.base_vehicle_id
      JOIN vcdb_model m ON m.id = bv.model_id
      WHERE m.vehicle_type = 'Van' AND pp.product_id IS NOT NULL
    )
    OR p.has_no_fitment = true
  )
  AND p.id IN (
    SELECT pc.product_id
    FROM product_category pc
    WHERE pc.category_id IN (
      SELECT c.id FROM category c
      WHERE c.full_path = 'Van Equipment > Van Accessories'
         OR c.full_path LIKE 'Van Equipment > Van Accessories > %'
    )
  );


-- ---------------------------------------------------------------------------
-- SANITY — the two shapes MUST return the same count (semantics preserved).
-- Run both counts and confirm they match before trusting the perf delta.
-- (Use the SELECT count(*) bodies above without EXPLAIN to compare numbers.)
-- ---------------------------------------------------------------------------
