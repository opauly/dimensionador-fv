"""Reference class from the monitored fleet (vrm-monitor's `vrm` schema, same Supabase project).

The wizard's equipment-free targets come from formulas calibrated on a handful of sites. This module answers the
complementary question with REAL data: "what did sites like this one actually need, and how did they behave?"

  site rows + daily energy rows + anomaly rows  --compute_site_stats()-->  one dict per site (pure, testable)
  fleet stats + a daily-kWh target             --reference_class()----->  comparable sites, health verdicts and a
                                                                           suggested kWp / battery kWh

Pure functions take plain lists of dicts; `load_fleet()` is the only part that touches the database. Nothing here
writes anything.

Health vocabulary (thresholds from docs/design-calibration-2026-08.md §3, deliberately reused, not re-fitted):
  * equivalent full cycles/day  healthy 0.4-0.7, < 0.2 over-built, > 0.9 under-built
  * "stressed"  = the bank went below 20% SoC on more than 10% of the complete days it was observed
  * "sobredimensionado" = the bank cycles < 0.2/day while the site is self-supplying (capex that never becomes kWh)
  * "respaldo"  = the bank cycles < 0.2/day but the site still buys >= 30% of its energy: backup-only use, no verdict
Only days flagged `complete_day` (or with >= 20 h of coverage) count, so a monitoring outage never reads as a fault.

Every number comes with `n` (how many sites back it). With fewer than MIN_SITES_FOR_SUGGESTION healthy comparable
sites no suggestion is made — the honest answer is "not enough comparable sites yet".
"""
from __future__ import annotations

import statistics
import time
from typing import Iterable

MIN_DAYS = 30                      # a site needs this many usable days to be a reference
MIN_SITES_FOR_SUGGESTION = 2   # below ~3 the suggestion is flagged confidence "baja"
LOW_SOC_PCT = 20.0
STRESSED_LOW_SOC_DAYS_PCT = 10.0
CYCLES_HEALTHY = (0.4, 0.7)
CYCLES_IDLE_BELOW = 0.2
CYCLES_UNDERBUILT_ABOVE = 0.9
_REFERENCE_DOD = 0.80              # same reference DoD design_targets uses when a bank's own DoD is unknown


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _usable_days(energy_rows: Iterable[dict]) -> list[dict]:
    """Days we can trust: positive load, and a complete day (explicit flag, else >= 20 h covered, else assume yes
    when the pipeline never recorded coverage at all)."""
    out = []
    for r in energy_rows:
        load = _f(r.get("load_kwh"))
        if not load or load <= 0:
            continue
        complete = r.get("complete_day")
        hours = _f(r.get("hours_covered"))
        if complete is False or (complete is None and hours is not None and hours < 20):
            continue
        out.append(r)
    return out


def _nominal_kwh(site: dict, energy_rows: list[dict]) -> float | None:
    nominal = _f(site.get("battery_nominal_kwh"))
    if nominal and nominal > 0:
        return nominal
    usable = _f(site.get("battery_usable_kwh"))
    if usable and usable > 0:
        dod = _f(site.get("battery_dod_pct"))
        return usable / ((dod / 100.0) if dod and dod > 0 else _REFERENCE_DOD)
    snaps = [_f(r.get("battery_kwh_snapshot")) for r in energy_rows]
    snaps = [s for s in snaps if s and s > 0]
    return max(snaps) if snaps else None


def _kwp(site: dict, energy_rows: list[dict]) -> float | None:
    kwp = _f(site.get("pv_kwp"))
    if kwp and kwp > 0:
        return kwp
    snaps = [_f(r.get("pv_kwp_snapshot")) for r in energy_rows]
    snaps = [s for s in snaps if s and s > 0]
    return max(snaps) if snaps else None


