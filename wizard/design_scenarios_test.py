"""
Step 6 (TEST) — static design-tier scenario cards.

Driven by calculations.sizing_off_grid.generate_design_scenarios() /
generate_design_scenarios_hybrid() instead of the legacy iterative
reliability search (generate_reliability_scenarios()). Lives entirely
outside wizard/off_grid.py and wizard/hybrid.py so production Step 6 is
never touched by this experiment. See pages/02b_new_proposal_test.py for
the page that reuses Steps 1-5 unchanged, routes this file's Step 6, then
hands off to the REAL wizard.off_grid/hybrid step7_costs()/step8_review()
unchanged (see _to_wizard_equipment()/_manual_to_wizard_equipment() below
for the adapters that make a selected design look like production Step 6's
own output).

Visual/UX parity with production's step6_equipment() (2026-08): reuses that
module's private styling/logic helpers directly (_spec_card, _chip_row,
_param_row, _CHECK_STATUS_STYLE, _MAX_CHARGE_CONTROLLERS,
_og_scenario_projection, _og_monthly_coverage_and_sim) rather than
duplicating them — same pattern wizard/hybrid.py already uses
(off_grid._render_demand_profile_block, off_grid.step7_costs). Manual mode
(Opción 2) is a genuine free-form override (series/strings/battery count),
independent of the tier formulas, same as production. Design validation is
built from the static model's OWN flags (within_limits,
meets_target_daily_kwh, worst_month_covers_load/recharge_ok,
tier_inversion_warning) instead of re-deriving production's electrical
checks — those still apply for manual mode, where the tier flags don't
exist.

Dropped from production for a first pass (lowest value / most code):
seasonal-coverage line chart, Sankey energy-flow diagram.

Still no autosave and still never persisted to Supabase: step7_costs()/
step8_review() only write st.session_state["wizard_costs"]/PDF bytes, no
proposal/version row is created (that only happens via the real page's own
save flow, never called here) — safe to click through fully as a sandbox.
"""
from __future__ import annotations
import streamlit as st

from config import BRAND_GREEN, BRAND_GREEN_LIGHT, BRAND_NAVY
from wizard import off_grid

_STATUS_COLORS = {"green": "#16a34a", "yellow": "#b45309", "red": "#dc2626"}
_STATUS_LABELS_ES = {"green": "Verde", "yellow": "Amarillo", "red": "Rojo"}


def _compute_hybrid_savings(consumption: dict, daily_generation_kwh: float) -> dict | None:
    """
    Shared gate + calc for the hybrid bill-reduction estimate, used by every
    card (auto tiers and manual) AND the final wizard_equipment adapters —
    one place so the same design never reports two different savings
    numbers. Mirrors wizard/off_grid.py's own step6_equipment() gate
    exactly (same function is shared there by both system types): only
    fires when Step 4 recorded a grid connection + tariff. Off-grid sessions
    never set these, so this is always a no-op there, same as production.
    """
    if not (bool(consumption.get("grid_connected")) and bool(consumption.get("utility"))):
        return None
    raw_critical_daily_kwh = consumption.get("daily_kwh", 0.0)
    main_panel = consumption.get("main_panel")
    if consumption.get("panel_scope") == "secondary" and main_panel:
        whole_home_avg_kwh_month = float(main_panel.get("avg_kwh_month") or 0)
    else:
        whole_home_avg_kwh_month = raw_critical_daily_kwh * 30.4
    if whole_home_avg_kwh_month <= 0:
        return None
    from calculations.sizing_off_grid import estimate_hybrid_savings_pct
    return estimate_hybrid_savings_pct(
        daily_generation_kwh=daily_generation_kwh, critical_daily_kwh=raw_critical_daily_kwh,
        whole_home_avg_kwh_month=whole_home_avg_kwh_month,
        daytime_fraction=0.45, tariff_info=consumption["utility"],
    )


def _final_inverter_qty(r: dict, system_type: str, base_qty: int) -> dict:
    """
    Automatic per-tier inverter count: base_qty (split-phase-driven) bumped
    up to whichever THIS tier's own loading-target recommendation needs
    (inverter_qty_recommended off-grid / islanded.inverter_qty_recommended
    hybrid) — mirrors production's Scenario-3 inverter-doubling idea, but
    per-tier and automatic rather than a single manual "Cantidad de
    inversores" input (production has none either).

    loading_pct is recomputed against the final qty with plain arithmetic
    (available_kw scales linearly with qty at fixed peak demand, so
    loading_pct_final = loading_pct_base * base_qty / final_qty) rather than
    a second call into the generator.
    """
    inv = r["inverter"]
    isl = inv["islanded"] if system_type != "off_grid" else inv
    recommended = isl.get("inverter_qty_recommended") or base_qty
    final_qty = max(base_qty, recommended)
    base_loading_pct = isl.get("loading_pct") or 0.0
    loading_target_pct = isl.get("loading_target_pct")
    loading_pct = (
        base_loading_pct if final_qty == base_qty
        else round(base_loading_pct * base_qty / final_qty, 1)
    )
    within_target = loading_target_pct is not None and loading_pct <= loading_target_pct
    return {
        "qty": final_qty, "loading_pct": loading_pct,
        "loading_target_pct": loading_target_pct, "within_target": within_target,
        "bumped": final_qty > base_qty,
    }


def _to_wizard_equipment(
    r: dict, system_type: str, panel: dict, inverter: dict, battery: dict, cc: dict,
    inverter_qty: int, consumption: dict, daily_kwh_consumption: float,
    monitoring: dict | None = None,
) -> dict:
    """
    Adapts one generate_design_scenarios()/_hybrid() tier result into the
    same shape wizard/off_grid.py's step6_equipment()'s own `result = {...}`
    produces — this is what lets a selected static-model tier hand off to
    the UNCHANGED production step7_costs()/step8_review().

    split_phase isn't decided by the static model (voltage-service
    question, not a sizing one) — computed here with check_split_phase()
    and consumption["voltage_v"] (set in Step 4), same as production.

    discharge_pct approximates the legacy field's meaning — how much of the
    installed bank cycles on a normal day — from the static model's own
    numbers: served load / installed capacity for off-grid,
    served_night_kwh / installed capacity for hybrid.
    """
    from calculations.sizing_off_grid import check_split_phase

    array = r["array"]
    pv = r["pv"]
    b = r["battery"]
    total_kwh_installed = b.get("total_kwh_installed", 0)
    daily_generation_kwh = pv.get("avg_month_daily_generation_kwh", 0)

    if system_type == "off_grid":
        discharge_pct = (
            round(daily_kwh_consumption / total_kwh_installed * 100, 2) if total_kwh_installed else 0.0
        )
    else:
        discharge_pct = (
            round(b.get("served_night_kwh", 0) / total_kwh_installed * 100, 2) if total_kwh_installed else 0.0
        )

    split_phase = check_split_phase(inverter, consumption.get("voltage_v", 120))
    hybrid_savings = _compute_hybrid_savings(consumption, daily_generation_kwh)

    return {
        "panel_id": panel["id"], "panel": panel,
        "inverter_id": inverter["id"], "inverter": inverter,
        "battery_id": battery["id"], "battery": battery,
        "charge_controller_id": cc["id"], "charge_controller": cc,
        "charge_controller_qty": array.get("charge_controller_qty", 1),
        "inverter_qty": inverter_qty,
        "monitoring_id": monitoring["id"] if monitoring else None, "monitoring": monitoring,
        "panels_per_string": array.get("panels_per_string"),
        "n_strings": array.get("strings"),
        "panel_count": array.get("total_panels", 0),
        "array_scenario": r["scenario"],
        "array_scenarios": None,
        "array": {
            "array_kw": array.get("system_kw", 0),
            "panel_count": array.get("total_panels", 0),
            "area_m2": array.get("area_m2", 0),
            "daily_generation_kwh": daily_generation_kwh,
        },
        "battery_bank": {**b, "discharge_pct": discharge_pct},
        "split_phase": split_phase,
        "hybrid_savings": hybrid_savings,
        "static_model_tier": r["scenario"],
    }


