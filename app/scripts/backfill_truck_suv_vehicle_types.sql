-- =====================================================================
-- backfill_truck_suv_vehicle_types.sql — 2026-05-10
--
-- Extends backfill_van_vehicle_types.sql to cover the other two vehicle
-- classes Titan customers shop. Once this runs, the YMM picker can mirror
-- the Van flow for Trucks + SUVs:
--   - Truck tab: Make dropdown drops from 75 to ~15 truck-OEMs, Models
--     drops to ~50 truck models. Popular-trucks rail shows F-150,
--     Silverado, Sierra, Ram, Tacoma, Tundra etc.
--   - SUV tab: similar shrink, popular-SUVs rail surfaces Bronco,
--     Wrangler, 4Runner, Tahoe, Suburban, Grand Cherokee etc.
--
-- Same approach as the Van pass: regex against model name + a hardcoded
-- list for the long-tail. Idempotent — only updates rows whose
-- vehicle_type is currently NULL.
-- =====================================================================

-- ---------------------------------------------------------------------
-- BLOCK A: Trucks (pickup truck OEMs: Ford F-Series, GM, Ram, Toyota,
--   Nissan, Jeep Gladiator, Honda Ridgeline, Hyundai Santa Cruz, plus
--   heavy-duty Class 4-6 truck chassis Isuzu NPR/NRR, F-650/750, etc.)
-- ---------------------------------------------------------------------
UPDATE vcdb_model SET vehicle_type = 'Truck'
WHERE vehicle_type IS NULL
  AND (
    -- Ford full-size + Super Duty + electric
    name ~* '^F-?[0-9]+( |$)'           -- F-150, F-250, F-350, F-450, F-550, F-650, F-750, F-150 Lightning
    OR name ~* '^F-?[0-9]+ (Super Duty|Lightning|Heritage|HD)$'
    OR name = 'Ranger'
    OR name = 'Maverick'
    OR name = 'Courier'
    OR name = 'Explorer Sport Trac'
    OR name = 'Mark LT'         -- Lincoln rebadged F-150

    -- GM full-size + heavy duty
    OR name ~* '^Silverado [0-9]+'
    OR name ~* '^Silverado [0-9]+ Classic$'
    OR name ~* '^Silverado [0-9]+ HD( Classic)?$'
    OR name = 'Avalanche'
    OR name = 'Colorado'
    OR name = 'S10 Pickup'
    OR name = 'C/K Pickup'
    OR name ~* '^C/?K [0-9]+'
    OR name ~* '^Kodiak C[0-9]+'
    OR name ~* '^TopKick C[0-9]+'

    -- GMC
    OR name ~* '^Sierra [0-9]+'
    OR name ~* '^Sierra [0-9]+ Classic$'
    OR name ~* '^Sierra [0-9]+ HD( Classic)?$'
    OR name = 'Canyon'
    OR name = 'Caballero'
    OR name = 'Sonoma'
    OR name = 'Syclone'
    OR name ~* '^C[0-9]{4,4}( Topkick)?'
    OR name ~* '^W[0-9]+'

    -- Ram (post-2010 spin-off from Dodge)
    OR name ~* '^[0-9]+(00)? Classic$' AND name ~* '^[12345]'
    OR name = '1500' OR name = '2500' OR name = '3500'
    OR name = '4500' OR name = '5500'
    OR name = '1500 Classic' OR name = '2500 HD' OR name = '3500 HD'
    OR name = 'Dakota'

    -- Dodge (pre-Ram)
    OR name = 'D150' OR name = 'D250' OR name = 'D350'
    OR name = 'W150' OR name = 'W250' OR name = 'W350'
    OR name = 'Power Wagon'
    OR name ~* '^Ram [0-9]+$'         -- "Ram 1500", "Ram 2500" (older Dodge Ram naming)
    OR name ~* '^Ram [0-9]+ Van$'     -- careful: this would be a van; left out by AND below

    -- Toyota
    OR name = 'Tacoma'
    OR name = 'Tundra'
    OR name = 'T100'
    OR name = 'Pickup'                -- 1989-95 Toyota Pickup
    OR name = 'Stout'

    -- Nissan
    OR name = 'Frontier'
    OR name = 'TITAN'
    OR name = 'TITAN XD'
    OR name = 'Titan'
    OR name = 'Hardbody'              -- older nickname; might not appear

    -- Jeep
    OR name = 'Gladiator'
    OR name = 'Comanche'
    OR name = 'J-10' OR name = 'J-20' OR name = 'J10' OR name = 'J20'
    OR name = 'Honcho'

    -- Honda
    OR name = 'Ridgeline'

    -- Hyundai
    OR name = 'Santa Cruz'

    -- Heavy-duty / commercial chassis cab
    OR name ~* '^NPR'                 -- Isuzu NPR / NPR-HD / NPR-XD
    OR name ~* '^NRR'
    OR name ~* '^NQR'
    OR name ~* '^FRR'
    OR name = 'FTR' OR name = 'FVR'
    OR name = 'Reach'                 -- Isuzu Reach
    OR name ~* '^W[0-9]+ Forward'    -- Chevy/Isuzu W-Series

    -- International / Workhorse / Hino etc.
    OR name ~* '^CV[0-9]+'
    OR name ~* '^MV[0-9]+'

    -- Mitsubishi Fuso
    OR name ~* '^FE[0-9]+'
    OR name ~* '^FG[0-9]+'

    -- Lordstown / Rivian / others
    OR name = 'Endurance'
    OR name = 'R1T'
    OR name = 'Cybertruck'
    OR name = 'Hummer EV Pickup'
    OR name = 'Lightning'             -- standalone "Lightning" if it exists
  );

