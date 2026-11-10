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


# ── Charge controller validation (Off-Grid/Hybrid, Phase 5) ─────────────────
#
# A charge controller (e.g. Victron SmartSolar MPPT 250/100) has a different
# spec shape than a grid-tied string inverter: a single max input voltage
# (vin_max) rather than an MPPT voltage *window*, and one input current
# rating (imax_in) rather than per-channel current across multiple trackers.
# Confirmed design (2026-07-23): the hard constraint is Voc_total ≤ vin_max;
# beyond that, add parallel strings to maximize array power up to imax_in.

def _cc_combo_metrics(ns: int, np_: int, panel: dict, charge_controller: dict) -> dict:
    """Compute all metrics for a (panels_in_series, strings_in_parallel) pair against a charge controller."""
    voc = float(panel["voc"])
    vmp = float(panel["vmp"])
    imp = float(panel["imp"])
    wp = int(panel["wp"])
    width_m = float(panel.get("width_m") or 0)
    height_m = float(panel.get("height_m") or 0)

    vin_max = float(charge_controller["vin_max"])
    imax_in = float(charge_controller["imax_in"])

    voc_total = round(ns * voc, 1)
    vmp_total = round(ns * vmp, 1)
    imp_total = round(np_ * imp, 2)
    system_kw = round(ns * np_ * wp / 1000, 2)
    area_m2 = round(ns * np_ * width_m * height_m, 1)

    violations: list[str] = []
    if voc_total > vin_max:
        violations.append(f"Voc {voc_total}V > Vin máx {vin_max:.0f}V del controlador")
    if imp_total > imax_in:
        violations.append(f"Corriente {imp_total}A > Imax entrada {imax_in:.0f}A del controlador")

    return {
        "panels_per_string": ns,
        "strings": np_,
        "total_panels": ns * np_,
        "system_kw": system_kw,
        "area_m2": area_m2,
        "voc_total": voc_total,
        "vmp_total": vmp_total,
        "imp_total": imp_total,
        "within_limits": len(violations) == 0,
        "violations": violations,
        "notes": "; ".join(violations) if violations else "OK",
        "_vin_max": vin_max,
        "_imax_in": imax_in,
    }


def max_array_for_charge_controller(panel: dict, charge_controller: dict) -> dict | None:
    """
    Finds the (panels_per_string, n_strings) combo that maximizes array power
    for one charge controller: picks the longest string that keeps
    Voc_total ≤ vin_max (minimizes current/losses, standard practice), then
    adds as many parallel strings as imax_in allows.

    Returns None if no valid series count exists (panel Voc alone exceeds vin_max).
    """
    voc = float(panel["voc"])
    imp = float(panel["imp"])
    vin_max = float(charge_controller["vin_max"])
    imax_in = float(charge_controller["imax_in"])

    max_series = int(vin_max / voc)
    if max_series < 1:
        return None

    max_parallel = max(1, int(imax_in / imp))

    return {"scenario": "M", **_cc_combo_metrics(max_series, max_parallel, panel, charge_controller)}


