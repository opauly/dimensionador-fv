"""Step 6 — Objetivos. Phase 24 Step 3 (PLAN_PHASE24_OBJETIVOS.md §1.1, §1.2, §1.8).

The user states the design goals once; the step shows an equipment-free "sweet spot" for them (Piso / Punto óptimo /
Techo) and is MANDATORY: nothing from Equipos onward opens until the goals are confirmed (`is_ready()`, enforced by
`wizard.py:_guard()` on the server, not just by a disabled button).

`objectives` blob section (a new durable section — see wizard/draft.py):
    {"system_type": "off_grid", "preset": "recomendado" | "minimo" | "maximo" | "personalizado" | "sugerido",
     "goals": {...}, "assumptions": {...Hybrid only...}, "confirmed": bool, "ack_ceiling_pct": float | None,
     "source": "user"}
`goals` holds the calibrated-tier fields for Off-Grid / Hybrid (plus Hybrid's optional `reduction_target_pct`), or
Grid Zero's `reduction_target_pct` / `max_dc_ac_ratio` / `max_system_kwp`. The sweet-spot block is derived on every
render, never stored. Grid Zero's AI daytime fraction is cached in `scratch.obj.daytime`, keyed by a hash of the loads
and city, so it is computed on first view and again only if those change.

Single owner of autonomy (Oscar, 2026-10-06): Off-Grid Step 4 no longer asks for it. Step 6 Equipos (unchanged) still
reads `consumption.autonomy_days`, so confirming Objetivos mirrors the goal there — Off-Grid's `autonomy_days`,
Hybrid's `backup_nights` (its closest equivalent; Hybrid has no autonomy goal of its own).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import fields as dc_fields
from dataclasses import replace

from calculations import design_targets as dt
from calculations.sizing_off_grid import HybridDesignTier, OffGridDesignTier
from wizard import draft

# Drafts already at or past Equipos (new numbering) when this ships have no objectives; they open with default goals
# and are never blocked (plan §1.8, Q7).
GRANDFATHER_FROM_STEP = 7

PRESET_LABELS = {"minimo": "Mínimo aceptable", "recomendado": "Recomendado", "maximo": "Máxima autonomía + crecimiento"}
_PRESET_INDEX = {"minimo": 0, "recomendado": 1, "maximo": 2}

_EXPANSION_OPTIONS = [("none", "Ninguna"), ("one", "Una"), ("two", "Dos")]

# name, label, unit, kind, step, help — in display order.
_N = "number"
_S = "select"
FIELD_SPECS: dict[str, list[dict]] = {
    "off_grid": [
        {"name": "autonomy_days", "label": "Días de autonomía", "unit": "días", "kind": _N, "step": 0.25,
         "help": "Días de consumo que el banco de baterías debe cubrir sin generación solar."},
        {"name": "reserve_soc_pct", "label": "Margen ante falla de FV", "unit": "%", "kind": _N, "step": 5,
         "help": "Capacidad que se compra y no se planifica dentro de la autonomía — tolerancia a una falla de la generación, no una 'reserva SoC' que el sistema aislado no tiene."},
        {"name": "pv_design_factor", "label": "Cobertura FV", "unit": "× consumo diario", "kind": _N, "step": 0.05,
         "help": "Energía diaria que debe entregar el arreglo, como múltiplo del consumo diario. Se dimensiona con el rendimiento promedio anual."},
        {"name": "solar_resource_basis", "label": "Base del recurso solar", "unit": "", "kind": _S,
         "options": [("average_month", "Mes promedio"), ("worst_month", "Peor mes")],
         "help": "Contra qué mes se verifica que el arreglo cumpla su objetivo (no cambia el tamaño recomendado)."},
        {"name": "inverter_loading_target_pct", "label": "Techo de carga del inversor", "unit": "% del pico", "kind": _N, "step": 1,
         "help": "Máximo de la potencia continua del inversor que puede usar el pico simultáneo; deja margen para arranques y cargas futuras."},
        {"name": "growth_energy_pct", "label": "Crecimiento de energía", "unit": "%", "kind": _N, "step": 1,
         "help": "Aumento esperado del consumo. Se reporta como preparación para crecer; no agranda el equipo."},
        {"name": "growth_peak_pct", "label": "Crecimiento de potencia pico", "unit": "%", "kind": _N, "step": 1,
         "help": "Aumento esperado de la demanda pico. Se reporta como preparación para crecer."},
        {"name": "expansion_provision", "label": "Provisión de expansión", "unit": "strings libres", "kind": _S,
         "options": _EXPANSION_OPTIONS, "help": "Entradas de controlador / strings reservados para ampliar el arreglo."},
    ],
    "hybrid": [
        {"name": "reserve_soc_pct", "label": "Reserva de SoC", "unit": "%", "kind": _N, "step": 5,
         "help": "Piso de carga que el inversor reserva para un corte de red (solo se libera si falla la red)."},
        {"name": "backup_nights", "label": "Noches de respaldo", "unit": "noches", "kind": _N, "step": 0.25,
         "help": "Noches de la carga crítica que la batería debe sostener durante un corte."},
        {"name": "cycling_nights", "label": "Noches de ciclado", "unit": "noches", "kind": _N, "step": 0.05,
         "help": "Noches de la carga servida que la ventana diaria de ciclado (sobre la reserva) debe cubrir."},
        {"name": "battery_basis", "label": "Base de la batería", "unit": "", "kind": _S,
         "options": [("critical", "Cargas críticas"), ("critical_plus_comfort", "Críticas + confort"), ("whole_building", "Todo el edificio")],
         "help": "Se registra, pero esta versión del modelo siempre dimensiona con las cargas críticas."},
        {"name": "pv_coverage", "label": "Cobertura FV objetivo", "unit": "× carga servida", "kind": _N, "step": 0.05,
         "help": "Energía diaria del arreglo como múltiplo de la carga que sirve el sistema. Sobre ~1.75× un sitio que no exporta no la aprovecha."},
        {"name": "inverter_islanded_loading_target_pct", "label": "Techo de carga del inversor (isla)", "unit": "% del pico crítico", "kind": _N, "step": 1,
         "help": "Máximo de la potencia del inversor que puede usar el pico de las cargas críticas durante un corte."},
        {"name": "growth_energy_pct", "label": "Crecimiento de energía", "unit": "%", "kind": _N, "step": 1, "help": ""},
        {"name": "growth_peak_pct", "label": "Crecimiento de potencia pico", "unit": "%", "kind": _N, "step": 1, "help": ""},
        {"name": "expansion_provision", "label": "Provisión de expansión", "unit": "strings libres", "kind": _S,
         "options": _EXPANSION_OPTIONS, "help": ""},
        {"name": "reduction_target_pct", "label": "Reducción de kWh objetivo (opcional)", "unit": "% del consumo", "kind": _N, "step": 5, "optional": True,
         "help": "Meta de energía de la red que el sistema debe evitar, sobre el consumo de toda la casa. Déjala vacía si solo importa la cobertura."},
    ],
    "grid_zero": [
        {"name": "reduction_target_pct", "label": "Reducción de kWh mensual objetivo", "unit": "% del consumo", "kind": _N, "step": 5,
         "help": "Meta principal: porcentaje del consumo mensual (promedio anual) que el sistema debe evitar comprar a la red. Se mide en kWh, no en colones."},
        {"name": "max_dc_ac_ratio", "label": "Relación DC/AC máxima", "unit": "", "kind": _N, "step": 0.05,
         "help": "Cuánto puede superar la potencia del arreglo a la del inversor."},
        {"name": "max_system_kwp", "label": "Tope de tamaño del sistema (opcional)", "unit": "kWp", "kind": _N, "step": 0.5, "optional": True,
         "help": "Límite de kWp por techo, presupuesto u otra razón. Déjalo vacío si no hay."},
    ],
}

_TIER_CLASS = {"off_grid": OffGridDesignTier, "hybrid": HybridDesignTier}


# ── small helpers ────────────────────────────────────────────────────────


def _system_type(blob: dict) -> str:
    return (blob.get("meta") or {}).get("system_type") or "grid_zero"


def _num(raw):
    """Form string -> float, blank/garbage -> None."""
    from webapp.wizard_steps.common import to_float

    return to_float(raw, None)


def _range(system_type: str, name: str) -> tuple:
    if name in dt.GOAL_RANGES[system_type]:
        return dt.GOAL_RANGES[system_type][name]
    if name == "reduction_target_pct":
        return dt.GOAL_RANGES["grid_zero"]["reduction_target_pct"]
    return (None, None)


def _tier_field_names(system_type: str) -> list[str]:
    return [f.name for f in dc_fields(_TIER_CLASS[system_type]) if f.name not in ("key", "label")]


def _tier_from_goals(system_type: str, goals: dict):
    base = dt.default_goals(system_type)
    changes = {k: goals.get(k) for k in _tier_field_names(system_type) if k in goals}
    return replace(base, key="C", label="Personalizado", **changes)


def _preset_goals(system_type: str, preset: str) -> dict:
    tier = dt.goal_presets(system_type)[_PRESET_INDEX[preset]]
    goals = {k: getattr(tier, k) for k in _tier_field_names(system_type)}
    if system_type == "hybrid":
        goals["reduction_target_pct"] = None
    return goals


def _default_goals(system_type: str, daytime_fraction: float) -> dict:
    if system_type == "grid_zero":
        g = dt.grid_zero_default_goals(daytime_fraction)
        return {"reduction_target_pct": g.reduction_target_pct, "max_dc_ac_ratio": g.max_dc_ac_ratio, "max_system_kwp": None}
    return _preset_goals(system_type, "recomendado")


def _default_assumptions(system_type: str) -> dict:
    if system_type != "hybrid":
        return {}
    return {"night_load_fraction": dt.HYBRID_ASSUMPTION_DEFAULTS["night_load_fraction"],
            "site_exports_to_grid": dt.HYBRID_ASSUMPTION_DEFAULTS["site_exports_to_grid"]}


def _match_preset(system_type: str, goals: dict) -> str:
    if system_type == "grid_zero":
        return "personalizado"
    for key in PRESET_LABELS:
        want = _preset_goals(system_type, key)
        if all(goals.get(k) == v for k, v in want.items() if k != "reduction_target_pct"):
            return key
    return "personalizado"


# ── Grid Zero's AI daytime fraction (computed on first view, cached) ─────


def _estimate_daytime(loads: list, city: str) -> tuple[float, str]:
    from ai.daytime_fraction import estimate_daytime_fraction_ai

    return estimate_daytime_fraction_ai(loads, city)


def _daytime(blob: dict, vid: str | None) -> dict:
    scratch = blob.get("scratch") or {}
    obj_scratch = scratch.get("obj") or {}
    loads = (scratch.get("s5") or {}).get("loads_data") or []
    city = (blob.get("site") or {}).get("city") or "Costa Rica"
    key = hashlib.sha1(json.dumps([loads, city], sort_keys=True, default=str).encode()).hexdigest()[:16]
    cached = obj_scratch.get("daytime") or {}
    if cached.get("key") == key and cached.get("fraction"):
        return cached
    fraction, note = _estimate_daytime(loads, city)
    fresh = {"key": key, "fraction": float(fraction), "note": note}
    if vid:
        draft.patch(vid, "scratch", {"obj": {**obj_scratch, "daytime": fresh}})
    return fresh


# ── sizing inputs read from the earlier steps ────────────────────────────


def _inputs(blob: dict, system_type: str) -> dict:
    """Everything the sweet-spot formulas need from Steps 3-5, or `missing` messages when something isn't there."""
    consumption = blob.get("consumption") or {}
    site = blob.get("site") or {}
    monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp") or []
    missing: list[str] = []

    if system_type == "grid_zero":
        # Grid Zero Step 6 falls back to 127 kWh/kWp/month when PVGIS isn't there; this block does the same.
        avg_kwh = float(consumption.get("avg_kwh") or 0)
        if avg_kwh <= 0:
            missing.append("Falta el consumo mensual promedio (Paso 5).")
        avg_irr = sum(monthly) / 12 if len(monthly) == 12 else 127.0
        return {"missing": missing, "avg_kwh_month": avg_kwh, "avg_irradiance_kwh_kwp_month": avg_irr}

    if len(monthly) != 12:
        missing.append("Falta la irradiancia PVGIS del sitio (Paso 3).")

    from calculations.load_profile_off_grid import compute_demand_load

    profile = consumption.get("profile") or {}
    lines = profile.get("lines") or []
    if not lines:
        missing.append("Falta el perfil de demanda diaria (Paso 5).")
    peak = compute_demand_load(lines)["total_demand_kw"] if lines else 0.0

    if system_type == "off_grid":
        daily = float(consumption.get("daily_kwh") or 0)
        if daily <= 0 and lines:
            missing.append("El consumo diario calculado es 0 (Paso 5).")
        return {"missing": missing, "daily_kwh": daily, "peak_kw": peak, "monthly_kwh_kwp": monthly}

    # hybrid — same derivation the generator's own test page uses for the whole-home figures
    critical_daily = float(consumption.get("daily_kwh_diversified", consumption.get("daily_kwh", 0.0)) or 0)
    main_panel = consumption.get("main_panel") or {}
    main_daily = float(main_panel.get("avg_kwh_month_diversified", main_panel.get("avg_kwh_month")) or 0.0) / 30.4
    if main_panel.get("mode") == "loads" and (main_panel.get("profile") or {}).get("lines"):
        main_peak = compute_demand_load(main_panel["profile"]["lines"])["total_demand_kw"]
    else:
        main_peak = (main_daily / 24.0) * 3.0
    return {"missing": missing, "critical_daily_kwh": critical_daily, "critical_peak_kw": peak,
            "whole_home_daily_kwh": critical_daily + main_daily, "whole_home_peak_kw": peak + main_peak,
            "monthly_kwh_kwp": monthly}


