-- =====================================================================
-- dci_codes corrections — generated 2026-05-10
-- Apply against the MySQL `nelsontruck1` database.
-- Each block is independent — review and apply individually.
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK 1: KNK / Weatherguard AAIA correction — CONFIRMED 2026-05-10
-- dci_codes has KNK -> DKJD which is incorrect.
-- The Weatherguard PIES feed we're getting from PACE uses BrandAAIAID = HWZD,
-- and Ben confirmed HWZD is the right AAIA code for Weatherguard.
-- Apply this update:

UPDATE dci_codes SET aaia_code='HWZD' WHERE dci_code='KNK' AND aaia_code='DKJD';

-- ---------------------------------------------------------------------
-- BLOCK 1B: YAK / Yakima AAIA correction — CONFIRMED 2026-05-10
-- dci_codes has YAK -> YAK (Titan-internal placeholder).
-- Real Yakima AAIA per the PACE PIES feed is FRFS (BrandLabel: "Yakima Products").
-- Verified: TTE YAK SKUs (8000101, 8000124, 8000134, 8000135...) match PACE
-- FRFS part_numbers exactly. Same Yakima.

UPDATE dci_codes SET aaia_code='FRFS' WHERE dci_code='YAK' AND aaia_code='YAK';

-- ---------------------------------------------------------------------


-- ---------------------------------------------------------------------
-- BLOCK 2: Add prod_code -> AAIA mappings for brands NOT yet in dci_codes
-- These prod_codes appear in tte_parts_master with active SKUs but have
-- no entry in dci_codes. The AAIA code suggestions below are best-effort
-- guesses that need to be VERIFIED with PACE rep before insertion.
--
-- DO NOT INSERT BLINDLY. Treat as a research checklist.
-- ---------------------------------------------------------------------

-- Bilstein  (likely AAIA exists; not in our snapshot)
-- INSERT INTO dci_codes (dci_code, prod_code, aaia_code, manu_title)
-- VALUES ('BIL', 'BIL', '????', 'Bilstein');

-- 3D MaxPider  (likely AAIA exists)
-- INSERT INTO dci_codes (dci_code, prod_code, aaia_code, manu_title)
-- VALUES ('3DU', '3DU', '????', '3D MaxPider');

-- Nitro Gear & Axle  (likely AAIA exists)
-- INSERT INTO dci_codes (dci_code, prod_code, aaia_code, manu_title)
-- VALUES ('NITRO', 'NITRO', '????', 'Nitro Gear & Axle');

-- Tuff Country EZ-Ride  (likely AAIA exists — suspension)
-- INSERT INTO dci_codes (dci_code, prod_code, aaia_code, manu_title)
-- VALUES ('TUFF', 'TUFF', '????', 'Tuff Country EZ-Ride');

-- TFP Inc.  (truck accessories)
-- INSERT INTO dci_codes (dci_code, prod_code, aaia_code, manu_title)
-- VALUES ('TFP', 'TFP', '????', 'TFP');

-- ---------------------------------------------------------------------
-- BLOCK 3: Duplicate prod_code entries (ACI, WES) — CONFIRMED INTENTIONAL 2026-05-10
-- Ben confirmed both rows are correct. The duplicates exist because Titan
-- consolidates two related brands under one prod_code:
--
-- ACI:
--   AGR -> ACI -> BGPC = Access Cover
--   LMX -> ACI -> HCMH = LOMAX  (preferred public-facing brand)
--
-- WES:
--   WET -> WES -> BCTC = Westin     (primary — what's actually stocked)
--   BGFJ -> WES -> BGFJ = Superwinch (limited stock; not actively sold)
--
-- Real-world disambiguation per tte_parts_master:
--   prod_code='ACI' (3,019 active SKUs, all supplier=117): all "ACCESS
--     REPLACEMENT PARTS" — sourced through Access Cover, marketed as LOMAX.
--   prod_code='WES' (7,740 active SKUs, all supplier=603): all bumper /
--     truck cap / step pad — pure Westin (no Superwinch products in here).
--
-- Website display rule:
--   When tte.prod_code='WES', display as Westin (BCTC).
--   When tte.prod_code='ACI', display as LOMAX (HCMH) — but offer access
--     to the full Access Cover (BGPC) catalog through that brand.
--
-- No SQL changes needed — leave both dci_codes rows in place. Disambiguation
-- happens in the app via supplier code or hand-curated default-brand-per-prod_code.
-- ---------------------------------------------------------------------


-- ---------------------------------------------------------------------
-- BLOCK 4: Replace placeholder AAIA codes with real ones
-- These rows have aaia_code = prod_code (a Titan-internal placeholder),
-- meaning the brand isn't actually published in the AAM/AAIA registry
-- under that code. If PACE confirms a real AAIA code exists, update.
-- ---------------------------------------------------------------------

-- Examples of placeholder rows worth checking with PACE rep:
--   BUY -> BUY  (Buyer Products — placeholder; AAIA may or may not exist)
--   RCS -> RCS  (Rough Country)
--   FED -> FED  (Federal Signal — Ben confirmed not on PACE)
--   WEST -> WEST  (Western Snow Plows — handled separately on snow plow site)
--   MYP -> MYP  (Meyer Products — handled separately on snow plow site)
--   AUTC -> AUTC  (Auto Crane)
--   YAK -> YAK  (Yakima — but our PACE feed has Yakima under FRFS, so
--                YAK should likely become FRFS in dci_codes)
--   MRW -> MRW  (METHOD wheels)
--   PROTEC -> PROTEC  (Protech Industries)
--   ECCO -> ECCO  (Ecco — Ben confirmed not on PACE)
--   SNOW -> SNOW  (Buyers Snow Dogg — handled separately on snow plow site)
--   KAR -> KAR  (Kargo Master)

-- If YAK should map to Yakima Products' real PACE-delivered AAIA (FRFS):
-- UPDATE dci_codes SET aaia_code='FRFS' WHERE dci_code='YAK' AND aaia_code='YAK';

-- =====================================================================
-- END
-- =====================================================================
