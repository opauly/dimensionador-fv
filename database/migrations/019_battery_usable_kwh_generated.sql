-- Migration 019: battery_usable_kwh becomes a generated column
--
-- Follow-up to 017/018, now that every hybrid/off-grid site has
-- battery_nominal_kwh and battery_dod_pct recorded from the datasheet.
-- battery_usable_kwh no longer needs to be a value anyone (or the app) can
-- write independently — it's fully determined by the two source facts.
-- GENERATED ALWAYS AS (...) STORED means Postgres recomputes it automatically
-- whenever either source column changes, and rejects any direct write to it,
-- so it can never drift out of sync with the datasheet values again.
--
-- Postgres can't ALTER a plain column into a generated one — it has to be
-- dropped and re-added. monitoring.sites.battery_usable_kwh is read by the
-- monitoring.fleet_summary view (migration 004), and Postgres won't drop a
-- column a view depends on, so that view is dropped and recreated (verbatim,
-- from 004) around the column swap. vrm.sites.battery_usable_kwh has no view
-- or index depending on it — vrm.compute_daily_health() reads
-- energy_daily.battery_kwh_snapshot instead, a separate per-day-captured
-- column untouched by this migration — so it's a plain drop + re-add there.
--
-- IMPORTANT: after this runs, nothing may pass battery_usable_kwh in an
-- insert/update payload for either sites table — Postgres raises an error on
-- writes to a generated column. pages/06_vrm_monitor.py's two save paths
-- (manual site form, CSV upload) are updated in this same change to stop
-- sending it — they still show the computed value to the user before saving,
-- just don't write it themselves anymore.

-- ── monitoring.sites ──────────────────────────────────────────────────
DROP VIEW IF EXISTS monitoring.fleet_summary;

ALTER TABLE monitoring.sites DROP COLUMN IF EXISTS battery_usable_kwh;
ALTER TABLE monitoring.sites
  ADD COLUMN battery_usable_kwh numeric
    GENERATED ALWAYS AS (round(battery_nominal_kwh * battery_dod_pct / 100, 2)) STORED;

CREATE OR REPLACE VIEW monitoring.fleet_summary AS
SELECT
  s.site_id,
  s.display_name,
  s.owner,
  s.location,
  s.country,
  s.pv_kwp,
  s.battery_usable_kwh,
  ed.date,
  ed.dump_type,
  ed.pv_kwh,
  ed.grid_kwh,
  ed.load_kwh,
  ed.battery_charge_kwh,
  ed.battery_discharge_kwh,
  ed.min_soc,
  ed.max_soc,
  ed.avg_soc,
  ed.outage_count,
  ed.outage_minutes,
  ed.min_voltage,
  ed.max_voltage,
  ed.min_temperature,
  ed.max_temperature,
  ed.avg_temperature,
  ed.pv_yield_kwh_sc0,
  ed.pv_yield_kwh_sc1,
  ed.pv_yield_kwh_mppt,
  ed.battery_reached_float,
  ed.min_grid_freq,
  ed.max_grid_freq,
  ed.min_grid_v_l1,
  ed.max_grid_v_l1,
  ed.min_grid_v_l2,
  ed.max_grid_v_l2,
  ed.grid_data_available,
  round(ed.grid_kwh / NULLIF(ed.load_kwh, 0::numeric) * 100::numeric, 1) AS grid_dependency_pct,
  round(ed.battery_discharge_kwh / NULLIF(s.battery_usable_kwh, 0::numeric), 3) AS battery_cycles,
  dh.health_score,
  dh.health_status,
  dh.alarms_count,
  dh.notes
FROM monitoring.energy_daily ed
JOIN monitoring.sites s ON s.site_id = ed.site_id
LEFT JOIN monitoring.daily_health dh
  ON dh.site_id = ed.site_id AND dh.date = ed.date AND dh.dump_type = ed.dump_type
WHERE s.active = true
ORDER BY ed.date DESC, s.display_name;

-- ── vrm.sites ─────────────────────────────────────────────────────────
ALTER TABLE vrm.sites DROP COLUMN IF EXISTS battery_usable_kwh;
ALTER TABLE vrm.sites
  ADD COLUMN battery_usable_kwh numeric
    GENERATED ALWAYS AS (round(battery_nominal_kwh * battery_dod_pct / 100, 2)) STORED;
