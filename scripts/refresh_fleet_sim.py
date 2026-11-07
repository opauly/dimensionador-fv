"""Rebuild the cached dataset behind the Objetivos "Simulación con datos reales" card (calculations/fleet_simulation.py).

    .venv/bin/python scripts/refresh_fleet_sim.py

Reads vrm.site_samples / vrm.weather_hourly (read-only) and writes .cache/fleet_sim.pkl. The app also rebuilds it in the
background when it is older than 24 h, so running this is only needed to force a refresh or to look at the validation table.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv(".env")
from calculations import fleet_simulation as fs

fs.refresh(blocking=True)
ds = fs.get_dataset()
if not ds:
    sys.exit("could not build the dataset")
print(f"window {ds['window'][0]:%Y-%m-%d} to {ds['window'][1]:%Y-%m-%d} | {len(ds['loads'])} load patterns | {len(ds['weather'])} weather locations")
print("solar response k:", None if ds["k"] is None else round(ds["k"], 3))
for v in ds["validation"]:
    flag = "accepted" if v["accepted"] else "rejected"
    print(f"  {v['name'][:34]:34} {flag:9} k={v['k'] if v['k'] is None else round(v['k'], 2)} corr={v['corr'] if v['corr'] is None else round(v['corr'], 2)} "
          f"rmse={v['rmse_pct'] if v['rmse_pct'] is None else round(v['rmse_pct'], 1)}")
