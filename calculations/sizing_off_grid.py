"""
Off-Grid system sizing: battery bank, array, discharge %, split-phase check. Phase 5.

Validation target (Jorge Ramírez):
    8 × 620W, 2 × Pylontech US5000C, Victron MPPT 250/100, Victron MultiPlus 5000VA
    → 5.0 kW, 16 m², 6.38 kWh/day, 9.60 kWh @10h, 66.46% discharge, $10,320, $2.08/Wp

Sizing pipeline (confirmed against the reference numbers 2026-07-23):
    1. size_array() sizes the panel count off the estimated daily load, producing
       daily_generation_kwh as an output (this is the "6.38 kWh/day" reference figure —
       it's the array's output, not a load input).
    2. size_battery_bank() then sizes the battery bank off that daily_generation_kwh,
       not off the raw load — an off-grid system stores what the array actually
       produces in a day for overnight/next-day use. Confirmed exactly:
       energy_needed = 6.38 kWh × 1 autonomy day; usable_needed = 6.38 / 0.80 (DoD)
       = 7.975 kWh → ceil(7.975 / 4.8 kWh per unit) = 2 batteries → 9.6 kWh installed
       → discharge_pct = 6.38 / 9.6 = 66.46% — matches the reference exactly.

Known open discrepancy (flagged, not silently resolved): the reference "16 m²" array
area does not reconcile with either JA Solar 620W SKU currently seeded in `panels`
(1.134m × 2.278m = 2.58 m²/panel, or 1.134m × 2.382m = 2.70 m²/panel) — both give
~20.6–21.6 m² for 8 panels, not 16 m². Either the original 2020 Jorge Ramírez install
used a different physical panel than what's seeded today, or "16 m²" was a rounded
estimate in the original documentation. size_array() below computes area from the
real panel dimensions passed in (matching calculations/mppt.py's pattern), so it will
report ~20-22 m² for this panel — flag to the user before treating 16 m² as ground truth.
"""
from __future__ import annotations
import math


def size_battery_bank(
    daily_kwh: float,
    autonomy_days: float,
    dod_pct: int,
    battery_voltage_v: float,
    battery_capacity_kwh: float,
) -> dict:
    """
    Sizes a battery bank to store `daily_kwh` (typically the array's daily
    generation, see module docstring) over `autonomy_days`, respecting the
    battery's usable depth-of-discharge.

    Returns: total_kwh_needed, battery_count, total_kwh_installed,
             discharge_pct, voltage_bank
    """
    if battery_capacity_kwh <= 0:
        raise ValueError("battery_capacity_kwh must be > 0")

    energy_needed_kwh = daily_kwh * autonomy_days
    usable_capacity_needed_kwh = energy_needed_kwh / (dod_pct / 100)
    battery_count = max(1, math.ceil(usable_capacity_needed_kwh / battery_capacity_kwh))
    total_kwh_installed = round(battery_count * battery_capacity_kwh, 2)
    discharge_pct = round(energy_needed_kwh / total_kwh_installed * 100, 2)

    return {
        "total_kwh_needed": round(energy_needed_kwh, 2),
        "battery_count": battery_count,
        "total_kwh_installed": total_kwh_installed,
        "discharge_pct": discharge_pct,
        "voltage_bank": battery_voltage_v,
    }


def size_array(
    daily_kwh: float,
    avg_peak_sun_hours: float,
    panel_wp: int,
    panel_width_m: float,
    panel_height_m: float,
    system_losses_pct: float = 0.20,
) -> dict:
    """
    Sizes the panel array to cover `daily_kwh` of estimated load, given average
    peak sun hours for the site. Panel physical dimensions are required to
    compute area_m2 (mirrors calculations/mppt.py's _combo_metrics pattern) —
    this extends the original Phase-0 stub signature, which didn't account for
    area depending on the specific panel's dimensions.

    Returns: array_kw, panel_count, area_m2, daily_generation_kwh
    """
    if avg_peak_sun_hours <= 0:
        raise ValueError("avg_peak_sun_hours must be > 0")

    derating = 1 - system_losses_pct
    required_kw = daily_kwh / (avg_peak_sun_hours * derating)
    panel_count = max(1, math.ceil(required_kw * 1000 / panel_wp))
    array_kw = round(panel_count * panel_wp / 1000, 2)
    area_m2 = round(panel_count * panel_width_m * panel_height_m, 1)
    daily_generation_kwh = round(array_kw * avg_peak_sun_hours * derating, 2)

    return {
        "array_kw": array_kw,
        "panel_count": panel_count,
        "area_m2": area_m2,
        "daily_generation_kwh": daily_generation_kwh,
    }


