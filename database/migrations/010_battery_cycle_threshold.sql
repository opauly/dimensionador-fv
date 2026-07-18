-- Migration 010: recalibrate battery-cycling threshold
--
-- batteryCyclesHigh/Mid (1.5 / 1.0 cycles per week) was miscalibrated for
-- Hybrid and Off-Grid systems, which are *designed* to cycle the battery
-- roughly once per day (~7/week) as normal, healthy self-consumption
-- behavior — the old default flagged every correctly-functioning system
-- as "High stress" permanently. Confirmed via Pylontech's LFP cycle-life
-- rating (~6,000 cycles @ 80% DOD) — daily cycling is sustainable for
-- 15+ years, well past typical system lifetime.
--
-- New values only flag genuinely abnormal cycling (>1.5-2x/day sustained,
-- suggesting an undersized battery or a system fault) rather than normal
-- daily operation.
--
-- Applies to Hybrid and Off-Grid alike — both cycle daily by design, so
-- no per-system_type differentiation needed for this specific threshold
-- (unlike whether battery scoring applies at all, see the TODO on
-- compute_daily_health() for the future no-battery Grid Zero case).

-- 1. New column default, for every future site
ALTER TABLE monitoring.sites
  ALTER COLUMN health_thresholds SET DEFAULT
    '{
      "socLowAlarm": 20,
      "socLowWarning": 30,
      "socLowWatch": 40,
      "outageMinLong": 120,
      "outageMinMid": 30,
      "outageCountHigh": 5,
      "gridDepHigh": 50,
      "gridDepMid": 20,
      "batteryCyclesHigh": 10.0,
      "batteryCyclesMid": 7.0
    }'::jsonb;

-- 2. Existing sites — only touch the two battery keys, preserve anything
--    already customized on other thresholds.
UPDATE monitoring.sites
SET health_thresholds = health_thresholds || '{"batteryCyclesHigh": 10.0, "batteryCyclesMid": 7.0}'::jsonb;

-- 3. compute_daily_health()'s fallback default (used when merging a
--    site's health_thresholds — keeps the function's own defaults
--    consistent with the column default above).
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

  v_defaults constant jsonb := '{
      "socLowAlarm": 20, "socLowWarning": 30, "socLowWatch": 40,
      "outageMinLong": 120, "outageMinMid": 30, "outageCountHigh": 5,
      "gridDepHigh": 50, "gridDepMid": 20,
      "batteryCyclesHigh": 10.0, "batteryCyclesMid": 7.0
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

  -- TODO(system_type): once monitoring.sites.system_type = 'grid_zero'
  -- (no-battery Fronius sites) is real, battery scoring below should be
  -- skipped entirely for that type rather than compared against any
  -- threshold — there's no battery to stress. Deferred until there's a
  -- real grid_zero site to verify against (matches the same deferral in
  -- the Apps Script report's KPI/info-block TODOs).
BEGIN
  SELECT * INTO ed
  FROM monitoring.energy_daily
  WHERE site_id = p_site_id AND date = p_date AND dump_type = p_dump_type
  ORDER BY id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

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
