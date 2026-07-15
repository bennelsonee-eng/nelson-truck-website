-- =====================================================================
-- categorize_bulldog_winch.sql — 2026-05-10
--
-- Bulldog Winch had 641 uncategorized products. Surveying the names
-- shows three product families:
--   1. Actual winches (12000lb / 9500lb / 8000lb Winch w/HP Motor ...)
--   2. Winch accessories (Wire Rope, Tree Saver Strap, Snatch Block,
--      Mounting Channel, Power Leads, Limit Switch, Contactor, Relay,
--      Switch Panel, Rope Shackle, Tube Thimble, etc.)
--   3. Non-winch products (Grille Guards, Headlight Guards, Tumblers,
--      Coolers, etc. — Bulldog Winch's branded merch + their bumper
--      line)
--
-- Most winch and winch-accessory SKUs route to "Winches and Accessories".
-- Grille Guards / Headlight Guards already have a category mapping path
-- via the regular Grille Guards leaf. Cooler/Tumbler stays uncategorized
-- (they're branded merch, not a vehicle product line).
--
-- Idempotent.
-- =====================================================================

-- Route Bulldog Winch products by name pattern (priority order via CASE).
INSERT INTO product_category (product_id, category_id, is_primary, created_at, updated_at)
SELECT
  p.id,
  cat_target.id,
  TRUE,
  NOW(),
  NOW()
FROM product p
JOIN brand b ON b.id = p.brand_id
CROSS JOIN LATERAL (
  SELECT id FROM category WHERE full_path = (
    CASE
      WHEN p.name ILIKE '%winch%'                          THEN 'Winches and Accessories'
      -- Winch accessories
      WHEN p.name ILIKE '%fairlead%'
        OR p.name ILIKE '%wire rope%'
        OR p.name ILIKE '%synthetic rope%'
        OR p.name ILIKE '%tree saver%'
        OR p.name ILIKE '%snatch block%'
        OR p.name ILIKE '%shackle%'
        OR p.name ILIKE '%hook%'
        OR p.name ILIKE '%winch mount%'
        OR p.name ILIKE '%mounting channel%'
        OR p.name ILIKE '%winch carrier%'
        OR p.name ILIKE '%carrier, winch%'
        OR p.name ILIKE '%contactor%'
        OR p.name ILIKE '%solenoid%'
        OR p.name ILIKE '%wiring kit%'
        OR p.name ILIKE '%power lead%'
        OR p.name ILIKE '%limit switch%'
        OR p.name ILIKE '%relay%'
        OR p.name ILIKE '%switch panel%'
        OR p.name ILIKE '%switch system%'
        OR p.name ILIKE '%recovery%'
        OR p.name ILIKE '%pull strap%'
        OR p.name ILIKE '%tube thimble%'                   THEN 'Winches and Accessories'
      -- Bumper / grille guard line (handled by the regular Grille Guards
      -- mapping for non-Bulldog brands but Bulldog needs an explicit route)
      WHEN p.name ILIKE '%grille guard%'                   THEN 'Bumpers and Grille Guards > Grille Guards'
      WHEN p.name ILIKE '%headlight guard%'                THEN 'Automotive Lighting > Headlight Covers'
      WHEN p.name ILIKE '%bumper%'                         THEN 'Bumpers and Grille Guards > Front Bumpers'
      -- Branded merch (tumblers, coolers) deliberately left uncategorized.
      ELSE NULL
    END
  )
) AS cat_target
WHERE b.name = 'Bulldog Winch'
  AND NOT EXISTS (
    SELECT 1 FROM product_category pc
    WHERE pc.product_id = p.id AND pc.category_id = cat_target.id
  );
