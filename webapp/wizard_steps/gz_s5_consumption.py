"""Grid Zero Step 5 — Historial de consumo eléctrico. Port of
wizard/grid_zero.py:step5_consumption() + its `_render_bill_section()` /
`_render_loads_section()` helpers.

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls. Every action route below (source
switch, bill extract/apply, tablero extract, loads table edit/add/remove/
apply, 12-month table recompute) patches `blob["scratch"]["s5"]` and then
re-renders the WHOLE `_s5_consumo.html` region via this same
`build_context()` — never a hand-built fragment — so the source badge, the
12-month table and the metrics/chart can never drift out of sync with each
other (this is exactly the failure mode §1.3 warns about: an action that
only recomputes the panel it touched leaves a sibling panel stale).

`scratch.s5` shape (PLAN §1.1's example, filled in here):
    {"selected_source": "bill"|"loads"|"manual",
     "bill_history": [...], "bill_meta": {...}, "bill_errors": [...],
     "loads_data": [...], "loads_from_tablero": bool,
     "applied_months": [...], "applied_source_meta": {...}}

Do-not-drop items carried from PLAN §1.10:
  4. `applied_source_meta`'s "· editada" suffix rule (`_updated_badge()`).
  9. `consumption.loads_display` is intentionally NOT introduced here —
     Grid Zero's loads table (unlike Off-Grid's, PLAN §1.10 item 1) has no
     `Categoría` column and is never persisted into the durable
     `consumption` section at all (Streamlit doesn't either: `w5_loads_data`
     is a transient widget key, and only the *applied 12-month grid* — not
     the loads table itself — becomes `wizard_consumption`). Nothing to
     round-trip here; item 9 is an Off-Grid/Hybrid concern (Step 7/9).
  23. `interconnection_permit_usd` is captured into `consumption` verbatim;
      Step 7's use of it as a cost-line override is out of this step's scope.
  26. the zero-export disclaimer lives in Step 4 (gz_s4_utility.py) since
      that is where the fixed-charge caption is shown; Step 5 only carries
      the tariff fields Step 4 already resolved.
"""
from __future__ import annotations

from calculations.load_estimator import DEFAULT_LOADS
from calculations.sizing_grid_zero import MONTHS_ES

_MONTH_ABBR_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

_SOURCE_OPTIONS = [
    ("bill", "📄 Subir factura (PDF)"),
    ("loads", "⚡ Cargas instaladas"),
    ("manual", "✍️ Manual"),
]
_SOURCE_VALUES = {v for v, _ in _SOURCE_OPTIONS}
_SOURCE_LABELS = {"bill": "Factura eléctrica", "loads": "Cargas instaladas", "manual": "Ingreso manual"}

# DEFAULT_LOADS (imported above) is calculations.load_estimator's own
# default table, same shape/order Streamlit's _DEFAULT_LOADS used — imported
# rather than re-typed so the two never drift.
_LOADS_FIELDS = ["desc", "w", "und", "hd", "dm"]


# ── scratch helpers ──────────────────────────────────────────────────────


def _s5(blob: dict) -> dict:
    return (blob.get("scratch") or {}).get("s5") or {}


def _rows_to_loads(rows: list[dict]) -> list[dict]:
    from webapp.wizard_steps.common import to_float

    loads = []
    for row in rows:
        loads.append({
            "Descripción": row.get("desc") or "",
            "W": to_float(row.get("w"), 0.0) or 0.0,
            "Und": to_float(row.get("und"), 1.0) or 1.0,
            "h/día": to_float(row.get("hd"), 0.0) or 0.0,
            "días/mes": to_float(row.get("dm"), 0.0) or 0.0,
        })
    return loads


def _overwrite_text(source_meta: dict) -> str:
    label = source_meta.get("label") or _SOURCE_LABELS.get(source_meta.get("source"), source_meta.get("source"))
    return f"La tabla tiene datos de {label}. Al aplicar se reemplazarán."


