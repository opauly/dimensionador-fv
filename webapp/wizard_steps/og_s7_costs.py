"""Off-Grid Step 7 — Detalles de costos. Port of
wizard/off_grid.py:step7_costs().

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls. Same "no scratch namespace of its
own" shape as `gz_s7_costs.py` (see that module's docstring) — `costs` is
already one of the seven durable blob sections, and every action here (row
edit, +Fila, quitar fila, Refrescar precios) writes its result straight into
`blob["costs"]` via `draft.patch(vid, "costs", ...)` in the blueprint.

Line item shape stored in `costs.line_items` — identical to Grid Zero's
(matches what `proposals/generator.py:build_from_wizard_blob()` already
reads):
    {"item", "item_en", "qty" (float|None), "unit_cost" (float),
     "total" (float, always derived — never independently edited),
     "iva_pct" (0.0|0.13), "specs", "specs_en"}

**Critical (flagged in the build task, do-not-drop item 17):** the inverter
line's `qty` is seeded from `equipment.inverter_qty` — the value Step 6
(`og_s6_equipment.save_step()`) already resolved, which accounts for BOTH
the split-phase doubling (240V master/slave) AND Scenario 3's
inverter-headroom doubling (`generate_reliability_scenarios()`'s
`inverter_growth_added`). This step must never re-derive that count from
`split_phase` alone the way `wizard/off_grid.py`'s own step7_costs() falls
back to for pre-Step-6-inverter_qty drafts (`inverter_qty = equipment.get(
"inverter_qty") or (2 if split_phase.get("requires_split_phase") else 1)`)
— every Off-Grid draft built through THIS port always has `inverter_qty`
already persisted by og_s6_equipment.py, so the fallback exists here only
for symmetry with the Streamlit source's own defensive coding, never for a
new draft actually hitting it.

KEY FINDING vs. the actual Streamlit source (reported, not silently
"fixed"): `wizard/off_grid.py`'s own `step7_costs()` has **no** "Refrescar
precios" button and does **no** live catalog-price re-fetch at all — its
initial seed reads `unit_cost` straight off the persisted `equipment.*`
dicts' own `cost_usd` (whatever price was live back when Step 6 loaded the
catalog), and that is the ONLY place a price ever comes from in the actual
Off-Grid Streamlit wizard. This module still builds the live-price
fetch/refresh mechanism identical to Grid Zero's (do-not-drop item 25 is
written generically, not "Grid Zero only", and the build task explicitly
asks for it/validates it) — a deliberate, disclosed parity feature, not a
port of something that already existed on this screen in `main`.

Do-not-drop items carried from PLAN §1.10 (cited by number at each site
below): 17 (inverter_qty read directly, never re-derived), 18
(`_MAX_CHARGE_CONTROLLERS = 4`), 24 (service defaults filtered by
`system_types` — excludes the interconnection permit from a true Off-Grid
quote), 25 (`Refrescar precios` touching only `unit_cost`).
"""
from __future__ import annotations

from webapp.wizard_steps.gz_s7_costs import (
    _IVA_OPTIONS,
    _iva_float,
    _iva_str,
    _margin_from_form,
    _row_subtotal,
    _shown_price,
    _suggested_margin_pct,
)

_LINE_FIELDS = ["item", "item_en", "qty", "unit_cost", "iva", "specs"]

# `_MAX_CHARGE_CONTROLLERS` (do-not-drop item 18) has no bearing on THIS
# step's own logic (it only ever caps how many controllers Step 6 lets an
# engineer parallel) — cited here only because §1.10 item 18 is listed for
# this build task; the actual cap lives in `og_s6_equipment.py` and
# `calculations/sizing_off_grid.py`, and `charge_controller_qty` arrives here
# already resolved.

# Fallback service list used when service_defaults table is unavailable —
# same shape as gz_s7_costs.py's own `_FALLBACK_SERVICES`, minus the
# interconnection permit (do-not-drop item 24's fallback-path analogue: a
# true Off-Grid system has no utility connection to interconnect, so this
# fallback must never carry that line either).
_FALLBACK_SERVICES: list[dict] = [
    {"item": "Diseño y gestión", "item_en": "Design & management",
     "unit_cost_usd": 0.0, "iva_pct": 0.13,
     "specs": "Estudios preliminares y gestión del proyecto",
     "specs_en": "Preliminary studies and project management", "enabled": True},
    {"item": "Mano de obra", "item_en": "Labor",
     "unit_cost_usd": 0.0, "iva_pct": 0.13,
     "specs": "Instalación y costos relacionados con la obra",
     "specs_en": "Installation and related project costs", "enabled": True},
    {"item": "Materiales eléctricos", "item_en": "Electrical materials",
     "unit_cost_usd": 0.0, "iva_pct": 0.13,
     "specs": "Cableado, protecciones y BOS",
     "specs_en": "Wiring, protection devices and BOS", "enabled": True},
]


