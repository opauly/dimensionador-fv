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

AC-coupled hybrid (`og_coupling`): branches 1 and 2 are replaced — there are no charge controllers.
  1. PV strings -> PV inverter       (DC, one run per string; Pauly's #10 solar-cable floor)
  2. PV inverter -> critical-loads sub-panel (AC 240 V split-phase: L1 + L2 + ground, no neutral)
"""
from __future__ import annotations

import math

from calculations import coupling as C
from calculations import wiring as W
from calculations.datasheet_limits import fronius_limits, multi_limits
from webapp.wizard_steps import og_coupling

SCRATCH_KEY = "wiring"


def _size(*args, **kw):
    """`wiring.size_branch` the way Pauly buys: only AWG sizes the dealers stock (no #3)."""
    return W.size_branch(*args, stocked_only=True, **kw)

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
    "pv_inv_ac_m": 10.0,  # AC-coupled: PV inverter -> critical-loads sub-panel
    "bat_inv_m": 2.0,    # battery bank -> inverter
    "ac_out_m": 10.0,    # inverter -> AC panel
    "ac_in_m": 10.0,     # grid -> inverter AC input
    "dc_inv_m": 5.0,     # Grid Zero: DC breakers -> string inverter
}
LENGTH_LABELS = {
    "pv_cc_m": "Paneles → controlador",
    "cc_bat_m": "Controlador → baterías",
    "bat_inv_m": "Baterías → inversor",
    "ac_out_m": "Inversor → tablero AC",
    "ac_in_m": "Red → entrada AC del inversor",
}


# AC-coupled designs: no controller run; the PV run ends at the PV inverter and the other
# lengths read against the critical-loads sub-panel.
LENGTH_LABELS_AC = {
    "pv_cc_m": "Paneles → inversor FV (vía gabinete DC)",
    "pv_inv_ac_m": "Inversor FV → sub-panel de cargas críticas",
    "bat_inv_m": "Baterías → Multis",
    "ac_out_m": "Multis → sub-panel",
    "ac_in_m": "Red → entrada AC de los Multis",
}


# Stable keys for the branches, so the materials rules and the unifilar can find a run without
# matching on its (Spanish, editable) label.
BRANCH_KEYS = {
    "Paneles → controlador de carga": "pv_cc",
    "Controlador de carga → baterías": "cc_bat",
    "Paneles → inversor FV (strings)": "pv_strings",
    "Inversor FV → sub-panel de cargas críticas": "pv_inv_ac",
    "Baterías → inversor": "bat_inv",
    "Inversor → tablero AC (salida)": "ac_out",
    "Red → entrada AC del inversor": "ac_in",
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


def manual_from_form(form) -> dict:
    """{branch key: {'ocpd_a': int|None, 'ugc': gauge|None}} from the manual-values form (blank = use the calculated)."""
    out = {}
    for key in BRANCH_KEYS.values():
        a, g = (form.get(f"man_ocpd_{key}") or "").strip(), (form.get(f"man_ugc_{key}") or "").strip()
        try:
            a = int(float(a.replace(",", "."))) if a else None
        except ValueError:
            a = None
        g = g if g in W.T.GAUGE_ORDER else None
        if (a and a > 0) or g:
            out[key] = {"ocpd_a": a if a and a > 0 else None, "ugc": g}
    return out


def lengths_from_form(form, base: dict | None = None) -> dict[str, float]:
    """Lengths posted by the form; a key the form does not carry (the controller run is hidden in an
    AC-coupled design) keeps its value from `base`, then the default."""
    base = clean_lengths(base)
    out = {}
    for key in DEFAULT_LENGTHS:
        if key not in form:
            out[key] = base[key]
            continue
        try:
            v = float(str(form.get(key, "")).replace(",", "."))
            out[key] = v if v > 0 else DEFAULT_LENGTHS[key]
        except ValueError:
            out[key] = DEFAULT_LENGTHS[key]
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


def fresh_equipment(eq: dict) -> dict:
    """A copy of the saved design's `equipment` where panel, inverter and battery carry the CURRENT catalog row.
    The design snapshots each row when it is chosen, so datasheet fields added later (module max series fuse,
    inverter continuous watts, battery fuse...) would be missing; the snapshot still wins for what the catalog lacks."""
    from database import equipment_db as E

    out = dict(eq or {})
    for key, getter in (("panel", E.get_panel), ("battery", E.get_battery)):
        snap = out.get(key) or {}
        if snap.get("id"):
            try:
                fresh = getter(snap["id"])
                if fresh:
                    out[key] = {**snap, **fresh}
            except Exception:
                pass
    if out.get("inverter"):
        out["inverter"] = _fresh_inverter(out)
    return out


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


def build_context(blob: dict, lengths_override: dict | None = None, coupling_override: dict | None = None,
                  manual_override: dict | None = None) -> dict:
    """{'ready': bool, 'reason': str|None, 'branches': [...], 'lengths': {...}, ...}

    `lengths_override` / `coupling_override` let a caller that owns those elsewhere (a project's
    tech_spec) size the same saved design with its own cable runs and PV coupling. `manual_override` is the
    engineer's own breaker / gauge per branch key ({key: {ocpd_a, ugc}}): applied on top and judged
    (`W.apply_manual`); the calculated values stay in each branch's `calc`."""
    blob = blob or {}
    eq = fresh_equipment(blob.get("equipment") or {})
    panel, cc = eq.get("panel") or {}, eq.get("charge_controller") or {}
    battery, inverter = eq.get("battery") or {}, _fresh_inverter(eq)
    # AC coupling (a string inverter on the AC-OUT of the Victron units, no charge controllers) is available to Off-Grid and Hybrid.
    can_couple = (blob.get("meta") or {}).get("system_type") in ("off_grid", "hybrid")
    saved_cpl = coupling_override if coupling_override is not None else og_coupling.from_blob(blob)
    cpl = og_coupling.resolve(eq, saved_cpl if can_couple else {})
    ac_coupled = cpl["ac"]
    ctx = {
        "ready": False, "reason": None, "branches": [],
        "lengths": clean_lengths(lengths_override) if lengths_override is not None else lengths(blob),
        "length_labels": LENGTH_LABELS_AC if ac_coupled else LENGTH_LABELS, "meters": {}, "insulation": W.DEFAULT_INSULATION,
        "conduit_type": W.DEFAULT_CONDUIT, "vd_limit": W.VD_LIMIT_PCT, "terminal_temp": W.TERMINAL_TEMP_C,
        "show_ac_in": False, "coupling": cpl, "can_couple": can_couple,
    }
    if ac_coupled:
        n_series, n_strings = int(cpl.get("series") or 0), int(cpl.get("strings") or 0)
        if not (panel and battery and inverter and cpl.get("pv_inverter") and n_series and n_strings):
            ctx["reason"] = "Elige y valida una configuración (paneles, baterías e inversor Victron) para dimensionar el cableado."
            return ctx
    else:
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

    if ac_coupled:
        pv_inv, pv_qty = cpl["pv_inverter"], cpl["qty"]
        branches = [
            _size(
                "Paneles → inversor FV (strings)", kind="dc", qty=n_strings,
                current_a=isc, factor=W.CONTINUOUS_FACTOR * W.PV_CONDITIONS_FACTOR,
                v_ref=array_v, length_m=L["pv_cc_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=PV_BRANCH_HAS_EGC,
                protection="breaker", ocpd_choices=C.DC_BREAKER_SIZES_A, min_gauge=C.PV_MIN_GAUGE, shared_conduit=True,
                min_conduit_trade=C.PV_MIN_CONDUIT_TRADE,
                note=f"Un tendido por string ({n_strings} strings de {n_series} módulos), cada uno con su breaker CC en el gabinete DC. "
                     f"Corriente = Isc × 1.25 × 1.25 (NEC 690.8); breaker de la serie estándar CC (NB1-63DC).",
            ),
        ]
        max_series = _f(panel, "max_series_fuse_a")
        if max_series:
            branches[0]["max_ocpd_a"] = int(max_series)
            branches[0]["notes"].append(f"Datasheet del módulo: protección máxima en serie {int(max_series)} A (aplica también al breaker).")
        pv_ac_a = C.pv_inverter_ac_current_a(pv_inv)
        pv_ac = _size(
            "Inversor FV → sub-panel de cargas críticas", kind="ac", qty=pv_qty,
            current_a=pv_ac_a, factor=W.CONTINUOUS_FACTOR,
            v_ref=C.PV_INVERTER_AC_V, length_m=L["pv_inv_ac_m"], hot=2, neutral=0, insulation=ins, conduit_type=conduit,
            note=f"Salida del inversor FV: {_f(pv_inv, 'kw'):g} kW ÷ {C.PV_INVERTER_AC_V:.0f} V = {pv_ac_a:.1f} A, × 1.25. "
                 "L1 + L2 + tierra, sin neutro; entra al sub-panel de cargas críticas del lado de carga de los Multis.",
        )
        fr_ds = fronius_limits(pv_inv.get("model")) or {}
        fr_max = _f(pv_inv, "max_ocpd_a") or fr_ds.get("ocpd_a")      # catalog column first, the built-in datasheet table as fallback
        if fr_max:
            pv_ac["max_ocpd_a"] = int(fr_max)
            pv_ac["notes"].append(f"Datasheet del fabricante a 240 V: breaker AC máx. {int(fr_max)} A (corriente de salida continua {pv_ac_a:g} A).")
        branches.append(pv_ac)
    else:
        branches = [
            _size(
                "Paneles → controlador de carga", kind="dc", qty=cc_qty,
                current_a=isc * strings_per_cc, factor=W.CONTINUOUS_FACTOR * W.PV_CONDITIONS_FACTOR,
                v_ref=array_v, length_m=L["pv_cc_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=PV_BRANCH_HAS_EGC,
                protection="breaker", shared_conduit=True, min_conduit_trade=C.PV_MIN_CONDUIT_TRADE,
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
        branches.append(_size(
            "Controlador de carga → baterías", kind="dc", qty=cc_qty, current_a=i_out, factor=W.CONTINUOUS_FACTOR,
            v_ref=v_bat, length_m=L["cc_bat_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=BATTERY_DC_BRANCH_HAS_EGC,
            protection="fuse", ocpd_choices=LYNX_FUSE_SIZES_A,
            note="Corriente de salida = el menor entre la capacidad del controlador y la potencia del arreglo ÷ voltaje de batería.",
        ))

    inv_kw = _f(inverter, "kw")
    if inv_kw:
        eff = (_f(inverter, "efficiency_pct") / 100.0) or W.INVERTER_EFFICIENCY
        multi_ds = multi_limits(inverter.get("model"))
        # The kW in the catalog is the VA rating; the DC side carries the continuous WATTS (datasheet, 25 C).
        p_dc_w = _f(inverter, "cont_w_25c") or (multi_ds["cont_w_25c"] if multi_ds else inv_kw * 1000.0)
        i_dc = p_dc_w / eff / v_bat
        bat_inv = _size(
            "Baterías → inversor", kind="dc", qty=inv_qty, current_a=i_dc, factor=W.CONTINUOUS_FACTOR,
            v_ref=v_bat, length_m=L["bat_inv_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=BATTERY_DC_BRANCH_HAS_EGC,
            protection="fuse", ocpd_choices=LYNX_FUSE_SIZES_A,
            note=f"Fusible en la barra Lynx Power In. Por inversor: potencia continua ({p_dc_w:.0f} W{' a 25 °C, datasheet' if (multi_ds or _f(inverter, 'cont_w_25c')) else ''}) ÷ eficiencia ({eff:.2f}{'' if _f(inverter, 'efficiency_pct') else ', supuesta'}) ÷ voltaje de banco ({v_bat:.1f} V). "
                 "La hoja de Excel usa el voltaje de salida CA en esta rama; aquí se usa el voltaje de CC.",
        )
        dc_fuse = _f(inverter, "dc_fuse_a")
        if dc_fuse:
            bat_inv["max_ocpd_a"] = int(dc_fuse)
            bat_inv["notes"].append(f"Fusible DC del fabricante: {int(dc_fuse)} A (manual del inversor).")
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

        out_branch = _size(
            "Inversor → tablero AC (salida)", kind="ac", qty=inv_qty,
            current_a=i_out, factor=W.CONTINUOUS_FACTOR,
            v_ref=leg_v, length_m=L["ac_out_m"], hot=hot, neutral=1, insulation=ins, conduit_type=conduit, shared_conduit=True,
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
            in_branch = _size(
                "Red → entrada AC del inversor", kind="ac", qty=inv_qty,
                current_a=rated_in, factor=1.0,
                v_ref=leg_v, length_m=L["ac_in_m"], hot=hot, neutral=1,
                ocpd_override=max_in, insulation=ins, conduit_type=conduit, shared_conduit=True,
                note=f"Por inversor: máxima corriente de entrada (passthrough) del datasheet, {rated_in:.0f} A. "
                     f"Breaker = el mayor estándar ≤ {rated_in:.0f} A ({max_in} A); el fabricante pide protección de {rated_in:.0f} A o menos. "
                     f"{hot} {'fase' if hot == 1 else 'fases'} + neutro + tierra por inversor.",
            )
            in_branch["max_ocpd_a"] = max_in
            in_branch["limited"] = True     # the breaker, not the load, caps this run (manufacturer limit)
            # The phases are sized from the pass-through rating, but the breaker caps what they can carry:
            # a smaller gauge whose next standard OCPD size covers the breaker is allowed by NEC 240.4(B).
            ug = in_branch.get("ugc")
            if ug and max_in:
                i = W.T.GAUGE_ORDER.index(ug)
                smaller = W.T.GAUGE_ORDER[i - 1] if i > 0 else None
                a_s = W.ampacity(smaller) if smaller else None
                if a_s and a_s < max_in and (W.ocpd_size(a_s) or 0) >= max_in:
                    in_branch["notes"].append(
                        f"Alternativa NEC 240.4(B): {W.gauge_label(smaller)} ({a_s:g} A a 75 °C) con el breaker de {max_in} A es permitido "
                        f"(siguiente tamaño estándar); se dibuja {W.gauge_label(ug)} para cubrir los {rated_in:.0f} A de paso del inversor. "
                        "Si el breaker limita la corriente, puedes usar el calibre menor.")
            if inv_qty > 1:
                in_branch["notes"].append(
                    f"El resumen de arriba suma los {inv_qty} inversores en un solo breaker de 2 polos ({ac_in['breaker_a']} A); "
                    f"aquí cada inversor tiene su propio breaker de {max_in} A.")
            branches.append(in_branch)
    else:
        ctx["ac_missing"] = True

    for b in branches:
        b["key"] = BRANCH_KEYS.get(b["label"])
        W.apply_manual(b, (manual_override or {}).get(b["key"]))
    ctx["has_manual"] = any(b.get("manual") for b in branches)
    ctx["gauge_options"] = [(g, W.gauge_label(g)) for g in W.T.GAUGE_ORDER[W.T.GAUGE_ORDER.index("14"):W.T.GAUGE_ORDER.index("500") + 1]]
    ctx.update(ready=True, branches=branches, meters=W.conductor_meters(branches))
    for b in branches:
        if b.get("ugc"):
            b["ugc_label"] = W.gauge_label(b["ugc"])
            b["egc_label"] = W.gauge_label(b["egc"]) if b.get("egc") else None
            for row in b.get("conductors") or []:
                row["label"] = W.gauge_label(row["gauge"])
    ctx["meter_rows"] = [(W.gauge_label(g), m) for g, m in ctx["meters"].items()]
    return ctx