def _updated_badge(selected_source: str, prev_meta: dict | None) -> dict:
    """Verbatim port of step5_consumption()'s auto-recalculate block
    (wizard/grid_zero.py L442-451) — do-not-drop item 4's "· editada" rule.
    While the Manual tab is active, any edit simply becomes "Ingreso
    manual"; editing the table while an imported source is active appends
    "· editada" to that source's existing label (once, not repeatedly)."""
    prev_meta = prev_meta or {}
    if selected_source == "manual" or not prev_meta.get("source"):
        return {"source": "manual", "label": "Ingreso manual"}
    base_label = prev_meta.get("label") or _SOURCE_LABELS.get(prev_meta["source"], prev_meta["source"])
    if not base_label.endswith("· editada"):
        base_label = base_label + " · editada"
    return {"source": prev_meta["source"], "label": base_label}


def _tariff_info(utility: dict) -> dict | None:
    tariff_id = utility.get("tariff_type_id")
    if not tariff_id:
        return None
    from database.tariffs_db import get_tariff_tiers

    return {
        "access_charge_crc": utility.get("access_charge_crc", 0),
        "bomberos_pct": utility.get("bomberos_pct", 0.0175),
        "iva_threshold_kwh": utility.get("iva_threshold_kwh", 280),
        "tiers": get_tariff_tiers(tariff_id),
    }


def _location(site: dict) -> str:
    return ", ".join(filter(None, [site.get("city"), site.get("province"), "Costa Rica"]))


# ── source switch ────────────────────────────────────────────────────────


def select_source(source: str) -> dict:
    if source not in _SOURCE_VALUES:
        source = "manual"
    return {"selected_source": source}


# ── bill section ─────────────────────────────────────────────────────────


def extract_bills(blob: dict, files: list) -> dict:
    """`factura/extraer`'s core logic — verbatim port of
    `_render_bill_section()`'s upload-and-extract branch, including the
    immediate tariff-based `fill_bill_amounts()` pass. An empty `files` list
    (nothing selected) clears any previously extracted history, matching
    the Streamlit handler's own early-return-and-clear."""
    s5 = _s5(blob)
    if not files:
        return {**s5, "bill_history": [], "bill_meta": {}, "bill_errors": []}

    from calculations.bill_parser import parse_bill_pdf
    from calculations.tariff_calculator import fill_bill_amounts

    utility = blob.get("utility") or {}
    all_history: list[dict] = []
    meta: dict = {}
    errors: list[str] = []
    for f in files:
        try:
            result = parse_bill_pdf(f.read())
            all_history.extend(result.get("history", []))
            meta = {"distributor": result.get("distributor", ""), "nise": result.get("nise", "")}
        except Exception as exc:
            errors.append(f"{getattr(f, 'filename', 'archivo')}: {exc}")

    if all_history:
        tariff_info = _tariff_info(utility)
        if tariff_info:
            try:
                all_history = fill_bill_amounts(all_history, tariff_info)
            except Exception:
                pass  # fail silently — bill amounts stay as extracted

    return {**s5, "bill_history": all_history, "bill_meta": meta, "bill_errors": errors}


def apply_bill_history(blob: dict) -> dict:
    """`factura/aplicar`'s core logic — verbatim port of the "Aplicar al
    historial de 12 meses" button, including the badge's date-range label
    (do-not-drop item 4)."""
    from calculations.bill_parser import build_12_month_grid

    s5 = _s5(blob)
    history = s5.get("bill_history") or []
    meta = s5.get("bill_meta") or {}
    utility = blob.get("utility") or {}
    site = blob.get("site") or {}

    grid = build_12_month_grid(history, location=_location(site), tariff_info=_tariff_info(utility))

    months_with_data = [(h["month"], h["year"]) for h in history if float(h.get("kwh") or 0) > 0]
    if months_with_data:
        mn_m, mn_y = min(months_with_data, key=lambda x: (x[1], x[0]))
        mx_m, mx_y = max(months_with_data, key=lambda x: (x[1], x[0]))
        range_str = f"{_MONTH_ABBR_ES[mn_m - 1]} {mn_y} – {_MONTH_ABBR_ES[mx_m - 1]} {mx_y}"
    else:
        range_str = f"{len(history)} meses"

    return {
        **s5,
        "applied_months": grid,
        "applied_source_meta": {
            "source": "bill",
            "label": f"Factura {meta.get('distributor', '')} · {range_str}",
        },
    }


