"""Off-Grid Step 5 — Perfil de demanda diaria. Port of
wizard/off_grid.py:step5_demand() + its `_render_demand_profile_block()`
helper.

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls.

`_render_demand_profile_block()` in the Streamlit source is parameterized by
`key_prefix` (Off-Grid critical loads "w5og" vs. a Hybrid main panel's own
instance, PLAN's Step 9) and by `diversified_used_downstream`/
`show_category_chart`/`show_hourly_chart` (off_grid.py's own Step 6 never
consumes the diversified figure — leave False; hybrid.py's does). This port
threads the same `scratch_key`/`diversified_used_downstream`/
`show_*_chart` arguments through `build_context()` so Step 9 can call it a
second time with different values without any rework here.

`scratch.<scratch_key>` shape (PLAN §1.1's model, filled in here):
    {"profile": {...build_load_profile() result...},
     "hourly_shape": {category: [24 floats]}}

Do-not-drop items carried from PLAN §1.10 (the single highest-risk piece of
this step, per the build plan's own warning):
  1. `default_demand_factor_pct()` fallback for lines saved before v3; the
     diversified total + its `diversified_used_downstream` caption switch;
     and — the part most likely to be ported wrong — the exact
     `user_confirmed`-vs-changed override rule in `recalculate()` below.
     Read that function's docstring before touching it.
  5. `_CONFIDENCE_BADGES` per line + the "N línea(s)... revísalas" warning.
"""
from __future__ import annotations

from calculations.load_profile_off_grid import CATEGORY_LABELS_ES, default_demand_factor_pct

_CONFIDENCE_BADGES = {
    "measured": ("📏 Medido", "#166534"),
    "api_calculated": ("🌐 API climática", "#1d4ed8"),
    "benchmark": ("📊 Tabla de referencia", "#6b7280"),
    "user_confirmed": ("✅ Confirmado por cliente", "#166534"),
    "default_assumed": ("⚠️ Estimado genérico", "#b45309"),
}

DEFAULT_SCRATCH_KEY = "s5og"


# ── scratch helpers ──────────────────────────────────────────────────────


def _scratch(blob: dict, scratch_key: str) -> dict:
    return (blob.get("scratch") or {}).get(scratch_key) or {}


def _site_latlon(blob: dict) -> tuple[float | None, float | None]:
    site = blob.get("site") or {}
    return site.get("lat"), site.get("lon")


def _table_rows(profile: dict, diversified_used_downstream: bool) -> list[dict]:
    """Verbatim port of `_render_demand_profile_block()`'s row-building loop
    (wizard/off_grid.py L384-405), including the do-not-drop item 1 fallback
    for lines saved before the v3 per-line rewrite (`.get()` with a computed
    default, not a bare key lookup that would KeyError on an old draft)."""
    rows = []
    for line in profile["lines"]:
        badge, color = _CONFIDENCE_BADGES.get(line["confidence"], (line["confidence"], "#6b7280"))
        factor = line.get("demand_factor_pct")
        if factor is None:
            factor = default_demand_factor_pct(line["category"])
        rows.append({
            "load_name": line["load_name"],
            "category": line["category"],
            "category_label": CATEGORY_LABELS_ES.get(line["category"], line["category"]),
            "quantity": line["quantity"],
            "duty_hours_day": line.get("duty_hours_day"),
            "kwh_day": line["estimated_kwh_day"],
            "factor_pct": round(factor * 100, 1),
            "energy_kwh_day": round(line["estimated_kwh_day"] * factor, 2),
            "badge": badge,
            "badge_color": color,
            "detail": line["source_detail"],
        })
    return rows


def _cat_totals(rows: list[dict]) -> dict:
    """Category key -> summed kWh/día, ascending by value — matches
    Streamlit's `edited.groupby("Categoría")["kWh/día"].sum().sort_values()`
    (smallest slice first in the donut/legend). Validation item 5 (donut
    total == table sum) holds by construction: both read `row["kwh_day"]`,
    never a second computation of the same figure."""
    totals: dict[str, float] = {}
    for r in rows:
        totals[r["category"]] = totals.get(r["category"], 0.0) + r["kwh_day"]
    return dict(sorted(totals.items(), key=lambda kv: kv[1]))


# ── Calcular / Recalcular ────────────────────────────────────────────────


