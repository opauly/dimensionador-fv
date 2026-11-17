"""Reverse sizing for a three-phase grid-tied plant (Grid Zero, industrial).

The wizard normally goes catalog -> design: pick an inverter, then see which string layouts fit it. An industrial plant cannot
depend on what is in the catalog (it may need 3 x 60 kW and the catalog stops at 10 kW), so this module goes the other way:
given the service (three-phase, line-to-line voltage), the panel and the array size to reach, it returns the MINIMUM design
that meets it:

  * how many inverters, of what AC size (a ladder of standard commercial sizes, no catalog row needed),
  * the string layout (modules in series, strings per inverter) corrected for cold Voc / hot Vmp,
  * what each inverter MUST support (DC max voltage, MPPT window, MPPT inputs, current per input) -- the spec to buy,
  * the AC side per inverter (rated current at the service voltage, breaker at 125 %),
  * a stand-in inverter dict (`virtual_inverter`) that the existing pipeline (MPPT checks, wiring, costs) can read like a catalog row.

Pure functions, plain dicts in / out. Assumptions that are market knowledge, not physics, are module constants or arguments so
they are visible and editable in one place: the size ladder (`AC_SIZE_LADDER_KW`) above all -- confirm what exists at the
service voltage before quoting.
"""
from __future__ import annotations

import math

from calculations import wiring as W

SQRT3 = math.sqrt(3.0)

# Three-phase service defaults (Costa Rica commercial/industrial secondary: 120/208 V wye, 60 Hz).
DEFAULT_V_LL = 208.0
DEFAULT_HZ = 60.0

# Standard AC sizes (kW) the recommender may combine. ASSUMPTION: confirm availability at the service voltage; large units are
# often 480 V only, in which case use `max_unit_kw` or plan a step-up transformer.
AC_SIZE_LADDER_KW = (10.0, 15.0, 20.0, 25.0, 30.0, 36.0, 40.0, 50.0, 60.0, 75.0, 100.0, 125.0)

DC_AC_RATIO_MAX = 1.2          # same ceiling the Grid Zero step already suggests (gz_s6_equipment.DC_AC_MAX_RATIO)
DC_AC_RATIO_WARN = 1.5         # above this the array clips a lot (coupling.DC_AC_RATIO_WARN)
AC_SLACK = 0.15                # AC capacity above the minimum that rounding to standard sizes may add before we prefer fewer units
MAX_UNITS = 40                 # sanity cap on identical inverters in one design

# DC-side assumptions (typical three-phase string inverters). Voltages in volts.
VDC_MAX_CLASS = (600.0, 1000.0, 1100.0, 1500.0)    # input-voltage classes the inverter market offers
VDC_MAX_DEFAULT = 1000.0
VMPPT_MAX_DEFAULT = 850.0      # top of the MPPT window we plan strings to stay under
DC_LINK_MARGIN = 1.10          # string Vmp (hot) must clear the AC peak line-to-line voltage by this margin
DC_MIN_FLOOR_V = 200.0
STRINGS_PER_MPPT = 2           # strings joined on one MPPT input (MC4 Y), as the wizard already does
K_VOC_DEFAULT = -0.0027        # 1/degC, used when the panel has no Voc coefficient
K_VMP_DEFAULT = -0.0034        # 1/degC, used when the panel has no Pmax coefficient
T_MIN_C = 10.0                 # coldest module temperature (Costa Rica highlands at dawn)
T_CELL_MAX_C = 70.0            # hottest module temperature

PF_RATED = 1.0                 # rated current at unity power factor (conservative: highest current is the one with PF = 1 at rated kW)


def _f(d: dict | None, key: str, default: float = 0.0) -> float:
    try:
        v = (d or {}).get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# ── Inverter count / size ────────────────────────────────────────────────────


def ac_current_a(kw: float, v_ll: float, pf: float = PF_RATED) -> float:
    """Rated line current of a three-phase inverter: I = P / (sqrt3 x V_LL x PF)."""
    return kw * 1000.0 / (SQRT3 * v_ll * pf) if v_ll and pf else 0.0


