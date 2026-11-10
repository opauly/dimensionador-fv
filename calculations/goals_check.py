"""Goals-vs-design check: does the equipment the engineer chose meet the goals stated in Objetivos?
Phase 24 Step 4 (PLAN_PHASE24_OBJETIVOS.md §1.4).

Pure module — numbers in, rows out — so every row is verifiable by hand (see `scripts/validate_phase24.py`).
Every achieved figure comes from the same `calculations/design_targets.py` formulas the sweet-spot block uses, solved
for what an INSTALLED design delivers instead of what a goal REQUIRES, so the block and the check cannot disagree.

Status vocabulary (one per row):
    ok     — inside the Piso–Techo band / meets the goal.
    justo  — a hair short: below the Piso by at most TOLERANCE of its value, or short of a goal by at most the
             tolerance (points for kWh goals, a few percent otherwise).
    bajo   — clearly short: the goal is not met.
    sobre  — above the Techo: the goal is met but the extra equipment is over-building.
    info   — worth showing, not a pass/fail.

The tolerances are provisional (to be tuned with Oscar once real quotes have been compared).
"""
from __future__ import annotations

import math

from calculations import design_targets as dt

TOLERANCE = 0.10             # share of the Piso / goal that still reads as "justo"
TOLERANCE_POINTS = 5.0       # percentage points, for kWh-reduction goals and inverter loading
TOLERANCE_RATIO = 0.05       # DC/AC ratio

STATUS_LABELS = {"ok": "Cumple", "justo": "Justo", "bajo": "No cumple", "sobre": "Sobre el máximo", "info": "Informativo"}


# ── status rules ─────────────────────────────────────────────────────────


def range_status(value, piso, techo, tol: float = TOLERANCE) -> str:
    if value is None or piso is None or techo is None:
        return "info"
    if value < piso:
        return "justo" if value >= piso * (1.0 - tol) else "bajo"
    if value > techo:
        return "sobre"
    return "ok"


def at_least_status(achieved, goal, tol: float = TOLERANCE) -> str:
    if achieved is None or goal is None:
        return "info"
    if achieved >= goal:
        return "ok"
    return "justo" if achieved >= goal * (1.0 - tol) else "bajo"


def at_least_points_status(achieved, goal, tol_points: float = TOLERANCE_POINTS) -> str:
    if achieved is None or goal is None:
        return "info"
    if achieved >= goal - 1e-9:
        return "ok"
    return "justo" if achieved >= goal - tol_points else "bajo"


def at_most_status(value, ceiling, tol: float) -> str:
    if value is None or ceiling is None:
        return "info"
    if value <= ceiling + 1e-9:
        return "ok"
    return "justo" if value <= ceiling + tol else "bajo"


def _row(key: str, label: str, achieved: str, target: str, band: str, status: str, note: str = "") -> dict:
    return {"key": key, "label": label, "achieved": achieved, "target": target, "band": band,
            "status": status, "status_label": STATUS_LABELS[status], "note": note}


def _f(value, nd: int = 1) -> str:
    return "—" if value is None else f"{value:,.{nd}f}"


def _band_cols(band: dict, key: str) -> tuple:
    return band["piso"][key], band["optimo"][key], band["techo"][key]


def summarize(rows: list[dict]) -> dict:
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "justo", "bajo", "sobre")}
    parts = []
    if counts["ok"]:
        parts.append(f"{counts['ok']} cumple" if counts["ok"] == 1 else f"{counts['ok']} cumplen")
    if counts["justo"]:
        parts.append(f"{counts['justo']} justo" if counts["justo"] == 1 else f"{counts['justo']} justos")
    if counts["bajo"]:
        parts.append(f"{counts['bajo']} no cumple" if counts["bajo"] == 1 else f"{counts['bajo']} no cumplen")
    if counts["sobre"]:
        parts.append(f"{counts['sobre']} sobre el máximo")
    worst = "bajo" if counts["bajo"] else "justo" if counts["justo"] else "sobre" if counts["sobre"] else "ok"
    return {**counts, "text": " · ".join(parts) or "sin filas", "overall": worst}


# ── Off-Grid ─────────────────────────────────────────────────────────────


