"""Grid Zero Step 7 — Detalles de costos. Port of
wizard/grid_zero.py:step7_costs() + its `_load_service_defaults()` /
`_get_current_prices()` / `_refresh_prices()` helpers.

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls. Unlike Steps 5/6, this step has no
`scratch` namespace of its own: `costs` is already one of the seven durable
blob sections (PLAN §1.1), and every action here (row edit, +Fila, quitar
fila, Refrescar precios) writes its result straight into `blob["costs"]`
via `draft.patch(vid, "costs", ...)` in the blueprint — there is no
"draft-vs-committed" distinction to preserve the way Step 5's bill history
or Step 6's scenario set need one. This also means a browser refresh
mid-edit keeps whatever was last change-triggered, same guarantee Steps 5/6
give.

Line item shape stored in `costs.line_items` (matches exactly what
`wizard/grid_zero.py`'s own Siguiente handler writes, and what
`proposals/generator.py:build_from_wizard_blob()` already reads):
    {"item", "item_en", "qty" (float|None), "unit_cost" (float),
     "total" (float, always derived — never independently edited),
     "iva_pct" (0.0|0.13), "specs", "specs_en"}

Do-not-drop items carried from PLAN §1.10 (cited by number at each site
below): 23 (interconnection-permit USD override from Step 5), 24 (service
defaults filtered by `system_types`), 25 (`Refrescar precios` touching only
`unit_cost`).
"""
from __future__ import annotations

_IVA_OPTIONS = ["0%", "13%"]

# Fallback service list used when service_defaults table is unavailable —
# verbatim copy of wizard/grid_zero.py's _FALLBACK_SERVICES.
_FALLBACK_SERVICES: list[dict] = [
    {"item": "Permiso de Interconexión", "item_en": "Interconnection Permit",
     "unit_cost_usd": 1000.0, "iva_pct": 0.0,
     "specs": "Requerido por el Reglamento de Generación Distribuida",
     "specs_en": "Required by the Distributed Generation Regulation", "enabled": True},
    {"item": "Diseño Eléctrico y Administración", "item_en": "Electrical Design & Management",
     "unit_cost_usd": 0.0, "iva_pct": 0.13,
     "specs": "Estudios preliminares, diseño eléctrico, inspección del sitio y gestión",
     "specs_en": "Preliminary studies, electrical design, site inspection and management", "enabled": True},
    {"item": "Mano de obra", "item_en": "Labor",
     "unit_cost_usd": 0.0, "iva_pct": 0.13,
     "specs": "Instalación y costos relacionados con la obra",
     "specs_en": "Installation and costs related to the project", "enabled": True},
    {"item": "Materiales eléctricos", "item_en": "Electrical materials",
     "unit_cost_usd": 0.0, "iva_pct": 0.13,
     "specs": "Materiales eléctricos y montaje solar",
     "specs_en": "Electrical materials and solar mounting", "enabled": True},
    {"item": "Transporte de equipo", "item_en": "Equipment transport",
     "unit_cost_usd": 0.0, "iva_pct": 0.13,
     "specs": "Transporte e instalación de equipo en sitio",
     "specs_en": "Equipment transport and on-site delivery", "enabled": True},
]

_LINE_FIELDS = ["item", "item_en", "qty", "unit_cost", "iva", "specs"]


def _iva_str(pct: float) -> str:
    return "13%" if float(pct or 0) >= 0.1 else "0%"


def _iva_float(s: str) -> float:
    return 0.13 if "13" in str(s or "") else 0.0


def _row_subtotal(qty, unit_cost) -> float:
    """qty is None (blank) => treat as 1 — verbatim port of
    step7_costs()'s own `_row_subtotal()`."""
    try:
        q = 1.0 if qty in (None, "") else float(qty)
    except (TypeError, ValueError):
        q = 1.0
    return round(q * float(unit_cost or 0), 2)


# ── catalog / pricing helpers (do-not-drop items 23, 24) ────────────────


