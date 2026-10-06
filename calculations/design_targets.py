"""Equipment-free design targets and the sizing formulas they share with the tier scenario generators.
Phase 24 Step 1 (PLAN_PHASE24_OBJETIVOS.md §1.2/§1.3).

Pure module — no `database`, `streamlit` or `flask` imports — so every function here is exercisable with plain
numbers (see `scripts/validate_phase24.py`).

Two layers, deliberately in one module so the two can never disagree (plan §1.3):

1. SHARED FORMULAS — `daily_yield_stats()`, `offgrid_battery_nominal_kwh()`, `pv_sizing()`,
   `inverter_qty_recommended()`, `hybrid_*`. These were lifted verbatim out of
   `calculations/sizing_off_grid.py:generate_design_scenarios()` / `generate_design_scenarios_hybrid()`, which now
   call them. Operation order is preserved exactly — the generators' output is pinned byte-identical by the golden
   check in `scripts/validate_phase24.py`.

2. EQUIPMENT-FREE TARGETS — `offgrid_targets()`, `hybrid_targets()`, `grid_zero_targets()`: the same formulas minus the
   "fit to the chosen equipment" part, driven by a goal set (a calibrated `OffGridDesignTier` / `HybridDesignTier`,
   or a `GridZeroGoals`). Each system type also gets a Piso / Punto óptimo / Techo band (`*_target_band()`): the goals
   shifted by the step sizes the calibrated tiers already have between Mínimo → Recomendado → Máxima, clamped to each
   field's valid range — centered on the user's own goals, not on fixed presets.

What an equipment-free target cannot know is the battery chemistry's own rated depth of discharge. It uses
`REFERENCE_BATTERY_DOD_PCT` (the same 80% the generators fall back to when a battery carries no `dod_pct`), reported
in each result's `assumptions` so it is never hidden.

Circular-import note: this module imports the tier dataclasses/constants from `sizing_off_grid` at module level;
`sizing_off_grid` imports THIS module only inside its two generator functions, never at its top level.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from calculations.sizing_off_grid import (
    _BATTERY_ROUND_TRIP_EFF_DEFAULT,
    _HEALTHY_ARRAY_PR,
    _HYBRID_DESIGN_TIERS,
    _INVERTER_CONVERSION_EFF_DEFAULT,
    _NIGHT_LOAD_FRACTION_DEFAULT,
    _OFF_GRID_DESIGN_TIERS,
    _monthly_to_daily_specific_yield,
    HybridDesignTier,
    OffGridDesignTier,
)

REFERENCE_BATTERY_DOD_PCT = 80.0

# ═══════════════════════════════════════════════════════════════════════════
# 1. Shared formulas (lifted from the tier generators — do not "simplify")
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class YieldStats:
    daily_yields: list[float]       # kWh/kWp/day, one per month
    avg_daily_yield: float
    worst_month_idx: int
    worst_daily_yield: float


def daily_yield_stats(monthly_kwh_kwp: list[float]) -> YieldStats:
    """PVGIS's 12 monthly kWh/kWp totals -> per-day yields, their annual average and the weakest month."""
    daily = _monthly_to_daily_specific_yield(monthly_kwh_kwp)
    avg = sum(daily) / len(daily)
    worst_idx = min(range(len(daily)), key=lambda i: daily[i])
    return YieldStats(daily, avg, worst_idx, daily[worst_idx])


def offgrid_battery_nominal_kwh(
    daily_kwh: float, autonomy_days: float, dod_usable_pct: float,
    battery_round_trip_eff: float, inverter_eff: float,
) -> tuple[float, float]:
    """(usable kWh the autonomy needs, nominal kWh to install) for an off-grid bank."""
    usable_kwh_needed = daily_kwh * autonomy_days
    nominal_kwh_needed = usable_kwh_needed / (
        (dod_usable_pct / 100.0) * battery_round_trip_eff * inverter_eff
    )
    return usable_kwh_needed, nominal_kwh_needed


