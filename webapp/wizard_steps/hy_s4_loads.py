"""Hybrid Step 4 — Cargas eléctricas y perfil de consumo general. Port of
wizard/hybrid.py:step4_loads().

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls.

Reuses, verbatim (per og_s4_loads.py's own docstring — it was built in Step 7
specifically so this step could call it a second time):
  - `og_s4_loads.save_step()`/`build_context()`/`add_catalog_rows()`/
    `extract_tablero()`/`extract_text()`/`update_table()`/`add_row()`/
    `remove_row()` for the CRITICAL (backup) loads block, scratch key
    `og_s4_loads.DEFAULT_SCRATCH_KEY` ("s4og") — verified against
    wizard/hybrid.py's own `off_grid._render_loads_block("w4og", current)`
    call, the SAME "w4og" widget-key family Off-Grid's own Step 4 uses.
  - The SAME functions again for the MAIN PANEL's independent loads
    instance (wizard/hybrid.py's "w4h_mp"), scratch key "mp" — PLAN §1.1's
    own example scratch shape names it exactly that
    (`"mp": {"loads_data": [...], "hourly_shape": {...}}`).
  - `gz_s4_utility.py`'s DB lookups/defaulting (`_utility_for()`,
    `_distributors()`, `_tariff_types()`, `select_distributor()`,
    `FIXED_CHARGE_DISCLAIMER`) for the distributor/tariff block — verified
    against wizard/hybrid.py's own `_render_utility_block()`: same fields
    (distributor id/name/abbrev, tariff id/code/name, access_charge_crc,
    bomberos_pct, iva_threshold_kwh), same fixed-charge disclaimer text.
    Two differences kept deliberately, not silently "fixed" to match
    gz_s4_utility.py: (a) Hybrid's utility dict has no NISE field — this
    step never renders or persists one; (b) the real Streamlit source
    embeds `"tiers": get_tariff_tiers(...)` directly into the saved dict,
    but this port follows the convention gz_s5_consumption.py's own
    `_tariff_info()` already established for Grid Zero — tiers are fetched
    fresh, on demand, wherever a tariff computation actually needs them,
    never cached in the persisted `utility` dict. See `_mp_bill_context()`.

GENUINE KEY FINDING vs. the build plan's summary of og_s4_loads.py's own
parameterization (reported, not silently patched around): the plan's own
scratch-key parameterization is NOT sufficient by itself for a second
independent loads table on the SAME page. `og_s4_loads.py`'s `update_table`/
`add_row`/`remove_row` (and the Step 4 Siguiente <form> that wraps both
tables at once) hard-coded the `<prefix>-N-<field>` form-field NAME to the
literal string "row" — reusing the critical table's own fragment for the
main panel verbatim would make both tables' inputs share the name
"row-0-desc" etc., which collide the instant Step 4's one wrapping <form>
is submitted (Siguiente). Fixed additively: `og_s4_loads.py`'s three
table-mutation functions now take an optional `row_prefix` (default "row",
so Off-Grid's own callers are unaffected); this step's main-panel instance
uses `row_prefix="mp_row"` (see MP_ROW_PREFIX below) everywhere it touches
that table.

`consumption.utility` (Hybrid-only; separate from the durable top-level
`utility` section Grid Zero owns — see the docstring note in
og_s6_equipment.py's `_compute()` for why that distinction matters) and
`consumption.main_panel` (`{"mode": "bill", "avg_kwh_month": ...}` or
`{"mode": "loads", "loads_display": ..., "loads": ..., "profile": ...,
"avg_kwh_month": ...}`) are Hybrid-only additions to the `consumption`
section — verbatim shape of wizard/hybrid.py's own
`_build_consumption_result()`.

Do-not-drop items carried from PLAN §1.10 (cited by number at each site
below): 1 (classify_load_category() at import time, inherited unchanged
from og_s4_loads.py for BOTH loads tables), 19 (grid_connected checkbox,
utility block, panel_scope primary/secondary, main-panel block in both
bill and loads modes).
"""
from __future__ import annotations

from webapp.wizard_steps import gz_s4_utility, og_s4_loads
from webapp.wizard_steps.og_s4_loads import _loads_to_taxonomy_list, _rows_to_display

