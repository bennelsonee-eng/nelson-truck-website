-- =====================================================================
-- deactivate_northwest_seat_covers.sql — 2026-05-11
--
-- Northwest Seat Covers shipped to titan_web via PIES ingestion but
-- (a) Titan doesn't carry the brand (0 rows in product_inventory),
-- (b) every one of its 96,931 SKUs has the same generic product name
--     "Seat Cover" (no model / fabric / vehicle differentiator),
-- (c) category_top is NULL on every row — they aren't classified at all,
-- (d) the brand isn't on Titan's stated stock list.
--
-- The combined effect is that the brand-strip on the home-page (sorted
-- by product_count desc among non-featured) and the /brands page surface
-- it as the #1 non-featured brand — but clicking it lands the user in
-- 96K identical "Seat Cover" rows that they can't navigate or refine.
--
-- FIA still ships ~7,900 seat covers from active stock, so removing
-- Northwest Seat Covers doesn't break the seat-cover sub-category.
--
-- This script sets Brand.is_active = FALSE.  The browse filter already
-- excludes inactive brands (catalog.py:160 base_q includes
-- `Brand.is_active == True`), so this is a soft, reversible deactivation
-- that hides the brand from every customer-facing surface without
-- deleting any rows.
--
-- To reinstate later (once names are differentiated by fabric / color
-- / vehicle), run:
--   UPDATE brand SET is_active = TRUE WHERE name = 'Northwest Seat Covers';
-- =====================================================================

UPDATE brand SET is_active = FALSE WHERE name = 'Northwest Seat Covers';

-- Verify
SELECT name, is_active,
       (SELECT COUNT(*) FROM product p WHERE p.brand_id = brand.id) AS sku_count
FROM brand
WHERE name = 'Northwest Seat Covers';
