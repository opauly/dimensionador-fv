"""Design an off-grid battery by replaying REAL conditions: real sunlight and real daily load patterns from the monitored fleet.

The formula in `design_targets` says what a battery should be in theory; this module says what actually happens to a battery of a
given size when it lives through the weather the fleet lived through and loads shaped like the fleet's loads.

How it works
  1. Data (vrm-monitor tables, read-only): 15-minute samples per site (`vrm.site_samples`) and hourly weather per location
     (`vrm.weather_hourly`). Only sites with kWp, battery and system type registered are used (same rule as `fleet_reference`).
  2. Solar response `k` (kW per kWp per kW/m2 of sunlight) is calibrated on off-grid sites where a replay of the site with its own
     panels and battery reproduces its real battery level (correlation >= MIN_CORR, RMSE <= MAX_RMSE_PCT). No such sites -> no
     simulation (we never fall back to a guessed `k`).
  3. A scenario = one weather location x one site's hourly load pattern, scaled so its mean day equals the requested kWh/day.
  4. Each scenario is run hour by hour (battery balance with round-trip and inverter efficiency); a local day "fails" when any
     energy is left unserved. Reported: % of failing days and the longest run of failing days.

Hybrid systems (`design_hybrid`) use the same engine with the grid as the fallback: the battery serves the load down to the
reserve and the grid covers the rest, so the questions are different: how much of the load solar+battery covers, how many nights
the battery lasts until sunrise, and how many REAL grid outages (`vrm.grid_events`) it would have outlasted. A hybrid replay
under-states grid import (real sites import more than an ideal dispatch), so the gap measured on cycling hybrids is reported next to it.

Limits (stated in the UI): daily-scale weather is the fleet's own window (~90 days, rainy season); the load SHAPE comes from other
customers; the model is hourly, so very short peaks are not seen.

The hourly dataset is built from ~100k database rows, so it is cached on disk (`.cache/fleet_sim.pkl`) and rebuilt in the background
when older than STALE_HOURS; `get_dataset()` never blocks a page on a rebuild.
"""
from __future__ import annotations

import logging
import pickle
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parent.parent / ".cache" / "fleet_sim.pkl"
STALE_HOURS = 24
DATASET_VERSION = 2              # bump when the cached dataset gains fields; older caches are rebuilt in the background
LOCAL_UTC_OFFSET_H = -6          # Costa Rica / the fleet's region (no daylight saving)
SHIFT_MIN = 60                   # site bucket start -> hour-ending label, matches Open-Meteo's "average of the preceding hour"
ETA_CHARGE = ETA_DISCHARGE = 0.975   # sqrt of the 0.95 round-trip default used by design_targets
ETA_INVERTER = 0.96
PHYSICAL_FLOOR_PCT = 10.0        # lowest level the fleet's off-grid banks really reach
TARGET_FAIL_PCT = 2.0            # at most this share of days with unserved energy
TARGET_STREAK_DAYS = 2           # and the 90th-percentile longest run of such days at most this
FAIL_KWH = 0.05                  # a day counts as failing above this much unserved energy
WARMUP_DAYS = 2
MIN_OVERLAP_DAYS = 20
MIN_CORR, MAX_RMSE_PCT = 0.65, 10.0
MIN_CALIBRATION_SITES = 2
NIGHT_TARGET_PCT = 90.0          # hybrid: the battery should carry the whole night (18:00-06:00) on at least this share of nights
OUTAGE_TARGET_PCT = 90.0         # hybrid: ...and outlast at least this share of real grid outages
NIGHT_START_H, NIGHT_END_H = 18, 6
OUTAGE_MIN_MIN, OUTAGE_MAX_H = 15, 72   # outages shorter than 15 min are noise; longer than 3 days no battery is designed for
MIN_OUTAGES = 8
HYBRID_MIN_CORR = 0.65

_lock = threading.Lock()
_state: dict = {"ds": None, "loaded_at": 0.0, "building": False}


