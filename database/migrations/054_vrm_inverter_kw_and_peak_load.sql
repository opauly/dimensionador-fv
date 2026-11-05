-- 054: inverter size per site and daily peak load, for the wizard's fleet reference (calculations/fleet_reference.py).
--
--   vrm.sites.inverter_nominal_kw   TOTAL continuous AC power of all inverter/charger units at 25 C, in kW, from the
--                                   datasheet (one MultiPlus-II 48/5000 = 4.0; two in split-phase = 8.0). Filled by
--                                   hand, like pv_kwp / battery_nominal_kwh. Nullable: a site without it is simply not
--                                   used for the inverter comparison.
--   vrm.energy_daily.peak_load_w    highest AC load (W) seen that day, written by the vrm-monitor ingestion for complete
--                                   days. Peaks from 15-minute VRM averages understate real peaks (lower bound).
--
-- Additive and idempotent. Already applied to the live project before this file was added, so this file is the record
-- of it (keep the repo's migrations the single source of truth for the vrm schema).

ALTER TABLE vrm.sites        ADD COLUMN IF NOT EXISTS inverter_nominal_kw numeric;
ALTER TABLE vrm.energy_daily ADD COLUMN IF NOT EXISTS peak_load_w         numeric;
