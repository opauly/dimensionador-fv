-- 053: two more inverter datasheet fields used by the wiring / breaker sizing.
--   ac_out_rated_a  rated current of the main AC output (AC-out-1). For a pass-through inverter this
--                   is more than its own inverter-only output: with the grid present the output also
--                   carries the pass-through current (MultiPlus-II 5k: 115 A vs 41.7 A on its own).
--                   It is the ceiling for the AC-out breaker.
--   efficiency_pct  maximum efficiency from the datasheet, used for the battery -> inverter DC current.
-- Values from the Victron MultiPlus-II 120V datasheet/manual. Additive and idempotent.

ALTER TABLE inverters
    ADD COLUMN IF NOT EXISTS ac_out_rated_a numeric,
    ADD COLUMN IF NOT EXISTS efficiency_pct numeric;

UPDATE inverters SET ac_out_rated_a = 115, efficiency_pct = 96 WHERE model = 'MultiPlus-II 48/5000/70-95';
UPDATE inverters SET ac_out_rated_a = 50,  efficiency_pct = 95 WHERE model = 'MultiPlus-II 48/3000/35-50';
