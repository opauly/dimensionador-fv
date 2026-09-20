"""Grid Zero Step 6 — Equipos (MPPT A/B/C/M). Port of
wizard/grid_zero.py:step6_equipment() — PLAN_PHASE20_PROPOSALS_JINJA.md's
"### Step 5 — Grid Zero step 6" build step, its own opening line: "The single
densest screen in the wizard. Port it as a whole; do not ship a partial
version."

Per PLAN §1.3, `build_context(blob)` is the one function every route
rendering any part of this step calls — the full-page GET and every one of
its action POSTs (equipment select, MPPT calc, scenario select, manual
select, manual live-validate, Siguiente/Atrás). Given how much this step
computes (scenarios, projections, chosen-config display, all three
charts/stats), every action swaps the SAME single fragment
(`wizard/_s6_equipos.html`, root id `s6-equipos`) rather than a narrower
region — the cross-dependencies here (an equipment change affects spec
cards AND scenarios AND manual defaults AND the chosen-config block AND
every stat below it; a manual-mode edit affects the manual card AND the
chosen-config block AND stats) make "just re-render the panel that changed"
exactly the failure mode §1.3 warns about.

`scratch.s6` shape (PLAN §1.1's example, filled in here):
    {"panel_id": ..., "inverter_id": ..., "monitoring_id": ...,
     "equip_key": "<panel_id>_<inverter_id>",
     "scenarios": [...], "selected_scenario": "B", "use_manual": false,
     "coverage_ai": {"fraction": 0.48, "note": "..."},
     "manual": {"series": 6, "parallel": 2}}

Do-not-drop items carried from PLAN §1.10 (cited by number at each site
below): 3, 6, 7, 8, 10, 11, 12, 13, 14, 15.

One deliberate correction vs. the literal Streamlit source, flagged here
because it changes behaviour and PLAN §1.10 item 15 requires it: see
`_resolve_chosen()`'s docstring.
"""
from __future__ import annotations

from calculations.mppt import check_design, validate_string_design


# ── scratch / catalog helpers ────────────────────────────────────────────


def _s6(blob: dict) -> dict:
    return (blob.get("scratch") or {}).get("s6") or {}


def _catalog() -> tuple[list[dict], list[dict], list[dict]]:
    from database.equipment_db import list_inverters, list_monitoring_devices, list_panels

    return list_panels(), list_inverters(), list_monitoring_devices()


def _find(items: list[dict], id_: str | None) -> dict | None:
    if not id_:
        return None
    return next((x for x in items if x.get("id") == id_), None)


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


def _avg_irradiance(site: dict) -> float:
    pvgis_monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp") or []
    return sum(pvgis_monthly) / 12 if pvgis_monthly else 127.0


def _resolve_selection(blob: dict) -> dict:
    """Panel/inverter/monitoring currently in play, plus the manual
    series/parallel currently in play — the one place every action + render
    function reads "what's selected right now" from, so a panel/inverter/
    monitoring pick made via `select_equipment()` and a manual edit made via
    `validate_manual()` are both immediately visible everywhere else,
    without each caller re-deriving the fallback chain itself."""
    s6 = _s6(blob)
    current = blob.get("equipment") or {}
    panels, inverters, monitoring_devices = _catalog()

    panel_id = s6.get("panel_id") or current.get("panel_id") or (panels[0]["id"] if panels else None)
    inverter_id = s6.get("inverter_id") or current.get("inverter_id") or (inverters[0]["id"] if inverters else None)
    monitoring_id = s6.get("monitoring_id", current.get("monitoring_id"))

    selected_panel = _find(panels, panel_id) or (panels[0] if panels else None)
    selected_inverter = _find(inverters, inverter_id) or (inverters[0] if inverters else None)
    selected_monitoring = _find(monitoring_devices, monitoring_id)

    # Manual series/parallel defaults to Escenario B's combo when scenarios
    # exist, else 6/2 — verbatim port of step6_equipment()'s
    # default_series/default_parallel (L921-922).
    manual = s6.get("manual") or {}
    scenarios = s6.get("scenarios") or []
    b_scenario = next((sc for sc in scenarios if sc.get("scenario") == "B"), None)
    m_series = int(manual.get("series") or (b_scenario["panels_per_string"] if b_scenario else 6))
    m_parallel = int(manual.get("parallel") or (b_scenario["strings"] if b_scenario else 2))

    return {
        "panels": panels,
        "inverters": inverters,
        "monitoring_devices": monitoring_devices,
        "selected_panel": selected_panel,
        "selected_inverter": selected_inverter,
        "selected_monitoring": selected_monitoring,
        "m_series": m_series,
        "m_parallel": m_parallel,
    }


