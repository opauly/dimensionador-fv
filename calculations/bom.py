"""Preliminary bill of materials from a saved design plus its wiring sizing.

Pure data in / data out. Inputs are the draft's `equipment` section and the branch list
from `calculations.wiring` (via `webapp.wizard_steps.og_wiring`). Quantities that come
from the wiring sizing are derived, not purchased amounts: conductor and conduit lengths
are the sum over branches of (conductors x runs x length), with a waste allowance, and
PVC conduit is counted in standard 3 m tubes.

This is deliberately the seam for a fuller BOM: later lines (mounting hardware, boxes,
fittings) can be appended here without touching the wiring maths.
"""
from __future__ import annotations

import math

from calculations import wiring as W

WASTE_FACTOR = 0.10      # cut-offs, slack and terminations
PVC_TUBE_LENGTH_M = 3.0  # standard PVC conduit length


def _model(item: dict | None) -> str:
    item = item or {}
    return f"{item.get('brand', '')} {item.get('model', '')}".strip()


def equipment_rows(eq: dict) -> list[dict]:
    """The chosen equipment with its quantity and the datasheet facts the installer needs."""
    panel, inv = eq.get("panel") or {}, eq.get("inverter") or {}
    bat, cc, mon = eq.get("battery") or {}, eq.get("charge_controller") or {}, eq.get("monitoring") or {}
    rows: list[dict] = []
    if panel:
        dims = (f" · {panel.get('height_m')}×{panel.get('width_m')} m" if panel.get("height_m") and panel.get("width_m") else "")
        rows.append({"category": "Paneles solares", "model": _model(panel), "qty": int(eq.get("panel_count") or 0),
                     "specs": f"{panel.get('wp')} W · Voc {panel.get('voc')} V · Vmp {panel.get('vmp')} V · Isc {panel.get('isc')} A · Imp {panel.get('imp')} A{dims}"})
    if inv:
        rows.append({"category": "Inversor/cargador", "model": _model(inv), "qty": int(eq.get("inverter_qty") or 1),
                     "specs": f"{inv.get('kw')} kW · salida {inv.get('output_v')} V · {inv.get('ac_output_current_a') or '—'} A CA · passthrough {inv.get('ac_input_current_max_a') or '—'} A"})
    if bat:
        rows.append({"category": "Baterías", "model": _model(bat), "qty": int((eq.get("battery_bank") or {}).get("battery_count") or 0),
                     "specs": f"{bat.get('capacity_kwh')} kWh · {bat.get('voltage_v')} V · {bat.get('capacity_ah')} Ah · DoD {bat.get('dod_pct')} % · {bat.get('cycles')} ciclos"})
    if cc:
        rows.append({"category": "Controlador de carga", "model": _model(cc), "qty": int(eq.get("charge_controller_qty") or 1),
                     "specs": f"Vin máx {cc.get('vin_max')} V · {cc.get('imax_in')} A entrada · {cc.get('imax_out')} A salida"})
    if mon:
        rows.append({"category": "Monitoreo", "model": _model(mon), "qty": 1, "specs": ""})
    return rows


def protection_rows(branches: list[dict]) -> list[dict]:
    """Breakers/fuses grouped by kind and rating, one per run of each branch."""
    groups: dict[tuple, dict] = {}
    for b in branches:
        if not b.get("ocpd_a"):
            continue
        hot = next((r["count"] for r in b.get("conductors") or [] if r["role"] == "UGC"), 2)
        key = (b["kind"], b["ocpd_a"], hot)
        g = groups.setdefault(key, {"qty": 0, "branches": []})
        g["qty"] += b["qty"]
        g["branches"].append(b["label"])
    rows = []
    for (kind, amps, poles), g in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        rows.append({
            "item": f"{'Breaker/fusible CC' if kind == 'dc' else 'Breaker CA'} {amps} A, {poles} polo{'s' if poles != 1 else ''}",
            "qty": g["qty"], "used_in": " · ".join(g["branches"]),
        })
    return rows


def conductor_rows(branches: list[dict], insulation: str) -> list[dict]:
    """Copper conductor metres by gauge, split live/neutral vs. ground."""
    live: dict[str, float] = {}
    ground: dict[str, float] = {}
    for b in branches:
        for r in b.get("conductors") or []:
            target = ground if r["role"] == "EGC" else live
            target[r["gauge"]] = target.get(r["gauge"], 0.0) + r["count"] * b["qty"] * b["length_m"]
    rows = []
    for title, data in (("activos / neutro", live), ("tierra (EGC)", ground)):
        for g in sorted(data, key=lambda g: W.T.GAUGE_ORDER.index(g)):
            m = round(data[g], 1)
            rows.append({"item": f"Conductor Cu {insulation} {W.gauge_label(g)} — {title}", "meters": m,
                         "with_waste": math.ceil(m * (1 + WASTE_FACTOR))})
    return rows


def conduit_rows(branches: list[dict], conduit_type: str) -> list[dict]:
    """PVC conduit by trade size: metres run and standard 3 m tubes (waste included)."""
    by_size: dict[str, float] = {}
    for b in branches:
        c = b.get("conduit")
        if c:
            by_size[c["trade"]] = by_size.get(c["trade"], 0.0) + b["qty"] * b["length_m"]
    order = [t for t, _m, _a in W.T.T4_PVC_CONDUIT[conduit_type]]
    rows = []
    for trade in sorted(by_size, key=order.index):
        m = round(by_size[trade], 1)
        rows.append({"item": f"Tubería PVC ({conduit_type}) {trade}″", "meters": m,
                     "tubes": math.ceil(m * (1 + WASTE_FACTOR) / PVC_TUBE_LENGTH_M)})
    return rows


def build_bom(eq: dict, wiring_ctx: dict) -> dict:
    """{'equipment': [...], 'protections': [...], 'conductors': [...], 'conduit': [...]}.
    The wiring sections are empty (with `wiring_ready` False) when no branch was sized."""
    branches = wiring_ctx.get("branches") or []
    ready = bool(wiring_ctx.get("ready"))
    return {
        "equipment": equipment_rows(eq),
        "protections": protection_rows(branches) if ready else [],
        "conductors": conductor_rows(branches, wiring_ctx.get("insulation", W.DEFAULT_INSULATION)) if ready else [],
        "conduit": conduit_rows(branches, wiring_ctx.get("conduit_type", W.DEFAULT_CONDUIT)) if ready else [],
        "wiring_ready": ready,
        "waste_pct": int(WASTE_FACTOR * 100),
        "tube_m": PVC_TUBE_LENGTH_M,
    }