def check_offgrid(tier, band: dict, facts: dict, inputs: dict) -> list[dict]:
    """`facts`: system_kw, battery_installed_kwh, battery_dod_pct, inverter_kw_total.
    `inputs`: the sweet-spot inputs (daily_kwh, peak_kw, monthly_kwh_kwp)."""
    daily, peak = inputs["daily_kwh"], inputs["peak_kw"]
    ys = dt.daily_yield_stats(inputs["monthly_kwh_kwp"])
    rows = []

    p, o, t = _band_cols(band, "system_kw")
    rows.append(_row("pv", "Paneles (potencia DC)", f"{_f(facts['system_kw'])} kWp", f"{_f(o)} kWp",
                     f"{_f(p)} – {_f(t)} kWp", range_status(facts["system_kw"], p, t)))

    p, o, t = _band_cols(band, "battery_nominal_kwh")
    rows.append(_row("battery", "Batería (capacidad nominal)", f"{_f(facts['battery_installed_kwh'])} kWh", f"{_f(o)} kWh",
                     f"{_f(p)} – {_f(t)} kWh", range_status(facts["battery_installed_kwh"], p, t)))

    window = min(100.0 - tier.reserve_soc_pct, facts["battery_dod_pct"])
    autonomy = dt.offgrid_autonomy_days_achieved(facts["battery_installed_kwh"], daily, window)
    capped = facts["battery_dod_pct"] < 100.0 - tier.reserve_soc_pct
    rows.append(_row("autonomy", "Autonomía lograda", f"{_f(autonomy, 2)} días", f"{_f(tier.autonomy_days, 2)} días", "meta mínima",
                     at_least_status(autonomy, tier.autonomy_days),
                     f"Ventana usable {_f(window, 0)}%" + (" — limitada por el DoD de esta batería." if capped else ".")))

    p, o, t = _band_cols(band, "inverter_kw")
    rows.append(_row("inverter", "Inversor (potencia AC)", f"{_f(facts['inverter_kw_total'])} kW", f"{_f(o)} kW",
                     f"{_f(p)} – {_f(t)} kW", range_status(facts["inverter_kw_total"], p, t)))
    loading = peak / facts["inverter_kw_total"] * 100.0 if facts["inverter_kw_total"] > 0 else None
    rows.append(_row("loading", "Carga del inversor", f"{_f(loading, 0)}% del pico", f"≤ {_f(tier.inverter_loading_target_pct, 0)}%", "límite de carga",
                     at_most_status(loading, tier.inverter_loading_target_pct, TOLERANCE_POINTS),
                     f"Pico simultáneo {_f(peak)} kW sobre {_f(facts['inverter_kw_total'])} kW instalados."))

    worst_gen = facts["system_kw"] * ys.worst_daily_yield * dt._HEALTHY_ARRAY_PR
    worst_cov = worst_gen / daily if daily > 0 else None
    rows.append(_row("worst", "Peor mes: cobertura del consumo", f"{_f(worst_cov, 2)}×", "≥ 1.00×", "chequeo",
                     "ok" if worst_cov is not None and worst_cov >= 1.0 else "bajo",
                     "El arreglo debe producir al menos el consumo diario incluso en el mes más flojo."))

    rows += _growth_offgrid(tier, facts, inputs, window)
    return rows


def _growth_offgrid(tier, facts, inputs, window) -> list[dict]:
    """Readiness for the stated growth — the equipment is NOT expected to be oversized for it; this reports what
    would have to be added (same spirit as `assess_growth_readiness()`)."""
    g_e, g_p = tier.growth_energy_pct, tier.growth_peak_pct
    if not (g_e or g_p):
        return []
    _, need_nominal = dt.offgrid_battery_nominal_kwh(inputs["daily_kwh"] * (1 + g_e / 100.0), tier.autonomy_days, window,
                                                     dt._BATTERY_ROUND_TRIP_EFF_DEFAULT, dt._INVERTER_CONVERSION_EFF_DEFAULT)
    need_inv = dt.inverter_required_kw(inputs["peak_kw"] * (1 + g_p / 100.0), tier.inverter_loading_target_pct)
    battery_ok = facts["battery_installed_kwh"] >= need_nominal - 1e-9
    inverter_ok = facts["inverter_kw_total"] >= need_inv - 1e-9
    missing = []
    if not battery_ok:
        missing.append(f"batería: faltan ~{_f(need_nominal - facts['battery_installed_kwh'])} kWh")
    if not inverter_ok:
        missing.append(f"inversor: faltan ~{_f(need_inv - facts['inverter_kw_total'])} kW")
    return [_row("growth", f"Crecimiento (+{_f(g_e, 0)}% energía, +{_f(g_p, 0)}% pico)",
                 "cubierto" if not missing else "; ".join(missing), "sin ampliar equipo", "preparación",
                 "ok" if not missing else "info",
                 "Se reporta como preparación para crecer; no se espera sobredimensionar el equipo por esto.")]


