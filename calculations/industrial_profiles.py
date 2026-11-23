"""Measured load profiles of industrial three-phase plants (eGauge, `vrm.egauge_*`, migrations 070/071) as the load reference of a
three-phase Grid Zero design, the way the VRM fleet is for single-phase homes.

The Grid Zero simulation (`fleet_simulation.grid_zero_curve`) replays "the zone's real sun x load patterns" hour by hour with zero
export. For a single-phase service the load patterns are the fleet's; for a three-phase service they are the chosen plant's eGauge
history, passed through the SAME engine by swapping `ds["loads"]` (`dataset_for`). Nothing else about the simulation changes.

The service lives in the draft's `utility` dict (Step 4): `service_phases` (1 | 3), `service_v_ll`, `profile_site_id`. A draft without
those keys is single-phase and behaves exactly as before.

Best-effort like the fleet modules: any failure means "no profile" and callers keep their single-phase behaviour.
"""
from __future__ import annotations

import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd

LOCAL_UTC_OFFSET_H = -6                       # same convention as fleet_simulation (Costa Rica, no daylight saving)
DAY_START_H, DAY_END_H = 7, 17                # solar hours, as in fleet_shares
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_TTL_S = 24 * 3600
PAGE = 1000
DEFAULT_V_LL = 208.0

_mem: dict = {}
_derived: dict = {}


# ── the service the draft was quoted for ─────────────────────────────────


def service_of(blob: dict | None) -> dict:
    """{"phases": 1|3, "v_ll": volts, "profile_site_id": str | None} from the draft's utility step. Default: single-phase."""
    u = (blob or {}).get("utility") or {}
    three = str(u.get("service_phases") or "1").strip().lower() in ("3", "three", "trifasico", "trifásico")
    try:
        v_ll = float(u.get("service_v_ll") or DEFAULT_V_LL)
    except (TypeError, ValueError):
        v_ll = DEFAULT_V_LL
    return {"phases": 3 if three else 1, "v_ll": v_ll, "profile_site_id": (u.get("profile_site_id") or None) if three else None}


def is_three_phase(blob: dict | None) -> bool:
    return service_of(blob)["phases"] == 3


def profile_id_for(blob: dict | None) -> str | None:
    """The measured plant to replay for this draft: its chosen reference (or the first registered one) on a three-phase service,
    None on a single-phase one (the fleet stays the reference)."""
    svc = service_of(blob)
    return (svc["profile_site_id"] or default_site_id()) if svc["phases"] == 3 else None


# ── reference plants ─────────────────────────────────────────────────────


def list_reference_sites(phases: int = 3) -> list[dict]:
    """Registered eGauge plants ({site_id, name, company, first_ts, last_ts, nominal_v_ll}); [] on any failure."""
    try:
        from database.supabase_client import get_client

        rows = (get_client().schema("vrm").table("egauge_sites").select("site_id, name, company, phases, nominal_v_ll, first_ts, last_ts")
                .eq("phases", phases).order("name").execute().data or [])
        return rows
    except Exception:                                   # noqa: BLE001
        return []


def default_site_id() -> str | None:
    sites = list_reference_sites()
    return sites[0]["site_id"] if sites else None


def _fetch_hourly(site_id: str) -> pd.Series | None:
    from database.supabase_client import get_client

    t = get_client().schema("vrm").table("egauge_hourly")
    ts, kw, start = [], [], 0
    while True:
        chunk = t.select("ts, usage_kw").eq("site_id", site_id).order("ts").range(start, start + PAGE - 1).execute().data or []
        ts += [r["ts"] for r in chunk]
        kw += [r["usage_kw"] for r in chunk]
        if len(chunk) < PAGE:
            break
        start += PAGE
    if not ts:
        return None
    s = pd.Series(kw, index=pd.to_datetime(ts, utc=True), dtype=float, name=site_id).sort_index()
    return s.asfreq("1h")                                # a hole stays NaN: the simulation only counts whole days