def _manual_to_wizard_equipment(
    combo: dict, mp: dict, panel: dict, inverter: dict, battery: dict, cc: dict,
    inverter_qty: int, consumption: dict, monitoring: dict | None = None,
) -> dict:
    """Same shape as _to_wizard_equipment(), built from a free-form manual
    array combo (calculations.mppt.check_charge_controller_design_multi())
    and its projection (off_grid._og_scenario_projection()) instead of a
    tier result — the static model has no tier concept in manual mode,
    matching production's own manual mode exactly."""
    from calculations.sizing_off_grid import check_split_phase

    split_phase = check_split_phase(inverter, consumption.get("voltage_v", 120))
    hybrid_savings = _compute_hybrid_savings(consumption, mp["daily_generation"])
    total_kwh_installed = mp["battery_kwh"]
    # Matches production's own manual-mode discharge_pct exactly: generation
    # / installed capacity (not consumption / installed, unlike the
    # tier-driven adapter above) — an existing inconsistency in production
    # between auto vs. manual discharge_pct semantics, replicated as-is
    # rather than silently "fixed" here.
    discharge_pct = (
        round(mp["daily_generation"] / total_kwh_installed * 100, 2) if total_kwh_installed else 0.0
    )

    return {
        "panel_id": panel["id"], "panel": panel,
        "inverter_id": inverter["id"], "inverter": inverter,
        "battery_id": battery["id"], "battery": battery,
        "charge_controller_id": cc["id"], "charge_controller": cc,
        "charge_controller_qty": combo.get("charge_controller_qty", 1),
        "inverter_qty": inverter_qty,
        "monitoring_id": monitoring["id"] if monitoring else None, "monitoring": monitoring,
        "panels_per_string": combo.get("panels_per_string"),
        "n_strings": combo.get("strings"),
        "panel_count": combo.get("total_panels", 0),
        "array_scenario": "M",
        "array_scenarios": None,
        "array": {
            "array_kw": combo.get("system_kw", 0),
            "panel_count": combo.get("total_panels", 0),
            "area_m2": combo.get("area_m2", 0),
            "daily_generation_kwh": mp["daily_generation"],
        },
        "battery_bank": {
            "battery_count": mp["battery_count"],
            "total_kwh_installed": mp["battery_kwh"],
            "discharge_pct": discharge_pct,
            "utilization_pct": mp.get("utilization_pct"),
        },
        "split_phase": split_phase,
        "hybrid_savings": hybrid_savings,
        "static_model_tier": "M",
    }


def _tier_card(
    r: dict, system_type: str, is_active: bool, final_inv: dict,
    hybrid_savings: dict | None, verification: dict | None, growth: dict | None,
) -> None:
    """One compact emoji card per tier — click selects it (does NOT commit
    wizard_equipment; the bottom 'Siguiente ->' does that for whichever
    design is active, tier or manual)."""
    if "error" in r:
        st.markdown(
            f'<div style="border:1.5px solid #dc2626;border-radius:8px;padding:0.9rem 1.1rem;'
            f'margin-bottom:0.75rem;"><b>Escenario {r["scenario"]}</b></div>',
            unsafe_allow_html=True,
        )
        st.error(r["error"])
        return

    array = r["array"]
    b = r["battery"]
    pv = r["pv"]
    is_valid = bool(r.get("within_limits"))
    ok_tag = "✅" if is_valid else "⚠️"

    btn_label = f"{'●' if is_active else '○'} Escenario {r['scenario']} — {array['total_panels']} paneles ({array['system_kw']} kW)"
    if st.button(btn_label, key=f"tds_sel_{r['scenario']}", use_container_width=True):
        st.session_state["tds_selected_scenario"] = r["scenario"]
        st.session_state["tds_use_manual"] = False
        st.rerun()

    lines = [f'{ok_tag} <b>{r["label"]}</b>']
    lines.append(f'🔢 Paneles: <b>{array["total_panels"]}</b> ({array["panels_per_string"]}×{array["strings"]})')
    inv_note = ' <span style="color:#1d4ed8;">(auto)</span>' if final_inv["bumped"] else ""
    lines.append(
        f'🔌 Inversores: <b>{final_inv["qty"]}</b>{inv_note} — carga {final_inv["loading_pct"]}% '
        f'({"OK" if final_inv["within_target"] else "excede objetivo"})'
    )
    lines.append(f'🎛️ Controladores: <b>{array.get("charge_controller_qty", 1)}</b>')
    if system_type == "off_grid":
        lines.append(
            f'🔋 Baterías: <b>{b["battery_count"]}</b> ({b["total_kwh_installed"]} kWh) — '
            f'reserva {b["reserve_soc_pct"]}%, autonomía {b["autonomy_days"]}d'
        )
    else:
        lines.append(
            f'🔋 Baterías: <b>{b["battery_count"]}</b> ({b["total_kwh_installed"]} kWh) — '
            f'reserva {b["reserve_soc_pct"]}%, respaldo {b["backup_nights"]} noche(s)'
        )
    lines.append(
        f'☀️ Generación: <b>{pv.get("avg_month_daily_generation_kwh")} kWh/día</b> · '
        f'cobertura <b>{pv.get("pv_coverage_actual")}×</b>'
    )
    if hybrid_savings:
        lines.append(f'💰 Reducción de factura: <b>~{hybrid_savings["savings_pct"]:.0f}%</b>')
    if verification is not None:
        v_icon = "✅" if verification["status"] == "green" else ("⚠️" if verification["status"] == "yellow" else "❌")
        lines.append(
            f'{v_icon} Verificación diaria: {_STATUS_LABELS_ES.get(verification["status"])} · '
            f'SoC mín {verification["minimum_soc_pct"]}%'
        )
    if growth is not None and (growth["additional_battery_units_needed"] or growth["additional_inverter_qty_needed"]):
        lines.append(
            f'🌱 Crecimiento (+{growth["growth_energy_pct"]}%): '
            f'+{growth["additional_battery_units_needed"]} batería(s), '
            f'+{growth["additional_inverter_qty_needed"]} inversor(es)'
        )

    warn_lines = []
    if b.get("tier_inversion_warning"):
        warn_lines.append("⚠️ Requiere más batería que el nivel anterior — revisa la batería seleccionada.")
    if b.get("backup_infeasible_with_this_battery"):
        warn_lines.append("⚠️ Reserva por debajo del DoD máximo — el respaldo no puede calcularse con esta batería.")
    if system_type == "off_grid":
        if pv.get("worst_month_load_coverage") is not None and not pv.get("worst_month_covers_load"):
            warn_lines.append("⚠️ No cubre el consumo en el mes más débil.")
    else:
        if pv.get("recharge_headroom") is not None and not pv.get("recharge_ok"):
            warn_lines.append("⚠️ Margen de recarga insuficiente.")
        if pv.get("pv_surplus_warning"):
            warn_lines.append("⚠️ FV supera lo que el sitio puede absorber sin exportar excedentes.")

    border = BRAND_GREEN if is_active else "#d1d5db"
    bg = BRAND_GREEN_LIGHT if is_active else "#f9fafb"
    warn_html = (
        "<br>" + "<br>".join(f'<span style="color:#92400e;font-size:0.75rem;">{w}</span>' for w in warn_lines)
        if warn_lines else ""
    )
    st.markdown(
        f'<div style="border:2px solid {border};border-radius:8px;padding:0.65rem 0.8rem;'
        f'background:{bg};font-size:0.82rem;line-height:1.9;">'
        + "<br>".join(lines) + warn_html +
        '</div>',
        unsafe_allow_html=True,
    )


