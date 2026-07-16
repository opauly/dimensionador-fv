-- Migration 006: per-site config in monitoring.sites
-- Moves config that is currently hardcoded in each Node-RED flow's
-- Project Config node into monitoring.sites, so onboarding a new site
-- becomes a database insert instead of editing flow JavaScript.
--
-- Adds:
--   health_thresholds jsonb  — per-site health scoring thresholds
--   app_script_url    text   — this site's Google Apps Script web app URL
--   utc_offset_hours  int    — this site's UTC offset
--
-- and rewrites compute_daily_health() to read each site's thresholds
-- (merged over a default set) instead of using hardcoded constants.
--
-- NON-BREAKING: the default thresholds equal the constants from
-- migration 005, so every existing site scores identically until its
-- health_thresholds are deliberately customized.

-- ────────────────────────────────────────────────────────────
-- 1. New columns (existing rows get the DEFAULT automatically)
-- ────────────────────────────────────────────────────────────
ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS health_thresholds jsonb NOT NULL DEFAULT
    '{
      "socLowAlarm": 20,
      "socLowWarning": 30,
      "socLowWatch": 40,
      "outageMinLong": 120,
      "outageMinMid": 30,
      "outageCountHigh": 5,
      "gridDepHigh": 50,
      "gridDepMid": 20,
      "batteryCyclesHigh": 1.5,
      "batteryCyclesMid": 1.0
    }'::jsonb;

ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS app_script_url text;

ALTER TABLE monitoring.sites
  ADD COLUMN IF NOT EXISTS utc_offset_hours int NOT NULL DEFAULT -6;

-- ────────────────────────────────────────────────────────────
-- 2. Backfill known values for existing sites
-- health_thresholds + utc_offset_hours already filled by the column
-- DEFAULT above. app_script_url is per-device and only known for m3;
-- fill m1/m2 manually once you have each one's deployment URL.
-- ────────────────────────────────────────────────────────────
UPDATE monitoring.sites
SET app_script_url = 'https://script.google.com/macros/s/AKfycbww6PjJRTZ4gqrSA_CxS5eLBmN6QtUsEWzaT8kP2whv1i87vkG6u4TzqgW-xVstLYvUZw/exec'
WHERE site_id = 'vista-atenas-lp-m3';

-- TODO — fill in when known:
-- UPDATE monitoring.sites SET app_script_url = '<m2 url>' WHERE site_id = 'vista-atenas-lp-m2';
-- UPDATE monitoring.sites SET app_script_url = '<m1 url>' WHERE site_id = 'vista-atenas-lp-m1';

-- ────────────────────────────────────────────────────────────
-- 3. Rewrite compute_daily_health() to read per-site thresholds.
-- Same signature → the existing trigger binding is preserved.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION monitoring.compute_daily_health(
  p_site_id text,
  p_date date,
  p_dump_type text DEFAULT 'AUTO'
)
RETURNS monitoring.daily_health
LANGUAGE plpgsql
AS $$
DECLARE
  ed monitoring.energy_daily%ROWTYPE;
  v_alarms_count integer;
  v_battery_capacity numeric;
  v_battery_cycles numeric;
  v_grid_dependency_pct numeric;
  v_min_soc numeric;
  v_outage_count integer;
  v_outage_minutes numeric;
  v_max_temperature numeric;
  v_min_voltage numeric;
  v_mppt_reached_float boolean;
  v_grid_data_available boolean;
  v_score integer := 100;
  v_notes text[] := '{}';
  v_status text;
  v_result monitoring.daily_health;

  -- Per-site thresholds merged over defaults (defaults match migration 005).
  v_defaults constant jsonb := '{
      "socLowAlarm": 20, "socLowWarning": 30, "socLowWatch": 40,
      "outageMinLong": 120, "outageMinMid": 30, "outageCountHigh": 5,
      "gridDepHigh": 50, "gridDepMid": 20,
      "batteryCyclesHigh": 1.5, "batteryCyclesMid": 1.0
  }'::jsonb;
  v_thr jsonb;

  t_soc_low_alarm       numeric;
  t_soc_low_warning     numeric;
  t_soc_low_watch       numeric;
  t_outage_min_long     numeric;
  t_outage_min_mid      numeric;
  t_outage_count_high   integer;
  t_grid_dep_high       numeric;
  t_grid_dep_mid        numeric;
  t_battery_cycles_high numeric;
  t_battery_cycles_mid  numeric;