def check_split_phase(inverter: dict, output_v_required: float) -> dict:
    """
    Flags whether the selected inverter needs a second unit in split-phase
    (master/slave) configuration or an autotransformer to deliver
    output_v_required — e.g. the seeded Victron MultiPlus-II 48/5000/70-50 is
    120V single-phase; 240V split-phase service needs two in parallel, or one
    plus an autotransformer.

    Returns: requires_split_phase (bool), autotransformer_needed (bool), warning_message (str)
    """
    inverter_v = float(inverter.get("output_v") or 120)
    requires_split_phase = output_v_required >= 240 and inverter_v < 240

    warning_message = ""
    if requires_split_phase:
        warning_message = (
            f"Este inversor entrega {inverter_v:.0f}V. Para producir "
            f"{output_v_required:.0f}V se requieren dos unidades en configuración "
            f"split-phase (master/slave), o una unidad con autotransformador."
        )

    return {
        "requires_split_phase": requires_split_phase,
        # Both are valid alternatives when requires_split_phase is True;
        # the wizard UI presents both, it doesn't pick one automatically.
        "autotransformer_needed": requires_split_phase,
        "warning_message": warning_message,
    }


# ── Reliability-driven auto scenarios (Phase 5 redesign, 2026-07-25) ────────
#
# The original Opción 1 (see calculations/mppt.py's now-removed
# validate_charge_controller_design()) generated 3 scenarios by nudging
# string count ±1 around a single load-driven target — battery size and
# charge-controller count were downstream side effects of whatever array
# that produced. Per user feedback, scenarios should instead be driven by a
# target minimum daily SoC (battery health/depth-of-discharge preference)
# and a recharge-reliability target against the real 12 months of PVGIS
# data — MPPT/charge-controller sizing remains a pure consequence of
# whichever array a scenario's reliability search lands on.

def size_battery_for_min_soc(
    daily_kwh_consumption: float,
    min_soc_pct: float,
    autonomy_days: float,
    battery_dod_pct: float,
    battery_voltage_v: float,
    battery_capacity_kwh: float,
) -> dict:
    """
    Sizes a battery bank for a target minimum SoC reached on a normal day's
    consumption (daily cycle depth) — a different question from
    size_battery_bank()'s "survive N sunless days" framing, and driven by
    consumption rather than generation, since it's the load (not the array)
    that draws the battery down between recharges.

    Also enforces size_battery_bank()'s original multi-day autonomy floor
    (surviving `autonomy_days` of zero generation without exceeding the
    battery's own rated max DoD) as a hard safety minimum on top of the
    min-SoC preference — whichever of the two needs more capacity wins, so a
    shallow-cycling preference (e.g. 50% target SoC) can never quietly ignore
    the autonomy days configured in Step 4.

    Returns the same key shape as size_battery_bank() (drop-in compatible
    with every downstream chip/param-row/chart that reads a battery_bank
    dict), plus `min_soc_actual_pct` and `driven_by` for the scenario UI.
    """
    if battery_capacity_kwh <= 0:
        raise ValueError("battery_capacity_kwh must be > 0")

    target_dod_pct = 100 - min_soc_pct
    daily_cycle_kwh_needed = daily_kwh_consumption / (target_dod_pct / 100)
    autonomy_kwh_needed = (daily_kwh_consumption * autonomy_days) / (battery_dod_pct / 100)

    driven_by = "min_soc" if daily_cycle_kwh_needed >= autonomy_kwh_needed else "autonomy_floor"
    usable_capacity_needed_kwh = max(daily_cycle_kwh_needed, autonomy_kwh_needed)

    battery_count = max(1, math.ceil(usable_capacity_needed_kwh / battery_capacity_kwh))
    total_kwh_installed = round(battery_count * battery_capacity_kwh, 2)
    daily_discharge_pct = round(daily_kwh_consumption / total_kwh_installed * 100, 2)

    return {
        "total_kwh_needed": round(usable_capacity_needed_kwh, 2),
        "battery_count": battery_count,
        "total_kwh_installed": total_kwh_installed,
        "discharge_pct": daily_discharge_pct,
        "voltage_bank": battery_voltage_v,
        "min_soc_actual_pct": round(100 - daily_discharge_pct, 1),
        "driven_by": driven_by,
    }