def compute_site_stats(site: dict, energy_rows: list[dict], anomalies: list[dict] | None = None) -> dict | None:
    """Everything the reference class needs from one site, or None when the site has too little usable data."""
    days = _usable_days(energy_rows)
    if len(days) < MIN_DAYS:
        return None
    loads = [_f(r["load_kwh"]) for r in days]
    avg_load = statistics.fmean(loads)
    kwp, nominal = _kwp(site, energy_rows), _nominal_kwh(site, energy_rows)

    pv = [_f(r.get("pv_kwh")) for r in days if _f(r.get("pv_kwh")) is not None]
    avg_pv = statistics.fmean(pv) if pv else None
    grid = [(_f(r.get("grid_kwh")), _f(r["load_kwh"])) for r in days if _f(r.get("grid_kwh")) is not None]
    grid_share = (sum(g for g, _ in grid) / sum(l for _, l in grid)) if grid and sum(l for _, l in grid) > 0 else None

    min_soc = [_f(r.get("min_soc")) for r in days if _f(r.get("min_soc")) is not None]
    low_soc_pct = (100.0 * sum(1 for m in min_soc if m < LOW_SOC_PCT) / len(min_soc)) if min_soc else None
    float_days = [bool(r.get("battery_reached_float")) for r in days if r.get("battery_reached_float") is not None]
    float_pct = (100.0 * sum(float_days) / len(float_days)) if float_days else None

    discharge = [_f(r.get("battery_discharge_kwh")) for r in days if _f(r.get("battery_discharge_kwh")) is not None]
    cycles = None
    if discharge and nominal:
        cycles = statistics.fmean(discharge) / (nominal * _REFERENCE_DOD)   # equivalent full cycles/day

    outage_min = [_f(r.get("outage_minutes")) or 0.0 for r in days]
    sorted_loads = sorted(loads)
    p90_load = sorted_loads[min(len(sorted_loads) - 1, int(0.9 * len(sorted_loads)))]

    an = anomalies or []
    verdict = "sin datos de batería"
    if nominal and kwp and low_soc_pct is not None:
        if low_soc_pct > STRESSED_LOW_SOC_DAYS_PCT or (cycles is not None and cycles > CYCLES_UNDERBUILT_ABOVE):
            verdict = "estresado"
        elif cycles is not None and cycles < CYCLES_IDLE_BELOW:
            # An idle bank on a site that still buys most of its energy is backup-only use, not an over-built system.
            verdict = "respaldo" if (grid_share is not None and grid_share >= 0.30) else "sobredimensionado"
        else:
            verdict = "sano"

    return {
        "site_id": str(site.get("site_id")), "name": site.get("display_name") or str(site.get("site_id")),
        "system_type": site.get("system_type"), "exports_to_grid": site.get("exports_to_grid"),
        "latitude": _f(site.get("latitude")), "longitude": _f(site.get("longitude")),
        "days": len(days), "avg_load_kwh": avg_load, "p90_load_kwh": p90_load, "avg_pv_kwh": avg_pv,
        "kwp": kwp, "battery_nominal_kwh": nominal,
        "kwp_per_kwh_day": (kwp / avg_load) if kwp else None,
        "battery_per_kwh_day": (nominal / avg_load) if nominal else None,
        "specific_yield": (avg_pv / kwp) if (kwp and avg_pv is not None) else None,
        "grid_share": grid_share, "low_soc_days_pct": low_soc_pct, "float_days_pct": float_pct,
        "cycles_per_day": cycles, "avg_outage_min_day": statistics.fmean(outage_min) if outage_min else None,
        "anomaly_types": sorted({a.get("anomaly_type") for a in an if a.get("anomaly_type")}),
        "anomaly_count": len(an), "verdict": verdict,
    }


def _quantiles(values: list[float]) -> dict | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    q = (lambda p: vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))])
    return {"n": len(vals), "p25": q(0.25), "median": statistics.median(vals), "p75": q(0.75), "min": vals[0], "max": vals[-1]}