# ── Hybrid ───────────────────────────────────────────────────────────────


def check_hybrid(tier, band: dict, facts: dict, inputs: dict, assumptions: dict, reduction_goal) -> list[dict]:
    """`facts`: system_kw, battery_installed_kwh, battery_dod_pct, inverter_kw_total, passthrough_a_total (or None).
    `inputs`: critical_daily_kwh, critical_peak_kw, whole_home_daily_kwh, whole_home_peak_kw, monthly_kwh_kwp."""
    ys = dt.daily_yield_stats(inputs["monthly_kwh_kwp"])
    deliverable = ys.avg_daily_yield * dt._HEALTHY_ARRAY_PR
    daytime = inputs.get("daytime_fraction") or dt.HYBRID_ASSUMPTION_DEFAULTS["daytime_fraction"]
    shiftable = dt.hybrid_shiftable_kwh(inputs["whole_home_daily_kwh"], inputs["critical_daily_kwh"], daytime)
    night_frac, critical_night = dt.hybrid_night_load(inputs["critical_daily_kwh"], assumptions.get("night_load_fraction"))
    rows = []

    p, o, t = _band_cols(band, "system_kw")
    rows.append(_row("pv", "Paneles (potencia DC)", f"{_f(facts['system_kw'])} kWp", f"{_f(o)} kWp",
                     f"{_f(p)} – {_f(t)} kWp", range_status(facts["system_kw"], p, t)))
    p, o, t = _band_cols(band, "battery_nominal_kwh")
    rows.append(_row("battery", "Batería (capacidad nominal)", f"{_f(facts['battery_installed_kwh'])} kWh", f"{_f(o)} kWh",
                     f"{_f(p)} – {_f(t)} kWh", range_status(facts["battery_installed_kwh"], p, t)))

    backup, cycling = dt.hybrid_nights_achieved(
        facts["battery_installed_kwh"], critical_night, shiftable, reserve_soc_pct=tier.reserve_soc_pct,
        backup_usable_pct=float(facts["battery_dod_pct"]))
    rows.append(_row("backup", "Respaldo ante corte (noches de carga crítica)", f"{_f(backup, 2)} noches", f"{_f(tier.backup_nights, 2)} noches",
                     "meta mínima", at_least_status(backup, tier.backup_nights),
                     f"Carga nocturna {_f(night_frac * 100, 0)}% de la carga crítica ({_f(critical_night)} kWh por noche)."))
    rows.append(_row("cycling", "Ciclado diario (noches de carga servida)", f"{_f(cycling, 2)} noches", f"{_f(tier.cycling_nights, 2)} noches",
                     "meta mínima", at_least_status(cycling, tier.cycling_nights),
                     f"Sobre la reserva de {_f(tier.reserve_soc_pct, 0)}% de SoC."))

    p, o, t = _band_cols(band, "inverter_kw")
    rows.append(_row("inverter", "Inversor (potencia AC, en isla)", f"{_f(facts['inverter_kw_total'])} kW", f"{_f(o)} kW",
                     f"{_f(p)} – {_f(t)} kW", range_status(facts["inverter_kw_total"], p, t)))
    loading = inputs["critical_peak_kw"] / facts["inverter_kw_total"] * 100.0 if facts["inverter_kw_total"] > 0 else None
    rows.append(_row("loading", "Carga del inversor en isla", f"{_f(loading, 0)}% del pico crítico",
                     f"≤ {_f(tier.inverter_islanded_loading_target_pct, 0)}%", "límite de carga",
                     at_most_status(loading, tier.inverter_islanded_loading_target_pct, TOLERANCE_POINTS)))
    if facts.get("passthrough_a_total"):
        need_a = band["optimo"]["grid_passthrough_required_a"]
        rows.append(_row("passthrough", "Corriente de paso desde la red", f"{_f(facts['passthrough_a_total'], 0)} A", f"≥ {_f(need_a, 0)} A",
                         "chequeo", "ok" if facts["passthrough_a_total"] >= need_a else "bajo",
                         "Corriente nominal de entrada AC del inversor frente al pico de toda la casa."))

    if reduction_goal is not None:
        achieved = dt.hybrid_reduction_pct(facts["system_kw"], deliverable, inputs["critical_daily_kwh"],
                                           inputs["whole_home_daily_kwh"] * 30.4, daytime)
        rows.append(_row("reduction", "Reducción de kWh de la red", f"{_f(achieved, 0)}%", f"{_f(reduction_goal, 0)}%", "meta",
                         at_least_points_status(achieved, reduction_goal),
                         f"Sobre el consumo de toda la casa; máximo alcanzable sin exportar {_f(dt.grid_zero_ceiling_pct(daytime), 0)}%."))

    coverage = facts["system_kw"] * deliverable / (inputs["critical_daily_kwh"] + shiftable) if (inputs["critical_daily_kwh"] + shiftable) > 0 else None
    if not assumptions.get("site_exports_to_grid") and coverage is not None and coverage > dt.NON_EXPORTING_COVERAGE_CEILING:
        rows.append(_row("surplus", "Cobertura FV en un sitio sin exportación", f"{_f(coverage, 2)}×", f"≤ {dt.NON_EXPORTING_COVERAGE_CEILING}×", "chequeo",
                         "sobre", "Sobre ese múltiplo el excedente no se aprovecha: el MPPT limita la producción."))
    return rows