# Round-trip battery charge/discharge efficiency — typical spec for LiFePO4
# (the chemistry every battery currently seeded in the DB uses). No per-
# battery efficiency field exists yet (checked: not in database/, not in
# calculations/sizing_off_grid.py or calculations/mppt.py before this), so
# this is a flat assumption, not a measured value. Applied to 100% of daily
# generation before it enters the simulated battery — deliberately
# conservative, since in reality some generation goes straight to direct-use
# loads with no round-trip loss at all; this only ever makes the simulated
# result equal or worse than reality, never better.
_BATTERY_ROUND_TRIP_EFFICIENCY = 0.92


def simulate_battery_soc(
    daily_generation_kwh: list[float],
    daily_kwh_consumption: float,
    capacity_kwh: float,
    battery_dod_pct: float,
    target_min_soc_pct: float,
    round_trip_eff: float = _BATTERY_ROUND_TRIP_EFFICIENCY,
    start_soc_pct: float = 100.0,
) -> dict:
    """
    Day-by-day battery energy-balance simulation against a real generation
    series — replaces the single-day static ratio previously used for
    min_soc_actual_pct and the monthly-average pass/fail previously used for
    recharge reliability (see module comment above _RELIABILITY_SCENARIO_DEFS
    for why: neither could see a multi-day cloudy streak driving the battery
    lower than any single day's cycle depth implies).

    `daily_generation_kwh` should already be array-kW-scaled and derated
    (calculations.mppt.find_array_for_reliability applies both before
    calling this), one value per real day in the reference year.
    `daily_kwh_consumption` is the flat per-day load estimate — the
    simulation runs at daily, not hourly, resolution (see CONTEXT.md for why:
    no calibrated hourly load curve exists yet, only an AI-illustrative one
    explicitly documented as not for sizing). Round-trip losses are applied
    to the full day's generation before it enters the battery — a
    deliberately conservative simplification (see _BATTERY_ROUND_TRIP_EFFICIENCY).

    The bank starts at `start_soc_pct` (default full — a new installation is
    commissioned and charged before handover, not handed over mid-cycle).

    Returns:
        min_soc_actual_pct: the single worst SoC reached anywhere in the
            simulated year — the honest replacement for the old static ratio.
        days_full_pct: % of days the battery reaches ~100% — the honest
            replacement for the old "meses de recarga X/12".
        unmet_load_days: days the battery would have been driven below its
            hard DoD floor — a real load-shedding/blackout risk, not just a
            healthy-cycling miss. This is what scenario search gates on.
        longest_low_soc_streak_days: longest consecutive run of days ending
            below `target_min_soc_pct` (the scenario's preference line, not
            the hard floor) — informational: extended shallow operation
            stresses the battery even on days it never actually blacks out.
        utilization_pct: % of total simulated generation that was actually
            used (consumption + battery charging) rather than curtailed
            because the battery was already full with nowhere else for the
            surplus to go (no grid, no export). A low number flags an array
            oversized relative to this battery/load combination — cheaper to
            fix with a bigger battery or fewer panels than to discover after
            install that most of what was quoted never gets used.
        total_generation_kwh / curtailed_kwh: the raw totals behind
            utilization_pct, for callers that want to report kWh directly.
    """
    if capacity_kwh <= 0 or not daily_generation_kwh:
        return {
            "min_soc_actual_pct": 0.0, "days_full_pct": 0.0,
            "unmet_load_days": len(daily_generation_kwh or []), "longest_low_soc_streak_days": 0,
            "daily_charge_in_kwh": [0.0] * len(daily_generation_kwh or []),
            "utilization_pct": 0.0, "total_generation_kwh": 0.0, "curtailed_kwh": 0.0,
        }

    floor_kwh = capacity_kwh * (1 - battery_dod_pct / 100)
    target_kwh = capacity_kwh * target_min_soc_pct / 100
    epsilon = capacity_kwh * 0.001

    soc_kwh = capacity_kwh * start_soc_pct / 100
    min_soc_kwh = soc_kwh
    days_full = 0
    unmet_load_days = 0
    low_streak = current_streak = 0
    daily_charge_in_kwh = []
    total_generation_kwh = 0.0
    curtailed_kwh = 0.0

    for gen_kwh in daily_generation_kwh:
        total_generation_kwh += gen_kwh
        soc_before = soc_kwh
        soc_kwh = min(capacity_kwh, soc_kwh + gen_kwh * round_trip_eff)
        charge_in = soc_kwh - soc_before
        daily_charge_in_kwh.append(round(charge_in, 3))
        # Generation the array made but the battery had no room left to store,
        # with no grid and no load beyond daily_kwh_consumption to absorb it —
        # real, unrecoverable loss, not a rendering artifact. See the
        # "Cobertura mensual" chart's navy "Recarga de batería" segment: this
        # is exactly the gap between that segment and the green generation bar.
        curtailed_kwh += max(0.0, gen_kwh * round_trip_eff - charge_in)
        if soc_kwh >= capacity_kwh - epsilon:
            days_full += 1
        soc_kwh -= daily_kwh_consumption
        if soc_kwh < floor_kwh:
            unmet_load_days += 1
            soc_kwh = floor_kwh  # can't physically go lower — real systems load-shed instead
        min_soc_kwh = min(min_soc_kwh, soc_kwh)

        if soc_kwh < target_kwh:
            current_streak += 1
            low_streak = max(low_streak, current_streak)
        else:
            current_streak = 0

    n_days = len(daily_generation_kwh)
    return {
        "min_soc_actual_pct": round(max(0.0, min_soc_kwh / capacity_kwh * 100), 1),
        "days_full_pct": round(days_full / n_days * 100, 1),
        "unmet_load_days": unmet_load_days,
        "longest_low_soc_streak_days": low_streak,
        "utilization_pct": round((1 - curtailed_kwh / total_generation_kwh) * 100, 1) if total_generation_kwh > 0 else 0.0,
        "total_generation_kwh": round(total_generation_kwh, 1),
        "curtailed_kwh": round(curtailed_kwh, 1),
        # Energy actually stored into the battery each day (post round-trip
        # loss, clipped at capacity) — not read by the scenario search, only
        # by the PDF's monthly coverage chart (wizard/off_grid.py Step 8),
        # which aggregates this into a real "recarga de batería" series
        # instead of a flat max(0, generation-consumption) approximation.
        "daily_charge_in_kwh": daily_charge_in_kwh,
    }