# ── dataset (database → hourly series), cached ───────────────────────────

def _fetch_samples(vrm, site_id: str, page: int = 1000) -> list[dict]:
    rows, start = [], 0
    while True:
        chunk = (vrm.table("site_samples").select("ts,pv_w,load_w,battery_w,soc_pct,grid_w")
                 .eq("site_id", site_id).order("ts").range(start, start + page - 1).execute().data or [])
        rows.extend(chunk)
        if len(chunk) < page:
            return rows
        start += page


def _hourly(df: pd.DataFrame) -> pd.DataFrame:
    x = df[[c for c in ("pv_w", "load_w", "soc_pct", "grid_w") if c in df.columns]].copy()
    x.index = x.index + pd.Timedelta(minutes=SHIFT_MIN)
    return x.resample("1h").mean()


def _replay_soc(pv_kwh, load_kwh, nominal, soc0_pct, floor_pct):
    """One site, one battery, hourly — returns the simulated state of charge (%) per hour."""
    soc = np.empty(len(pv_kwh))
    e, lo = nominal * soc0_pct / 100.0, nominal * floor_pct / 100.0
    for i in range(len(pv_kwh)):
        net = pv_kwh[i] - load_kwh[i] / ETA_INVERTER
        if net >= 0:
            e = min(nominal, e + net * ETA_CHARGE)
        else:
            e -= min(-net / ETA_DISCHARGE, max(0.0, e - lo))
        soc[i] = 100.0 * e / nominal
    return soc


def build_dataset() -> dict:
    """Pull the 15-minute samples and weather, reduce to hourly, calibrate and validate the solar response."""
    from database.supabase_client import get_client

    vrm = get_client().schema("vrm")
    sites = vrm.table("sites").select("site_id,display_name,system_type,pv_kwp,battery_nominal_kwh,latitude,longitude").execute().data or []
    hybrid_ids = {s["site_id"] for s in sites if s.get("system_type") == "hybrid"}
    sites = [s for s in sites if s.get("pv_kwp") and s.get("battery_nominal_kwh") and s.get("system_type")]

    wrows, start = [], 0
    while True:
        chunk = (vrm.table("weather_hourly").select("lat,lon,ts,ghi_wm2").order("ts").range(start, start + 999).execute().data or [])
        wrows.extend(chunk)
        if len(chunk) < 1000:
            break
        start += 1000
    w = pd.DataFrame(wrows)
    w["ts"] = pd.to_datetime(w["ts"], utc=True)
    w["lat2"], w["lon2"] = w["lat"].astype(float).round(2), w["lon"].astype(float).round(2)
    weather = {}
    for (la, lo), g in w.groupby(["lat2", "lon2"]):
        s = g.set_index("ts")["ghi_wm2"].sort_index()
        weather[(float(la), float(lo))] = s[~s.index.duplicated()].dropna()

    loads, validation, seen, hybrids = {}, [], set(), []
    for s in sites:
        rows = _fetch_samples(vrm, s["site_id"])
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()
        key = (s["display_name"], len(df), float(s["pv_kwp"]))
        if key in seen:                       # the fleet lists some installations twice
            continue
        seen.add(key)
        h = _hourly(df)
        load = (h["load_w"].dropna() / 1000.0)
        if len(load) >= 24 * MIN_OVERLAP_DAYS and load.sum() / (len(load) / 24.0) >= 1.0:
            loads[s["display_name"]] = load
        if s.get("latitude") is None:
            continue
        ghi = weather.get((round(float(s["latitude"]), 2), round(float(s["longitude"]), 2)))
        if ghi is None:
            continue
        if s["system_type"] == "off_grid":
            validation.append(_validate_site(s, h, ghi))
        elif s["system_type"] == "hybrid" and "grid_w" in h:
            hybrids.append((s, h, ghi))

    ok = [v for v in validation if v["accepted"]]
    k = float(np.median([v["k"] for v in ok])) if len(ok) >= MIN_CALIBRATION_SITES else None
    hyb_val = [_validate_hybrid(s, h, g, k) for s, h, g in hybrids] if k else []
    good = [v for v in hyb_val if v["accepted"]]
    gaps = sorted(v["gap_pts"] for v in good)
    hybrid = {"validation": hyb_val, "accepted": len(good),
              "gap_pts": float(np.median(gaps)) if gaps else None,
              "gap_range": (float(np.percentile(gaps, 25)), float(np.percentile(gaps, 75))) if gaps else None,
              "k_sites": [v["k_site"] for v in hyb_val if v["k_site"]], "outages": _fetch_outages(vrm, hybrid_ids)}
    return {"version": DATASET_VERSION, "built_at": time.time(), "weather": weather, "loads": loads, "k": k, "validation": validation,
            "hybrid": hybrid,
            "window": (min(s.index[0] for s in weather.values()), max(s.index[-1] for s in weather.values()))}