def _load_service_defaults() -> list[dict]:
    """Return enabled, Grid-Zero-applicable service defaults from DB; fall
    back to `_FALLBACK_SERVICES`. Do-not-drop item 24 — this is what
    excludes the interconnection permit from a true Off-Grid quote (that
    filter lives here, unconditionally, so a future Off-Grid step 7 reusing
    this same helper inherits it for free)."""
    try:
        from database.equipment_db import list_service_defaults

        rows = list_service_defaults()
        if rows:
            return [
                r for r in rows
                if r.get("enabled", True)
                and (not r.get("system_types") or "grid_zero" in r["system_types"])
            ]
    except Exception:
        pass
    return _FALLBACK_SERVICES


def _get_current_prices(panel: dict, inverter: dict, monitoring: dict | None) -> dict[str, float]:
    """Fetch live prices from DB for equipment + service defaults. Falls
    back to the blob's own (possibly stale) cost_usd if the DB call fails —
    verbatim port of step7_costs()'s own `_get_current_prices()`."""
    prices: dict[str, float] = {}
    try:
        from database.equipment_db import get_inverter, get_panel

        if panel and panel.get("id"):
            fresh = get_panel(panel["id"])
            prices["Paneles solares"] = round(float((fresh or panel).get("cost_usd") or 0), 2)
        elif panel:
            prices["Paneles solares"] = round(float(panel.get("cost_usd") or 0), 2)
        if inverter and inverter.get("id"):
            fresh = get_inverter(inverter["id"])
            prices["Inversores"] = round(float((fresh or inverter).get("cost_usd") or 0), 2)
        elif inverter:
            prices["Inversores"] = round(float(inverter.get("cost_usd") or 0), 2)
    except Exception:
        if panel:
            prices["Paneles solares"] = round(float(panel.get("cost_usd") or 0), 2)
        if inverter:
            prices["Inversores"] = round(float(inverter.get("cost_usd") or 0), 2)
    if monitoring:
        try:
            from database.supabase_client import get_client

            r = (get_client().table("monitoring_devices")
                 .select("cost_usd").eq("id", monitoring["id"]).single().execute())
            prices["Sistema de monitoreo remoto"] = round(float((r.data or {}).get("cost_usd") or 0), 2)
        except Exception:
            prices["Sistema de monitoreo remoto"] = round(float(monitoring.get("cost_usd") or 0), 2)
    for svc in _load_service_defaults():
        prices[svc["item"]] = round(float(svc.get("unit_cost_usd") or 0), 2)
    return prices


def _refresh_prices_core(
    line_items: list[dict], panel: dict, inverter: dict, monitoring: dict | None,
) -> tuple[list[dict], int]:
    """(updated_line_items, n_changed) — do-not-drop item 25: ONLY
    `unit_cost` is touched here; qty, iva_pct, specs and custom (non-
    catalog) rows are returned untouched. Verbatim port of step7_costs()'s
    own `_refresh_prices()`."""
    price_map = _get_current_prices(panel, inverter, monitoring)
    updated, changes = [], 0
    for li in line_items:
        new_li = dict(li)
        if li.get("item") in price_map:
            new_price = price_map[li["item"]]
            if abs(new_price - float(li.get("unit_cost") or 0)) > 0.001:
                new_li["unit_cost"] = new_price
                changes += 1
        updated.append(new_li)
    return updated, changes


