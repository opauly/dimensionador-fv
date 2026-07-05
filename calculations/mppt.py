from __future__ import annotations
"""
MPPT string design validator. Phase 2.

validate_string_design() explores every valid (series, parallel) combination and
returns 3 scenarios: B centred on target kW, A below, C above.

check_design() validates a specific (series, parallel) pair for the manual mode.
"""
import math


def _combo_metrics(ns: int, np_: int, panel: dict, inverter: dict) -> dict:
    """Compute all metrics for a (panels_in_series, strings_in_parallel) pair."""
    voc  = float(panel["voc"])
    vmp  = float(panel["vmp"])
    imp  = float(panel["imp"])
    isc  = float(panel["isc"])
    wp   = int(panel["wp"])
    width_m  = float(panel.get("width_m") or 0)
    height_m = float(panel.get("height_m") or 0)

    vmax      = float(inverter["vmax"])
    vmin_mppt = float(inverter["vmin_mppt"])
    vmax_mppt = float(inverter["vmax_mppt"])
    imax_mppt = float(inverter["imax_mppt"])
    mppt_ch   = int(inverter["mppt_channels"])

    voc_total = round(ns * voc, 1)
    vmp_total = round(ns * vmp, 1)
    strings_per_ch = math.ceil(np_ / mppt_ch)
    isc_per_ch = round(strings_per_ch * isc, 2)
    imp_per_ch = round(strings_per_ch * imp, 2)
    system_kw  = round(ns * np_ * wp / 1000, 2)
    area_m2    = round(ns * np_ * width_m * height_m, 1)

    violations: list[str] = []
    if voc_total > vmax:
        violations.append(f"Voc {voc_total}V > Vmax {vmax:.0f}V")
    if vmp_total < vmin_mppt:
        violations.append(f"Vmp {vmp_total}V < MPPT mín {vmin_mppt:.0f}V")
    if vmp_total > vmax_mppt:
        violations.append(f"Vmp {vmp_total}V > MPPT máx {vmax_mppt:.0f}V")
    if imp_per_ch > imax_mppt:
        violations.append(f"Corriente MPPT {imp_per_ch}A > Imax {imax_mppt:.0f}A")

    return {
        "panels_per_string": ns,
        "strings": np_,
        "strings_per_mppt": strings_per_ch,
        "total_panels": ns * np_,
        "system_kw": system_kw,
        "area_m2": area_m2,
        "voc_total": voc_total,
        "vmp_total": vmp_total,
        "isc_per_mppt": isc_per_ch,
        "imp_per_mppt": imp_per_ch,
        "within_limits": len(violations) == 0,
        "violations": violations,
        "notes": "; ".join(violations) if violations else "OK",
        # inverter limits — carried for display in check_design
        "_vmax": vmax,
        "_vmin_mppt": vmin_mppt,
        "_vmax_mppt": vmax_mppt,
        "_imax_mppt": imax_mppt,
    }


def _make_description(scenario: str, combo: dict, b_total: int, inverter: dict) -> str:
    """One-line explanation of why this scenario was generated and what its design looks like."""
    ns  = combo["panels_per_string"]
    np_ = combo["strings"]
    spc = combo["strings_per_mppt"]   # strings per MPPT channel
    ch  = int(inverter.get("mppt_channels") or 1)
    vmin = float(inverter.get("vmin_mppt") or 0)
    vmax = float(inverter.get("vmax_mppt") or 0)
    vmp  = combo["vmp_total"]

    # Primary: why it was picked relative to target
    diff = combo["total_panels"] - b_total
    if scenario == "B":
        primary = "más cercano al consumo objetivo"
    elif diff < 0:
        n = abs(diff)
        primary = f"{n} panel{'es' if n != 1 else ''} menos — menor inversión inicial"
    else:
        primary = f"{diff} panel{'es' if diff != 1 else ''} más — mayor cobertura del consumo"

    # String architecture
    if np_ == 1:
        arch = "string único — cableado DC más simple"
    elif spc == 1 and ch > 1:
        arch = f"1 string por cada uno de los {ch} trackers MPPT"
    else:
        arch = f"{spc} string{'s' if spc > 1 else ''} en paralelo por tracker"

    # Voltage position within MPPT window (only note if toward edges)
    if vmax > vmin:
        pos = (vmp - vmin) / (vmax - vmin)
        if pos > 0.75:
            volt = "Vmp elevado → menos pérdidas I²R en DC"
        elif pos < 0.25:
            volt = "Vmp moderado → mayor margen ante irradiancia parcial"
        else:
            volt = None
    else:
        volt = None

    parts = [primary, arch]
    if volt:
        parts.append(volt)
    return " · ".join(parts)