BEGIN
  SELECT * INTO ed
  FROM monitoring.energy_daily
  WHERE site_id = p_site_id AND date = p_date AND dump_type = p_dump_type
  ORDER BY id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  -- Load this site's thresholds, merged over defaults. A missing site row
  -- or missing keys fall back to defaults, so this is always safe.
  SELECT health_thresholds INTO v_thr FROM monitoring.sites WHERE site_id = p_site_id;
  v_thr := v_defaults || COALESCE(v_thr, '{}'::jsonb);

  t_soc_low_alarm       := (v_thr->>'socLowAlarm')::numeric;
  t_soc_low_warning     := (v_thr->>'socLowWarning')::numeric;
  t_soc_low_watch       := (v_thr->>'socLowWatch')::numeric;
  t_outage_min_long     := (v_thr->>'outageMinLong')::numeric;
  t_outage_min_mid      := (v_thr->>'outageMinMid')::numeric;
  t_outage_count_high   := (v_thr->>'outageCountHigh')::integer;
  t_grid_dep_high       := (v_thr->>'gridDepHigh')::numeric;
  t_grid_dep_mid        := (v_thr->>'gridDepMid')::numeric;
  t_battery_cycles_high := (v_thr->>'batteryCyclesHigh')::numeric;
  t_battery_cycles_mid  := (v_thr->>'batteryCyclesMid')::numeric;

  v_alarms_count       := monitoring.count_alarm_episodes(p_site_id, p_date);
  v_min_soc            := COALESCE(ed.min_soc, 0);
  v_outage_count       := COALESCE(ed.outage_count, 0);
  v_outage_minutes     := COALESCE(ed.outage_minutes, 0);
  v_battery_capacity   := COALESCE(NULLIF(ed.battery_kwh_snapshot, 0), 1);
  v_battery_cycles     := COALESCE(ed.battery_discharge_kwh, 0) / v_battery_capacity;
  v_grid_dependency_pct := CASE WHEN COALESCE(ed.load_kwh, 0) > 0
                             THEN (COALESCE(ed.grid_kwh, 0) / ed.load_kwh) * 100
                             ELSE 0 END;
  v_max_temperature    := NULLIF(COALESCE(ed.max_temperature, 0), 0);
  v_min_voltage        := NULLIF(COALESCE(ed.min_voltage, 0), 0);
  v_mppt_reached_float := COALESCE(ed.battery_reached_float, false);
  v_grid_data_available := COALESCE(ed.grid_data_available, true);

  IF v_alarms_count > 0 THEN
    v_score := v_score - LEAST(25, v_alarms_count * 5);
    v_notes := array_append(v_notes, v_alarms_count || ' alarm event(s)');
  END IF;

  IF v_min_soc > 0 AND v_min_soc < t_soc_low_alarm THEN
    v_score := v_score - 25;
    v_notes := array_append(v_notes, 'Very low SOC');
  ELSIF v_min_soc < t_soc_low_warning THEN
    v_score := v_score - 15;
    v_notes := array_append(v_notes, 'Low SOC');
  ELSIF v_min_soc < t_soc_low_watch THEN
    v_score := v_score - 8;
    v_notes := array_append(v_notes, 'SOC below ' || t_soc_low_watch || '%');
  END IF;

  IF v_outage_minutes > t_outage_min_long THEN
    v_score := v_score - 20;
    v_notes := array_append(v_notes, 'Long outage time');
  ELSIF v_outage_minutes > t_outage_min_mid THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'Moderate outage time');
  ELSIF v_outage_minutes > 0 THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Grid outage detected');
  END IF;

  IF v_outage_count > t_outage_count_high THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'Frequent outages');
  END IF;

  IF v_grid_dependency_pct > t_grid_dep_high THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'High grid dependency');
  ELSIF v_grid_dependency_pct > t_grid_dep_mid THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Moderate grid dependency');
  END IF;

  IF v_battery_cycles > t_battery_cycles_high THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'High battery cycling');
  ELSIF v_battery_cycles > t_battery_cycles_mid THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Moderate battery cycling');
  END IF;

  IF v_max_temperature IS NOT NULL AND v_max_temperature > 45 THEN
    v_score := v_score - 15;
    v_notes := array_append(v_notes, 'High battery temperature (' || v_max_temperature || '°C)');
  ELSIF v_max_temperature IS NOT NULL AND v_max_temperature > 40 THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Elevated battery temperature (' || v_max_temperature || '°C)');
  END IF;

  IF v_min_voltage IS NOT NULL AND v_min_voltage < 46.0 THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'Low battery voltage (' || v_min_voltage || 'V)');
  END IF;

  IF v_mppt_reached_float = false THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Battery did not fully charge today');
  END IF;

  IF v_grid_data_available = false THEN
    v_notes := array_append(v_notes, 'No grid measurements recorded — verify AC input connections');
  END IF;

  v_score := GREATEST(0, LEAST(100, v_score));

  v_status := 'Excellent';
  IF v_score < 70 THEN v_status := 'Attention';
  ELSIF v_score < 80 THEN v_status := 'Watch';
  ELSIF v_score < 90 THEN v_status := 'Good';
  END IF;

  IF array_length(v_notes, 1) IS NULL THEN
    v_notes := array_append(v_notes, 'Normal operation');
  END IF;

  INSERT INTO monitoring.daily_health
    (site_id, date, dump_type, health_score, health_status, alarms_count,
     min_soc, outage_count, outage_minutes, grid_dependency_pct, battery_cycles, notes)
  VALUES
    (p_site_id, p_date, p_dump_type, v_score, v_status, v_alarms_count,
     ed.min_soc, v_outage_count, v_outage_minutes,
     ROUND(v_grid_dependency_pct, 1), ROUND(v_battery_cycles, 2), array_to_string(v_notes, '; '))
  ON CONFLICT (site_id, date, dump_type) DO UPDATE SET
    health_score        = EXCLUDED.health_score,
    health_status        = EXCLUDED.health_status,
    alarms_count          = EXCLUDED.alarms_count,
    min_soc               = EXCLUDED.min_soc,
    outage_count           = EXCLUDED.outage_count,
    outage_minutes          = EXCLUDED.outage_minutes,
    grid_dependency_pct       = EXCLUDED.grid_dependency_pct,
    battery_cycles             = EXCLUDED.battery_cycles,
    notes                       = EXCLUDED.notes
  RETURNING * INTO v_result;

  RETURN v_result;
END;
$$;
