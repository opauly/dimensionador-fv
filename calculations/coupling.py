"""AC-coupled hybrid: the PV side checks.

In an AC-coupled hybrid the PV array feeds an on-grid string inverter (Fronius) instead of
charge controllers, and that inverter is connected on the AC-OUT side of the Victron
MultiPlus-II units (the critical-loads sub-panel). Nothing here touches the battery side.

Pure functions, catalog rows in / plain dicts out, so the wizard step, the project's Técnico tab
and the validation script all share the same numbers. The rules come from Oscar's
`unifilar-hibrido-ac` skill (references/diseno.md) and the Victron AC-coupling guideline.
"""
from __future__ import annotations

import math

# Standard DC breaker ratings of the DIN-rail family Pauly buys for PV strings (NB1-63DC), so a
# string breaker is proposed from stock sizes instead of the AC list the workbook uses.
DC_BREAKER_SIZES_A = (10, 16, 20, 25, 32, 40, 50, 63)

# Practice floor for PV string cable: Pauly buys #10 AWG solar cable for every array, even when the
# ampacity would allow #12.
PV_MIN_GAUGE = "10"

# Solar wiring always goes in at least 1" conduit (bigger than the 3/4" the fill would allow).
PV_MIN_CONDUIT_TRADE = "1"

# Fronius AC output (single phase, split-phase 240 V).
PV_INVERTER_AC_V = 240.0

# DC/AC ratio above which the string inverter clips noticeably (info, not a hard limit).
DC_AC_RATIO_WARN = 1.5


def _f(d: dict | None, key: str, default: float = 0.0) -> float:
    try:
        v = (d or {}).get(key)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def default_layout(panel_count: int, channels: int) -> tuple[int, int]:
    """(strings, modules per string) that fills the MPPT inputs evenly: one string per MPPT,
    as many modules in series as the panel count needs."""
    channels = max(1, channels)
    panel_count = max(1, panel_count)
    strings = min(channels, panel_count)
    return strings, math.ceil(panel_count / strings)


def suggest_pv_inverter(inverters: list[dict], array_kw: float) -> dict | None:
    """Smallest string inverter whose AC rating is at least 95 % of the array (DC/AC ratio ~1);
    the largest one when the array is bigger than all of them."""
    rows = sorted((i for i in inverters if i.get("type") == "string_inverter"), key=lambda i: _f(i, "kw"))
    if not rows:
        return None
    for i in rows:
        if _f(i, "kw") >= 0.95 * array_kw:
            return i
    return rows[-1]


def check_strings(panel: dict, pv_inv: dict, strings: int, series: int, *, qty: int = 1,
                  hybrid_kw_total: float | None = None) -> dict:
    """Is this string layout valid for this PV inverter, and does the PV inverter fit the Multis?

    `strings` are spread over the inverter's MPPT inputs (`mppt_channels`); with more strings than
    inputs the extra ones are paralleled on an MPPT and the current check shows it. Short-circuit
    current is not in the catalog for the PV inverter, so the per-MPPT check uses the module's Imp
    (what the MPPT actually draws) against the inverter's max MPPT current."""
    channels = max(1, int(_f(pv_inv, "mppt_channels", 1)))
    total_channels = channels * max(1, qty)
    spm = math.ceil(strings / total_channels) if strings else 0
    voc, vmp = _f(panel, "voc") * series, _f(panel, "vmp") * series
    imp, isc = _f(panel, "imp"), _f(panel, "isc")
    vmax, vmax_mppt, vmin_mppt = _f(pv_inv, "vmax"), _f(pv_inv, "vmax_mppt"), _f(pv_inv, "vmin_mppt")
    imax = _f(pv_inv, "imax_mppt")
    array_kw = strings * series * _f(panel, "wp") / 1000.0
    inv_kw = _f(pv_inv, "kw") * max(1, qty)
    ratio = array_kw / inv_kw if inv_kw else 0.0

    checks: list[dict] = []

    def add(label: str, ok: bool | None, detail: str) -> None:
        checks.append({"label": label, "ok": ok, "detail": detail})

    hard_v = vmax or vmax_mppt
    if hard_v:
        add("Voc del string (sin corrección por frío) ≤ tensión máx. de entrada", voc <= hard_v,
            f"{voc:.0f} V de {hard_v:.0f} V")
    if vmin_mppt and vmax_mppt:
        add("Vmp del string dentro de la ventana MPPT", vmin_mppt <= vmp <= vmax_mppt,
            f"{vmp:.0f} V en {vmin_mppt:.0f}–{vmax_mppt:.0f} V")
    if imax and spm:
        i_mppt = imp * spm
        add("Corriente por MPPT (Imp × strings) ≤ máx. del inversor", i_mppt <= imax,
            f"{i_mppt:.1f} A de {imax:.0f} A" + (f" ({spm} strings en paralelo por MPPT)" if spm > 1 else ""))
    if strings > total_channels:
        add("Strings ≤ entradas MPPT", None,
            f"{strings} strings sobre {total_channels} entradas MPPT: hay strings en paralelo, revisar la caja combinadora")
    if inv_kw:
        add("Relación CC/CA del arreglo", ratio <= DC_AC_RATIO_WARN, f"{array_kw:.1f} kWp / {inv_kw:.1f} kW = {ratio:.2f}")
    if hybrid_kw_total:
        add("Inversor FV ≤ potencia de los Multis en AC-OUT (guía de Victron)", inv_kw <= hybrid_kw_total + 1e-9,
            f"{inv_kw:.1f} kW de {hybrid_kw_total:.1f} kW de inversores Victron")

    return {
        "strings": strings, "series": series, "channels": total_channels, "strings_per_mppt": spm,
        "voc_string": round(voc, 1), "vmp_string": round(vmp, 1), "imp_string": imp, "isc_string": isc,
        "array_kw": round(array_kw, 2), "dc_ac_ratio": round(ratio, 2), "checks": checks,
        "ok": all(c["ok"] is not False for c in checks),
    }


def pv_inverter_ac_current_a(pv_inv: dict) -> float:
    """Rated AC output current: the catalog value when present, else the Fronius datasheet, else kW / 240 V."""
    cur = _f(pv_inv, "ac_output_current_a")
    if cur:
        return cur
    from calculations.datasheet_limits import fronius_limits

    ds = fronius_limits(pv_inv.get("model"))                 # Fronius datasheet: max continuous output current @240 V
    return ds["out_a"] if ds else _f(pv_inv, "kw") * 1000.0 / PV_INVERTER_AC_V