def _seed_line_items(blob: dict) -> list[dict]:
    """Default line items built from the selected equipment + service
    defaults, with live catalog prices — verbatim port of step7_costs()'s
    own "else" branch (first-ever visit to this step, before any edit has
    been persisted). Never persisted by this function itself; the caller
    decides whether/when to write it back (matches gz_s5/gz_s6's own
    "compute a default for display, only persist on an actual action" rule)."""
    equipment = blob.get("equipment") or {}
    consumption = blob.get("consumption") or {}
    panel = equipment.get("panel") or {}
    inverter = equipment.get("inverter") or {}
    monitoring = equipment.get("monitoring")
    chosen = equipment.get("chosen_scenario") or {}
    panel_count = chosen.get("total_panels", 0)

    live_prices = _get_current_prices(panel, inverter, monitoring)
    items: list[dict] = []

    if panel:
        items.append({
            "item": "Paneles solares", "item_en": "Solar panels",
            "qty": panel_count,
            "unit_cost": live_prices.get("Paneles solares", 0.0),
            "iva_pct": 0.0,
            "specs": f"{panel.get('brand','')} {panel.get('model','')} {panel.get('wp','')}W".strip(),
            "specs_en": f"{panel.get('brand','')} {panel.get('model','')} {panel.get('wp','')}W".strip(),
        })
    if inverter:
        items.append({
            "item": "Inversores", "item_en": "Inverters",
            "qty": 1,
            "unit_cost": live_prices.get("Inversores", 0.0),
            "iva_pct": 0.0,
            "specs": f"{inverter.get('brand','')} {inverter.get('model','')}".strip(),
            "specs_en": f"{inverter.get('brand','')} {inverter.get('model','')}".strip(),
        })

    for svc in _load_service_defaults():
        item_name = svc["item"]
        row: dict = {
            "item":      item_name,
            "item_en":   svc.get("item_en", item_name),
            "qty":       None,
            "unit_cost": live_prices.get(item_name, float(svc.get("unit_cost_usd") or 0)),
            "iva_pct":   float(svc.get("iva_pct") or 0),
            "specs":     svc.get("specs", ""),
            "specs_en":  svc.get("specs_en", svc.get("specs", "")),
        }
        # Do-not-drop item 23: the interconnection-permit USD captured back
        # in Step 5 (Consumo) overrides this line item's unit cost here,
        # exactly as wizard/grid_zero.py's step7_costs() does.
        if row["item"] == "Permiso de Interconexión":
            row["unit_cost"] = float(consumption.get("interconnection_permit_usd") or row["unit_cost"])
        items.append(row)

    if monitoring:
        items.append({
            "item": "Sistema de monitoreo remoto", "item_en": "Remote monitoring system",
            "qty": 1,
            "unit_cost": live_prices.get("Sistema de monitoreo remoto", 0.0),
            "iva_pct": 0.0,
            "specs": f"{monitoring.get('brand','')} {monitoring.get('model','')}".strip(),
            "specs_en": f"{monitoring.get('brand','')} {monitoring.get('model','')}".strip(),
        })

    for it in items:
        it["total"] = _row_subtotal(it.get("qty"), it.get("unit_cost"))
    return items


# ── totals ────────────────────────────────────────────────────────────


def _finalize(blob: dict, items: list[dict]) -> dict:
    """Recompute qty/unit_cost -> per-row total -> subtotal/IVA/TOTAL/$-per-
    Wp from `items` — the one place every action + `build_context()` derives
    the footer from, so they can never disagree (PLAN §1.3)."""
    equipment = blob.get("equipment") or {}
    panel = equipment.get("panel") or {}
    chosen = equipment.get("chosen_scenario") or {}
    panel_count = chosen.get("total_panels", 0)
    panel_wp = float(panel.get("wp") or 0)

    finalized = []
    subtotal = 0.0
    iva_amount = 0.0
    for it in items:
        unit_cost = float(it.get("unit_cost") or 0)
        iva_pct = float(it.get("iva_pct") or 0)
        line_total = _row_subtotal(it.get("qty"), unit_cost)
        subtotal += line_total
        iva_amount += round(line_total * iva_pct, 2)
        finalized.append({**it, "unit_cost": unit_cost, "iva_pct": iva_pct, "total": line_total})

    subtotal = round(subtotal, 2)
    iva_amount = round(iva_amount, 2)
    total = round(subtotal + iva_amount, 2)
    panel_wp_total = panel_count * panel_wp
    cost_per_wp = round(total / panel_wp_total, 3) if panel_wp_total else 0.0

    return {
        "line_items": finalized,
        "subtotal_usd": subtotal,
        "iva_usd": iva_amount,
        "total_usd": total,
        "cost_per_wp": cost_per_wp,
    }