# ── parsing, validation ──────────────────────────────────────────────────


def parse_form(system_type: str, form, base_goals: dict, base_assumptions: dict) -> tuple[dict, dict]:
    """Goals/assumptions as typed on screen. A blank number is None (validation reports it); an absent field keeps
    its previous value, so a partial POST can never wipe a goal."""
    goals = dict(base_goals)
    for spec in FIELD_SPECS[system_type]:
        key = f"g_{spec['name']}"
        if key not in form:
            continue
        raw = form.get(key)
        if spec["kind"] == _S:
            goals[spec["name"]] = (raw or "").strip() or None
        else:
            goals[spec["name"]] = _num(raw)
    assumptions = dict(base_assumptions)
    if system_type == "hybrid":
        if "a_night_load_pct" in form:
            pct = _num(form.get("a_night_load_pct"))
            assumptions["night_load_fraction"] = None if pct is None else pct / 100.0
        assumptions["site_exports_to_grid"] = form.get("a_site_exports") == "on"
    return goals, assumptions


def _status(system_type: str, goals: dict, assumptions: dict, daytime_fraction: float) -> dict:
    """{"errors": [...], "needs_ack": bool, "ceiling_pct": float | None}."""
    if system_type == "grid_zero":
        g = dt.GridZeroGoals(
            reduction_target_pct=goals.get("reduction_target_pct"),
            max_dc_ac_ratio=goals.get("max_dc_ac_ratio"), max_system_kwp=goals.get("max_system_kwp"))
        st = dt.grid_zero_goal_status(g, daytime_fraction)
        return {"errors": st["errors"], "needs_ack": st["needs_acknowledgement"], "ceiling_pct": st["ceiling_pct"]}

    errors = dt.validate_goals(system_type, _tier_from_goals(system_type, goals))
    needs_ack, ceiling = False, None
    if system_type == "hybrid":
        r = goals.get("reduction_target_pct")
        lo, hi = dt.GOAL_RANGES["grid_zero"]["reduction_target_pct"]
        ceiling = dt.grid_zero_ceiling_pct(dt.HYBRID_ASSUMPTION_DEFAULTS["daytime_fraction"])
        if r is not None:
            if not (lo <= r <= hi):
                errors.append(f"reduction_target_pct: debe estar entre {lo:g} y {hi:g} (recibido {r:g})")
            elif r > ceiling + 1e-9:
                needs_ack = True
        night = assumptions.get("night_load_fraction")
        nlo, nhi = dt.NIGHT_LOAD_FRACTION_RANGE
        if night is None or not (nlo <= night <= nhi):
            errors.append(f"night_load_fraction: debe estar entre {nlo * 100:g}% y {nhi * 100:g}%")
    return {"errors": errors, "needs_ack": needs_ack, "ceiling_pct": ceiling}