# (scenario_key, min_soc_target_pct, max_unmet_load_days_per_year, growth_extra_strings)
#
# max_unmet_load_days replaced the original required_months_ok_of_12 (9, 11,
# 12) when scenario validation moved from a monthly-average check to a real
# day-by-day simulation (see simulate_battery_soc()). This is a deliberate
# reinterpretation, not a literal unit conversion: a "bad month" under the
# old monthly-average check just meant the month's average generation fell
# a little short — the battery still cycled normally all month. An "unmet
# load day" under the new simulation means the battery would have actually
# hit its hard DoD floor that day — a real load-shedding event in the field.
# The two aren't the same severity, so the tolerances below were chosen to
# keep each scenario's relative leniency (1 most tolerant, 3 zero-tolerance)
# without pretending a like-for-like scaling exists. Revisit these numbers
# once real installed-site VRM data gives us actual outage tolerance to
# calibrate against.
#
# min_soc_target_pct spacing was widened from the original (20/40/50) after
# real usage showed scenarios 1 and 2 routinely landing on byte-identical
# hardware — size_battery_for_min_soc() rounds usable capacity UP to whole
# battery units (math.ceil), so two genuinely different targets collapse
# onto the same battery count whenever both fall inside the same unit
# bracket. Worked example that surfaced this (daily load ~5.5 kWh/día, 4.8
# kWh battery units): 20% needed 6.9 kWh, 40% needed 9.2 kWh — both round up
# to 2 batteries (9.6 kWh) even though the underlying targets differ by 2.3
# kWh, because neither crosses the next 4.8 kWh boundary. No fixed set of
# percentages can *guarantee* separation for every possible daily load/
# battery-unit combination — the boundary a given project needs to clear is
# itself a function of both — but wider gaps make a collision meaningfully
# less likely across the typical small/medium off-grid residential range
# this tool targets (checked against 4.6–5.75 kWh/día daily loads with 4.8
# kWh battery units: 20/55/75 keeps all three scenarios on distinct battery
# counts throughout that range, where 20/40/50 collided).
#
# Real tradeoff, not just a label change: scenario 2 ("Recomendado") now
# targets a materially shallower daily cycle (45% DoD vs the old 60%), which
# is gentler on the battery but generally recommends more battery capacity
# by default than before — a real cost increase on the default "recommended"
# quote, traded for scenarios that actually look different from each other.
_RELIABILITY_SCENARIO_DEFS = [
    ("1", 20.0, 15, 0),
    ("2", 55.0, 5, 0),
    ("3", 75.0, 0, 1),
]

