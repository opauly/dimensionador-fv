"""Check the wizard's physical assumptions against what the real fleet measures (reads the live Supabase fleet tables).

    .venv/bin/python -m scripts.fleet_calibration

Two measurements, each with how many installations it rests on:
  1. PV derating — real kWh/kWp on clear-of-curtailment days relative to PVGIS (the wizard applies a 0.80 derating on top of PVGIS,
     which already carries 14 % system losses). Only days where the battery was nowhere near full count: otherwise the charge
     controller throttles the array and the day says nothing about the panels.
  2. Battery round-trip efficiency — energy discharged / energy charged over the window, corrected by the change in stored energy
     (the wizard uses 0.92 in its day-by-day simulation and 0.96 in the closed-form sizing).
It only reports; the wizard's constants are changed by hand when the evidence is strong enough (see the "needs" lines).
"""
from __future__ import annotations

import calendar
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PV_DERATING_WIZARD = 0.80
BATTERY_EFF_SIM, BATTERY_EFF_FORMULA = 0.92, 0.96
MIN_SITES_TO_CHANGE = 6


def _rows(vrm, table: str, columns: str) -> list[dict]:
    out, start = [], 0
    while True:
        chunk = vrm.table(table).select(columns).range(start, start + 999).execute().data or []
        out += chunk
        if len(chunk) < 1000:
            return out
        start += 1000


def pv_derating(vrm, sites: dict, weather: dict) -> list[tuple]:
    import pandas as pd

    from calculations import pvgis

    ed = pd.DataFrame(_rows(vrm, "energy_daily", "site_id,date,pv_kwh,complete_day,battery_reached_float,max_soc"))
    ed["date"] = pd.to_datetime(ed["date"])
    ed = ed[ed.complete_day == True].drop_duplicates(["site_id", "date"])        # noqa: E712
    out, seen = [], set()
    for sid, g in ed.groupby("site_id"):
        s = sites.get(sid)
        if not s or not s.get("latitude") or not s.get("pv_kwp"):
            continue
        kwp = float(s["pv_kwp"])
        key = (s["display_name"], len(g), kwp)
        if key in seen:                                   # the fleet lists some installations twice
            continue
        seen.add(key)
        w = weather.get((round(float(s["latitude"]), 2), round(float(s["longitude"]), 2)))
        if w is None:
            continue
        local = w.copy()
        local.index = local.index.tz_convert("Etc/GMT+6")
        ghi_day = local.resample("D").sum() / 1000.0
        ghi_day.index = ghi_day.index.tz_localize(None)
        em = pvgis.fetch_irradiance(float(s["latitude"]), float(s["longitude"]))["monthly_kwh_kwp"]
        g = g.copy()
        g["ghi"] = g.date.map(ghi_day)
        g = g.dropna(subset=["ghi"])
        g["real"] = g.pv_kwh.astype(float) / kwp
        g["pvgis"] = [em[d.month - 1] / calendar.monthrange(d.year, d.month)[1] for d in g.date]
        ok = g[(g.real > 0.3) & (g.ghi > 3.5) & (g.max_soc.astype(float) < 85) & (g.battery_reached_float == False)]   # noqa: E712
        if len(ok) < 8:
            continue
        out.append((s["display_name"], s["system_type"], len(ok), float((ok.real / ok.ghi).median() / (ok.pvgis.mean() / ok.ghi.mean()))))
    return out


def battery_efficiency(vrm, sites: dict) -> list[tuple]:
    import pandas as pd

    ed = pd.DataFrame(_rows(vrm, "energy_daily", "site_id,date,complete_day,battery_charge_kwh,battery_discharge_kwh,avg_soc"))
    ed = ed[ed.complete_day == True].drop_duplicates(["site_id", "date"]).copy()     # noqa: E712
    for c in ("battery_charge_kwh", "battery_discharge_kwh", "avg_soc"):
        ed[c] = ed[c].astype(float)
    out, seen = [], set()
    for sid, g in ed.groupby("site_id"):
        s = sites.get(sid)
        if not s or not s.get("battery_nominal_kwh"):
            continue
        key = (s["display_name"], len(g))
        if key in seen:
            continue
        seen.add(key)
        g = g.sort_values("date").dropna(subset=["battery_charge_kwh", "battery_discharge_kwh"])
        charge, discharge = g.battery_charge_kwh.sum(), g.battery_discharge_kwh.sum()
        if len(g) < 30 or charge < 50:                    # a bank that barely cycled says nothing about efficiency
            continue
        d_stored = (g.avg_soc.tail(3).mean() - g.avg_soc.head(3).mean()) / 100.0 * float(s["battery_nominal_kwh"])
        eff = (discharge + d_stored) / charge
        if 0.80 < eff < 1.02:
            out.append((s["display_name"], s["system_type"], len(g), eff))
    return out


def _per_installation(rows: list[tuple]) -> list[tuple]:
    """The fleet lists some installations twice (two ids): one row per name, the mean of its values."""
    by_name: dict[str, list[tuple]] = {}
    for r in rows:
        by_name.setdefault(r[0], []).append(r)
    return [(n, rs[0][1], sum(x[2] for x in rs), statistics.mean(x[3] for x in rs)) for n, rs in by_name.items()]


def _summary(label: str, rows: list[tuple], wizard: str) -> None:
    rows = _per_installation(rows)
    vals = sorted(r[3] for r in rows)
    print(f"\n{label}\n  installations: {len(vals)}   wizard uses: {wizard}")
    for r in sorted(rows, key=lambda r: r[3]):
        print(f"    {r[0]:<38} {r[1]:<9} {r[2]:>4} days   {r[3]:.3f}")
    if vals:
        print(f"  fleet median: {statistics.median(vals):.3f}   range {vals[0]:.3f}-{vals[-1]:.3f}")
        print(f"  needs >= {MIN_SITES_TO_CHANGE} installations to change a constant: {'enough' if len(vals) >= MIN_SITES_TO_CHANGE else 'not enough yet'}")


def main() -> int:
    from calculations import fleet_simulation as fs
    from database.supabase_client import get_client

    vrm = get_client().schema("vrm")
    sites = {s["site_id"]: s for s in vrm.table("sites").select("site_id,display_name,system_type,pv_kwp,battery_nominal_kwh,latitude,longitude").execute().data}
    ds = fs.get_dataset()
    if not ds:
        print("fleet dataset not ready yet — run again in a minute")
        return 1
    _summary("PV derating vs PVGIS (uncurtailed days only)", pv_derating(vrm, sites, ds["weather"]), f"{PV_DERATING_WIZARD:.2f}")
    _summary("Battery round-trip efficiency", battery_efficiency(vrm, sites), f"{BATTERY_EFF_SIM:.2f} (daily sim) / {BATTERY_EFF_FORMULA:.2f} (formulas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
