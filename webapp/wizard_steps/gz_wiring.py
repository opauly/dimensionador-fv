"""Wiring for a Grid Zero design (string inverter, no batteries, no charge controllers), NEC-based like the Off-Grid /
Hybrid one (`og_wiring`) and returned in the same shape, so the Técnico tab, the materials list and the unifilar read it alike.

Four runs, as Oscar draws them:
  1. PV strings -> DC breakers       (DC, one run per string; #10 solar-cable floor, 1 in conduit)
  2. DC breakers -> inverter          (DC, one run per string; protected by the string breaker, so no breaker of its own)
  3. Inverter -> generation meter base           (AC 240 V split-phase, L1 + L2 + ground; breaker = 125 % of the inverter's maximum output
                                       current, limited to the manufacturer's maximum; it sits in the meter base)
  4. Generation meter base -> consumption meter base (same conductors as run 3, its own editable length, no breaker of its own)
"""
from __future__ import annotations

from calculations import coupling as C
from calculations import wiring as W
from calculations.datasheet_limits import fronius_limits
from materials.engine import grid_zero_equipment
from webapp.wizard_steps import og_wiring
from webapp.wizard_steps.og_wiring import _f, _size

LENGTH_LABELS = {
    "pv_cc_m": "Paneles → breakers CC",
    "dc_inv_m": "Breakers CC → Fronius",
    "ac_out_m": "Fronius → base de generación",
    "gz_link_m": "Base de generación → base de consumo",
}
BRANCH_KEYS = {
    "Paneles → breakers CC (strings)": "pv_strings",
    "Breakers CC → inversor (strings)": "pv_dc_inv",
    "Inversor → base de medidor de generación": "gz_ac",
    "Base de generación → base de consumo": "gz_link",
}


def build_context(blob: dict, lengths_override: dict | None = None, manual_override: dict | None = None) -> dict:
    blob = blob or {}
    eq = grid_zero_equipment(og_wiring.fresh_equipment(blob.get("equipment") or {}))
    panel, inverter = eq.get("panel") or {}, eq.get("inverter") or {}
    ctx = {
        "ready": False, "reason": None, "branches": [],
        "lengths": og_wiring.clean_lengths(lengths_override) if lengths_override is not None else og_wiring.lengths(blob),
        "length_labels": LENGTH_LABELS, "meters": {}, "insulation": W.DEFAULT_INSULATION,
        "conduit_type": W.DEFAULT_CONDUIT, "vd_limit": W.VD_LIMIT_PCT, "terminal_temp": W.TERMINAL_TEMP_C,
        "show_ac_in": False, "coupling": {}, "can_couple": False,
    }
    n_series, n_strings = int(eq.get("panels_per_string") or 0), int(eq.get("n_strings") or 0)
    if not (panel and inverter and n_series and n_strings):
        ctx["reason"] = "Falta un diseño completo (paneles, strings e inversor) para dimensionar el cableado."
        return ctx
    L = ctx["lengths"]
    isc, vmp = _f(panel, "isc"), _f(panel, "vmp")
    array_v = vmp * n_series
    ins, conduit = W.DEFAULT_INSULATION, W.DEFAULT_CONDUIT

    pv = _size(
        "Paneles → breakers CC (strings)", kind="dc", qty=n_strings,
        current_a=isc, factor=W.CONTINUOUS_FACTOR * W.PV_CONDITIONS_FACTOR,
        v_ref=array_v, length_m=L["pv_cc_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=og_wiring.PV_BRANCH_HAS_EGC,
        protection="breaker", ocpd_choices=C.DC_BREAKER_SIZES_A, min_gauge=C.PV_MIN_GAUGE, shared_conduit=True,
        min_conduit_trade=C.PV_MIN_CONDUIT_TRADE,
        note=f"Un tendido por string ({n_strings} strings de {n_series} módulos), cada uno con su breaker CC en el centro de carga DC. "
             f"Corriente = Isc × 1.25 × 1.25 (NEC 690.8); breaker de la serie comercial CC.",
    )
    max_series = _f(panel, "max_series_fuse_a")
    if max_series:
        pv["max_ocpd_a"] = int(max_series)
        pv["notes"].append(f"Datasheet del módulo: protección máxima en serie {int(max_series)} A (aplica también al breaker).")

    dc_inv = _size(
        "Breakers CC → inversor (strings)", kind="dc", qty=n_strings,
        current_a=isc, factor=W.CONTINUOUS_FACTOR * W.PV_CONDITIONS_FACTOR,
        v_ref=array_v, length_m=L["dc_inv_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=og_wiring.PV_BRANCH_HAS_EGC,
        protection="breaker", ocpd_choices=C.DC_BREAKER_SIZES_A, min_gauge=C.PV_MIN_GAUGE, shared_conduit=True,
        min_conduit_trade=C.PV_MIN_CONDUIT_TRADE,
        note="Del centro de carga DC a la entrada de cada MPPT del inversor. Mismo conductor que el tendido del techo; "
             "lo protege el breaker del string, por eso no lleva uno propio.",
    )
    dc_inv["ocpd_a"] = None

    out_a = C.pv_inverter_ac_current_a(inverter)
    ac = _size(
        "Inversor → base de medidor de generación", kind="ac", qty=1, current_a=out_a, factor=W.CONTINUOUS_FACTOR,
        v_ref=C.PV_INVERTER_AC_V, length_m=L["ac_out_m"], hot=2, neutral=0, insulation=ins, conduit_type=conduit,
        note=f"Salida del inversor: corriente máxima {out_a:.1f} A × 1.25 (NEC 705 / 690.8). L1 + L2 + tierra, sin neutro. "
             "El breaker va en la base de medidor de generación (interruptor principal).",
    )
    ds = fronius_limits(inverter.get("model")) or {}
    max_ocpd = _f(inverter, "max_ocpd_a") or ds.get("ocpd_a")
    if max_ocpd:
        ac["max_ocpd_a"] = int(max_ocpd)
        ac["notes"].append(f"Datasheet del fabricante a 240 V: breaker AC máx. {int(max_ocpd)} A.")
        if ac.get("ocpd_a") and ac["ocpd_a"] > max_ocpd:
            ac["notes"].append(f"El breaker calculado ({ac['ocpd_a']} A) supera el máximo del fabricante: se limita a {int(max_ocpd)} A.")
            ac["ocpd_a"] = int(max_ocpd)

    # Interconnection with the existing consumption meter base: the same conductors that reach the generation base, its own length.
    link = _size(
        "Base de generación → base de consumo", kind="ac", qty=1, current_a=out_a, factor=W.CONTINUOUS_FACTOR,
        v_ref=C.PV_INVERTER_AC_V, length_m=L["gz_link_m"], hot=2, neutral=0, insulation=ins, conduit_type=conduit,
        note="Mismo conductor que llega a la base de medidor de generación (L1 + L2 + tierra); interconecta con la base de medición de consumo "
             "existente. Lo protege el breaker de la base de generación, por eso no lleva uno propio.",
    )
    link["ocpd_a"] = None

    branches = [pv, dc_inv, ac, link]
    for b in branches:
        b["key"] = BRANCH_KEYS.get(b["label"])
        man = (manual_override or {}).get(b["key"])
        if b["key"] == "gz_link" and not man and (manual_override or {}).get("gz_ac"):
            man = {"ocpd_a": None, "ugc": (manual_override["gz_ac"] or {}).get("ugc")}     # "the same cable" as the run that reaches the generation base
        W.apply_manual(b, man)
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
