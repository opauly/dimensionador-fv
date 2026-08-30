-- Migration 031: live site snapshots — Fleet Dashboard Phase 2.
--
-- Phase 1 (2026-08-30, admin /admin/fleet) rolled up data this pipeline
-- already computes DAILY (health score, alarm episodes) into one
-- cross-site view — genuinely useful, but "as of the last completed day,"
-- never "right now." This closes that gap: one row per site, holding its
-- MOST RECENT live reading, upserted by a ~15-minute job
-- (`victron/vrm_live.py:fetch_live_snapshot()` /
-- `vrm_api/routers/vrm_fleet.py:post_refresh_snapshots()`).
--
-- One row per site (UPSERT on site_id), not a growing history table — a
-- live dashboard answers "what is this site doing right now," not "show me
-- a trend" (the existing `vrm.energy_daily` already covers trends, at daily
-- grain). Revisit only if a real "last 24h sparkline" need shows up later;
-- that would be a genuinely different table (a short rolling window), not
-- a reason to widen this one.
--
-- Every power/SOC field is NULLABLE — this pipeline's own established rule
-- (migration 012's pv_yield_kwh_sc0/sc1, vrm_series.py's whole "no data is
-- better than fabricated data" section): a signal this specific
-- installation doesn't publish reads NULL, never a fabricated zero.
--
-- `inverter_state`/`active_ac_source` are stored RAW and undecoded (the
-- literal value VRM's `S`/`AI` attribute codes return) — their enum
-- meanings were not confirmed against Victron's own documentation during
-- this phase (a live probe, 2026-08-30, found `AI` returning a bare
-- integer with no confirmed mapping to "grid"/"generator"/"inverter").
-- Decoding these into human labels is real future work, not something to
-- guess at now — see `victron/vrm_live.py`'s own module comment.
--
-- Run once in the Supabase SQL Editor. Idempotent: safe to run twice.

CREATE TABLE IF NOT EXISTS vrm.site_snapshots (
  site_id             text        PRIMARY KEY REFERENCES vrm.sites(site_id) ON DELETE CASCADE,
  captured_at         timestamptz NOT NULL,
  pv_power_w          numeric,
  load_power_w        numeric,
  battery_power_w     numeric,
  grid_power_w        numeric,
  soc_pct             numeric,
  inverter_state_raw  text,
  active_ac_source_raw text,
  raw                 jsonb,
  updated_at          timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE vrm.site_snapshots IS
  'Fleet Dashboard Phase 2 (2026-08-30). One row per site, upserted by the ~15-minute snapshot-refresh job — the site''s most recent live reading, not a history table. NULL fields mean this installation does not publish that signal, never a fabricated 0. inverter_state_raw/active_ac_source_raw are undecoded VRM enum values (codes S/AI) — see this migration''s own header for why they are not translated into human labels yet.';

COMMENT ON COLUMN vrm.site_snapshots.grid_power_w IS
  'Only populated for installations with a real grid-power attribute published (confirmed present on some real sites, absent on others during Phase 2''s own live probe, 2026-08-30) — NULL, not 0, when this installation has no such signal.';

COMMENT ON COLUMN vrm.site_snapshots.raw IS
  'The raw per-code values this snapshot was derived from (PVP per solar-charger instance, a1/a2, bp, SOC, g1-g3 if present, S, AI) — kept for debugging/future re-derivation without needing a second live API call, same "raw" precedent vrm.subscriptions.raw already sets for ONVO payloads.';
