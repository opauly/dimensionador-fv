"""Conductor, OCPD and PVC-conduit sizing per circuit branch.

A simplified, deliberately spreadsheet-tied port of Oscar's "Dimensionador CCC + FV"
workbook (sheets "CCCs FV (Off-Grid)" / "(On-Grid)"). Copper conductors and PVC conduit
only; every table lives in `calculations/nec_tables.py`, generated from that workbook.

Per branch, exactly the workbook's chain:

1. Design current   = branch current x 1.25 (continuous load); PV array circuits also
                      x 1.25 (NEC 690.8: Isc x 1.25 x 1.25).
2. Initial gauge    = smallest Cu conductor whose T310.15(B)(16) ampacity at the equipment
                      terminal temperature (75 C) is >= the design current.
3. OCPD             = next standard size >= the design current (workbook "Breakers").
4. Voltage drop     = 2 x I x R x L (DC; I = branch current without the 1.25 factors) or
                      2 x I x (R cos(phi) + X sin(phi)) x L (AC, PF 0.8, PVC-conduit R/X
                      from T9). The workbook's "Calibre incrementado" cell is typed by
                      hand; here the gauge is raised until the drop is <= 2 % (the SEI
                      recommendation the workbook cites).
5. EGC              = T250.122 keyed by the rating of the breaker/fuse that protects the circuit
                      (never larger than the circuit conductors), enlarged in proportion to any
                      voltage-drop upsizing (250.122(B): "regla de tres" on circular mils).
                      The workbook uses T250.66 (a grounding-ELECTRODE table keyed by the phase
                      gauge); `egc_gauge()` keeps that legacy rule for the workbook checks.
6. Conduit          = smallest PVC trade size whose 40 % fill area holds the sum of the
                      conductor cross-sections (T5 for the chosen insulation).

Differences from the workbook, on purpose (each is also surfaced to the user):
* The workbook's battery->inverter branch divides power by the AC output voltage; here the
  DC bank voltage is used (the workbook figure would undersize that DC cable roughly 5x).
* PV-circuit voltage drop is judged against the array voltage (Vmp x modules in series),
  not the 24 V battery voltage the off-grid sheet uses for the whole module->battery run.
* No ambient-temperature or >3-conductor bundling derating — the FV sheets do not apply
  them either (only the generic CCCs sheet does).
"""
from __future__ import annotations

import math

from calculations import nec_tables as T

# ── Workbook defaults (sheet "CCCs FV (Off-Grid)" input cells) ────────────────
TERMINAL_TEMP_C = 75            # C14 "Temperatura terminales de equipo"
CONTINUOUS_FACTOR = 1.25        # C42/C68/C90 "Factor de ajuste 80%"
PV_CONDITIONS_FACTOR = 1.25     # C43 "Factor de ajuste condiciones óptimas"
VD_LIMIT_PCT = 2.0              # C57/C79/C101 "Recomendada SEI"
AC_POWER_FACTOR = 0.8           # H96 DEGREES(ACOS(0.8))
INVERTER_EFFICIENCY = 0.95      # C37 (0.96 in the sample); no efficiency field in the catalog
DEFAULT_INSULATION = "RHW-2"    # C8 — what 35 of the workbook copies use for off-grid/hybrid
DEFAULT_CONDUIT = "PVC A"       # C10

_TEMP_IDX = {60: 0, 75: 1, 90: 2}


def ampacity(gauge: str, temp_c: int = TERMINAL_TEMP_C) -> float | None:
    return T.T310_15_B_16_CU[gauge][_TEMP_IDX[temp_c]]


# AWG sizes the dealers do not stock (#3 and #1): the app sizes with `stocked_only` so the list
# never asks for a cable nobody sells; the workbook comparison keeps the full table.
UNSTOCKED_GAUGES = ("3", "1")


def _order(stocked_only: bool) -> list[str]:
    return [g for g in T.GAUGE_ORDER if not (stocked_only and g in UNSTOCKED_GAUGES)]


def _next_stocked(gauge: str) -> str:
    """`gauge` itself when sold, else the next larger one that is."""
    order = T.GAUGE_ORDER
    for g in order[order.index(gauge):]:
        if g not in UNSTOCKED_GAUGES:
            return g
    return gauge


