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
from dataclasses import dataclass


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
        unserved_energy_kwh: the actual kWh shortfall summed across every
            unmet_load_day (floor_kwh - soc_kwh before the day gets clamped
            at the floor) — a day count alone can't distinguish a 0.1 kWh
            near-miss from a 5 kWh real shortfall; this is the energy-side
            complement used by run_daily_energy_balance_check() below.
        days_at_reserve_floor: days ending below `target_min_soc_pct` (the
            scenario's softer reserve/preference line, not the hard DoD
            floor) — the day-count companion to longest_low_soc_streak_days.
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
            "unmet_load_days": len(daily_generation_kwh or []), "unserved_energy_kwh": 0.0,
            "days_at_reserve_floor": len(daily_generation_kwh or []), "longest_low_soc_streak_days": 0,
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
    unserved_energy_kwh = 0.0
    days_at_reserve_floor = 0
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
            unserved_energy_kwh += floor_kwh - soc_kwh  # deficit BEFORE the clamp below — the real shortfall
            soc_kwh = floor_kwh  # can't physically go lower — real systems load-shed instead
        min_soc_kwh = min(min_soc_kwh, soc_kwh)

        if soc_kwh < target_kwh:
            days_at_reserve_floor += 1
            current_streak += 1
            low_streak = max(low_streak, current_streak)
        else:
            current_streak = 0

    n_days = len(daily_generation_kwh)
    return {
        "min_soc_actual_pct": round(max(0.0, min_soc_kwh / capacity_kwh * 100), 1),
        "days_full_pct": round(days_full / n_days * 100, 1),
        "unmet_load_days": unmet_load_days,
        "unserved_energy_kwh": round(unserved_energy_kwh, 2),
        "days_at_reserve_floor": days_at_reserve_floor,
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


# ── Non-authoritative verification pass (v1) ─────────────────────────────────
# Authority split, confirmed with Oscar (2026-08-06 — same conversation as
# _OFF_GRID_DESIGN_TIERS below): the static design-tier model DECIDES the
# quoted equipment. This function only checks the ALREADY-SELECTED design
# against a real reference year and raises a flag — it never resizes the
# array/battery and never picks a different scenario. Called after
# generate_design_scenarios()/_hybrid(), not instead of it.
#
# Deliberately does not expose a reliability %, loss-of-load HOURS, event
# counts, or any statistical/probabilistic claim (median/P25 autonomy,
# equivalent-full-cycles, hourly dispatch) — explicitly out of scope per the
# same conversation ("what I would remove from scope"): the daily-resolution
# PVGIS series behind simulate_battery_soc() doesn't support those claims,
# and a quoting tool doesn't need them. Only a qualitative status plus the
# handful of numbers a designer would actually check by hand.
#
# Thresholds below are v1 policy, not physics — same "first pass, tune later"
# caveat as every other _V1 constant in this module.
_YELLOW_STREAK_DAYS_THRESHOLD = 3     # several consecutive low-SoC days
_YELLOW_RESERVE_FLOOR_DAYS_THRESHOLD = 10  # repeatedly touching the reserve across the year
_RED_UNMET_DAYS_THRESHOLD = 5         # more than a handful of real shortfall days/year
_RED_UNSERVED_ENERGY_KWH_THRESHOLD = 5.0   # cumulative shortfall big enough to matter, not a rounding artifact


def run_daily_energy_balance_check(
    daily_generation_kwh: list[float],
    daily_kwh_consumption: float,
    capacity_kwh: float,
    battery_dod_pct: float,
    reserve_soc_pct: float,
    round_trip_eff: float = _BATTERY_ROUND_TRIP_EFFICIENCY,
) -> dict:
    """
    Runs simulate_battery_soc() against an already-selected design and
    classifies the result as green/yellow/red per the rules above — the
    quoting tool's only reliability-adjacent claim, and a qualitative one.

    reserve_soc_pct is the design's own chosen reserve (off-grid: the tier's
    reserve_soc_pct; hybrid: same field, ESS-reserve meaning) — passed
    straight through as simulate_battery_soc()'s target_min_soc_pct.

    Returns:
        {
          "status": "green" | "yellow" | "red",
          "minimum_soc_pct": float,
          "days_at_reserve_floor": int,
          "longest_reserve_floor_streak_days": int,
          "unmet_load_days": int,
          "unserved_energy_kwh": float,
          "energy_served_pct": float,
          "notes": [str, ...],
        }
    """
    sim = simulate_battery_soc(
        daily_generation_kwh, daily_kwh_consumption, capacity_kwh, battery_dod_pct, reserve_soc_pct, round_trip_eff,
    )
    n_days = len(daily_generation_kwh) or 1
    annual_consumption_kwh = daily_kwh_consumption * n_days
    energy_served_pct = (
        round(max(0.0, 1 - sim["unserved_energy_kwh"] / annual_consumption_kwh) * 100, 2)
        if annual_consumption_kwh > 0 else 100.0
    )

    notes: list[str] = []
    if sim["unmet_load_days"] > 0:
        material = (
            sim["unmet_load_days"] >= _RED_UNMET_DAYS_THRESHOLD
            or sim["unserved_energy_kwh"] >= _RED_UNSERVED_ENERGY_KWH_THRESHOLD
        )
        status = "red" if material else "yellow"
        notes.append(
            f"{sim['unmet_load_days']} día(s)/año con energía no servida "
            f"({sim['unserved_energy_kwh']} kWh/año) en el año de referencia simulado."
        )
    elif (
        sim["longest_low_soc_streak_days"] >= _YELLOW_STREAK_DAYS_THRESHOLD
        or sim["days_at_reserve_floor"] >= _YELLOW_RESERVE_FLOOR_DAYS_THRESHOLD
    ):
        status = "yellow"
        notes.append(
            f"La batería opera en o por debajo de la reserva configurada en "
            f"{sim['days_at_reserve_floor']} día(s)/año del año simulado "
            f"(racha más larga: {sim['longest_low_soc_streak_days']} días consecutivos)."
        )
    else:
        status = "green"
        notes.append("El banco de baterías no cruza la reserva configurada en el año de referencia simulado.")

    return {
        "status": status,
        "minimum_soc_pct": sim["min_soc_actual_pct"],
        "days_at_reserve_floor": sim["days_at_reserve_floor"],
        "longest_reserve_floor_streak_days": sim["longest_low_soc_streak_days"],
        "unmet_load_days": sim["unmet_load_days"],
        "unserved_energy_kwh": sim["unserved_energy_kwh"],
        "energy_served_pct": energy_served_pct,
        "notes": notes,
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


# ═══════════════════════════════════════════════════════════════════════════
# Static design-tier scenario model (v2 — replaces the iterative reliability
# search above as the live Step 6 driver; see generate_design_scenarios()
# further down in this module once built).
#
# Authority split, confirmed with Oscar (2026-08-06):
#   - This static model DECIDES the quoted equipment: load energy, coincident
#     peak, reserve SoC, PV design factor, worst-month PVGIS adequacy,
#     inverter headroom and equipment compatibility.
#   - The legacy day-by-day simulation (simulate_battery_soc(), further up in
#     this module) is demoted to a non-authoritative verification pass run
#     AFTER a design is selected — it may raise a green/yellow/red flag on
#     the chosen design, but it never resizes the array/battery or picks a
#     different scenario. See run_daily_energy_balance_check() (planned).
#   - find_array_for_reliability()'s "grow the array until N days/year clear
#     a reliability target" search is retired from the sizing path for the
#     same reason: it would silently compete with the static factors above
#     for authority over the quoted array size. Kept in place, unused by the
#     new path, during the migration.
#   - No generator/genset modeling, no loss-of-load-hours, no unmet-load-day
#     counts, no statistical outage-starting-SoC distribution — the daily
#     PVGIS series this tool has doesn't support those claims. Reliability is
#     expressed qualitatively per tier (see label/description), not as a %.
#
# The tables below are engineering POLICY, not physics — each numeric field
# is a defensible default picked from the middle/conservative end of a wider
# acceptable range (documented per-field), meant to be reviewed and tuned,
# not treated as a derived constant.
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OffGridDesignTier:
    """One design tier's static sizing policy for an off-grid system."""
    key: str
    label: str
    # Lower operational/emergency SoC boundary — NOT a normal daily cycling
    # target. Actual daily cycling depth is an emergent result of load, PV,
    # battery size and weather; this is the floor the design should avoid
    # crossing except under an explicit emergency strategy.
    reserve_soc_pct: float
    # Days of average daily consumption the battery alone must be able to
    # cover, independent of same-day PV production.
    autonomy_days: float
    # Initial PV sizing check: E_PV,target = E_load × pv_design_factor.
    # Verified against PVGIS afterward, not treated as sufficient on its own.
    pv_design_factor: float
    # Which PVGIS monthly figure the design factor gets verified against —
    # "average_month" (annual average) or "worst_month" (lowest-yield month
    # in the monthly series).
    solar_resource_basis: str
    # Target ceiling for coincident peak load as a % of inverter continuous
    # rating — leaves headroom for surge/starting currents and future loads.
    inverter_loading_target_pct: float
    # Client-stated expected future increase in daily energy and peak demand,
    # % — reported as expansion readiness, not auto-applied to equipment size.
    growth_energy_pct: float
    growth_peak_pct: float
    # "none" | "one" | "two" — number of MPPT/string expansion provisions
    # reserved in the design (spare charge-controller input / string slot),
    # reported as expansion readiness alongside the growth %s above.
    expansion_provision: str


# ── Calibration, 2026-08 ────────────────────────────────────────────────────
# Values below are derived from 12 months of VRM data across 9 installed sites
# (Feb-Aug 2026 usable; VRM only retains 1-minute data ~6 months). Full method,
# evidence and caveats: docs/design-calibration-2026-08.md
#
# PROVISIONAL. Off-grid rests on 3 sites, one of which (roberto-villalobos)
# has an array delivering ~70-75% of nameplate capability, so its outcomes
# cannot be read as a verdict on its design. These constants are therefore
# NOT fitted to off-grid outcomes; they are derived from the physics measured
# on healthy hybrid arrays (PV capability, low-sun run statistics, load shape)
# plus an explicit no-grid-backstop margin. See the doc's "Open assumptions".
#
# reserve_soc_pct: 25/35/50 — T1/T3 aligned with the hybrid tiers (engineer
#   decision, 2026-08), T2 trimmed from 40 to 35 after back-testing showed it
#   costs zero real protection (see below), but this does NOT mean the same
#   thing as on a hybrid and the difference matters. On a hybrid this is a
#   real inverter setting: the pack stops there and the grid takes over.
#   Off-grid systems have no min-SoC setting at all — nothing enforces this
#   line, and a bad enough week will discharge straight through it. Here it
#   is purely SIZING HEADROOM: capacity that is bought and deliberately not
#   planned into the autonomy figure.
#
#   What it buys is FAULT TOLERANCE, not weather margin — weather is already
#   covered on the PV side (at 3.0x coverage a 3-day low-sun run at the
#   measured 67% derate still delivers ~2.0x load). The one real failure in
#   the fleet was karen-montealegre-guarda hitting 5% SoC during a 3-day TOTAL
#   PV outage (0.00 kWh/day — an equipment fault, not clouds); its 2.76 days
#   to empty were not enough. T2's 35% reserve still gives 4.29 days to the
#   hard floor (guarda's daily load, 4.97 kWh battery units) — identical to
#   40%, because both round up to the same 3-unit bank. T3's 50% is kept
#   (not trimmed to 40%) precisely because at 40% it collapses onto the same
#   bank as T2 for that load — 45%+ is where a 4th unit actually buys T3 real
#   extra autonomy over T2.
#
#   Cost of the choice, stated plainly: T2 lands at 4.11x nominal per kWh/day
#   of load and T3 at 5.48x, against an installed fleet spanning 1.79-3.19x.
#   Every off-grid quote is therefore larger than anything currently in
#   service. That is a deliberate service-response decision (remote sites,
#   slow visits), not a value fitted to observed outcomes.
#
#   UI note: labelling this "reserva SoC" on an off-grid quote implies a
#   setting the client does not have. Prefer wording like "margen ante falla
#   de FV (dias)" — describe the days-to-empty it buys, not a SoC floor.
# autonomy_days: 2.0/2.25/2.5 days of usable energy. Observed installed
#   usable-kWh per kWh/day of load: 1.70 (villalobos, stressed - but see the
#   array caveat), 2.21 (karen, never stressed), 3.03 (guarda, only failed
#   during a 3-day PV fault).
# pv_design_factor: 3.0/3.25/3.5 x daily load, measured as delivered coverage
#   from a HEALTHY array (kWp x PVGIS_annual x 0.88). Sites in service run
#   3.11-4.19. This is ~2.2x the hybrid factor, which is the point: at 3.0x,
#   a 3-day low-sun run (67% of mean yield, measured) still delivers 2.0x
#   load, so the battery only has to cover nightly cycling rather than the
#   whole run. Below ~1.5x the same run runs a real deficit.
_OFF_GRID_DESIGN_TIERS: list[OffGridDesignTier] = [
    OffGridDesignTier(
        key="1", label="Mínimo aceptable",
        reserve_soc_pct=25.0, autonomy_days=2.0, pv_design_factor=3.00,
        solar_resource_basis="average_month", inverter_loading_target_pct=85.0,
        growth_energy_pct=0.0, growth_peak_pct=0.0, expansion_provision="none",
    ),
    OffGridDesignTier(
        key="2", label="Recomendado",
        reserve_soc_pct=35.0, autonomy_days=2.25, pv_design_factor=3.25,
        solar_resource_basis="worst_month", inverter_loading_target_pct=75.0,
        growth_energy_pct=15.0, growth_peak_pct=15.0, expansion_provision="one",
    ),
    OffGridDesignTier(
        key="3", label="Máxima autonomía + crecimiento",
        reserve_soc_pct=50.0, autonomy_days=2.5, pv_design_factor=3.50,
        solar_resource_basis="worst_month", inverter_loading_target_pct=68.0,
        growth_energy_pct=27.0, growth_peak_pct=27.0, expansion_provision="two",
    ),
]


@dataclass(frozen=True)
class HybridDesignTier:
    """One design tier's static sizing policy for a hybrid (solar->battery->grid) system."""
    key: str
    label: str
    # Victron-ESS-style "minimum SoC unless grid fails": the SoC floor
    # reserved from normal grid-connected self-consumption cycling, released
    # for use only during an outage (subject to the configured emergency
    # behavior). Same mechanism as reserve_soc_pct above, different consumer.
    reserve_soc_pct: float
    # Nights of the backed-up load the usable battery window must carry.
    #
    # This REPLACED backup_autonomy_hours (was 6/12/36 h). The hours model
    # sized for N hours of uninterrupted drain, a scenario the fleet data says
    # does not occur: PV recharges the bank every day an outage runs. During a
    # 33-hour island at vista-atenas-lp-m3 the pack never dropped below 72%
    # SoC — it drained overnight and recovered to 100% by midday, still with
    # no grid. The binding case is therefore ONE NIGHT of load, not N hours.
    # See docs/design-calibration-2026-08.md §"Why backup hours was wrong".
    backup_nights: float
    # Nights of the SERVED night load (critical + shiftable) that the daily
    # cycling window — the range above the reserve line — must carry.
    #
    # This is the layer that actually decides hybrid battery size, and it is
    # directly measurable on installed systems as
    #     (nominal x (100 - reserve_soc) / 100) / night_load_kwh
    # Fleet: rebeca-ruiz-casona 0.97 (best performer), apartamento 1.34,
    # vista-atenas-lp-m1 1.54, m2 1.77, m3 2.91 (over-built, idles at 0.50
    # cycles/day). Tier values span the working part of that range.
    cycling_nights: float
    # "critical" | "critical_plus_comfort" | "whole_building" — which loads
    # the backup figure above is computed against.
    battery_basis: str
    # Target PV coverage: (kWp x PVGIS_annual_daily x PR) / daily load.
    # Replaced the old pv_sizing_objective string + hardcoded margins, which
    # could not express "how much PV is too much" — the thing the data is
    # clearest about (see the exporting/non-exporting note below).
    pv_coverage: float
    # Target ceiling for backed-up coincident peak as a % of the inverter's
    # STANDALONE/islanded continuous rating — checked separately from the
    # grid-connected/passthrough rating (see the dual inverter-mode check).
    inverter_islanded_loading_target_pct: float
    growth_energy_pct: float
    growth_peak_pct: float
    expansion_provision: str


# ── Calibration, 2026-08 ────────────────────────────────────────────────────
# Derived from 5 clean hybrid sites x ~183 usable days each.
# Full evidence: docs/design-calibration-2026-08.md
#
# reserve_soc_pct: 25/35/45 (engineer decision, 2026-08). T1 sits on the
#   observed configured floor (25%, casona). T2's 35% has NO installed system
#   running at it — the fleet's real configured floors are 25% (casona, which
#   already imports 22% from grid, i.e. mildly under-batteried even there) and
#   38-40% (the three Vista meters, comfortable) — 35% is a deliberate
#   interpolation between them, not a measured value, chosen because T2 is the
#   default/recommended sale and the safer end of that gap. T3's 45% is ABOVE
#   anything in the fleet: a deliberate product choice for the maximum-
#   resilience tier (more energy held back for an outage), not a measured
#   value. Note the cost: a higher reserve shrinks the daily cycling window,
#   so the same cycling_nights needs a bigger bank, and the battery is
#   exercised less (fleet cycles/day falls off above ~40% reserve). Was
#   20/45/67 before calibration, 25/40/50 immediately after it.
# backup_nights: 1.0/1.5/2.0 — nights of CRITICAL load the full DoD window
#   must carry with the grid down. Rarely the binding layer (see cycling_nights)
#   but it is the resilience promise the tier makes to the client.
# cycling_nights: 1.0/1.25/1.6 — the layer that actually sets hybrid battery
#   size. Measured directly on installed systems as window/night-load:
#   casona 0.97 (best performer in the fleet, 0.70 cycles/day, one day below
#   20% SoC in 183), apartamento 1.34, m1 1.54, m2 1.77, m3 2.91 (over-built,
#   idles at 0.50 cycles/day). T1 sits at the proven-tight end, T3 below the
#   point where the battery stops being exercised.
# pv_coverage: 1.3/1.5/1.7. Sites in service run 1.32-2.14. Above ~1.7 the
#   extra array is not harvested unless the site EXPORTS: casona and
#   apartamento have the identical 0.42 kWp per kWh/day, but casona sends 49%
#   to the grid and returns PR 0.93 while apartamento, with no export path,
#   returns 0.48. vista-atenas-lp-m1 at 2.14 coverage harvests no more than
#   m3 at 1.32. For an exporting site these ceilings do not apply — surplus
#   is monetised rather than curtailed.
_HYBRID_DESIGN_TIERS: list[HybridDesignTier] = [
    HybridDesignTier(
        key="1", label="Mínimo aceptable",
        reserve_soc_pct=25.0, backup_nights=1.0, cycling_nights=1.0,
        battery_basis="critical", pv_coverage=1.30,
        inverter_islanded_loading_target_pct=85.0,
        growth_energy_pct=0.0, growth_peak_pct=0.0, expansion_provision="none",
    ),
    HybridDesignTier(
        key="2", label="Recomendado",
        reserve_soc_pct=35.0, backup_nights=1.5, cycling_nights=1.25,
        battery_basis="critical_plus_comfort", pv_coverage=1.50,
        inverter_islanded_loading_target_pct=75.0,
        growth_energy_pct=15.0, growth_peak_pct=15.0, expansion_provision="one",
    ),
    HybridDesignTier(
        key="3", label="Máxima autonomía + crecimiento",
        reserve_soc_pct=45.0, backup_nights=2.0, cycling_nights=1.6,
        battery_basis="whole_building", pv_coverage=1.70,
        inverter_islanded_loading_target_pct=68.0,
        growth_energy_pct=27.0, growth_peak_pct=27.0, expansion_provision="two",
    ),
]

# Performance ratio of a healthy array against PVGIS, used to convert a target
# PV coverage into kWp. Measured: rebeca-ruiz-casona runs 0.93 of PVGIS while
# exporting 49% of its output (so it is essentially uncurtailed and the figure
# is a true capability reading); vista-atenas-lp-m3 returns 0.93 of intent.
# 0.88 carries a small margin for soiling and degradation over the design life.
_HEALTHY_ARRAY_PR = 0.88

# Fraction of daily load that lands between 18:00 and 06:00, used when the
# caller does not supply a measured value. Fleet median is 40% (range 17-54%
# across 9 sites), so this is a real default rather than a guess — but it is
# the dominant battery-sizing input, and a site with an unusual profile (a
# daytime-heavy commercial load, say) should override it.
_NIGHT_LOAD_FRACTION_DEFAULT = 0.40

# Fraction of its own mean yield a healthy array still delivers across a
# multi-day low-sun run — the off-grid design case, and measurable from
# grid-tied sites because it is a weather property, not a topology one.
# 1-in-50 values from 3 healthy arrays, Feb-Aug 2026.
_LOW_SUN_DERATE = {1: 0.50, 2: 0.63, 3: 0.67, 5: 0.72, 7: 0.74}

# PV coverage a site with no export path can actually absorb. Beyond this the
# MPPT throttles once the battery is full and the load is served, so the extra
# array never becomes kWh. vista-atenas-lp-m1 sits at 2.14x coverage and
# harvests no more than vista-atenas-lp-m3 at 1.32x.
_NON_EXPORTING_COVERAGE_CEILING = 1.75

# Recharge headroom: what the array has left after serving the daytime load,
# divided by the energy needed to refill that night's discharge. Below 1.0 the
# bank cannot get back to full on a typical day, so it starts each night lower
# than the design assumes; the site then leans on the grid (hybrid) or drifts
# down across consecutive days (off-grid).
#
# This is a TIMING check, not an energy one. On pure energy the recharge is
# nearly free — the battery returns what it took, minus round-trip losses of
# roughly 4% of daily load — and the 1.3-1.7x coverage already absorbs that.
# What the coverage factor does NOT guarantee is that the surplus lands inside
# the solar window, alongside the daytime load, in the same day.
#
# Fleet (hybrid): rebeca-ruiz-apartamento sits at 0.61 and NEVER reached float
# in 183 days while importing 26% from the grid — the clearest case. m1/m2 sit
# at 1.43 (float ~70% of days, ~10% grid), m3 at 2.14 (89%, 2.3% grid).
# Off-grid roberto-villalobos is 0.98, right on the line.
#
# PROVISIONAL: 5 hybrid sites cannot place this threshold precisely, and the
# metric deliberately does not explain every case — rebeca-ruiz-casona has
# ample headroom (2.17) yet still imports 22%, because its constraint is
# battery size, not recharge capability. The two failure modes are separate
# and both are reported.
_RECHARGE_HEADROOM_MIN = 1.0
_RECHARGE_HEADROOM_COMFORTABLE = 1.4



# Typical LiFePO4 round-trip efficiency and typical off-grid inverter
# (DC->AC + AC->DC charging) conversion efficiency — used only as the default
# arguments to generate_design_scenarios() below; neither is read from the
# battery/inverter catalog because those tables don't carry an explicit
# efficiency field today.
_BATTERY_ROUND_TRIP_EFF_DEFAULT = 0.95
_INVERTER_CONVERSION_EFF_DEFAULT = 0.96

_DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _monthly_to_daily_specific_yield(monthly_kwh_kwp: list[float]) -> list[float]:
    """PVGIS's 12 monthly kWh/kWp TOTALS -> 12 average daily kWh/kWp/day figures."""
    return [m / d for m, d in zip(monthly_kwh_kwp, _DAYS_IN_MONTH)]


def generate_design_scenarios(
    panel: dict,
    charge_controller: dict,
    battery: dict,
    inverter: dict,
    daily_kwh_consumption: float,
    peak_demand_kw: float,
    monthly_kwh_kwp: list[float],
    inverter_qty: int = 1,
    max_cc: int = 4,
    battery_round_trip_eff: float = _BATTERY_ROUND_TRIP_EFF_DEFAULT,
    inverter_eff: float = _INVERTER_CONVERSION_EFF_DEFAULT,
    tiers: list[OffGridDesignTier] | None = None,
) -> list[dict]:
    """
    Static design-tier scenario generator — the v2 replacement for
    generate_reliability_scenarios() as Step 6's live driver (see the module
    comment above _OFF_GRID_DESIGN_TIERS for the authority split with the
    legacy day-by-day simulation, which this function does NOT call).

    Sizes each of the 3 design tiers independently from static policy
    factors instead of an iterative reliability search:
      1. Battery — usable capacity down to the tier's reserve SoC must cover
         `autonomy_days` of average consumption, after round-trip and
         inverter conversion losses. The usable-DoD window is capped at the
         battery's own rated dod_pct if that's tighter than the reserve-SoC
         window (whichever constraint is stricter wins, same principle used
         elsewhere in this module).
      2. PV array — sized to a target daily energy (daily_kwh_consumption *
         pv_design_factor), converted to a target kW via PVGIS's own daily
         specific yield for either the annual average or the worst month
         (per tier's solar_resource_basis). PVGIS's monthly_kwh_kwp already
         has the API's configured system loss baked in, so no extra
         derating is applied here on top of it. Both bases are reported
         regardless of which one the tier is anchored to, so "meets worst
         month" is always visible even for tiers sized off the average.
      3. Inverter — peak_demand_kw checked against inverter_qty * inverter
         continuous rating * the tier's loading-target ceiling. If it
         doesn't clear, the qty that WOULD clear it is reported — equipment
         selection stays a human decision, nothing here auto-resizes it.

    Returns one dict per tier (in tier order). No unmet-load-day count, no
    reliability %, no generator/genset logic — every field here is either a
    static input, a derived design number, or a pass/fail against this
    tier's own policy ceiling.
    """
    from calculations.mppt import find_array_for_target_kw

    defs = tiers or _OFF_GRID_DESIGN_TIERS
    daily_yields = _monthly_to_daily_specific_yield(monthly_kwh_kwp)
    avg_daily_yield = sum(daily_yields) / len(daily_yields)
    worst_month_idx = min(range(len(daily_yields)), key=lambda i: daily_yields[i])
    worst_daily_yield = daily_yields[worst_month_idx]

    battery_dod_pct = float(battery.get("dod_pct") or 80)
    battery_capacity_kwh = float(battery["capacity_kwh"])
    inverter_kw = float(inverter["kw"])

    results = []
    for tier in defs:
        # ── 1. Battery ──────────────────────────────────────────────────
        dod_usable_pct = min(100.0 - tier.reserve_soc_pct, battery_dod_pct)
        usable_kwh_needed = daily_kwh_consumption * tier.autonomy_days
        nominal_kwh_needed = usable_kwh_needed / (
            (dod_usable_pct / 100.0) * battery_round_trip_eff * inverter_eff
        )
        battery_count = max(1, math.ceil(nominal_kwh_needed / battery_capacity_kwh))
        total_kwh_installed = round(battery_count * battery_capacity_kwh, 2)
        battery_bank = {
            "battery_count": battery_count,
            "total_kwh_installed": total_kwh_installed,
            "reserve_soc_pct": tier.reserve_soc_pct,
            "dod_usable_pct": round(dod_usable_pct, 1),
            "usable_kwh_for_autonomy": round(usable_kwh_needed, 2),
            "autonomy_days": tier.autonomy_days,
            "capped_by_battery_dod_rating": battery_dod_pct < (100.0 - tier.reserve_soc_pct),
        }

        # ── 2. PV array ─────────────────────────────────────────────────
        # Sized against ANNUAL average yield x the healthy-array PR, because
        # that is how pv_design_factor was measured (delivered coverage =
        # kWp x PVGIS_annual x 0.88 / load; sites in service run 3.11-4.19).
        # Sizing the 3.0-3.5x factor against worst-month yield instead would
        # apply the seasonal margin twice — the factor already contains it.
        # Worst month is still checked below, but as an adequacy GATE (does
        # the weakest month still cover daily consumption?) rather than as the
        # sizing basis.
        target_daily_kwh = daily_kwh_consumption * tier.pv_design_factor
        deliverable_per_kw = avg_daily_yield * _HEALTHY_ARRAY_PR
        target_system_kw = (target_daily_kwh / deliverable_per_kw
                            if deliverable_per_kw > 0 else 0.0)

        array = find_array_for_target_kw(panel, charge_controller, target_system_kw, max_cc=max_cc)
        if array is None:
            results.append({
                "scenario": tier.key,
                "label": tier.label,
                "error": "No existe una combinación serie/paralelo válida para este panel + controlador.",
            })
            continue

        avg_daily_generation = round(array["system_kw"] * deliverable_per_kw, 2)
        worst_daily_generation = round(array["system_kw"] * worst_daily_yield * _HEALTHY_ARRAY_PR, 2)
        basis_generation = worst_daily_generation if tier.solar_resource_basis == "worst_month" else avg_daily_generation
        # The gate that actually matters off-grid: in the weakest month, does
        # the array still out-produce the daily load? Falling below 1.0 here
        # means the bank drains a little every day of that month with no grid
        # to make it up — the failure mode roberto-villalobos lives in
        # (delivered coverage 1.03x, 7 days below 20% SoC).
        worst_month_load_coverage = (worst_daily_generation / daily_kwh_consumption
                                     if daily_kwh_consumption > 0 else None)
        pv_check = {
            "target_daily_kwh": round(target_daily_kwh, 2),
            "pv_coverage_target": tier.pv_design_factor,
            "pv_coverage_actual": (round(avg_daily_generation / daily_kwh_consumption, 2)
                                   if daily_kwh_consumption > 0 else None),
            "assumed_array_pr": _HEALTHY_ARRAY_PR,
            "solar_resource_basis": tier.solar_resource_basis,
            "target_system_kw": round(target_system_kw, 2),
            "avg_month_daily_generation_kwh": avg_daily_generation,
            "worst_month_daily_generation_kwh": worst_daily_generation,
            "worst_month_index": worst_month_idx,
            "worst_month_load_coverage": (round(worst_month_load_coverage, 2)
                                          if worst_month_load_coverage is not None else None),
            "worst_month_covers_load": bool(
                worst_month_load_coverage is not None and worst_month_load_coverage >= 1.0),
            "meets_target_daily_kwh": basis_generation >= target_daily_kwh * 0.98,  # 2% rounding tolerance
        }

        # ── 3. Inverter ─────────────────────────────────────────────────
        available_kw = inverter_kw * inverter_qty
        loading_pct = round(peak_demand_kw / available_kw * 100, 1) if available_kw > 0 else None
        within_inverter_target = loading_pct is not None and loading_pct <= tier.inverter_loading_target_pct
        inverter_qty_recommended = (
            math.ceil(peak_demand_kw / (inverter_kw * tier.inverter_loading_target_pct / 100.0))
            if inverter_kw > 0 else None
        )
        inverter_check = {
            "inverter_qty": inverter_qty,
            "available_kw": round(available_kw, 2),
            "loading_pct": loading_pct,
            "loading_target_pct": tier.inverter_loading_target_pct,
            "within_target": within_inverter_target,
            "inverter_qty_recommended": inverter_qty_recommended,
        }

        results.append({
            "scenario": tier.key,
            "label": tier.label,
            "battery": battery_bank,
            "pv": pv_check,
            "inverter": inverter_check,
            "array": array,
            "expansion_provision": tier.expansion_provision,
            "growth_energy_pct": tier.growth_energy_pct,
            "growth_peak_pct": tier.growth_peak_pct,
            # meets_target_daily_kwh folded in: an array that misses its own
            # tier's PV target (e.g. capped by max_cc) is not a working design,
            # even if the equipment combo itself is electrically valid and the
            # inverter clears its loading target. worst_month_covers_load is
            # deliberately NOT included here — T1 is sized against the average
            # month by design (solar_resource_basis), so failing worst-month
            # coverage there is expected policy, not a broken design; it stays
            # its own dedicated warning instead.
            "within_limits": (
                bool(array.get("within_limits"))
                and within_inverter_target
                and pv_check["meets_target_daily_kwh"]
            ),
        })

    return results


def generate_design_scenarios_hybrid(
    panel: dict,
    charge_controller: dict,
    battery: dict,
    inverter: dict,
    critical_daily_kwh: float,
    critical_peak_kw: float,
    whole_home_daily_kwh: float,
    whole_home_peak_kw: float,
    monthly_kwh_kwp: list[float],
    inverter_qty: int = 1,
    max_cc: int = 4,
    battery_round_trip_eff: float = _BATTERY_ROUND_TRIP_EFF_DEFAULT,
    inverter_eff: float = _INVERTER_CONVERSION_EFF_DEFAULT,
    daytime_fraction: float = 0.45,
    shiftable_daily_kwh: float | None = None,
    ac_output_v: float = 240.0,
    night_load_fraction: float | None = None,
    site_exports_to_grid: bool = False,
    tiers: list[HybridDesignTier] | None = None,
) -> list[dict]:
    """
    Static design-tier scenario generator for hybrid (solar->battery->grid)
    systems — the hybrid counterpart to generate_design_scenarios() above.
    Same authority split: this decides the quoted equipment, the legacy
    day-by-day simulation (if run at all) only flags concerns afterward.

    Recalibrated 2026-08 against 12 months of VRM data from 5 clean hybrid
    sites. Method, evidence and caveats: docs/design-calibration-2026-08.md

    Battery — two capacities computed INDEPENDENTLY, then the larger wins
    (per spec: sizing self-consumption first and growing it to meet backup
    is just an indirect way of arriving at the backup requirement; both
    numbers should stand on their own):
      - C_backup: capacity between the tier's reserve_soc_pct and the
        battery's own absolute DoD floor, sized to carry `backup_nights` x
        ONE NIGHT of the critical load.
        This used to be `backup_autonomy_hours` x the average hourly rate,
        i.e. N hours of uninterrupted drain. The fleet data says that case
        does not occur: PV recharges the bank every day an outage runs, so
        the binding constraint is a single night. Measured outages are p90
        ~60-75 min, worst ~5 h; and during a 33-hour island at
        vista-atenas-lp-m3 the pack never went below 72% SoC because it
        recovered to 100% by midday with the grid still down.
      - C_daily_shift: capacity ABOVE the reserve line, sized to cover
        shiftable_daily_kwh (the non-critical, non-daytime portion of whole-
        home consumption — defaults to (whole_home_daily_kwh -
        critical_daily_kwh) * (1 - daytime_fraction) if not given explicitly).
      - C_selected = max(C_backup, C_daily_shift); battery_count derived from it.

    night_load_fraction: share of the day's load falling 18:00-06:00. This is
    the dominant battery-sizing input and varies 17-54% across the fleet, so
    pass a measured value when one exists; otherwise
    _NIGHT_LOAD_FRACTION_DEFAULT (0.40, the fleet median) is used and the
    result reports which was applied.

    PV — sized from the tier's `pv_coverage` against ANNUAL AVERAGE yield:
        target_kW = coverage x daily_load / (annual_daily_yield x PR)
    with PR = _HEALTHY_ARRAY_PR. Worst-month is reported as supporting
    adequacy info, not the driving constraint (annual self-consumption is
    what matters for a grid-connected system).

    site_exports_to_grid: when False (the default, and the common case here),
    PV above roughly 1.7x coverage is simply not harvested — the MPPT throttles
    once the battery is full and the load is served, so the extra array is
    wasted capex. The scenario reports `pv_surplus_warning` when a tier's
    coverage exceeds what a non-exporting site can absorb. When the site does
    export, that ceiling does not apply and no warning is raised.

    Inverter — TWO separately-checked operating modes, since grid-connected
    passthrough and standalone/islanded output are different electrical
    questions for a hybrid unit:
      - Islanded: critical_peak_kw against inverter_qty * inverter.kw *
        the tier's inverter_islanded_loading_target_pct — this is the
        resilience-critical check (what the inverter must supply alone
        during an outage).
      - Grid-connected: whole_home_peak_kw's current against the inverter's
        own rated ac_input_current_max_a (passthrough/transfer current) —
        only checked if that field is filled in the catalog; reported as
        `validated: False` rather than silently passing if it's missing.

    `battery_basis` (critical/critical_plus_comfort/whole_building) is
    reported per-tier but does NOT yet change which loads are counted here —
    this v1 always sizes off critical_daily_kwh/critical_peak_kw regardless
    of tier. Swapping in a broader load set for tiers 2/3 needs a load-
    selection UI that doesn't exist yet; tracked as a follow-up, not silently
    approximated here.
    """
    from calculations.mppt import find_array_for_target_kw

    defs = tiers or _HYBRID_DESIGN_TIERS
    daily_yields = _monthly_to_daily_specific_yield(monthly_kwh_kwp)
    avg_daily_yield = sum(daily_yields) / len(daily_yields)
    worst_month_idx = min(range(len(daily_yields)), key=lambda i: daily_yields[i])
    worst_daily_yield = daily_yields[worst_month_idx]

    battery_dod_pct = float(battery.get("dod_pct") or 80)
    battery_capacity_kwh = float(battery["capacity_kwh"])
    inverter_kw = float(inverter["kw"])
    abs_floor_pct = 100.0 - battery_dod_pct

    if shiftable_daily_kwh is None:
        non_critical_daily_kwh = max(0.0, whole_home_daily_kwh - critical_daily_kwh)
        shiftable_daily_kwh = non_critical_daily_kwh * (1.0 - daytime_fraction)

    night_frac = (_NIGHT_LOAD_FRACTION_DEFAULT if night_load_fraction is None
                  else float(night_load_fraction))
    night_frac = min(max(night_frac, 0.05), 0.95)
    # One night of the backed-up load — the real backup design case.
    critical_night_kwh = critical_daily_kwh * night_frac

    results = []
    prev_battery_count = 0
    for tier in defs:
        # ── 1. Battery: backup layer and self-consumption layer, independently ──
        # The Victron setting is "minimum SoC UNLESS GRID FAILS": during an
        # outage the reserve is released and the pack may discharge all the
        # way to its real cutoff. So the backup layer gets the FULL usable
        # window (the battery's own DoD), not the thin slice between the
        # reserve line and the floor.
        #
        # Sizing backup against (reserve - floor) was wrong and the back-test
        # caught it: rebeca-ruiz-casona, the best-performing site in the
        # fleet, came out 2.67x larger than what is actually installed and
        # working. It also re-created the tier inversion, because a lower
        # tier's thinner reserve shrinks that denominator faster than its
        # smaller backup_nights shrinks the numerator. Against the full DoD
        # window both layers grow monotonically with tier, so the inversion
        # cannot occur by construction.
        backup_usable_pct = float(battery_dod_pct)
        # Daily cycling happens above the reserve line — that window is what
        # has to absorb the shiftable load without touching the reserve.
        self_consumption_usable_pct = max(0.0, 100.0 - tier.reserve_soc_pct)

        energy_critical_during_outage = critical_night_kwh * tier.backup_nights
        eff = battery_round_trip_eff * inverter_eff

        backup_infeasible = backup_usable_pct <= 0.0
        c_backup = (
            energy_critical_during_outage / ((backup_usable_pct / 100.0) * eff)
            if not backup_infeasible else None
        )
        # The nightly cycling layer serves the WHOLE backed-up night, not just
        # the non-critical shiftable part: with the grid present the critical
        # loads still draw from the battery overnight. Sizing this off
        # shiftable_daily_kwh alone under-counted the real nightly draw.
        served_night_kwh = critical_night_kwh + shiftable_daily_kwh
        c_daily_shift = (
            (tier.cycling_nights * served_night_kwh)
            / ((self_consumption_usable_pct / 100.0) * eff)
            if self_consumption_usable_pct > 0 else None
        )

        candidates = [c for c in (c_backup, c_daily_shift) if c is not None]
        if not candidates:
            results.append({
                "scenario": tier.key,
                "label": tier.label,
                "error": "Reserva de SoC incompatible con el DoD de la batería seleccionada.",
            })
            continue

        c_selected_nominal = max(candidates)
        driven_by = "backup" if c_backup is not None and c_backup >= (c_daily_shift or 0) else "daily_shift"
        battery_count = max(1, math.ceil(c_selected_nominal / battery_capacity_kwh))
        total_kwh_installed = round(battery_count * battery_capacity_kwh, 2)
        # A lower tier's thinner reserve_soc_pct eats into backup_usable_pct's
        # own denominator (reserve_soc_pct - abs_floor_pct) faster than its
        # smaller backup_nights shrinks the numerator, so a "cheaper"
        # tier can mathematically demand a BIGGER battery than the tier above
        # it for some batteries' DoD — a real interaction between the tier
        # table and whatever battery is selected, not a rounding artifact.
        # Deliberately NOT clamped up to match the previous tier: doing so
        # would silently inflate a higher tier's quote to cover a lower
        # tier's own blown-up number. Flagged instead so the engineer sees it.
        tier_inversion_warning = battery_count < prev_battery_count
        prev_battery_count = battery_count
        battery_bank = {
            "battery_count": battery_count,
            "total_kwh_installed": total_kwh_installed,
            "tier_inversion_warning": tier_inversion_warning,
            "reserve_soc_pct": tier.reserve_soc_pct,
            "backup_usable_pct": round(backup_usable_pct, 1),
            "self_consumption_usable_pct": round(self_consumption_usable_pct, 1),
            "c_backup_kwh": round(c_backup, 2) if c_backup is not None else None,
            "c_daily_shift_kwh": round(c_daily_shift, 2) if c_daily_shift is not None else None,
            "driven_by": driven_by,
            "backup_infeasible_with_this_battery": backup_infeasible,
            "backup_nights": tier.backup_nights,
            "cycling_nights": tier.cycling_nights,
            "critical_night_kwh": round(critical_night_kwh, 2),
            "served_night_kwh": round(served_night_kwh, 2),
            "night_load_fraction": round(night_frac, 3),
            "night_load_fraction_source": ("measured" if night_load_fraction is not None
                                           else "fleet_default"),
            "battery_basis": tier.battery_basis,
            "shiftable_daily_kwh": round(shiftable_daily_kwh, 2),
        }

        # ── 2. PV array — annual average is the driving basis for hybrid ──
        # Coverage is expressed against the load the system actually serves
        # (critical + shiftable), converted to kW through the healthy-array PR
        # rather than assuming the array delivers PVGIS in full.
        baseline_daily_kwh = critical_daily_kwh + shiftable_daily_kwh
        target_daily_kwh = baseline_daily_kwh * tier.pv_coverage
        deliverable_per_kw = avg_daily_yield * _HEALTHY_ARRAY_PR
        target_system_kw = (target_daily_kwh / deliverable_per_kw
                            if deliverable_per_kw > 0 else 0.0)

        array = find_array_for_target_kw(panel, charge_controller, target_system_kw, max_cc=max_cc)
        if array is None:
            results.append({
                "scenario": tier.key,
                "label": tier.label,
                "error": "No existe una combinación serie/paralelo válida para este panel + controlador.",
            })
            continue

        # Generation figures use the healthy-array PR too: quoting raw
        # kW x PVGIS overstates what a real array delivers by 7-12%.
        avg_daily_generation = round(array["system_kw"] * deliverable_per_kw, 2)
        worst_daily_generation = round(array["system_kw"] * worst_daily_yield * _HEALTHY_ARRAY_PR, 2)
        actual_coverage = (avg_daily_generation / baseline_daily_kwh
                           if baseline_daily_kwh > 0 else None)
        # Above ~1.7x coverage a non-exporting site cannot absorb the surplus:
        # once the battery is full and the load is served the MPPT throttles,
        # so the extra array is capex that never turns into kWh. Measured:
        # vista-atenas-lp-m1 at 2.14x coverage harvests no more than
        # vista-atenas-lp-m3 at 1.32x.
        pv_surplus_warning = bool(
            not site_exports_to_grid
            and actual_coverage is not None
            and actual_coverage > _NON_EXPORTING_COVERAGE_CEILING
        )
        # Recharge timing: after serving the daytime load, is the leftover
        # generation enough to put back what the night took? See
        # _RECHARGE_HEADROOM_MIN — this is what the coverage factor alone does
        # not guarantee.
        daytime_load_kwh = baseline_daily_kwh * (1.0 - night_frac)
        recharge_needed_kwh = served_night_kwh / eff if eff > 0 else 0.0
        recharge_surplus_kwh = avg_daily_generation - daytime_load_kwh
        recharge_headroom = (recharge_surplus_kwh / recharge_needed_kwh
                             if recharge_needed_kwh > 0 else None)

        pv_check = {
            "pv_coverage_target": tier.pv_coverage,
            "pv_coverage_actual": round(actual_coverage, 2) if actual_coverage is not None else None,
            "assumed_array_pr": _HEALTHY_ARRAY_PR,
            "daytime_load_kwh": round(daytime_load_kwh, 2),
            "recharge_needed_kwh": round(recharge_needed_kwh, 2),
            "recharge_surplus_kwh": round(recharge_surplus_kwh, 2),
            "recharge_headroom": (round(recharge_headroom, 2)
                                  if recharge_headroom is not None else None),
            "recharge_ok": bool(recharge_headroom is not None
                                and recharge_headroom >= _RECHARGE_HEADROOM_MIN),
            "recharge_comfortable": bool(recharge_headroom is not None
                                         and recharge_headroom >= _RECHARGE_HEADROOM_COMFORTABLE),
            "target_daily_kwh": round(target_daily_kwh, 2),
            "target_system_kw": round(target_system_kw, 2),
            "avg_month_daily_generation_kwh": avg_daily_generation,
            "worst_month_daily_generation_kwh": worst_daily_generation,
            "worst_month_index": worst_month_idx,
            "worst_month_adequacy_pct": (
                round(worst_daily_generation / target_daily_kwh * 100, 1) if target_daily_kwh > 0 else None
            ),
            "meets_target_daily_kwh": avg_daily_generation >= target_daily_kwh * 0.98,
            "site_exports_to_grid": site_exports_to_grid,
            "pv_surplus_warning": pv_surplus_warning,
        }

        # ── 3. Inverter — islanded (resilience) and grid-connected (passthrough) ──
        available_islanded_kw = inverter_kw * inverter_qty
        islanded_loading_pct = (
            round(critical_peak_kw / available_islanded_kw * 100, 1) if available_islanded_kw > 0 else None
        )
        within_islanded = (
            islanded_loading_pct is not None
            and islanded_loading_pct <= tier.inverter_islanded_loading_target_pct
        )
        islanded_qty_recommended = (
            math.ceil(critical_peak_kw / (inverter_kw * tier.inverter_islanded_loading_target_pct / 100.0))
            if inverter_kw > 0 else None
        )

        rated_passthrough_a = inverter.get("ac_input_current_max_a")
        grid_connected_check = {"validated": False}
        if rated_passthrough_a:
            passthrough_available_a = round(float(rated_passthrough_a) * inverter_qty, 1)
            whole_home_peak_a = round(whole_home_peak_kw * 1000 / ac_output_v, 1)
            grid_connected_check = {
                "validated": True,
                "whole_home_peak_a": whole_home_peak_a,
                "passthrough_available_a": passthrough_available_a,
                "within_target": whole_home_peak_a <= passthrough_available_a,
            }

        inverter_check = {
            "inverter_qty": inverter_qty,
            "islanded": {
                "available_kw": round(available_islanded_kw, 2),
                "loading_pct": islanded_loading_pct,
                "loading_target_pct": tier.inverter_islanded_loading_target_pct,
                "within_target": within_islanded,
                "inverter_qty_recommended": islanded_qty_recommended,
            },
            "grid_connected": grid_connected_check,
        }

        # meets_target_daily_kwh folded in for the same reason as the off-grid
        # generator above: a PV array that misses its own tier's target (e.g.
        # capped by max_cc) is not a working design. pv_surplus_warning is
        # deliberately excluded — an oversized/uncurtailed array is a cost
        # concern, not a "this design doesn't work" one, and already has its
        # own dedicated warning.
        within_limits = (
            bool(array.get("within_limits"))
            and within_islanded
            and grid_connected_check.get("within_target", True) is not False
            and pv_check["meets_target_daily_kwh"]
        )

        results.append({
            "scenario": tier.key,
            "label": tier.label,
            "battery": battery_bank,
            "pv": pv_check,
            "inverter": inverter_check,
            "array": array,
            "expansion_provision": tier.expansion_provision,
            "growth_energy_pct": tier.growth_energy_pct,
            "growth_peak_pct": tier.growth_peak_pct,
            "within_limits": within_limits,
        })
    return results


# ── Growth / expansion readiness (v1) ────────────────────────────────────────
# Per spec: "a 25% growth allowance does not necessarily mean every component
# is oversized by 25%" — so this does NOT pre-oversize anything. It answers,
# for an ALREADY-SELECTED tier, two separate questions: does the quoted
# battery/inverter already cover the tier's own stated growth_*_pct (energy
# for battery, peak for inverter), and if not, how many more units would it
# take — by rerunning the SAME formula the tier was sized with against the
# grown load, then diffing against what's actually quoted. PV/charge-
# controller string headroom is read from the tier's own expansion_provision
# (already reflected in the array generate_design_scenarios() picked).
# Busbar rating and physical installation space aren't tracked anywhere in
# the equipment catalog — reported as needing manual review, not fabricated.
_SPARE_STRINGS_BY_PROVISION = {"none": 0, "one": 1, "two": 2}


def assess_growth_readiness(
    tier_result: dict,
    battery_capacity_kwh: float,
    battery_dod_pct: float,
    inverter_kw: float,
    daily_kwh_consumption: float,
    peak_demand_kw: float,
    battery_round_trip_eff: float = _BATTERY_ROUND_TRIP_EFF_DEFAULT,
    inverter_eff: float = _INVERTER_CONVERSION_EFF_DEFAULT,
) -> dict:
    """Off-grid growth-readiness report for one tier_result from generate_design_scenarios()."""
    battery = tier_result["battery"]
    inverter = tier_result["inverter"]
    growth_energy_pct = tier_result.get("growth_energy_pct", 0.0)
    growth_peak_pct = tier_result.get("growth_peak_pct", growth_energy_pct)

    grown_daily_kwh = daily_kwh_consumption * (1 + growth_energy_pct / 100.0)
    dod_usable_pct = min(100.0 - battery["reserve_soc_pct"], battery_dod_pct)
    grown_usable_kwh = grown_daily_kwh * battery["autonomy_days"]
    grown_nominal_kwh = grown_usable_kwh / ((dod_usable_pct / 100.0) * battery_round_trip_eff * inverter_eff)
    grown_battery_count = max(1, math.ceil(grown_nominal_kwh / battery_capacity_kwh))
    additional_battery_units = max(0, grown_battery_count - battery["battery_count"])

    grown_peak_kw = peak_demand_kw * (1 + growth_peak_pct / 100.0)
    grown_inverter_qty = (
        math.ceil(grown_peak_kw / (inverter_kw * inverter["loading_target_pct"] / 100.0)) if inverter_kw > 0 else inverter["inverter_qty"]
    )
    additional_inverter_qty = max(0, grown_inverter_qty - inverter["inverter_qty"])

    return {
        "growth_energy_pct": growth_energy_pct,
        "growth_peak_pct": growth_peak_pct,
        "additional_battery_units_needed": additional_battery_units,
        "additional_inverter_qty_needed": additional_inverter_qty,
        "spare_pv_strings_provisioned": _SPARE_STRINGS_BY_PROVISION.get(tier_result.get("expansion_provision"), 0),
        "busbar_physical_space_note": (
            "No verificable con los datos del catálogo actual — revisión manual del ingeniero en sitio."
        ),
    }


def assess_growth_readiness_hybrid(
    tier_result: dict,
    battery_capacity_kwh: float,
    battery_dod_pct: float,
    inverter_kw: float,
    critical_daily_kwh: float,
    critical_peak_kw: float,
    battery_round_trip_eff: float = _BATTERY_ROUND_TRIP_EFF_DEFAULT,
    inverter_eff: float = _INVERTER_CONVERSION_EFF_DEFAULT,
) -> dict:
    """
    Hybrid growth-readiness report — reuses generate_design_scenarios_hybrid()'s
    own C_backup/C_daily_shift split against the grown critical load and the
    tier's own shiftable_daily_kwh (not re-derived, since the daytime_fraction
    default it depends on isn't available here), then diffs against what's
    quoted. Inverter check applies growth_peak_pct to the backed-up/islanded
    peak specifically — the resilience-critical operating mode.
    """
    battery = tier_result["battery"]
    inverter = tier_result["inverter"]
    growth_energy_pct = tier_result.get("growth_energy_pct", 0.0)
    growth_peak_pct = tier_result.get("growth_peak_pct", growth_energy_pct)

    grown_critical_daily_kwh = critical_daily_kwh * (1 + growth_energy_pct / 100.0)
    # Same windows generate_design_scenarios_hybrid() sizes with: backup gets
    # the full DoD (the reserve is released when the grid fails), daily
    # cycling gets the range above the reserve line.
    backup_usable_pct = float(battery_dod_pct)
    self_consumption_usable_pct = max(0.0, 100.0 - battery["reserve_soc_pct"])
    eff = battery_round_trip_eff * inverter_eff

    # Same night-load basis the tier was sized with (see backup_nights), so
    # the growth delta is a like-for-like re-run rather than a second model.
    grown_critical_night_kwh = grown_critical_daily_kwh * battery["night_load_fraction"]
    grown_energy_critical_during_outage = grown_critical_night_kwh * battery["backup_nights"]
    c_backup = (
        grown_energy_critical_during_outage / ((backup_usable_pct / 100.0) * eff) if backup_usable_pct > 0 else None
    )
    grown_served_night_kwh = grown_critical_night_kwh + battery["shiftable_daily_kwh"]
    c_daily_shift = (
        (battery["cycling_nights"] * grown_served_night_kwh)
        / ((self_consumption_usable_pct / 100.0) * eff)
        if self_consumption_usable_pct > 0 else None
    )
    candidates = [c for c in (c_backup, c_daily_shift) if c is not None]
    grown_battery_count = max(1, math.ceil(max(candidates) / battery_capacity_kwh)) if candidates else battery["battery_count"]
    additional_battery_units = max(0, grown_battery_count - battery["battery_count"])

    grown_critical_peak_kw = critical_peak_kw * (1 + growth_peak_pct / 100.0)
    islanded_target_pct = inverter["islanded"]["loading_target_pct"]
    grown_inverter_qty = (
        math.ceil(grown_critical_peak_kw / (inverter_kw * islanded_target_pct / 100.0)) if inverter_kw > 0 else inverter["inverter_qty"]
    )
    additional_inverter_qty = max(0, grown_inverter_qty - inverter["inverter_qty"])

    return {
        "growth_energy_pct": growth_energy_pct,
        "growth_peak_pct": growth_peak_pct,
        "additional_battery_units_needed": additional_battery_units,
        "additional_inverter_qty_needed": additional_inverter_qty,
        "spare_pv_strings_provisioned": _SPARE_STRINGS_BY_PROVISION.get(tier_result.get("expansion_provision"), 0),
        "busbar_physical_space_note": (
            "No verificable con los datos del catálogo actual — revisión manual del ingeniero en sitio."
        ),
    }

    return results
