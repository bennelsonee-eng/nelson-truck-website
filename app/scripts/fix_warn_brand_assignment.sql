-- =====================================================================
-- fix_warn_brand_assignment.sql — 2026-05-10
--
-- 4,805 BCSQ-prefixed products were ingested with brand_id=6 (Aries
-- Offroad) instead of brand_id=16 (Warn). The Warn PIES feed
-- AAM_BCSQ_PIES_20260505015201.zip should have routed them to Warn.
-- Root cause: an earlier Aries-side ingest pulled in Warn-mfg items
-- as cross-references with the SKU "BCSQ-{partnum}" but attributed
-- them to Aries' brand_id. The Warn ingest then matched the SKUs
-- via the upsert path and only updated names, not brand_id.
--
-- Fix:
--   1. Move every BCSQ-* product to brand_id=16.
--   2. Categorize them into Winches and Accessories by name pattern
--      (the same logic used for Bulldog Winch).
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Re-assign brand
-- ---------------------------------------------------------------------
UPDATE product
SET brand_id = 16
WHERE sku LIKE 'BCSQ-%' AND brand_id <> 16;

-- ---------------------------------------------------------------------
-- BLOCK B: Categorize by name pattern
-- ---------------------------------------------------------------------
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT
  p.id, cat_target.id, TRUE, NOW(), NOW()
FROM product p
CROSS JOIN LATERAL (
  SELECT id FROM category WHERE full_path = (
    CASE
      WHEN p.name ILIKE '%winch%'                          THEN 'Winches and Accessories'
      WHEN p.name ILIKE '%fairlead%'
        OR p.name ILIKE '%wire rope%'
        OR p.name ILIKE '%synthetic rope%'
        OR p.name ILIKE '%tree saver%'
        OR p.name ILIKE '%snatch block%'
        OR p.name ILIKE '%shackle%'
        OR p.name ILIKE '%hook%'
        OR p.name ILIKE '%mount plate%'
        OR p.name ILIKE '%winch mount%'
        OR p.name ILIKE '%mounting channel%'
        OR p.name ILIKE '%contactor%'
        OR p.name ILIKE '%solenoid%'
        OR p.name ILIKE '%wiring kit%'
        OR p.name ILIKE '%power lead%'
        OR p.name ILIKE '%switch panel%'
        OR p.name ILIKE '%recovery%'
        OR p.name ILIKE '%pull strap%'
        OR p.name ILIKE '%snow plow strap%'
        OR p.name ILIKE '%bump stop%'                      THEN 'Winches and Accessories'
      ELSE NULL
    END
  )
) cat_target
WHERE p.brand_id = 16
  AND NOT EXISTS (
    SELECT 1 FROM product_category pc
    WHERE pc.product_id = p.id AND pc.category_id = cat_target.id
  );