# ── catalog / pricing helpers (do-not-drop items 17, 18, 24, 25) ─────────


def _system_type(blob: dict) -> str:
    """The draft's actual system type ("off_grid" or "hybrid" — this module
    is never used for "grid_zero", see webapp/blueprints/wizard.py's step-7
    dispatch table), falling back to "off_grid" only for a draft saved
    before Step 2 (Tipo e idioma) ever wrote `meta.system_type`."""
    return (blob.get("meta") or {}).get("system_type") or "off_grid"


def _load_service_defaults(system_type: str = "off_grid") -> list[dict]:
    """Enabled service defaults applicable to `system_type`, from DB; falls
    back to `_FALLBACK_SERVICES`. Do-not-drop item 24 — this is the actual
    filter that excludes the interconnection permit from a true Off-Grid
    quote (its `system_types` row is `["grid_zero", "hybrid"]`, which does
    not contain `"off_grid"`).

    Bug fixed 2026-09-26 (found during Phase 23's review, unrelated to that
    phase's own change): this always checked the literal string
    `"off_grid"` regardless of which system type the draft actually was —
    since this module also serves Hybrid quotes (`webapp/blueprints/
    wizard.py`'s step-7 dispatch maps both `"off_grid"` and `"hybrid"` to
    `og_s7_costs`), a real Hybrid quote was filtered as if it were Off-Grid,
    silently dropping "Permiso de Interconexión" even though its
    `system_types` explicitly includes `"hybrid"`. Every caller now passes
    the draft's real system type via `_system_type(blob)`."""
    try:
        from database.equipment_db import list_service_defaults

        rows = list_service_defaults()
        if rows:
            return [
                r for r in rows
                if r.get("enabled", True)
                and (not r.get("system_types") or system_type in r["system_types"])
            ]
    except Exception:
        pass
    return _FALLBACK_SERVICES


def _get_current_prices(
    panel: dict, inverter: dict, battery: dict, cc: dict, monitoring: dict | None,
    system_type: str = "off_grid",
) -> dict[str, float]:
    """Fetch live prices from DB for equipment + service defaults, falling
    back to each dict's own (possibly stale) `cost_usd` if the DB call
    fails — Off-Grid analogue of `gz_s7_costs.py`'s own helper, extended
    with battery + charge controller (see this module's own "KEY FINDING"
    docstring note for why this mechanism exists at all here)."""
    prices: dict[str, float] = {}
    try:
        from database.equipment_db import get_battery, get_charge_controller, get_inverter, get_panel

        if panel and panel.get("id"):
            fresh = get_panel(panel["id"])
            prices["Paneles solares"] = round(float((fresh or panel).get("cost_usd") or 0), 2)
        elif panel:
            prices["Paneles solares"] = round(float(panel.get("cost_usd") or 0), 2)
        if inverter and inverter.get("id"):
            fresh = get_inverter(inverter["id"])
            prices["Inversor/cargador"] = round(float((fresh or inverter).get("cost_usd") or 0), 2)
        elif inverter:
            prices["Inversor/cargador"] = round(float(inverter.get("cost_usd") or 0), 2)
        if battery and battery.get("id"):
            fresh = get_battery(battery["id"])
            prices["Baterías"] = round(float((fresh or battery).get("cost_usd") or 0), 2)
        elif battery:
            prices["Baterías"] = round(float(battery.get("cost_usd") or 0), 2)
        if cc and cc.get("id"):
            fresh = get_charge_controller(cc["id"])
            prices["Controlador de carga"] = round(float((fresh or cc).get("cost_usd") or 0), 2)
        elif cc:
            prices["Controlador de carga"] = round(float(cc.get("cost_usd") or 0), 2)
    except Exception:
        for label, item in (
            ("Paneles solares", panel), ("Inversor/cargador", inverter),
            ("Baterías", battery), ("Controlador de carga", cc),
        ):
            if item:
                prices[label] = round(float(item.get("cost_usd") or 0), 2)
    if monitoring:
        try:
            from database.supabase_client import get_client

            r = (get_client().table("monitoring_devices")
                 .select("cost_usd").eq("id", monitoring["id"]).single().execute())
            prices["Monitoreo"] = round(float((r.data or {}).get("cost_usd") or 0), 2)
        except Exception:
            prices["Monitoreo"] = round(float(monitoring.get("cost_usd") or 0), 2)
    for svc in _load_service_defaults(system_type):
        prices[svc["item"]] = round(float(svc.get("unit_cost_usd") or 0), 2)
    return prices


