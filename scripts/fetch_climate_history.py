"""Download multi-year hourly sunlight (GHI) for the reference climate zones and store it in public.climate_ghi_history.

    .venv/bin/python scripts/fetch_climate_history.py            # all zones, 2021-2025
    .venv/bin/python scripts/fetch_climate_history.py caribe_norte --years 2016-2025

Source: Open-Meteo archive (`shortwave_radiation`, UTC), the same variable and hour convention as vrm.weather_hourly.ghi_wm2.
Only the public reference points are sent to the service, never a client's coordinates. Safe to re-run (upsert per zone/year).
The logic lives in calculations/climate_history.py (also used by the wizard's "Actualizar clima" button).
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv(".env")

from calculations.climate_history import ZONES, fetch_zone, store_year  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zones", nargs="*", help="zone keys (default: all)")
    ap.add_argument("--years", default="2021-2025")
    a = ap.parse_args()
    y0, y1 = (int(x) for x in a.years.split("-"))
    keys = a.zones or list(ZONES)
    from database.supabase_client import get_client

    db = get_client()
    for key in keys:
        _, lat, lon = ZONES[key]
        years = fetch_zone(lat, lon, y0, y1)
        for y, vals in sorted(years.items()):
            store_year(db, key, y, vals)
        means = ", ".join(f"{y}: {sum(v) / len(v):.0f}" for y, v in sorted(years.items()))
        print(f"{key:18} {len(years)} years | mean W/m2 by year -> {means}", flush=True)
        time.sleep(1.0)                                 # be polite to the free API


if __name__ == "__main__":
    main()