def initial_gauge(design_a: float, temp_c: int = TERMINAL_TEMP_C, stocked_only: bool = False) -> str | None:
    """Smallest listed Cu gauge with ampacity >= design current; None if beyond the table."""
    for g in _order(stocked_only):
        amp = ampacity(g, temp_c)
        if amp is not None and amp >= design_a:
            return g
    return None


def ocpd_size(design_a: float) -> int | None:
    """Next standard OCPD rating >= the design current (workbook 'Breakers')."""
    for size in T.OCPD_SIZES_A:
        if size >= design_a:
            return size
    return None


def ocpd_size_max(rating_a: float) -> int | None:
    """Largest standard OCPD rating <= `rating_a` (a manufacturer's "or less" limit, e.g. the
    MultiPlus-II 5k AC input: 'fuse or breaker rated 95 A or less' -> 90 A). None below the table."""
    best = None
    for size in T.OCPD_SIZES_A:
        if size <= rating_a:
            best = size
    return best


def vdrop_dc(gauge: str, current_a: float, length_m: float) -> float:
    return 2.0 * current_a * T.T8_R_DC_CU_OHM_KM[gauge] * length_m / 1000.0


def vdrop_ac(gauge: str, current_a: float, length_m: float, pf: float = AC_POWER_FACTOR) -> float:
    x_km, r_km = T.T9_AC_PVC_CU[gauge]
    phi = math.acos(pf)
    z = (r_km * math.cos(phi) + x_km * math.sin(phi)) * length_m / 1000.0
    return 2.0 * current_a * z


def egc_gauge(ugc_initial: str, ugc_final: str) -> str:
    """T250.66 by the initial UGC, enlarged in proportion if the UGC was upsized (250.122(B)).

    The comparison is strict, exactly like the workbook's MATCH on circular mils, so a near
    miss of a few cmils bumps the EGC a whole size (e.g. batt->inverter C86: 26,260 needed vs
    26,240 for 6 AWG -> 4 AWG). Kept on purpose to stay tied to the spreadsheet."""
    base = T.T250_66_CU[ugc_initial]
    if ugc_final == ugc_initial:
        return base
    needed_cmils = T.T8_CMILS[ugc_final] * T.T8_CMILS[base] / T.T8_CMILS[ugc_initial]
    for g in T.GAUGE_ORDER:
        if T.T8_CMILS[g] >= needed_cmils:
            return g
    return T.GAUGE_ORDER[-1]


def egc_gauge_ocpd(ocpd_a: float, ugc_start: str, ugc_vd: str) -> str:
    """Equipment-grounding conductor by T250.122: the gauge listed for the rating of the OCPD that
    protects the circuit (smallest listed rating >= `ocpd_a`). If the phase conductors were enlarged
    for voltage drop (`ugc_vd` above `ugc_start`), the EGC grows in the same proportion on circular
    mils (250.122(B)). The caller caps the result at the phase gauge (250.122(A))."""
    base = T.T250_122_CU[-1][1]
    for rating, g in reversed(T.T250_122_CU):          # ascending ratings
        if rating >= ocpd_a:
            base = g
            break
    if ugc_vd == ugc_start:
        return base
    needed_cmils = T.T8_CMILS[ugc_vd] * T.T8_CMILS[base] / T.T8_CMILS[ugc_start]
    for g in T.GAUGE_ORDER:
        if T.T8_CMILS[g] >= needed_cmils:
            return g
    return T.GAUGE_ORDER[-1]


def pick_conduit(total_mm2: float, conduit_type: str = DEFAULT_CONDUIT, min_trade: str | None = None) -> dict | None:
    """Smallest PVC trade size whose 40 % fill area >= total conductor area, else None.
    `min_trade` is a practice floor (e.g. 1" for solar wiring)."""
    table = T.T4_PVC_CONDUIT[conduit_type]
    first = next((i for i, (trade, _, _) in enumerate(table) if trade == min_trade), 0) if min_trade else 0
    for trade, metric, area in table[first:]:
        if area >= total_mm2:
            return {"trade": trade, "metric": metric, "type": conduit_type,
                    "fill_pct": round(total_mm2 / area * 40.0, 1)}
    return None


