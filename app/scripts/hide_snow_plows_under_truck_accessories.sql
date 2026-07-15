-- hide_snow_plows_under_truck_accessories.sql
--
-- Category 102 ("Truck Accessories > Exterior > Snow Plows and
-- Accessories") was showing as a tile under Truck Accessories > Exterior
-- alongside Mud Guards / Paint Protection / etc., which is semantically
-- wrong — snow plows are equipment, not exterior accessories, and they
-- already have a dedicated top-nav entry "❄ SNOW PLOWS" that routes to
-- Truck Equipment > Snow Plows/Spreaders (id 55).
--
-- All 1,160 products linked to category 102 are ALSO linked under the
-- Truck Equipment > Snow Plows tree, so deactivating 102 doesn't
-- orphan any products — they remain discoverable via the proper nav.
--
-- Reversible: re-enable with `UPDATE category SET is_active=true WHERE id=102;`

UPDATE category SET is_active = false, updated_at = NOW() WHERE id = 102;
