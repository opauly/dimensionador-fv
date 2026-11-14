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
    "bill_calibrated": ("🧾 Ajustado al recibo", "#047857"),
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
            "installed_kw": float(line.get("connected_power_kw") or 0) * int(line.get("quantity") or 1),
            "badge": badge,
            "badge_color": color,
            "detail": line["source_detail"],
        })
    return rows


def _row_totals(rows: list[dict]) -> dict:
    """Footer of the demand table: energy (kWh/día), its blended demand factor, and the installed vs demanded POWER the same
    per-line factors give (the ones the engineer can edit here)."""
    kwh = sum(r["kwh_day"] for r in rows)
    energy = sum(r["energy_kwh_day"] for r in rows)
    installed = sum(r["installed_kw"] for r in rows)
    demand = sum(r["installed_kw"] * r["factor_pct"] / 100.0 for r in rows)
    return {"qty": sum(int(r["quantity"] or 0) for r in rows), "kwh_day": round(kwh, 2), "energy_kwh_day": round(energy, 2),
            "energy_factor_pct": round(energy / kwh * 100) if kwh else 0,
            "installed_kw": round(installed, 2), "demand_kw": round(demand, 2),
            "power_factor_pct": round(demand / installed * 100) if installed else 0}


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
    return {**scratch, "profile": profile, "adjust_note": None}


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
    calibrated = set()            # lines a previous "Ajustar al recibo" scaled and the engineer has not retyped since
    for i, (orig, line) in enumerate(zip(loads, profile["lines"])):
        row = rows[i] if i < len(rows) else {}

        new_hours = to_float(row.get("hd"))
        was_calibrated = line.get("confidence") == "bill_calibrated"
        already_confirmed = line.get("confidence") == "user_confirmed" or was_calibrated
        current_default = line.get("duty_hours_day") or 0
        duty_hours_override = (
            float(new_hours)
            if (
                new_hours is not None
                and (already_confirmed or float(new_hours) != current_default)
            )
            else None
        )
        if was_calibrated and duty_hours_override is not None and abs(duty_hours_override - current_default) < 1e-9:
            calibrated.add(i)

        factor_pct = to_float(row.get("fd"))
        factor = float(factor_pct) / 100.0 if factor_pct is not None else line.get("demand_factor_pct")

        updated_loads.append({
            **orig,
            "category": line["category"],
            "demand_factor_pct": factor,
            "duty_hours_day": duty_hours_override,
        })

    new_profile = build_load_profile(updated_loads, lat=lat, lon=lon)
    out = {**scratch, "adjust_note": None}
    bill_month = to_float(form.get("adjust_kwh_month"))
    if bill_month is not None:
        out["bill_kwh_month"] = bill_month

    if form.get("_adjust") == "1":
        if not bill_month or bill_month <= 0:
            out.update(adjust_note="Escribe el consumo mensual real del recibo (kWh/mes).", adjust_ok=False)
        else:
            new_profile, calibrated, note, ok = _adjust_to_bill(updated_loads, new_profile, calibrated, bill_month / MONTH_DAYS, lat, lon)
            out.update(adjust_note=note, adjust_ok=ok)
    _mark_calibrated(new_profile, calibrated, profile)
    out["profile"] = new_profile
    return out


MONTH_DAYS = 30.4          # same days-per-month the hybrid main-panel figures use
MAX_HOURS = 24.0