def get_hourly(site_id: str | None) -> pd.Series | None:
    """The plant's hourly mean load, kW, hourly UTC index. Memory -> disk cache (24 h) -> Supabase. None when unavailable."""
    if not site_id:
        return None
    hit = _mem.get(site_id)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    path = CACHE_DIR / f"egauge_hourly_{site_id}.pkl"
    try:
        if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_S:
            s = pickle.loads(path.read_bytes())
            _mem[site_id] = (time.time(), s)
            return s
    except Exception:                                   # noqa: BLE001 — a bad cache file just means refetch
        pass
    try:
        s = _fetch_hourly(site_id)
    except Exception:                                   # noqa: BLE001
        s = None
    if s is None:
        return hit[1] if hit else None
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        path.write_bytes(pickle.dumps(s))
    except Exception:                                   # noqa: BLE001
        pass
    _mem[site_id] = (time.time(), s)
    return s


# ── plugging the plant into the existing simulation ──────────────────────


def dataset_for(ds: dict | None, site_id: str | None) -> dict | None:
    """The fleet dataset with the load patterns replaced by the plant's (weather, solar response `k` and climate stay). With no plant /
    no data: `ds` itself, so a caller never has to branch. The derived dict is cached per (ds, plant) so the simulation's own
    caches (keyed by the dataset's identity) keep working."""
    if not ds or not site_id:
        return ds
    key = (id(ds), site_id)
    if key in _derived:
        return _derived[key][1]
    s = get_hourly(site_id)
    if s is None or s.dropna().empty:
        return ds
    out = {**ds, "loads": {f"egauge:{site_id}": s.dropna()}, "industrial_site": site_id}
    if len(_derived) > 6:
        _derived.clear()
    _derived[key] = (ds, out)                           # keep `ds` alive: its id must not be reused while this entry exists
    return out


def dataset_for_blob(ds: dict | None, blob: dict | None) -> dict | None:
    svc = service_of(blob)
    if svc["phases"] != 3:
        return ds
    return dataset_for(ds, svc["profile_site_id"] or default_site_id())


# ── what the profile says (shown in the wizard) ──────────────────────────


def stats(site_id: str | None) -> dict | None:
    """Mean kW, peak, day share (07-17 local), minimum daytime load as a fraction of the mean, years of data."""
    s = get_hourly(site_id)
    if s is None:
        return None
    s = s.dropna()
    if len(s) < 24 * 30:
        return None
    local_h = (s.index.hour + LOCAL_UTC_OFFSET_H) % 24
    day = s[(local_h >= DAY_START_H) & (local_h < DAY_END_H)]
    mean = float(s.mean())
    return {"mean_kw": mean, "peak_kw": float(s.max()), "day_share": float(day.sum() / s.sum()),
            "day_p5_ratio": float(np.percentile(day, 5) / mean) if mean > 0 else None,
            "years": round(len(s) / 8766.0, 1), "hours": int(len(s))}


def monthly_factors(site_id: str | None) -> list[float] | None:
    """Calendar-month load factors of the measured plant (Jan..Dec, local time, mean 1.0): how much above/below its yearly average the
    plant runs each month. Used to spread a yearly-flat estimate over 12 months. None without data."""
    s = get_hourly(site_id)
    if s is None:
        return None
    s = s.dropna()
    if len(s) < 24 * 365:
        return None
    month = (s.index + pd.Timedelta(hours=LOCAL_UTC_OFFSET_H)).month
    by = s.groupby(month).mean()
    if len(by) != 12 or by.mean() <= 0:
        return None
    return [float(by[m] / by.mean()) for m in range(1, 13)]


def day_share(site_id: str | None) -> tuple[float, str] | None:
    """(share of consumption during solar hours, note) for the wizard's daytime-fraction slot, or None."""
    st = stats(site_id)
    if not st:
        return None
    return st["day_share"], (f"Perfil medido de la planta de referencia (eGauge, {st['years']:.1f} años cada 15 min, 07:00-17:00): "
                             f"{st['day_share'] * 100:.0f} %")