# Hybrid-only variant. Off-Grid's array search stops at the smallest array
# that clears each scenario's reliability target — correct there, since
# anything beyond battery+critical-load capacity is genuinely wasted (no
# grid to send it to). Hybrid is different: surplus beyond battery+critical
# loads AC-couples back to the main panel and offsets the rest of the site's
# bill (see estimate_hybrid_savings_pct()), so a bigger array isn't wasted
# the same way — it's more savings. Without a hybrid-specific push, scenarios
# 1 and 2 routinely land on the exact same array (both reliability targets
# were already cleared by the smallest array, so neither search had a reason
# to grow further) — real user feedback, not a hypothetical. Scenario 2
# ("Recomendado") gets +1 string beyond its reliability floor so it visibly
# differs from scenario 1's bare minimum; scenario 3 keeps its already-larger
# growth margin. Scenario 1 stays untouched (0 extra) — it's meant to read
# as the genuine floor to compare everything else against.
_HYBRID_RELIABILITY_SCENARIO_DEFS = [
    ("1", 20.0, 15, 0),
    ("2", 55.0, 5, 1),
    ("3", 75.0, 0, 2),
]

_RELIABILITY_SCENARIO_LABELS = {
    "1": "Mínimo aceptable",
    "2": "Recomendado",
    "3": "Máxima autonomía + crecimiento",
}

# Fraction of installed inverter capacity the connected load has to reach
# before it's flagged as "tight" — chosen so a comfortably-sized system
# (<=80% loaded) never triggers a warning, while a system with little
# headroom does. Applied identically to the scenario-1/2 warning and to
# scenario 3's decision to double inverter count; a single named constant so
# both stay consistent and the threshold is easy to revisit.
_INVERTER_HEADROOM_TRIGGER_PCT = 0.80