def _effective_label(scenarios: list[dict] | None, s6: dict, using_manual: bool) -> str | None:
    """Do-not-drop item 13 — verbatim port of step6_equipment()'s inline
    default-selection logic (L823-827): `valid_labels[min(1, len-1)]`, i.e.
    prefer Escenario B, falling back to A/C when B isn't valid. Recomputed
    on every render (never written back to `scratch`), exactly like the
    Streamlit original recomputes it as a local on every rerun rather than
    persisting the fallback."""
    stored = s6.get("selected_scenario")
    if using_manual or not scenarios:
        return stored
    valid_labels = [s["scenario"] for s in scenarios if s["within_limits"]]
    if not valid_labels:
        return stored
    if stored not in valid_labels:
        return valid_labels[min(1, len(valid_labels) - 1)]
    return stored


def _resolve_chosen(
    scenarios: list[dict] | None, effective_label: str | None, using_manual: bool, manual_design: dict | None,
) -> tuple[dict | None, str | None]:
    """The chosen (auto-scenario or manual) design, or None if nothing valid
    is currently selectable — the single source both `build_context()` (for
    the chosen-config block + `can_continue`) and `save_step()` (for what
    gets persisted at "Siguiente") call, so they can never disagree about
    whether a design is currently valid.

    DELIBERATE CORRECTION vs. wizard/grid_zero.py's literal source (flagged
    per this file's module docstring): the Streamlit "Siguiente" handler
    (L1253-1263) does NOT re-check `m["within_limits"]` when `using_manual`
    is true — it unconditionally builds `chosen_scenario` from whatever
    series/parallel are currently typed and labels it "M", even if those
    values are out of limits (the on-screen "chosen" used for the
    Validación/Margen/Dimensionamiento preview two dozen lines earlier DOES
    gate on validity via `chosen = m if m["within_limits"] else None` —
    only the persist path skips that check). PLAN §1.10 item 14/15 are
    explicit that an out-of-limits manual design "cannot be selected as the
    active configuration" and that Siguiente must reject it server-side, so
    this port applies the same validity gate on both paths rather than
    reproducing the Streamlit persist path's gap.
    """
    if using_manual:
        chosen = manual_design if (manual_design is not None and manual_design.get("within_limits")) else None
        return chosen, "M"
    chosen = next((s for s in (scenarios or []) if s["scenario"] == effective_label), None)
    return chosen, effective_label


