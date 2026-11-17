-- 071: hourly roll-up of the eGauge 15-minute readings, so the wizard downloads 42k rows (5 years) instead of 168k.
-- ts = START of the UTC hour. usage_kw is the hour's mean; peak_kw / min_kw are the highest / lowest 15-minute reading in it.
CREATE OR REPLACE VIEW vrm.egauge_hourly WITH (security_invoker = true) AS
SELECT site_id,
       (date_trunc('hour', ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC') AS ts,
       avg(usage_kw)::real  AS usage_kw,
       max(usage_kw)::real  AS peak_kw,
       min(usage_kw)::real  AS min_kw,
       count(*)::smallint   AS n
FROM vrm.egauge_samples
GROUP BY site_id, (date_trunc('hour', ts AT TIME ZONE 'UTC') AT TIME ZONE 'UTC');

COMMENT ON VIEW vrm.egauge_hourly IS 'Hourly mean / peak / min of vrm.egauge_samples.usage_kw (start of the UTC hour).';