def check_charge_controller_design_multi(
    panel: dict,
    charge_controller: dict,
    panels_per_string: int,
    n_strings: int,
    max_cc: int = 4,
) -> dict | None:
    """
    Validate a specific (panels_per_string, n_strings) array against a charge
    controller's electrical limits, accounting for paralleling multiple
    controllers when a single one can't carry the array's current —
    charge_controller_qty is the minimum controller count (up to max_cc)
    whose combined Imax_in covers the array's total string current, and
    within_limits/violations are checked against that scaled current limit
    rather than a single controller's Imax_in (a single Voc_total ≤ vin_max
    check still applies, since paralleling controllers doesn't change string
    voltage).

    Returns None if even max_cc controllers in parallel can't carry the
    design's current (n_strings is too large for this panel/controller pair).

    Does NOT set a 'scenario' key (unlike check_charge_controller_design()) —
    this is a shared building block for both the manual-mode check and
    validate_charge_controller_design()'s A/B/C generation, and the caller in
    each case is the one who knows the right label to attach.
    """
    from calculations.datasheet_limits import controller_trackers

    imp = float(panel["imp"])
    imax_in = float(charge_controller["imax_in"]) * controller_trackers(charge_controller)   # all of a unit's trackers together
    n_strings = max(1, n_strings)
    if imax_in <= 0:
        return None
    total_imp = round(n_strings * imp, 2)
    cc_qty = max(1, math.ceil(total_imp / imax_in))
    if cc_qty > max_cc:
        return None

    m = _cc_combo_metrics(panels_per_string, n_strings, panel, charge_controller)
    vin_max = float(charge_controller["vin_max"])
    imp_limit = imax_in * cc_qty
    violations: list[str] = []
    if m["voc_total"] > vin_max:
        violations.append(f"Voc {m['voc_total']}V > Vin máx {vin_max:.0f}V del controlador")
    if m["imp_total"] > imp_limit:
        violations.append(
            f"Corriente {m['imp_total']}A > Imax {imp_limit:.0f}A "
            f"({cc_qty}×{imax_in:.0f}A del controlador)"
        )
    m["charge_controller_qty"] = cc_qty
    m["within_limits"] = len(violations) == 0
    m["violations"] = violations
    m["notes"] = "; ".join(violations) if violations else "OK"
    return m


def find_array_for_target_kw(
    panel: dict,
    charge_controller: dict,
    target_system_kw: float,
    max_cc: int = 4,
    max_strings: int = 60,
) -> dict | None:
    """
    Finds the smallest array (fewest parallel strings) whose system_kw meets
    or exceeds target_system_kw — the non-iterative counterpart to
    find_array_for_reliability() below, used by the static design-tier model
    (calculations/sizing_off_grid.py: generate_design_scenarios()) instead of
    an iterative day-by-day reliability search.

    Series count uses the same convention as the rest of this module: fixed
    at the value that maximizes Voc within vin_max (minimizes DC current/
    cabling losses). Only strings in parallel are searched, paralleling more
    charge controllers (up to max_cc) as current demands it.

    Returns the smallest combo with system_kw >= target_system_kw. If
    target_system_kw can't be reached within max_strings/max_cc, returns the
    largest combo that was still reachable instead of None, so the caller
    always gets *a* design to evaluate — its own system_kw vs. the target
    (checked by the caller) is what surfaces the shortfall, not a bare
    failure. Returns None only if no series count exists at all (panel Voc
    alone exceeds vin_max).
    """
    voc = float(panel["voc"])
    vin_max = float(charge_controller["vin_max"])
    if voc <= 0:
        return None
    max_series = int(vin_max / voc)
    if max_series < 1:
        return None

    chosen_series = None
    for series in range(max_series, 0, -1):
        if check_charge_controller_design_multi(panel, charge_controller, series, 1, max_cc):
            chosen_series = series
            break
    if chosen_series is None:
        return None

    last_valid = None
    for n_strings in range(1, max_strings + 1):
        combo = check_charge_controller_design_multi(panel, charge_controller, chosen_series, n_strings, max_cc)
        if combo is None:
            break  # exceeded max_cc — return whatever was still valid
        last_valid = combo
        if combo["system_kw"] >= target_system_kw:
            return combo

    return last_valid


def _best_layout(n_panels: int, max_series: int, max_parallel: int) -> tuple[int, int] | None:
    """(series, parallel) with series x parallel == n_panels, as many modules in series as the voltage limit allows
    (fewest strings, lowest DC current), within `max_parallel` strings. None when no such split exists."""
    for series in range(min(max_series, n_panels), 0, -1):
        if n_panels % series == 0 and n_panels // series <= max_parallel:
            return series, n_panels // series
    return None