def pv_sizing(
    daily_kwh_basis: float, coverage_factor: float, avg_daily_yield: float, array_pr: float = _HEALTHY_ARRAY_PR,
) -> tuple[float, float, float]:
    """(target daily kWh, deliverable kWh/kWp/day, target system kW).

    Sized against the ANNUAL AVERAGE yield x the healthy-array PR — that is how the coverage factors were measured
    (see the calibration doc). Worst month is an adequacy gate elsewhere, never the sizing basis."""
    target_daily_kwh = daily_kwh_basis * coverage_factor
    deliverable_per_kw = avg_daily_yield * array_pr
    target_system_kw = (target_daily_kwh / deliverable_per_kw if deliverable_per_kw > 0 else 0.0)
    return target_daily_kwh, deliverable_per_kw, target_system_kw


def inverter_required_kw(peak_kw: float, loading_target_pct: float) -> float:
    """Continuous inverter rating that keeps `peak_kw` at or under the loading ceiling."""
    return peak_kw / (loading_target_pct / 100.0)


def inverter_qty_recommended(peak_kw: float, inverter_kw: float, loading_target_pct: float) -> int | None:
    """How many units of a given inverter clear the loading ceiling (None if the unit has no rating)."""
    return (
        math.ceil(peak_kw / (inverter_kw * loading_target_pct / 100.0))
        if inverter_kw > 0 else None
    )


def hybrid_night_load(critical_daily_kwh: float, night_load_fraction: float | None) -> tuple[float, float]:
    """(night-load fraction applied, one night of the critical load in kWh)."""
    night_frac = (_NIGHT_LOAD_FRACTION_DEFAULT if night_load_fraction is None else float(night_load_fraction))
    night_frac = min(max(night_frac, 0.05), 0.95)
    return night_frac, critical_daily_kwh * night_frac


def hybrid_shiftable_kwh(whole_home_daily_kwh: float, critical_daily_kwh: float, daytime_fraction: float) -> float:
    """Non-critical, non-daytime share of whole-home consumption (what the battery shifts to night)."""
    non_critical_daily_kwh = max(0.0, whole_home_daily_kwh - critical_daily_kwh)
    return non_critical_daily_kwh * (1.0 - daytime_fraction)


def hybrid_battery_layers(
    critical_night_kwh: float, shiftable_daily_kwh: float, *, backup_nights: float, cycling_nights: float,
    reserve_soc_pct: float, backup_usable_pct: float, battery_round_trip_eff: float, inverter_eff: float,
) -> dict:
    """The two independently-sized hybrid battery layers; the larger wins.

    backup layer  — `backup_nights` x one night of the critical load, over the battery's FULL usable window
                    (the Victron reserve is released when the grid fails).
    cycling layer — `cycling_nights` x the whole backed-up night (critical + shiftable), over the window ABOVE the
                    reserve line.
    Returns every intermediate the generator reports; `c_selected_nominal` is None when neither layer is feasible."""
    self_consumption_usable_pct = max(0.0, 100.0 - reserve_soc_pct)
    energy_critical_during_outage = critical_night_kwh * backup_nights
    eff = battery_round_trip_eff * inverter_eff

    backup_infeasible = backup_usable_pct <= 0.0
    c_backup = (
        energy_critical_during_outage / ((backup_usable_pct / 100.0) * eff)
        if not backup_infeasible else None
    )
    served_night_kwh = critical_night_kwh + shiftable_daily_kwh
    c_daily_shift = (
        (cycling_nights * served_night_kwh)
        / ((self_consumption_usable_pct / 100.0) * eff)
        if self_consumption_usable_pct > 0 else None
    )

    candidates = [c for c in (c_backup, c_daily_shift) if c is not None]
    if not candidates:
        return {"c_selected_nominal": None, "backup_infeasible": backup_infeasible,
                "self_consumption_usable_pct": self_consumption_usable_pct, "served_night_kwh": served_night_kwh}
    c_selected_nominal = max(candidates)
    driven_by = "backup" if c_backup is not None and c_backup >= (c_daily_shift or 0) else "daily_shift"
    return {
        "c_selected_nominal": c_selected_nominal,
        "c_backup": c_backup,
        "c_daily_shift": c_daily_shift,
        "driven_by": driven_by,
        "backup_infeasible": backup_infeasible,
        "self_consumption_usable_pct": self_consumption_usable_pct,
        "served_night_kwh": served_night_kwh,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. Goal presets, ranges and validation
# ═══════════════════════════════════════════════════════════════════════════

# Valid range per goal field, used both to validate the Objetivos form and to clamp the Piso/Techo band.
# PROVISIONAL: chosen to bracket the calibrated tiers with generous room; to be confirmed with Oscar when the
# Objetivos form is built (Step 3). Autonomy's 0.5-7 matches the field it replaces in Off-Grid Step 4.
GOAL_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "off_grid": {
        "reserve_soc_pct": (10.0, 60.0), "autonomy_days": (0.5, 7.0), "pv_design_factor": (1.0, 5.0),
        "inverter_loading_target_pct": (40.0, 100.0), "growth_energy_pct": (0.0, 50.0), "growth_peak_pct": (0.0, 50.0),
    },
    "hybrid": {
        "reserve_soc_pct": (10.0, 60.0), "backup_nights": (0.5, 4.0), "cycling_nights": (0.5, 3.0),
        "pv_coverage": (0.8, 2.5), "inverter_islanded_loading_target_pct": (40.0, 100.0),
        "growth_energy_pct": (0.0, 50.0), "growth_peak_pct": (0.0, 50.0),
    },
}