-- Pull Buick Roadmaster back out if a regex accidentally caught it
UPDATE vcdb_model SET vehicle_type = NULL WHERE name = 'Roadmaster';


-- ---------------------------------------------------------------------
-- BLOCK B: SUVs (sport utility / crossover — covers commercial-popular
--   models like Bronco, Wrangler, 4Runner, Tahoe, Suburban, Yukon, Grand
--   Cherokee, Pilot, Expedition, etc.)
-- ---------------------------------------------------------------------
UPDATE vcdb_model SET vehicle_type = 'SUV'
WHERE vehicle_type IS NULL
  AND name IN (
    -- Ford
    'Bronco', 'Bronco Sport', 'Bronco II',
    'Expedition', 'Expedition EL', 'Expedition Max',
    'Explorer', 'Explorer Sport',
    'Escape', 'Edge', 'Flex',
    'EcoSport', 'Excursion',

    -- Chevrolet
    'Tahoe', 'Suburban', 'Suburban 1500', 'Suburban 2500',
    'Blazer', 'Blazer EV', 'TrailBlazer', 'Trailblazer', 'Trailblazer EXT',
    'Traverse', 'Equinox', 'Captiva Sport',

    -- GMC
    'Yukon', 'Yukon XL', 'Yukon Denali', 'Yukon Denali XL',
    'Terrain', 'Acadia', 'Acadia Limited', 'Envoy', 'Envoy XL',
    'Jimmy', 'Typhoon',

    -- Cadillac
    'Escalade', 'Escalade ESV', 'Escalade EXT', 'Escalade IQ',
    'XT4', 'XT5', 'XT6', 'SRX', 'XTS',

    -- Lincoln
    'Navigator', 'Navigator L',
    'Aviator', 'Nautilus', 'Corsair', 'MKX', 'MKT', 'MKC',

    -- Buick
    'Enclave', 'Encore', 'Encore GX', 'Envision', 'Rendezvous',

    -- Ram (small SUVs from the Dodge era)
    'Durango', 'Journey',

    -- Jeep
    'Wrangler', 'Wrangler JK', 'Wrangler JL', 'Wrangler Unlimited',
    'Wrangler 4xe', 'Wrangler Rubicon 392',
    'Grand Cherokee', 'Grand Cherokee L', 'Grand Cherokee WK',
    'Cherokee', 'Cherokee KL', 'Cherokee XJ',
    'Compass', 'Renegade', 'Patriot', 'Liberty', 'Commander',
    'Grand Wagoneer', 'Wagoneer', 'Wagoneer L',

    -- Toyota
    '4Runner', 'Sequoia', 'Land Cruiser', 'Land Cruiser Prado',
    'RAV4', 'RAV4 EV', 'RAV4 Prime', 'Highlander',
    'FJ Cruiser', 'Venza', 'C-HR', 'bZ4X', 'Corolla Cross',
    'Grand Highlander',

    -- Nissan
    'Pathfinder', 'Armada', 'Xterra', 'Murano',
    'Rogue', 'Rogue Sport', 'Rogue Select',
    'Kicks', 'Juke', 'Ariya', 'Patrol',

    -- Honda
    'Pilot', 'Passport', 'CR-V', 'HR-V', 'CRV',

    -- Acura
    'MDX', 'RDX', 'ZDX',

    -- Hyundai
    'Tucson', 'Santa Fe', 'Santa Fe XL', 'Santa Fe Sport',
    'Kona', 'Palisade', 'Nexo', 'Venue',

    -- Kia
    'Sorento', 'Sportage', 'Telluride', 'Soul', 'Seltos', 'Niro',

    -- Genesis
    'GV60', 'GV70', 'GV80',

    -- Subaru
    'Forester', 'Outback', 'Ascent', 'Crosstrek', 'Tribeca', 'Solterra',

    -- Mazda
    'CX-3', 'CX-30', 'CX-5', 'CX-50', 'CX-7', 'CX-9', 'CX-90',
    'Tribute', 'MX-30',

    -- Mitsubishi
    'Outlander', 'Outlander Sport', 'Outlander PHEV', 'Eclipse Cross',
    'Endeavor', 'Montero', 'Montero Sport', 'Pajero', 'Raider',

    -- Suzuki
    'Grand Vitara', 'Vitara', 'Samurai', 'Sidekick', 'XL-7',

    -- Isuzu
    'Trooper', 'Rodeo', 'Rodeo Sport', 'Amigo', 'Ascender', 'Axiom',
    'VehiCROSS',

    -- Lexus
    'GX', 'GX 460', 'GX 470', 'GX 550',
    'LX', 'LX 470', 'LX 570', 'LX 600',
    'RX', 'RX 300', 'RX 330', 'RX 350', 'RX 400h', 'RX 450h',
    'NX', 'UX', 'TX',

    -- Infiniti
    'QX30', 'QX50', 'QX55', 'QX56', 'QX60', 'QX70', 'QX80',
    'EX', 'FX', 'JX',

    -- Land Rover
    'Defender', 'Defender 90', 'Defender 110', 'Defender 130',
    'Discovery', 'Discovery Sport', 'LR2', 'LR3', 'LR4',
    'Range Rover', 'Range Rover Sport', 'Range Rover Velar',
    'Range Rover Evoque', 'Freelander',

    -- INEOS
    'Grenadier',

    -- Tesla
    'Model X', 'Model Y',

    -- Volkswagen
    'Atlas', 'Atlas Cross Sport', 'Tiguan', 'Touareg', 'ID.4', 'Taos',

    -- Volvo
    'XC40', 'XC60', 'XC70', 'XC90',

    -- BMW
    'X1', 'X2', 'X3', 'X4', 'X5', 'X6', 'X7', 'XM',

    -- Mercedes-Benz SUVs
    'GLA', 'GLB', 'GLC', 'GLE', 'GLS', 'G-Class',
    'GLA250', 'GLE350', 'GLE450',
    'GLK350', 'ML350', 'ML450', 'ML500', 'ML550', 'GL450', 'GL550',

    -- Porsche
    'Cayenne', 'Macan',

    -- Audi
    'Q3', 'Q4', 'Q5', 'Q6', 'Q7', 'Q8', 'SQ5', 'SQ7', 'SQ8',
    'e-tron',

    -- Rivian
    'R1S',

    -- Lucid
    'Gravity'
  );

-- =====================================================================
-- Verify
-- =====================================================================
--   SELECT vehicle_type, COUNT(*) FROM vcdb_model WHERE vehicle_type IS NOT NULL GROUP BY vehicle_type;