# ── loads section ────────────────────────────────────────────────────────


def extract_tablero(blob: dict, file_bytes: bytes, media_type: str) -> dict:
    """`tablero/extraer`'s core logic. Raises on failure (mirrors
    `parse_tablero()`'s own contract) — the caller route is responsible for
    catching and surfacing the error, same as the bill-extract route does
    for its own per-file errors."""
    from calculations.tablero_parser import parse_tablero

    s5 = _s5(blob)
    loads = parse_tablero(file_bytes, media_type)
    return {**s5, "loads_data": loads, "loads_from_tablero": True}


def update_loads_table(blob: dict, form) -> dict:
    """Plain cell-edit recompute for the loads table — PLAN §1.5's
    `change`-triggered pattern applied to this second editable grid (not
    called out by name in §1.7's route table, but the same construct as the
    12-month table's `tabla` route)."""
    from webapp.wizard_steps.common import parse_rows

    s5 = _s5(blob)
    rows = parse_rows(form, "row", _LOADS_FIELDS)
    return {**s5, "loads_data": _rows_to_loads(rows), "loads_from_tablero": False}


def add_loads_row(blob: dict, form) -> dict:
    from webapp.wizard_steps.common import parse_rows

    s5 = _s5(blob)
    rows = parse_rows(form, "row", _LOADS_FIELDS)
    loads = _rows_to_loads(rows)
    loads.append({"Descripción": "", "W": 0.0, "Und": 1.0, "h/día": 0.0, "días/mes": 0.0})
    return {**s5, "loads_data": loads, "loads_from_tablero": False}


def remove_loads_row(blob: dict, form) -> dict:
    from webapp.wizard_steps.common import parse_rows

    s5 = _s5(blob)
    rows = parse_rows(form, "row", _LOADS_FIELDS)
    loads = _rows_to_loads(rows)
    idx = int(form.get("_row", -1) or -1)
    if 0 <= idx < len(loads):
        loads.pop(idx)
    return {**s5, "loads_data": loads, "loads_from_tablero": False}


def apply_loads(blob: dict) -> dict:
    """`cargas/aplicar`'s core logic — verbatim port of `_render_loads_section()`'s
    "Aplicar a 12 meses" button."""
    from calculations.load_estimator import estimate_loads_12_months_ai
    from calculations.tariff_calculator import estimate_bill_crc

    s5 = _s5(blob)
    loads_data = s5.get("loads_data") or list(DEFAULT_LOADS)
    site = blob.get("site") or {}
    utility = blob.get("utility") or {}

    monthly_kwh = estimate_loads_12_months_ai(loads_data, location=_location(site))
    tariff_info = _tariff_info(utility)
    grid = [
        {
            "month": MONTHS_ES[i],
            "kwh": round(monthly_kwh[i], 1),
            "bill_crc": float(estimate_bill_crc(monthly_kwh[i], tariff_info))
            if tariff_info and monthly_kwh[i] > 0 else 0.0,
        }
        for i in range(12)
    ]
    n = len(loads_data)
    from_tablero = bool(s5.get("loads_from_tablero"))
    return {
        **s5,
        "applied_months": grid,
        "applied_source_meta": {
            "source": "loads",
            "label": f"Tablero · {n} circuitos" if from_tablero else f"Cargas instaladas · {n} equipos",
        },
    }