# ── the sweet-spot block ─────────────────────────────────────────────────


def _fmt(value, nd=1):
    return "—" if value is None else f"{value:,.{nd}f}"


def _block(system_type: str, goals: dict, assumptions: dict, inputs: dict, daytime_fraction: float) -> dict | None:
    """Piso / Punto óptimo / Techo table + the assumptions behind it. None when the inputs aren't there yet."""
    if inputs["missing"]:
        return None
    if system_type == "grid_zero":
        g = dt.GridZeroGoals(
            reduction_target_pct=float(goals["reduction_target_pct"]), max_dc_ac_ratio=float(goals["max_dc_ac_ratio"]),
            max_system_kwp=goals.get("max_system_kwp"))
        band = dt.grid_zero_target_band(
            g, avg_kwh_month=inputs["avg_kwh_month"],
            avg_irradiance_kwh_kwp_month=inputs["avg_irradiance_kwh_kwp_month"], daytime_fraction=daytime_fraction)
        cols = [band["piso"], band["optimo"], band["techo"]]
        rows = [
            {"label": "Paneles (potencia DC)", "unit": "kWp", "values": [_fmt(c["system_kw"]) for c in cols]},
            {"label": "Inversor (potencia AC)", "unit": "kW", "values": [_fmt(c["inverter_kw"]) for c in cols]},
            {"label": "Reducción de kWh que entrega", "unit": "%", "values": [_fmt(c["reduction_pct"]) for c in cols]},
        ]
        notes = [f"Techo alcanzable sin baterías: {_fmt(band['optimo']['ceiling_pct'])}% — solo el consumo diurno "
                 f"({_fmt(daytime_fraction * 100, 0)}% del total) puede servirse con solar sin exportar.",
                 "Modelo de promedio mensual con cero exportación, el mismo que usa el paso de Equipos."]
        if not band["optimo"]["attainable"]:
            notes.append("La meta excede ese techo: el tamaño mostrado entrega el techo, no la meta.")
        if band["optimo"]["capped_by_max_kwp"]:
            notes.append("El tope de tamaño limita el sistema; la reducción mostrada es la que entrega ese tope.")
        return {"rows": rows, "notes": notes}

    tier = _tier_from_goals(system_type, goals)
    if system_type == "off_grid":
        band = dt.offgrid_target_band(tier, daily_kwh=inputs["daily_kwh"], peak_kw=inputs["peak_kw"],
                                      monthly_kwh_kwp=inputs["monthly_kwh_kwp"])
        cols = [band["piso"], band["optimo"], band["techo"]]
        rows = [
            {"label": "Paneles (potencia DC)", "unit": "kWp", "values": [_fmt(c["system_kw"]) for c in cols]},
            {"label": "Batería (capacidad nominal)", "unit": "kWh", "values": [_fmt(c["battery_nominal_kwh"]) for c in cols]},
            {"label": "Inversor (potencia AC continua)", "unit": "kW", "values": [_fmt(c["inverter_kw"]) for c in cols]},
        ]
        a = band["optimo"]["assumptions"]
        notes = [f"Consumo {_fmt(inputs['daily_kwh'])} kWh/día · pico {_fmt(inputs['peak_kw'])} kW.",
                 f"Batería con DoD de referencia {_fmt(a['reference_battery_dod_pct'], 0)}% (ventana usable {_fmt(a['usable_window_pct'], 0)}%); "
                 "el DoD real se aplica al elegir la batería.",
                 f"Paneles según el rendimiento promedio anual × PR {a['array_pr']}. Inversor = pico ÷ {_fmt(a['inverter_loading_target_pct'], 0)}%."]
        if not band["optimo"]["worst_month_covers_load"]:
            notes.append("En el peor mes el arreglo recomendado no alcanza a cubrir el consumo diario.")
        return {"rows": rows, "notes": notes}

    # hybrid
    night = assumptions.get("night_load_fraction")
    kw = dict(critical_daily_kwh=inputs["critical_daily_kwh"], critical_peak_kw=inputs["critical_peak_kw"],
              whole_home_daily_kwh=inputs["whole_home_daily_kwh"], whole_home_peak_kw=inputs["whole_home_peak_kw"],
              monthly_kwh_kwp=inputs["monthly_kwh_kwp"], daytime_fraction=dt.HYBRID_ASSUMPTION_DEFAULTS["daytime_fraction"],
              night_load_fraction=night)
    band = dt.hybrid_target_band(tier, reduction_target_pct=goals.get("reduction_target_pct"), **kw)
    cols = [band["piso"], band["optimo"], band["techo"]]
    rows = [
        {"label": "Paneles (potencia DC)", "unit": "kWp", "values": [_fmt(c["system_kw"]) for c in cols]},
        {"label": "Batería (capacidad nominal)", "unit": "kWh", "values": [_fmt(c["battery_nominal_kwh"]) for c in cols]},
        {"label": "Inversor (potencia AC, en isla)", "unit": "kW", "values": [_fmt(c["inverter_kw"]) for c in cols]},
        {"label": "Reducción de kWh que entrega", "unit": "%", "values": [_fmt(c["kwh_reduction_pct_at_size"]) for c in cols]},
    ]
    a = band["optimo"]["assumptions"]
    notes = [f"Carga crítica {_fmt(inputs['critical_daily_kwh'])} kWh/día (pico {_fmt(inputs['critical_peak_kw'])} kW); "
             f"casa completa {_fmt(inputs['whole_home_daily_kwh'])} kWh/día.",
             f"Carga nocturna {_fmt(a['night_load_fraction'] * 100, 0)}% ({'medida' if a['night_load_fraction_source'] == 'measured' else 'por defecto'}) · "
             f"fracción diurna {_fmt(a['daytime_fraction'] * 100, 0)}% · DoD de referencia {_fmt(band['optimo']['assumptions']['reference_battery_dod_pct'], 0)}%.",
             f"Batería definida por: {'respaldo' if band['optimo']['battery_driven_by'] == 'backup' else 'ciclado diario'}. "
             f"Paneles definidos por: {'meta de reducción de kWh' if band['optimo']['pv_driven_by'] == 'kwh_reduction' else 'cobertura FV'}."]
    if not assumptions.get("site_exports_to_grid") and tier.pv_coverage > dt.NON_EXPORTING_COVERAGE_CEILING:
        notes.append(f"Cobertura {_fmt(tier.pv_coverage, 2)}× supera ~{dt.NON_EXPORTING_COVERAGE_CEILING}×: un sitio que no exporta no aprovecharía el excedente.")
    return {"rows": rows, "notes": notes}