def conductor_area(gauge: str, insulation: str = DEFAULT_INSULATION) -> float | None:
    return T.T5_AREA_MM2[insulation].get(gauge)


def build_rows(*, ugc: str, egc: str, hot: int, neutral: int, egc_included: bool, ocpd, protection: str,
               current_a: float, qty: int, shared_conduit: bool, insulation: str, egc_rule: str):
    """One row per conductor type (phases / neutral / ground) with its gauge, ampacity and the rule
    that defines it, plus the total cross-section for the conduit fill. Phases pass through the
    breaker or fuse; neutral and ground go straight through (the ground is sized by that breaker)."""
    amp = ampacity(ugc)
    conductors = [("UGC", ugc, hot)] + ([("EGC", egc, 1)] if egc_included else [])
    if neutral:
        conductors.insert(1, ("Neutro", ugc, neutral))
    protector = "fusible" if protection == "fuse" else "breaker"
    amp_txt = f"{amp:g} A a 75 °C" if amp is not None else "—"
    rule = {
        "UGC": (f"Fase{'s' if hot > 1 else ''}: pasa por el {protector} de {ocpd} A; ampacidad {amp_txt}" if ocpd is not None
                else f"Fase{'s' if hot > 1 else ''}: ampacidad {amp_txt}"),
        "Neutro": f"Va directo (sin {protector}); lleva la corriente de su fase ({current_a:.0f} A), mismo calibre",
        "EGC": f"Va directo (sin {protector}); {egc_rule}",
    }
    rows, total_mm2, missing = [], 0.0, False
    pipe_runs = qty if shared_conduit else 1
    for role, g, n in conductors:
        a = conductor_area(g, insulation)
        if a is None:
            missing = True
        else:
            total_mm2 += a * n * (1 if role == "EGC" else pipe_runs)   # one EGC serves every run in a shared pipe
        rows.append({"role": role, "gauge": g, "count": n, "mm2": a, "ampacity": ampacity(g), "rule": rule[role]})
    return rows, total_mm2, missing


