-- Migration 038: vrm.site_anomalies — Fleet Dashboard Phase 3b (unexpected
-- silence), PLAN_PHASE19_FLEET_P3.md §2/§3.
--
-- A deliberately SEPARATE signal from `vrm.daily_health`
-- (`vrm.compute_daily_health()`, migration 012) and its trigger — this table
-- and the logic that writes it (`victron/anomaly_silence.py`) never touch
-- that function or fire from its trigger (PLAN_PHASE19_FLEET_P3.md §1: lower
-- blast radius, nothing else depends on this table yet).
--
-- One open row per (site_id, anomaly_type) at a time, same open/cleared
-- shape `vrm.alarm_events`/`vrm.critical_alerts` already use (`cleared_at
-- IS NULL` = still active): a new detection while one is already open
-- updates `detail` in place rather than opening a duplicate row; a check
-- that no longer finds the condition sets `cleared_at`. The app layer
-- (`victron/anomaly_silence.py`) is what maintains that invariant, same as
-- `vrm.site_snapshots`' own "one row per site" is maintained by the caller
-- upserting on `site_id`, not a table-level guarantee alone — but unlike
-- that table, THIS invariant only needs to hold among the OPEN rows for a
-- given (site_id, anomaly_type), so the partial unique index below actually
-- can (and does) enforce it at the database level too, catching a bug that
-- would otherwise silently double-open the same anomaly.
--
-- Only 'unexpected_silence' (Phase 3b) is written by anything today —
-- 'quiet_drift' (3a) and 'underperformance' (3c) are already in the CHECK
-- constraint's vocabulary per the plan doc's own schema (§2) so a later
-- phase's migration doesn't need to widen this constraint, but nothing
-- writes those two anomaly_type values yet.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.

CREATE TABLE IF NOT EXISTS vrm.site_anomalies (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  site_id       text        NOT NULL REFERENCES vrm.sites(site_id) ON DELETE CASCADE,
  anomaly_type  text        NOT NULL CHECK (anomaly_type IN ('quiet_drift', 'unexpected_silence', 'underperformance')),
  detected_at   timestamptz NOT NULL,
  cleared_at    timestamptz,        -- NULL = still active
  detail        jsonb,              -- e.g. {"silent_since": "...", "minutes_silent": 47, "expected_window_local": "08:00-16:00"}
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Plain lookup index for "this site's open anomalies" (the plan doc's own
-- §2 index) — superseded for the (site_id, anomaly_type) case by the UNIQUE
-- index below, but kept as its own index too since a dashboard query for
-- "all of this site's open anomalies, any type" is still exactly a
-- site_id-only lookup.
CREATE INDEX IF NOT EXISTS idx_vrm_site_anomalies_open_site
  ON vrm.site_anomalies (site_id) WHERE cleared_at IS NULL;

-- Enforces the "one open row per (site_id, anomaly_type)" invariant the plan
-- doc's own §2 states in prose (not just relying on the writer's own
-- read-before-write logic) — same "a hard constraint backs a real invariant"
-- precedent `vrm_energy_daily_site_date_unique` (migration 012) and
-- `idx_vrm_sites_customer_installation` (migration 024) already set in this
-- schema.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vrm_site_anomalies_one_open_per_type
  ON vrm.site_anomalies (site_id, anomaly_type) WHERE cleared_at IS NULL;

COMMENT ON TABLE vrm.site_anomalies IS
  'Fleet Dashboard Phase 3 (2026-09-03), PLAN_PHASE19_FLEET_P3.md. Deterministic anomaly detection, separate from vrm.daily_health/compute_daily_health(). anomaly_type is one of quiet_drift (3a)/unexpected_silence (3b)/underperformance (3c) — only unexpected_silence is written as of this migration. cleared_at IS NULL means still active; at most one active row per (site_id, anomaly_type), enforced by idx_vrm_site_anomalies_one_open_per_type.';

COMMENT ON COLUMN vrm.site_anomalies.detail IS
  'Whatever the detecting check found useful to show on the dashboard — shape varies by anomaly_type, never a fixed set of keys across all three. See victron/anomaly_silence.py''s own docstring for unexpected_silence''s exact keys.';
