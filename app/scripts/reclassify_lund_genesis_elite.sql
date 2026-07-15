-- =====================================================================
-- reclassify_lund_genesis_elite.sql — 2026-05-14
--
-- Follow-up to reroute_tonneau_covers.sql.  Owner correction:
-- Lund "Genesis Elite Tri-Fold" is a SOFT folding tonneau (not hard,
-- as the earlier rule conservatively assumed).  Moves all 101 SKUs
-- with name LIKE 'Genesis Elite Tri-Fold%' from Hard Folding (337)
-- to Soft Folding (341).
--
-- Same two-step (INSERT new row + DELETE old) pattern as the parent
-- script, to avoid UNIQUE (product_id, category_id) conflicts.
-- =====================================================================

-- Step 1: ensure target row exists
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 341, TRUE, NOW(), NOW()
FROM product_category pc
JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337
  AND b.name = 'Lund'
  AND p.name ILIKE 'Genesis Elite Tri-Fold%'
ON CONFLICT (product_id, category_id) DO NOTHING;

-- Step 2: remove the wrong-bucket row
DELETE FROM product_category pc
USING product p, brand b
WHERE pc.category_id = 337
  AND pc.product_id = p.id
  AND b.id = p.brand_id
  AND b.name = 'Lund'
  AND p.name ILIKE 'Genesis Elite Tri-Fold%';

-- Verification
SELECT 'Hard Folding (337)' AS cat, COUNT(*) AS n
FROM product_category pc JOIN product p ON p.id = pc.product_id JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Lund' AND p.name ILIKE 'Genesis Elite Tri-Fold%'
UNION ALL
SELECT 'Soft Folding (341)', COUNT(*)
FROM product_category pc JOIN product p ON p.id = pc.product_id JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 341 AND b.name = 'Lund' AND p.name ILIKE 'Genesis Elite Tri-Fold%';
