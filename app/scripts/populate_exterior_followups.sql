-- =====================================================================
-- populate_exterior_followups.sql — 2026-05-14
--
-- Follow-up to populate_exterior_subcategories.sql. Tackles the two
-- remaining "weak" exterior subcategories the owner flagged plus a
-- Mirrors expansion that catches the obvious mirror candidates the
-- first pass missed.
--
-- FINDINGS FROM REFINED PATTERN ANALYSIS:
--
--  * SPOILERS (id=106) — SKIPPING.
--    Initial "358 candidates" estimate was almost entirely false
--    positives.  The " Wing " pattern was catching Lund "Gull Wing
--    Cross Boxes" (crossover toolboxes!) and OVS "Wing Window Doors"
--    (truck cap windows!).  True patterns (Rear / Roof / Cab / Lip
--    Spoiler) return 0 SKUs each.  Only "Air Dam" returns 1.
--    Conclusion: Titan apparently doesn't stock vehicle spoilers as
--    a distinct product line.  Leaving id=106 empty until/unless the
--    owner adds one.
--
--  * TRIM AND DRESS-UP (id=109) — POPULATING.
--    Two clean patterns surface ~150 SKUs:
--        Door Sill / Sill Plate   ~ 22
--        Pillar Post              ~128
--    The 108 "Chrome Trim" hits are explicitly NOT included — they
--    are all window-deflector trim and already live in the window
--    deflector subcategory.
--
--  * MIRRORS (id=95) — EXPANDING.
--    Existing 8 SKUs from first pass + ~99 more:
--        Mirror Cover / Mirror Mount   ~55
--        Door Mirror / Folding Mirror  ~44
--
-- Same idempotent pattern as the parent script: INSERT new
-- product_category rows with ON CONFLICT DO NOTHING.  Safe to re-run.
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Trim and Dress-Up (id=109)
-- Door Sill plates + Pillar Post covers.  Window-deflector chrome
-- trim is deliberately excluded — those 108 SKUs are already
-- correctly bucketed under deflectors.
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 109, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Door Sill%'
    OR p.name ILIKE '%Sill Plate%'
    OR p.name ILIKE '%Pillar Post%'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- BLOCK B: Mirrors expansion (id=95)
-- Adds Mirror Cover/Mount and Door/Folding Mirror patterns to the
-- existing Towing/Power/Manual/Replacement Mirror hits from the
-- parent script.
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT p.id, 95, TRUE, NOW(), NOW()
FROM product p JOIN brand b ON b.id = p.brand_id
WHERE p.is_for_sale AND NOT p.is_hidden AND b.is_active
  AND (
    p.name ILIKE '%Mirror Cover%'
    OR p.name ILIKE '%Mirror Mount%'
    OR p.name ILIKE '%Door Mirror%'
    OR p.name ILIKE '%Folding Mirror%'
  )
ON CONFLICT (product_id, category_id) DO NOTHING;

-- =====================================================================
-- Verification — final SKU counts per affected category
-- =====================================================================
SELECT c.full_path, COUNT(DISTINCT pc.product_id) AS n
FROM category c
LEFT JOIN product_category pc ON pc.category_id = c.id
LEFT JOIN product p ON p.id = pc.product_id
LEFT JOIN brand b ON b.id = p.brand_id
WHERE c.id IN (95, 106, 109)
  AND (p.is_for_sale IS NULL OR (p.is_for_sale AND NOT p.is_hidden AND b.is_active))
GROUP BY c.full_path ORDER BY c.full_path;