def find_array_per_controller(panel: dict, charge_controller: dict, target_system_kw: float, max_cc: int = 4) -> dict | None:
    """DC-coupled array sized by the number of panels the target needs, not by a fixed string size.

    One charge controller takes up to `max_series` modules in series (Voc <= Vin max) and as many parallel strings as its
    input current allows — 5 x 2 = 10 panels on a 250/100 with a 620 W module. The panel count is the target rounded up to a
    whole panel, and up to an even number when it is odd (an odd count does not split into two equal strings). It goes on the
    fewest controllers that can carry it, shared as evenly as possible with an even count on each (6 -> 3 x 2, 8 -> 4 x 2,
    10 -> 5 x 2, 26 -> 10 + 8 + 8 on three controllers), and each controller's modules are split into equal strings with as
    many in series as the voltage allows.

    Returns the dict shape the rest of the wizard reads — `panels_per_string` (the longest string, the conservative voltage),
    `strings` (all of them), `charge_controller_qty`, `total_panels` (exact) — plus `groups` (one entry per controller) and
    `layout_text`. When the target needs more than `max_cc` controllers can take, returns the largest array they can (the
    caller compares its kW with the target). None when a single module already exceeds the controller's voltage."""
    voc, imp, wp = float(panel["voc"]), float(panel["imp"]), float(panel["wp"])
    vin_max, imax_in = float(charge_controller["vin_max"]), float(charge_controller["imax_in"])
    max_series = int(vin_max / voc) if voc > 0 else 0
    if max_series < 1 or imax_in <= 0 or wp <= 0 or imp <= 0:
        return None
    from calculations.datasheet_limits import controller_trackers

    # A controller with several independent MPPT trackers (e.g. the RS 450/200: 4) takes as many strings as trackers x what one tracker carries.
    trackers, per_tracker = controller_trackers(charge_controller), max(1, int(imax_in / imp))
    max_parallel = trackers * per_tracker
    # Several independent trackers that each carry ONE string (the RS 450/200 with a 15 A module): every tracker has its own
    # voltage, so the strings need not be equal — 30 panels on one unit is 8 + 8 + 7 + 7.
    independent = trackers > 1 and per_tracker == 1
    cap = max_series * max_parallel
    n = max(2, math.ceil(target_system_kw * 1000.0 / wp - 1e-9))
    n += n % 2                                                    # odd -> round up

    def split(total: int, k: int) -> list[tuple] | None:
        units = total // 2
        if units < k:
            return None
        base, extra = divmod(units, k)
        groups = []
        for i in range(k):
            count = 2 * (base + (1 if i < extra else 0))
            if count > cap:
                return None
            if independent:
                strings = math.ceil(count / max_series)                      # fewest, longest strings
                lo, extra_s = divmod(count, strings)
                lengths = [lo + 1] * extra_s + [lo] * (strings - extra_s)
                groups.append((count, lengths[0], strings, lengths))
                continue
            layout = _best_layout(count, max_series, max_parallel)
            if layout is None:
                return None
            groups.append((count, layout[0], layout[1], [layout[0]] * layout[1]))
        return groups

    groups = None
    for k in range(max(1, math.ceil(n / cap)), max_cc + 1):
        groups = split(n, k)
        if groups:
            break
    if groups is None:                                            # target out of reach: the biggest array max_cc controllers take
        for total in range(max_cc * (cap - cap % 2), 1, -2):
            groups = split(total, max_cc)
            if groups:
                break
    if not groups:
        return None

    k = len(groups)
    total_panels = sum(g[0] for g in groups)
    n_strings = sum(g[2] for g in groups)
    series_max = max(g[1] for g in groups)               # longest string: the voltage the controller must take
    width, height = float(panel.get("width_m") or 0), float(panel.get("height_m") or 0)
    combo = _cc_combo_metrics(series_max, n_strings, panel, charge_controller)
    combo.update({
        "total_panels": total_panels, "system_kw": round(total_panels * wp / 1000, 2),
        "area_m2": round(total_panels * width * height, 1), "charge_controller_qty": k,
        "groups": [{"panels": c, "series": s_, "strings": p_, "lengths": lens} for c, s_, p_, lens in groups],
        "within_limits": True, "violations": [], "notes": "OK",
    })
    # "5S×2P + 4S×2P + 4S×2P": one entry per controller (S = en serie, P = strings en paralelo).
    if independent:
        combo["layout_text"] = " | ".join("+".join(str(x) for x in g[3]) for g in groups) + " paneles por string (un string por entrada MPPT)"
    else:
        combo["layout_text"] = (f"{groups[0][1]} en serie × {groups[0][2]} en paralelo" if k == 1
                                else " + ".join(f"{g[1]}S×{g[2]}P" for g in groups))
    return combo


