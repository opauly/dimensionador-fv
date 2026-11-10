"""Manufacturer limits the wiring maths checks against (read from the datasheets in
`Desktop/Pauly & Co/General/FV General/Datasheets/Inversor/`), keyed by the model name.

* MultiPlus-II 120 V datasheet (Victron): continuous output (VA and W at 25 °C), peak power,
  maximum AC input current / transfer switch, efficiency.
* Fronius Primo 3.8-15.0 datasheet (US version): maximum continuous output current and the
  OCPD / AC breaker size at 240 V.

These are the FALLBACK: the catalog columns added by migration 058 (panels.max_series_fuse_a, inverters.cont_w_25c / peak_w /
max_ocpd_a / dc_fuse_a, batteries.fuse_a ...) win when filled, and are what the admin catalog form edits.
"""
from __future__ import annotations

import re

# model suffix -> continuous VA, continuous W @25 C, peak W, max AC input / transfer switch (A), max efficiency
MULTIPLUS_II_120V = {
    "12/3000/120-50": dict(cont_va=3000, cont_w_25c=2400, peak_w=5500, ac_in_a=50, eff=0.93),
    "24/3000/70-50": dict(cont_va=3000, cont_w_25c=2400, peak_w=5500, ac_in_a=50, eff=0.94),
    "48/3000/35-50": dict(cont_va=3000, cont_w_25c=2400, peak_w=5500, ac_in_a=50, eff=0.95),
    "24/5000/120-95": dict(cont_va=5000, cont_w_25c=4000, peak_w=9000, ac_in_a=95, eff=0.95),
    "48/5000/70-95": dict(cont_va=5000, cont_w_25c=4000, peak_w=9000, ac_in_a=95, eff=0.96),
}
MULTI_AC_V = 120.0

# Fronius Primo model number -> (max continuous output current A @240 V, OCPD / AC breaker size A @240 V)
FRONIUS_PRIMO_240V = {
    "3.8": (15.8, 20), "5.0": (20.8, 30), "6.0": (25.0, 35), "7.6": (31.7, 40), "8.2": (34.2, 45),
    "10.0": (41.6, 60), "11.4": (47.5, 60), "12.5": (52.1, 70), "15.0": (62.5, 80),
}


# Victron SmartSolar MPPT RS: several independent MPPT trackers in one unit, each with its own PV input (the catalog `imax_in` is the
# current of ONE tracker). Models not listed here have a single input. FALLBACK until the catalog carries the count itself.
CONTROLLER_TRACKERS = {"RS 450/200": 4, "RS 450/100": 2}


def controller_trackers(cc: dict | None) -> int:
    """Independent PV inputs (MPPT trackers) of a charge controller: the catalog value when present, else the datasheet table above, else 1."""
    cc = cc or {}
    try:
        n = int(cc.get("mppt_channels") or 0)
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        return n
    model = cc.get("model") or ""
    return next((v for k, v in CONTROLLER_TRACKERS.items() if k in model), 1)


# Victron rates a controller's PV power at its output current x the 48 V absorption voltage (57.6 V): 70 A -> 4 kW, 100 A -> 5.8 kW,
# 200 A -> 11.5 kW. An array above it is NOT a fault — the controller just limits its output (clipping losses) — so this is only
# reported, softly. The catalog `max_pv_w` column (when it exists) wins; otherwise this estimate from `imax_out`.
BATTERY_ABSORPTION_V = 57.6


def controller_max_pv_w(cc: dict | None) -> float | None:
    """Maximum PV power one controller unit can turn into output (W); None when neither the catalog nor `imax_out` gives it."""
    cc = cc or {}
    try:
        if cc.get("max_pv_w"):
            return float(cc["max_pv_w"])
        return float(cc["imax_out"]) * BATTERY_ABSORPTION_V if cc.get("imax_out") else None
    except (TypeError, ValueError):
        return None


def multi_limits(model: str | None) -> dict | None:
    """Datasheet row of a MultiPlus-II 120 V model, plus the AC currents at 120 V."""
    for key, row in MULTIPLUS_II_120V.items():
        if key in (model or ""):
            return {**row, "ac_cont_a": round(row["cont_va"] / MULTI_AC_V, 1), "ac_peak_a": round(row["peak_w"] / MULTI_AC_V, 1)}
    return None


def fronius_limits(model: str | None) -> dict | None:
    """{'out_a', 'ocpd_a'} for a Fronius Primo at 240 V, from its model name ('Primo 10.0-1')."""
    m = re.search(r"Primo\s*(\d+\.\d)", model or "", re.I)
    row = FRONIUS_PRIMO_240V.get(m.group(1)) if m else None
    return {"out_a": row[0], "ocpd_a": row[1]} if row else None