def calculate(blob: dict, scratch_key: str) -> dict:
    """`POST paso/5/calcular` → build_load_profile() (§1.7). ALWAYS a fresh
    compute from the pristine `consumption.loads` — verbatim Streamlit
    behaviour: clicking "Calcular perfil de consumo" never carries forward
    a prior click's Horas/día or Factor demanda overrides (only "Recalcular
    con cambios" does, via `recalculate()` below). `hourly_shape` (a
    separate scratch key, independent of `profile`) is left untouched,
    matching Streamlit's own st.session_state — never cleared by this
    button either."""
    from calculations.load_profile_off_grid import build_load_profile

    consumption = blob.get("consumption") or {}
    loads = consumption.get("loads") or []
    lat, lon = _site_latlon(blob)
    profile = build_load_profile(loads, lat=lat, lon=lon)
    scratch = _scratch(blob, scratch_key)
    return {**scratch, "profile": profile}


def recalculate(blob: dict, scratch_key: str, form) -> dict:
    """`POST paso/5/recalcular` — verbatim port of the "Recalcular con
    cambios" button (wizard/off_grid.py L455-493).

    THE OVERRIDE RULE (PLAN §1.10 item 1 — getting this wrong produces two
    OPPOSITE bugs, both documented in the Streamlit source at that exact
    site):
      (a) flagging every untouched default row as "user_confirmed" on every
          click — hides real defaults from the "revísalas antes de
          continuar" warning, forever, even for lines nobody ever touched;
      (b) silently REVERTING an already-confirmed override back to the
          category default on a SECOND recalc click where that cell simply
          wasn't retyped again (its <input> still shows the same number,
          but that alone must not be read as "unchanged" vs "still
          confirmed" — those are different questions).

    Avoided the same way the Streamlit source does: a line counts as an
    engineer override if EITHER (i) the prior PROFILE already carries
    `confidence == "user_confirmed"` for that line (a previous recalc set
    it — keep it an override even if this click's number happens to match
    it exactly), OR (ii) the submitted value genuinely differs from that
    line's current default `duty_hours_day`. This is why `loads` is read
    FRESH from the pristine, never-mutated `consumption.loads` on every
    call (same as Streamlit's step5_demand() always passing
    `current.get("loads", [])` into the block on every rerun) while the
    PRIOR PROFILE (carried in scratch, not re-derived) is what actually
    makes the rule stateful across clicks — swapping which of these two
    is "fresh" vs "carried forward" is exactly how to introduce bug (a) or
    (b) above.
    """
    from calculations.load_profile_off_grid import build_load_profile
    from webapp.wizard_steps.common import parse_rows, to_float

    consumption = blob.get("consumption") or {}
    loads = consumption.get("loads") or []
    scratch = _scratch(blob, scratch_key)
    profile = scratch.get("profile")
    lat, lon = _site_latlon(blob)

    if not profile:
        return calculate(blob, scratch_key)

    rows = parse_rows(form, "line", ["hd", "fd"])
    updated_loads = []
    for i, (orig, line) in enumerate(zip(loads, profile["lines"])):
        row = rows[i] if i < len(rows) else {}

        new_hours = to_float(row.get("hd"))
        already_confirmed = line.get("confidence") == "user_confirmed"
        current_default = line.get("duty_hours_day") or 0
        duty_hours_override = (
            float(new_hours)
            if (
                new_hours is not None
                and (already_confirmed or float(new_hours) != current_default)
            )
            else None
        )

        factor_pct = to_float(row.get("fd"))
        factor = float(factor_pct) / 100.0 if factor_pct is not None else line.get("demand_factor_pct")

        updated_loads.append({
            **orig,
            "category": line["category"],
            "demand_factor_pct": factor,
            "duty_hours_day": duty_hours_override,
        })

    new_profile = build_load_profile(updated_loads, lat=lat, lon=lon)
    return {**scratch, "profile": new_profile}