def _fetch_outages(vrm, site_ids: set) -> dict:
    """Real grid outages at the fleet's hybrid sites, in hours. Outages beyond OUTAGE_MAX_H are counted apart (not designed for)."""
    rows, start = [], 0
    while True:
        chunk = vrm.table("grid_events").select("site_id,duration_minutes").range(start, start + 999).execute().data or []
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        start += 1000
    mine = [r for r in rows if r["site_id"] in site_ids and r.get("duration_minutes") is not None and float(r["duration_minutes"]) >= OUTAGE_MIN_MIN]
    hours = [float(r["duration_minutes"]) / 60.0 for r in mine]
    return {"hours": [h for h in hours if h <= OUTAGE_MAX_H], "longer": sum(1 for h in hours if h > OUTAGE_MAX_H),
            "sites": len({r["site_id"] for r in mine})}


def _replay_import(pv_kwh, load_kwh, nominal, soc0_pct, floor_pct):
    """Hybrid replay of one site: battery serves down to `floor`, the grid covers the rest. Returns (grid import kWh, SoC %) per hour."""
    imp, soc = np.zeros(len(pv_kwh)), np.zeros(len(pv_kwh))
    e, lo = nominal * soc0_pct / 100.0, nominal * floor_pct / 100.0
    for i in range(len(pv_kwh)):
        net = pv_kwh[i] - load_kwh[i] / ETA_INVERTER
        if net >= 0:
            e = min(nominal, e + net * ETA_CHARGE)
        else:
            need = -net / ETA_DISCHARGE
            used = min(need, max(0.0, e - lo))
            e -= used
            imp[i] = (need - used) * ETA_DISCHARGE * ETA_INVERTER
        soc[i] = 100.0 * e / nominal
    return imp, soc


def _validate_hybrid(site: dict, h: pd.DataFrame, ghi: pd.Series, k: float) -> dict:
    """Replay a hybrid with the off-grid solar response and its own lowest battery level as floor; compare battery level and grid import.
    Only sites that really cycle their battery (not parked at 100 %) say anything about the dispatch."""
    kwp, nominal = float(site["pv_kwp"]), float(site["battery_nominal_kwh"])
    out = {"name": site["display_name"], "corr": None, "rmse_pct": None, "sim_share": None, "real_share": None, "gap_pts": None,
           "k_site": None, "accepted": False}
    j = h.join(ghi.rename("ghi"), how="inner").dropna(subset=["pv_w", "load_w", "soc_pct", "grid_w", "ghi"])
    if len(j) < 24 * MIN_OVERLAP_DAYS:
        return out
    bright = j[(j.soc_pct < 90) & (j.ghi > 300)]
    if len(bright) >= 50:
        out["k_site"] = float(((bright.pv_w / 1000.0) / (kwp * bright.ghi / 1000.0)).quantile(0.75))
    real_soc = j.soc_pct.values
    load = j.load_w.values / 1000.0
    if load.sum() / (len(j) / 24.0) < 1.0:
        return out
    imp, soc = _replay_import(k * kwp * j.ghi.values / 1000.0, load, nominal, float(real_soc[0]), float(np.percentile(real_soc, 2)))
    real_imp = np.clip(j.grid_w.values, 0, None) / 1000.0
    out["sim_share"], out["real_share"] = 100.0 * imp.sum() / load.sum(), 100.0 * real_imp.sum() / load.sum()
    out["gap_pts"] = out["real_share"] - out["sim_share"]
    out["corr"] = float(pd.Series(soc).corr(pd.Series(real_soc)))
    out["rmse_pct"] = float(np.sqrt(np.mean((soc - real_soc) ** 2)))
    cycles = float(np.percentile(real_soc, 95) - np.percentile(real_soc, 5)) >= 25.0 and out["real_share"] < 60.0
    out["accepted"] = bool(cycles and out["corr"] is not None and out["corr"] >= HYBRID_MIN_CORR)
    return out