def _adjust_to_bill(updated_loads: list[dict], profile: dict, calibrated: set, target_day: float, lat, lon):
    """"Ajustar al recibo": scale the daily hours of the lines the engineer has NOT confirmed so the total kWh/día equals the
    real consumption on the bill. Lines with hours the engineer typed stay as they are; a line that would need more than 24 h
    stops at 24 and the others absorb the rest. Returns (profile, calibrated line indexes, note, ok)."""
    from calculations.load_profile_off_grid import build_load_profile

    lines = profile["lines"]
    flexible = [i for i, l in enumerate(lines)
                if (l["confidence"] != "user_confirmed" or i in calibrated)
                and l["connected_power_kw"] * l["quantity"] > 0 and (l.get("duty_hours_day") or 0) > 0]
    fixed_kwh = sum(l["estimated_kwh_day"] for i, l in enumerate(lines) if i not in flexible)
    flex_kwh = sum(lines[i]["estimated_kwh_day"] for i in flexible)
    if not flexible or flex_kwh <= 0:
        return profile, calibrated, "No hay líneas que ajustar: todas tienen horas confirmadas o no consumen.", False
    remaining = target_day - fixed_kwh
    if remaining <= 0:
        return profile, calibrated, (f"Las líneas con horas confirmadas ya suman {fixed_kwh:,.1f} kWh/día, "
                                     f"más que el recibo ({target_day:,.1f} kWh/día)."), False

    kw = {i: lines[i]["connected_power_kw"] * lines[i]["quantity"] for i in flexible}
    hours = {i: float(lines[i]["duty_hours_day"]) for i in flexible}
    free, factor, capped_n = set(flexible), 1.0, 0
    while free:
        free_kwh = sum(kw[i] * hours[i] for i in free)
        factor = remaining / free_kwh
        over = [i for i in free if hours[i] * factor > MAX_HOURS]
        if not over:
            for i in free:
                hours[i] = round(hours[i] * factor, 3)
            break
        for i in over:
            hours[i] = MAX_HOURS
            remaining -= kw[i] * MAX_HOURS
            free.discard(i)
            capped_n += 1
        if remaining <= 0:
            break

    adjusted = [dict(l) for l in updated_loads]
    for i in flexible:
        adjusted[i]["duty_hours_day"] = hours[i]
    new_profile = build_load_profile(adjusted, lat=lat, lon=lon)
    total = new_profile["total_kwh_day"]
    fixed_n = len(lines) - len(flexible)
    ok = abs(total - target_day) <= max(0.05, target_day * 0.005)
    note = (f"Ajustado a {target_day * MONTH_DAYS:,.0f} kWh/mes ({target_day:,.1f} kWh/día): "
            f"{len(flexible)} línea(s) escaladas ×{factor:,.1f}" + (f", {fixed_n} con horas confirmadas se respetaron" if fixed_n else "") + ".")
    if ok and factor >= 2:
        note += " Un factor tan alto sugiere que faltan equipos en la lista o que se usan más horas de las típicas."
    if not ok:
        note = (f"No se alcanza el recibo: {capped_n} línea(s) ya están al máximo de 24 h/día. "
                f"Total posible {total:,.1f} kWh/día de {target_day:,.1f}. Faltan cargas en la lista.")
    return new_profile, set(flexible), note, ok


def _mark_calibrated(profile: dict, calibrated: set, prior_profile: dict) -> None:
    """Lines scaled by "Ajustar al recibo" keep their own badge (and stay overrides on later recalculations)."""
    for i in calibrated:
        if i < len(profile["lines"]):
            line = profile["lines"][i]
            line["confidence"] = "bill_calibrated"
            line["source_detail"] = (f"{line['connected_power_kw']} kW × {line['duty_hours_day']} h/día × {line['quantity']} "
                                     f"(horas ajustadas para que el total coincida con el recibo)")


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
    result = {
        **consumption,
        "profile": profile,
        "daily_kwh": total_kwh_day,
        "daily_kwh_diversified": total_diversified,
    }
    result["daily_kwh_max"] = _daily_kwh_all_at_maximum(blob, consumption, total_kwh_day)
    return result


def _daily_kwh_all_at_maximum(blob: dict, consumption: dict, expected_total: float):
    """kWh/day if every load were used at its STATED maximum (Step 4's Horas/día, before the expected-use %). None when
    no load carries an expected-use reduction, i.e. the maximum is the same as the sizing basis."""
    loads = consumption.get("loads") or []
    if not any(l.get("duty_hours_max") and l.get("duty_hours_day") != l.get("duty_hours_max") for l in loads):
        return None
    try:
        from calculations.load_profile_off_grid import build_load_profile

        max_loads = [{**l, "duty_hours_day": l["duty_hours_max"]} if l.get("duty_hours_max") else l for l in loads]
        lat, lon = _site_latlon(blob)
        total = build_load_profile(max_loads, lat=lat, lon=lon)["total_kwh_day"]
        return total if total > expected_total + 1e-9 else None
    except Exception:
        return None


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
            "bill_kwh_month": scratch.get("bill_kwh_month"),
            "calibrated_count": 0,
            "adjust_note": None, "adjust_ok": True,
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
        "totals": _row_totals(rows),
        "total_kwh_day": total_kwh_day,
        "total_kwh_day_diversified": total_diversified,
        "diversified_used_downstream": diversified_used_downstream,
        "default_count": default_count,
        "chart_html": chart_html,
        "show_category_chart": show_category_chart,
        "show_hourly_chart": show_hourly_chart,
        "hourly_chart_html": hourly_chart_html,
        "can_continue": total_kwh_day > 0,
        "bill_kwh_month": scratch.get("bill_kwh_month"),
        "calibrated_count": sum(1 for r in rows if r["badge"] == _CONFIDENCE_BADGES["bill_calibrated"][0]),
        "adjust_note": scratch.get("adjust_note"),
        "adjust_ok": scratch.get("adjust_ok", True),
    }