def find_array_for_pv_inverter(panel: dict, pv_inverter: dict, target_system_kw: float, qty: int = 1) -> dict | None:
    """AC-coupled array: the panels go straight to the MPPT inputs of the string inverter (Fronius) — there is no charge
    controller. Same sizing rule as the DC case: the panel count the target needs (up to an even number when odd), split
    into equal strings, as many strings as fit the MPPT inputs (one string per MPPT first) and as many modules in series as
    the inverter's voltage window allows. Returns the same dict shape as the DC finder with `charge_controller_qty` = 0 and
    the inverter's own limits in `ac_limits`; None when the inverter has no voltage data or no layout fits."""
    voc, vmp, imp, wp = float(panel["voc"]), float(panel["vmp"]), float(panel["imp"]), float(panel["wp"])
    channels = max(1, int(float(pv_inverter.get("mppt_channels") or 1))) * max(1, qty)
    vmax = float(pv_inverter.get("vmax") or pv_inverter.get("vmax_mppt") or 0)
    vmin_mppt, vmax_mppt = float(pv_inverter.get("vmin_mppt") or 0), float(pv_inverter.get("vmax_mppt") or 0)
    imax = float(pv_inverter.get("imax_mppt") or 0)
    if vmax <= 0 or wp <= 0 or voc <= 0:
        return None
    n = max(2, math.ceil(target_system_kw * 1000.0 / wp - 1e-9))
    n += n % 2
    per_mppt_parallel = max(1, int(imax / imp)) if imax > 0 else 1

    best = None
    for strings in range(min(channels * per_mppt_parallel, n), 0, -1):          # most strings first (one per MPPT before pairing)
        if n % strings:
            continue
        series = n // strings
        if series * voc > vmax or (vmax_mppt and series * vmp > vmax_mppt) or (vmin_mppt and series * vmp < vmin_mppt):
            continue
        if strings > channels and (strings / channels) > per_mppt_parallel:
            continue
        # prefer using the MPPT inputs evenly: strings that are a multiple of the channel count (or fit within it)
        key = (strings <= channels or strings % channels == 0, strings if strings <= channels else -strings)
        if best is None or key > best[0]:
            best = (key, strings, series)
    if best is None:
        return None
    _, strings, series = best
    spm = math.ceil(strings / channels)
    width, height = float(panel.get("width_m") or 0), float(panel.get("height_m") or 0)
    voc_total, imp_total = round(series * voc, 1), round(spm * imp, 2)
    violations = []
    if imax > 0 and imp_total > imax:
        violations.append(f"Corriente por MPPT {imp_total}A > {imax:.0f}A del inversor")
    return {
        "panels_per_string": series, "strings": strings, "total_panels": series * strings,
        "system_kw": round(series * strings * wp / 1000, 2), "area_m2": round(series * strings * width * height, 1),
        "voc_total": voc_total, "vmp_total": round(series * vmp, 1), "imp_total": imp_total,
        "charge_controller_qty": 0, "within_limits": not violations, "violations": violations,
        "layout_text": f"{series} en serie × {strings} en paralelo · {min(strings, channels)} MPPT" if strings else None,
        "notes": "OK" if not violations else "; ".join(violations),
        "ac_limits": {"vmax": vmax, "imax_mppt": imax, "channels": channels, "kw": float(pv_inverter.get("kw") or 0) * max(1, qty), "pv_inverter": f"{pv_inverter.get('brand', '')} {pv_inverter.get('model', '')}".strip()},
    }


