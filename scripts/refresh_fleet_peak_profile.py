"""Re-measure how the real fleet's load peaks scale with consumption and how long they last.

    python -m scripts.refresh_fleet_peak_profile

Reads `vrm.site_samples` (15-minute averages of the load) and writes `calculations/data/fleet_peak_profile.json`, which
`calculations/fleet_peaks.py` reads. A snapshot file (not a live query) because the raw series is ~200 k rows: too slow for a page.
Re-run it every few months or when new sites join the fleet.

What is measured per installation (the fleet lists some installations twice; the longest series is kept):
  - the 99th percentile of the 15-minute load, a power-law fit of it against the average load (peaks fall relative to the average as sites grow);
  - how much of the time the load sits above 3x / 4x its average, and how long such a stretch lasts;
  - the installed inverter against the highest 15-minute load actually seen.
15-minute averages hide second-long motor starts: this is the "sustained peak", not the surge.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "calculations" / "data" / "fleet_peak_profile.json"
MIN_DAYS = 20
MIN_AVG_KW = 0.05
BLOCKS_PER_DAY = 96


def _runs(above: np.ndarray) -> list[int]:
    runs, c = [], 0
    for a in above:
        if a:
            c += 1
        elif c:
            runs.append(c)
            c = 0
    if c:
        runs.append(c)
    return runs


def measure() -> dict:
    from calculations.fleet_peaks import _rows
    from database.supabase_client import get_client

    vrm = get_client().schema("vrm")
    sites = pd.DataFrame(_rows(vrm, "sites", "site_id,display_name,inverter_nominal_kw"))
    s = pd.DataFrame(_rows(vrm, "site_samples", "site_id,ts,load_w,gap"))
    s = s[s.load_w.notna() & (s.gap != True)].copy()                    # noqa: E712
    s["ts"] = pd.to_datetime(s.ts)
    s["kw"] = s.load_w.astype(float) / 1000.0

    rows = []
    for sid, g in s.groupby("site_id"):
        g = g.sort_values("ts")
        if len(g) < BLOCKS_PER_DAY * MIN_DAYS:
            continue
        avg = float(g.kw.mean())
        if avg < MIN_AVG_KW:
            continue
        r = {"site_id": sid, "days": len(g) / BLOCKS_PER_DAY, "avg_kw": avg, "max_kw": float(g.kw.max()), "p99_kw": float(g.kw.quantile(0.99))}
        for k in (3, 4):
            above = (g.kw > k * avg).values
            runs = _runs(above)
            r[f"time{k}"] = float(above.mean() * 100)
            r[f"run{k}_p95_h"] = float(np.percentile(runs, 95) * 0.25) if runs else 0.0
        rows.append(r)
    d = pd.DataFrame(rows).merge(sites, on="site_id", how="left").sort_values("days", ascending=False).drop_duplicates("display_name")
    if len(d) < 8:
        raise SystemExit(f"only {len(d)} usable installations — not enough to fit a profile")

    b, a = np.polyfit(np.log(d.avg_kw), np.log(d.p99_kw), 1)
    resid = np.log(d.p99_kw) - (a + b * np.log(d.avg_kw))
    inv = d.dropna(subset=["inverter_nominal_kw"])
    inv = inv[inv.inverter_nominal_kw > 0]
    return {
        "as_of": date.today().isoformat(),
        "source": "vrm.site_samples, 15-minute load averages",
        "n_sites": int(len(d)),
        "days_median": round(float(d.days.median()), 0),
        "fit": {"a": round(float(np.exp(a)), 4), "b": round(float(b), 4), "resid_sd_log": round(float(resid.std()), 4),
                "avg_kw_min": round(float(d.avg_kw.min()), 3), "avg_kw_max": round(float(d.avg_kw.max()), 3)},
        "duration": {f"{k}x": {"time_pct": round(float(d[f"time{k}"].median()), 1), "run_p95_h": round(float(d[f"run{k}_p95_h"].median()), 2)} for k in (3, 4)},
        "inverter_over_max": {"n": int(len(inv)), "median": round(float((inv.inverter_nominal_kw / inv.max_kw).median()), 2)} if len(inv) else None,
    }


if __name__ == "__main__":
    prof = measure()
    OUT.write_text(json.dumps(prof, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(json.dumps(prof, indent=2))
