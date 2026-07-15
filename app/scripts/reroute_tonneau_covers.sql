-- =====================================================================
-- reroute_tonneau_covers.sql — 2026-05-14
--
-- The "Truck Accessories > Truck Bed Covers > Hard Folding Truck Bed
-- Covers" category (id=337) is currently acting as a catch-all for
-- *every* tonneau cover regardless of style.  It holds 11,512 SKUs
-- mixing hard folding, soft folding, soft rolling, soft snap,
-- retractable, and one-piece.  The five sibling categories (Soft
-- Folding, Soft Rolling, Soft Snap, Hard Retractable, Hard One-Piece)
-- are all empty.
--
-- This script splits the bucket by brand + product-name pattern.
-- Rules ordered from most-specific to least-specific so a product
-- like "Soft Tri-Fold" hits the Soft Folding rule before any generic
-- "Tri-Fold" catch.  Any SKU that doesn't match any rule is LEFT in
-- 337 (i.e. we conservatively keep ambiguous items in their original
-- placement rather than guess).
--
-- Target category IDs (verified live):
--   337 — Hard Folding Truck Bed Covers
--   338 — Hard One-Piece Truck Bed Covers
--   339 — Hard Retractable Truck Bed Covers
--   340 — Hard Rolling Truck Bed Covers
--   341 — Soft Folding Truck Bed Covers
--   342 — Soft Rolling Truck Bed Covers
--   343 — Soft Snap and Snapless Truck Bed Covers
-- =====================================================================

-- ---------------------------------------------------------------------
-- Helper: each "rule" block does
--   1. INSERT into product_category(target) ON CONFLICT DO NOTHING
--      — adds the new categorization
--   2. DELETE the old (337) row
--   — net effect: MOVE the product from 337 → target.  The two-step
--     pattern is necessary because product_category has UNIQUE
--     (product_id, category_id), so a plain UPDATE could conflict if
--     a product happens to be cross-listed elsewhere.
-- ---------------------------------------------------------------------

-- =====================================================================
-- BLOCK A: brand-wide moves where the brand only makes ONE style
-- =====================================================================

-- A.1: Retrax  →  Hard Retractable (id=339)
-- Retrax's entire catalog is retractable (RetraxONE/PRO/Powertrax)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 339, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Retrax'
ON CONFLICT (product_id, category_id) DO NOTHING;

DELETE FROM product_category WHERE category_id = 337 AND product_id IN (
  SELECT p.id FROM product p JOIN brand b ON b.id = p.brand_id
  WHERE b.name = 'Retrax'
);

-- A.2: Roll-N-Lock  →  Hard Retractable (id=339)
-- Their A/E/M-Series are all retractable
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 339, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Roll-N-Lock'
ON CONFLICT (product_id, category_id) DO NOTHING;

DELETE FROM product_category WHERE category_id = 337 AND product_id IN (
  SELECT p.id FROM product p JOIN brand b ON b.id = p.brand_id
  WHERE b.name = 'Roll-N-Lock'
);

-- =====================================================================
-- BLOCK B: name-pattern routing inside mixed-line brands
-- =====================================================================

