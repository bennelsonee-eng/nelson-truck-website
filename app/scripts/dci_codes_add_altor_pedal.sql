-- =====================================================================
-- dci_codes additions — Altor Locks + Pedal Commander — generated 2026-07-21
-- Apply against the MySQL `nelsontruck1` database (the source of truth the
-- price/AAM sync reads via the read-only bridge). Same workflow as the
-- "12 New Lines" additions and dci_codes_fixes.sql.
--
-- WHY: both brands appear in Master Line Card 2026 and have active parts in
-- nte_parts_master, but had NO dci_codes entry, so their SKUs can't resolve a
-- brand/AAIA in the price sync (skipped_no_aaia_for_prod_code).
--
-- SOURCE OF AAIA CODES: "Master Line Card 2026.xls" (sheet "Line Card",
-- columns SUPPLIER CODE | AAIA CODE | SUPPLIER):
--     ALT  | KVJD | ALTOR LOCKS
--     PDC  | GHQP | PEDAL COMMANDER
--
-- VERIFIED LIVE against nelsontruck1 on 2026-07-21 (read-only bridge):
--   * dci_codes has NO row for ALT / PC / PDC (safe to INSERT).
--   * nte_parts_master.prod_code counts: ALT=7, PC=84, PDC=0.
--       -> Pedal Commander parts are coded PC in the parts master, NOT the
--          line card's supplier code PDC. dci_codes.prod_code must match
--          nte_parts_master.prod_code for the join, so we use prod_code='PC'.
--   * KVJD and GHQP are unused as dci_code(PK) and aaia_code (no collision).
--
-- CONVENTION (matches the New Lines you added): for brands with no real DCI
-- catalog code, dci_code = aaia_code, and cat_id = '' (empty, not a category).
-- All five columns are NOT NULL.
-- =====================================================================

-- Altor Locks  (prod_code ALT -> 7 nte_parts_master SKUs)
INSERT INTO dci_codes (dci_code, prod_code, aaia_code, cat_id, manu_title)
VALUES ('KVJD', 'ALT', 'KVJD', '', 'Altor Locks');

-- Pedal Commander  (prod_code PC -> 84 nte_parts_master SKUs)
INSERT INTO dci_codes (dci_code, prod_code, aaia_code, cat_id, manu_title)
VALUES ('GHQP', 'PC', 'GHQP', '', 'Pedal Commander');

-- Sanity check after applying:
--   SELECT dci_code, prod_code, aaia_code, cat_id, manu_title
--   FROM dci_codes WHERE prod_code IN ('ALT','PC');
-- =====================================================================
-- END
-- =====================================================================