# ── 12-month table ───────────────────────────────────────────────────────


def recompute_table(blob: dict, form) -> dict:
    """`paso/5/tabla`'s core logic — PLAN §1.5's live-recompute pattern
    applied to Grid Zero's `Factura (₡)` auto-calculation (verbatim port of
    wizard/grid_zero.py L421-455). Only a genuine kWh change (vs. what's
    currently applied) triggers the tariff recompute + badge update; a
    kWh-unchanged edit (i.e. the human only retyped `Factura (₡)` directly)
    is kept as typed, matching the original's own kwh-only comparison.

    Adaptation forced by the stateless request model (noted, not a silent
    deviation): if no tariff is selected yet, Streamlit's original silently
    skips its whole recompute block, leaving the *just-typed* values visible
    only in the widget's own live state until something else re-runs the
    script. Flask has no such widget-state limbo, so this still persists the
    typed values verbatim (kWh and Factura as submitted) — just without a
    tariff-driven recompute or a badge change — rather than discarding the
    edit outright.
    """
    from webapp.wizard_steps.common import parse_rows, to_float

    s5 = _s5(blob)
    utility = blob.get("utility") or {}
    consumption = blob.get("consumption") or {}
    selected_source = s5.get("selected_source") or consumption.get("source") or "manual"

    rows = parse_rows(form, "m", ["kwh", "bill_crc"])
    old_months = s5.get("applied_months") or consumption.get("months_data") or []
    old_kwh = [round(float((old_months[i] if i < len(old_months) else {}).get("kwh") or 0)) for i in range(12)]

    new_kwh, new_bill = [], []
    for i in range(12):
        row = rows[i] if i < len(rows) else {}
        new_kwh.append(to_float(row.get("kwh"), 0.0) or 0.0)
        new_bill.append(to_float(row.get("bill_crc"), 0.0) or 0.0)
    new_kwh_rounded = [round(v) for v in new_kwh]

    tariff_info = _tariff_info(utility)
    kwh_changed = new_kwh_rounded != old_kwh
    new_meta = s5.get("applied_source_meta")
    if kwh_changed and tariff_info:
        from calculations.tariff_calculator import estimate_bill_crc

        new_bill = [float(estimate_bill_crc(k, tariff_info)) for k in new_kwh]
        new_meta = _updated_badge(selected_source, s5.get("applied_source_meta"))

    months = [{"month": MONTHS_ES[i], "kwh": float(new_kwh[i]), "bill_crc": float(new_bill[i])} for i in range(12)]
    return {**s5, "applied_months": months, "applied_source_meta": new_meta}


# ── Siguiente/Atrás ──────────────────────────────────────────────────────


def save_step(form) -> dict:
    """`Siguiente`/`Atrás`'s persisted fields — verbatim port of
    step5_consumption()'s own return dict. The 12-month table and the
    source radio both live inside the same `<form>` as Siguiente/Atrás
    (PLAN §1.4 pattern 1), so this reads straight from the posted form
    rather than from `scratch` — whatever is on screen is what gets saved,
    same as Streamlit's own `edited_df`-at-click-time semantics."""
    from webapp.wizard_steps.common import parse_rows, to_float

    rows = parse_rows(form, "m", ["kwh", "bill_crc"])
    months_data, kwh_values, bill_values = [], [], []
    for i in range(12):
        row = rows[i] if i < len(rows) else {}
        kwh = to_float(row.get("kwh"), 0.0) or 0.0
        bill = to_float(row.get("bill_crc"), 0.0) or 0.0
        kwh_values.append(kwh)
        bill_values.append(bill)
        months_data.append({"month": MONTHS_ES[i], "kwh": kwh, "bill_crc": bill})

    filled = [v for v in kwh_values if v > 0]
    avg_kwh = round(sum(filled) / len(filled), 2) if filled else 0.0
    filled_bills = [v for v in bill_values if v > 0]
    avg_bill = round(sum(filled_bills) / len(filled_bills)) if filled_bills else 0

    source = form.get("source") or "manual"
    if source not in _SOURCE_VALUES:
        source = "manual"

    icpe = to_float(form.get("icpe_usd"), 1000.0)
    return {
        "source": source,
        "months_data": months_data,
        "avg_kwh": avg_kwh,
        "avg_bill_crc": avg_bill,
        "interconnection_permit_usd": icpe if icpe is not None else 1000.0,
    }


