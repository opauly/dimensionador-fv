-- Migration 040: vrm.site_anomalies.anomaly_type -- add 'incomplete_charging'
--
-- Fleet Dashboard Phase 3d, added 2026-09-03 once the original three checks
-- (migration 038's own CHECK constraint: unexpected_silence, quiet_drift,
-- underperformance) were live. Same table, same "one open row per
-- (site_id, anomaly_type)" shape -- see victron/anomaly_battery.py's own
-- module docstring for the check itself and why it doesn't need this
-- migration's own new columns, just a fourth allowed value on the existing
-- one.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice (the
-- ADD CONSTRAINT below fails harmlessly the second time since the widened
-- constraint by that name already exists -- rerun only the DROP+ADD pair
-- if that happens, not the whole file blindly).

ALTER TABLE vrm.site_anomalies
  DROP CONSTRAINT IF EXISTS site_anomalies_anomaly_type_check;

ALTER TABLE vrm.site_anomalies
  ADD CONSTRAINT site_anomalies_anomaly_type_check
  CHECK (anomaly_type IN ('quiet_drift', 'unexpected_silence', 'underperformance', 'incomplete_charging'));

COMMENT ON TABLE vrm.site_anomalies IS
  'Fleet Dashboard Phase 3 (2026-09-03), PLAN_PHASE19_FLEET_P3.md. Deterministic anomaly detection, separate from vrm.daily_health/compute_daily_health(). anomaly_type is one of quiet_drift (3a)/unexpected_silence (3b)/underperformance (3c)/incomplete_charging (3d) -- all four are real, live-written shapes as of migration 040. cleared_at IS NULL means still active; at most one active row per (site_id, anomaly_type), enforced by idx_vrm_site_anomalies_one_open_per_type.';
