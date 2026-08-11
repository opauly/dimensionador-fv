-- Migration 018: backfill battery_usable_kwh from nominal x DoD
--
-- Follow-up to 017. All hybrid/off-grid sites now have battery_nominal_kwh
-- and battery_dod_pct filled in from their datasheets — this recomputes
-- battery_usable_kwh from those two instead of the old hand-typed value, so
-- every site's usable figure reflects the same, auditable source facts.
--
-- Safe to re-run: only touches rows where both source columns are present,
-- and it's a plain deterministic overwrite (no accumulation).

UPDATE monitoring.sites
SET battery_usable_kwh = round(battery_nominal_kwh * battery_dod_pct / 100, 2)
WHERE battery_nominal_kwh IS NOT NULL
  AND battery_dod_pct IS NOT NULL;

UPDATE vrm.sites
SET battery_usable_kwh = round(battery_nominal_kwh * battery_dod_pct / 100, 2)
WHERE battery_nominal_kwh IS NOT NULL
  AND battery_dod_pct IS NOT NULL;