# ── build_context ────────────────────────────────────────────────────────


def build_context(blob: dict) -> dict:
    blob = blob or {}
    consumption = blob.get("consumption") or {}
    s5 = _s5(blob)

    selected_source = s5.get("selected_source") or consumption.get("source") or "manual"
    if selected_source not in _SOURCE_VALUES:
        selected_source = "manual"

    applied_months = s5.get("applied_months")
    if not applied_months or len(applied_months) != 12:
        saved = consumption.get("months_data")
        applied_months = saved if (saved and len(saved) == 12) else None

    source_meta = s5.get("applied_source_meta")
    if not source_meta and consumption.get("source"):
        src = consumption["source"]
        source_meta = {"source": src, "label": f"{_SOURCE_LABELS.get(src, src)} (guardado)"}

    months_rows = applied_months or [{"month": m, "kwh": 0.0, "bill_crc": 0.0} for m in MONTHS_ES]
    kwh_values = [float(row.get("kwh") or 0) for row in months_rows]
    bill_values = [float(row.get("bill_crc") or 0) for row in months_rows]

    filled = [v for v in kwh_values if v > 0]
    avg_kwh = round(sum(filled) / len(filled), 2) if filled else 0.0
    filled_bills = [v for v in bill_values if v > 0]
    avg_bill = round(sum(filled_bills) / len(filled_bills)) if filled_bills else 0

    chart_html = None
    if avg_kwh > 0 and len(filled) >= 3:
        from webapp.figures import consumption_monthly_fig, fig_to_fragment

        chart_html = fig_to_fragment(consumption_monthly_fig(kwh_values))

    bill_history = s5.get("bill_history") or []
    bill_meta = s5.get("bill_meta") or {}
    bill_errors = s5.get("bill_errors") or []

    from calculations.load_estimator import kwh_from_loads

    loads_data = s5.get("loads_data") or list(DEFAULT_LOADS)
    loads_from_tablero = bool(s5.get("loads_from_tablero"))
    loads_total_kwh = kwh_from_loads(loads_data)

    bill_overwrite_note = None
    if bill_history and source_meta and source_meta.get("source") and source_meta["source"] != "bill":
        bill_overwrite_note = _overwrite_text(source_meta)

    loads_overwrite_note = None
    if loads_total_kwh > 0 and source_meta and source_meta.get("source") and source_meta["source"] != "loads":
        loads_overwrite_note = _overwrite_text(source_meta)

    icpe = consumption.get("interconnection_permit_usd")
    if icpe is None:
        icpe = 1000.0

    return {
        "source": selected_source,
        "source_options": _SOURCE_OPTIONS,
        "months": [
            {"name": MONTHS_ES[i], "kwh": kwh_values[i], "bill_crc": bill_values[i]}
            for i in range(12)
        ],
        "avg_kwh": avg_kwh,
        "avg_bill": avg_bill,
        "chart_html": chart_html,
        "source_meta": source_meta,
        "bill_history": bill_history,
        "bill_meta": bill_meta,
        "bill_errors": bill_errors,
        "bill_overwrite_note": bill_overwrite_note,
        "loads_data": loads_data,
        "loads_from_tablero": loads_from_tablero,
        "loads_total_kwh": loads_total_kwh,
        "loads_overwrite_note": loads_overwrite_note,
        "icpe_usd": icpe,
        "can_continue": avg_kwh > 0,
    }