# ── current state, context ───────────────────────────────────────────────


def _current(blob: dict, system_type: str, daytime_fraction: float) -> dict:
    """The goals/assumptions/preset the page should show: the stored ones if they were written for this system type,
    otherwise the pre-fill defaults."""
    stored = blob.get("objectives") or {}
    if stored.get("system_type") == system_type and stored.get("goals"):
        defaults = _default_goals(system_type, daytime_fraction)
        goals = {**defaults, **stored["goals"]}
        assumptions = {**_default_assumptions(system_type), **(stored.get("assumptions") or {})}
        return {"goals": goals, "assumptions": assumptions, "preset": stored.get("preset") or _match_preset(system_type, goals),
                "confirmed": bool(stored.get("confirmed")), "ack_ceiling_pct": stored.get("ack_ceiling_pct"),
                "source": stored.get("source", "user"), "stored": True}
    return {"goals": _default_goals(system_type, daytime_fraction), "assumptions": _default_assumptions(system_type),
            "preset": "sugerido" if system_type == "grid_zero" else "recomendado", "confirmed": False,
            "ack_ceiling_pct": None, "source": "default", "stored": False}


def _daytime_fraction(blob: dict, system_type: str, vid: str | None) -> tuple[float, str]:
    if system_type == "grid_zero":
        d = _daytime(blob, vid)
        return float(d["fraction"]), d.get("note", "")
    return dt.HYBRID_ASSUMPTION_DEFAULTS["daytime_fraction"], ""