_EXPANSION_ORDER = ["none", "one", "two"]
_OFF_GRID_BASES = ("average_month", "worst_month")
_HYBRID_BASES = ("critical", "critical_plus_comfort", "whole_building")


def goal_presets(system_type: str) -> list:
    """The calibrated Mínimo / Recomendado / Máxima tiers as editable goal sets (fresh copies of frozen records)."""
    if system_type == "off_grid":
        return [replace(t) for t in _OFF_GRID_DESIGN_TIERS]
    if system_type == "hybrid":
        return [replace(t) for t in _HYBRID_DESIGN_TIERS]
    raise ValueError(f"goal_presets() has no calibrated tiers for system_type={system_type!r}")


def default_goals(system_type: str):
    """Recomendado — the pre-fill for the Objetivos form. A pre-fill only: the step is mandatory (plan §1.8), so
    these never count as "set" until the user confirms them."""
    return goal_presets(system_type)[1]


def validate_goals(system_type: str, goals) -> list[str]:
    """Human-readable problems with a goal set (empty list = valid). Used by the Objetivos step's gate."""
    errors: list[str] = []
    for fname, (lo, hi) in GOAL_RANGES[system_type].items():
        value = getattr(goals, fname, None)
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{fname}: falta un valor numérico")
        elif not (lo <= float(value) <= hi):
            errors.append(f"{fname}: debe estar entre {lo:g} y {hi:g} (recibido {value:g})")
    if getattr(goals, "expansion_provision", None) not in _EXPANSION_ORDER:
        errors.append("expansion_provision: debe ser none, one o two")
    if system_type == "off_grid" and getattr(goals, "solar_resource_basis", None) not in _OFF_GRID_BASES:
        errors.append("solar_resource_basis: debe ser average_month o worst_month")
    if system_type == "hybrid" and getattr(goals, "battery_basis", None) not in _HYBRID_BASES:
        errors.append("battery_basis: debe ser critical, critical_plus_comfort o whole_building")
    return errors


# ═══════════════════════════════════════════════════════════════════════════
# 3. Equipment-free targets
# ═══════════════════════════════════════════════════════════════════════════