def _scenario_projection(
    system_kw: float,
    avg_irradiance: float,
    avg_kwh: float,
    avg_bill_crc: float,
    tariff_info: dict | None,
    daytime_fraction: float = 0.45,
) -> dict:
    """
    Zero-export model: no energy fed to grid; excess solar is curtailed.
    Verbatim port of wizard/grid_zero.py's own `_scenario_projection()`
    (L590-643) — kept here rather than imported from `wizard/grid_zero.py`
    (a Streamlit-importing module) so `webapp/wizard_steps/*.py` stays free
    of any dependency on the Streamlit wizard, matching every other step
    module's convention (gz_s4_utility.py/gz_s5_consumption.py import only
    from `calculations`/`database`, never from `wizard.*`).

      daytime_kwh   = avg_kwh × daytime_fraction   (consumption during solar hours)
      self_consumed = min(gen, daytime_kwh)          (solar actually used on-site)
      curtailed     = max(0, gen − daytime_kwh)      (solar that can't be absorbed)
      grid_kwh      = avg_kwh − self_consumed        (still drawn from grid)
      coverage      = self_consumed / avg_kwh         (always < 100 % due to nights)

    `new_bill` is the energy-charge + access-charge estimate only —
    bomberos, alumbrado público, IVA, and Generación Distribuida charges are
    deliberately excluded (do-not-drop item 26); see
    `calculations/tariff_calculator.py`'s docstring.
    """
    from calculations.tariff_calculator import estimate_bill_crc as _est

    gen = round(system_kw * avg_irradiance)

    daytime_kwh = avg_kwh * daytime_fraction
    self_consumed = min(float(gen), daytime_kwh)
    curtailed = max(0, gen - int(daytime_kwh))
    grid_kwh = max(0.0, avg_kwh - self_consumed)

    coverage = round(self_consumed / avg_kwh * 100, 1) if avg_kwh > 0 else 0.0
    self_consumption_pct = round(self_consumed / gen * 100) if gen > 0 else 0

    if tariff_info:
        new_bill = _est(grid_kwh, tariff_info)
        savings = max(0, round(avg_bill_crc - new_bill))
    else:
        new_bill = None
        savings = None
    return {
        "gen": int(gen),
        "grid_kwh": int(grid_kwh),
        "coverage": coverage,
        "curtailed": curtailed,
        "new_bill": int(new_bill) if new_bill is not None else None,
        "savings": savings,
        "self_consumption_pct": self_consumption_pct,
    }


# ── equipment selection (do-not-drop item 11) ───────────────────────────


def select_equipment(blob: dict, form) -> dict:
    """`paso/6/equipo`'s core logic — verbatim port of the
    `equip_key`-changed reset block (wizard/grid_zero.py L728-734).
    Changing panel OR inverter clears scenarios/manual-mode/selection.
    `coverage_ai` (the AI daytime-fraction estimate) is intentionally NOT
    cleared — Streamlit's own reset only pops `w6_use_manual`/`w6_scenarios`/
    `w6_selected_scenario`, never `w6_coverage_ai`, because that estimate
    depends on the loads profile + location, not on which panel/inverter is
    selected."""
    s6 = _s6(blob)
    panels, inverters, _monitoring = _catalog()

    panel_id = (form.get("panel_id") or "").strip() or s6.get("panel_id") or (panels[0]["id"] if panels else None)
    inverter_id = (form.get("inverter_id") or "").strip() or s6.get("inverter_id") or (
        inverters[0]["id"] if inverters else None
    )
    monitoring_id = (form.get("monitoring_id") or "").strip() or None

    equip_key = f"{panel_id}_{inverter_id}" if panel_id and inverter_id else None
    new_s6 = {**s6, "panel_id": panel_id, "inverter_id": inverter_id, "monitoring_id": monitoring_id}

    if s6.get("equip_key") != equip_key:
        new_s6["equip_key"] = equip_key
        new_s6.pop("scenarios", None)
        new_s6.pop("selected_scenario", None)
        new_s6["use_manual"] = False
    return new_s6


# ── MPPT auto scenarios ──────────────────────────────────────────────────