def generate_reliability_scenarios(
    panel: dict,
    charge_controller: dict,
    battery: dict,
    daily_kwh_consumption: float,
    daily_kwh_kwp: list[float],
    autonomy_days: float,
    base_inverter_qty: int,
    inverter_kw: float,
    total_connected_load_kw: float,
    max_cc: int = 4,
    scenario_defs: list[tuple] | None = None,
) -> list[dict]:
    """
    Generates the 3 off-grid auto scenarios: each targets a minimum daily SoC
    (battery cycle-depth preference), validated with a real day-by-day
    battery-SoC simulation (simulate_battery_soc()) against a real reference
    year of PVGIS-derived daily generation, rather than nudging string count
    around one target or checking a monthly average.

    Scenario 1 — "Mínimo aceptable": min SoC ~20% (80% daily cycle depth),
        array sized so the simulated year has at most 15 days where the
        battery would hit its hard DoD floor.
    Scenario 2 — "Recomendado": min SoC ~40% (60% cycle depth), at most 5
        unmet-load days across the simulated year.
    Scenario 3 — "Máxima autonomía + crecimiento": min SoC ~50% (50% cycle
        depth, the shallowest/healthiest cycling of the three), zero
        unmet-load days across the simulated year, plus one extra string of
        headroom for future load growth — and, if the connected load is
        already using >=80% of the base inverter setup's capacity, DOUBLE
        the inverter count too. Sizing more panels/battery for growth while
        leaving no headroom on the inverter itself would be a false sense of
        future-proofing, so scenario 3 checks inverter power explicitly
        rather than treating it as fixed. Scenarios 1/2 never add inverters
        (they represent current need, not growth) but are flagged
        (`inverter_headroom_tight`) when the same >=80% condition holds, so
        a thin-margin design doesn't pass by unnoticed.

    See the module comment above _RELIABILITY_SCENARIO_DEFS for why
    "unmet-load days" (a real, simulated blackout risk) replaced the old
    "months OK" monthly-average check — they are not a like-for-like
    conversion, only a preserved relative ordering of leniency.

    `total_connected_load_kw` should be the sum of individually-rated loads
    from Step 4 (quantity × nameplate kW) — it deliberately excludes the
    "Uso general" behavior-driven aggregate, which has no defined peak-watts
    figure (only kWh/día), so this is a lower bound on true simultaneous
    connected load, not a complete one.

    Battery capacity is a design target set independently of array size (it
    only depends on daily consumption and the min-SoC preference), so it's
    computed once per scenario *before* searching for an array — the search
    then validates that array against this fixed capacity, rather than the
    old flow where the array was found first and the battery sized
    separately with no cross-check between them.

    Each returned dict merges the array combo (from
    calculations.mppt.find_array_for_reliability — panels_per_string,
    strings, charge_controller_qty, system_kw, area_m2, voc_total,
    imp_total, within_limits, notes) with a `battery` sub-dict (from
    size_battery_for_min_soc, with min_soc_actual_pct/driven_by now sourced
    from the simulation plus new days_full_pct/unmet_load_days/
    longest_low_soc_streak_days/utilization_pct keys), inverter sizing (`inverter_qty`,
    `inverter_power_w`, `inverter_load_ratio_pct`, `inverter_headroom_tight`,
    `inverter_growth_added`), and scenario metadata. Scenarios whose array
    search fails (e.g. reliability target unreachable within max_cc
    controllers) are omitted from the result.
    """
    from calculations.mppt import find_array_for_reliability

    defs = scenario_defs or _RELIABILITY_SCENARIO_DEFS
    battery_dod_pct = battery.get("dod_pct", 80)
    base_capacity_w = base_inverter_qty * inverter_kw * 1000
    load_ratio = (total_connected_load_kw * 1000 / base_capacity_w) if base_capacity_w > 0 else 0.0
    headroom_tight = load_ratio >= _INVERTER_HEADROOM_TRIGGER_PCT

    results = []
    for label, min_soc_pct, max_unmet_days, growth_strings in defs:
        bank = size_battery_for_min_soc(
            daily_kwh_consumption, min_soc_pct, autonomy_days,
            battery_dod_pct, battery["voltage_v"], battery["capacity_kwh"],
        )
        array_combo = find_array_for_reliability(
            panel, charge_controller, daily_kwh_kwp, daily_kwh_consumption,
            bank["total_kwh_installed"], battery_dod_pct, min_soc_pct, max_unmet_days,
            max_cc, growth_extra_strings=growth_strings,
        )
        if array_combo is None:
            continue
        reliability = array_combo.pop("reliability")
        bank["min_soc_actual_pct"] = reliability["min_soc_actual_pct"]
        bank["days_full_pct"] = reliability["days_full_pct"]
        bank["unmet_load_days"] = reliability["unmet_load_days"]
        bank["longest_low_soc_streak_days"] = reliability["longest_low_soc_streak_days"]
        bank["utilization_pct"] = reliability["utilization_pct"]
        # growth_strings > 0, not label == "3": Off-Grid only ever puts
        # growth on scenario 3, so this is unchanged there. Hybrid's own
        # scenario_defs (_HYBRID_RELIABILITY_SCENARIO_DEFS) also puts growth
        # on scenario 2, and it should get the same inverter-headroom check
        # scenario 3 always did — sizing more panels for extra self-
        # consumption while leaving zero room on the inverter would be the
        # same false sense of security this check exists to catch.
        growth_added = growth_strings > 0 and headroom_tight
        inv_qty = base_inverter_qty * 2 if growth_added else base_inverter_qty
        results.append({
            "scenario": label,
            "label": _RELIABILITY_SCENARIO_LABELS[label],
            "min_soc_target_pct": min_soc_pct,
            "max_unmet_load_days": max_unmet_days,
            "growth_strings": growth_strings,
            "battery": bank,
            "inverter_qty": inv_qty,
            "inverter_power_w": round(inv_qty * inverter_kw * 1000),
            "inverter_load_ratio_pct": round(load_ratio * 100, 1),
            "inverter_headroom_tight": headroom_tight,
            "inverter_growth_added": growth_added,
            **array_combo,
        })
    return results