# Hybrid's critical (backup) loads reuse Off-Grid's own default scratch key
# verbatim — wizard/hybrid.py calls off_grid._render_loads_block("w4og", ...),
# the SAME widget-key family Off-Grid's own Step 4 uses.
CRITICAL_SCRATCH_KEY = og_s4_loads.DEFAULT_SCRATCH_KEY  # "s4og"
# PLAN §1.1's own example scratch shape names this "mp" verbatim.
MP_SCRATCH_KEY = "mp"
MP_ROW_PREFIX = "mp_row"

_PANEL_SCOPE_LABELS = {
    "primary": "Tablero principal — estas cargas representan el consumo total del sitio",
    "secondary": "Tablero secundario (respaldo) — hay un tablero principal aparte con cargas adicionales",
}
_MAIN_PANEL_MODE_LABELS = {"bill": "Factura eléctrica", "loads": "Lista de cargas"}


# ── main-panel loads-table shim (do-not-drop item 19's "second, genuinely
# independent loads table") ───────────────────────────────────────────────


def _mp_blob(blob: dict) -> dict:
    """og_s4_loads.py's build_context()/_current_loads_display() fall back to
    `consumption.loads_display` when scratch is empty (a draft resumed after
    a prior Siguiente click) — that fallback field is the CRITICAL loads'
    own. Shim a blob whose `consumption.loads_display` points at the
    persisted `consumption.main_panel.loads_display` instead, so the main
    panel's independent instance falls back to ITS OWN prior data, never the
    critical table's — with zero changes to og_s4_loads.py's read path."""
    consumption = blob.get("consumption") or {}
    main_panel = consumption.get("main_panel") or {}
    return {**blob, "consumption": {**consumption, "loads_display": main_panel.get("loads_display") or []}}


def mp_add_catalog_rows(blob: dict, picks: list[str]) -> dict:
    return og_s4_loads.add_catalog_rows(_mp_blob(blob), MP_SCRATCH_KEY, picks)


def mp_extract_tablero(blob: dict, file_bytes: bytes, media_type: str) -> dict:
    return og_s4_loads.extract_tablero(_mp_blob(blob), MP_SCRATCH_KEY, file_bytes, media_type)


def mp_extract_text(blob: dict, text: str) -> dict:
    return og_s4_loads.extract_text(_mp_blob(blob), MP_SCRATCH_KEY, text)


def mp_update_table(blob: dict, form) -> dict:
    return og_s4_loads.update_table(_mp_blob(blob), MP_SCRATCH_KEY, form, row_prefix=MP_ROW_PREFIX)


def mp_add_row(blob: dict, form) -> dict:
    return og_s4_loads.add_row(_mp_blob(blob), MP_SCRATCH_KEY, form, row_prefix=MP_ROW_PREFIX)


def mp_remove_row(blob: dict, form) -> dict:
    return og_s4_loads.remove_row(_mp_blob(blob), MP_SCRATCH_KEY, form, row_prefix=MP_ROW_PREFIX)


def mp_loads_context(blob: dict) -> dict:
    return og_s4_loads.build_context(_mp_blob(blob), MP_SCRATCH_KEY)


# ── utility (distributor/tariff) block — reuses gz_s4_utility.py directly,
# shimmed onto consumption.utility instead of the durable top-level section
# Grid Zero owns ──────────────────────────────────────────────────────────


def _utility_blob(blob: dict) -> dict:
    consumption = blob.get("consumption") or {}
    return {**blob, "utility": consumption.get("utility") or {}}


def select_distributor(distributor_id: str | None) -> dict:
    return gz_s4_utility.select_distributor(distributor_id)


def utility_context(blob: dict) -> dict:
    return gz_s4_utility.build_context(_utility_blob(blob))


# ── main-panel "bill" mode ────────────────────────────────────────────────


def mp_bill_context(blob: dict) -> dict:
    consumption = blob.get("consumption") or {}
    main_panel = consumption.get("main_panel") or {}
    utility = consumption.get("utility") or {}
    avg_kwh_month = float(main_panel.get("avg_kwh_month") or 0.0)

    current_bill_crc = None
    if utility.get("tariff_type_id") and avg_kwh_month > 0:
        from webapp.wizard_steps.gz_s5_consumption import _tariff_info

        tariff_info = _tariff_info(utility)
        if tariff_info:
            from calculations.tariff_calculator import estimate_bill_crc

            current_bill_crc = estimate_bill_crc(avg_kwh_month, tariff_info)

    return {"avg_kwh_month": avg_kwh_month, "current_bill_crc": current_bill_crc}


