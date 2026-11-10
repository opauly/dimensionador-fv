-- 058: manufacturer limits the wiring / breaker / fuse sizing checks against, plus a datasheet file per equipment row.
-- Values come from the datasheets in Desktop/Pauly & Co/General/FV General/Datasheets/. NULL = not entered yet
-- (the checks skip it). Additive and idempotent.
--
--   panels.max_series_fuse_a      module "maximum series fuse / overcurrent protection rating" (a breaker counts too)
--   inverters.cont_w_25c          continuous output WATTS at 25 C (the catalog kw is the VA rating; the DC side carries watts)
--   inverters.peak_w              peak power (W)
--   inverters.max_ocpd_a          maximum AC breaker size the manufacturer allows on the output (Fronius table)
--   inverters.dc_fuse_a           DC fuse rating the manufacturer recommends / allows on the battery side
--   batteries.max_charge_a / max_discharge_a / fuse_a   continuous currents and the fuse the manufacturer calls for
--   datasheet_path                path in the private "solar-tool" bucket (datasheets/<type>/<file>.pdf)

ALTER TABLE panels            ADD COLUMN IF NOT EXISTS max_series_fuse_a numeric;
ALTER TABLE inverters         ADD COLUMN IF NOT EXISTS cont_w_25c numeric,
                              ADD COLUMN IF NOT EXISTS peak_w numeric,
                              ADD COLUMN IF NOT EXISTS max_ocpd_a numeric,
                              ADD COLUMN IF NOT EXISTS dc_fuse_a numeric;
ALTER TABLE batteries         ADD COLUMN IF NOT EXISTS max_charge_a numeric,
                              ADD COLUMN IF NOT EXISTS max_discharge_a numeric,
                              ADD COLUMN IF NOT EXISTS fuse_a numeric,
                              ADD COLUMN IF NOT EXISTS datasheet_path text;
ALTER TABLE charge_controllers ADD COLUMN IF NOT EXISTS datasheet_path text;
ALTER TABLE monitoring_devices ADD COLUMN IF NOT EXISTS datasheet_path text;

-- Victron MultiPlus-II 120 V datasheet: continuous 4000 W (5000 VA) at 25 C, peak 9000 W (48/5000); 2400 W / 5500 W (48/3000).
UPDATE inverters SET cont_w_25c = 4000, peak_w = 9000 WHERE model LIKE 'MultiPlus-II 48/5000%';
UPDATE inverters SET cont_w_25c = 2400, peak_w = 5500 WHERE model LIKE 'MultiPlus-II 48/3000%';

-- Fronius Primo datasheet (US), 240 V: max continuous output current and AC breaker size. Only fills what is empty.
UPDATE inverters SET ac_output_current_a = COALESCE(ac_output_current_a, v.out_a), max_ocpd_a = COALESCE(max_ocpd_a, v.ocpd)
FROM (VALUES ('Primo 3.8', 15.8, 20), ('Primo 5.0', 20.8, 30), ('Primo 6.0', 25.0, 35), ('Primo 7.6', 31.7, 40),
             ('Primo 8.2', 34.2, 45), ('Primo 10.0', 41.6, 60), ('Primo 11.4', 47.5, 60), ('Primo 12.5', 52.1, 70),
             ('Primo 15.0', 62.5, 80)) AS v(prefix, out_a, ocpd)
WHERE inverters.brand = 'Fronius' AND inverters.model LIKE v.prefix || '%';