def build_context(blob: dict, vid: str | None = None) -> dict:
    blob = blob or {}
    system_type = _system_type(blob)
    fraction, day_note = _daytime_fraction(blob, system_type, vid)
    cur = _current(blob, system_type, fraction)
    goals, assumptions = cur["goals"], cur["assumptions"]
    status = _status(system_type, goals, assumptions, fraction)
    inputs = _inputs(blob, system_type)
    block = _block(system_type, goals, assumptions, inputs, fraction) if not status["errors"] else None

    ack_ok = (not status["needs_ack"]) or cur["ack_ceiling_pct"] == status["ceiling_pct"]
    field_errors = {e.split(":", 1)[0]: e.split(":", 1)[1].strip() for e in status["errors"] if ":" in e}
    fields = [
        {**spec, "value": goals.get(spec["name"]), "error": field_errors.get(spec["name"]),
         "min": _range(system_type, spec["name"])[0], "max": _range(system_type, spec["name"])[1]}
        for spec in FIELD_SPECS[system_type]
    ]
    return {
        "system_type": system_type,
        "fields": fields,
        "presets": ([{"key": k, "label": v, "active": cur["preset"] == k} for k, v in PRESET_LABELS.items()]
                    if system_type != "grid_zero" else []),
        "preset": cur["preset"],
        "assumptions": assumptions,
        "night_load_pct": None if assumptions.get("night_load_fraction") is None else round(assumptions["night_load_fraction"] * 100, 1),
        "block": block,
        "inputs_missing": inputs["missing"],
        "errors": status["errors"],
        "needs_ack": status["needs_ack"],
        "ack_checked": status["needs_ack"] and ack_ok,
        "ceiling_pct": status["ceiling_pct"],
        "daytime_note": day_note,
        "daytime_fraction_pct": round(fraction * 100),
        "confirmed": cur["confirmed"],
        "from_default": cur["source"] == "default" and not cur["stored"],
        "can_continue": not status["errors"] and (not status["needs_ack"] or ack_ok),
    }