def calc_mppt(blob: dict) -> dict:
    """`paso/6/mppt/calcular`'s core logic — verbatim port of the "Calcular
    configuración MPPT" button (L775-787): AI daytime-fraction estimate
    (now `ai/daytime_fraction.py`, PLAN §1.7) informs `target_kw`, which
    `validate_string_design()` turns into the A/B/C scenarios."""
    s6 = _s6(blob)
    sel = _resolve_selection(blob)
    selected_panel, selected_inverter = sel["selected_panel"], sel["selected_inverter"]
    if not selected_panel or not selected_inverter:
        return s6

    consumption = blob.get("consumption") or {}
    site = blob.get("site") or {}
    avg_kwh = consumption.get("avg_kwh", 0) or 0
    avg_irradiance = _avg_irradiance(site)

    # Reads Step 5's loads table regardless of which consumption source is
    # currently active — verbatim match of the original's own
    # `st.session_state.get("w5_loads_data", [])` (not gated on `source`).
    loads = ((blob.get("scratch") or {}).get("s5") or {}).get("loads_data") or []
    location = site.get("city") or "Costa Rica"

    from ai.daytime_fraction import estimate_daytime_fraction_ai

    fraction, note = estimate_daytime_fraction_ai(loads, location)
    daytime_kwh = avg_kwh * fraction
    target_kw = (daytime_kwh / avg_irradiance) if avg_irradiance > 0 else None

    scenarios = validate_string_design(selected_panel, selected_inverter, target_kw)

    return {
        **s6,
        "coverage_ai": {"fraction": fraction, "note": note},
        "scenarios": scenarios,
        "use_manual": False,
    }


def select_scenario(blob: dict, label: str) -> dict:
    """`paso/6/escenario/<label>`'s core logic. Only a currently-valid
    scenario's selector button renders at all (do-not-drop item 10), and
    this mirrors that server-side: selecting an unknown/invalid label is a
    no-op rather than silently activating an out-of-limits design."""
    s6 = _s6(blob)
    scenarios = s6.get("scenarios") or []
    valid_labels = {s["scenario"] for s in scenarios if s["within_limits"]}
    if label not in valid_labels:
        return s6
    return {**s6, "selected_scenario": label, "use_manual": False}


# ── Manual design (do-not-drop items 8, 14) ─────────────────────────────


def validate_manual(blob: dict, form) -> dict:
    """`paso/6/manual/validar`'s core logic — the live, change-triggered
    Voc/Vmp/Imax recompute (PLAN §1.4 pattern 3) as series/parallel are
    edited. Only updates the stored series/parallel; does not touch
    `use_manual` — `build_context()`'s own `_resolve_chosen()` call already
    re-validates on every render, so a manual design that was selected and
    then edited into invalid territory naturally stops being `chosen`
    without this route needing to know that itself."""
    from webapp.wizard_steps.common import to_float

    s6 = _s6(blob)
    series = int(to_float(form.get("m_series"), 6) or 6)
    parallel = int(to_float(form.get("m_parallel"), 2) or 2)
    series = max(1, min(50, series))
    parallel = max(1, min(50, parallel))
    return {**s6, "manual": {"series": series, "parallel": parallel}}


def select_manual(blob: dict) -> dict:
    """`paso/6/manual`'s core logic — do-not-drop item 14: a manual design
    can only be *selected* (i.e. become the active configuration) when it is
    currently `within_limits`. Rejecting this server-side (not just via a
    disabled button) is do-not-drop item 15's explicit requirement."""
    s6 = _s6(blob)
    sel = _resolve_selection(blob)
    if not sel["selected_panel"] or not sel["selected_inverter"]:
        return s6
    m = check_design(sel["selected_panel"], sel["selected_inverter"], sel["m_series"], sel["m_parallel"])
    if not m.get("within_limits"):
        return s6
    return {**s6, "use_manual": True}


# ── Siguiente ─────────────────────────────────────────────────────────────