def _validate_site(site: dict, h: pd.DataFrame, ghi: pd.Series) -> dict:
    """Calibrate k on bright hours where the battery was not full, then replay the site and compare battery levels."""
    kwp, nominal = float(site["pv_kwp"]), float(site["battery_nominal_kwh"])
    out = {"name": site["display_name"], "k": None, "corr": None, "rmse_pct": None, "accepted": False}
    j = h.join(ghi.rename("ghi"), how="inner").dropna(subset=["pv_w", "load_w", "soc_pct", "ghi"])
    bright = j[(j.soc_pct < 90) & (j.ghi > 300)]
    if len(bright) < 50:
        return out
    ratio = (bright.pv_w / 1000.0) / (kwp * bright.ghi / 1000.0)
    k = float(ratio.quantile(0.75))             # upper quartile = potential, not clipped/throttled hours
    real = j.soc_pct.values
    floor = max(0.0, min(PHYSICAL_FLOOR_PCT, float(real.min()) - 1.0))
    sim = _replay_soc(k * kwp * j.ghi.values / 1000.0, j.load_w.values / 1000.0, nominal, float(real[0]), floor)
    corr = float(pd.Series(sim).corr(pd.Series(real)))
    rmse = float(np.sqrt(np.mean((sim - real) ** 2)))
    out.update(k=k, corr=corr, rmse_pct=rmse, accepted=bool(corr >= MIN_CORR and rmse <= MAX_RMSE_PCT))
    return out


def _save(ds: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(ds, fh)
    tmp.replace(CACHE_PATH)


def refresh(blocking: bool = True) -> None:
    """Rebuild the dataset and write the cache. `blocking=False` does it on a background thread."""
    def work():
        try:
            ds = build_dataset()
            _save(ds)
            with _lock:
                _state.update(ds=ds, loaded_at=time.time())
        except Exception:                                   # noqa: BLE001 — best effort, the card just stays hidden
            log.warning("fleet_simulation: could not rebuild the dataset", exc_info=True)
        finally:
            with _lock:
                _state["building"] = False

    with _lock:
        if _state["building"]:
            return
        _state["building"] = True
    if blocking:
        work()
    else:
        threading.Thread(target=work, daemon=True, name="fleet-sim-refresh").start()


def get_dataset() -> dict | None:
    """The cached dataset (memory, then disk), or None while none exists. Starts a background rebuild when missing or stale."""
    with _lock:
        ds = _state["ds"]
    if ds is None and CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "rb") as fh:
                ds = pickle.load(fh)
            with _lock:
                _state.update(ds=ds, loaded_at=time.time())
        except Exception:                                   # noqa: BLE001
            ds = None
    if ds is None or ds.get("version") != DATASET_VERSION or time.time() - ds["built_at"] > STALE_HOURS * 3600:
        refresh(blocking=False)
    return ds


# ── the simulation ───────────────────────────────────────────────────────

