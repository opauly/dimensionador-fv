"""Plano de techo: what the design says (module size, strings), the saved answers and the fit summary.

The saved plan is one small dict, kept in the same two homes as the other design answers: `blob["scratch"]["roof_plan"]` for a quote version and
`projects.tech_spec["roof_plan"]` for a project (a project starts from its quote's plan until it saves its own).

    {"photo": {"path": storage path, "w": px, "h": px} | None,
     "scale": {"px_per_m": float, "p1": [x, y], "p2": [x, y], "dist_m": float} | None,      # set by clicking two points of a known length
     "gap_mm": 20,                                  # mid clamp between modules
     "strings": [{"id": 1, "count": 8, "rows": 1, "orient": "portrait" | "landscape", "x": px, "y": px, "rot": degrees clockwise}],
     "roof": [[x, y], ...]}                          # optional outline of the roof plane, photo pixels
"""
from __future__ import annotations

import math

from techo import geometry as G

SCRATCH_KEY = "roof_plan"
COLORS = ("#2E86C1", "#E67E22", "#27AE60", "#8E44AD", "#C0392B", "#16A085", "#D4AC0D", "#566573")
DEFAULT_GAP_MM = 20.0
ORIENTS = ("portrait", "landscape")


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def design_info(d: dict) -> dict:
    """Module size and strings of the design (`projects_design.load` result): AC-coupled designs use the string inverter's layout."""
    from materials import engine

    eq = d.get("eq") or {}
    panel = eq.get("panel") or {}
    cpl = (d.get("wiring") or {}).get("coupling") or {}
    if cpl.get("ac") and cpl.get("strings"):
        n_str = int(cpl["strings"])
        per = int(cpl.get("series") or cpl.get("modules_per_string") or 0)
    else:
        n_str, per = int(eq.get("n_strings") or 0), int(eq.get("panels_per_string") or 0)
    total = int(eq.get("panel_count") or (n_str * per))
    counts = [per] * n_str if n_str and n_str * per == total else (
        [total // n_str + (1 if i < total % n_str else 0) for i in range(n_str)] if n_str else ([total] if total else []))
    return {
        "panel": {"brand": panel.get("brand") or "", "model": panel.get("model") or "", "wp": _f(panel.get("wp")),
                  "width_m": _f(panel.get("width_m")), "height_m": _f(panel.get("height_m")), "voc": _f(panel.get("voc")), "isc": _f(panel.get("isc")),
                  "vmp": _f(panel.get("vmp")), "imp": _f(panel.get("imp")), "weight_kg": _f(panel.get("weight_kg"))},
        "counts": counts, "panel_count": total, "gap_m": engine.PANEL_GAP_M,
        "system": _system(d, eq, cpl),
    }


def _system(d: dict, eq: dict, cpl: dict) -> dict:
    """What the sheet says about the system: how the strings connect, the inverter and the powers (kW)."""
    inv = eq.get("inverter") or {}
    if cpl.get("ac") and cpl.get("pv_inverter"):
        pv = cpl["pv_inverter"]
        return {"mode": "ac", "unit": f"{pv.get('brand', '')} {pv.get('model', '')}".strip(), "qty": int(cpl.get("qty") or cpl.get("pv_inverter_qty") or 1),
                "channels": int((cpl.get("check") or {}).get("channels") or pv.get("mppt_channels") or 1), "ac_kw": _f(pv.get("kw")) * int(cpl.get("qty") or 1),
                "voltage": "120/240 Vac"}
    cc = eq.get("charge_controller") or {}
    return {"mode": "dc", "unit": f"{cc.get('brand', '')} {cc.get('model', '')}".strip(), "qty": int(eq.get("charge_controller_qty") or 1), "channels": 1,
            "ac_kw": _f(inv.get("kw")) * int(eq.get("inverter_qty") or 1), "inverter": f"{inv.get('brand', '')} {inv.get('model', '')}".strip(),
            "voltage": "120/240 Vac" if (eq.get("split_phase") or {}).get("requires_split_phase") or int(eq.get("inverter_qty") or 1) > 1 else "120 Vac"}


def system_lines(plan: dict, info: dict) -> list[str]:
    """«DETALLE DE SISTEMA» of the sheet, in the wording of Pauly & Co's roof sheets."""
    p, sy = info["panel"], info.get("system") or {}
    out = ["El sistema se compone de:"]
    for i, s in enumerate(plan["strings"]):
        if not s["count"]:
            continue
        if sy.get("mode") == "ac":
            ch = i % max(1, sy.get("channels", 1)) + 1
            inv = i // max(1, sy.get("channels", 1)) + 1
            out.append(f"1x String de {s['count']} módulos al canal {ch} del inversor {inv}.")
        else:
            out.append(f"1x String de {s['count']} módulos al controlador de carga {i // max(1, math.ceil(len(plan['strings']) / max(1, sy.get('qty', 1)))) + 1}.")
    placed = sum(s["count"] for s in plan["strings"])
    out.append(f"En total son {placed} módulos fotovoltaicos {p['brand']} {p['model']} de {p['wp']:g} W.")
    if sy.get("mode") == "ac":
        out.append(f"El inversor es un {sy['unit']}." if sy.get("qty", 1) == 1 else f"Los {sy['qty']} inversores son {sy['unit']}.")
    else:
        out.append(f"Se instalan {sy.get('qty', 1)} controlador(es) {sy.get('unit', '')} e inversor(es) {sy.get('inverter', '')}.".replace("  ", " "))
    out.append(f"Potencia DC: {placed * p['wp'] / 1000:.1f} kW.")
    if sy.get("ac_kw"):
        out.append(f"Potencia AC: {sy['ac_kw']:g} kW.")
    out.append(f"Voltaje {sy.get('voltage', '120/240 Vac')}.")
    return out


def default_strings(info: dict, photo: dict | None = None) -> list[dict]:
    """One string per design string, stacked near the middle of the photo until the user moves them."""
    w, h = (photo or {}).get("w") or 2000, (photo or {}).get("h") or 1125
    n = max(1, len(info["counts"]))
    return [{"id": i + 1, "count": c, "rows": 1, "orient": "portrait", "x": w / 2, "y": h * (i + 1) / (n + 1), "rot": 0.0}
            for i, c in enumerate(info["counts"] or [info["panel_count"] or 1])]


def clean(plan: dict | None, info: dict | None = None) -> dict:
    plan = plan or {}
    ph = plan.get("photo") if isinstance(plan.get("photo"), dict) and plan["photo"].get("path") else None
    sc = plan.get("scale") if isinstance(plan.get("scale"), dict) and _f((plan.get("scale") or {}).get("px_per_m")) > 0 else None
    strings = []
    for i, s in enumerate(plan.get("strings") or []):
        if not isinstance(s, dict):
            continue
        strings.append({"id": int(s.get("id") or i + 1), "count": max(0, min(200, int(_f(s.get("count"), 0)))),
                        "rows": max(1, min(20, int(_f(s.get("rows"), 1)))), "orient": s.get("orient") if s.get("orient") in ORIENTS else "portrait",
                        "x": _f(s.get("x")), "y": _f(s.get("y")), "rot": _f(s.get("rot")) % 360.0})
    if not strings and info:
        strings = default_strings(info, ph)
    roof = [[_f(p[0]), _f(p[1])] for p in (plan.get("roof") or []) if isinstance(p, (list, tuple)) and len(p) == 2]
    return {"photo": ph and {"path": ph["path"], "w": int(_f(ph.get("w"))), "h": int(_f(ph.get("h")))},
            "scale": sc and {"px_per_m": _f(sc["px_per_m"]), "p1": sc.get("p1"), "p2": sc.get("p2"), "dist_m": _f(sc.get("dist_m"))},
            "gap_mm": max(0.0, min(200.0, _f(plan.get("gap_mm"), DEFAULT_GAP_MM))), "strings": strings, "roof": roof if len(roof) >= 3 else []}


def summary(plan: dict, info: dict) -> dict:
    """Modules placed vs designed, kWp, area and the fit checks (needs a scale)."""
    p = info["panel"]
    placed = sum(s["count"] for s in plan["strings"])
    out = {"placed": placed, "designed": info["panel_count"], "kwp": round(placed * p["wp"] / 1000.0, 2),
           "area_m2": round(placed * p["width_m"] * p["height_m"], 1), "overlaps": [], "outside": {}, "scaled": bool(plan["scale"])}
    if plan["scale"] and p["width_m"] and p["height_m"]:
        chk = G.check(plan["strings"], p["width_m"], p["height_m"], plan["gap_mm"] / 1000.0, plan["scale"]["px_per_m"], [tuple(q) for q in plan["roof"]])
        out["overlaps"], out["outside"] = chk["overlaps"], chk["outside"]
    out["ok"] = bool(out["scaled"] and placed == info["panel_count"] and not out["overlaps"] and not out["outside"])
    return out