def save_step(blob: dict) -> dict | None:
    """`Siguiente`'s persisted fields — verbatim port of
    step6_equipment()'s own return dict (wizard/grid_zero.py L1274-1289),
    with `_resolve_chosen()`'s validity gate applied (see its docstring).
    Returns None when neither a valid auto scenario nor a valid manual
    design currently exists — do-not-drop item 15's server-side half; the
    caller (webapp/blueprints/wizard.py) treats None as "reject the advance,
    re-render step 6 with an error" exactly like every other step's
    `can_continue` guard."""
    s6 = _s6(blob)
    sel = _resolve_selection(blob)
    selected_panel, selected_inverter = sel["selected_panel"], sel["selected_inverter"]
    if not selected_panel or not selected_inverter:
        return None

    scenarios = s6.get("scenarios") or []
    using_manual = bool(s6.get("use_manual"))
    manual_design = check_design(selected_panel, selected_inverter, sel["m_series"], sel["m_parallel"])

    effective_label = _effective_label(scenarios, s6, using_manual)
    chosen, active_label = _resolve_chosen(scenarios, effective_label, using_manual, manual_design)
    if chosen is None:
        return None

    consumption = blob.get("consumption") or {}
    site = blob.get("site") or {}
    utility = blob.get("utility") or {}
    avg_kwh = consumption.get("avg_kwh", 0) or 0
    avg_bill_crc = consumption.get("avg_bill_crc", 0) or 0
    avg_irradiance = _avg_irradiance(site)
    coverage_ai = s6.get("coverage_ai") or {}
    daytime_fraction = float(coverage_ai.get("fraction") or 0.45)
    ai_note = str(coverage_ai.get("note") or "")
    tariff_info = _tariff_info(utility)

    chosen_scenario = dict(chosen)
    projection = _scenario_projection(
        chosen_scenario["system_kw"], avg_irradiance, avg_kwh, avg_bill_crc, tariff_info, daytime_fraction,
    )

    return {
        "panel_id": selected_panel["id"],
        "panel": selected_panel,
        "inverter_id": selected_inverter["id"],
        "inverter": selected_inverter,
        "mppt_scenario": active_label,
        "chosen_scenario": chosen_scenario,
        # Do-not-drop item 7 — the FULL scenario set, not just the chosen one.
        "scenarios": scenarios,
        "projection": projection,
        # Do-not-drop item 6 — persisted alongside (not read back out of the
        # transient scratch.s6.coverage_ai, which a resumed session could
        # lose) so Step 8's caption survives.
        "daytime_fraction_note": ai_note,
        "monitoring_id": sel["selected_monitoring"]["id"] if sel["selected_monitoring"] else None,
        "monitoring": sel["selected_monitoring"],
    }


# ── build_context ────────────────────────────────────────────────────────