# ── Grid Zero ────────────────────────────────────────────────────────────


def check_grid_zero(goals: "dt.GridZeroGoals", band: dict, facts: dict, ack: bool) -> list[dict]:
    """`facts`: system_kw, inverter_kw, reduction_pct (Step 6's own projection of the chosen design)."""
    rows = []
    p, o, t = _band_cols(band, "system_kw")
    rows.append(_row("pv", "Paneles (potencia DC)", f"{_f(facts['system_kw'])} kWp", f"{_f(o)} kWp",
                     f"{_f(p)} – {_f(t)} kWp", range_status(facts["system_kw"], p, t)))
    p, o, t = _band_cols(band, "inverter_kw")
    rows.append(_row("inverter", "Inversor (potencia AC)", f"{_f(facts['inverter_kw'])} kW", f"{_f(o)} kW",
                     f"{_f(p)} – {_f(t)} kW", range_status(facts["inverter_kw"], p, t)))
    ratio = facts["system_kw"] / facts["inverter_kw"] if facts["inverter_kw"] > 0 else None
    rows.append(_row("dcac", "Relación DC/AC", _f(ratio, 2), f"≤ {_f(goals.max_dc_ac_ratio, 2)}", "tope",
                     at_most_status(ratio, goals.max_dc_ac_ratio, TOLERANCE_RATIO)))
    ceiling = band["optimo"]["ceiling_pct"]
    rows.append(_row("reduction", "Reducción de kWh mensual", f"{_f(facts['reduction_pct'], 0)}%", f"{_f(goals.reduction_target_pct, 0)}%", "meta",
                     at_least_points_status(facts["reduction_pct"], goals.reduction_target_pct),
                     f"Máximo alcanzable sin baterías {_f(ceiling, 0)}%." + (" Meta por encima del máximo, reconocida." if ack and goals.reduction_target_pct > ceiling else "")))
    if goals.max_system_kwp is not None:
        rows.append(_row("cap", "Tope de tamaño del sistema", f"{_f(facts['system_kw'])} kWp", f"≤ {_f(goals.max_system_kwp)} kWp", "tope",
                         "ok" if facts["system_kw"] <= goals.max_system_kwp + 1e-9 else "bajo"))
    return rows