def inverter_options(kwp: float, *, ratio_max: float = DC_AC_RATIO_MAX, ladder: tuple = AC_SIZE_LADDER_KW,
                     max_unit_kw: float | None = None, max_units: int = MAX_UNITS, ac_slack: float = AC_SLACK) -> list[dict]:
    """Every (size x count) that reaches the array with DC/AC <= ratio_max, best first.

    Best = fewest units among those whose total AC is within `ac_slack` of the minimum AC needed (rounding to a standard size should
    not buy a lot of extra inverter), then the smallest total AC. When nothing fits within the slack, the smallest total AC wins."""
    need = kwp / ratio_max if ratio_max else kwp
    opts = []
    for size in ladder:
        if max_unit_kw and size > max_unit_kw + 1e-9:
            continue
        n = max(1, math.ceil(need / size - 1e-9))
        if n > max_units:
            continue
        opts.append({"unit_kw": size, "qty": n, "ac_kw_total": round(size * n, 2), "ac_need_kw": round(need, 2)})
    if not opts:
        return []
    cap = need * (1.0 + ac_slack)
    within = [o for o in opts if o["ac_kw_total"] <= cap + 1e-9]
    pool = within or opts
    pool = sorted(pool, key=(lambda o: (o["qty"], o["ac_kw_total"])) if within else (lambda o: (o["ac_kw_total"], o["qty"])))
    rest = [o for o in sorted(opts, key=lambda o: (o["ac_kw_total"], o["qty"])) if o not in pool]
    return pool + rest


# ── Strings ──────────────────────────────────────────────────────────────────


