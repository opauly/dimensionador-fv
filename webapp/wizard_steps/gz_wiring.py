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
from calculations import meter_cts
from calculations import pv_groups
from calculations import wiring as W
from calculations.datasheet_limits import fronius_limits
from materials.engine import grid_zero_equipment
from webapp.wizard_steps import disconnect_center, og_wiring
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
    "Centro de carga → base de medidor de generación": "gz_ac",
    "Inversor → centro de carga de desconexión": "gz_disc",
}


def build_context(blob: dict, lengths_override: dict | None = None, manual_override: dict | None = None,
                  disconnect_override: dict | None = None) -> dict:
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
    n_inv = max(1, int(eq.get("inverter_qty") or 1))
    disc = disconnect_center.resolve(disconnect_override if disconnect_override is not None else disconnect_center.from_blob(blob), "grid_zero",
                                     forced=n_inv > 1)
    ctx["disconnect"] = disc
    if disc["enabled"]:
        ctx["length_labels"] = {**LENGTH_LABELS, "ac_out_m": "Centro de carga → base de generación", disconnect_center.LENGTH_KEY: disconnect_center.LENGTH_LABEL}
    n_series, n_strings = int(eq.get("panels_per_string") or 0), int(eq.get("n_strings") or 0)
    if not (panel and inverter and n_series and n_strings):
        ctx["reason"] = "Falta un diseño completo (paneles, strings e inversor) para dimensionar el cableado."
        return ctx
    L = ctx["lengths"]
    isc, vmp = _f(panel, "isc"), _f(panel, "vmp")
    array_v = vmp * n_series
    # Strings of one inverter that share an MPPT input are joined with MC4 Y connectors: one run and one DC breaker per MPPT input.
    strings_each = max(1, -(-n_strings // n_inv))
    channels = int(_f(inverter, "mppt_channels") or 0) or strings_each
    pvg_each = pv_groups.summary(strings_each, channels)
    pvg = {**pvg_each, "strings": n_strings, "runs": pvg_each["runs"] * n_inv, "inverters": n_inv, "per_inverter": pvg_each["runs"],
           "y_pieces": pvg_each["y_pieces"] * n_inv}
    ctx["pv_groups"] = pvg
    runs, per_run = pvg["runs"], pvg_each["per_run"]
    y_text = (f" Los strings de cada inversor se juntan de a {per_run} con conectores MC4 en Y (en el techo): queda un tendido y un breaker por entrada MPPT."
              if per_run > 1 else "")
    ins, conduit = W.DEFAULT_INSULATION, W.DEFAULT_CONDUIT

    pv = _size(
        "Paneles → breakers CC (strings)", kind="dc", qty=runs,
        current_a=isc * per_run, factor=W.CONTINUOUS_FACTOR * W.PV_CONDITIONS_FACTOR,
        v_ref=array_v, length_m=L["pv_cc_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=og_wiring.PV_BRANCH_HAS_EGC,
        protection="breaker", ocpd_choices=C.DC_BREAKER_SIZES_A, min_gauge=C.PV_MIN_GAUGE, max_gauge=C.PV_MAX_GAUGE, shared_conduit=True,
        min_conduit_trade=C.PV_MIN_CONDUIT_TRADE,
        note=f"Un tendido por entrada MPPT ({n_strings} strings de {n_series} módulos), cada uno con su breaker CC en el centro de carga DC." + y_text
             + f" Corriente = Isc × {per_run} × 1.25 × 1.25 (NEC 690.8); breaker de la serie comercial CC.",
    )
    og_wiring.module_protection(pv, panel, pvg_each)

    dc_inv = _size(
        "Breakers CC → inversor (strings)", kind="dc", qty=runs,
        current_a=isc * per_run, factor=W.CONTINUOUS_FACTOR * W.PV_CONDITIONS_FACTOR,
        v_ref=array_v, length_m=L["dc_inv_m"], hot=2, insulation=ins, conduit_type=conduit, egc_included=og_wiring.PV_BRANCH_HAS_EGC,
        protection="breaker", ocpd_choices=C.DC_BREAKER_SIZES_A, min_gauge=C.PV_MIN_GAUGE, max_gauge=C.PV_MAX_GAUGE, shared_conduit=True,
        min_conduit_trade=C.PV_MIN_CONDUIT_TRADE,
        note="Del centro de carga DC a la entrada de cada MPPT del inversor. Mismo conductor que el tendido del techo; "
             "lo protege el breaker del string, por eso no lleva uno propio.",
    )
    dc_inv["ocpd_a"] = None

    three = meter_cts.phases(inverter) == 3                  # three-phase inverter: 3 lines + neutral at the service's line-to-line voltage
    ac_v = float(inverter.get("output_v") or 208.0) if three else C.PV_INVERTER_AC_V
    ac_kw = dict(hot=3, neutral=1, phases=3) if three else dict(hot=2, neutral=0)
    ac_conductors = "L1 + L2 + L3 + neutro + tierra" if three else "L1 + L2 + tierra, sin neutro"
    out_a = C.pv_inverter_ac_current_a(inverter)
    out_total = out_a * n_inv          # several Fronius in parallel: what reaches the base is the sum
    ac = _size(
        "Inversor → base de medidor de generación", kind="ac", qty=1, current_a=out_total, factor=W.CONTINUOUS_FACTOR,
        v_ref=ac_v, length_m=L["ac_out_m"], **ac_kw, insulation=ins, conduit_type=conduit,
        note=(f"Salida del inversor: corriente máxima {out_a:.1f} A × 1.25 (NEC 705 / 690.8). " if n_inv == 1
              else f"Suma de {n_inv} inversores en paralelo: {n_inv} × {out_a:.1f} A = {out_total:.1f} A × 1.25 (NEC 705 / 690.8). ")
             + ac_conductors + ". El breaker va en la base de medidor de generación (interruptor principal).",
    )
    ds = fronius_limits(inverter.get("model")) or {}
    max_ocpd = _f(inverter, "max_ocpd_a") or ds.get("ocpd_a")
    if max_ocpd and n_inv == 1:        # the manufacturer limit is per inverter: with several, each one has its own breaker in the load center
        ac["max_ocpd_a"] = int(max_ocpd)
        ac["notes"].append(f"Datasheet del fabricante a 240 V: breaker AC máx. {int(max_ocpd)} A.")
        if ac.get("ocpd_a") and ac["ocpd_a"] > max_ocpd:
            ac["notes"].append(f"El breaker calculado ({ac['ocpd_a']} A) supera el máximo del fabricante: se limita a {int(max_ocpd)} A.")
            ac["ocpd_a"] = int(max_ocpd)

    # Interconnection with the existing consumption meter base: the same conductors that reach the generation base, its own length.
    link = _size(
        "Base de generación → base de consumo", kind="ac", qty=1, current_a=out_total, factor=W.CONTINUOUS_FACTOR,
        v_ref=ac_v, length_m=L["gz_link_m"], **ac_kw, insulation=ins, conduit_type=conduit,
        note=f"Mismo conductor que llega a la base de medidor de generación ({ac_conductors}); interconecta con la base de medición de consumo "
             "existente. Lo protege el breaker de la base de generación, por eso no lleva uno propio.",
    )
    link["ocpd_a"] = None

    branches = [pv, dc_inv, ac, link]
    if disc["enabled"]:
        # Optional disconnect load center next to the Fronius (does not replace the generation meter base): the run to the base starts
        # at the center, and a short run joins the Fronius to it. The center's 2P breaker is the same size as the one in the base.
        ac["label"] = "Centro de carga → base de medidor de generación"
        ac["notes"].append("Sale del centro de carga de desconexión (4 espacios) junto al Fronius; el breaker de la base de generación sigue siendo el interruptor principal.")
        to_center = _size(
            "Inversor → centro de carga de desconexión", kind="ac", qty=n_inv, current_a=out_a, factor=W.CONTINUOUS_FACTOR,
            v_ref=ac_v, length_m=L[disconnect_center.LENGTH_KEY], **ac_kw, insulation=ins, conduit_type=conduit,
            note=f"Salida de cada inversor ({out_a:.1f} A × 1.25) al centro de carga de desconexión: un tendido por Fronius ({n_inv}), cada uno a su breaker de "
                 f"{'3 polos' if three else '2 polos'}. {ac_conductors}." + (" Las barras del centro de carga juntan los inversores." if n_inv > 1 else ""),
        )
        if max_ocpd or ds.get("ocpd_a"):
            cap = int(max_ocpd or ds.get("ocpd_a"))
            to_center["max_ocpd_a"] = cap
            if to_center.get("ocpd_a") and to_center["ocpd_a"] > cap:
                to_center["ocpd_a"] = cap
        branches.insert(2, to_center)
    for b in branches:
        b["key"] = BRANCH_KEYS.get(b["label"])
        man = (manual_override or {}).get(b["key"])
        if b["key"] == "gz_disc" and not man and (manual_override or {}).get("gz_ac"):
            man = {"ocpd_a": (manual_override["gz_ac"] or {}).get("ocpd_a"), "ugc": (manual_override["gz_ac"] or {}).get("ugc")}
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
