"""Builds the wall `Spec` of a project from its saved design (equipment, wiring context, materials list) and the sizes stored in the catalog."""
from __future__ import annotations

import re

from plano import layout as L

TABLES = {"inverter": "inverters", "battery": "batteries", "charge_controller": "charge_controllers", "monitoring": "monitoring_devices"}


def _client():
    from database.equipment_db import get_client

    return get_client()


def catalog_dims(table: str, id_: str | None) -> tuple | None:
    """(width, height, depth) in mm of one catalog row, None when the row or its sizes are not there."""
    if not id_:
        return None
    try:
        rows = _client().table(table).select("width_mm, height_mm, depth_mm").eq("id", id_).limit(1).execute().data
    except Exception:
        return None
    if not rows or not rows[0].get("width_mm") or not rows[0].get("height_mm"):
        return None
    r = rows[0]
    return float(r["width_mm"]), float(r["height_mm"]), float(r.get("depth_mm") or 0)


def fixed_dims() -> dict[str, tuple]:
    """{key: (w, h, d)} of the parts without an equipment table (Lynx Power In, gabinete, Chint box, duct)."""
    try:
        rows = _client().table("fixed_equipment_dimensions").select("key, width_mm, height_mm, depth_mm").execute().data
    except Exception:
        return {}
    return {r["key"]: (r.get("width_mm"), r.get("height_mm"), r.get("depth_mm")) for r in rows or []}


def _name(it: dict | None) -> str:
    return f"{(it or {}).get('brand', '')} {(it or {}).get('model', '')}".strip()


def _short(model: str) -> str:
    model = re.sub(r"^(Victron Energy|Fronius|Pylontech)\s+", "", model or "").strip()
    return re.sub(r"/\d+-\d+(/\d+)?(\s+\d+V)?$", "", model).strip()      # MultiPlus-II 48/5000/70-95 -> MultiPlus-II 48/5000


def build_spec(project: dict, d: dict, lines: list[dict], *, dims=catalog_dims, fixed=None) -> L.Spec:
    """`lines` = the materials list lines (they hold the Chint boxes, the load centers and the Lynx bars the rules already worked out)."""
    fixed = fixed if fixed is not None else fixed_dims()
    eq, wiring = d["eq"], d["wiring"]
    system = project.get("system_type") or "hybrid"
    spec = L.Spec(system=system)
    inv = eq.get("inverter") or {}
    qty = max(1, int(eq.get("inverter_qty") or 1)) if inv else 0
    if system == "grid_zero":
        spec.fronius = L.part("fronius", _short(_name(inv)), dims("inverters", inv.get("id")), qty)
    else:
        spec.victron = L.part("victron", _short(_name(inv)), dims("inverters", inv.get("id")), qty)
        cpl = wiring.get("coupling") or {}
        if cpl.get("ac") and cpl.get("pv_inverter"):
            pv = cpl["pv_inverter"]
            spec.fronius = L.part("fronius", _short(_name(pv)), dims("inverters", pv.get("id")), int(cpl.get("qty") or 1))
        else:
            cc = eq.get("charge_controller") or {}
            if cc:
                spec.controllers = L.part("controller", _short(_name(cc)), dims("charge_controllers", cc.get("id")), int(eq.get("charge_controller_qty") or 1))
        bat = eq.get("battery") or {}
        n_bat = int((eq.get("battery_bank") or {}).get("battery_count") or 0)
        if bat and n_bat:
            model = (bat.get("model") or "").lower()
            if "fidus" in model:
                spec.fidus = L.part("fidus", _short(_name(bat)), dims("batteries", bat.get("id")), n_bat)
            else:
                spec.rack = L.part("rack", _short(_name(bat)), dims("batteries", bat.get("id")), n_bat)
    by = {ln["name"]: ln for ln in lines if ln.get("qty")}
    spec.gabinete = L.part("gabinete", "Gabinete 50x40x20", fixed.get("gabinete_50x40x20"), 1, note="medida nominal, por confirmar")
    if spec.gabinete:
        spec.gabinete.real = False      # the nominal 50x40x20 of the list line (POR CONFIRMAR MEDIDA)
    chint = by.get("Centro de carga Chint DC 5 espacios")
    if chint:
        spec.chint = L.part("chint", "Caja Chint DC", fixed.get("chint_dc_5"), int(chint["qty"]), note="alto por confirmar")
        if spec.chint:
            spec.chint.real = False     # width and depth are real, the height is only the hole spacing
    for name, ln in by.items():
        m = re.match(r"Tablero NEMA 3R (\d+) espacios", name)
        if m:
            spec.centers.append(L.center_part(int(m.group(1)), int(ln["qty"])))
    lynx = by.get("Lynx Power In")
    if lynx:
        spec.lynx = L.part("lynx", "Lynx Power In", fixed.get("lynx_power_in"), int(lynx["qty"]))
    spec.centers = [c for c in spec.centers if c]
    return spec