# ── AC breaker sizing (v1) ───────────────────────────────────────────────────
# Suggests standard 2-pole breaker sizes for the inverter's AC Out (always)
# and AC In / grid-passthrough (hybrid only) circuits, from the demand load
# computed by calculations.load_profile_off_grid.compute_demand_load() and
# the selected inverter's own rated AC current specs (ac_output_current_a /
# ac_input_current_max_a, sourced from the datasheet parser).
#
# Deliberately the practical 2-pole stock list the business actually
# specs/purchases from, not the full NEC 240.6(A) standard-size list (10A up
# to 6000A, used by e.g. a reference NEC conductor/conduit workbook this was
# checked against) — the two serve different purposes. This list is what
# gets shown/quoted; nothing here needs the full code list since no
# conductor/EGC/conduit sizing is being ported (that engine is a separate,
# larger, not-yet-scheduled piece of work).
BREAKER_SIZES_2POLE_V1 = [15, 20, 30, 40, 50, 60, 70, 90, 100, 125, 150, 175, 200]

# Continuous-load factor (NEC 210.19(A)/215.2(A)-style 125%) applied to the
# design current before rounding up to a standard breaker size.
_CONTINUOUS_LOAD_FACTOR = 1.25


def suggest_breaker_2pole(current_a: float) -> int | None:
    """
    Rounds a design current up to the nearest size in BREAKER_SIZES_2POLE_V1.
    Returns None if current_a exceeds the largest listed size (200A) — the
    caller should flag that as out of range for a standard 2-pole breaker
    rather than silently pick something not on the practical stock list.
    """
    for size in BREAKER_SIZES_2POLE_V1:
        if size >= current_a:
            return size
    return None


def compute_peak_current_a(demand_kw: float, voltage_v: float) -> float:
    """
    Peak/design current at the design voltage (120V single-phase or 240V
    split-phase — whichever the system's AC output uses). Assumes PF≈1: no
    power-factor field exists on any equipment record yet, so this is a
    documented simplification, not a precise electrical figure.
    """
    if voltage_v <= 0:
        return 0.0
    return round(demand_kw * 1000 / voltage_v, 2)


def compute_ac_breaker_summary(
    demand_kw: float,
    voltage_v: float,
    inverter: dict,
    inverter_qty: int,
    grid_connected: bool = False,
) -> dict:
    """
    AC Out (always) and AC In (hybrid + grid_connected only) breaker
    suggestions for Step 6's "Resumen eléctrico — carga y protecciones".

    AC Out is sized off the DEMANDED load (peak_current_a × 1.25 continuous
    factor) — this is a design/selection question — then checked against
    what the selected inverter configuration can actually deliver
    (ac_output_current_a × inverter_qty, falling back to a flagged
    kw*1000/output_v estimate when the datasheet field is empty).

    AC In is sized purely off the inverter's own rated max passthrough
    current (ac_input_current_max_a × inverter_qty) — a grid-side protection
    question answered by the equipment's own rating, not by site demand.
    None if the inverter has no passthrough rating on file, or the system
    isn't grid-connected (plain off-grid with no AC input in use).

    Returns:
        {
          "peak_current_a": float,
          "ac_out": {"design_current_a", "breaker_a", "available_current_a",
                     "available_current_estimated", "exceeds_available"},
          "ac_in": same shape, or None,
        }
    """
    peak_current_a = compute_peak_current_a(demand_kw, voltage_v)
    ac_out_design_a = round(peak_current_a * _CONTINUOUS_LOAD_FACTOR, 2)

    rated_out_a = inverter.get("ac_output_current_a")
    available_estimated = rated_out_a is None
    if rated_out_a is None:
        out_v = float(inverter.get("output_v") or voltage_v or 1)
        rated_out_a = (float(inverter.get("kw") or 0) * 1000 / out_v) if out_v else 0.0
    available_out_a = round(float(rated_out_a) * max(1, inverter_qty), 2)

    ac_out = {
        "design_current_a": ac_out_design_a,
        "breaker_a": suggest_breaker_2pole(ac_out_design_a),
        "available_current_a": available_out_a,
        "available_current_estimated": available_estimated,
        "exceeds_available": ac_out_design_a > available_out_a,
    }

    ac_in = None
    if grid_connected:
        rated_in_a = inverter.get("ac_input_current_max_a")
        if rated_in_a:
            ac_in_current_a = round(float(rated_in_a) * max(1, inverter_qty), 2)
            ac_in = {
                "design_current_a": ac_in_current_a,
                "breaker_a": suggest_breaker_2pole(ac_in_current_a),
                "available_current_a": ac_in_current_a,
                "available_current_estimated": False,
                "exceeds_available": False,
            }

    return {"peak_current_a": peak_current_a, "ac_out": ac_out, "ac_in": ac_in}


