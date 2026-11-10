"""Day / night load shares measured on the real fleet — the practical default for every wizard assumption about WHEN a home uses its energy.

The monitored sites' hourly load (the same cached dataset the fleet simulation uses) tells how much of the day's load falls in
the solar hours (07:00-17:00) and at night (18:00-06:00). Medians across sites replace the fixed guesses (45 % daytime, 40 %
night) and the AI estimate the wizards used before; the fixed numbers remain only as the fallback while the fleet dataset is not
ready, so nothing breaks without it. The fleet grows, so these shares sharpen on their own.
"""
from __future__ import annotations

import numpy as np

DAY_START_H, DAY_END_H = 7, 17          # solar hours
NIGHT_START_H, NIGHT_END_H = 18, 6      # same window the hybrid night simulation uses
FALLBACK_DAY = 0.45
FALLBACK_NIGHT = 0.40
MIN_SITES = 3

_cache: dict = {}


def _share(load, hours) -> float | None:
    from calculations.fleet_simulation import LOCAL_UTC_OFFSET_H

    pos = load.clip(lower=0)
    total = float(pos.sum())
    if total <= 0:
        return None
    local_h = (load.index.hour + LOCAL_UTC_OFFSET_H) % 24
    return float(pos[hours(local_h)].sum()) / total


def fleet_shares() -> dict | None:
    """{"day": share 07-17, "night": share 18-06, "n": sites, "day_range": (lo, hi), "night_range": (lo, hi)} or None."""
    try:
        from calculations.fleet_simulation import get_dataset

        ds = get_dataset()
    except Exception:                                   # noqa: BLE001 — optional
        return None
    if not ds or not ds.get("loads"):
        return None
    key = ds.get("built_at")
    if _cache.get("key") == key:
        return _cache["val"]
    days, nights = [], []
    for load in ds["loads"].values():
        d = _share(load, lambda h: (h >= DAY_START_H) & (h < DAY_END_H))
        n = _share(load, lambda h: (h >= NIGHT_START_H) | (h < NIGHT_END_H))
        if d is not None and n is not None:
            days.append(d)
            nights.append(n)
    val = None
    if len(days) >= MIN_SITES:
        val = {"day": float(np.median(days)), "night": float(np.median(nights)), "n": len(days),
               "day_range": (min(days), max(days)), "night_range": (min(nights), max(nights))}
    _cache.update(key=key, val=val)
    return val


def daytime_fraction_for(loads: list, city: str) -> tuple[float, str]:
    """(share of consumption during solar hours, short note for the wizard). The fleet's median when available, else the AI
    estimate from the loads list (its old behaviour, with its own 45 % fallback)."""
    fs = fleet_shares()
    if fs:
        lo, hi = fs["day_range"]
        return fs["day"], (f"Mediana real de {fs['n']} sitios de la flota (07:00-17:00): {fs['day'] * 100:.0f} % "
                           f"(rango {lo * 100:.0f}-{hi * 100:.0f} %)")
    from ai.daytime_fraction import estimate_daytime_fraction_ai

    return estimate_daytime_fraction_ai(loads, city)


def hybrid_defaults() -> dict:
    """The hybrid wizard's starting assumptions: night share of the critical load and daytime share of consumption, from the fleet
    when available (rounded to whole percent), else the historical fixed values."""
    fs = fleet_shares()
    return {"night_load_fraction": round(fs["night"], 2) if fs else FALLBACK_NIGHT,
            "daytime_fraction": round(fs["day"], 2) if fs else FALLBACK_DAY,
            "site_exports_to_grid": False}
