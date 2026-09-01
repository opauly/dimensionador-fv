-- Migration 032: vrm.ingestion_log.critical_alerts_written — a genuine
-- deployment gap found live 2026-09-01, not a new feature.
--
-- Commit fd6775a (2026-08-29, "Phase 18 Phase 2: critical alerts...") added
-- `critical_alerts_written` to victron/ingest.py:ingest_parsed()'s
-- ingestion_log insert, but never shipped the matching migration. Since
-- that commit, EVERY sync of EVERY site (scheduled daily syncs, admin/
-- customer "Sync now") has crashed on this exact insert with
-- "Could not find the 'critical_alerts_written' column of 'ingestion_log'
-- in the schema cache" (PGRST204).
--
-- The real data survives: alarm_events/critical_alerts/energy_daily (and
-- the daily_health trigger it fires) are all written earlier in
-- ingest_parsed(), before this line — so health scores and reports have
-- stayed correct. What's been silently broken since Aug 29: (1) the
-- ingestion_log audit trail has zero new rows, and (2) vrm.sites.
-- vrm_last_synced_at never advances, because vrm_api/routers/vrm_sync.py:
-- _do_sync()'s own `sites.update({"vrm_last_synced_at": ...})` call sits
-- AFTER ingest_parsed() returns — the exception thrown here means it's
-- never reached. This is what made the Fleet dashboard's "Connection"
-- status look stuck at Aug 29 for days even though real report data kept
-- advancing underneath it.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.

ALTER TABLE vrm.ingestion_log
  ADD COLUMN IF NOT EXISTS critical_alerts_written integer NOT NULL DEFAULT 0;

COMMENT ON COLUMN vrm.ingestion_log.critical_alerts_written IS
  'How many vrm.critical_alerts rows this ingest wrote — the critical-alerts counterpart to alarm_events_written, same shape. Missing since migration 029 added the critical_alerts table itself without this column; added here after the gap broke every sync starting 2026-08-29 (commit fd6775a) with a PGRST204 schema-cache error.';