def build_context(blob: dict) -> dict:
    blob = blob or {}
    s6 = _s6(blob)
    consumption = blob.get("consumption") or {}
    site = blob.get("site") or {}
    utility = blob.get("utility") or {}

    sel = _resolve_selection(blob)
    panels, inverters, monitoring_devices = sel["panels"], sel["inverters"], sel["monitoring_devices"]
    selected_panel, selected_inverter, selected_monitoring = (
        sel["selected_panel"], sel["selected_inverter"], sel["selected_monitoring"],
    )

    if not panels or not inverters:
        return {
            "no_catalog": True,
            "can_continue": False,
            "panels": [], "inverters": [], "monitoring_devices": [],
        }

    area_panel = float(selected_panel.get("width_m") or 0) * float(selected_panel.get("height_m") or 0)

    avg_kwh = consumption.get("avg_kwh", 0) or 0
    avg_bill_crc = consumption.get("avg_bill_crc", 0) or 0
    avg_irradiance = _avg_irradiance(site)

    coverage_ai = s6.get("coverage_ai") or {}
    daytime_fraction = float(coverage_ai.get("fraction") or 0.45)
    ai_note = str(coverage_ai.get("note") or "")
    daytime_kwh = avg_kwh * daytime_fraction

    tariff_info = _tariff_info(utility)

    scenarios = s6.get("scenarios")
    using_manual = bool(s6.get("use_manual"))
    effective_label = _effective_label(scenarios, s6, using_manual)

    # ── Scenario table + projection cards (do-not-drop items 10, 12, 13) ──
    scenario_rows = []
    scenario_cards = []
    all_saturated = False
    optimal_kw = None
    valid_scenarios: list[dict] = []
    if scenarios:
        valid_scenarios = [s for s in scenarios if s["within_limits"]]
        for s in scenarios:
            proj = _scenario_projection(s["system_kw"], avg_irradiance, avg_kwh, avg_bill_crc, tariff_info, daytime_fraction)
            scenario_rows.append({
                "escenario": s["scenario"],
                "panels_per_string": s["panels_per_string"],
                "strings": s["strings"],
                "total_panels": s["total_panels"],
                "system_kw": s["system_kw"],
                "area_m2": s.get("area_m2") or round(s["total_panels"] * area_panel, 1),
                "voc_total": s["voc_total"],
                "vmp_total": s["vmp_total"],
                "self_consumption_pct": proj["self_consumption_pct"],
                "within_limits": s["within_limits"],
                "notes": s["notes"],
            })
            scenario_cards.append({
                "scenario": s,
                "proj": proj,
                "is_valid": s["within_limits"],
                "is_selected": (s["scenario"] == effective_label) and not using_manual,
            })
        all_saturated = len(scenarios) > 1 and all(c["proj"]["curtailed"] > 0 for c in scenario_cards)
        if all_saturated:
            optimal_kw = round(daytime_kwh / avg_irradiance, 2) if avg_irradiance > 0 else None

    note_parts = []
    if ai_note:
        note_parts.append(f"🤖 IA — Perfil de consumo: {ai_note}")
    note_parts.append(
        "ℹ️ Zero-export: el excedente solar no se inyecta a la red — se descarta. La cobertura está "
        "limitada por el consumo diurno estimado. Autoconsumo = fracción de la generación que "
        "efectivamente desplaza consumo de la red."
    )

    # ── Manual design (do-not-drop items 8, 14) ───────────────────────────
    manual_design = check_design(selected_panel, selected_inverter, sel["m_series"], sel["m_parallel"])
    vmax = float(selected_inverter.get("vmax") or 0)
    vmin_mppt = float(selected_inverter.get("vmin_mppt") or 0)
    vmax_mppt = float(selected_inverter.get("vmax_mppt") or 0)
    imax_mppt = float(selected_inverter.get("imax_mppt") or 0)
    manual_area_m2 = manual_design.get("area_m2") or round(manual_design["total_panels"] * area_panel, 1)
    manual_proj = None
    if avg_kwh > 0:
        manual_proj = _scenario_projection(
            manual_design["system_kw"], avg_irradiance, avg_kwh, avg_bill_crc, tariff_info, daytime_fraction,
        )

    # ── Chosen config (resolved once — reused by Validación/Margen/
    # Dimensionamiento/Generación-vs-consumo/Estadísticas below) ──────────
    chosen, active_label = _resolve_chosen(scenarios, effective_label, using_manual, manual_design)

    chosen_ctx = None
    if chosen:
        voc_ok = chosen["voc_total"] <= vmax
        vmp_ok = vmin_mppt <= chosen["vmp_total"] <= vmax_mppt
        imp_ok = chosen["imp_per_mppt"] <= imax_mppt
        is_chosen_valid = chosen["within_limits"]

        margin_items = [
            ("Voc del arreglo (vs. inversor)", (chosen["voc_total"] / vmax * 100) if vmax else 0),
            ("Corriente por MPPT (vs. inversor)", (chosen["imp_per_mppt"] / imax_mppt * 100) if imax_mppt else 0),
        ]
        from webapp.figures import fig_to_fragment, gz_margin_bars_fig

        margin_chart_html = fig_to_fragment(gz_margin_bars_fig(margin_items))

        chosen_proj = _scenario_projection(
            chosen["system_kw"], avg_irradiance, avg_kwh, avg_bill_crc, tariff_info, daytime_fraction,
        )

        gen_chart_html = None
        if chosen_proj["gen"] > 0:
            from webapp.figures import gz_generation_vs_consumption_fig

            gen_chart_html = fig_to_fragment(gz_generation_vs_consumption_fig(chosen_proj["gen"], avg_kwh))

        chosen_ctx = {
            "scenario_note": "manual" if chosen["scenario"] == "M" else f"Escenario {chosen['scenario']}",
            "voc_ok": voc_ok, "vmp_ok": vmp_ok, "imp_ok": imp_ok,
            "is_valid": is_chosen_valid,
            "vmax": vmax, "vmin_mppt": vmin_mppt, "vmax_mppt": vmax_mppt, "imax_mppt": imax_mppt,
            "voc_total": chosen["voc_total"], "vmp_total": chosen["vmp_total"], "imp_per_mppt": chosen["imp_per_mppt"],
            "notes": chosen.get("notes"),
            "margin_chart_html": margin_chart_html,
            "total_panels": chosen["total_panels"], "panels_per_string": chosen["panels_per_string"],
            "strings": chosen["strings"], "system_kw": chosen["system_kw"],
            "area_m2": chosen.get("area_m2") or round(chosen["total_panels"] * area_panel, 1),
            "proj": chosen_proj,
            "gen_chart_html": gen_chart_html,
        }

    # ── Estadísticas — Cobertura mensual + Aprovechamiento solar (do-not-
    # drop items 3, 6) ─────────────────────────────────────────────────────
    stats_ctx = None
    if chosen:
        pvgis_monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp") or []
        coverage_chart_html = None
        if pvgis_monthly and len(pvgis_monthly) == 12:
            months_data = consumption.get("months_data") or []
            monthly_kwh_real = (
                [md["kwh"] for md in months_data] if len(months_data) == 12 else [avg_kwh] * 12
            )
            gen_m = [round(v * chosen["system_kw"], 1) for v in pvgis_monthly]
            from webapp.figures import fig_to_fragment, monthly_coverage_fig

            coverage_chart_html = fig_to_fragment(monthly_coverage_fig(gen_m, monthly_kwh_real, flag_shortfall=False))

        step6_proj = _scenario_projection(
            chosen["system_kw"], avg_irradiance, avg_kwh, avg_bill_crc, tariff_info, daytime_fraction,
        )
        self_consumption_pct = step6_proj["self_consumption_pct"]
        used_kwh_month = round(step6_proj["gen"] - step6_proj["curtailed"])
        curtailed_kwh_month = round(step6_proj["curtailed"])

        from webapp.figures import fig_to_fragment, gz_solar_utilization_fig

        utilization_chart_html = fig_to_fragment(
            gz_solar_utilization_fig(used_kwh_month, curtailed_kwh_month, self_consumption_pct)
        )

        stats_ctx = {
            "coverage_chart_html": coverage_chart_html,
            "utilization_chart_html": utilization_chart_html,
            "self_consumption_pct": self_consumption_pct,
            "ai_note": ai_note,
            "oversized": self_consumption_pct < 50,
        }

    return {
        "panels": panels, "inverters": inverters, "monitoring_devices": monitoring_devices,
        "selected_panel": selected_panel, "selected_inverter": selected_inverter,
        "selected_monitoring": selected_monitoring,
        "area_panel": area_panel,
        "scenarios": scenarios,
        "scenario_rows": scenario_rows,
        "scenario_cards": scenario_cards,
        "valid_scenarios_count": len(valid_scenarios),
        "all_saturated": all_saturated,
        "optimal_kw": optimal_kw,
        "daytime_kwh": daytime_kwh,
        "note_parts": note_parts,
        "using_manual": using_manual,
        "manual": {
            "series": sel["m_series"], "parallel": sel["m_parallel"],
            "design": manual_design, "area_m2": manual_area_m2,
            "vmax": vmax, "vmin_mppt": vmin_mppt, "vmax_mppt": vmax_mppt, "imax_mppt": imax_mppt,
            "can_select": manual_design.get("within_limits", False),
            "proj": manual_proj,
        },
        "chosen": chosen_ctx,
        "active_label": active_label,
        "stats": stats_ctx,
        "can_continue": chosen is not None,
    }