# ── Siguiente/Atrás ──────────────────────────────────────────────────────


def save_step(form) -> dict:
    """Verbatim port of wizard/hybrid.py:step4_loads()'s own
    `_build_consumption_result()`. `og_s4_loads.save_step(form)` (row prefix
    "row") supplies the critical loads/autonomy/voltage fields unchanged.

    `panel_scope` is the one field that must be OMITTED (not defaulted to
    "primary") when its radio wasn't rendered this click (grid_connected
    False) — wizard/draft.py:patch()'s shallow per-section merge means an
    omitted key here leaves the previously-persisted value untouched,
    matching Streamlit's own `panel_scope = current.get("panel_scope",
    "primary")` fallback-to-PRIOR-value (not to "primary" outright).
    `utility`/`main_panel`, by contrast, are ALWAYS explicitly recomputed
    (None when their `if` block didn't run) — verbatim to the Streamlit
    source, where both variables are declared None and only reassigned
    inside their own `if` block on every single rerun."""
    from webapp.wizard_steps.common import parse_rows, to_float

    critical = og_s4_loads.save_step(form)

    grid_connected = form.get("grid_connected") == "on"
    result: dict = {**critical, "grid_connected": grid_connected}

    posted_scope = (form.get("panel_scope") or "").strip()
    if posted_scope in _PANEL_SCOPE_LABELS:
        result["panel_scope"] = posted_scope
    panel_scope = result.get("panel_scope", posted_scope)

    utility = None
    main_panel = None
    if grid_connected:
        distributor_id = (form.get("distributor_id") or "").strip() or None
        tariff_type_id = (form.get("tariff_type_id") or "").strip() or None
        utility = gz_s4_utility._utility_for(distributor_id, tariff_type_id) or None

        if panel_scope == "secondary":
            mp_mode = (form.get("mp_mode") or "bill").strip()
            if mp_mode not in _MAIN_PANEL_MODE_LABELS:
                mp_mode = "bill"
            if mp_mode == "bill":
                avg_kwh_month = to_float(form.get("mp_avg_kwh_month"), 0.0) or 0.0
                main_panel = {"mode": "bill", "avg_kwh_month": float(avg_kwh_month)}
            else:
                rows = parse_rows(form, MP_ROW_PREFIX, og_s4_loads._ROW_FIELDS)
                mp_loads_display = _rows_to_display(rows)
                main_panel = {
                    "mode": "loads",
                    "loads_display": mp_loads_display,
                    "loads": _loads_to_taxonomy_list(mp_loads_display),
                    # profile/avg_kwh_month computed in Step 5 once
                    # build_load_profile() runs (_build_step5_result()).
                    "profile": None,
                    "avg_kwh_month": None,
                }

    result["utility"] = utility
    result["main_panel"] = main_panel
    return result


# ── build_context ────────────────────────────────────────────────────────


def build_context(blob: dict) -> dict:
    blob = blob or {}
    consumption = blob.get("consumption") or {}

    critical = og_s4_loads.build_context(blob)  # scratch_key defaults to "s4og"

    grid_connected = consumption.get("grid_connected", True)
    panel_scope = consumption.get("panel_scope") or "primary"
    main_panel = consumption.get("main_panel") or {}
    mp_mode = main_panel.get("mode") or "bill"
    show_main_panel = bool(grid_connected and panel_scope == "secondary")

    utility_ctx = utility_context(blob) if grid_connected else None

    mp_ctx = None
    mp_bill_ctx = None
    if show_main_panel:
        if mp_mode == "loads":
            mp_ctx = mp_loads_context(blob)
        else:
            mp_bill_ctx = mp_bill_context(blob)

    return {
        **critical,
        "grid_connected": grid_connected,
        "panel_scope": panel_scope,
        "panel_scope_labels": _PANEL_SCOPE_LABELS,
        "mp_mode": mp_mode,
        "mp_mode_labels": _MAIN_PANEL_MODE_LABELS,
        "show_main_panel": show_main_panel,
        "utility": utility_ctx,
        "mp": mp_ctx,
        "mp_bill": mp_bill_ctx,
        "can_continue": critical["can_continue"],
    }
