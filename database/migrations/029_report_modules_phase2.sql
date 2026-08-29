-- Migration 029: report module selection — Phase 18 "Phase 2" (new module types)
--
-- Adds four new selectable modules on top of migration 028's nine:
-- critical_alerts, grid_meter_detail, generator_runtime, tank_level. See
-- PLAN_PHASE18.md §7 for the module inventory and the 2026-08-26 live VRM
-- API diagnostics probe that grounds every column below in a real,
-- confirmed attribute code rather than a guess.
--
-- Oscar's own instruction for this step (2026-08-29): build all four
-- unconditionally — a subscriber may have a generator or tank even though
-- none of the installations this product currently manages do — and when a
-- site has no data for one, the report shows it as zero/unavailable rather
-- than hiding the module. That is a rendering-time concern (weekly_report.py
-- Step 2), not a schema one; every column below is a plain nullable field,
-- same as every VRM-API-only column migration 012 already shipped
-- (pv_yield_kwh_sc0/sc1 etc.) that reads NULL on a CSV-sourced row.

-- ════════════════════════════════════════════════════════════════════
-- 1. Critical alerts — a NEW table, deliberately NOT vrm.alarm_events
-- ════════════════════════════════════════════════════════════════════
-- vrm.count_alarm_episodes() (migration 012) counts every row for a
-- site/date in vrm.alarm_events with no filter on `source` or `alarm` —
-- health_score is a straight function of that count. vrm_csv.py's own
-- ALARM_CATEGORIES comment calls widening the *scored* categories "a
-- deliberate, cross-path change" that would make health scores mean
-- different things depending on ingestion path if done carelessly. DC
-- ripple / cell imbalance / temperature faults are real and
-- safety-relevant (any of them can precede a shutdown) but must NEVER be
-- scored — so they get their own table the scoring trigger never reads,
-- rather than a new `source` value inside alarm_events that a future
-- change to count_alarm_episodes() could accidentally start counting.
-- Column shape deliberately mirrors vrm.alarm_events (alarm/severity/source/
-- timestamp) — `category` here IS that table's `source` column, renamed
-- only to make the fixed 3-value vocabulary read as what it is rather than
-- a free-text source label — so `victron.vrm_daily.alarm_episode_events()`
-- (already shared code, called with `source=<category id>`) produces rows
-- insertable here with a plain rename, not a reshape.
CREATE TABLE IF NOT EXISTS vrm.critical_alerts (
  id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  site_id       text        NOT NULL REFERENCES vrm.sites(site_id) ON DELETE CASCADE,
  category      text        NOT NULL CHECK (category IN ('dc_ripple', 'cell_imbalance', 'temp_fault')),
  alarm         text,       -- human label, e.g. 'High DC Ripple L2', 'Module1 has cell imbalance'
  severity      text,       -- 'WARNING' | 'CLEARED', same vocabulary as alarm_events
  "timestamp"   timestamptz,
  created_at    timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vrm_critical_alerts_site_ts
  ON vrm.critical_alerts USING btree (site_id, "timestamp");

COMMENT ON TABLE vrm.critical_alerts IS
  'PLAN_PHASE18.md §7 item 9. Deliberately separate from vrm.alarm_events so vrm.count_alarm_episodes() (and therefore health_score) never sees these rows — see this migration''s own comment for the full reasoning. Populated only by the VRM-API ingestion path today (victron/vrm_series.py); the CSV path already detects the CSV-column equivalents via vrm_csv.py''s UNSCORED_ALARM_SIGNALS but, as of this migration, still only logs them as ingestion warnings rather than writing rows here — the two paths reaching full parity is a follow-up, not blocking this module''s existence.';

-- ════════════════════════════════════════════════════════════════════
-- 2. vrm.energy_daily — hardware-conditional per-day fields
-- ════════════════════════════════════════════════════════════════════
-- All nullable, all NULL on every row that exists before this migration
-- and on every CSV-sourced row that has no equivalent column to read —
-- same "NULL, not a fabricated zero" rule migration 012's own
-- pv_yield_kwh_sc0/sc1 columns already follow, and the same rule that
-- lets a report tell "no generator on this system" (NULL) apart from "the
-- generator didn't run this week" (0) when a caller wants to.
ALTER TABLE vrm.energy_daily
  -- Gt ("Accumulated time for generic Generator") is a lifetime counter,
  -- not a daily flow total — this column is the WITHIN-DAY delta
  -- (last sample minus first sample), computed by the mapper, not a
  -- running total. Confirmed present in VRM diagnostics on 4 real
  -- installations (all El Encino) but with zero actual data points in a
  -- 90-day live probe (2026-08-29) — the attribute is registered, nothing
  -- is currently reporting through it. Ships anyway per Oscar's own
  -- instruction: a future subscriber's generator may report live, and a
  -- site with the attribute registered but silent should read 0 hours,
  -- not omit the module.
  ADD COLUMN IF NOT EXISTS generator_hours numeric,

  -- A real physical grid meter's own per-phase readings (confirmed live
  -- on Emtec, 2026-08-29: g1v/g1c/g1p/g1pf/g1F and the L2/L3 equivalents,
  -- plus gpn/gps) — materially richer than the IV1/IV2 inverter-side
  -- approximation the existing Grid Quality module already uses. Shaped
  -- as jsonb rather than ~15 new columns for 3 phases x (v/c/p/pf) plus
  -- frequency/PEN-voltage/phase-sequence, matching the precedent
  -- vrm.sites.health_thresholds already sets for a per-installation blob
  -- that has no fixed cardinality across installations (a single-phase
  -- site has no L2/L3 keys at all, rather than three all-NULL columns).
  ADD COLUMN IF NOT EXISTS grid_meter jsonb,

  -- Tank sensor fields (confirmed registered in VRM diagnostics on El
  -- Encino Casita: tc/tf/ts/tcn — 2026-08-26 probe; zero live data points
  -- in a 90-day check, 2026-08-29, same "registered but silent" situation
  -- as the generator above). No numeric fill-percentage code was found on
  -- any of the 13 real installations this product manages — `tank_level_pct`
  -- below is speculative (Victron's own D-Bus tank service publishes a
  -- `/Level` path generically; the VRM stats attribute code for it was
  -- never seen on real data here) and is populated only if a future
  -- installation actually publishes it. `tank_status`/`tank_fluid_type`
  -- store Victron's raw values un-decoded (their documented enums were not
  -- empirically confirmed against any real reading either) rather than
  -- inventing a label mapping nothing here can verify.
  ADD COLUMN IF NOT EXISTS tank_level_pct numeric,
  ADD COLUMN IF NOT EXISTS tank_status text,
  ADD COLUMN IF NOT EXISTS tank_fluid_type text,
  ADD COLUMN IF NOT EXISTS tank_capacity_m3 numeric;