def _scenarios(ds: dict) -> dict | None:
    """Stack every (weather location x load pattern) pair onto one local-midnight-aligned hourly grid."""
    weather, loads = ds["weather"], ds["loads"]
    if not weather or not loads:
        return None
    first = min(min(s.index[0] for s in weather.values()), min(s.index[0] for s in loads.values()))
    last = max(max(s.index[-1] for s in weather.values()), max(s.index[-1] for s in loads.values()))
    shift = pd.Timedelta(hours=LOCAL_UTC_OFFSET_H)
    day0 = (first + shift).floor("D") - shift
    n_days = int(np.ceil((last - day0) / pd.Timedelta(days=1))) + 1
    index = pd.date_range(day0, periods=n_days * 24, freq="1h")
    ghi_by_loc = {k: s.reindex(index).values for k, s in weather.items()}
    load_by_site = {k: s.reindex(index).values / (s.sum() / (len(s) / 24.0)) for k, s in loads.items()}   # kW per (kWh/day)
    ghi, unit, names = [], [], []
    for (loc, g), (name, l) in [(a, b) for a in ghi_by_loc.items() for b in load_by_site.items()]:
        ok = ~np.isnan(g) & ~np.isnan(l)
        if ok.sum() < 24 * MIN_OVERLAP_DAYS:
            continue
        ghi.append(np.where(ok, g, 0.0) / 1000.0)            # kW/m2
        unit.append(np.where(ok, l, 0.0))
        names.append((loc, name, ok))
    if not ghi:
        return None
    ghi, unit = np.array(ghi), np.array(unit)
    valid = np.array([o for _, _, o in names])
    day_ok = valid.reshape(len(names), n_days, 24).all(axis=2)
    counted = day_ok & (np.cumsum(day_ok, axis=1) > WARMUP_DAYS)
    return {"ghi": ghi, "unit": unit, "counted": counted, "valid": valid, "n_days": n_days, "n": len(names),
            "locations": len({n[0] for n in names}), "patterns": len({n[1] for n in names}), "index": index}