def offgrid_targets(
    goals: OffGridDesignTier, *, daily_kwh: float, peak_kw: float, monthly_kwh_kwp: list[float],
    reference_dod_pct: float = REFERENCE_BATTERY_DOD_PCT,
    battery_round_trip_eff: float = _BATTERY_ROUND_TRIP_EFF_DEFAULT, inverter_eff: float = _INVERTER_CONVERSION_EFF_DEFAULT,
) -> dict:
    """Off-grid sweet spot: PV kWp, battery kWh and inverter kW for these goals and loads — no equipment chosen."""
    ys = daily_yield_stats(monthly_kwh_kwp)

    dod_usable_pct = min(100.0 - goals.reserve_soc_pct, reference_dod_pct)
    usable_kwh, nominal_kwh = offgrid_battery_nominal_kwh(
        daily_kwh, goals.autonomy_days, dod_usable_pct, battery_round_trip_eff, inverter_eff)

    target_daily_kwh, deliverable_per_kw, system_kw = pv_sizing(
        daily_kwh, goals.pv_design_factor, ys.avg_daily_yield)
    worst_daily_generation = system_kw * ys.worst_daily_yield * _HEALTHY_ARRAY_PR
    worst_month_load_coverage = worst_daily_generation / daily_kwh if daily_kwh > 0 else None

    return {
        "system_type": "off_grid",
        "system_kw": system_kw,
        "battery_nominal_kwh": nominal_kwh,
        "battery_usable_kwh": usable_kwh,
        "inverter_kw": inverter_required_kw(peak_kw, goals.inverter_loading_target_pct),
        "target_daily_generation_kwh": target_daily_kwh,
        "worst_month_load_coverage": worst_month_load_coverage,
        "worst_month_covers_load": bool(worst_month_load_coverage is not None and worst_month_load_coverage >= 1.0),
        "assumptions": {
            "reference_battery_dod_pct": reference_dod_pct,
            "usable_window_pct": round(dod_usable_pct, 1),
            "battery_round_trip_eff": battery_round_trip_eff,
            "inverter_eff": inverter_eff,
            "array_pr": _HEALTHY_ARRAY_PR,
            "solar_basis_for_sizing": "average_month",
            "pv_design_factor": goals.pv_design_factor,
            "autonomy_days": goals.autonomy_days,
            "inverter_loading_target_pct": goals.inverter_loading_target_pct,
        },
    }


def hybrid_targets(
    goals: HybridDesignTier, *, critical_daily_kwh: float, critical_peak_kw: float, whole_home_daily_kwh: float,
    whole_home_peak_kw: float, monthly_kwh_kwp: list[float], daytime_fraction: float = 0.45,
    shiftable_daily_kwh: float | None = None, night_load_fraction: float | None = None, ac_output_v: float = 240.0,
    reference_dod_pct: float = REFERENCE_BATTERY_DOD_PCT,
    battery_round_trip_eff: float = _BATTERY_ROUND_TRIP_EFF_DEFAULT, inverter_eff: float = _INVERTER_CONVERSION_EFF_DEFAULT,
) -> dict:
    """Hybrid sweet spot: PV kWp, battery kWh and islanded inverter kW — no equipment chosen."""
    ys = daily_yield_stats(monthly_kwh_kwp)

    if shiftable_daily_kwh is None:
        shiftable_daily_kwh = hybrid_shiftable_kwh(whole_home_daily_kwh, critical_daily_kwh, daytime_fraction)
    night_frac, critical_night_kwh = hybrid_night_load(critical_daily_kwh, night_load_fraction)

    layers = hybrid_battery_layers(
        critical_night_kwh, shiftable_daily_kwh, backup_nights=goals.backup_nights,
        cycling_nights=goals.cycling_nights, reserve_soc_pct=goals.reserve_soc_pct,
        backup_usable_pct=float(reference_dod_pct), battery_round_trip_eff=battery_round_trip_eff,
        inverter_eff=inverter_eff)

    baseline_daily_kwh = critical_daily_kwh + shiftable_daily_kwh
    target_daily_kwh, _deliverable, system_kw = pv_sizing(baseline_daily_kwh, goals.pv_coverage, ys.avg_daily_yield)

    return {
        "system_type": "hybrid",
        "system_kw": system_kw,
        "battery_nominal_kwh": layers["c_selected_nominal"],
        "battery_driven_by": layers.get("driven_by"),
        "battery_c_backup_kwh": layers.get("c_backup"),
        "battery_c_daily_shift_kwh": layers.get("c_daily_shift"),
        "inverter_kw": inverter_required_kw(critical_peak_kw, goals.inverter_islanded_loading_target_pct),
        # Equipment-dependent: the unit's own rated pass-through current is compared to this in the check strip.
        "grid_passthrough_required_a": whole_home_peak_kw * 1000 / ac_output_v,
        "target_daily_generation_kwh": target_daily_kwh,
        "assumptions": {
            "reference_battery_dod_pct": reference_dod_pct,
            "night_load_fraction": round(night_frac, 3),
            "night_load_fraction_source": "measured" if night_load_fraction is not None else "fleet_default",
            "daytime_fraction": daytime_fraction,
            "shiftable_daily_kwh": round(shiftable_daily_kwh, 2),
            "array_pr": _HEALTHY_ARRAY_PR,
            "pv_coverage": goals.pv_coverage,
            "backup_nights": goals.backup_nights,
            "cycling_nights": goals.cycling_nights,
            "inverter_islanded_loading_target_pct": goals.inverter_islanded_loading_target_pct,
        },
    }


