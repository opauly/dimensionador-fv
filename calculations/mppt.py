from __future__ import annotations
"""
MPPT string design validator. Generates 3 scenarios (A/B/C) per inverter. Phase 2.

Scenarios are centered around target_system_kw (derived from consumption / irradiance).
A = one string fewer than B, C = one string more.
"""
import math


def validate_string_design(
    panel: dict,
    inverter: dict,
    target_system_kw: float | None = None,
) -> list[dict]:
    """
    Generate 3 MPPT scenarios for the given panel + inverter combination.

    Each scenario tries a different number of panels per string and strings in parallel,
    keeping Voc within inverter Vmax and Vmp within MPPT window.

    Returns list of 3 dicts, each with:
        scenario: 'A' | 'B' | 'C'
        panels_per_string: int
        strings: int
        total_panels: int
        system_kw: float
        voc_total: float
        vmp_total: float
        isc_total: float
        within_limits: bool
        notes: str
    """
    if not inverter.get("vmax") or not inverter.get("vmin_mppt"):
        return []

    voc = float(panel["voc"])
    vmp = float(panel["vmp"])
    imp = float(panel["imp"])
    isc = float(panel["isc"])
    wp = int(panel["wp"])

    v_max = float(inverter["vmax"])
    vmin_mppt = float(inverter["vmin_mppt"])
    vmax_mppt = float(inverter["vmax_mppt"])
    imax_mppt = float(inverter["imax_mppt"])
    mppt_channels = int(inverter["mppt_channels"])

    # Valid panels-in-series range
    max_series_by_voc = int(v_max / voc)
    max_series_by_vmp = int(vmax_mppt / vmp)
    min_series = math.ceil(vmin_mppt / vmp)
    max_series = min(max_series_by_voc, max_series_by_vmp)

    if min_series > max_series:
        return []

    # Parallel strings per MPPT channel
    max_strings_per_mppt = max(1, int(imax_mppt / imp))
    total_parallel = max_strings_per_mppt * mppt_channels

    # Center scenario B around target system size
    if target_system_kw and total_parallel > 0:
        target_panels = round(target_system_kw * 1000 / wp)
        target_series = max(min_series, min(max_series, round(target_panels / total_parallel)))
    else:
        target_series = (min_series + max_series) // 2

    scenario_b = max(min_series, min(max_series, target_series))
    scenario_a = max(min_series, scenario_b - 1)
    scenario_c = min(max_series, scenario_b + 1)

    # Deduplicate while maintaining A ≤ B ≤ C ordering
    candidates = sorted({scenario_a, scenario_b, scenario_c})
    labels = "ABC"
    if len(candidates) < 3:
        # Range is too tight — repeat boundary values
        while len(candidates) < 3:
            candidates.append(candidates[-1])

    scenarios = []
    for label, n_series in zip(labels, candidates[:3]):
        total_panels = n_series * total_parallel
        voc_total = round(n_series * voc, 1)
        vmp_total = round(n_series * vmp, 1)
        isc_total = round(max_strings_per_mppt * isc, 2)
        system_kw = round(total_panels * wp / 1000, 2)

        within = voc_total <= v_max and vmin_mppt <= vmp_total <= vmax_mppt

        notes_parts: list[str] = []
        if voc_total > v_max:
            notes_parts.append(f"Voc {voc_total}V > Vmax {v_max:.0f}V")
        if vmp_total < vmin_mppt:
            notes_parts.append(f"Vmp {vmp_total}V < MPPT mín {vmin_mppt:.0f}V")
        if vmp_total > vmax_mppt:
            notes_parts.append(f"Vmp {vmp_total}V > MPPT máx {vmax_mppt:.0f}V")

        scenarios.append({
            "scenario": label,
            "panels_per_string": n_series,
            "strings": total_parallel,
            "strings_per_mppt": max_strings_per_mppt,
            "total_panels": total_panels,
            "system_kw": system_kw,
            "voc_total": voc_total,
            "vmp_total": vmp_total,
            "isc_total": isc_total,
            "within_limits": within,
            "notes": "; ".join(notes_parts) if notes_parts else "OK",
        })

    return scenarios