def _run(sc: dict, k: float, daily_kwh: float, kwp: np.ndarray, batt: np.ndarray, floors: np.ndarray) -> dict:
    """Hour-by-hour balance for P (kWp, battery) pairs x F floors x S scenarios. Returns failing-day % and 90th-pct longest run."""
    S, T = sc["ghi"].shape
    P, F = len(kwp), len(floors)
    kwp3, nom3 = kwp[None, :, None], batt[None, :, None]
    lo = nom3 * (floors[:, None, None] / 100.0)
    e = np.broadcast_to(nom3, (F, P, S)).copy()
    uns_day = np.zeros((F, P, S, sc["n_days"]))
    for t in range(T):
        pv = k * kwp3 * sc["ghi"][:, t][None, None, :]                    # (1,P,S) kWh this hour
        net = pv - daily_kwh * sc["unit"][:, t][None, None, :] / ETA_INVERTER
        gain = np.minimum(nom3, e + net * ETA_CHARGE)
        need = -net / ETA_DISCHARGE
        avail = np.maximum(0.0, e - lo)
        short = np.maximum(0.0, need - avail)
        e = np.where(net >= 0, gain, e - np.minimum(need, avail))
        uns_day[..., t // 24] += short * ETA_DISCHARGE * ETA_INVERTER
    counted = sc["counted"][None, None]                                    # (1,1,S,D)
    fail = (uns_day > FAIL_KWH) & counted
    fail_pct = 100.0 * fail.sum(axis=(2, 3)) / max(1, counted.sum())
    run = np.zeros((F, P, S)); best = np.zeros((F, P, S))
    for d in range(sc["n_days"]):
        run = np.where(counted[..., d], (run + 1) * fail[..., d], 0.0)
        best = np.maximum(best, run)
    unserved_pct = 100.0 * (uns_day * counted).sum(axis=(2, 3)) / max(1e-9, daily_kwh * counted.sum())
    return {"fail_pct": fail_pct, "streak_p90": np.percentile(best, 90, axis=2), "unserved_pct": unserved_pct}


def _meets(res: dict) -> np.ndarray:
    return (res["fail_pct"] <= TARGET_FAIL_PCT) & (res["streak_p90"] <= TARGET_STREAK_DAYS)


def design(ds: dict, daily_kwh: float, kwp: float, *, reserve_pct: float,
           compare_batteries: dict[str, float] | None = None) -> dict | None:
    """Smallest battery meeting the target for `daily_kwh` kWh/day and `kwp` kWp, plus how given batteries would have fared.

    Two floors: the physical one (the bank may be emptied to PHYSICAL_FLOOR_PCT) and the design reserve (`reserve_pct` is never
    touched). Returns None when the dataset cannot support a simulation."""
    k = ds.get("k")
    sc = _scenarios(ds)
    if not k or not sc or daily_kwh <= 0 or kwp <= 0:
        return None
    reserve = float(min(max(reserve_pct, PHYSICAL_FLOOR_PCT), 60.0))
    floors = np.array([PHYSICAL_FLOOR_PCT, reserve])
    grid = daily_kwh * np.linspace(0.4, 6.0, 57)                           # candidate batteries, ~0.1 day of load apart
    extras = {n: float(b) for n, b in (compare_batteries or {}).items() if b and b > 0}
    cands = np.concatenate([grid, np.array(list(extras.values()))]) if extras else grid
    res = _run(sc, k, daily_kwh, np.full(len(cands), kwp), cands, floors)
    ok = _meets(res)

    def smallest(f):
        idx = np.where(ok[f, :len(grid)])[0]
        return float(grid[idx[0]]) if len(idx) else None

    out = {"k": k, "scenarios": sc["n"], "locations": sc["locations"], "patterns": sc["patterns"],
           "days": int(sc["counted"].sum()), "window": ds["window"], "reserve_pct": reserve, "kwp": kwp, "daily_kwh": daily_kwh,
           "battery_min_physical": smallest(0), "battery_min_reserve": smallest(1),
           "compare": [{"name": n, "battery": b,
                        "fail_pct_physical": float(res["fail_pct"][0, len(grid) + i]),
                        "fail_pct_reserve": float(res["fail_pct"][1, len(grid) + i]),
                        "streak_p90": float(res["streak_p90"][0, len(grid) + i])} for i, (n, b) in enumerate(extras.items())],
           "validation": [v for v in ds["validation"]]}
    # Panels: with the reserve-respecting battery (or the physical one if that is unreachable), the smallest array that meets the target.
    battery = out["battery_min_reserve"] or out["battery_min_physical"]
    if battery:
        kwps = daily_kwh * np.linspace(0.3, 2.2, 20)
        res_k = _run(sc, k, daily_kwh, kwps, np.full(len(kwps), battery), floors[:1] if battery == out["battery_min_physical"] else floors[1:])
        good = np.where(_meets(res_k)[0])[0]
        out["kwp_min"] = float(kwps[good[0]]) if len(good) else None
        out["kwp_min_for_battery"] = float(battery)
    else:
        out["kwp_min"], out["kwp_min_for_battery"] = None, None
    return out


# ── hybrid ───────────────────────────────────────────────────────────────

def _run_hybrid(sc: dict, k: float, daily_kwh: float, kwp: np.ndarray, batt: np.ndarray, floor_pct: float, keep_state: bool = False) -> dict:
    """Hour-by-hour balance for P (kWp, battery) pairs x S scenarios with the grid as fallback.
    Returns grid-import % of the load, % of nights carried to sunrise by solar+battery, and (optionally) the battery energy per hour."""
    S, T = sc["ghi"].shape
    P = len(batt)
    local_h = np.arange(T) % 24
    night = (local_h >= NIGHT_START_H) | (local_h < NIGHT_END_H)
    night_id = (np.arange(T) - NIGHT_START_H) // 24 + 1
    n_nights = int(night_id.max()) + 1
    counted_h = np.repeat(sc["counted"], 24, axis=1)[:, :T]                               # (S,T)
    nom, lo = batt[:, None], batt[:, None] * floor_pct / 100.0
    e = np.broadcast_to(nom, (P, S)).copy()
    imp_total = np.zeros((P, S))
    night_imp = np.zeros((P, S, n_nights))
    state = np.zeros((P, S, T), dtype=np.float32) if keep_state else None
    for t in range(T):
        pv = k * kwp[:, None] * sc["ghi"][:, t][None, :]
        net = pv - daily_kwh * sc["unit"][:, t][None, :] / ETA_INVERTER
        gain = np.minimum(nom, e + net * ETA_CHARGE)
        need = -net / ETA_DISCHARGE
        avail = np.maximum(0.0, e - lo)
        short = np.maximum(0.0, need - avail)
        e = np.where(net >= 0, gain, e - np.minimum(need, avail))
        imp = short * ETA_DISCHARGE * ETA_INVERTER
        imp_total += imp * counted_h[:, t][None, :]
        if night[t]:
            night_imp[:, :, night_id[t]] += imp
        if keep_state:
            state[:, :, t] = e
    # a night counts when all its 12 hours are inside valid, post-warm-up data
    valid = sc["valid"]
    night_ok_mask = np.zeros((S, n_nights), dtype=bool)
    for n in range(WARMUP_DAYS + 1, n_nights):
        idx = np.where((night_id == n) & night)[0]
        if len(idx) == 12:
            night_ok_mask[:, n] = valid[:, idx].all(axis=1)
    carried = (night_imp <= FAIL_KWH) & night_ok_mask[None]
    load_total = daily_kwh * (sc["unit"] * counted_h).sum(axis=1)                        # (S,)
    return {"import_pct": 100.0 * imp_total.sum(axis=1) / max(1e-9, load_total.sum()),
            "nights_ok_pct": 100.0 * carried.sum(axis=(1, 2)) / max(1, night_ok_mask.sum() * 1),
            "state": state, "counted_h": counted_h}


def _outage_survival(sc: dict, daily_kwh: float, batt: np.ndarray, state: np.ndarray, counted_h: np.ndarray, horizon: int = int(OUTAGE_MAX_H)) -> list[np.ndarray]:
    """For each battery: hours the critical load would have been served if the grid failed at each hour of the dataset (no sun counted,
    battery released down to the physical floor). One sorted array per battery."""
    S, T = sc["ghi"].shape
    need = daily_kwh * sc["unit"] / (ETA_INVERTER * ETA_DISCHARGE)                         # (S,T) battery kWh per hour
    cs = np.concatenate([np.zeros((S, 1)), np.cumsum(need, axis=1)], axis=1)               # (S,T+1)
    starts = np.arange(T - horizon - 1)
    out = []
    for p in range(len(batt)):
        vals = []
        for s in range(S):
            ok = counted_h[s, starts] & sc["valid"][s, starts]
            if not ok.any():
                continue
            t = starts[ok]
            avail = np.maximum(0.0, state[p, s, t].astype(float) - batt[p] * PHYSICAL_FLOOR_PCT / 100.0)
            reach = np.searchsorted(cs[s], cs[s, t + 1] + avail, side="right") - 1
            vals.append(np.minimum(reach - (t + 1), horizon))
        out.append(np.sort(np.concatenate(vals)) if vals else np.zeros(0))
    return out


def _coverage_pct(surv_sorted: np.ndarray, durations_h: list[float]) -> float:
    """Average over the real outages of the share of start times at which the battery would have outlasted that outage."""
    if not len(surv_sorted) or not durations_h:
        return float("nan")
    need = np.ceil(np.array(durations_h))
    share = 1.0 - np.searchsorted(surv_sorted, need, side="left") / len(surv_sorted)
    return float(100.0 * share.mean())


def design_hybrid(ds: dict, critical_daily_kwh: float, kwp: float, *, reserve_pct: float,
                  compare_batteries: dict[str, float] | None = None) -> dict | None:
    """Hybrid design test: real sun + fleet load patterns + real grid outages. See the module docstring."""
    hyb = ds.get("hybrid")
    k = ds.get("k")
    sc = _scenarios(ds)
    if hyb is None or not k or not sc or critical_daily_kwh <= 0 or kwp <= 0:
        return None
    reserve = float(min(max(reserve_pct, PHYSICAL_FLOOR_PCT), 60.0))
    durations = hyb["outages"]["hours"]
    have_outages = len(durations) >= MIN_OUTAGES
    grid = critical_daily_kwh * np.linspace(0.4, 6.0, 29)
    extras = {n: float(b) for n, b in (compare_batteries or {}).items() if b and b > 0}
    cands = np.concatenate([grid, np.array(list(extras.values()))]) if extras else grid
    run = _run_hybrid(sc, k, critical_daily_kwh, np.full(len(cands), kwp), cands, reserve, keep_state=True)
    surv = _outage_survival(sc, critical_daily_kwh, cands, run["state"], run["counted_h"])
    gap = hyb.get("gap_pts")

    def adj(x):
        return None if gap is None else float(min(100.0, x + gap))

    def first(mask):
        idx = np.where(mask[:len(grid)])[0]
        return float(grid[idx[0]]) if len(idx) else None

    cover = np.array([_coverage_pct(s, durations) for s in surv]) if have_outages else np.full(len(cands), np.nan)
    out = {"k": k, "scenarios": sc["n"], "locations": sc["locations"], "patterns": sc["patterns"], "days": int(sc["counted"].sum()),
           "window": ds["window"], "reserve_pct": reserve, "kwp": kwp, "daily_kwh": critical_daily_kwh,
           "gap_pts": gap, "gap_range": hyb.get("gap_range"), "gap_sites": hyb.get("accepted", 0),
           "night_target": NIGHT_TARGET_PCT, "outage_target": OUTAGE_TARGET_PCT,
           "battery_min_nights": first(run["nights_ok_pct"] >= NIGHT_TARGET_PCT),
           "battery_min_backup": first(cover >= OUTAGE_TARGET_PCT) if have_outages else None,
           "outages": {"n": len(durations), "sites": hyb["outages"]["sites"], "longer": hyb["outages"]["longer"], "enough": have_outages,
                       "median_h": float(np.median(durations)) if durations else None,
                       "p90_h": float(np.percentile(durations, 90)) if durations else None},
           "compare": [], "validation": hyb["validation"], "k_sites": hyb.get("k_sites") or []}
    for i, (n, b) in enumerate(extras.items()):
        j = len(grid) + i
        sv = surv[j]
        out["compare"].append({"name": n, "battery": b, "import_pct": float(run["import_pct"][j]), "import_pct_adj": adj(run["import_pct"][j]),
                               "nights_ok_pct": float(run["nights_ok_pct"][j]),
                               "outage_cover_pct": None if not have_outages else float(cover[j]),
                               "backup_p10_h": float(np.percentile(sv, 10)) if len(sv) else None,
                               "backup_median_h": float(np.median(sv)) if len(sv) else None})
    # Panels: more kWp with the formula (or first compared) battery
    ref_b = next(iter(extras.values()), None) or out["battery_min_nights"]
    if ref_b:
        factors = np.array([0.6, 0.8, 1.0, 1.25, 1.5])
        rk = _run_hybrid(sc, k, critical_daily_kwh, kwp * factors, np.full(len(factors), ref_b), reserve)
        out["kwp_curve"] = [{"kwp": float(kwp * f), "factor": float(f), "import_pct": float(rk["import_pct"][i]),
                             "import_pct_adj": adj(rk["import_pct"][i]), "nights_ok_pct": float(rk["nights_ok_pct"][i])}
                            for i, f in enumerate(factors)]
        out["kwp_curve_battery"] = float(ref_b)
    return out