def size_branch(
    label: str, *, kind: str, qty: int, current_a: float, factor: float, v_ref: float, length_m: float,
    hot: int = 2, neutral: int = 0, ocpd_override: int | None = None,
    insulation: str = DEFAULT_INSULATION, conduit_type: str = DEFAULT_CONDUIT, note: str | None = None,
    egc_included: bool = True, protection: str = "breaker", ocpd_choices: tuple | None = None,
    min_gauge: str | None = None, shared_conduit: bool = False,
    stocked_only: bool = False, min_conduit_trade: str | None = None,
) -> dict:
    """Size one branch end to end. `current_a` is the branch current WITHOUT adjustment
    factors (used for voltage drop, like the workbook); `factor` is the multiplier that
    turns it into the NEC design current. `kind` is "dc" or "ac". `egc_included=False` leaves the
    equipment-grounding conductor out of this branch's conductor count (conduit fill and metres) —
    used for DC branches that carry only + and −.

    `protection` is "breaker" or "fuse" (reporting only). `ocpd_choices` restricts the OCPD to a
    fixed set of ratings (e.g. the fuses a Lynx Power In bus takes): the smallest one >= the design
    current is used, and the conductor is then enlarged until its ampacity allows that rating — a
    conductor may only be protected by the next standard size above its ampacity (NEC 240.4(B)), so
    a 200 A fuse cannot sit on a 130 A cable.

    `shared_conduit` puts the `qty` runs in ONE raceway (e.g. both PV strings, or the AC wiring of two
    inverters, share a pipe): the conduit is sized for all their conductors together and counted once.

    `stocked_only` skips the AWG sizes dealers do not carry (#3, #1): the next one up is used.
    `min_conduit_trade` is a practice floor for the raceway (solar wiring is always at least 1").
    `min_gauge` is a practice floor (e.g. Pauly always pulls #10 solar cable): the conductor starts
    there when the ampacity would allow something smaller. The EGC still derives from the
    gauge the floor starts from, as the workbook derives it from the initial gauge."""
    notes: list[str] = [note] if note else []
    design_a = round(current_a * factor, 2)
    ugc_raw = initial_gauge(design_a)
    ugc_i = initial_gauge(design_a, stocked_only=stocked_only)
    out: dict = {
        "label": label, "kind": kind, "qty": qty, "current_a": round(current_a, 2), "design_a": design_a,
        "length_m": length_m, "v_ref": round(v_ref, 1), "notes": notes, "ok": True,
        "insulation": insulation, "protection": protection, "raceways": 1 if shared_conduit else qty,
    }
    if ugc_i is None:
        out.update(ok=False, ugc=None, ocpd_a=ocpd_override or ocpd_size(design_a), conduit=None)
        notes.append("La corriente excede la tabla T310.15(B)(16): requiere conductores en paralelo (fuera del alcance de esta herramienta).")
        return out

    vd = vdrop_dc if kind == "dc" else vdrop_ac
    start_g = ugc_i
    if ugc_raw != ugc_i:
        notes.append(f"El calibre mínimo seguro sería {ugc_raw} AWG, pero no se vende: se usa {ugc_i} AWG.")
    if min_gauge and T.GAUGE_ORDER.index(min_gauge) > T.GAUGE_ORDER.index(ugc_i):
        start_g = min_gauge
        notes.append(f"Calibre mínimo de práctica: {min_gauge} AWG (la ampacidad permitiría {ugc_i} AWG).")
    start = T.GAUGE_ORDER.index(start_g)
    ugc = start_g
    vd_v = vd(ugc, current_a, length_m)
    for g in [g for g in T.GAUGE_ORDER[start:] if g in _order(stocked_only)]:
        ugc = g
        vd_v = vd(g, current_a, length_m)
        if v_ref and vd_v / v_ref * 100.0 <= VD_LIMIT_PCT:
            break
    vd_pct = vd_v / v_ref * 100.0 if v_ref else 0.0
    vd_pct_initial = vd(ugc_i, current_a, length_m) / v_ref * 100.0 if v_ref else 0.0
    if vd_pct > VD_LIMIT_PCT:
        out["ok"] = False
        notes.append(f"La caída de tensión ({vd_pct:.2f} %) supera {VD_LIMIT_PCT:.0f} % incluso con el calibre máximo de la tabla.")
    vd_g = ugc                      # gauge after the voltage-drop step, before any OCPD-driven enlargement

    if ocpd_override is not None:
        ocpd = ocpd_override
    elif ocpd_choices:
        ocpd = next((c for c in sorted(ocpd_choices) if c >= design_a), None)
        if ocpd is None:
            out["ok"] = False
            notes.append(f"La corriente de diseño ({design_a:.0f} A) supera el {'fusible' if protection == 'fuse' else 'dispositivo'} "
                         f"máximo disponible ({max(ocpd_choices)} A): requiere conductores/protecciones en paralelo.")
    else:
        ocpd = ocpd_size(design_a)
    # A conductor may only carry an OCPD up to the next standard size above its ampacity (NEC 240.4(B)).
    # A restricted set (fuses) can force a larger rating than the design current needs -> enlarge the cable.
    if ocpd is not None:
        for g in [g for g in T.GAUGE_ORDER[T.GAUGE_ORDER.index(ugc):] if g in _order(stocked_only)]:
            a = ampacity(g)
            if a is not None and ocpd <= ocpd_size(a):
                if g != ugc:
                    notes.append(f"Conductor subido de {ugc} a {g} para poder llevar el {'fusible' if protection == 'fuse' else 'dispositivo'} de {ocpd} A.")
                    ugc = g
                    vd_v = vd(ugc, current_a, length_m)
                    vd_pct = vd_v / v_ref * 100.0 if v_ref else 0.0
                break
    amp = ampacity(ugc)
    if ocpd is not None and amp is not None and ocpd > amp:
        notes.append(f"OCPD de {ocpd} A mayor que la ampacidad del conductor ({amp:.0f} A): permitido por NEC 240.4(B) (siguiente tamaño estándar).")

    # Equipment ground: by the protective device (T250.122), never larger than the phase conductors.
    egc_rule = None
    if ocpd is not None:
        egc = egc_gauge_ocpd(ocpd, start_g, vd_g)
        egc_rule = f"T250.122 por {'fusible' if protection == 'fuse' else 'breaker'} de {ocpd} A" + (
            " + 250.122(B) por caída de tensión" if vd_g != start_g else "")
    else:
        egc = egc_gauge(start_g, ugc)
        egc_rule = "T250.66 (sin protección definida)"
    if stocked_only and egc in UNSTOCKED_GAUGES:
        egc = _next_stocked(egc)
        egc_rule += f" · {egc} AWG por ser el calibre que se vende"
    if T.GAUGE_ORDER.index(egc) > T.GAUGE_ORDER.index(ugc):
        egc = ugc
        egc_rule += " · limitada al calibre de las fases (250.122(A))"

    rows, total_mm2, missing = build_rows(
        ugc=ugc, egc=egc, hot=hot, neutral=neutral, egc_included=egc_included, ocpd=ocpd, protection=protection,
        current_a=current_a, qty=qty, shared_conduit=shared_conduit, insulation=insulation, egc_rule=egc_rule)
    conduit = None if missing else pick_conduit(total_mm2, conduit_type, min_conduit_trade)
    if conduit and min_conduit_trade and conduit["trade"] == min_conduit_trade and pick_conduit(total_mm2, conduit_type)["trade"] != min_conduit_trade:
        notes.append(f"Tubo mínimo de práctica: {min_conduit_trade}″ (el relleno permitiría uno menor).")
    if conduit is None:
        out["ok"] = False
        notes.append("No hay área de conducto PVC suficiente en la tabla para esta combinación de conductores.")

    out.update({
        "ugc_initial": ugc_i, "ugc_from": start_g, "ugc": ugc, "ugc_ampacity": amp, "upsized_for_vd": ugc != start_g,
        "ocpd_a": ocpd, "vd_v": round(vd_v, 2), "vd_pct": round(vd_pct, 2), "vd_pct_initial": round(vd_pct_initial, 2),
        "egc": egc if egc_included else None, "conductors": rows, "total_mm2": round(total_mm2, 1), "conduit": conduit,
        "hot": hot, "neutral": neutral, "egc_included": egc_included, "shared_conduit": shared_conduit,
        "egc_rule": egc_rule,
    })
    return out


