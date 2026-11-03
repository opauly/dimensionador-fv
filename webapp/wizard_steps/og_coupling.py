"""PV coupling choice for Hybrid designs: DC-coupled (charge controllers, what the sizing engine
designs) or AC-coupled (a Fronius-class string inverter on the AC-OUT side of the Victron units).

The sizing engine in the Equipos step is DC-coupled and untouched; this module keeps the coupling
choice next to the wiring it changes. The same small dict lives in two homes, like the cable
lengths do: `blob["scratch"]["coupling"]` for a quote being built, `projects.tech_spec["coupling"]`
for a won project.

    {"mode": "dc" | "ac",
     "pv_inverter_id": catalog inverter id (AC only; suggested from the array size when empty),
     "pv_inverter_qty": 1,
     "strings": int | None, "modules_per_string": int | None}   # AC layout; defaults fill the MPPTs

`resolve()` turns that plus the saved design into everything the wiring and BOM need.
"""
from __future__ import annotations

from calculations import coupling as C

SCRATCH_KEY = "coupling"
MODES = ("dc", "ac")


def _int(v, default: int | None = None) -> int | None:
    try:
        n = int(float(str(v).replace(",", ".")))
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


def clean(saved: dict | None) -> dict:
    saved = saved or {}
    mode = saved.get("mode") if saved.get("mode") in MODES else "dc"
    return {
        "mode": mode,
        "pv_inverter_id": saved.get("pv_inverter_id") or None,
        "pv_inverter_qty": _int(saved.get("pv_inverter_qty"), 1),
        "strings": _int(saved.get("strings")),
        "modules_per_string": _int(saved.get("modules_per_string")),
    }


def from_form(form) -> dict | None:
    """The coupling fields of the wiring form, or None when the form does not carry them
    (an older page posting only cable lengths must not reset the choice)."""
    if "coupling_mode" not in form:
        return None
    return clean({
        "mode": form.get("coupling_mode"),
        "pv_inverter_id": form.get("pv_inverter_id"),
        "pv_inverter_qty": form.get("pv_inverter_qty"),
        "strings": form.get("cpl_strings"),
        "modules_per_string": form.get("cpl_series"),
    })


def from_blob(blob: dict) -> dict:
    return clean(((blob or {}).get("scratch") or {}).get(SCRATCH_KEY))


def pv_inverter_options() -> list[dict]:
    from database.equipment_db import list_inverters

    return [i for i in list_inverters() if i.get("type") == "string_inverter"]


def resolve(eq: dict, saved: dict | None) -> dict:
    """{'mode', 'ac': bool, ...}. In AC mode also: 'pv_inverter', 'qty', 'strings', 'series',
    'check' (calculations.coupling.check_strings), 'options', 'selected_id'.

    AC mode needs a panel; with no PV inverter chosen yet one is suggested from the array size and
    the layout defaults to one string per MPPT input."""
    cfg = clean(saved)
    out = {**cfg, "ac": cfg["mode"] == "ac", "pv_inverter": None, "check": None, "options": [], "selected_id": None,
           "strings": cfg["strings"], "series": cfg["modules_per_string"]}
    if not out["ac"]:
        return out

    panel = eq.get("panel") or {}
    options = pv_inverter_options()
    out["options"] = options
    chosen = next((i for i in options if i["id"] == cfg["pv_inverter_id"]), None)
    panel_count = int(eq.get("panel_count") or (eq.get("array") or {}).get("panel_count") or 0)
    array_kw = panel_count * float(panel.get("wp") or 0) / 1000.0
    if chosen is None:
        chosen = C.suggest_pv_inverter(options, array_kw)
    out["pv_inverter"] = chosen
    out["selected_id"] = chosen["id"] if chosen else None
    if not (chosen and panel):
        return out

    qty = cfg["pv_inverter_qty"] or 1
    d_strings, d_series = C.default_layout(panel_count, int(chosen.get("mppt_channels") or 1) * qty)
    strings = cfg["strings"] or d_strings
    series = cfg["modules_per_string"] or d_series
    inv = eq.get("inverter") or {}
    hybrid_kw = float(inv.get("kw") or 0) * int(eq.get("inverter_qty") or 1) or None
    out.update(qty=qty, strings=strings, series=series, panel_count=panel_count,
               check=C.check_strings(panel, chosen, strings, series, qty=qty, hybrid_kw_total=hybrid_kw))
    return out
