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
5. EGC              = T250.66 (as the workbook does) keyed by the initial gauge, then
                      enlarged in proportion to any voltage-drop upsizing (250.122(B):
                      "regla de tres" on circular mils).
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


def initial_gauge(design_a: float, temp_c: int = TERMINAL_TEMP_C) -> str | None:
    """Smallest listed Cu gauge with ampacity >= design current; None if beyond the table."""
    for g in T.GAUGE_ORDER:
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


def pick_conduit(total_mm2: float, conduit_type: str = DEFAULT_CONDUIT) -> dict | None:
    """Smallest PVC trade size whose 40 % fill area >= total conductor area, else None."""
    for trade, metric, area in T.T4_PVC_CONDUIT[conduit_type]:
        if area >= total_mm2:
            return {"trade": trade, "metric": metric, "type": conduit_type,
                    "fill_pct": round(total_mm2 / area * 40.0, 1)}
    return None


def conductor_area(gauge: str, insulation: str = DEFAULT_INSULATION) -> float | None:
    return T.T5_AREA_MM2[insulation].get(gauge)


def size_branch(
    label: str, *, kind: str, qty: int, current_a: float, factor: float, v_ref: float, length_m: float,
    hot: int = 2, neutral: int = 0, ocpd_override: int | None = None,
    insulation: str = DEFAULT_INSULATION, conduit_type: str = DEFAULT_CONDUIT, note: str | None = None,
) -> dict:
    """Size one branch end to end. `current_a` is the branch current WITHOUT adjustment
    factors (used for voltage drop, like the workbook); `factor` is the multiplier that
    turns it into the NEC design current. `kind` is "dc" or "ac"."""
    notes: list[str] = [note] if note else []
    design_a = round(current_a * factor, 2)
    ugc_i = initial_gauge(design_a)
    out: dict = {
        "label": label, "kind": kind, "qty": qty, "current_a": round(current_a, 2), "design_a": design_a,
        "length_m": length_m, "v_ref": round(v_ref, 1), "notes": notes, "ok": True,
        "insulation": insulation,
    }
    if ugc_i is None:
        out.update(ok=False, ugc=None, ocpd_a=ocpd_override or ocpd_size(design_a), conduit=None)
        notes.append("La corriente excede la tabla T310.15(B)(16): requiere conductores en paralelo (fuera del alcance de esta herramienta).")
        return out

    vd = vdrop_dc if kind == "dc" else vdrop_ac
    start = T.GAUGE_ORDER.index(ugc_i)
    ugc = ugc_i
    vd_v = vd(ugc, current_a, length_m)
    for g in T.GAUGE_ORDER[start:]:
        ugc = g
        vd_v = vd(g, current_a, length_m)
        if v_ref and vd_v / v_ref * 100.0 <= VD_LIMIT_PCT:
            break
    vd_pct = vd_v / v_ref * 100.0 if v_ref else 0.0
    vd_pct_initial = vd(ugc_i, current_a, length_m) / v_ref * 100.0 if v_ref else 0.0
    if vd_pct > VD_LIMIT_PCT:
        out["ok"] = False
        notes.append(f"La caída de tensión ({vd_pct:.2f} %) supera {VD_LIMIT_PCT:.0f} % incluso con el calibre máximo de la tabla.")
    egc = egc_gauge(ugc_i, ugc)

    ocpd = ocpd_override if ocpd_override is not None else ocpd_size(design_a)
    amp = ampacity(ugc)
    if ocpd is not None and amp is not None and ocpd > amp:
        notes.append(f"OCPD de {ocpd} A mayor que la ampacidad del conductor ({amp:.0f} A): permitido por NEC 240.4(B) (siguiente tamaño estándar).")

    conductors = [("UGC", ugc, hot), ("EGC", egc, 1)]
    if neutral:
        conductors.insert(1, ("Neutro", ugc, neutral))
    rows, total_mm2, missing = [], 0.0, False
    for role, g, n in conductors:
        a = conductor_area(g, insulation)
        if a is None:
            missing = True
        else:
            total_mm2 += a * n
        rows.append({"role": role, "gauge": g, "count": n, "mm2": a})
    conduit = None if missing else pick_conduit(total_mm2, conduit_type)
    if conduit is None:
        out["ok"] = False
        notes.append("No hay área de conducto PVC suficiente en la tabla para esta combinación de conductores.")

    out.update({
        "ugc_initial": ugc_i, "ugc": ugc, "ugc_ampacity": amp, "upsized_for_vd": ugc != ugc_i,
        "ocpd_a": ocpd, "vd_v": round(vd_v, 2), "vd_pct": round(vd_pct, 2), "vd_pct_initial": round(vd_pct_initial, 2),
        "egc": egc, "conductors": rows, "total_mm2": round(total_mm2, 1), "conduit": conduit,
    })
    return out


def gauge_label(gauge: str) -> str:
    """'8' -> '8 AWG', '250' -> '250 kcmil' (the workbook's rule: <= 4/0 is AWG)."""
    return f"{gauge} AWG" if T.T8_CMILS[gauge] <= T.T8_CMILS["4/0"] else f"{gauge} kcmil"


def conductor_meters(branches: list[dict]) -> dict[str, float]:
    """Total conductor length per gauge (m) across all branches, quantities included —
    the raw input for a future wiring materials line."""
    totals: dict[str, float] = {}
    for b in branches:
        for row in b.get("conductors") or []:
            totals[row["gauge"]] = totals.get(row["gauge"], 0.0) + row["count"] * b["qty"] * b["length_m"]
    return {g: round(totals[g], 1) for g in T.GAUGE_ORDER if g in totals}