-- B.1: Bak Industries — Vortrak / RollBAK / Retractable  →  Hard Retractable
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 339, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Bak Industries'
  AND (p.name ILIKE '%Vortrak%' OR p.name ILIKE '%RollBAK%' OR p.name ILIKE '%Retractable%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Bak Industries'
  AND (p.name ILIKE '%Vortrak%' OR p.name ILIKE '%RollBAK%' OR p.name ILIKE '%Retractable%');

-- B.2: Bak Industries — Revolver / Hard Rolling  →  Hard Rolling (id=340)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 340, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Bak Industries'
  AND (p.name ILIKE '%Revolver%' OR p.name ILIKE '%Hard Rolling%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Bak Industries'
  AND (p.name ILIKE '%Revolver%' OR p.name ILIKE '%Hard Rolling%');

-- B.3: TruXedo — TruXedo's catalog is mostly SOFT covers.
--   * "Titanium" (one-piece-ish hard rolling) → leave in 337 for now; not sure
--   * Everything else with Lo Pro / Sentry / Pro X / Deuce / Edge / Lo Pro
--     Invis-A-Rack / Truxport → Soft Rolling (most are roll-up)
--   * Deuce is a soft folding 2-pc cover specifically → Soft Folding
-- B.3a: Deuce → Soft Folding
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 341, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Truxedo'
  AND p.name ILIKE '%Deuce%'
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Truxedo' AND p.name ILIKE '%Deuce%';

-- B.3b: TruXedo Lo Pro / Sentry / Pro X / Edge / TruXport / Invis-A-Rack → Soft Rolling
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 342, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Truxedo'
  AND (p.name ILIKE '%Lo Pro%' OR p.name ILIKE '%Sentry%' OR p.name ILIKE '%Pro X%'
       OR p.name ILIKE '%The Edge%' OR p.name ILIKE '%TruXport%' OR p.name ILIKE '%Invis-A-Rack%'
       OR p.name ILIKE '%Roll Up%' OR p.name ILIKE '%Roll-Up%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Truxedo'
  AND (p.name ILIKE '%Lo Pro%' OR p.name ILIKE '%Sentry%' OR p.name ILIKE '%Pro X%'
       OR p.name ILIKE '%The Edge%' OR p.name ILIKE '%TruXport%' OR p.name ILIKE '%Invis-A-Rack%'
       OR p.name ILIKE '%Roll Up%' OR p.name ILIKE '%Roll-Up%');

-- B.4: Extang — split Trifecta + Express + Classic Tool Box + Full Tilt + BlackMax to Soft;
--   Solid Fold + Encore stay/go to Hard Folding / Hard Retractable
-- B.4a: Extang Trifecta / Express / Classic / Full Tilt / BlackMax → Soft Folding
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 341, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Extang'
  AND (p.name ILIKE '%Trifecta%' OR p.name ILIKE '%Express%' OR p.name ILIKE 'Classic%'
       OR p.name ILIKE '%Full Tilt%' OR p.name ILIKE '%BlackMax%' OR p.name ILIKE '%eMax%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Extang'
  AND (p.name ILIKE '%Trifecta%' OR p.name ILIKE '%Express%' OR p.name ILIKE 'Classic%'
       OR p.name ILIKE '%Full Tilt%' OR p.name ILIKE '%BlackMax%' OR p.name ILIKE '%eMax%');

-- B.4b: Extang Encore → Hard Retractable (id=339)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 339, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Extang'
  AND p.name ILIKE '%Encore%'
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Extang' AND p.name ILIKE '%Encore%';

-- (Extang Solid Fold + remaining stay in 337 = Hard Folding, correct)

-- B.5: Undercover — FLEX / Armor Flex / Ultra Flex are HARD FOLDING
--   LUX / Elite LX / LX are HARD ONE-PIECE
--   SwingCase is HARD ONE-PIECE specialty
-- B.5a: Undercover LUX / Elite LX / LX / Classic → Hard One-Piece (id=338)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 338, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Undercover Tonneau'
  AND (p.name ILIKE 'LUX%' OR p.name ILIKE 'Elite LX%' OR p.name ILIKE 'LX %'
       OR p.name ILIKE 'LX-%' OR p.name ILIKE '%Classic%'
       OR p.name ILIKE '%Swing Case%' OR p.name ILIKE '%SwingCase%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Undercover Tonneau'
  AND (p.name ILIKE 'LUX%' OR p.name ILIKE 'Elite LX%' OR p.name ILIKE 'LX %'
       OR p.name ILIKE 'LX-%' OR p.name ILIKE '%Classic%'
       OR p.name ILIKE '%Swing Case%' OR p.name ILIKE '%SwingCase%');
-- (Undercover FLEX + Armor Flex + Ultra Flex stay in 337 = Hard Folding)

-- B.6: Lund Genesis Roll Up / Elite Roll Up → Soft Rolling (id=342)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 342, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Lund'
  AND (p.name ILIKE '%Roll Up%' OR p.name ILIKE '%Roll-Up%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Lund'
  AND (p.name ILIKE '%Roll Up%' OR p.name ILIKE '%Roll-Up%');

-- B.7: Lund Genesis Tri-Fold (without "Elite") → Soft Folding (id=341)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 341, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Lund'
  AND p.name ILIKE 'Genesis Tri-Fold%'
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Lund' AND p.name ILIKE 'Genesis Tri-Fold%';

-- B.8: Lund Genesis Snap / Seal & Peel → Soft Snap and Snapless (id=343)
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 343, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Lund'
  AND (p.name ILIKE '%Snap%' OR p.name ILIKE '%Seal & Peel%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Lund'
  AND (p.name ILIKE '%Snap%' OR p.name ILIKE '%Seal & Peel%');

-- (Lund "Genesis Elite Tri-Fold" + "Hard Fold" stay in 337 — they ARE hard
-- folding.  "Genesis Tri-Fold" without Elite is soft.)

-- B.9: Rugged Liner — Premium Hard Folding stays in 337 (already correct).
--   Premium Rollup → Soft Rolling.  Vinyl Snap → Soft Snap.
--   Premium Vinyl Folding → Soft Folding.
-- B.9a: Rugged Liner Premium Rollup → Soft Rolling
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 342, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Rugged Liner'
  AND (p.name ILIKE '%Premium Rollup%' OR p.name ILIKE '%Premium Roll Up%' OR p.name ILIKE '%Premium Roll-Up%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Rugged Liner'
  AND (p.name ILIKE '%Premium Rollup%' OR p.name ILIKE '%Premium Roll Up%' OR p.name ILIKE '%Premium Roll-Up%');

-- B.9b: Rugged Liner Snap / Vinyl Snap → Soft Snap
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 343, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Rugged Liner'
  AND (p.name ILIKE '%Snap%' OR (p.name ILIKE '%Vinyl%' AND p.name NOT ILIKE '%Folding%'))
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Rugged Liner'
  AND (p.name ILIKE '%Snap%' OR (p.name ILIKE '%Vinyl%' AND p.name NOT ILIKE '%Folding%'));

-- B.9c: Rugged Liner Premium Vinyl Folding → Soft Folding
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 341, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Rugged Liner'
  AND p.name ILIKE '%Vinyl Folding%'
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Rugged Liner' AND p.name ILIKE '%Vinyl Folding%';

-- B.10: Bestop ZipRail Soft → Soft Rolling.  EZ-Roll → Soft Rolling.
--   EZ-Fold Hard → stay (Hard Folding correct).  ZipRail (without "Soft") → Soft Rolling.
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 342, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Bestop'
  AND (p.name ILIKE '%ZipRail%' OR p.name ILIKE '%EZ-Roll%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Bestop'
  AND (p.name ILIKE '%ZipRail%' OR p.name ILIKE '%EZ-Roll%');

-- B.11: WeatherTech Roll Up / AlloyCover → Soft Rolling
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 342, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'WeatherTech'
  AND (p.name ILIKE '%Roll Up%' OR p.name ILIKE '%Roll-Up%' OR p.name ILIKE '%AlloyCover%' OR p.name ILIKE '%Alloy Cover%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'WeatherTech'
  AND (p.name ILIKE '%Roll Up%' OR p.name ILIKE '%Roll-Up%' OR p.name ILIKE '%AlloyCover%' OR p.name ILIKE '%Alloy Cover%');

-- B.12: Westin — Soft Tri-Fold → Soft Folding.  Soft Roll-Up → Soft Rolling.
--   Electric Retractable → Hard Retractable.  Hard Roll-Up → Hard Rolling.  Hard Tri-Fold → stay.
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 341, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Westin'
  AND p.name ILIKE '%Soft Tri-Fold%'
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Westin' AND p.name ILIKE '%Soft Tri-Fold%';

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 342, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Westin'
  AND p.name ILIKE '%Soft Roll-Up%'
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Westin' AND p.name ILIKE '%Soft Roll-Up%';

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 339, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Westin'
  AND (p.name ILIKE '%Electric Retractable%' OR p.name ILIKE '%Retractable%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Westin'
  AND (p.name ILIKE '%Electric Retractable%' OR p.name ILIKE '%Retractable%');

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 340, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Westin'
  AND p.name ILIKE '%Hard Roll-Up%'
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Westin' AND p.name ILIKE '%Hard Roll-Up%';

-- B.13: Rough Country — Soft Tri-Fold → Soft Folding.  Soft Roll Up → Soft Rolling.
--   Hard Roll Up → Hard Rolling.  Hard Tri-Fold + Hard Low Profile → stay.
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 341, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Rough Country'
  AND p.name ILIKE '%Soft Tri-Fold%'
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Rough Country' AND p.name ILIKE '%Soft Tri-Fold%';

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 342, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Rough Country'
  AND (p.name ILIKE '%Soft Roll Up%' OR p.name ILIKE '%Soft Roll-Up%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Rough Country'
  AND (p.name ILIKE '%Soft Roll Up%' OR p.name ILIKE '%Soft Roll-Up%');

INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT pc.product_id, 340, TRUE, NOW(), NOW()
FROM product_category pc JOIN product p ON p.id = pc.product_id
JOIN brand b ON b.id = p.brand_id
WHERE pc.category_id = 337 AND b.name = 'Rough Country'
  AND (p.name ILIKE '%Hard Roll Up%' OR p.name ILIKE '%Hard Roll-Up%')
ON CONFLICT (product_id, category_id) DO NOTHING;
DELETE FROM product_category pc USING product p, brand b
WHERE pc.category_id = 337 AND pc.product_id = p.id AND b.id = p.brand_id
  AND b.name = 'Rough Country'
  AND (p.name ILIKE '%Hard Roll Up%' OR p.name ILIKE '%Hard Roll-Up%');

-- =====================================================================
-- Verification
-- =====================================================================
SELECT c.full_path, COUNT(DISTINCT pc.product_id) AS n
FROM category c
LEFT JOIN product_category pc ON pc.category_id = c.id
LEFT JOIN product p ON p.id = pc.product_id
LEFT JOIN brand b ON b.id = p.brand_id
WHERE c.full_path LIKE 'Truck Accessories > Truck Bed Covers%'
  AND (p.is_for_sale IS NULL OR (p.is_for_sale = TRUE AND p.is_hidden = FALSE AND b.is_active = TRUE))
GROUP BY c.full_path
ORDER BY c.full_path;
