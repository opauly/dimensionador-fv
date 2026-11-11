"""How high the real fleet's load peaks above its own average — a measured reference for every "peak kW" the wizard estimates.

The wizard turns a load list into a design peak with per-category demand factors (calculations/load_profile_off_grid.py,
first-pass values). Those factors cannot be checked against the fleet directly (the monitored sites have no nameplate list),
but the fleet does record each day's peak load (`vrm.energy_daily.peak_load_w`) next to the day's energy, so what CAN be
measured is peak / average power. Per installation we take the mean daily peak and the 95th-percentile daily peak, both
divided by the average power; the medians across installations are the fleet's typical and design-level ratios.

Informational only: it never changes a sizing result by itself. Best-effort — any failure just means "no fleet data".
"""
from __future__ import annotations

import statistics
import time

MIN_SITES = 6          # installations needed before the number is shown / used
MIN_DAYS = 30          # complete days with a peak reading per installation
MIN_AVG_KW = 0.05      # ignore almost-idle sites: their ratio says nothing
FALLBACK_TYPICAL = 3.0  # what the wizard assumed before it could be measured (peak = 3 x average)
_TTL_S = 3600
_cache: dict = {}


def _rows(vrm, table: str, columns: str) -> list[dict]:
    out, start = [], 0
    while True:
        chunk = vrm.table(table).select(columns).range(start, start + 999).execute().data or []
        out += chunk
        if len(chunk) < 1000:
            return out
        start += 1000


def _measure() -> dict | None:
    import pandas as pd

    from database.supabase_client import get_client

    vrm = get_client().schema("vrm")
    names = {s["site_id"]: s["display_name"] for s in vrm.table("sites").select("site_id,display_name").execute().data}
    ed = pd.DataFrame(_rows(vrm, "energy_daily", "site_id,date,load_kwh,peak_load_w,complete_day"))
    if ed.empty:
        return None
    ed = ed[(ed.complete_day == True) & ed.peak_load_w.notna() & ed.load_kwh.notna()]       # noqa: E712
    ed = ed.drop_duplicates(["site_id", "date"]).copy()
    ed["peak_kw"] = ed.peak_load_w.astype(float) / 1000.0
    ed["avg_kw"] = ed.load_kwh.astype(float) / 24.0
    ed = ed[ed.avg_kw > MIN_AVG_KW]

    best: dict[str, tuple[int, float, float]] = {}      # the fleet lists some installations twice: keep the longest series
    for sid, g in ed.groupby("site_id"):
        if len(g) < MIN_DAYS:
            continue
        avg = float(g.avg_kw.mean())
        row = (len(g), float(g.peak_kw.mean()) / avg, float(g.peak_kw.quantile(0.95)) / avg)
        name = names.get(sid) or sid
        if name not in best or row[0] > best[name][0]:
            best[name] = row
    if len(best) < MIN_SITES:
        return None
    typical = [r[1] for r in best.values()]
    design = [r[2] for r in best.values()]
    return {"n": len(best), "typical": statistics.median(typical), "design": statistics.median(design),
            "design_range": (min(design), max(design))}


def fleet_peak_ratios() -> dict | None:
    """{"n", "typical": mean daily peak / avg, "design": 95th-pct daily peak / avg, "design_range": (lo, hi)} or None."""
    hit = _cache.get("v")
    if hit and time.time() - hit[0] < _TTL_S:
        return hit[1]
    try:
        val = _measure()
    except Exception:                                   # noqa: BLE001 — informational
        val = None
    _cache["v"] = (time.time(), val)
    return val


def typical_peak_ratio() -> float:
    """Peak / average power for a typical day: the fleet's median, or the historical 3.0 while it cannot be measured."""
    fp = fleet_peak_ratios()
    return round(fp["typical"], 1) if fp else FALLBACK_TYPICAL


def expected_peak_kw(daily_kwh: float) -> dict | None:
    """What the fleet's measurements say the peak of a home using `daily_kwh` a day looks like:
    {"design_kw" (median 95th-pct peak), "range_kw" (lowest / highest site), "n"}; None without fleet data."""
    fp = fleet_peak_ratios()
    if not fp or not daily_kwh or daily_kwh <= 0:
        return None
    avg = float(daily_kwh) / 24.0
    lo, hi = fp["design_range"]
    return {"design_kw": avg * fp["design"], "range_kw": (avg * lo, avg * hi), "n": fp["n"]}


def clear_cache() -> None:
    _cache.clear()