COMMENT ON COLUMN vrm.energy_daily.generator_hours IS
  'PLAN_PHASE18.md §7 item 4b. Within-day delta of Victron''s Gt (accumulated generator runtime) counter. NULL = signal not published by this installation at all; 0 = published but the generator did not run that day.';
COMMENT ON COLUMN vrm.energy_daily.grid_meter IS
  'PLAN_PHASE18.md §7 item 4a. Per-phase real grid-meter detail (voltage/current/power/power-factor per phase, frequency, PEN voltage, phase sequence) when a physical meter — not just the inverter''s own AC-input reading — is present. NULL = no real meter on this installation.';

-- ════════════════════════════════════════════════════════════════════
-- 3. Module id CHECK constraints — extend to 13 known ids
-- ════════════════════════════════════════════════════════════════════
-- Migration 028 added both constraints inline (ADD COLUMN ... CHECK (...))
-- without an explicit name, so Postgres auto-named them by its own
-- deterministic "<table>_<column>_check" convention — but this migration
-- doesn't lean on knowing that name is exactly right. A DO block looks up
-- whatever CHECK constraint actually exists on each column via
-- information_schema and drops it by its real, looked-up name, so a wrong
-- assumption here fails loudly (the ADD below would then error "already
-- exists" against a stale narrower constraint) rather than silently
-- leaving the old 9-id constraint in place forever alongside a harmless
-- unused new one.
DO $$
DECLARE
  con_name text;
BEGIN
  SELECT tc.constraint_name INTO con_name
  FROM information_schema.constraint_column_usage ccu
  JOIN information_schema.table_constraints tc
    ON tc.constraint_name = ccu.constraint_name AND tc.constraint_schema = ccu.constraint_schema
  WHERE ccu.table_schema = 'vrm' AND ccu.table_name = 'sites'
    AND ccu.column_name = 'report_modules' AND tc.constraint_type = 'CHECK';
  IF con_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE vrm.sites DROP CONSTRAINT %I', con_name);
  END IF;

  SELECT tc.constraint_name INTO con_name
  FROM information_schema.constraint_column_usage ccu
  JOIN information_schema.table_constraints tc
    ON tc.constraint_name = ccu.constraint_name AND tc.constraint_schema = ccu.constraint_schema
  WHERE ccu.table_schema = 'vrm' AND ccu.table_name = 'customers'
    AND ccu.column_name = 'default_report_modules' AND tc.constraint_type = 'CHECK';
  IF con_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE vrm.customers DROP CONSTRAINT %I', con_name);
  END IF;
END $$;

ALTER TABLE vrm.sites
  ADD CONSTRAINT sites_report_modules_check
    CHECK (report_modules IS NULL OR report_modules <@ ARRAY[
      'energy_mix', 'battery_health', 'grid_quality', 'events',
      'soc_chart', 'solar_performance', 'weather', 'trend', 'savings',
      'critical_alerts', 'grid_meter_detail', 'generator_runtime', 'tank_level'
    ]::text[]);

ALTER TABLE vrm.customers
  ADD CONSTRAINT customers_default_report_modules_check
    CHECK (default_report_modules IS NULL OR default_report_modules <@ ARRAY[
      'energy_mix', 'battery_health', 'grid_quality', 'events',
      'soc_chart', 'solar_performance', 'weather', 'trend', 'savings',
      'critical_alerts', 'grid_meter_detail', 'generator_runtime', 'tank_level'
    ]::text[]);