def string_limits(panel: dict, *, v_ll: float = DEFAULT_V_LL, vdc_max: float = VDC_MAX_DEFAULT, vmppt_max: float = VMPPT_MAX_DEFAULT,
                  t_min: float = T_MIN_C, t_cell_max: float = T_CELL_MAX_C) -> dict:
    """Module voltages at the temperature extremes and the range of modules in series that keeps a string inside the plan.

    Voc is corrected to the coldest cell temperature (must stay under the inverter's max DC voltage); Vmp to the hottest (must stay
    above the MPPT floor, which is itself no lower than what the grid needs: the DC bus must clear the AC peak line-to-line voltage)."""
    voc, vmp = _f(panel, "voc"), _f(panel, "vmp")
    raw_voc = panel.get("temp_coeff_voc")                     # catalog coefficients are in %/degC
    k_voc = float(raw_voc) / 100.0 if raw_voc not in (None, "") else K_VOC_DEFAULT
    raw_pmax = panel.get("temp_coeff_pmax")
    k_vmp = float(raw_pmax) / 100.0 if raw_pmax not in (None, "") else K_VMP_DEFAULT
    voc_cold = voc * (1.0 + k_voc * (t_min - 25.0))
    vmp_cold = vmp * (1.0 + k_vmp * (t_min - 25.0))
    vmp_hot = vmp * (1.0 + k_vmp * (t_cell_max - 25.0))
    vmppt_min = max(DC_MIN_FLOOR_V, v_ll * math.sqrt(2.0) * DC_LINK_MARGIN)
    ns_max = min(int(vdc_max // voc_cold), int(vmppt_max // vmp_cold)) if voc_cold and vmp_cold else 0
    ns_min = math.ceil(vmppt_min / vmp_hot) if vmp_hot else 0
    return {"voc_cold": round(voc_cold, 2), "vmp_cold": round(vmp_cold, 2), "vmp_hot": round(vmp_hot, 2), "vmppt_min": round(vmppt_min, 1),
            "ns_min": ns_min, "ns_max": ns_max, "vdc_max": vdc_max, "vmppt_max": vmppt_max, "t_min": t_min, "t_cell_max": t_cell_max}


def string_layout(panel: dict, target_panels: int, qty: int, limits: dict) -> dict | None:
    """Modules in series and strings per inverter for `qty` identical inverters, reaching at least `target_panels`.

    Picks the series count that adds the fewest extra modules over the target (ties: the longer string, so fewer strings and less DC cable)."""
    ns_min, ns_max = limits["ns_min"], limits["ns_max"]
    if ns_min < 1 or ns_max < ns_min:
        return None
    best = None
    for ns in range(ns_max, ns_min - 1, -1):
        per_inv = max(1, math.ceil(target_panels / (ns * qty)))
        panels = per_inv * ns * qty
        key = (panels - target_panels, -ns)
        if best is None or key < best[0]:
            best = (key, ns, per_inv, panels)
    _, ns, per_inv, panels = best
    return {"panels_per_string": ns, "strings_per_inverter": per_inv, "strings_total": per_inv * qty, "total_panels": panels}


# ── The recommendation ───────────────────────────────────────────────────────


def recommend(panel: dict, target_kwp: float, *, v_ll: float = DEFAULT_V_LL, hz: float = DEFAULT_HZ, neutral: bool = True,
              ratio_max: float = DC_AC_RATIO_MAX, max_unit_kw: float | None = None, ladder: tuple = AC_SIZE_LADDER_KW,
              vdc_max: float = VDC_MAX_DEFAULT, strings_per_mppt: int = STRINGS_PER_MPPT,
              t_min: float = T_MIN_C, t_cell_max: float = T_CELL_MAX_C) -> dict:
    """Minimum three-phase design that reaches `target_kwp` (DC) with `panel` on a `v_ll` service.

    Returns {"ok", "reasons", "warnings", "inverter": {...spec each unit must meet...}, "array": {...}, "ac": {...},
             "limits": {...}, "assumptions": {...}}. `ok` is False (with `reasons`) when no design exists, e.g. a panel whose Voc
    leaves no valid string length for this service voltage."""
    wp = _f(panel, "wp")
    out: dict = {"ok": False, "reasons": [], "warnings": [], "inverter": None, "array": None, "ac": None}
    if wp <= 0 or target_kwp <= 0:
        out["reasons"].append("Faltan la potencia del panel o la potencia objetivo del arreglo.")
        return out
    limits = string_limits(panel, v_ll=v_ll, vdc_max=vdc_max, t_min=t_min, t_cell_max=t_cell_max)
    out["limits"] = limits
    out["assumptions"] = {"ratio_max": ratio_max, "ladder_kw": list(ladder), "max_unit_kw": max_unit_kw, "vdc_max": vdc_max,
                          "strings_per_mppt": strings_per_mppt, "t_min_c": t_min, "t_cell_max_c": t_cell_max, "v_ll": v_ll, "hz": hz,
                          "pf_rated": PF_RATED}
    if limits["ns_min"] < 1 or limits["ns_max"] < limits["ns_min"]:
        out["reasons"].append(f"Ningún largo de string sirve: el módulo necesita al menos {limits['ns_min']} en serie para el servicio de {v_ll:g} V "
                              f"pero a lo sumo {limits['ns_max']} por el voltaje máximo de CC ({vdc_max:g} V, Voc en frío {limits['voc_cold']} V).")
        return out

    target_panels = math.ceil(target_kwp * 1000.0 / wp - 1e-9)
    chosen = None
    for opt in inverter_options(target_kwp, ratio_max=ratio_max, ladder=ladder, max_unit_kw=max_unit_kw):
        lay = string_layout(panel, target_panels, opt["qty"], limits)
        if not lay:
            continue
        array_kw = round(lay["total_panels"] * wp / 1000.0, 2)
        ratio = array_kw / opt["ac_kw_total"]
        if ratio > ratio_max + 1e-9:          # rounding up to whole strings pushed the ratio over the ceiling: try the next option
            continue
        chosen = (opt, lay, array_kw, ratio)
        break
    if not chosen:
        out["reasons"].append("No hay combinación de inversores de la escalera que alcance el arreglo con la relación CC/CA pedida; "
                              "sube el límite de unidades o la relación CC/CA.")
        return out
    opt, lay, array_kw, ratio = chosen

    n, size = opt["qty"], opt["unit_kw"]
    ns, spi = lay["panels_per_string"], lay["strings_per_inverter"]
    channels = math.ceil(spi / strings_per_mppt)
    spm = math.ceil(spi / channels)
    voc_s, vmp_hot_s, vmp_cold_s = ns * limits["voc_cold"], ns * limits["vmp_hot"], ns * limits["vmp_cold"]
    i_rated = ac_current_a(size, v_ll)
    ocpd = W.ocpd_size(i_rated * W.CONTINUOUS_FACTOR)

    out["inverter"] = {
        "qty": n, "kw": size, "phase": "three", "output_v": v_ll, "hz": hz, "wires": "3F + N + T" if neutral else "3F + T",
        "ac_current_a": round(i_rated, 1),
        "vmax_dc_required": next((c for c in VDC_MAX_CLASS if c >= voc_s), VDC_MAX_CLASS[-1]),
        "mppt_min_required_v": int(math.floor(vmp_hot_s)), "mppt_max_required_v": int(math.ceil(vmp_cold_s)),
        "mppt_channels_required": channels, "strings_per_mppt": spm,
        "imax_mppt_required_a": math.ceil(spm * _f(panel, "imp") * 10.0 - 1e-9) / 10.0,
        "isc_mppt_required_a": math.ceil(spm * _f(panel, "isc") * 10.0 - 1e-9) / 10.0,
    }
    out["array"] = {**lay, "system_kw": array_kw, "dc_ac_ratio": round(ratio, 2), "target_kwp": target_kwp, "target_panels": target_panels,
                    "voc_string_cold": round(voc_s, 1), "vmp_string_hot": round(vmp_hot_s, 1), "vmp_string_cold": round(vmp_cold_s, 1),
                    "vmp_string_stc": round(ns * _f(panel, "vmp"), 1)}
    out["ac"] = {"ac_kw_total": opt["ac_kw_total"], "ac_need_kw": opt["ac_need_kw"], "ac_current_total_a": round(i_rated * n, 1),
                 "ocpd_each_a": ocpd, "ct_count": 3, "neutral": neutral}

    if ratio > DC_AC_RATIO_WARN:
        out["warnings"].append(f"Relación CC/CA de {ratio:.2f}: el inversor va a recortar bastante en las horas de más sol.")
    if i_rated * W.CONTINUOUS_FACTOR > 400:
        out["warnings"].append(f"Cada inversor saca {i_rated:.0f} A a {v_ll:g} V: el alimentador por unidad queda fuera de la tabla de cables "
                               "(requiere conductores en paralelo). Considera unidades más chicas o interconectar a 480 V con transformador.")
    if i_rated * n > 800:
        out["warnings"].append(f"La corriente total de CA es {i_rated * n:.0f} A a {v_ll:g} V: el punto de conexión (barras/breaker principal) debe "
                               "poder recibirla; revisa el tablero principal.")
    out["ok"] = True
    return out


def virtual_inverter(rec: dict, *, name: str = "Por especificar") -> dict | None:
    """A stand-in inverter row (same keys as the catalog's) carrying the MINIMUM spec of a recommendation, so MPPT checks, wiring
    and costs can read it like any catalog inverter. `cost_usd` is None: the real price is typed in the Costos step."""
    inv = (rec or {}).get("inverter")
    if not inv:
        return None
    kw, v = inv["kw"], inv["output_v"]
    return {
        "id": f"reco-3f-{kw:g}kw-{v:g}v", "generic": True, "brand": name, "model": f"Trifásico {kw:g} kW {v:g} V",
        "kw": kw, "type": "string_inverter", "phase": "three", "output_v": v,
        "vmax": float(inv["vmax_dc_required"]), "vmin_mppt": float(inv["mppt_min_required_v"]), "vmax_mppt": float(inv["mppt_max_required_v"]),
        "imax_mppt": float(inv["imax_mppt_required_a"]), "mppt_channels": int(inv["mppt_channels_required"]),
        "ac_output_current_a": inv["ac_current_a"], "cost_usd": None,
        "notes": "Especificación mínima requerida; elegir el modelo comercial que la cumpla.",
    }