def find_array_for_reliability(
    panel: dict,
    charge_controller: dict,
    daily_kwh_kwp: list[float],
    daily_kwh_consumption: float,
    capacity_kwh: float,
    battery_dod_pct: float,
    target_min_soc_pct: float,
    max_unmet_load_days: int,
    max_cc: int = 4,
    growth_extra_strings: int = 0,
    max_strings: int = 60,
) -> dict | None:
    """
    Finds the smallest array (fewest parallel strings) that keeps a
    `capacity_kwh` battery bank from ever dropping below its hard
    depth-of-discharge floor more than `max_unmet_load_days` times across a
    real reference year — the array-sizing half of the reliability-driven
    scenario generator (see calculations/sizing_off_grid.py's
    generate_reliability_scenarios() and simulate_battery_soc()).

    This replaced a monthly-average check (does generation clear consumption
    in >=N of 12 PVGIS months) that couldn't see multi-day cloudy streaks
    within a month, and said nothing about whether the battery was actually
    sized right for the array it was paired with — see the module-level
    calculations/sizing_off_grid.py comment above _RELIABILITY_SCENARIO_DEFS
    for why day-level simulation is materially more honest here.

    `capacity_kwh`/`battery_dod_pct`/`target_min_soc_pct` describe a battery
    bank already sized by size_battery_for_min_soc() for this scenario's
    cycle-depth preference — battery capacity is a design target set
    independently of array size (it only depends on daily consumption), so
    the caller fixes it before searching; this function validates that the
    array is actually big enough to make that battery behave as promised
    across a real year, not just on one average day.

    Series count is fixed at the value that maximizes Voc within vin_max
    (same convention as the rest of this module — longer strings minimize
    current/cabling losses); only strings in parallel are searched, growing
    by one at a time and paralleling more charge controllers (up to max_cc)
    as current demands it.

    `growth_extra_strings` adds headroom strings on top of the
    reliability-satisfying array (used by the "always + room to grow"
    scenario) — if that grown combo would exceed max_cc controllers, the
    ungrown (but still reliability-satisfying) combo is returned instead
    rather than failing outright.

    Returns None if no series count exists at all (panel Voc alone exceeds
    vin_max), or if max_strings is exhausted without meeting the reliability
    target within max_cc controllers. On success, the returned dict carries a
    `reliability` sub-dict — simulate_battery_soc()'s full output for the
    winning array — for the caller to fold into the scenario's battery info.
    """
    from calculations.sizing_off_grid import simulate_battery_soc

    voc = float(panel["voc"])
    vin_max = float(charge_controller["vin_max"])
    if voc <= 0:
        return None
    max_series = int(vin_max / voc)
    if max_series < 1:
        return None

    chosen_series = None
    for series in range(max_series, 0, -1):
        if check_charge_controller_design_multi(panel, charge_controller, series, 1, max_cc):
            chosen_series = series
            break
    if chosen_series is None:
        return None

    derating = 1 - 0.20  # matches calculations/sizing_off_grid.py's size_array() default

    combo = None
    sim = None
    for n_strings in range(1, max_strings + 1):
        combo = check_charge_controller_design_multi(panel, charge_controller, chosen_series, n_strings, max_cc)
        if combo is None:
            return None  # exceeded max_cc before reaching the reliability target
        system_kw = combo["system_kw"]
        daily_generation = [v * system_kw * derating for v in daily_kwh_kwp]
        sim = simulate_battery_soc(
            daily_generation, daily_kwh_consumption, capacity_kwh, battery_dod_pct, target_min_soc_pct,
        )
        if sim["unmet_load_days"] <= max_unmet_load_days:
            break
    else:
        return None

    if growth_extra_strings:
        grown = check_charge_controller_design_multi(
            panel, charge_controller, chosen_series, n_strings + growth_extra_strings, max_cc,
        )
        if grown:
            grown_generation = [v * grown["system_kw"] * derating for v in daily_kwh_kwp]
            sim = simulate_battery_soc(
                grown_generation, daily_kwh_consumption, capacity_kwh, battery_dod_pct, target_min_soc_pct,
            )
            combo = grown

    combo["reliability"] = sim
    return combo