# ── actions ──────────────────────────────────────────────────────────────


def recalc(blob: dict, form, vid: str | None = None) -> dict:
    """`paso/6/recalcular` and Atrás: re-parse what is on screen into an `objectives` dict. Never confirms — it keeps
    `confirmed` only when nothing about the goals changed, so editing a confirmed goal blocks Equipos again until it
    is re-confirmed (plan §1.8)."""
    system_type = _system_type(blob)
    fraction, _ = _daytime_fraction(blob, system_type, vid)
    cur = _current(blob, system_type, fraction)

    preset = (form.get("apply_preset") or "").strip()
    if preset in PRESET_LABELS and system_type != "grid_zero":
        goals = {**cur["goals"], **_preset_goals(system_type, preset)}
        assumptions = cur["assumptions"]
        preset_name = preset
    elif form.get("apply_preset") == "sugerido" and system_type == "grid_zero":
        goals, assumptions, preset_name = _default_goals(system_type, fraction), cur["assumptions"], "sugerido"
    else:
        goals, assumptions = parse_form(system_type, form, cur["goals"], cur["assumptions"])
        preset_name = _match_preset(system_type, goals)

    status = _status(system_type, goals, assumptions, fraction)
    unchanged = bool(cur["stored"] and goals == cur["goals"] and assumptions == cur["assumptions"])
    ack_posted = bool(status["needs_ack"] and form.get("ack_unattainable") == "on")
    # Confirmation survives only an edit that changed nothing, and only while any above-ceiling goal is still
    # acknowledged — unticking the box or touching a goal sends the draft back to unconfirmed.
    confirmed = bool(cur["confirmed"] and unchanged and (not status["needs_ack"] or ack_posted))
    return {"system_type": system_type, "preset": preset_name, "goals": goals, "assumptions": assumptions,
            "confirmed": confirmed, "ack_ceiling_pct": status["ceiling_pct"] if ack_posted else None, "source": "user"}