def validate_string_design(
    panel: dict,
    inverter: dict,
    target_system_kw: float | None = None,
) -> list[dict]:
    """
    Generate 3 MPPT scenarios (A / B / C) by exploring all valid
    (panels_in_series × strings_in_parallel) combinations.

    B is the valid combo closest to target_system_kw.
    A is the closest valid combo with fewer total panels than B.
    C is the closest valid combo with more total panels than B.

    Each scenario dict includes a human-readable 'description' field.
    Returns list of up to 3 dicts with scenario key added.
    """
    if not inverter.get("vmax") or not inverter.get("vmin_mppt"):
        return []

    voc      = float(panel["voc"])
    vmp      = float(panel["vmp"])
    imp      = float(panel["imp"])
    vmax     = float(inverter["vmax"])
    vmin_mppt= float(inverter["vmin_mppt"])
    vmax_mppt= float(inverter["vmax_mppt"])
    imax_mppt= float(inverter["imax_mppt"])
    mppt_ch  = int(inverter["mppt_channels"])

    max_series = min(int(vmax / voc), int(vmax_mppt / vmp))
    min_series = math.ceil(vmin_mppt / vmp)
    max_per_ch = max(1, int(imax_mppt / imp))
    max_parallel = max_per_ch * mppt_ch

    if min_series > max_series:
        return []

    # Enumerate all valid combos
    valid: list[dict] = []
    for ns in range(min_series, max_series + 1):
        voc_t = round(ns * voc, 1)
        vmp_t = round(ns * vmp, 1)
        if voc_t > vmax or not (vmin_mppt <= vmp_t <= vmax_mppt):
            continue
        for np_ in range(1, max_parallel + 1):
            strings_per_ch = math.ceil(np_ / mppt_ch)
            if round(strings_per_ch * imp, 2) > imax_mppt:
                continue
            valid.append(_combo_metrics(ns, np_, panel, inverter))

    if not valid:
        return []

    target = target_system_kw or valid[len(valid) // 2]["system_kw"]

    b = min(valid, key=lambda c: abs(c["system_kw"] - target))

    smaller = [c for c in valid if c["total_panels"] < b["total_panels"]]
    a = min(smaller, key=lambda c: abs(c["system_kw"] - target)) if smaller else b

    larger = [c for c in valid if c["total_panels"] > b["total_panels"]]
    c = min(larger, key=lambda c: abs(c["system_kw"] - target)) if larger else b

    b_total = b["total_panels"]
    return [
        {"scenario": "A", "description": _make_description("A", a, b_total, inverter), **a},
        {"scenario": "B", "description": _make_description("B", b, b_total, inverter), **b},
        {"scenario": "C", "description": _make_description("C", c, b_total, inverter), **c},
    ]


def check_design(
    panel: dict,
    inverter: dict,
    panels_per_string: int,
    n_strings: int,
) -> dict:
    """
    Validate a specific (panels_per_string, n_strings) configuration.

    Returns the full metrics dict with 'violations' list (empty = valid) and
    'scenario' = 'M' to identify it as a manual design.
    """
    return {"scenario": "M", **_combo_metrics(panels_per_string, n_strings, panel, inverter)}
