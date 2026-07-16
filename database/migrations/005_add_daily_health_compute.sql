-- Migration 005: monitoring.daily_health auto-compute
-- Ports Google Apps Script's calculateHealthScore() / appendDailyHealth() /
-- countAlarmEpisodesForDate() (victron-monitor/apps-script/Victron_Events_App_Script_v1p6.js,
-- lines ~150-350) into Postgres, so monitoring.daily_health gets populated
-- automatically instead of only existing in Google Sheets.
--
-- Thresholds are hardcoded to match Node-RED's CONFIG.defaultHealthThresholds
-- (all 3 current sites share these). If/when sites need distinct thresholds,
-- move these into columns on monitoring.sites and read them per-row instead.

-- ────────────────────────────────────────────────────────────
-- Alarm episode counter — mirrors countAlarmEpisodesForDate().
-- An episode = one WARNING/ALARM through to its CLEARED; rapid
-- oscillation between WARNING/ALARM counts as one episode, not many.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION monitoring.count_alarm_episodes(p_site_id text, p_date date)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  rec RECORD;
  episodes integer := 0;
  in_episode boolean := false;
BEGIN
  FOR rec IN
    SELECT severity
    FROM monitoring.alarm_events
    WHERE site_id = p_site_id
      AND ("timestamp" AT TIME ZONE 'America/Costa_Rica')::date = p_date
    ORDER BY "timestamp" ASC
  LOOP
    IF (rec.severity = 'WARNING' OR rec.severity = 'ALARM') AND NOT in_episode THEN
      episodes := episodes + 1;
      in_episode := true;
    ELSIF rec.severity = 'CLEARED' THEN
      in_episode := false;
    END IF;
  END LOOP;

  RETURN episodes;
END;
$$;

-- ────────────────────────────────────────────────────────────
-- compute_daily_health — the RPC. Computes the score for one
-- site+date+dump_type from monitoring.energy_daily +
-- monitoring.alarm_events, and upserts monitoring.daily_health.
-- Callable directly via RPC (POST /rest/v1/rpc/compute_daily_health)
-- for backfill/manual recompute, and invoked automatically by the
-- trigger below for every new energy_daily row.
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

  -- thresholds — match Node-RED CONFIG.defaultHealthThresholds
  t_soc_low_alarm       constant numeric  := 20;
  t_soc_low_warning     constant numeric  := 30;
  t_soc_low_watch       constant numeric  := 40;
  t_outage_min_long     constant numeric  := 120;
  t_outage_min_mid      constant numeric  := 30;
  t_outage_count_high   constant integer  := 5;
  t_grid_dep_high       constant numeric  := 50;
  t_grid_dep_mid        constant numeric  := 20;
  t_battery_cycles_high constant numeric  := 1.5;
  t_battery_cycles_mid  constant numeric  := 1.0;
BEGIN
  SELECT * INTO ed
  FROM monitoring.energy_daily
  WHERE site_id = p_site_id AND date = p_date AND dump_type = p_dump_type
  ORDER BY id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

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

  -- Alarms
  IF v_alarms_count > 0 THEN
    v_score := v_score - LEAST(25, v_alarms_count * 5);
    v_notes := array_append(v_notes, v_alarms_count || ' alarm event(s)');
  END IF;

  -- SOC (faithfully replicates the JS falsy-coalescing quirk: a 0/missing
  -- min_soc falls into the "< socLowWarning" branch, same as the source)
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

  -- Outage duration
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

  -- Outage frequency
  IF v_outage_count > t_outage_count_high THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'Frequent outages');
  END IF;

  -- Grid dependency
  IF v_grid_dependency_pct > t_grid_dep_high THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'High grid dependency');
  ELSIF v_grid_dependency_pct > t_grid_dep_mid THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Moderate grid dependency');
  END IF;

  -- Battery cycling
  IF v_battery_cycles > t_battery_cycles_high THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'High battery cycling');
  ELSIF v_battery_cycles > t_battery_cycles_mid THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Moderate battery cycling');
  END IF;

  -- Battery temperature
  IF v_max_temperature IS NOT NULL AND v_max_temperature > 45 THEN
    v_score := v_score - 15;
    v_notes := array_append(v_notes, 'High battery temperature (' || v_max_temperature || '°C)');
  ELSIF v_max_temperature IS NOT NULL AND v_max_temperature > 40 THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Elevated battery temperature (' || v_max_temperature || '°C)');
  END IF;

  -- Battery voltage
  IF v_min_voltage IS NOT NULL AND v_min_voltage < 46.0 THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'Low battery voltage (' || v_min_voltage || 'V)');
  END IF;

  -- MPPT never reached float
  IF v_mppt_reached_float = false THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Battery did not fully charge today');
  END IF;

  -- Grid data availability — data quality flag, no score penalty
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

-- ────────────────────────────────────────────────────────────
-- Trigger — fires after every energy_daily insert/update and
-- (re)computes that row's daily_health automatically.
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION monitoring.trg_energy_daily_health()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM monitoring.compute_daily_health(NEW.site_id, NEW.date, NEW.dump_type);
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS energy_daily_health_trigger ON monitoring.energy_daily;
CREATE TRIGGER energy_daily_health_trigger
  AFTER INSERT OR UPDATE ON monitoring.energy_daily
  FOR EACH ROW
  EXECUTE FUNCTION monitoring.trg_energy_daily_health();

-- ────────────────────────────────────────────────────────────
-- Grants — table grants from migration 004 don't cover function
-- EXECUTE privileges; needed so the trigger can write as `anon`
-- (the role Node-RED authenticates as) and so compute_daily_health
-- can be called directly as an RPC.
-- ────────────────────────────────────────────────────────────
GRANT EXECUTE ON FUNCTION monitoring.count_alarm_episodes(text, date) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION monitoring.compute_daily_health(text, date, text) TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA monitoring GRANT EXECUTE ON FUNCTIONS TO anon, authenticated, service_role;

-- ────────────────────────────────────────────────────────────
-- Backfill existing energy_daily rows (run once after deploying).
-- ────────────────────────────────────────────────────────────
-- DO $$
-- DECLARE r RECORD;
-- BEGIN
--   FOR r IN SELECT DISTINCT site_id, date, dump_type FROM monitoring.energy_daily LOOP
--     PERFORM monitoring.compute_daily_health(r.site_id, r.date, r.dump_type);
--   END LOOP;
-- END $$;
