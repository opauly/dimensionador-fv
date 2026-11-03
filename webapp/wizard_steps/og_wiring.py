"""Wiring summary for the Off-Grid / Hybrid Equipos step: conductor gauge, OCPD and PVC
conduit per branch, built from the design already saved in the draft.

Reads `blob["equipment"]` (panel, string layout, controller / inverter / battery counts) and
`blob["consumption"]` (demand profile, voltage, grid connection) — never recomputes the
scenario engine — and keeps the only inputs it needs that the design does not know (cable
run lengths) in `blob["scratch"]["wiring"]`. All the sizing maths lives in
`calculations/wiring.py`; this module only maps the design onto branches.

Branches (each sized by `wiring.size_branch`):
  1. PV array -> charge controller   (DC, per controller; combiner box assumed: one pair)
  2. Charge controller -> batteries  (DC, per controller)
  3. Batteries -> inverter           (DC, per inverter)
  4. Inverter -> AC panel            (AC out; breaker taken from the existing AC summary)
  5. Grid -> inverter AC input       (AC in; hybrid with grid connection only)
"""
from __future__ import annotations

import math

from calculations import wiring as W

SCRATCH_KEY = "wiring"

# The 48 V DC equipment (controllers, batteries, inverters) all lands on a Victron Lynx Power In bus,
# which is protected with fuses, not breakers, and only a few ratings are stocked. Sizing is the same;
# the protection is just limited to this set. Only the PV array -> charge controller run uses a
# (DC) breaker.
LYNX_FUSE_SIZES_A = (100, 125, 200, 250)

# Equipment-grounding conductor (EGC) per DC run. The PV run (panels -> controller) carries one with
# its + and − (three conductors); the battery-side runs (controller -> batteries, batteries -> inverter)
# carry just + and −. Each switch independently adds/removes one EGC from that branch's conductor
# count, which changes its conduit fill and the conductor metres in the BOM.
PV_BRANCH_HAS_EGC = True

# What the AC-OUT breaker and conductor are designed from (the other basis is shown next to it):
#   "connected" — 125 % of the connected loads, i.e. every critical circuit loaded at once
#   "demand"    — 125 % of the demand-factor estimate (the v1 demand factors are uncalibrated)
AC_OUT_BASIS = "connected"
BATTERY_DC_BRANCH_HAS_EGC = False

# Cable run lengths in metres. Site-specific, so editable in the UI; these defaults are
# round-number stand-ins in the range the workbook's sample projects use.
DEFAULT_LENGTHS = {
    "pv_cc_m": 15.0,     # PV array -> charge controller
    "cc_bat_m": 2.0,     # charge controller -> battery bank
    "bat_inv_m": 2.0,    # battery bank -> inverter
    "ac_out_m": 10.0,    # inverter -> AC panel
    "ac_in_m": 10.0,     # grid -> inverter AC input
}
LENGTH_LABELS = {
    "pv_cc_m": "Paneles → controlador",
    "cc_bat_m": "Controlador → baterías",
    "bat_inv_m": "Baterías → inversor",
    "ac_out_m": "Inversor → tablero AC",
    "ac_in_m": "Red → entrada AC del inversor",
}


def clean_lengths(saved: dict | None) -> dict[str, float]:
    """Defaults overlaid with any positive saved values (also used for a project's own lengths)."""
    saved = saved or {}
    out = dict(DEFAULT_LENGTHS)
    for key in DEFAULT_LENGTHS:
        try:
            v = float(saved.get(key))
            if v > 0:
                out[key] = v
        except (TypeError, ValueError):
            pass
    return out


def lengths(blob: dict) -> dict[str, float]:
    return clean_lengths(((blob or {}).get("scratch") or {}).get(SCRATCH_KEY))


def lengths_from_form(form) -> dict[str, float]:
    out = {}
    for key, default in DEFAULT_LENGTHS.items():
        try:
            v = float(str(form.get(key, "")).replace(",", "."))
            out[key] = v if v > 0 else default
        except ValueError:
            out[key] = default
    return out