def reference_class(stats: list[dict], *, system_type: str, daily_kwh: float, window: float = 2.0) -> dict:
    """Comparable sites (same system type, load within [1/window, window] x daily_kwh; widened once if too few),
    their health, and — only when enough healthy sites exist — a data-backed kWp / battery suggestion."""
    same = _unique_systems([s for s in stats if s["system_type"] == system_type])

    def pick(w):
        return [s for s in same if daily_kwh / w <= s["avg_load_kwh"] <= daily_kwh * w]

    comparable, used_window = pick(window), window
    if len([s for s in comparable if s["kwp"] and s["battery_nominal_kwh"]]) < MIN_SITES_FOR_SUGGESTION:
        comparable, used_window = pick(window * 1.6), window * 1.6
    full = [s for s in comparable if s["kwp"] and s["battery_nominal_kwh"]]
    healthy = [s for s in full if s["verdict"] == "sano"]

    out = {
        "system_type": system_type, "daily_kwh": daily_kwh, "window": used_window,
        "same_type_sites": len(same), "comparable": comparable, "with_sizing": len(full), "healthy": len(healthy),
        "verdicts": {v: sum(1 for s in full if s["verdict"] == v) for v in ("sano", "estresado", "sobredimensionado", "respaldo")},
        "load_range": _quantiles([s["avg_load_kwh"] for s in comparable]),
        "specific_yield": _quantiles([s["specific_yield"] for s in full]),
        "grid_share": _quantiles([s["grid_share"] for s in comparable]),
        "anomaly_types": _count_types(comparable),
        "suggestion": None,
        "note": None,
    }
    if len(healthy) >= MIN_SITES_FOR_SUGGESTION:
        kq = _quantiles([s["kwp_per_kwh_day"] for s in healthy])
        bq = _quantiles([s["battery_per_kwh_day"] for s in healthy])
        out["suggestion"] = {
            "n": len(healthy), "confidence": _confidence(len(healthy)), "kwp_per_kwh_day": kq, "battery_per_kwh_day": bq,
            "kwp": {"p25": kq["p25"] * daily_kwh, "median": kq["median"] * daily_kwh, "p75": kq["p75"] * daily_kwh},
            "battery_nominal_kwh": {"p25": bq["p25"] * daily_kwh, "median": bq["median"] * daily_kwh, "p75": bq["p75"] * daily_kwh},
        }
    else:
        out["note"] = (f"Solo {len(healthy)} sistema(s) sano(s) comparable(s) con kWp y batería registrados "
                       f"(se necesitan {MIN_SITES_FOR_SUGGESTION}); no se sugiere un tamaño.")
    return out


def _unique_systems(sites: list[dict]) -> list[dict]:
    """The fleet lists some installations twice (identical kWp / battery / load). Count each physical system once,
    keeping the listing with the most days, so a duplicate never counts as independent evidence."""
    best: dict[tuple, dict] = {}
    for s in sites:
        key = (s["system_type"], s["kwp"], s["battery_nominal_kwh"], round(s["avg_load_kwh"] / 3.0)) if s["kwp"] else (s["site_id"],)
        if key not in best or s["days"] > best[key]["days"]:
            best[key] = s
    return list(best.values())


def _confidence(n: int) -> str:
    return "alta" if n >= 5 else "media" if n >= 3 else "baja"


def _count_types(sites: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for s in sites:
        for t in s["anomaly_types"]:
            counts[t] = counts.get(t, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


# ── database loader (read-only) ──────────────────────────────────────────

_ENERGY_COLS = ("site_id,date,load_kwh,pv_kwh,grid_kwh,battery_discharge_kwh,min_soc,battery_reached_float,"
                "outage_minutes,complete_day,hours_covered,pv_kwp_snapshot,battery_kwh_snapshot")
_SITE_COLS = ("site_id,display_name,system_type,pv_kwp,battery_nominal_kwh,battery_usable_kwh,battery_dod_pct,"
              "exports_to_grid,latitude,longitude")
_CACHE: dict = {"at": 0.0, "stats": None}
CACHE_SECONDS = 6 * 3600


def _fetch_all(table, columns: str, page: int = 1000) -> list[dict]:
    rows, start = [], 0
    while True:
        chunk = table.select(columns).range(start, start + page - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < page:
            return rows
        start += page


def load_fleet(force: bool = False) -> list[dict]:
    """Per-site stats for every site with enough data, cached in-process for CACHE_SECONDS."""
    if not force and _CACHE["stats"] is not None and time.time() - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["stats"]
    from database.supabase_client import get_client

    vrm = get_client().schema("vrm")
    sites = _fetch_all(vrm.table("sites"), _SITE_COLS)
    energy = _fetch_all(vrm.table("energy_daily"), _ENERGY_COLS)
    try:
        anomalies = _fetch_all(vrm.table("site_anomalies"), "site_id,anomaly_type")
    except Exception:
        anomalies = []

    by_site: dict[str, list[dict]] = {}
    for r in energy:
        by_site.setdefault(str(r["site_id"]), []).append(r)
    an_by_site: dict[str, list[dict]] = {}
    for a in anomalies:
        an_by_site.setdefault(str(a["site_id"]), []).append(a)

    stats = []
    for site in sites:
        sid = str(site["site_id"])
        st = compute_site_stats(site, by_site.get(sid, []), an_by_site.get(sid, []))
        if st:
            stats.append(st)
    _CACHE.update(at=time.time(), stats=stats)
    return stats