def generate_hourly_shape(blob: dict, scratch_key: str) -> dict:
    """`POST paso/5/perfil/horario` (§1.7's exact route) →
    estimate_hourly_shape_illustrative() — illustrative-only, gated behind
    its own button, never touches the kWh/día sizing math (do-not-drop
    item 1's sibling note in wizard/off_grid.py)."""
    from calculations.load_profile_off_grid import estimate_hourly_shape_illustrative

    scratch = _scratch(blob, scratch_key)
    profile = scratch.get("profile")
    if not profile:
        return scratch

    rows = _table_rows(profile, diversified_used_downstream=False)
    cat_totals = _cat_totals(rows)
    load_names = [r["load_name"] for r in rows if r["category"] != "behavior_driven"] or None
    shapes = estimate_hourly_shape_illustrative(list(cat_totals.keys()), load_names=load_names)
    return {**scratch, "hourly_shape": shapes}


# ── Siguiente/Atrás ──────────────────────────────────────────────────────


def save_step(blob: dict, scratch_key: str = DEFAULT_SCRATCH_KEY) -> dict:
    """Verbatim port of step5_demand()'s own return dict — `daily_kwh` is
    the RAW (non-diversified) total (this is what off_grid.py's own Step 6
    sizes the array/battery against — `daily_kwh_diversified` is carried
    for display/Hybrid only, PLAN §1.10 item 1's "diversified_used_downstream"
    switch)."""
    consumption = blob.get("consumption") or {}
    scratch = _scratch(blob, scratch_key)
    profile = scratch.get("profile") or consumption.get("profile")
    if not profile:
        return consumption

    total_kwh_day = profile.get("total_kwh_day", 0.0)
    total_diversified = profile.get("total_kwh_day_diversified", total_kwh_day)
    return {
        **consumption,
        "profile": profile,
        "daily_kwh": total_kwh_day,
        "daily_kwh_diversified": total_diversified,
    }


# ── build_context ────────────────────────────────────────────────────────


def build_context(
    blob: dict,
    scratch_key: str = DEFAULT_SCRATCH_KEY,
    diversified_used_downstream: bool = False,
    show_category_chart: bool = True,
    show_hourly_chart: bool = True,
) -> dict:
    blob = blob or {}
    consumption = blob.get("consumption") or {}
    scratch = _scratch(blob, scratch_key)
    # Scratch first (this session's live calc/recalc), else whatever was
    # already persisted at a prior Siguiente click (a draft resumed at this
    # step, or revisited via the breadcrumb) — same fallback shape as
    # gz_s5_consumption.build_context()'s applied_months handling.
    profile = scratch.get("profile") or consumption.get("profile")

    if not profile:
        return {
            "scratch_key": scratch_key,
            "profile": None,
            "rows": [],
            "total_kwh_day": 0.0,
            "total_kwh_day_diversified": 0.0,
            "diversified_used_downstream": diversified_used_downstream,
            "default_count": 0,
            "chart_html": None,
            "show_category_chart": show_category_chart,
            "show_hourly_chart": show_hourly_chart,
            "hourly_chart_html": None,
            "can_continue": False,
        }

    rows = _table_rows(profile, diversified_used_downstream)
    cat_totals = _cat_totals(rows)
    total_kwh_day = profile.get("total_kwh_day", round(sum(r["kwh_day"] for r in rows), 2))
    total_diversified = profile.get("total_kwh_day_diversified", total_kwh_day)
    default_count = sum(1 for r in rows if r["badge"] == _CONFIDENCE_BADGES["default_assumed"][0])

    chart_html = None
    if show_category_chart and total_kwh_day > 0 and cat_totals:
        from webapp.figures import fig_to_fragment, og_category_donut_fig

        chart_html = fig_to_fragment(og_category_donut_fig(cat_totals))

    hourly_chart_html = None
    shapes = scratch.get("hourly_shape")
    if show_hourly_chart and total_kwh_day > 0 and shapes:
        from webapp.figures import fig_to_fragment, og_hourly_stack_fig

        hourly_chart_html = fig_to_fragment(og_hourly_stack_fig(cat_totals, shapes))

    return {
        "scratch_key": scratch_key,
        "profile": profile,
        "rows": rows,
        "total_kwh_day": total_kwh_day,
        "total_kwh_day_diversified": total_diversified,
        "diversified_used_downstream": diversified_used_downstream,
        "default_count": default_count,
        "chart_html": chart_html,
        "show_category_chart": show_category_chart,
        "show_hourly_chart": show_hourly_chart,
        "hourly_chart_html": hourly_chart_html,
        "can_continue": total_kwh_day > 0,
    }
