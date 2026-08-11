-- Migration 017: battery nominal kWh + DoD% as the source of truth
--
-- `battery_usable_kwh` (monitoring.sites / vrm.sites) was being hand-typed
-- directly, but nobody enters a system that way — the datasheet reports
-- NOMINAL capacity and depth-of-discharge separately, and usable = nominal x
-- dod/100 was being computed in someone's head before typing it in, with no
-- record of what DoD was assumed. That's also inconsistent with how the
-- proposal tool's own equipment catalog already models a battery
-- (capacity_kwh + dod_pct as separate fields, usable derived on demand) —
-- this migration brings the monitoring side in line with that.
--
-- Deliberately additive and non-breaking:
--   - battery_nominal_kwh / battery_dod_pct are new, nullable columns.
--   - battery_usable_kwh is UNCHANGED — every existing consumer (the
--     compute_daily_health() functions in both schemas, the battery_cycles
--     view in 004, victron/vrm_csv.py, victron/weekly_report.py) keeps
--     reading it exactly as before.
--   - The app (pages/06_vrm_monitor.py) now collects nominal + DoD% instead
--     of usable directly, and computes usable = nominal * dod/100 before
--     writing all three columns. Existing rows (El Encino, 2 Floor Pool,
--     Vista Atenas LP M1/M2/M3) keep their hand-entered battery_usable_kwh
--     until someone supplies the real nominal/DoD to backfill from.
--
-- NOT turned into a GENERATED column on purpose: that requires dropping and
-- re-adding battery_usable_kwh, which would NULL it out for every site until
-- nominal_kwh/dod_pct are backfilled — an outage for the health dashboard's
-- battery_cycles metric on exactly the sites that already have good data.
-- Once every active site has nominal + DoD recorded, a follow-up migration
-- can safely make battery_usable_kwh GENERATED ALWAYS AS (...) STORED.

ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS battery_nominal_kwh  numeric;
ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS battery_dod_pct       numeric
                            CHECK (battery_dod_pct IS NULL
                                   OR (battery_dod_pct > 0 AND battery_dod_pct <= 100));

ALTER TABLE vrm.sites
  ADD COLUMN IF NOT EXISTS battery_nominal_kwh  numeric;
ALTER TABLE vrm.sites
  ADD COLUMN IF NOT EXISTS battery_dod_pct       numeric
                            CHECK (battery_dod_pct IS NULL
                                   OR (battery_dod_pct > 0 AND battery_dod_pct <= 100));
