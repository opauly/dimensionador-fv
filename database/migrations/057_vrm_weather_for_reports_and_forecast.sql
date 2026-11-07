-- 057: the weather table now also serves the PDF reports and the forecast, so it keeps what they use.
--
--   vrm.weather_hourly (added columns)
--       sunshine_s      seconds of sunshine in the hour (the reports' "sunshine hours").
--       rain_prob_pct   chance of rain, % (a forecast figure; the forecast's storm / rain advice).
--       weather_code    WMO weather code (95, 96 and 99 are thunderstorms).
--       fetched_at      when this row was last refreshed. A row whose ts is later than fetched_at is a FORECAST for an hour
--                       that had not happened yet; it is overwritten by the next refresh. Rows with ts <= fetched_at are
--                       what the weather actually did.
--
--   vrm.weather_daily   sunrise and sunset per place per day (the forecast's "will the battery reach sunrise").
--
-- Backend-only like the rest of the schema: RLS on, no policies. Additive and idempotent.

ALTER TABLE vrm.weather_hourly ADD COLUMN IF NOT EXISTS sunshine_s     real;
ALTER TABLE vrm.weather_hourly ADD COLUMN IF NOT EXISTS rain_prob_pct  real;
ALTER TABLE vrm.weather_hourly ADD COLUMN IF NOT EXISTS weather_code   smallint;
ALTER TABLE vrm.weather_hourly ADD COLUMN IF NOT EXISTS fetched_at     timestamptz NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS vrm.weather_daily (
    lat         numeric(6, 2) NOT NULL,
    lon         numeric(7, 2) NOT NULL,
    date        date          NOT NULL,        -- the UTC day the row was read for
    sunrise     timestamptz,
    sunset      timestamptz,
    fetched_at  timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (lat, lon, date)
);

ALTER TABLE vrm.weather_daily ENABLE ROW LEVEL SECURITY;

COMMENT ON COLUMN vrm.weather_hourly.fetched_at IS 'Last refresh. ts > fetched_at = a forecast for an hour that had not happened yet.';
COMMENT ON TABLE  vrm.weather_daily IS 'Sunrise / sunset per place per UTC day, from Open-Meteo.';