def save_step(blob: dict, form, vid: str | None = None) -> tuple[dict, list[str]]:
    """Siguiente: (objectives, errors). Confirms only when every goal is valid and any above-ceiling goal has been
    explicitly acknowledged; otherwise the edits are kept unconfirmed and `errors` says why."""
    objectives = recalc(blob, form, vid)
    system_type = objectives["system_type"]
    fraction, _ = _daytime_fraction(blob, system_type, vid)
    status = _status(system_type, objectives["goals"], objectives["assumptions"], fraction)
    errors = list(status["errors"])
    # A browser always submits every goal field (blank ones as ""), so a POST that lacks one is not the form —
    # recalc() would silently fall back to the pre-filled defaults and "confirm" goals nobody looked at.
    absent = [spec["name"] for spec in FIELD_SPECS[system_type] if not spec.get("optional") and f"g_{spec['name']}" not in form]
    if absent:
        errors.append("form: Faltan campos de objetivos (" + ", ".join(absent) + ").")
    if status["needs_ack"] and form.get("ack_unattainable") != "on":
        errors.append("ack: La meta de reducción supera lo alcanzable sin baterías — marca la casilla para confirmarla de todos modos.")
    if errors:
        return {**objectives, "confirmed": False}, errors
    ack = status["ceiling_pct"] if status["needs_ack"] else None
    return {**objectives, "confirmed": True, "ack_ceiling_pct": ack, "source": "user"}, []


