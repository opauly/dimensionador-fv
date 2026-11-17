-- 069: multi-year hourly sunlight history for reference climate zones of Costa Rica.
--
-- Why: the "Simulación con datos reales" card (calculations/fleet_simulation.py) replays the fleet's own weather, which is only
-- ~90 rainy-season days from the fleet's locations. A reliability goal such as "at most 2 days a year without energy" needs many
-- years of weather, in the climate of the site being quoted. This table holds that history; it is OUR table (the vrm schema belongs
-- to VRM Monitor and also holds forecasts, so it is left untouched).
--
--   public.climate_ghi_history   one row per zone per year.
--       zone        short key of the reference zone (e.g. 'caribe_norte').
--       label       human name of the zone.
--       lat, lon    the public reference point used to fetch it (rounded to 0.01 deg). Never a client's coordinates.
--       year        calendar year (UTC).
--       ghi_wm2     sunlight on a horizontal surface, W/m2, one value per hour from Jan 1 00:00 UTC (8760 values, 8784 in a leap
--                   year). Same variable and the same hour convention as vrm.weather_hourly.ghi_wm2 (Open-Meteo shortwave_radiation;
--                   checked identical on the overlapping 2026 days).
--       source      where it came from.
--
-- Backend-only: RLS on with no policies (default deny for the public API roles); the app reads it with its server key.

CREATE TABLE IF NOT EXISTS public.climate_ghi_history (
    zone       text          NOT NULL,
    label      text          NOT NULL,
    lat        numeric(6, 2) NOT NULL,
    lon        numeric(7, 2) NOT NULL,
    year       smallint      NOT NULL,
    ghi_wm2    smallint[]    NOT NULL,
    source     text          NOT NULL DEFAULT 'open-meteo-archive',
    fetched_at timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (zone, year),
    CHECK (cardinality(ghi_wm2) IN (8760, 8784))
);

ALTER TABLE public.climate_ghi_history ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.climate_ghi_history IS 'Hourly sunlight (GHI, W/m2) per reference climate zone and year, from Open-Meteo. Feeds the multi-year reliability simulation.';