def _refresh_prices_core(
    line_items: list[dict], panel: dict, inverter: dict, battery: dict, cc: dict, monitoring: dict | None,
    system_type: str = "off_grid",
) -> tuple[list[dict], int]:
    """(updated_line_items, n_changed) — do-not-drop item 25: ONLY
    `unit_cost` is touched; qty, iva_pct, specs and custom (non-catalog)
    rows are returned untouched."""
    price_map = _get_current_prices(panel, inverter, battery, cc, monitoring, system_type)
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
    defaults, with live catalog prices — verbatim port of
    `wizard/off_grid.py:step7_costs()`'s own "else" branch (first-ever visit
    to this step), except unit costs come from `_get_current_prices()`
    rather than the equipment dict's own possibly-stale `cost_usd` (this
    module's disclosed "KEY FINDING" parity feature, see module docstring).
    Never persisted by this function itself."""
    equipment = blob.get("equipment") or {}
    panel = equipment.get("panel") or {}
    inverter = equipment.get("inverter") or {}
    battery = equipment.get("battery") or {}
    cc = equipment.get("charge_controller") or {}
    monitoring = equipment.get("monitoring")
    split_phase = equipment.get("split_phase") or {}

    panel_count = equipment.get("panel_count", 0)
    cc_qty = equipment.get("charge_controller_qty", 1)
    battery_count = (equipment.get("battery_bank") or {}).get("battery_count", 0)
    # Do-not-drop item 17: read Step 6's own resolved inverter_qty directly
    # — never re-derive it. The `or (...)` fallback only matters for a draft
    # saved before og_s6_equipment.py started writing inverter_qty (mirrors
    # wizard/off_grid.py's own defensive fallback verbatim); it is not a
    # second source of truth this step invents.
    inverter_qty = equipment.get("inverter_qty") or (2 if split_phase.get("requires_split_phase") else 1)
    system_type = _system_type(blob)

    live_prices = _get_current_prices(panel, inverter, battery, cc, monitoring, system_type)
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
            "item": "Inversor/cargador", "item_en": "Inverter/charger",
            "qty": inverter_qty,
            "unit_cost": live_prices.get("Inversor/cargador", 0.0),
            "iva_pct": 0.0,
            "specs": f"{inverter.get('brand','')} {inverter.get('model','')}".strip(),
            "specs_en": f"{inverter.get('brand','')} {inverter.get('model','')}".strip(),
        })
    if battery:
        items.append({
            "item": "Baterías", "item_en": "Batteries",
            "qty": battery_count,
            "unit_cost": live_prices.get("Baterías", 0.0),
            "iva_pct": 0.0,
            "specs": f"{battery.get('brand','')} {battery.get('model','')} {battery.get('capacity_kwh','')}kWh".strip(),
            "specs_en": f"{battery.get('brand','')} {battery.get('model','')} {battery.get('capacity_kwh','')}kWh".strip(),
        })
    if cc:
        items.append({
            "item": "Controlador de carga", "item_en": "Charge controller",
            "qty": cc_qty,
            "unit_cost": live_prices.get("Controlador de carga", 0.0),
            "iva_pct": 0.0,
            "specs": f"{cc.get('brand','')} {cc.get('model','')}".strip(),
            "specs_en": f"{cc.get('brand','')} {cc.get('model','')}".strip(),
        })
    if monitoring:
        items.append({
            "item": "Monitoreo", "item_en": "Monitoring",
            "qty": 1,
            "unit_cost": live_prices.get("Monitoreo", 0.0),
            "iva_pct": 0.0,
            "specs": f"{monitoring.get('brand','')} {monitoring.get('model','')}".strip(),
            "specs_en": f"{monitoring.get('brand','')} {monitoring.get('model','')}".strip(),
        })
    # Phase 23: "Estructura de montaje" used to be hardcoded here (Off-Grid/
    # Hybrid only). Migration 049 folded it into `service_defaults` for all
    # three system types (system_types=NULL), so the generic catalog loop
    # below now picks it up on its own — appending it a second time here
    # would show the line twice.

    for svc in _load_service_defaults(system_type):
        item_name = svc["item"]
        items.append({
            "item":      item_name,
            "item_en":   svc.get("item_en", item_name),
            "qty":       None,
            "unit_cost": live_prices.get(item_name, float(svc.get("unit_cost_usd") or 0)),
            "iva_pct":   float(svc.get("iva_pct") or 0),
            "specs":     svc.get("specs", ""),
            "specs_en":  svc.get("specs_en", svc.get("specs", "")),
        })

    for it in items:
        it["total"] = _row_subtotal(it.get("qty"), it.get("unit_cost"))
    return items


# ── totals ────────────────────────────────────────────────────────────


def _finalize(blob: dict, items: list[dict], margin_pct: float | None = None) -> dict:
    """Recompute qty/unit_cost -> per-row shown price -> total ->
    subtotal/IVA/TOTAL/$-per-Wp from `items` — the one place every action +
    `build_context()` derives the footer from (PLAN §1.3). Phase 23 change
    identical to `gz_s7_costs.py`'s own `_finalize()` — see that module's
    docstring for the full reasoning; not repeated here."""
    equipment = blob.get("equipment") or {}
    panel = equipment.get("panel") or {}
    panel_count = equipment.get("panel_count", 0)
    panel_wp = float(panel.get("wp") or 0)

    if margin_pct is None:
        margin_pct = float((blob.get("costs") or {}).get("margin_pct") or 0.0)

    eligible = {row["item"]: bool(row.get("markup_eligible", True))
                for row in _load_service_defaults(_system_type(blob))}

    finalized = []
    subtotal = 0.0
    iva_amount = 0.0
    for it in items:
        real_cost = float(it.get("unit_cost") or 0)
        item_name = it.get("item") or ""
        shown_price = _shown_price(real_cost, item_name, margin_pct, eligible)
        iva_pct = float(it.get("iva_pct") or 0)
        line_total = _row_subtotal(it.get("qty"), shown_price)
        subtotal += line_total
        iva_amount += round(line_total * iva_pct, 2)
        finalized.append({
            **it, "unit_cost": real_cost, "unit_price_shown": shown_price,
            "markup_eligible": eligible.get(item_name, True),
            "iva_pct": iva_pct, "total": line_total,
        })

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
        "margin_pct": margin_pct,
    }


def _items_from_form(blob: dict, form) -> list[dict]:
    """The inverse of the `r-<i>-<field>` table — identical rule to
    `gz_s7_costs.py`'s own `_items_from_form()` (`specs_en` carried over from
    the matching original row by ES description, not independently
    editable)."""
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
    return _finalize(blob, _items_from_form(blob, form), _margin_from_form(blob, form))


def add_line_row(blob: dict, form) -> dict:
    items = _items_from_form(blob, form)
    items.append({
        "item": "", "item_en": "", "qty": None, "unit_cost": 0.0,
        "iva_pct": 0.0, "specs": "", "specs_en": "",
    })
    return _finalize(blob, items, _margin_from_form(blob, form))


def remove_line_row(blob: dict, form) -> dict:
    items = _items_from_form(blob, form)
    idx = int(form.get("_row", -1) or -1)
    if 0 <= idx < len(items):
        items.pop(idx)
    return _finalize(blob, items, _margin_from_form(blob, form))


def refresh_prices(blob: dict) -> tuple[dict, int]:
    """`paso/7/refrescar`'s core logic. Returns (new_costs, n_changed). No
    form is submitted for this action, so `_finalize()` keeps whatever
    margin is already persisted on the blob."""
    equipment = blob.get("equipment") or {}
    panel = equipment.get("panel") or {}
    inverter = equipment.get("inverter") or {}
    battery = equipment.get("battery") or {}
    cc = equipment.get("charge_controller") or {}
    monitoring = equipment.get("monitoring")
    current = blob.get("costs", {}).get("line_items") or _seed_line_items(blob)
    updated, n_changed = _refresh_prices_core(current, panel, inverter, battery, cc, monitoring, _system_type(blob))
    return _finalize(blob, updated), n_changed


def save_step(blob: dict, form) -> dict:
    """`Siguiente`/`Atrás`'s persisted fields — re-parses the submitted form
    at click time, same rule as `gz_s7_costs.py:save_step()`."""
    return _finalize(blob, _items_from_form(blob, form), _margin_from_form(blob, form))


# ── build_context ────────────────────────────────────────────────────


def build_context(blob: dict) -> dict:
    blob = blob or {}
    items = blob.get("costs", {}).get("line_items") or _seed_line_items(blob)

    # Phase 23: see gz_s7_costs.py:build_context()'s own comment — identical
    # "never touched" rule, not repeated here.
    costs_section = blob.get("costs") or {}
    margin_suggestion = None
    margin_override = None
    if "margin_pct" not in costs_section:
        margin_suggestion = _suggested_margin_pct(blob)
        if margin_suggestion is not None:
            margin_override = margin_suggestion["margin_pct"]

    finalized = _finalize(blob, items, margin_override)

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
        "margin_pct": finalized["margin_pct"],
        "margin_suggestion": margin_suggestion,
        "refresh_message": None,
        "can_continue": finalized["total_usd"] > 0,
    }
