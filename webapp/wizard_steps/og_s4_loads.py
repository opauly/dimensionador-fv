"""Off-Grid Step 4 — Cargas eléctricas y perfil de consumo general. Port of
wizard/off_grid.py:step4_loads() + its `_render_loads_block()` helper.

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls.

`_render_loads_block()` in the Streamlit source is parameterized by
`key_prefix` so it can render twice on the same page — once for Off-Grid's
own critical loads ("w4og"), once for a Hybrid system's separate main-panel
loads ("w4h_mp", PLAN's Step 9). This port carries that same idea forward as
a `scratch_key` argument threaded through every function here (default
"s4og" for Off-Grid's own instance) — Hybrid's Step 9 will call these same
functions with a different scratch_key. The persisted-section side of that
parameterization (where the CONFIRMED table lands on Siguiente — directly
in `consumption` for Off-Grid, a nested sub-dict for Hybrid's main panel,
per wizard/off_grid.py's own `_render_loads_block()` docstring) is NOT
generalized yet — out of this step's scope, left for Step 9 to extend
`save_step()`/`build_context()` accordingly.

`scratch.<scratch_key>` shape (PLAN §1.1's model, filled in here):
    {"loads_data": [{"Descripción","Cantidad","Potencia (kW)","Categoría"}, ...]}

Do-not-drop items carried from PLAN §1.10:
  1. classify_load_category() runs at IMPORT time (tablero/texto), not
     lazily at display time — the engineer sees/corrects the category
     immediately in the resulting table (`_classified_rows()` below).
     Every import method (catálogo/tablero/texto) APPENDS onto whatever's
     already in the table, never replaces it (`_append()` below) — verified
     against wizard/off_grid.py's own `_append_loads()` closure.
  17. `voltage_v` is captured here (`save_step()`); the split-phase warning
      itself renders in Step 6 (`check_split_phase()` needs the chosen
      inverter, which isn't picked until then — wizard/off_grid.py L854-856).
"""
from __future__ import annotations

from calculations.load_profile_off_grid import (
    CATEGORY_LABELS_ES, COMMON_LOADS_CATALOG_V1, classify_load_category,
)

_CATEGORY_AUTO_LABEL = "(Automático)"
_CATEGORY_LABEL_TO_KEY = {v: k for k, v in CATEGORY_LABELS_ES.items()}
# (key, label) pairs for the <select> — "" means "(Automático)", matching
# wizard/off_grid.py's own SelectboxColumn options list (label-keyed there
# since Streamlit's data_editor has no separate value/label concept; this
# port keeps the KEY as the <option> value so round-tripping a selection
# doesn't depend on comparing translated strings).
CATEGORY_SELECT_OPTIONS = [("", _CATEGORY_AUTO_LABEL)] + list(CATEGORY_LABELS_ES.items())
CATALOG_OPTIONS = {f"{c['name']} ({c['nameplate_kw']} kW)": c for c in COMMON_LOADS_CATALOG_V1}

_ROW_FIELDS = ["desc", "qty", "kw", "cat"]

DEFAULT_SCRATCH_KEY = "s4og"


# ── scratch helpers ──────────────────────────────────────────────────────


def _scratch(blob: dict, scratch_key: str) -> dict:
    return (blob.get("scratch") or {}).get(scratch_key) or {}


def _rows_to_display(rows: list[dict]) -> list[dict]:
    from webapp.wizard_steps.common import to_float

    out = []
    for row in rows:
        cat_key = row.get("cat") or ""
        out.append({
            "Descripción": row.get("desc") or "",
            "Cantidad": int(to_float(row.get("qty"), 1.0) or 1),
            "Potencia (kW)": to_float(row.get("kw"), 0.0) or 0.0,
            "Categoría": CATEGORY_LABELS_ES.get(cat_key, _CATEGORY_AUTO_LABEL),
        })
    return out


def _loads_to_taxonomy_list(loads_display: list[dict]) -> list[dict]:
    """Verbatim port of wizard/off_grid.py:_loads_to_taxonomy_list() — the
    shape build_load_profile() (Step 5) expects."""
    return [
        {
            "name": r.get("Descripción", ""),
            "quantity": int(r.get("Cantidad") or 1),
            "nameplate_kw": float(r.get("Potencia (kW)") or 0),
            "category": _CATEGORY_LABEL_TO_KEY.get(r.get("Categoría")),
        }
        for r in loads_display
        if r.get("Descripción")
    ]


def _classified_rows(extracted: list[dict]) -> list[dict]:
    """Runs classify_load_category() at IMPORT time (do-not-drop item 1) —
    verbatim port of wizard/off_grid.py:_render_loads_block()'s
    `_classified_rows()` closure."""
    rows = []
    for r in extracted:
        category_key = classify_load_category(r["Descripción"])
        rows.append({
            "Descripción": r["Descripción"],
            "Cantidad": r["Cantidad"],
            "Potencia (kW)": r["Potencia (kW)"],
            "Categoría": CATEGORY_LABELS_ES.get(category_key, _CATEGORY_AUTO_LABEL),
        })
    return rows