# ── Hybrid bill-reduction estimate (v1) ──────────────────────────────────────
def estimate_hybrid_savings_pct(
    daily_generation_kwh: float,
    critical_daily_kwh: float,
    whole_home_avg_kwh_month: float,
    daytime_fraction: float,
    tariff_info: dict,
) -> dict:
    """
    Hybrid bill-reduction estimate: how much of the whole home's monthly
    bill the surplus solar (beyond what serves critical loads and charges
    the battery that keeps them alive at night) offsets by AC-coupling back
    to the main panel. Array/battery sizing itself is untouched by this —
    it stays purely reliability-driven (see generate_reliability_scenarios())
    — this is a read-out computed on top of whichever array a scenario
    already lands on, never a second target the search chases.

    Daily-resolution approximation, not hourly — no calibrated hourly load
    curve exists in this codebase (see simulate_battery_soc()'s docstring),
    so the split between "serves critical loads / charges the battery" and
    "available to offset the rest of the house" is a daily-total split, not
    a real simultaneity model. `critical_daily_kwh` (the reliability
    scenario's own daily consumption figure) is netted out of
    daily_generation_kwh BEFORE applying the same zero-export self-
    consumption formula wizard/grid_zero.py's _scenario_projection() uses
    for Grid Zero — without that netting step, the same solar kWh would be
    counted twice: once as a whole-home daytime offset, again as the
    battery charge that avoided a critical-load nighttime grid draw.

    Args:
        daily_generation_kwh: the scenario's own daily array generation
            (already derated — e.g. a reliability scenario's own daily
            generation figure, not system_kw × sun hours recomputed here).
        critical_daily_kwh: critical-load daily consumption (Step 5's
            total_kwh_day for the critical-loads profile) — the portion of
            generation already "spoken for" by the backup design.
        whole_home_avg_kwh_month: the site's total monthly consumption —
            either the critical-load profile's own daily_kwh × 30.4 (panel
            scope "primary": critical loads ARE the whole site) or the
            main panel's own avg_kwh_month (panel scope "secondary").
        daytime_fraction: same AI-estimated fraction Grid Zero uses — share
            of whole-home consumption that happens during solar hours.
        tariff_info: dict shape calculations/tariff_calculator.py:
            estimate_bill_crc() expects (access_charge_crc, bomberos_pct,
            iva_threshold_kwh, tiers).

    Returns:
        {
          "gen_available_kwh_day": float,   # generation left over after critical-load service, per day
          "self_consumed_kwh_month": float,
          "old_bill_crc": float, "new_bill_crc": float,
          "savings_crc": float, "savings_pct": float,
        }
    """
    from calculations.tariff_calculator import estimate_bill_crc

    gen_available_kwh_day = max(0.0, daily_generation_kwh - critical_daily_kwh)
    gen_available_kwh_month = gen_available_kwh_day * 30.4

    daytime_kwh_month = whole_home_avg_kwh_month * daytime_fraction
    self_consumed_kwh_month = min(gen_available_kwh_month, daytime_kwh_month)
    grid_kwh_month = max(0.0, whole_home_avg_kwh_month - self_consumed_kwh_month)

    old_bill = estimate_bill_crc(whole_home_avg_kwh_month, tariff_info)
    new_bill = estimate_bill_crc(grid_kwh_month, tariff_info)
    savings_crc = max(0.0, old_bill - new_bill)
    savings_pct = round(savings_crc / old_bill * 100, 1) if old_bill > 0 else 0.0

    return {
        "gen_available_kwh_day": round(gen_available_kwh_day, 2),
        "self_consumed_kwh_month": round(self_consumed_kwh_month, 1),
        "old_bill_crc": round(old_bill),
        "new_bill_crc": round(new_bill),
        "savings_crc": round(savings_crc),
        "savings_pct": savings_pct,
    }