def _f(d: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(d.get(key) if d.get(key) is not None else default)
    except (TypeError, ValueError):
        return default


def _ac_summary(blob: dict, inverter_qty: int):
    """The same AC breaker summary Step 7 already shows, so wire and breaker never disagree."""
    consumption = blob.get("consumption") or {}
    profile_lines = (consumption.get("profile") or {}).get("lines") or []
    if not profile_lines:
        return None
    from calculations.load_profile_off_grid import compute_demand_load
    from calculations.sizing_off_grid import compute_ac_breaker_summary

    eq = blob.get("equipment") or {}
    split = bool((eq.get("split_phase") or {}).get("requires_split_phase"))
    design_v = 240.0 if split else float(consumption.get("voltage_v") or 120)
    demand = compute_demand_load(profile_lines)
    summary = compute_ac_breaker_summary(
        demand["total_demand_kw"], design_v, eq.get("inverter") or {}, inverter_qty,
        grid_connected=bool(consumption.get("grid_connected")),
    )
    return summary, design_v, split, demand


def _fresh_inverter(eq: dict) -> dict:
    """The saved design snapshots the inverter row when it was chosen, so fields added to the
    catalog later (rated AC-out current, efficiency) are missing from older drafts. Re-read the
    row by id and fall back to the snapshot."""
    snap = eq.get("inverter") or {}
    if snap.get("id"):
        try:
            from database.equipment_db import get_inverter

            fresh = get_inverter(snap["id"])
            if fresh:
                return {**snap, **fresh}
        except Exception:
            pass
    return snap


def build_context(blob: dict, lengths_override: dict | None = None) -> dict:
    """{'ready': bool, 'reason': str|None, 'branches': [...], 'lengths': {...}, ...}

    `lengths_override` lets a caller that owns the lengths elsewhere (a project's tech_spec)
    size the same saved design with its own cable runs."""
    blob = blob or {}
    eq = blob.get("equipment") or {}
    panel, cc = eq.get("panel") or {}, eq.get("charge_controller") or {}
    battery, inverter = eq.get("battery") or {}, _fresh_inverter(eq)
    ctx = {
        "ready": False, "reason": None, "branches": [],
        "lengths": clean_lengths(lengths_override) if lengths_override is not None else lengths(blob),
        "length_labels": LENGTH_LABELS, "meters": {}, "insulation": W.DEFAULT_INSULATION,
        "conduit_type": W.DEFAULT_CONDUIT, "vd_limit": W.VD_LIMIT_PCT, "terminal_temp": W.TERMINAL_TEMP_C,
        "show_ac_in": False,
    }
    n_series, n_strings = int(eq.get("panels_per_string") or 0), int(eq.get("n_strings") or 0)
    if not (panel and cc and battery and inverter and n_series and n_strings):
        ctx["reason"] = "Elige y valida una configuración (paneles, controlador, baterías e inversor) para dimensionar el cableado."
        return ctx

    L = ctx["lengths"]
    cc_qty = max(1, int(eq.get("charge_controller_qty") or 1))
    inv_qty = max(1, int(eq.get("inverter_qty") or 1))
    strings_per_cc = math.ceil(n_strings / cc_qty)
    isc, imp, vmp = _f(panel, "isc"), _f(panel, "imp"), _f(panel, "vmp")
    v_bat = _f(battery, "voltage_v", 48.0) or 48.0
    array_v = vmp * n_series
    ins, conduit = W.DEFAULT_INSULATION, W.DEFAULT_CONDUIT

    branches = [
        W.size_branch(
            "Paneles → controlador de carga", kind="dc", qty=cc_qty,
            current_a=isc * strings_per_cc, factor=W.CONTINUOUS_FACTOR * W.PV_CONDITIONS_FACTOR,
            v_ref=array_v, length_m=L["pv_cc_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=PV_BRANCH_HAS_EGC,
            protection="breaker",
            note=f"{strings_per_cc} string(s) de {n_series} módulos por controlador, combinados en una caja (un par de conductores). "
                 f"Corriente = Isc × strings × 1.25 × 1.25 (NEC 690.8).",
        ),
    ]

    # Controller output: the lower of its rating and what the array can push at battery voltage.
    pv_power_cc = array_v * imp * strings_per_cc
    i_out = pv_power_cc / v_bat
    rating_out = _f(cc, "imax_out")
    if rating_out:
        i_out = min(i_out, rating_out)
    branches.append(W.size_branch(
        "Controlador de carga → baterías", kind="dc", qty=cc_qty, current_a=i_out, factor=W.CONTINUOUS_FACTOR,
        v_ref=v_bat, length_m=L["cc_bat_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=BATTERY_DC_BRANCH_HAS_EGC,
        protection="fuse", ocpd_choices=LYNX_FUSE_SIZES_A,
        note="Corriente de salida = el menor entre la capacidad del controlador y la potencia del arreglo ÷ voltaje de batería.",
    ))

    inv_kw = _f(inverter, "kw")
    if inv_kw:
        eff = (_f(inverter, "efficiency_pct") / 100.0) or W.INVERTER_EFFICIENCY
        i_dc = inv_kw * 1000.0 / eff / v_bat
        bat_inv = W.size_branch(
            "Baterías → inversor", kind="dc", qty=inv_qty, current_a=i_dc, factor=W.CONTINUOUS_FACTOR,
            v_ref=v_bat, length_m=L["bat_inv_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=BATTERY_DC_BRANCH_HAS_EGC,
            protection="fuse", ocpd_choices=LYNX_FUSE_SIZES_A,
            note=f"Fusible en la barra Lynx Power In. Por inversor: potencia ÷ eficiencia ({eff:.2f}{'' if _f(inverter, 'efficiency_pct') else ', supuesta'}) ÷ voltaje de banco ({v_bat:.1f} V). "
                 "La hoja de Excel usa el voltaje de salida CA en esta rama; aquí se usa el voltaje de CC.",
        )
        bat_inv["notes"].append(
            "El manual del MultiPlus-II indica no instalar los cables de batería dentro de un conducto cerrado: confirma si este tramo va entubado.")
        branches.append(bat_inv)

    ac = _ac_summary(blob, inv_qty)
    if ac is not None:
        summary, design_v, split, demand = ac
        # Each inverter has its own AC out and AC in run to the panel: its own phase (or two for a
        # 240 V unit), neutral and ground. 120 V units therefore carry 3 conductors each, and the
        # voltage drop is judged against the inverter's own voltage, not the 240 V of the pair.
        leg_v = _f(inverter, "output_v", 120.0) or 120.0
        hot = 2 if leg_v >= 200 else 1
        conn = "phase" if hot == 1 else "phases"
        i_connected = demand["total_installed_kw"] * 1000.0 / (leg_v * inv_qty)
        i_demand = demand["total_demand_kw"] * 1000.0 / (leg_v * inv_qty)
        i_out, i_alt = (i_connected, i_demand) if AC_OUT_BASIS == "connected" else (i_demand, i_connected)
        alt_label = "demanda" if AC_OUT_BASIS == "connected" else "carga conectada"
        basis_label = "carga conectada (todos los circuitos a la vez)" if AC_OUT_BASIS == "connected" else "demanda (factores de demanda)"

        out_branch = W.size_branch(
            "Inversor → tablero AC (salida)", kind="ac", qty=inv_qty,
            current_a=i_out, factor=W.CONTINUOUS_FACTOR,
            v_ref=leg_v, length_m=L["ac_out_m"], hot=hot, neutral=1, insulation=ins, conduit_type=conduit,
            note=f"Por inversor ({leg_v:.0f} V): {basis_label} ÷ {inv_qty} inversor(es), × 1.25. "
                 f"{hot} {'fase' if hot == 1 else 'fases'} + neutro + tierra por inversor.",
        )
        out_branch["alt"] = {"label": alt_label, "current_a": round(i_alt, 1), "ocpd_a": W.ocpd_size(i_alt * W.CONTINUOUS_FACTOR)}
        rated_out = _f(inverter, "ac_out_rated_a")
        if rated_out:
            out_branch["max_ocpd_a"] = W.ocpd_size_max(rated_out)
            if out_branch.get("ocpd_a") and out_branch["max_ocpd_a"] and out_branch["ocpd_a"] > out_branch["max_ocpd_a"]:
                out_branch["notes"].append(
                    f"El breaker de {out_branch['ocpd_a']} A supera lo que admite la salida del inversor "
                    f"({rated_out:.0f} A nominal → máx. {out_branch['max_ocpd_a']} A).")
        branches.append(out_branch)

        # AC IN: designed from the most the inverter can take in (its pass-through rating); the breaker
        # is the largest standard size AT OR BELOW that rating (manufacturer: "rated … or less").
        ac_in = summary.get("ac_in")
        rated_in = _f(inverter, "ac_input_current_max_a")
        if ac_in and rated_in:
            ctx["show_ac_in"] = True
            max_in = W.ocpd_size_max(rated_in)
            in_branch = W.size_branch(
                "Red → entrada AC del inversor", kind="ac", qty=inv_qty,
                current_a=rated_in, factor=1.0,
                v_ref=leg_v, length_m=L["ac_in_m"], hot=hot, neutral=1,
                ocpd_override=max_in, insulation=ins, conduit_type=conduit,
                note=f"Por inversor: máxima corriente de entrada (passthrough) del datasheet, {rated_in:.0f} A. "
                     f"Breaker = el mayor estándar ≤ {rated_in:.0f} A ({max_in} A); el fabricante pide protección de {rated_in:.0f} A o menos. "
                     f"{hot} {'fase' if hot == 1 else 'fases'} + neutro + tierra por inversor.",
            )
            in_branch["max_ocpd_a"] = max_in
            if inv_qty > 1:
                in_branch["notes"].append(
                    f"El resumen de arriba suma los {inv_qty} inversores en un solo breaker de 2 polos ({ac_in['breaker_a']} A); "
                    f"aquí cada inversor tiene su propio breaker de {max_in} A.")
            branches.append(in_branch)
    else:
        ctx["ac_missing"] = True

    ctx.update(ready=True, branches=branches, meters=W.conductor_meters(branches))
    for b in branches:
        if b.get("ugc"):
            b["ugc_label"] = W.gauge_label(b["ugc"])
            b["egc_label"] = W.gauge_label(b["egc"]) if b.get("egc") else None
            for row in b.get("conductors") or []:
                row["label"] = W.gauge_label(row["gauge"])
    ctx["meter_rows"] = [(W.gauge_label(g), m) for g, m in ctx["meters"].items()]
    return ctx