def _current_loads_display(blob: dict, scratch_key: str) -> list[dict]:
    """Whatever the table currently shows — scratch if any action has
    touched it this session, else the persisted consumption.loads_display
    (a draft resumed after Siguiente was already clicked once, or opened
    fresh at this step for the first time)."""
    scratch = _scratch(blob, scratch_key)
    if "loads_data" in scratch:
        return scratch["loads_data"]
    consumption = blob.get("consumption") or {}
    return list(consumption.get("loads_display") or [])


def _append(blob: dict, scratch_key: str, new_rows: list[dict]) -> dict:
    """Every import method (catálogo/tablero/texto) appends onto whatever's
    already in the table — never replaces (PLAN's explicit requirement)."""
    current = _current_loads_display(blob, scratch_key)
    return {"loads_data": current + new_rows}


# ── catálogo ─────────────────────────────────────────────────────────────


def add_catalog_rows(blob: dict, scratch_key: str, picks: list[str]) -> dict:
    new_rows = []
    for label in picks:
        item = CATALOG_OPTIONS.get(label)
        if not item:
            continue
        new_rows.append({
            "Descripción": item["name"],
            "Cantidad": 1,
            "Potencia (kW)": item["nameplate_kw"],
            "Categoría": CATEGORY_LABELS_ES[item["category"]],
        })
    return _append(blob, scratch_key, new_rows)


# ── tablero / texto (§1.7's exact routes) ────────────────────────────────


def extract_tablero(blob: dict, scratch_key: str, file_bytes: bytes, media_type: str) -> dict:
    """Raises on failure (parse_tablero_off_grid()'s own contract) — the
    caller route catches and surfaces the error, same as Grid Zero's
    equivalent tablero-extract route does."""
    from calculations.tablero_parser import parse_tablero_off_grid

    extracted = parse_tablero_off_grid(file_bytes, media_type)
    return _append(blob, scratch_key, _classified_rows(extracted))


def extract_text(blob: dict, scratch_key: str, text: str) -> dict:
    from calculations.tablero_parser import parse_tablero_text_off_grid

    extracted = parse_tablero_text_off_grid(text)
    return _append(blob, scratch_key, _classified_rows(extracted))


# ── editable table — change-triggered sync, +Fila, quitar fila ──────────
# The `change`-triggered sync route matters even though Siguiente reads
# straight from the posted form (like Grid Zero Step 5's loads table): any
# OTHER action (catálogo/tablero/texto/+Fila/quitar) re-renders the whole
# #s4og-cargas fragment from scratch, so an inline edit that hasn't yet been
# synced to scratch would otherwise be silently overwritten by that swap.


def update_table(blob: dict, scratch_key: str, form) -> dict:
    from webapp.wizard_steps.common import parse_rows

    rows = parse_rows(form, "row", _ROW_FIELDS)
    return {"loads_data": _rows_to_display(rows)}


def add_row(blob: dict, scratch_key: str, form) -> dict:
    from webapp.wizard_steps.common import parse_rows

    rows = parse_rows(form, "row", _ROW_FIELDS)
    loads = _rows_to_display(rows)
    loads.append({"Descripción": "", "Cantidad": 1, "Potencia (kW)": 0.0, "Categoría": _CATEGORY_AUTO_LABEL})
    return {"loads_data": loads}


def remove_row(blob: dict, scratch_key: str, form) -> dict:
    from webapp.wizard_steps.common import parse_rows

    rows = parse_rows(form, "row", _ROW_FIELDS)
    loads = _rows_to_display(rows)
    idx = int(form.get("_row", -1) or -1)
    if 0 <= idx < len(loads):
        loads.pop(idx)
    return {"loads_data": loads}


# ── Siguiente/Atrás ──────────────────────────────────────────────────────


def save_step(form) -> dict:
    """Verbatim port of step4_loads()'s `_build_consumption_result()` —
    reads straight from the posted form (whatever's on screen at
    Siguiente-click time), same pattern as
    gz_s5_consumption.save_step()/apply_loads()'s sibling table."""
    from webapp.wizard_steps.common import parse_rows, to_float

    rows = parse_rows(form, "row", _ROW_FIELDS)
    loads_display = _rows_to_display(rows)

    autonomy_days = to_float(form.get("autonomy_days"), 1.0) or 1.0
    autonomy_days = min(7.0, max(0.5, round(autonomy_days * 2) / 2))
    voltage_v = 240 if form.get("voltage") == "240" else 120

    return {
        "autonomy_days": float(autonomy_days),
        "voltage_v": voltage_v,
        "loads_display": loads_display,   # keeps the Categoría column round-trippable (do-not-drop item 9)
        "loads": _loads_to_taxonomy_list(loads_display),
    }


# ── build_context ────────────────────────────────────────────────────────


def build_context(blob: dict, scratch_key: str = DEFAULT_SCRATCH_KEY) -> dict:
    blob = blob or {}
    consumption = blob.get("consumption") or {}

    loads_data = _current_loads_display(blob, scratch_key)
    autonomy_days = float(consumption.get("autonomy_days") or 1.0)
    voltage_v = consumption.get("voltage_v") or 120

    return {
        "scratch_key": scratch_key,
        "autonomy_days": autonomy_days,
        "voltage_v": voltage_v,
        "catalog_options": list(CATALOG_OPTIONS.keys()),
        "category_options": CATEGORY_SELECT_OPTIONS,
        "loads_data": loads_data,
        "can_continue": len(loads_data) > 0,
    }