def step6_equipment_static() -> dict | None:
    st.markdown("### Paso 6 (TEST) — Equipos, modelo estático")
    from wizard.common import inject_step6_heading_css
    inject_step6_heading_css()
    st.caption(
        "Motor de diseño estático (niveles fijos, sin búsqueda iterativa de confiabilidad). "
        "Esta página no guarda nada en la base de datos."
    )

    system_type = st.session_state.get("wizard_meta", {}).get("system_type", "off_grid")
    consumption = st.session_state.get("wizard_consumption", {})
    site = st.session_state.get("wizard_site", {})
    monthly_kwh_kwp = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp") or []
    daily_kwh_kwp = (site.get("pvgis_daily") or {}).get("daily_kwh_kwp") or []

    if not monthly_kwh_kwp:
        st.warning("No hay datos de irradiancia PVGIS para este sitio — vuelve al Paso 3.")
        return None
    if not consumption.get("profile"):
        st.warning("No hay perfil de demanda calculado — vuelve al Paso 5.")
        return None

    # Same fetch-if-missing fallback production's Step 6 has: the real daily
    # PVGIS series (for the day-by-day sim behind "Aprovechamiento solar" /
    # "Cobertura mensual") isn't fetched by Step 3, only lazily here — an
    # older draft, or one that never visited the real Step 6, won't have it
    # cached on wizard_site yet.
    if not daily_kwh_kwp and site.get("lat") and site.get("lon"):
        try:
            from calculations.pvgis import fetch_daily_series
            pvgis_daily = fetch_daily_series(site["lat"], site["lon"])
            daily_kwh_kwp = pvgis_daily.get("daily_kwh_kwp", [])
            site = {**site, "pvgis_daily": pvgis_daily}
            st.session_state["wizard_site"] = site
        except Exception:
            pass

    from database.equipment_db import (
        list_panels, list_inverters, list_batteries, list_charge_controllers, list_monitoring_devices,
    )
    from calculations.load_profile_off_grid import compute_demand_load

    try:
        panels = list_panels()
        inverters = [i for i in list_inverters() if i.get("type") == "hybrid"]
        batteries = list_batteries()
        charge_controllers = list_charge_controllers()
        monitoring_devices = list_monitoring_devices()
    except Exception as e:
        st.error(f"Error cargando catálogo: {e}")
        return None

    if not (panels and inverters and batteries and charge_controllers):
        st.warning("Faltan equipos en el catálogo (panel, inversor híbrido, batería o controlador de carga).")
        return None

    panel_options = {f"{p['brand']} {p['model']} — {p['wp']}W": p for p in panels}
    inverter_options = {f"{i['brand']} {i['model']} — {i['kw']} kW": i for i in inverters}
    battery_options = {f"{b['brand']} {b['model']} — {b['capacity_kwh']} kWh": b for b in batteries}
    cc_options = {f"{c['brand']} {c['model']} — {c['vin_max']:.0f}V/{c['imax_in']:.0f}A": c for c in charge_controllers}
    monitoring_options = {"— Sin monitoreo —": None} | {
        f"{m['brand']} {m['model']}": m for m in monitoring_devices
    }

    st.markdown("#### Selección de equipos")
    row1_col1, row1_col2 = st.columns(2)
    with row1_col1:
        panel = panel_options[st.selectbox("Panel solar *", list(panel_options.keys()), key="tds_panel")]
        panel_area = round(float(panel.get("width_m") or 0) * float(panel.get("height_m") or 0), 2)
        off_grid._spec_card(f"{panel['brand']} {panel['model']}", [
            f"Potencia: {panel['wp']} W", f"Voc: {panel['voc']} V", f"Vmp: {panel['vmp']} V",
            f"Isc: {panel['isc']} A", f"Imp: {panel['imp']} A", f"Área: {panel_area} m²",
        ])
    with row1_col2:
        inverter = inverter_options[st.selectbox("Inversor/cargador *", list(inverter_options.keys()), key="tds_inv")]
        off_grid._spec_card(f"{inverter['brand']} {inverter['model']}", [
            f"Potencia: {inverter['kw']} kW", f"Voltaje de salida: {inverter.get('output_v', '—')} V",
            f"Corriente AC salida: {inverter.get('ac_output_current_a') or '— (estimada de kW/V)'} A",
            f"Corriente AC entrada máx.: {inverter.get('ac_input_current_max_a') or '—'} A",
        ])
        from calculations.sizing_off_grid import check_split_phase
        split_phase = check_split_phase(inverter, consumption.get("voltage_v", 120))
        if split_phase["requires_split_phase"]:
            st.warning(f"⚠️ {split_phase['warning_message']}")

    row2_col1, row2_col2 = st.columns(2)
    with row2_col1:
        cc = cc_options[st.selectbox("Controlador de carga *", list(cc_options.keys()), key="tds_cc")]
        off_grid._spec_card(f"{cc['brand']} {cc['model']}", [
            f"Vin máx: {cc['vin_max']:.0f} V", f"Imax entrada: {cc['imax_in']:.0f} A",
            f"Imax salida: {cc.get('imax_out', '—')} A",
        ])
    with row2_col2:
        battery = battery_options[st.selectbox("Batería *", list(battery_options.keys()), key="tds_bat")]
        off_grid._spec_card(f"{battery['brand']} {battery['model']}", [
            f"Química: {battery.get('chemistry', '—')}", f"Capacidad: {battery['capacity_kwh']} kWh",
            f"Voltaje: {battery['voltage_v']} V", f"Descarga máxima (DoD): {battery.get('dod_pct', '—')}%",
        ])

    row3_col1, _row3_col2 = st.columns(2)
    with row3_col1:
        mon_label = st.selectbox("Monitoreo", list(monitoring_options.keys()), key="tds_mon")
        monitoring = monitoring_options[mon_label]
        if monitoring:
            off_grid._spec_card(f"{monitoring['brand']} {monitoring['model']}", [
                f"Compatible con: {monitoring.get('compatible_with', '—')}",
            ])

    base_inverter_qty = 2 if split_phase["requires_split_phase"] else 1

    # Reset scenario/manual selection when the equipment that the sizing
    # itself depends on changes — same idea as production's w6og_equip_key
    # reset, so a stale selection from a previous battery/panel/cc combo
    # doesn't silently carry over.
    equip_key = f"{panel['id']}_{cc['id']}_{battery['id']}_{inverter['id']}"
    if st.session_state.get("tds_equip_key") != equip_key:
        st.session_state["tds_equip_key"] = equip_key
        st.session_state.pop("tds_use_manual", None)
        st.session_state.pop("tds_selected_scenario", None)

    a, b_col = st.columns(2)
    night_pct = a.number_input(
        "Carga nocturna (% del día)", min_value=5, max_value=95, value=40, step=5,
        key="tds_night_pct",
        help="Porcentaje del consumo diario que ocurre entre 18:00 y 06:00 — es el "
             "dato que más pesa en el tamaño de la batería. El 40% por defecto es la "
             "mediana de 9 sitios monitoreados (rango real 17-54%). Ajustalo si el "
             "sitio tiene un perfil distinto (p. ej. un comercio diurno).",
    )
    exports = b_col.checkbox(
        "El sitio puede exportar excedentes", value=False, key="tds_exports",
        help="Si no exporta, el FV por encima de ~1.75× la carga no se aprovecha: "
             "con la batería llena y la carga cubierta el MPPT limita la producción.",
    )

    st.divider()

    if system_type == "off_grid":
        daily_kwh_consumption = consumption.get("daily_kwh", 0.0)
        demand = compute_demand_load(consumption["profile"]["lines"])
        peak_demand_kw = demand["total_demand_kw"]

        from calculations.sizing_off_grid import (
            generate_design_scenarios, run_daily_energy_balance_check, assess_growth_readiness,
        )
        results = generate_design_scenarios(
            panel, cc, battery, inverter,
            daily_kwh_consumption=daily_kwh_consumption,
            peak_demand_kw=peak_demand_kw,
            monthly_kwh_kwp=monthly_kwh_kwp,
            inverter_qty=base_inverter_qty,
        )

        verifications, growths = {}, {}
        for r in results:
            if "error" in r:
                continue
            if daily_kwh_kwp:
                gen = [v * r["array"]["system_kw"] for v in daily_kwh_kwp]
                verifications[r["scenario"]] = run_daily_energy_balance_check(
                    gen, daily_kwh_consumption, r["battery"]["total_kwh_installed"],
                    battery["dod_pct"], r["battery"]["reserve_soc_pct"],
                )
            growths[r["scenario"]] = assess_growth_readiness(
                r, battery["capacity_kwh"], battery["dod_pct"], inverter["kw"],
                daily_kwh_consumption, peak_demand_kw,
            )
        critical_daily_kwh = daily_kwh_consumption  # unified name used below
    else:
        critical_daily_kwh = consumption.get("daily_kwh_diversified", consumption.get("daily_kwh", 0.0))
        demand = compute_demand_load(consumption["profile"]["lines"])
        critical_peak_kw = demand["total_demand_kw"]

        main_panel = consumption.get("main_panel") or {}
        main_panel_daily_kwh = (
            main_panel.get("avg_kwh_month_diversified", main_panel.get("avg_kwh_month")) or 0.0
        ) / 30.4
        main_panel_approx = False
        if main_panel.get("mode") == "loads" and main_panel.get("profile"):
            mp_demand = compute_demand_load(main_panel["profile"]["lines"])
            main_panel_peak_kw = mp_demand["total_demand_kw"]
        else:
            main_panel_peak_kw = (main_panel_daily_kwh / 24.0) * 3.0
            main_panel_approx = True

        whole_home_daily_kwh = critical_daily_kwh + main_panel_daily_kwh
        whole_home_peak_kw = critical_peak_kw + main_panel_peak_kw

        if main_panel_approx:
            st.caption(
                "Tablero principal en modo factura: pico estimado como 3x el promedio horario "
                "(no hay cargas individuales) — usar con precaución para el chequeo del inversor en red."
            )

        from calculations.sizing_off_grid import (
            generate_design_scenarios_hybrid, run_daily_energy_balance_check, assess_growth_readiness_hybrid,
        )
        results = generate_design_scenarios_hybrid(
            panel, cc, battery, inverter,
            critical_daily_kwh=critical_daily_kwh,
            critical_peak_kw=critical_peak_kw,
            whole_home_daily_kwh=whole_home_daily_kwh,
            whole_home_peak_kw=whole_home_peak_kw,
            monthly_kwh_kwp=monthly_kwh_kwp,
            inverter_qty=base_inverter_qty,
            night_load_fraction=night_pct / 100.0,
            site_exports_to_grid=exports,
        )

        verifications, growths = {}, {}
        for r in results:
            if "error" in r:
                continue
            if daily_kwh_kwp:
                gen = [v * r["array"]["system_kw"] for v in daily_kwh_kwp]
                verifications[r["scenario"]] = run_daily_energy_balance_check(
                    gen, critical_daily_kwh, r["battery"]["total_kwh_installed"],
                    battery["dod_pct"], r["battery"]["reserve_soc_pct"],
                )
            growths[r["scenario"]] = assess_growth_readiness_hybrid(
                r, battery["capacity_kwh"], battery["dod_pct"], inverter["kw"],
                critical_daily_kwh, critical_peak_kw,
            )

    served_load_daily_kwh = critical_daily_kwh
    avg_peak_sun_hours = (sum(monthly_kwh_kwp) / 12 / 30.4) if monthly_kwh_kwp else 4.5
    valid_results = {r["scenario"]: r for r in results if "error" not in r}
    using_manual = st.session_state.get("tds_use_manual", False)
    selected_scenario = st.session_state.get("tds_selected_scenario", "2")
    if selected_scenario not in valid_results and valid_results:
        selected_scenario = next(iter(valid_results))

    # ── Opción 1 — Escenarios automáticos ────────────────────────────────
    st.markdown("#### Opción 1 — Escenarios automáticos")
    st.caption(
        "Cada nivel fija reserva de SoC, cobertura FV y (híbrido) noches de respaldo por política "
        "de diseño, calibrada contra datos reales de flota — no una búsqueda iterativa. Clic en una "
        "tarjeta para activarla; 'Siguiente' abajo confirma la activa (tarjeta o manual)."
    )
    cols = st.columns(3)
    for col, r in zip(cols, results):
        with col:
            if "error" in r:
                _tier_card(r, system_type, False, {"qty": 0, "loading_pct": 0, "loading_target_pct": 0, "within_target": False, "bumped": False}, None, None, None)
                continue
            final_inv = _final_inverter_qty(r, system_type, base_inverter_qty)
            hybrid_savings_card = _compute_hybrid_savings(consumption, r["pv"].get("avg_month_daily_generation_kwh", 0))
            is_active = (not using_manual) and (r["scenario"] == selected_scenario)
            _tier_card(
                r, system_type, is_active, final_inv, hybrid_savings_card,
                verifications.get(r["scenario"]), growths.get(r["scenario"]),
            )

    # ── Opción 2 — Configuración manual ──────────────────────────────────
    st.divider()
    st.markdown("#### Opción 2 — Configuración manual")
    st.caption("Ajusta los parámetros libremente, sin las reglas de nivel — se valida contra los límites del controlador en tiempo real.")

    from calculations.mppt import check_charge_controller_design_multi

    default_t2 = valid_results.get("2") or next(iter(valid_results.values()), None)
    default_series = default_t2["array"]["panels_per_string"] if default_t2 else 1
    default_strings = default_t2["array"]["strings"] if default_t2 else 1
    default_battery_count = default_t2["battery"]["battery_count"] if default_t2 else 1

    m = None
    mp = None
    m_col1, m_col2 = st.columns(2)
    with m_col1:
        m_series = st.number_input("Paneles en serie (por string)", min_value=1, max_value=50,
                                    value=default_series, step=1, key="tds_m_series")
        m_strings = st.number_input("Strings en paralelo (total)", min_value=1, max_value=50,
                                     value=default_strings, step=1, key="tds_m_strings")
        m_battery_count = st.number_input(
            "Cantidad de baterías", min_value=1, max_value=50,
            value=default_battery_count, step=1, key="tds_m_battery_count",
        )
        m = check_charge_controller_design_multi(panel, cc, m_series, m_strings, off_grid._MAX_CHARGE_CONTROLLERS)
        if m is None:
            st.markdown(
                '<div style="background:#fef2f2;border-left:4px solid #dc2626;border-radius:6px;'
                'padding:0.5rem 0.8rem;font-size:0.83rem;">'
                f'❌ Esta combinación excede {off_grid._MAX_CHARGE_CONTROLLERS} controladores en paralelo — reduce los strings.</div>',
                unsafe_allow_html=True,
            )
        else:
            off_grid._chip_row([
                f"🔢 <b>{m['total_panels']}</b> paneles", f"⚡ <b>{m['system_kw']} kW</b>",
                f"📐 <b>{m['area_m2']} m²</b>", f"🎛️ <b>{m['charge_controller_qty']}</b> controlador(es)",
                f"Voc <b>{m['voc_total']} V</b>", f"Corriente <b>{m['imp_total']} A</b>",
            ])
            imp_limit_m = cc["imax_in"] * m["charge_controller_qty"]
            off_grid._param_row("Voc total", f"{m['voc_total']} V", m["voc_total"] <= cc["vin_max"], f"≤ {cc['vin_max']:.0f} V")
            off_grid._param_row(
                "Corriente total", f"{m['imp_total']} A", m["imp_total"] <= imp_limit_m,
                f"≤ {imp_limit_m:.0f} A" + (f" ({m['charge_controller_qty']}×{cc['imax_in']:.0f}A)" if m["charge_controller_qty"] > 1 else ""),
            )

    with m_col2:
        if m is not None:
            if m["within_limits"]:
                btn_label = f"{'●' if using_manual else '○'} Usar configuración manual — {m['total_panels']} paneles ({m['system_kw']} kW)"
                if st.button(btn_label, key="tds_manual_on", use_container_width=True):
                    st.session_state["tds_use_manual"] = True
                    st.rerun()
            else:
                st.markdown(
                    '<div style="font-size:0.8rem;color:#9ca3af;padding:0.3rem 0;">'
                    '⚠️ Configuración manual — corrige los errores en rojo para poder seleccionarla</div>',
                    unsafe_allow_html=True,
                )

            mp = off_grid._og_scenario_projection(
                m, avg_peak_sun_hours, served_load_daily_kwh, 0, battery.get("dod_pct", 80),
                battery["voltage_v"], battery["capacity_kwh"],
                daily_kwh_kwp=daily_kwh_kwp, battery_count_override=m_battery_count,
            )
            m_hybrid_savings = _compute_hybrid_savings(consumption, mp["daily_generation"])
            m_cover_line = (
                '<span style="color:#166534;">✅ Cubre el consumo diario</span>' if mp["covers"] else
                '<span style="color:#92400e;">⚠️ No cubre el consumo diario</span>'
            )
            m_lines = [
                f'☀️ Generación: <b>{mp["daily_generation"]:.2f} kWh/día</b>',
                f'🔢 Paneles: <b>{m["total_panels"]}</b> ({m["panels_per_string"]}×{m["strings"]})',
                f'🔌 Inversores: <b>{base_inverter_qty}</b>',
                f'🎛️ Controladores: <b>{m["charge_controller_qty"]}</b>',
                f'🔋 Baterías: <b>{mp["battery_count"]}</b> ({mp["battery_kwh"]:.1f} kWh)',
                m_cover_line,
            ]
            if mp.get("utilization_pct") is not None:
                m_lines.append(f'☀️ Aprovechamiento solar: <b>{mp["utilization_pct"]:.0f}%</b>')
            if m_hybrid_savings:
                m_lines.append(f'💰 Reducción de factura: <b>~{m_hybrid_savings["savings_pct"]:.0f}%</b>')
            m_border = "#6366f1" if using_manual else "#d1d5db"
            m_bg = "#f5f3ff" if using_manual else "#f9fafb"
            st.markdown(
                f'<div style="border:2px solid {m_border};border-radius:8px;padding:0.65rem 0.8rem;'
                f'background:{m_bg};font-size:0.82rem;line-height:1.9;">' + "<br>".join(m_lines) + '</div>',
                unsafe_allow_html=True,
            )

    # ── Resolve the active configuration ─────────────────────────────────
    chosen_equipment = None
    chosen_array = None
    chosen_label = None
    if using_manual and m is not None and m["within_limits"] and mp is not None:
        chosen_equipment = _manual_to_wizard_equipment(
            m, mp, panel, inverter, battery, cc, base_inverter_qty, consumption, monitoring=monitoring,
        )
        chosen_array = m
        chosen_label = "Configuración manual"
        chosen_is_valid = m["within_limits"]
    elif selected_scenario in valid_results:
        r_sel = valid_results[selected_scenario]
        final_inv_sel = _final_inverter_qty(r_sel, system_type, base_inverter_qty)
        chosen_equipment = _to_wizard_equipment(
            r_sel, system_type, panel, inverter, battery, cc, final_inv_sel["qty"],
            consumption, served_load_daily_kwh, monitoring=monitoring,
        )
        chosen_array = r_sel["array"]
        chosen_label = f"Escenario {r_sel['scenario']} · {r_sel['label']}"
        chosen_is_valid = bool(r_sel.get("within_limits"))
    else:
        chosen_is_valid = False

    # ── Validación del diseño ─────────────────────────────────────────────
    st.divider()
    st.markdown("#### Validación del diseño")
    if chosen_equipment is None:
        st.error("No hay una configuración seleccionada. Elige un escenario arriba o activa la configuración manual.")
    else:
        st.caption(f"Configuración activa: {chosen_label}")
        banner_status = "ok" if chosen_is_valid else "fail"
        style = off_grid._CHECK_STATUS_STYLE[banner_status]
        st.markdown(
            f'<div style="background:{style["bg"]};border-left:4px solid {style["border"]};'
            f'border-radius:6px;padding:0.6rem 0.9rem;margin-bottom:0.6rem;font-weight:700;'
            f'color:{BRAND_NAVY};">{style["icon"]} {"Configuración válida" if chosen_is_valid else "Configuración inválida"}</div>',
            unsafe_allow_html=True,
        )
        if using_manual:
            st.caption("Configuración manual — límites eléctricos (Voc/corriente) verificados en 'Opción 2' arriba.")
        else:
            r_sel = valid_results[selected_scenario]
            pv_sel = r_sel["pv"]
            b_sel = r_sel["battery"]
            off_grid._param_row(
                "Cobertura del objetivo PV", f"{pv_sel.get('pv_coverage_actual')}×",
                bool(pv_sel.get("meets_target_daily_kwh")), f"≥ {pv_sel.get('pv_coverage_target')}× objetivo",
            )
            if system_type == "off_grid":
                cov = pv_sel.get("worst_month_load_coverage")
                if cov is not None:
                    off_grid._param_row("Mes más débil vs. consumo", f"{cov}×", bool(pv_sel.get("worst_month_covers_load")), "≥ 1.0×")
            else:
                hr = pv_sel.get("recharge_headroom")
                if hr is not None:
                    off_grid._param_row("Margen de recarga", f"{hr}×", bool(pv_sel.get("recharge_ok")), "≥ 1.0×")
                if pv_sel.get("pv_surplus_warning"):
                    off_grid._param_row("Cobertura FV (sin exportar)", f"{pv_sel.get('pv_coverage_actual')}×", False, "≤ 1.75×")
            off_grid._param_row(
                "Orden de niveles (batería)", "creciente" if not b_sel.get("tier_inversion_warning") else "invertido",
                not b_sel.get("tier_inversion_warning", False), "creciente con el nivel",
            )
            if system_type != "off_grid" and b_sel.get("backup_infeasible_with_this_battery"):
                off_grid._param_row("Respaldo calculable", "no", False, "reserva > piso DoD de la batería")

        if chosen_array is not None:
            st.markdown("##### Margen de diseño")
            st.caption(
                "Qué tan cerca está el diseño de sus límites eléctricos — del **controlador de carga** "
                "(Voc, corriente) y de la **batería** (profundidad de descarga)."
            )
            cc_qty_chosen = chosen_array.get("charge_controller_qty", 1)
            imp_limit_chosen = cc["imax_in"] * cc_qty_chosen
            dod_pct_chosen = battery.get("dod_pct", 80) or 80
            discharge_pct_chosen = chosen_equipment["battery_bank"]["discharge_pct"]

            def _margin_pct_color(pct: float) -> str:
                if pct > 95:
                    return "#dc2626"
                if pct > 80:
                    return "#b45309"
                return BRAND_GREEN

            import plotly.graph_objects as go
            margin_items = [
                ("Voc del arreglo (vs. controlador)", (chosen_array["voc_total"] / cc["vin_max"] * 100) if cc["vin_max"] else 0),
                ("Corriente del arreglo (vs. controlador)", (chosen_array["imp_total"] / imp_limit_chosen * 100) if imp_limit_chosen else 0),
                ("Profundidad de descarga (vs. batería)", (discharge_pct_chosen / dod_pct_chosen * 100) if dod_pct_chosen else 0),
            ]
            margin_fig = go.Figure(go.Bar(
                x=[v for _, v in margin_items], y=[k for k, _ in margin_items], orientation="h",
                marker_color=[_margin_pct_color(v) for _, v in margin_items],
                text=[f"{v:.0f}%" for _, v in margin_items], textposition="outside",
            ))
            margin_fig.add_vline(x=100, line_dash="dash", line_color="#9ca3af")
            margin_fig.update_layout(
                xaxis=dict(title="% del límite", range=[0, max(110, max(v for _, v in margin_items) * 1.15)]),
                height=200, margin=dict(t=10, b=10, l=10, r=30),
            )
            st.plotly_chart(margin_fig, use_container_width=True)
            st.caption("Verde: margen cómodo (<80% del límite). Ámbar: 80–95%. Rojo: >95%, revisar diseño.")

    # ── Resumen eléctrico — carga y protecciones ─────────────────────────
    st.divider()
    st.markdown("#### Resumen eléctrico — carga y protecciones")
    profile = consumption.get("profile") or {}
    if profile.get("lines") and chosen_equipment is not None:
        from calculations.sizing_off_grid import compute_ac_breaker_summary
        demand2 = compute_demand_load(profile["lines"])
        design_voltage_v = 240.0 if chosen_equipment["split_phase"]["requires_split_phase"] else float(consumption.get("voltage_v", 120))
        ac_summary = compute_ac_breaker_summary(
            demand2["total_demand_kw"], design_voltage_v, inverter, chosen_equipment["inverter_qty"],
            grid_connected=bool(consumption.get("grid_connected")),
        )
        ac_out = ac_summary["ac_out"]
        ac_in = ac_summary["ac_in"]
        # NOT ac_out["available_current_a"] * design_voltage_v: that current is
        # the inverter's own rated output current AT ITS OWN output_v (e.g.
        # 41.67A @ 120V = 5kW/unit) with inverter_qty already multiplied in —
        # re-multiplying by design_voltage_v (240V for a split-phase service)
        # double-counts the qty and reports 2x the real available power (a
        # 2x5kW split-phase pair showed 20kW instead of 10kW). Nameplate kW
        # x qty is unambiguous regardless of parallel-same-phase vs.
        # split-phase master/slave topology, unlike the current figure.
        available_power_kw = float(inverter.get("kw") or 0) * chosen_equipment["inverter_qty"]
        off_grid._chip_row([
            f"🏗️ Instalada: <b>{demand2['total_installed_kw']:.2f} kW</b>",
            f"📊 Demandada: <b>{demand2['total_demand_kw']:.2f} kW</b> ({demand2['blended_factor'] * 100:.0f}%)",
            f"🔌 Disponible inversor: <b>{available_power_kw:.2f} kW</b>"
            + (" (estimado)" if ac_out["available_current_estimated"] else ""),
            f"⚡ Corriente pico: <b>{ac_summary['peak_current_a']:.1f} A</b>",
        ])

        breaker_cols = st.columns(2) if ac_in else st.columns(1)
        with breaker_cols[0]:
            out_border = "#dc2626" if ac_out["exceeds_available"] else "#d1d5db"
            st.markdown(
                f'<div style="border:2px solid {out_border};border-radius:8px;padding:0.65rem 0.8rem;'
                f'background:#f9fafb;font-size:0.82rem;line-height:1.9;">'
                f'<div style="font-weight:700;font-size:0.88rem;color:{BRAND_NAVY};">AC Out — salida del inversor</div>'
                f'Corriente de diseño: <b>{ac_out["design_current_a"]:.1f} A</b> (demanda × 1.25)<br>'
                f'Breaker sugerido (2 polos): <b>{ac_out["breaker_a"] or "fuera de rango (>200A)"} A</b><br>'
                f'{"⚠️" if ac_out["exceeds_available"] else "✅"} Disponible del inversor: <b>{ac_out["available_current_a"]:.1f} A</b>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if ac_out["exceeds_available"]:
                st.warning("⚠️ La corriente demandada supera lo que el inversor seleccionado puede entregar.")
        if ac_in:
            with breaker_cols[1]:
                st.markdown(
                    f'<div style="border:2px solid #d1d5db;border-radius:8px;padding:0.65rem 0.8rem;'
                    f'background:#f9fafb;font-size:0.82rem;line-height:1.9;">'
                    f'<div style="font-weight:700;font-size:0.88rem;color:{BRAND_NAVY};">AC In — passthrough (red)</div>'
                    f'Corriente máx. passthrough: <b>{ac_in["design_current_a"]:.1f} A</b><br>'
                    f'Breaker sugerido (2 polos): <b>{ac_in["breaker_a"] or "fuera de rango (>200A)"} A</b>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        elif bool(consumption.get("grid_connected")):
            st.info("ℹ️ Este inversor no tiene registrada su corriente máxima de passthrough AC.")
    else:
        st.info("No hay líneas de carga del Paso 4/5, o no hay una configuración activa, para calcular la demanda eléctrica.")

    # ── Dimensionamiento calculado ────────────────────────────────────────
    st.divider()
    st.markdown("#### Dimensionamiento calculado")
    if chosen_equipment is not None:
        st.caption(f"Configuración activa: {chosen_label}")
        arr = chosen_equipment["array"]
        bb = chosen_equipment["battery_bank"]
        panel_arrangement = f"{chosen_equipment['panels_per_string']} en serie × {chosen_equipment['n_strings']} en paralelo"
        inverter_arrangement = "Split-phase 120/240V" if chosen_equipment["split_phase"]["requires_split_phase"] else f"{consumption.get('voltage_v', 120):.0f}V"
        off_grid._chip_row([
            f"🔢 <b>{arr['panel_count']}</b> paneles", f"🔀 <b>{panel_arrangement}</b>",
            f"⚡ <b>{arr['array_kw']} kW</b>", f"📐 <b>{arr['area_m2']} m²</b>",
            f"🔌 <b>{chosen_equipment['inverter_qty']}</b> inversor(es) ({inverter_arrangement})",
            f"🎛️ <b>{chosen_equipment['charge_controller_qty']}</b> controlador(es)",
            f"🔋 <b>{bb['battery_count']}</b> baterías",
        ])
        i1, i2 = st.columns(2)
        with i1:
            off_grid._metric_card("Generación diaria", f"{arr['daily_generation_kwh']} kWh/día")
        with i2:
            off_grid._metric_card("Capacidad del banco", f"{bb['total_kwh_installed']} kWh")

        # ── Estadísticas ───────────────────────────────────────────────
        if arr["daily_generation_kwh"] > 0:
            st.markdown("##### Generación vs. consumo")
            display_daily_generation = arr["daily_generation_kwh"]
            margin_kwh_gen = round(max(0, display_daily_generation - served_load_daily_kwh), 2)
            import plotly.graph_objects as go
            gen_fig = go.Figure(go.Bar(
                x=[display_daily_generation, served_load_daily_kwh, margin_kwh_gen],
                y=["Generación diaria", "Consumo diario", "Recarga de batería"],
                orientation="h", marker_color=[BRAND_GREEN, BRAND_NAVY, "#86efac"],
                text=[f"{display_daily_generation:.2f} kWh/día", f"{served_load_daily_kwh:.2f} kWh/día", f"{margin_kwh_gen:.2f} kWh/día"],
                textposition="outside",
            ))
            gen_fig.update_layout(
                xaxis=dict(title="kWh/día", range=[0, max(display_daily_generation, served_load_daily_kwh, margin_kwh_gen) * 1.3 or 1]),
                height=200, margin=dict(t=10, b=10, l=10, r=10),
            )
            st.plotly_chart(gen_fig, use_container_width=True)

            step6_coverage, step6_sim = off_grid._og_monthly_coverage_and_sim(
                {"array_kw": arr["array_kw"]}, battery, bb, {"daily_kwh": served_load_daily_kwh}, site,
            )
            if step6_coverage:
                from wizard.common import monthly_coverage_chart
                st.markdown("##### Cobertura mensual estimada")
                st.plotly_chart(
                    monthly_coverage_chart(
                        step6_coverage.get("generation"), step6_coverage.get("consumption"),
                        recharge_kwh=step6_coverage.get("recharge"), flag_shortfall=True,
                    ),
                    use_container_width=True,
                )
            if step6_sim:
                is_hybrid_grid = bool(consumption.get("grid_connected"))
                st.markdown("##### Aprovechamiento de generación solar" + (" (banco de baterías)" if is_hybrid_grid else ""))
                util_pct = step6_sim["utilization_pct"]
                used_kwh = round(step6_sim["total_generation_kwh"] - step6_sim["curtailed_kwh"])
                curtailed_kwh = round(step6_sim["curtailed_kwh"])
                import plotly.graph_objects as go
                util_fig = go.Figure()
                util_fig.add_trace(go.Bar(
                    y=["Generación anual"], x=[used_kwh],
                    name="Batería/cargas críticas" if is_hybrid_grid else "Aprovechado",
                    orientation="h", marker_color=BRAND_GREEN,
                    text=[f"{util_pct:.0f}% · {used_kwh:,} kWh"], textposition="inside",
                ))
                util_fig.add_trace(go.Bar(
                    y=["Generación anual"], x=[curtailed_kwh],
                    name="Acoplado a red (ahorro)" if is_hybrid_grid else "Curtailed (no aprovechado)",
                    orientation="h", marker_color="#d1d5db",
                    text=[f"{100 - util_pct:.0f}% · {curtailed_kwh:,} kWh"], textposition="inside",
                ))
                util_fig.update_layout(
                    barmode="stack", height=170, margin=dict(t=45, b=10, l=10, r=10),
                    xaxis_title="kWh/año", showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.05),
                )
                st.plotly_chart(util_fig, use_container_width=True)

            # ── Flujo de energía (Sankey) ────────────────────────────────
            # Same base structure as production's off-grid Sankey (gross ->
            # losses + useful -> critical-load categories, rescaled to the
            # served daily load so the diagram stays internally consistent)
            # extended for hybrid with two more terminal flows: surplus that
            # AC-couples to the main panel (reuses the same
            # self_consumed_kwh_month _compute_hybrid_savings() already
            # produces for the card's own 💰 line -- not a new estimate) and
            # whatever's left over, treated as battery recharge -- same
            # energy-balance simplification production's off-grid Sankey
            # already uses for "Margen / recarga batería" (no hourly
            # dispatch model exists in this codebase to sequence it more
            # precisely). Every terminal node's label carries its share of
            # gross generation, per user request.
            profile_for_sankey = consumption.get("profile") or {}
            if profile_for_sankey and served_load_daily_kwh > 0:
                from calculations.load_profile_off_grid import CATEGORY_LABELS_ES

                raw_cat_kwh: dict[str, float] = {}
                for line in profile_for_sankey.get("lines", []):
                    raw_cat_kwh[line["category"]] = raw_cat_kwh.get(line["category"], 0) + line["estimated_kwh_day"]
                raw_total = sum(raw_cat_kwh.values())
                if raw_total > 0:
                    scale = served_load_daily_kwh / raw_total
                    cat_kwh = {k: round(v * scale, 3) for k, v in raw_cat_kwh.items()}

                    gross_kwh = round(arr["array_kw"] * avg_peak_sun_hours, 2)
                    losses_kwh = round(max(0, gross_kwh - display_daily_generation), 2)
                    margin_kwh = round(max(0, display_daily_generation - served_load_daily_kwh), 2)

                    st.markdown("##### Flujo de energía")
                    st.caption(
                        "De dónde sale la energía generada: pérdidas del sistema y el resto hacia cada "
                        "categoría de carga crítica" + (", hacia el tablero principal o hacia la batería."
                        if is_hybrid_grid else " o hacia la batería.") +
                        " Cada bloque muestra su parte de la generación bruta."
                    )

                    def _pct(kwh: float) -> str:
                        return f" — {round(kwh / gross_kwh * 100):.0f}%" if gross_kwh > 0 else ""

                    labels = ["Generación bruta", f"Pérdidas del sistema{_pct(losses_kwh)}", "Energía útil"]
                    node_colors = [BRAND_GREEN, "#9ca3af", BRAND_NAVY]
                    sources = [0, 0]
                    targets = [1, 2]
                    values = [losses_kwh, display_daily_generation]
                    link_colors = ["rgba(156,163,175,0.45)", "rgba(75,174,106,0.4)"]
                    for cat, kwh in sorted(cat_kwh.items(), key=lambda x: -x[1]):
                        if kwh <= 0:
                            continue
                        labels.append(f"{CATEGORY_LABELS_ES.get(cat, cat)}{_pct(kwh)}")
                        node_colors.append(off_grid._CATEGORY_CHART_COLORS.get(cat, "#9ca3af"))
                        sources.append(2)
                        targets.append(len(labels) - 1)
                        values.append(kwh)
                        link_colors.append("rgba(30,45,84,0.3)")

                    if is_hybrid_grid:
                        main_panel_offset_kwh = 0.0
                        hybrid_savings_sankey = _compute_hybrid_savings(consumption, display_daily_generation)
                        if hybrid_savings_sankey:
                            main_panel_offset_kwh = round(
                                min(margin_kwh, hybrid_savings_sankey["self_consumed_kwh_month"] / 30.4), 3,
                            )
                        if main_panel_offset_kwh > 0.01:
                            labels.append(f"Excedente → tablero principal (ahorro){_pct(main_panel_offset_kwh)}")
                            node_colors.append("#f59e0b")
                            sources.append(2)
                            targets.append(len(labels) - 1)
                            values.append(main_panel_offset_kwh)
                            link_colors.append("rgba(245,158,11,0.35)")
                        recharge_kwh = round(max(0, margin_kwh - main_panel_offset_kwh), 3)
                        if recharge_kwh > 0.01:
                            labels.append(f"Recarga de batería{_pct(recharge_kwh)}")
                            node_colors.append("#86efac")
                            sources.append(2)
                            targets.append(len(labels) - 1)
                            values.append(recharge_kwh)
                            link_colors.append("rgba(75,174,106,0.25)")
                    elif margin_kwh > 0.01:
                        labels.append(f"Margen / recarga batería{_pct(margin_kwh)}")
                        node_colors.append("#86efac")
                        sources.append(2)
                        targets.append(len(labels) - 1)
                        values.append(margin_kwh)
                        link_colors.append("rgba(75,174,106,0.25)")

                    import plotly.graph_objects as go
                    sankey_fig = go.Figure(go.Sankey(
                        node=dict(label=labels, color=node_colors, pad=20, thickness=16,
                                  line=dict(color="white", width=0.5)),
                        link=dict(source=sources, target=targets, value=values, color=link_colors),
                        textfont=dict(color=BRAND_NAVY, size=12, family="Arial, sans-serif"),
                    ))
                    sankey_fig.update_layout(height=340, margin=dict(t=10, b=10, l=10, r=10))
                    st.plotly_chart(sankey_fig, use_container_width=True)
                    if is_hybrid_grid:
                        st.caption(
                            "Aproximación de balance diario, no un despacho horario real: el excedente hacia "
                            "el tablero principal usa el mismo cálculo de la tarjeta de escenario (💰 "
                            "reducción de factura); lo que sobra después se trata como recarga de batería."
                        )

    st.divider()
    col_back, _, col_next = st.columns([1.6, 1.8, 1.6])
    with col_back:
        if st.button("← Atrás", key="tds_back"):
            st.session_state["wizard_step"] = 5
            st.rerun()
    with col_next:
        if st.button("Siguiente →", key="tds_next", type="primary", disabled=chosen_equipment is None):
            st.session_state["wizard_equipment"] = chosen_equipment
            return chosen_equipment

    return None