def mirror_consumption(objectives: dict) -> dict:
    """What Step 6 Equipos (unchanged) still reads from `consumption`: confirming Objetivos writes the autonomy goal
    there so Objetivos stays the only place it is entered."""
    goals = objectives.get("goals") or {}
    if objectives.get("system_type") == "off_grid" and goals.get("autonomy_days") is not None:
        return {"autonomy_days": float(goals["autonomy_days"])}
    if objectives.get("system_type") == "hybrid" and goals.get("backup_nights") is not None:
        return {"autonomy_days": float(goals["backup_nights"])}
    return {}


def is_ready(blob: dict) -> bool:
    """The gate for Equipos and everything after (plan §1.8): goals confirmed for THIS system type, or a draft that
    was already at/past Equipos before objectives existed (grandfathered — it has no `objectives` at all)."""
    blob = blob or {}
    stored = blob.get("objectives")
    if stored:
        return bool(stored.get("confirmed")) and stored.get("system_type") == _system_type(blob)
    return draft.effective_step_reached(blob.get("meta")) >= GRANDFATHER_FROM_STEP


def _cached_fraction(blob: dict, system_type: str) -> float:
    if system_type == "grid_zero":
        daytime = ((blob.get("scratch") or {}).get("obj") or {}).get("daytime") or {}
        return float(daytime.get("fraction") or 0.45)
    return dt.HYBRID_ASSUMPTION_DEFAULTS["daytime_fraction"]


def effective_goals(blob: dict) -> dict:
    """What the goals-vs-design check (a later step) judges against: the confirmed goals, or the defaults — tagged
    `source: "default"` — for a grandfathered draft. Never calls the AI (uses the cached daytime fraction)."""
    system_type = _system_type(blob)
    fraction = _cached_fraction(blob, system_type)
    cur = _current(blob, system_type, fraction)
    return {"system_type": system_type, "goals": cur["goals"], "assumptions": cur["assumptions"],
            "source": "default" if not cur["stored"] else cur["source"], "confirmed": cur["confirmed"],
            "daytime_fraction": fraction}