@dataclass(frozen=True)
class GridZeroGoals:
    """Grid Zero has no calibrated tiers — its main goal is the monthly kWh reduction (annual average), measured on
    energy, never on colones (Oscar, 2026-10-06)."""
    reduction_target_pct: float
    max_dc_ac_ratio: float = 1.2           # provisional pre-fill
    max_system_kwp: float | None = None    # optional cap


def grid_zero_ceiling_pct(daytime_fraction: float) -> float:
    """Highest kWh reduction a zero-export system can reach without storage: only the daytime share of consumption
    can ever be served by solar, whatever the array size."""
    return round(daytime_fraction * 100.0, 1)


def grid_zero_default_goals(daytime_fraction: float) -> GridZeroGoals:
    """Pre-fill: 90% of the attainable ceiling, rounded down to a 5-point step. PROVISIONAL — Grid Zero has no
    calibrated tiers to read a default from; it is a pre-fill only (the step is mandatory, plan §1.8)."""
    ceiling = grid_zero_ceiling_pct(daytime_fraction)
    return GridZeroGoals(reduction_target_pct=float(max(5, math.floor(ceiling * 0.9 / 5.0) * 5)))


def grid_zero_targets(
    goals: GridZeroGoals, *, avg_kwh_month: float, avg_irradiance_kwh_kwp_month: float, daytime_fraction: float,
) -> dict:
    """Smallest array whose kWh reduction meets the goal under the zero-export model Step 6 already uses
    (`gen = kWp x average monthly kWh/kWp`, useful = min(gen, avg kWh x daytime fraction)).

    A goal above the ceiling is not silently clamped away: `attainable` is False, `reduction_pct` reports what the
    returned size actually delivers, and the caller (the Objetivos step) decides whether to require an
    acknowledgement (plan §1.8)."""
    ceiling_pct = grid_zero_ceiling_pct(daytime_fraction)
    attainable = goals.reduction_target_pct <= ceiling_pct + 1e-9
    effective_pct = min(goals.reduction_target_pct, ceiling_pct)

    kwh_per_kwp = avg_irradiance_kwh_kwp_month
    system_kw = (effective_pct / 100.0) * avg_kwh_month / kwh_per_kwp if kwh_per_kwp > 0 else 0.0
    capped = goals.max_system_kwp is not None and system_kw > goals.max_system_kwp
    if capped:
        system_kw = float(goals.max_system_kwp)

    gen_kwh_month = system_kw * kwh_per_kwp
    self_consumed = min(gen_kwh_month, avg_kwh_month * daytime_fraction)
    reduction_pct = self_consumed / avg_kwh_month * 100.0 if avg_kwh_month > 0 else 0.0

    return {
        "system_type": "grid_zero",
        "system_kw": system_kw,
        "inverter_kw": system_kw / goals.max_dc_ac_ratio if goals.max_dc_ac_ratio > 0 else None,
        "reduction_target_pct": goals.reduction_target_pct,
        "reduction_pct": reduction_pct,
        "ceiling_pct": ceiling_pct,
        "attainable": attainable,
        "capped_by_max_kwp": capped,
        "assumptions": {
            "daytime_fraction": daytime_fraction,
            "avg_kwh_month": avg_kwh_month,
            "avg_irradiance_kwh_kwp_month": kwh_per_kwp,
            "max_dc_ac_ratio": goals.max_dc_ac_ratio,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 4. Piso / Punto óptimo / Techo
# ═══════════════════════════════════════════════════════════════════════════


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(max(value, lo), hi)


def _shift_tier(goals, system_type: str, direction: int):
    """`goals` shifted one calibrated step down (direction=-1, the Piso) or up (+1, the Techo).

    The step for each numeric field is the signed difference between the calibrated tiers (Recomendado minus Mínimo
    for the Piso, Máxima minus Recomendado for the Techo), so fields that shrink a design as they grow — like the
    inverter loading ceiling, 85/75/68 — move the right way automatically. Results are clamped to the field's range."""
    minimo, recomendado, maxima = goal_presets(system_type)
    steps = (recomendado, minimo) if direction < 0 else (maxima, recomendado)
    changes: dict = {}
    for fname, (lo, hi) in GOAL_RANGES[system_type].items():
        delta = getattr(steps[0], fname) - getattr(steps[1], fname)
        shifted = getattr(goals, fname) - delta if direction < 0 else getattr(goals, fname) + delta
        changes[fname] = round(_clamp(shifted, lo, hi), 4)
    idx = _EXPANSION_ORDER.index(goals.expansion_provision)
    changes["expansion_provision"] = _EXPANSION_ORDER[int(_clamp(idx + direction, 0, len(_EXPANSION_ORDER) - 1))]
    return replace(goals, **changes)


def offgrid_target_band(goals: OffGridDesignTier, **kwargs) -> dict:
    """{"piso", "optimo", "techo"} off-grid targets; `optimo` is exactly the user's goals."""
    return {
        "piso": offgrid_targets(_shift_tier(goals, "off_grid", -1), **kwargs),
        "optimo": offgrid_targets(goals, **kwargs),
        "techo": offgrid_targets(_shift_tier(goals, "off_grid", +1), **kwargs),
    }


def hybrid_target_band(goals: HybridDesignTier, **kwargs) -> dict:
    return {
        "piso": hybrid_targets(_shift_tier(goals, "hybrid", -1), **kwargs),
        "optimo": hybrid_targets(goals, **kwargs),
        "techo": hybrid_targets(_shift_tier(goals, "hybrid", +1), **kwargs),
    }


# Grid Zero has no calibrated tiers to read step sizes from; this spacing is PROVISIONAL (to be set with Oscar).
_GRID_ZERO_BAND_STEP_PTS = 10.0


def grid_zero_target_band(goals: GridZeroGoals, **kwargs) -> dict:
    daytime_fraction = kwargs["daytime_fraction"]
    ceiling = grid_zero_ceiling_pct(daytime_fraction)
    piso = replace(goals, reduction_target_pct=max(5.0, goals.reduction_target_pct - _GRID_ZERO_BAND_STEP_PTS))
    techo = replace(goals, reduction_target_pct=min(ceiling, goals.reduction_target_pct + _GRID_ZERO_BAND_STEP_PTS))
    return {
        "piso": grid_zero_targets(piso, **kwargs),
        "optimo": grid_zero_targets(goals, **kwargs),
        "techo": grid_zero_targets(techo, **kwargs),
    }