def _items_from_form(blob: dict, form) -> list[dict]:
    """The inverse of the `r-<i>-<field>` table — PLAN §1.5's `st.data_editor`
    replacement applied to the cost line items. `specs_en` is not an editable
    column (mirrors the Streamlit editor, which only exposes ES description +
    EN description + qty + unit cost + IVA + ES specs): it is carried over
    from whatever the matching row (by ES description) already had, falling
    back to the freshly-typed ES specs text for a brand-new custom row —
    verbatim port of step7_costs()'s own `original_lookup` logic."""
    from webapp.wizard_steps.common import parse_rows, to_float

    original = blob.get("costs", {}).get("line_items") or _seed_line_items(blob)
    original_lookup = {r.get("item"): r for r in original}

    rows = parse_rows(form, "r", _LINE_FIELDS)
    items = []
    for row in rows:
        desc_es = row.get("item") or ""
        orig = original_lookup.get(desc_es, {})
        items.append({
            "item": desc_es,
            "item_en": row.get("item_en") or desc_es,
            "qty": to_float(row.get("qty")),
            "unit_cost": to_float(row.get("unit_cost"), 0.0) or 0.0,
            "iva_pct": _iva_float(row.get("iva")),
            "specs": row.get("specs") or "",
            "specs_en": orig.get("specs_en", row.get("specs") or ""),
        })
    return items


# ── actions ──────────────────────────────────────────────────────────


def recompute_table(blob: dict, form) -> dict:
    """`paso/7/tabla`'s core logic — PLAN §1.5's live-recompute pattern."""
    return _finalize(blob, _items_from_form(blob, form))


def add_line_row(blob: dict, form) -> dict:
    items = _items_from_form(blob, form)
    items.append({
        "item": "", "item_en": "", "qty": None, "unit_cost": 0.0,
        "iva_pct": 0.0, "specs": "", "specs_en": "",
    })
    return _finalize(blob, items)


def remove_line_row(blob: dict, form) -> dict:
    items = _items_from_form(blob, form)
    idx = int(form.get("_row", -1) or -1)
    if 0 <= idx < len(items):
        items.pop(idx)
    return _finalize(blob, items)


def refresh_prices(blob: dict) -> tuple[dict, int]:
    """`paso/7/refrescar`'s core logic. Returns (new_costs, n_changed) — the
    caller surfaces `n_changed` in the fragment (do-not-drop item 25's
    "reports how many rows changed" requirement)."""
    equipment = blob.get("equipment") or {}
    panel = equipment.get("panel") or {}
    inverter = equipment.get("inverter") or {}
    monitoring = equipment.get("monitoring")
    current = blob.get("costs", {}).get("line_items") or _seed_line_items(blob)
    updated, n_changed = _refresh_prices_core(current, panel, inverter, monitoring)
    return _finalize(blob, updated), n_changed


def save_step(blob: dict, form) -> dict:
    """`Siguiente`/`Atrás`'s persisted fields — re-parses the submitted form
    at click time (same "whatever is on screen is what gets saved" rule
    gz_s5_consumption.save_step() documents), so a cell edited but not yet
    round-tripped through the change-triggered recompute is not lost."""
    return _finalize(blob, _items_from_form(blob, form))


# ── build_context ────────────────────────────────────────────────────


def build_context(blob: dict) -> dict:
    blob = blob or {}
    items = blob.get("costs", {}).get("line_items") or _seed_line_items(blob)
    finalized = _finalize(blob, items)

    rows = [
        {**it, "iva_display": _iva_str(it.get("iva_pct", 0))}
        for it in finalized["line_items"]
    ]

    return {
        "rows": rows,
        "iva_options": _IVA_OPTIONS,
        "subtotal_usd": finalized["subtotal_usd"],
        "iva_usd": finalized["iva_usd"],
        "total_usd": finalized["total_usd"],
        "cost_per_wp": finalized["cost_per_wp"],
        "refresh_message": None,
        "can_continue": finalized["total_usd"] > 0,
    }
