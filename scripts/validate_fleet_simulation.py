"""Sanity checks for calculations/fleet_simulation.py on synthetic data (no database needed).

    .venv/bin/python scripts/validate_fleet_simulation.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np

from calculations import fleet_simulation as fs

fails = 0


def check(name, cond):
    global fails
    print(("  ok   " if cond else "  FAIL ") + name)
    fails += 0 if cond else 1


def scenario(days=12, sun=True, flat=True):
    T = days * 24
    hour = np.arange(T) % 24
    ghi = np.where((hour >= 7) & (hour <= 16), 0.8, 0.0)[None, :] * (1.0 if sun else 0.0)
    unit = (np.ones(T) / 24.0)[None, :] if flat else np.where((hour >= 17) | (hour <= 5), 1 / 12.0, 0.0)[None, :]
    counted = np.ones((1, days), dtype=bool)
    counted[:, :fs.WARMUP_DAYS] = False
    return {"ghi": ghi, "unit": unit, "counted": counted, "n_days": days, "n": 1}


floors = np.array([10.0])
sc = scenario()
r = fs._run(sc, 0.72, 10.0, np.array([8.0, 8.0, 8.0]), np.array([5.0, 15.0, 40.0]), floors)
check("a bigger battery never fails more days", r["fail_pct"][0, 0] >= r["fail_pct"][0, 1] >= r["fail_pct"][0, 2])
check("a 5 kWh battery cannot carry a 10 kWh/day flat load", r["fail_pct"][0, 0] > 50)
check("a 40 kWh battery with 8 kWp carries it without failing", r["fail_pct"][0, 2] == 0)

dark = scenario(sun=False)
r2 = fs._run(dark, 0.72, 10.0, np.array([8.0]), np.array([20.0]), floors)
check("with no sun a 20 kWh bank (18 kWh above the floor) fails once ~2 days of load are gone", r2["fail_pct"][0, 0] > 60)

r3 = fs._run(sc, 0.72, 10.0, np.array([2.0, 8.0, 20.0]), np.array([30.0, 30.0, 30.0]), floors)
check("more panels never fail more days", r3["fail_pct"][0, 0] >= r3["fail_pct"][0, 1] >= r3["fail_pct"][0, 2])

zero = fs._run(sc, 0.72, 0.001, np.array([8.0]), np.array([5.0]), floors)
check("a negligible load never fails", zero["fail_pct"][0, 0] == 0)

r4 = fs._run(sc, 0.72, 10.0, np.array([8.0, 8.0]), np.array([20.0, 20.0]), np.array([10.0, 50.0]))
check("a higher reserve floor never fails fewer days", r4["fail_pct"][1, 0] >= r4["fail_pct"][0, 0])

soc = fs._replay_soc(np.zeros(48), np.full(48, 0.5), 10.0, 100.0, 10.0)
check("replay: an empty-sun day drains the bank but never below the floor", soc.min() >= 10.0 - 1e-9 and soc[-1] < soc[0])

print("\nFAILED" if fails else "\nall passed")
sys.exit(1 if fails else 0)