def apply_manual(b: dict, manual: dict | None) -> dict:
    """Overlay the engineer's own breaker/fuse rating and/or phase gauge on a sized branch and judge it.

    The calculated values stay in `b["calc"]`. The verdict (`b["manual"]`) has a check per field:
    * a LARGER gauge than calculated is fine (more margin);
    * a gauge whose ampacity does not cover the design current is dangerous (unless the branch is
      capped by the manufacturer, e.g. the AC input, where the breaker limits the current: then the
      conductor only has to be protected by it, NEC 240.4(B));
    * a breaker/fuse above what protects the conductor (240.4(B): next standard size above its
      ampacity) or above the manufacturer's maximum is dangerous;
    * a breaker/fuse below the design current trips under normal load (not compliant), unless the
      branch is manufacturer-limited (a lower breaker then just caps the input).
    The ground, conduit fill and voltage drop are recomputed from the manual values."""
    if not manual or not b.get("ugc"):
        return b
    man_a, man_g = manual.get("ocpd_a"), manual.get("ugc")
    if man_g not in T.GAUGE_ORDER:
        man_g = None
    if not man_a and not man_g:
        return b
    calc_a, calc_g = b["ocpd_a"], b["ugc"]
    ugc, ocpd = man_g or calc_g, int(man_a) if man_a else calc_a
    amp = ampacity(ugc)
    limited = bool(b.get("limited"))
    max_a = b.get("max_ocpd_a")
    design = b.get("design_a") or 0.0
    protector = "fusible" if b.get("protection") == "fuse" else "breaker"
    msgs: list[str] = []
    g_ok = a_ok = None

    # protection of the conductor (applies to whichever of the two was changed)
    prot_cap = ocpd_size(amp) if amp is not None else None
    protected = prot_cap is None or ocpd <= prot_cap
    covers = amp is None or amp >= design or (limited and protected)

    if man_g:
        g_ok = covers
        if not covers:
            msgs.append(f"{gauge_label(ugc)} aguanta {amp:g} A, menos que la corriente de diseño ({design:.0f} A).")
        elif T.GAUGE_ORDER.index(ugc) > T.GAUGE_ORDER.index(calc_g):
            msgs.append(f"{gauge_label(ugc)} es mayor que el calculado ({gauge_label(calc_g)}): más holgado, sin riesgo.")
        elif ugc != calc_g:
            msgs.append(f"{gauge_label(ugc)} es menor que el calculado ({gauge_label(calc_g)}) pero cubre la carga"
                        + (" con el breaker que la limita (NEC 240.4(B))." if limited else "."))
        if not protected:
            g_ok = False
            msgs.append(f"El {protector} de {ocpd} A no protege a {gauge_label(ugc)}: NEC 240.4(B) permite máx. {prot_cap} A.")
    if man_a:
        a_ok = True
        if not protected:
            a_ok = False
            if not man_g:
                msgs.append(f"{ocpd} A supera lo que protege a {gauge_label(ugc)} ({amp:g} A): NEC 240.4(B) permite máx. {prot_cap} A.")
        if max_a and ocpd > max_a:
            a_ok = False
            msgs.append(f"{ocpd} A supera el máximo del fabricante ({max_a} A).")
        if not limited and ocpd < design:
            a_ok = False
            msgs.append(f"{ocpd} A es menor que la corriente de diseño ({design:.0f} A): dispararía con carga normal.")
        if a_ok and ocpd != calc_a:
            msgs.append(f"{ocpd} A difiere del calculado ({calc_a} A) pero está dentro de los límites.")

    # recompute what depends on the manual values
    kind_vd = vdrop_dc if b["kind"] == "dc" else vdrop_ac
    vd_v = kind_vd(ugc, b["current_a"], b["length_m"])
    egc = None
    if b.get("egc_included") or b.get("egc"):
        egc = egc_gauge_ocpd(ocpd, ugc, ugc)
        egc_rule = f"T250.122 por {protector} de {ocpd} A (valor manual)"
        if T.GAUGE_ORDER.index(egc) > T.GAUGE_ORDER.index(ugc):
            egc, egc_rule = ugc, egc_rule + " · limitada al calibre de las fases (250.122(A))"
    else:
        egc_rule = b.get("egc_rule") or ""
    rows, total_mm2, missing = build_rows(
        ugc=ugc, egc=egc or ugc, hot=b["hot"], neutral=b["neutral"], egc_included=bool(egc), ocpd=ocpd,
        protection=b.get("protection", "breaker"), current_a=b["current_a"], qty=b["qty"],
        shared_conduit=bool(b.get("shared_conduit")), insulation=b["insulation"], egc_rule=egc_rule)
    conduit = None if missing else pick_conduit(total_mm2, (b.get("conduit") or {}).get("type") or DEFAULT_CONDUIT)
    b["calc"] = {"ocpd_a": calc_a, "ugc": calc_g, "egc": b.get("egc")}
    b.update({
        "ocpd_a": ocpd, "ugc": ugc, "ugc_ampacity": amp, "egc": egc, "conductors": rows, "total_mm2": round(total_mm2, 1),
        "conduit": conduit, "vd_v": round(vd_v, 2), "vd_pct": round(vd_v / b["v_ref"] * 100.0, 2) if b.get("v_ref") else 0.0,
        "upsized_for_vd": False,
        "manual": {"ocpd_a": int(man_a) if man_a else None, "ugc": man_g, "ocpd_ok": a_ok, "ugc_ok": g_ok, "msgs": msgs,
                   "ok": all(x is not False for x in (a_ok, g_ok))},
    })
    return b


def gauge_label(gauge: str) -> str:
    """'8' -> '8 AWG', '250' -> '250 kcmil' (the workbook's rule: <= 4/0 is AWG)."""
    return f"{gauge} AWG" if T.T8_CMILS[gauge] <= T.T8_CMILS["4/0"] else f"{gauge} kcmil"


def conductor_meters(branches: list[dict]) -> dict[str, float]:
    """Total conductor length per gauge (m) across all branches, quantities included —
    the raw input for a future wiring materials line."""
    totals: dict[str, float] = {}
    for b in branches:
        for row in b.get("conductors") or []:
            runs = b.get("raceways", b["qty"]) if row["role"] == "EGC" else b["qty"]
            totals[row["gauge"]] = totals.get(row["gauge"], 0.0) + row["count"] * runs * b["length_m"]
    return {g: round(totals[g], 1) for g in T.GAUGE_ORDER if g in totals}
