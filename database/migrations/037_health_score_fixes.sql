-- Migration 037: three health-score correctness fixes
--
-- Found 2026-09-03 while adding the score's "why" notes to the Fleet
-- Dashboard UI — once the reasoning was actually visible, three problems
-- with the scoring itself became obvious that a bare number had been
-- hiding.
--
-- 1. Battery cycling was silently dead for every VRM-API site.
--    `COALESCE(ed.battery_discharge_kwh, 0) / capacity` treated "not
--    measured" as "zero discharge" -- and victron/vrm_series.py's own
--    docstring documents that battery_discharge_kwh is NULL on EVERY
--    VRM-API-sourced row by design (VRM's derived battery totals disagreed
--    with a real battery monitor by up to 97%). That made cycles = 0
--    always for that whole ingestion path, so the check could never fire,
--    with nothing anywhere saying so. weekly_report.py already gets this
--    right (`battery_kwh_available` -- "no data is better than fabricated
--    data") and shows "n/a" rather than a fake 0; the SQL score should
--    behave the same way: skip the check when the input isn't real,
--    rather than silently pass it.
--
-- 2. Outage duration and outage count independently penalized the same
--    underlying event set, uncapped -- a site with six 15-minute blips
--    (90 min total) could score as badly as one 150-minute outage despite
--    60% less real downtime, because -10 (moderate duration) + -10
--    (frequent) stacked to match -20 (long duration alone). Capping the
--    combined outage deduction at 20 (the existing single worst-case
--    ceiling) keeps frequency and duration as distinct, visible notes
--    without letting many-short-blips outscore-badly a genuinely longer
--    single outage.
--
-- 3. Off-grid systems are routinely SIZED to cycle deep into their battery
--    every day -- that's the design, not a fault. The mildest SOC tier
--    ("SOC below 40%", -8) fired for off-grid exactly as often as for a
--    grid-tied hybrid dipping the same way for no good reason, penalizing
--    correct operation. The WARNING (-15) and ALARM (-25) tiers still
--    apply to every system type -- a genuinely dangerous SOC is a problem
--    regardless of design -- only the mild "watch" tier is skipped for
--    off-grid specifically. monitoring.compute_daily_health() has no
--    system_type differentiation yet (its own TODO comment, migration
--    010) so this fix is vrm-only; #1 and #2 apply to both, keeping the
--    stated rule that a health score must mean the same thing on both
--    paths.

CREATE OR REPLACE FUNCTION vrm.compute_daily_health(
  p_site_id text,
  p_date date,
  p_dump_type text DEFAULT 'csv_upload'
)
RETURNS vrm.daily_health
LANGUAGE plpgsql
AS $$
DECLARE
  ed vrm.energy_daily%ROWTYPE;
  v_alarms_count integer;
  v_battery_capacity numeric;
  v_battery_cycles numeric;
  v_grid_dependency_pct numeric;
  v_min_soc numeric;
  v_outage_count integer;
  v_outage_minutes numeric;
  v_outage_penalty integer;
  v_max_temperature numeric;
  v_min_voltage numeric;
  v_mppt_reached_float boolean;
  v_grid_data_available boolean;
  v_system_type text;
  v_has_battery boolean;
  v_has_grid boolean;
  v_score integer := 100;
  v_notes text[] := '{}';
  v_status text;
  v_result vrm.daily_health;

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
BEGIN
  SELECT * INTO ed
  FROM vrm.energy_daily
  WHERE site_id = p_site_id AND date = p_date AND dump_type = p_dump_type
  ORDER BY id DESC
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN NULL;
  END IF;

  SELECT health_thresholds, system_type INTO v_thr, v_system_type
  FROM vrm.sites WHERE site_id = p_site_id;
  v_thr := v_defaults || COALESCE(v_thr, '{}'::jsonb);
  v_system_type := COALESCE(v_system_type, 'hybrid');

  v_has_battery := v_system_type IN ('off_grid', 'hybrid');
  v_has_grid    := v_system_type IN ('grid_zero', 'hybrid');

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

  v_alarms_count       := vrm.count_alarm_episodes(p_site_id, p_date);
  v_min_soc            := COALESCE(ed.min_soc, 0);
  v_outage_count       := COALESCE(ed.outage_count, 0);
  v_outage_minutes     := COALESCE(ed.outage_minutes, 0);
  v_battery_capacity   := COALESCE(NULLIF(ed.battery_kwh_snapshot, 0), 1);
  -- Fix 1: NULL means "not measured for this site" (every VRM-API row, by
  -- design), not "zero discharge" -- keep it NULL rather than fabricating
  -- a passing 0, and skip the whole battery-cycling check below when it is.
  v_battery_cycles     := CASE WHEN ed.battery_discharge_kwh IS NULL THEN NULL
                               ELSE ed.battery_discharge_kwh / v_battery_capacity END;
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

  IF v_has_battery THEN
    IF v_min_soc > 0 AND v_min_soc < t_soc_low_alarm THEN
      v_score := v_score - 25;
      v_notes := array_append(v_notes, 'Very low SOC');
    ELSIF v_min_soc < t_soc_low_warning THEN
      v_score := v_score - 15;
      v_notes := array_append(v_notes, 'Low SOC');
    -- Fix 3: off-grid systems are routinely sized to cycle this deep every
    -- day by design -- the WARNING/ALARM tiers above still catch a
    -- genuinely dangerous SOC regardless of system type; only this
    -- mildest tier is skipped for off-grid specifically.
    ELSIF v_min_soc < t_soc_low_watch AND v_has_grid THEN
      v_score := v_score - 8;
      v_notes := array_append(v_notes, 'SOC below ' || t_soc_low_watch || '%');
    END IF;
  END IF;

  IF v_has_grid THEN
    -- Fix 2: duration and frequency are distinct, worth separate notes,
    -- but both describe the SAME day's outage events -- cap their combined
    -- cost at the existing single worst-case ceiling (20) so many short
    -- blips can't outscore-badly one genuinely longer outage.
    v_outage_penalty := 0;
    IF v_outage_minutes > t_outage_min_long THEN
      v_outage_penalty := v_outage_penalty + 20;
      v_notes := array_append(v_notes, 'Long outage time');
    ELSIF v_outage_minutes > t_outage_min_mid THEN
      v_outage_penalty := v_outage_penalty + 10;
      v_notes := array_append(v_notes, 'Moderate outage time');
    ELSIF v_outage_minutes > 0 THEN
      v_outage_penalty := v_outage_penalty + 5;
      v_notes := array_append(v_notes, 'Grid outage detected');
    END IF;

    IF v_outage_count > t_outage_count_high THEN
      v_outage_penalty := v_outage_penalty + 10;
      v_notes := array_append(v_notes, 'Frequent outages');
    END IF;

    v_score := v_score - LEAST(v_outage_penalty, 20);

    IF v_grid_dependency_pct > t_grid_dep_high THEN
      v_score := v_score - 10;
      v_notes := array_append(v_notes, 'High grid dependency');
    ELSIF v_grid_dependency_pct > t_grid_dep_mid THEN
      v_score := v_score - 5;
      v_notes := array_append(v_notes, 'Moderate grid dependency');
    END IF;
  END IF;

  IF v_has_battery THEN
    IF v_battery_cycles IS NOT NULL THEN
      IF v_battery_cycles > t_battery_cycles_high THEN
        v_score := v_score - 10;
        v_notes := array_append(v_notes, 'High battery cycling');
      ELSIF v_battery_cycles > t_battery_cycles_mid THEN
        v_score := v_score - 5;
        v_notes := array_append(v_notes, 'Moderate battery cycling');
      END IF;
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
  END IF;

  IF v_has_grid AND v_grid_data_available = false THEN
    v_notes := array_append(v_notes, 'No grid measurements recorded — verify AC input connections');
  END IF;

  IF ed.complete_day = false THEN
    v_notes := array_append(v_notes,
      'Partial day (' || COALESCE(ROUND(ed.hours_covered, 1)::text, '?') || 'h of data)');
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

  INSERT INTO vrm.daily_health
    (site_id, date, dump_type, health_score, health_status, alarms_count,
     min_soc, outage_count, outage_minutes, grid_dependency_pct, battery_cycles, notes)
  VALUES
    (p_site_id, p_date, p_dump_type, v_score, v_status, v_alarms_count,
     ed.min_soc, v_outage_count, v_outage_minutes,
     ROUND(v_grid_dependency_pct, 1), ROUND(v_battery_cycles, 2), array_to_string(v_notes, '; '))
  ON CONFLICT (site_id, date, dump_type) DO UPDATE SET
    health_score        = EXCLUDED.health_score,
    health_status       = EXCLUDED.health_status,
    alarms_count        = EXCLUDED.alarms_count,
    min_soc             = EXCLUDED.min_soc,
    outage_count        = EXCLUDED.outage_count,
    outage_minutes      = EXCLUDED.outage_minutes,
    grid_dependency_pct = EXCLUDED.grid_dependency_pct,
    battery_cycles      = EXCLUDED.battery_cycles,
    notes               = EXCLUDED.notes
  RETURNING * INTO v_result;

  RETURN v_result;
END;
$$;


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
  v_outage_penalty integer;
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

  -- TODO(system_type): unchanged from migration 010 -- once
  -- monitoring.sites.system_type = 'grid_zero' is real, battery scoring
  -- should be skipped entirely for that type. Fix 3 (off-grid SOC-watch
  -- exemption) is NOT ported here for the same reason: there is no
  -- system_type signal in this schema yet to gate it on.
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
  -- Fix 1, same reasoning as vrm.compute_daily_health() above -- defensive
  -- here (Node-RED does populate real battery_discharge_kwh today), but
  -- keeps both functions agreeing on what NULL means if that ever changes.
  v_battery_cycles     := CASE WHEN ed.battery_discharge_kwh IS NULL THEN NULL
                               ELSE ed.battery_discharge_kwh / v_battery_capacity END;
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

  -- Fix 2, same reasoning as vrm.compute_daily_health() above.
  v_outage_penalty := 0;
  IF v_outage_minutes > t_outage_min_long THEN
    v_outage_penalty := v_outage_penalty + 20;
    v_notes := array_append(v_notes, 'Long outage time');
  ELSIF v_outage_minutes > t_outage_min_mid THEN
    v_outage_penalty := v_outage_penalty + 10;
    v_notes := array_append(v_notes, 'Moderate outage time');
  ELSIF v_outage_minutes > 0 THEN
    v_outage_penalty := v_outage_penalty + 5;
    v_notes := array_append(v_notes, 'Grid outage detected');
  END IF;

  IF v_outage_count > t_outage_count_high THEN
    v_outage_penalty := v_outage_penalty + 10;
    v_notes := array_append(v_notes, 'Frequent outages');
  END IF;

  v_score := v_score - LEAST(v_outage_penalty, 20);

  IF v_grid_dependency_pct > t_grid_dep_high THEN
    v_score := v_score - 10;
    v_notes := array_append(v_notes, 'High grid dependency');
  ELSIF v_grid_dependency_pct > t_grid_dep_mid THEN
    v_score := v_score - 5;
    v_notes := array_append(v_notes, 'Moderate grid dependency');
  END IF;

  IF v_battery_cycles IS NOT NULL THEN
    IF v_battery_cycles > t_battery_cycles_high THEN
      v_score := v_score - 10;
      v_notes := array_append(v_notes, 'High battery cycling');
    ELSIF v_battery_cycles > t_battery_cycles_mid THEN
      v_score := v_score - 5;
      v_notes := array_append(v_notes, 'Moderate battery cycling');
    END IF;
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
    health_status       = EXCLUDED.health_status,
    alarms_count        = EXCLUDED.alarms_count,
    min_soc             = EXCLUDED.min_soc,
    outage_count        = EXCLUDED.outage_count,
    outage_minutes      = EXCLUDED.outage_minutes,
    grid_dependency_pct = EXCLUDED.grid_dependency_pct,
    battery_cycles      = EXCLUDED.battery_cycles,
    notes               = EXCLUDED.notes
  RETURNING * INTO v_result;

  RETURN v_result;
END;
$$;
