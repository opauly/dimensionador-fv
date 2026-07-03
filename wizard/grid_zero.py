from __future__ import annotations
"""Wizard steps 4–8 for Grid Zero proposals. Phase 2."""
import pandas as pd
import streamlit as st

from config import BRAND_GREEN, BRAND_GREEN_LIGHT


# ── Step 4 — Utility account ─────────────────────────────────────────────────

def step4_utility() -> dict | None:
    """Distributor, NISE, tariff type selection. Returns utility dict."""
    st.markdown("### Paso 4 — Cuenta de distribuidora eléctrica")

    from database.tariffs_db import list_distributors, list_tariff_types

    current = st.session_state.get("wizard_utility", {})

    try:
        distributors = list_distributors()
    except Exception as e:
        st.error(f"No se pudo cargar distribuidoras: {e}")
        return None

    dist_options = {f"{d['abbreviation']} — {d['name']}": d for d in distributors}
    dist_labels = list(dist_options.keys())

    current_dist_abbrev = current.get("distributor_abbrev", "")
    default_dist_idx = next(
        (i for i, d in enumerate(distributors) if d["abbreviation"] == current_dist_abbrev),
        0,
    )

    col1, col2 = st.columns(2)
    with col1:
        dist_label = st.selectbox("Distribuidora *", dist_labels, index=default_dist_idx, key="w4_dist")
        selected_dist = dist_options[dist_label]

    with col2:
        nise = st.text_input("NISE (número de cliente)", value=current.get("nise", "N/A"), key="w4_nise")

    # Load tariff types for selected distributor
    try:
        tariff_types = list_tariff_types(selected_dist["id"])
    except Exception as e:
        st.error(f"No se pudo cargar tarifas: {e}")
        tariff_types = []

    selected_tariff = None
    if tariff_types:
        tariff_options = {f"{t['code']} — {t['name']}": t for t in tariff_types}
        current_code = current.get("tariff_code", tariff_types[0]["code"])
        default_tariff_idx = next(
            (i for i, t in enumerate(tariff_types) if t["code"] == current_code), 0
        )
        tariff_label = st.selectbox(
            "Tipo de tarifa *",
            list(tariff_options.keys()),
            index=default_tariff_idx,
            key="w4_tariff",
        )
        selected_tariff = tariff_options[tariff_label]

        st.caption(
            f"Cargo fijo: ₡{selected_tariff['access_charge_crc']:,.0f}/mes · "
            f"Bomberos: {selected_tariff['bomberos_pct']*100:.2f}% · "
            f"Umbral IVA: {selected_tariff['iva_threshold_kwh']} kWh"
        )
    else:
        st.warning("No hay tarifas registradas para esta distribuidora.")

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w4_back"):
            st.session_state["wizard_step"] = 3
            st.rerun()
    with col_next:
        can_continue = selected_tariff is not None
        if st.button("Siguiente →", key="w4_next", type="primary", disabled=not can_continue):
            result = {
                "distributor_id": selected_dist["id"],
                "distributor_name": selected_dist["name"],
                "distributor_abbrev": selected_dist["abbreviation"],
                "nise": nise.strip() or "N/A",
                "tariff_type_id": selected_tariff["id"],
                "tariff_code": selected_tariff["code"],
                "tariff_name": selected_tariff["name"],
            }
            st.session_state["wizard_utility"] = result
            return result

    return None


# ── Step 5 — Consumption ─────────────────────────────────────────────────────

_MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def step5_consumption() -> dict | None:
    """12-month kWh / bill table, manual entry. Returns consumption dict."""
    st.markdown("### Paso 5 — Historial de consumo eléctrico")

    current = st.session_state.get("wizard_consumption", {})
    saved_months = current.get("months_data", [])

    # Build default DataFrame
    if saved_months and len(saved_months) == 12:
        df_init = pd.DataFrame(saved_months)
        # Ensure column names match
        if "month" not in df_init.columns:
            df_init["month"] = _MONTH_NAMES
    else:
        df_init = pd.DataFrame({
            "month": _MONTH_NAMES,
            "kwh": [0.0] * 12,
            "bill_crc": [0.0] * 12,
        })

    st.caption("Ingresa el consumo mensual (kWh) y el monto de la factura (₡) de los últimos 12 meses.")

    edited_df = st.data_editor(
        df_init,
        column_config={
            "month": st.column_config.TextColumn("Mes", disabled=True, width="small"),
            "kwh": st.column_config.NumberColumn("kWh", min_value=0, format="%.0f", width="small"),
            "bill_crc": st.column_config.NumberColumn("Factura (₡)", min_value=0, format="%.0f", width="medium"),
        },
        use_container_width=True,
        hide_index=True,
        key="w5_table",
    )

    kwh_values = edited_df["kwh"].tolist()
    bill_values = edited_df["bill_crc"].tolist()

    filled = [v for v in kwh_values if v and v > 0]
    avg_kwh = round(sum(filled) / len(filled), 2) if filled else 0.0
    filled_bills = [v for v in bill_values if v and v > 0]
    avg_bill = round(sum(filled_bills) / len(filled_bills)) if filled_bills else 0

    # Interconnection permit cost
    icpe_cost = st.number_input(
        "Costo del permiso de interconexión (USD)",
        value=float(current.get("interconnection_permit_usd", 1000.0)),
        min_value=0.0,
        step=100.0,
        format="%.2f",
        key="w5_icpe",
    )

    if avg_kwh > 0:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Consumo promedio", f"{avg_kwh:,.0f} kWh/mes")
        with col2:
            st.metric("Factura promedio", f"₡{avg_bill:,.0f}/mes")

        if len(filled) >= 3:
            import plotly.graph_objects as go
            fig = go.Figure(go.Bar(
                x=_MONTH_NAMES[:len(kwh_values)],
                y=kwh_values,
                marker_color=BRAND_GREEN,
                text=[f"{v:.0f}" if v else "" for v in kwh_values],
                textposition="outside",
            ))
            fig.update_layout(
                title="Consumo mensual (kWh)",
                yaxis_title="kWh",
                height=240,
                margin=dict(t=40, b=10, l=10, r=10),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w5_back"):
            st.session_state["wizard_step"] = 4
            st.rerun()
    with col_next:
        can_continue = avg_kwh > 0
        if st.button("Siguiente →", key="w5_next", type="primary", disabled=not can_continue):
            months_data = [
                {"month": _MONTH_NAMES[i], "kwh": float(kwh_values[i] or 0), "bill_crc": float(bill_values[i] or 0)}
                for i in range(12)
            ]
            result = {
                "source": "manual",
                "months_data": months_data,
                "avg_kwh": avg_kwh,
                "avg_bill_crc": avg_bill,
                "interconnection_permit_usd": icpe_cost,
            }
            st.session_state["wizard_consumption"] = result
            return result

    if avg_kwh <= 0:
        st.caption("Ingresa al menos un mes de consumo para continuar.")

    return None


# ── Step 6 — Equipment ────────────────────────────────────────────────────────

def step6_equipment() -> dict | None:
    """Panel + inverter selection, MPPT validation, 3 scenarios."""
    st.markdown("### Paso 6 — Equipos")

    from database.equipment_db import list_panels, list_inverters, list_monitoring_devices
    from calculations.mppt import validate_string_design

    current = st.session_state.get("wizard_equipment", {})
    consumption = st.session_state.get("wizard_consumption", {})
    site = st.session_state.get("wizard_site", {})

    try:
        panels = list_panels()
        inverters = list_inverters()
        monitoring_devices = list_monitoring_devices()
    except Exception as e:
        st.error(f"Error cargando catálogo: {e}")
        return None

    if not panels or not inverters:
        st.warning("No hay equipos en el catálogo. Contacta al administrador.")
        return None

    panel_options = {f"{p['brand']} {p['model']} — {p['wp']}W": p for p in panels}
    inverter_options = {f"{inv['brand']} {inv['model']} — {inv['kw']} kW": inv for inv in inverters}
    monitoring_options = {"— Sin monitoreo —": None} | {f"{m['brand']} {m['model']}": m for m in monitoring_devices}

    # Default selections
    current_panel_id = current.get("panel_id")
    current_inverter_id = current.get("inverter_id")
    current_monitoring_id = current.get("monitoring_id")

    default_panel_idx = next((i for i, p in enumerate(panels) if p["id"] == current_panel_id), 0)
    default_inv_idx = next((i for i, inv in enumerate(inverters) if inv["id"] == current_inverter_id), 0)

    col1, col2 = st.columns(2)
    with col1:
        panel_label = st.selectbox("Panel solar *", list(panel_options.keys()), index=default_panel_idx, key="w6_panel")
        selected_panel = panel_options[panel_label]

        st.markdown(f"""
        <div style="background:{BRAND_GREEN_LIGHT};border-radius:6px;padding:0.6rem 1rem;font-size:0.85rem;">
        <b>{selected_panel['brand']} {selected_panel['model']}</b><br>
        Voc: {selected_panel['voc']}V · Vmp: {selected_panel['vmp']}V<br>
        Isc: {selected_panel['isc']}A · Imp: {selected_panel['imp']}A<br>
        Área: {selected_panel.get('width_m', 0) * selected_panel.get('height_m', 0):.2f} m²<br>
        Garantía: {selected_panel.get('warranty_product_yr', '—')} años producto / {selected_panel.get('warranty_power_yr', '—')} años potencia
        </div>
        """, unsafe_allow_html=True)

    with col2:
        inv_label = st.selectbox("Inversor *", list(inverter_options.keys()), index=default_inv_idx, key="w6_inv")
        selected_inverter = inverter_options[inv_label]

        st.markdown(f"""
        <div style="background:{BRAND_GREEN_LIGHT};border-radius:6px;padding:0.6rem 1rem;font-size:0.85rem;">
        <b>{selected_inverter['brand']} {selected_inverter['model']}</b><br>
        Vmax: {selected_inverter.get('vmax', '—')}V · MPPT: {selected_inverter.get('vmin_mppt', '—')}–{selected_inverter.get('vmax_mppt', '—')}V<br>
        Imax MPPT: {selected_inverter.get('imax_mppt', '—')}A · Canales: {selected_inverter.get('mppt_channels', '—')}<br>
        Garantía: {selected_inverter.get('warranty_yr', '—')} años
        </div>
        """, unsafe_allow_html=True)

    # MPPT calculation
    avg_kwh = consumption.get("avg_kwh", 0)
    pvgis_monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp", [])
    avg_irradiance = sum(pvgis_monthly) / 12 if pvgis_monthly else 127.0

    target_kw = (0.85 * avg_kwh / avg_irradiance) if avg_irradiance > 0 else None

    st.divider()
    if st.button("⚡ Calcular configuración MPPT", key="w6_calc_mppt"):
        with st.spinner("Calculando escenarios de strings…"):
            scenarios = validate_string_design(selected_panel, selected_inverter, target_kw)
            st.session_state["w6_scenarios"] = scenarios

    scenarios = st.session_state.get("w6_scenarios", current.get("scenarios"))

    selected_scenario_label = current.get("mppt_scenario", "B")

    if scenarios:
        st.markdown("**Escenarios de diseño MPPT:**")

        scenario_data = []
        for s in scenarios:
            area = round(
                s["total_panels"] * selected_panel.get("width_m", 1.134) * selected_panel.get("height_m", 2.278),
                1,
            )
            ok_icon = "✅" if s["within_limits"] else "⚠️"
            scenario_data.append({
                "Escenario": f"Escenario {s['scenario']}",
                "Paneles/string": s["panels_per_string"],
                "Strings": s["strings"],
                "Total paneles": s["total_panels"],
                "Sistema (kW)": s["system_kw"],
                "Área (m²)": area,
                "Voc total (V)": s["voc_total"],
                "Vmp total (V)": s["vmp_total"],
                "Estado": ok_icon,
                "Notas": s["notes"],
            })

        st.dataframe(pd.DataFrame(scenario_data), use_container_width=True, hide_index=True)

        valid_scenarios = [s for s in scenarios if s["within_limits"]]
        if not valid_scenarios:
            st.warning("Ningún escenario es válido con este par panel/inversor.")
        else:
            scenario_opts = {f"Escenario {s['scenario']} — {s['total_panels']} paneles ({s['system_kw']} kW)": s["scenario"]
                            for s in valid_scenarios}
            default_sel_idx = next(
                (i for i, v in enumerate(scenario_opts.values()) if v == selected_scenario_label),
                min(1, len(valid_scenarios) - 1),
            )
            sel_label = st.radio(
                "Seleccionar escenario",
                list(scenario_opts.keys()),
                index=default_sel_idx,
                key="w6_scenario_radio",
                horizontal=True,
            )
            selected_scenario_label = scenario_opts[sel_label]
    else:
        st.info("Haz clic en 'Calcular configuración MPPT' para ver los escenarios.")

    # Monitoring (optional)
    st.divider()
    mon_label = st.selectbox("Sistema de monitoreo (opcional)", list(monitoring_options.keys()), key="w6_mon")
    selected_monitoring = monitoring_options[mon_label]

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w6_back"):
            st.session_state["wizard_step"] = 5
            st.rerun()
    with col_next:
        can_continue = scenarios is not None and any(s["within_limits"] for s in scenarios)
        if st.button("Siguiente →", key="w6_next", type="primary", disabled=not can_continue):
            chosen_scenario = next((s for s in scenarios if s["scenario"] == selected_scenario_label), scenarios[0])
            result = {
                "panel_id": selected_panel["id"],
                "panel": selected_panel,
                "inverter_id": selected_inverter["id"],
                "inverter": selected_inverter,
                "mppt_scenario": selected_scenario_label,
                "chosen_scenario": chosen_scenario,
                "scenarios": scenarios,
                "monitoring_id": selected_monitoring["id"] if selected_monitoring else None,
                "monitoring": selected_monitoring,
            }
            st.session_state["wizard_equipment"] = result
            return result

    if not scenarios:
        st.caption("Calcula los escenarios MPPT antes de continuar.")

    return None


# ── Step 7 — Costs ───────────────────────────────────────────────────────────

_DEFAULT_LINE_ITEMS = [
    {"item": "Paneles solares", "item_en": "Solar panels",
     "qty": None, "unit_cost": 0.0, "specs": "", "specs_en": ""},
    {"item": "Inversores", "item_en": "Inverters",
     "qty": 1, "unit_cost": 0.0, "specs": "", "specs_en": ""},
    {"item": "Permiso de Interconexión", "item_en": "Interconnection Permit",
     "qty": None, "unit_cost": 1000.0,
     "specs": "Requerido por el Reglamento de Generación Distribuida",
     "specs_en": "Required by the Distributed Generation Regulation"},
    {"item": "Diseño Eléctrico y Administración", "item_en": "Electrical Design & Management",
     "qty": None, "unit_cost": 0.0,
     "specs": "Estudios preliminares, diseño eléctrico, inspección del sitio y gestión",
     "specs_en": "Preliminary studies, electrical design, site inspection and management"},
    {"item": "Mano de obra", "item_en": "Labor",
     "qty": None, "unit_cost": 0.0,
     "specs": "Instalación y costos relacionados con la obra",
     "specs_en": "Installation and costs related to the project"},
    {"item": "Materiales eléctricos", "item_en": "Electrical materials",
     "qty": None, "unit_cost": 0.0,
     "specs": "Materiales eléctricos y montaje solar",
     "specs_en": "Electrical materials and solar mounting"},
    {"item": "Sistema de monitoreo remoto", "item_en": "Remote monitoring system",
     "qty": 1, "unit_cost": 0.0, "specs": "", "specs_en": ""},
]


def step7_costs() -> dict | None:
    """Line items table, IVA toggle, totals. Returns costs dict."""
    st.markdown("### Paso 7 — Detalles de costos")

    current = st.session_state.get("wizard_costs", {})
    equipment = st.session_state.get("wizard_equipment", {})
    consumption = st.session_state.get("wizard_consumption", {})

    panel = equipment.get("panel", {})
    inverter = equipment.get("inverter", {})
    monitoring = equipment.get("monitoring")
    chosen_scenario = equipment.get("chosen_scenario", {})
    panel_count = chosen_scenario.get("total_panels", 0)

    # Build initial line items from equipment selection
    if current.get("line_items"):
        line_items = current["line_items"]
    else:
        line_items = []
        for item in _DEFAULT_LINE_ITEMS:
            row = dict(item)
            if row["item"] == "Paneles solares" and panel:
                row["qty"] = panel_count
                row["specs"] = f"{panel.get('brand', '')} {panel.get('model', '')} {panel.get('wp', '')}W"
                row["specs_en"] = row["specs"]
                cost = panel.get("cost_usd") or 0.0
                row["unit_cost"] = round(cost, 2)
            elif row["item"] == "Inversores" and inverter:
                row["qty"] = 1
                row["specs"] = f"{inverter.get('brand', '')} {inverter.get('model', '')}"
                row["specs_en"] = row["specs"]
                row["unit_cost"] = round(inverter.get("cost_usd") or 0.0, 2)
            elif row["item"] == "Sistema de monitoreo remoto":
                if monitoring:
                    row["specs"] = f"{monitoring.get('brand', '')} {monitoring.get('model', '')}"
                    row["specs_en"] = row["specs"]
                    row["unit_cost"] = round(monitoring.get("cost_usd") or 0.0, 2)
                else:
                    continue  # skip if no monitoring selected
            elif row["item"] == "Permiso de Interconexión":
                row["unit_cost"] = float(consumption.get("interconnection_permit_usd", 1000.0))
            line_items.append(row)

    # Editable table: item, qty, unit_cost, total (computed)
    df = pd.DataFrame([{
        "Descripción (ES)": r["item"],
        "Descripción (EN)": r.get("item_en", r["item"]),
        "Qty": r.get("qty") or "",
        "Costo unitario (USD)": r["unit_cost"],
        "Especificaciones": r.get("specs", ""),
    } for r in line_items])

    st.caption("Edita cantidades y costos. Los totales se calculan automáticamente.")

    edited = st.data_editor(
        df,
        column_config={
            "Descripción (ES)": st.column_config.TextColumn(width="medium"),
            "Descripción (EN)": st.column_config.TextColumn(width="medium"),
            "Qty": st.column_config.TextColumn(width="small"),
            "Costo unitario (USD)": st.column_config.NumberColumn(min_value=0, format="$%.2f", width="small"),
            "Especificaciones": st.column_config.TextColumn(width="large"),
        },
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        key="w7_table",
    )

    # Compute totals
    def _row_total(row: pd.Series) -> float:
        qty_raw = row["Qty"]
        try:
            qty = 1.0 if pd.isna(qty_raw) or qty_raw == "" else float(qty_raw)
        except (ValueError, TypeError):
            qty = 1.0
        return round(qty * float(row["Costo unitario (USD)"] or 0), 2)

    edited["Total (USD)"] = edited.apply(_row_total, axis=1)
    subtotal = round(edited["Total (USD)"].sum(), 2)

    iva_rate = st.radio("IVA", ["0% (exento)", "13%"], horizontal=True,
                        index=0 if current.get("iva_rate", 0) == 0 else 1,
                        key="w7_iva")
    iva_pct = 0.0 if "0%" in iva_rate else 0.13
    iva_amount = round(subtotal * iva_pct, 2)
    total = round(subtotal + iva_amount, 2)

    panel_wp_total = panel_count * panel.get("wp", 0)
    cost_per_wp = round(total / panel_wp_total, 3) if panel_wp_total else 0.0

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Subtotal", f"${subtotal:,.2f}")
    with col2:
        st.metric(f"IVA ({iva_rate})", f"${iva_amount:,.2f}")
    with col3:
        st.metric("TOTAL", f"${total:,.2f}")

    if cost_per_wp:
        st.caption(f"${cost_per_wp:.2f}/Wp")

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w7_back"):
            st.session_state["wizard_step"] = 6
            st.rerun()
    with col_next:
        can_continue = total > 0
        if st.button("Siguiente →", key="w7_next", type="primary", disabled=not can_continue):
            # Rebuild line_items from edited df
            updated_items = []
            original_items_lookup = {r["item"]: r for r in line_items}
            for _, row in edited.iterrows():
                desc_es = row["Descripción (ES)"]
                original = original_items_lookup.get(desc_es, {})
                updated_items.append({
                    "item": desc_es,
                    "item_en": row["Descripción (EN)"],
                    "qty": None if pd.isna(row["Qty"]) or row["Qty"] == "" else row["Qty"],
                    "unit_cost": float(row["Costo unitario (USD)"] or 0),
                    "total": float(row["Total (USD)"]),
                    "specs": row["Especificaciones"],
                    "specs_en": original.get("specs_en", row["Especificaciones"]),
                })
            result = {
                "line_items": updated_items,
                "iva_rate": iva_pct,
                "subtotal_usd": subtotal,
                "iva_usd": iva_amount,
                "total_usd": total,
                "cost_per_wp": cost_per_wp,
            }
            st.session_state["wizard_costs"] = result
            return result

    return None


# ── Step 8 — Review + Generate PDF ───────────────────────────────────────────

def step8_review() -> None:
    """Summary cards, billing comparison, benefits, intro paragraph, Generate PDF button."""
    st.markdown("### Paso 8 — Revisión y generación de propuesta")

    from datetime import date as dt

    from calculations.tariffs import calculate_bill
    from calculations.sizing_grid_zero import size_system, compute_avg_billing
    from calculations.financials import calculate_irr, calculate_roi, calculate_25yr_savings
    from database.tariffs_db import get_tariff_tiers
    from utils.currency import get_exchange_rate
    from wizard.state import get_company_info, get_bank_info

    meta = st.session_state.get("wizard_meta", {})
    client = st.session_state.get("wizard_client", {})
    site = st.session_state.get("wizard_site", {})
    utility = st.session_state.get("wizard_utility", {})
    consumption = st.session_state.get("wizard_consumption", {})
    equipment = st.session_state.get("wizard_equipment", {})
    costs = st.session_state.get("wizard_costs", {})

    language = meta.get("language", "es")
    panel = equipment.get("panel", {})
    inverter = equipment.get("inverter", {})
    chosen = equipment.get("chosen_scenario", {})
    panel_count = chosen.get("total_panels", 0)
    system_kw = chosen.get("system_kw", 0.0)

    pvgis_monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp", [])
    avg_kwh = consumption.get("avg_kwh", 0)
    monthly_kwh = [m["kwh"] for m in consumption.get("months_data", [])] or [avg_kwh] * 12

    # Compute sizing
    sizing = {}
    avg_billing = {}
    exchange_rate = 520.0
    tiers = []
    tariff_type = {}

    try:
        exchange_rate = get_exchange_rate()
    except Exception:
        pass

    try:
        tariff_type_id = utility.get("tariff_type_id")
        if tariff_type_id:
            tiers = get_tariff_tiers(tariff_type_id)
            from database.tariffs_db import list_tariff_types
            tt_list = list_tariff_types(utility.get("distributor_id", ""))
            tariff_type = next((t for t in tt_list if t["id"] == tariff_type_id), {})
    except Exception as e:
        st.warning(f"No se pudo cargar tarifa: {e}")

    if pvgis_monthly and tiers:
        sizing = size_system(avg_kwh, pvgis_monthly, panel.get("wp", 620), panel_count)
        try:
            avg_billing = compute_avg_billing(
                monthly_kwh, sizing["monthly_generation"], tariff_type, tiers, exchange_rate
            )
        except Exception as e:
            st.warning(f"Error en cálculo de ahorro: {e}")
    else:
        sizing = {
            "system_kw": system_kw,
            "panel_count": panel_count,
            "avg_generation_kwh": 0,
            "avg_net_consumption_kwh": 0,
        }

    # Financial projections
    total_usd = costs.get("total_usd", 0)
    total_crc = total_usd * exchange_rate
    savings_crc = avg_billing.get("savings_crc", 0)
    savings_year1_crc = savings_crc * 12
    savings_year1_usd = round(savings_year1_crc / exchange_rate, 2) if exchange_rate else 0

    irr_pct, roi_years, savings_25yr_usd = 0.0, 0.0, 0.0
    if savings_year1_crc > 0 and total_crc > 0:
        try:
            irr_pct = calculate_irr(total_crc, savings_year1_crc)
            roi_years = calculate_roi(total_crc, savings_year1_crc)
            savings_25yr_crc = calculate_25yr_savings(savings_year1_crc)
            savings_25yr_usd = round(savings_25yr_crc / exchange_rate, 2)
        except Exception:
            pass

    avg_monthly_savings_usd = round(savings_year1_usd / 12, 2)
    pct_savings = avg_billing.get("pct_savings", 0)
    area_m2 = round(panel_count * panel.get("width_m", 1.134) * panel.get("height_m", 2.278), 1)

    # ── Summary cards ────────────────────────────────────────────────────────
    st.markdown("#### Resumen técnico")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Sistema", f"{system_kw:.2f} kW")
    with c2:
        st.metric("Paneles", str(panel_count))
    with c3:
        st.metric("Área", f"{area_m2} m²")
    with c4:
        st.metric("$/Wp", f"${costs.get('cost_per_wp', 0):.2f}")

    if avg_billing:
        st.markdown("#### Facturación estimada (promedio mensual)")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Consumo actual", f"{avg_billing.get('consumption_kwh', 0):,.0f} kWh")
            st.metric("Factura actual", f"₡{avg_billing.get('bill_crc', 0):,.0f}")
        with c2:
            st.metric("Generación solar", f"{avg_billing.get('generation_kwh', 0):,.0f} kWh")
            st.metric("Nueva factura", f"₡{avg_billing.get('new_bill_crc', 0):,.0f}")
        with c3:
            st.metric("Ahorro mensual", f"₡{avg_billing.get('savings_crc', 0):,.0f}")
            st.metric("Reducción", f"{pct_savings:.1f}%")

    if savings_year1_usd > 0:
        st.markdown("#### Beneficios financieros")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Ahorro año 1", f"${savings_year1_usd:,.0f}")
        with c2:
            st.metric("Ahorro 25 años", f"${savings_25yr_usd:,.0f}")
        with c3:
            st.metric("TIR", f"{irr_pct:.2f}%")
        with c4:
            st.metric("ROI", f"{roi_years:.2f} años")

    # ── Intro paragraph ───────────────────────────────────────────────────────
    st.divider()
    st.markdown("#### Párrafo introductorio")
    st.caption("Este texto aparecerá en la propuesta. En Fase 4 lo generará Claude. Puedes editarlo ahora.")

    default_intro_es = (
        "Esta propuesta se basa en la facturación eléctrica mensual aproximada. "
        "Propone un sistema de energía solar conectado a la red pero sin entrega de "
        "excedentes de energía (grid-zero). El diseño propuesto no incluye sistemas de respaldo de energía."
    )
    default_intro_en = (
        "This proposal is based on approximate monthly electricity billing. "
        "It proposes a solar energy system connected to the grid without exporting surplus energy (grid-zero). "
        "The proposed design does not include energy backup systems."
    )

    saved_text = st.session_state.get("wizard_proposal_text", "")
    if not saved_text:
        saved_text = default_intro_es if language == "es" else default_intro_en

    proposal_text = st.text_area("Texto introductorio", value=saved_text, height=120, key="w8_intro")
    st.session_state["wizard_proposal_text"] = proposal_text

    # ── Generate PDF ─────────────────────────────────────────────────────────
    st.divider()
    col_back, _, col_pdf = st.columns([1, 3, 2])
    with col_back:
        if st.button("← Atrás", key="w8_back"):
            st.session_state["wizard_step"] = 7
            st.rerun()

    with col_pdf:
        if st.button("📄 Generar PDF", key="w8_gen", type="primary"):
            company = get_company_info()
            bank = get_bank_info()

            # Build PDF data dict matching generator.MARIA_JOSE_DATA shape
            today = dt.today().strftime("%-d/%-m/%Y") if hasattr(dt.today(), 'strftime') else dt.today().isoformat()

            warranty_inv_years_es = f"{inverter.get('warranty_yr', 5)} años"
            warranty_inv_years_en = f"{inverter.get('warranty_yr', 5)} years"

            cost_items = []
            for li in costs.get("line_items", []):
                qty_val = li.get("qty")
                try:
                    qty_int = int(float(qty_val)) if qty_val is not None and qty_val != "" else None
                except (ValueError, TypeError):
                    qty_int = None
                cost_items.append({
                    "item": li["item"],
                    "item_en": li.get("item_en", li["item"]),
                    "qty": qty_int,
                    "specs": li.get("specs", ""),
                    "specs_en": li.get("specs_en", li.get("specs", "")),
                    "total": float(li.get("total", 0)),
                })

            # Build quote number string for this version
            _quote_num_str = ""
            try:
                from database.proposals_db import format_quote_number, get_proposal
                proposal_id = st.session_state.get("wizard_proposal_id")
                version_id_now = st.session_state.get("wizard_version_id")
                if proposal_id:
                    _prop = get_proposal(proposal_id)
                    if _prop and _prop.get("quote_number"):
                        _vnum = st.session_state.get("wizard_meta", {}).get("version_number", 1)
                        _quote_num_str = format_quote_number(
                            _prop["quote_number"], _prop.get("created_at", ""), _vnum
                        )
            except Exception:
                pass

            pdf_data = {
                "date": today,
                "quote_number": _quote_num_str,
                "client": {
                    "name": client.get("name", ""),
                    "location": client.get("location", f"{site.get('city', '')}, {site.get('province', '')}"),
                    "nise": utility.get("nise", client.get("nise", "N/A")),
                },
                "system_type_label": "Grid Zero",
                "intro_lines": [proposal_text],
                "billing_avg": {
                    "consumption_kwh": avg_billing.get("consumption_kwh", avg_kwh),
                    "bill_crc": avg_billing.get("bill_crc", consumption.get("avg_bill_crc", 0)),
                    "generation_kwh": avg_billing.get("generation_kwh", sizing.get("avg_generation_kwh", 0)),
                    "new_consumption_kwh": avg_billing.get("new_consumption_kwh", sizing.get("avg_net_consumption_kwh", 0)),
                    "new_bill_crc": avg_billing.get("new_bill_crc", 0),
                    "savings_crc": avg_billing.get("savings_crc", 0),
                },
                "benefits": {
                    "savings_year1_usd": savings_year1_usd,
                    "savings_25yr_usd": savings_25yr_usd,
                    "irr_pct": irr_pct,
                    "roi_years": roi_years,
                    "avg_monthly_savings_usd": avg_monthly_savings_usd,
                    "pct_savings": pct_savings,
                },
                "benefits_notes_es": "No se considera la entrega de excedentes de energía a la red eléctrica nacional",
                "benefits_notes_en": "Excess energy delivered to the national grid is not considered",
                "cost_items": cost_items,
                "total_usd": total_usd,
                "technical": {
                    "system_kw": system_kw,
                    "area_m2": area_m2,
                    "panel_count": panel_count,
                    "inverter_count": 1,
                },
                "cost_per_wp": costs.get("cost_per_wp", 0),
                "warranty_inverter_years": warranty_inv_years_es,
                "warranty_inverter_years_en": warranty_inv_years_en,
                "payment_notes_es": [
                    "Solicitamos un pago inicial del 70% por adelantado y el 30% restante contra entrega del proyecto",
                    "Duración estimada: 21 días después del pago inicial",
                    "Se entrega factura electrónica por el monto total",
                    "Los pagos se realizan mediante transferencia bancaria a la siguiente cuenta:",
                ],
                "payment_notes_en": [
                    "We request an initial payment of 70% in advance and the remaining 30% upon project delivery",
                    "Estimated duration: 21 days after initial payment",
                    "An electronic invoice is provided for the full amount",
                    "Payments are made via bank transfer to the following account:",
                ],
                **bank,
                "company": company,
                "validity_days": 15,
            }

            try:
                from proposals.generator import generate_pdf
                with st.spinner("Generando PDF…"):
                    pdf_bytes = generate_pdf(pdf_data, "grid_zero", language)

                lang_label = "ES" if language == "es" else "EN"
                client_name_safe = client.get("name", "propuesta").replace(" ", "_")
                st.success(f"PDF generado — {len(pdf_bytes):,} bytes")
                st.download_button(
                    label=f"⬇ Descargar PDF ({lang_label})",
                    data=pdf_bytes,
                    file_name=f"cotizacion_{client_name_safe}_{lang_label}.pdf",
                    mime="application/pdf",
                    key="w8_download",
                )

                # Optionally upload to Supabase
                proposal_id = st.session_state.get("wizard_proposal_id")
                version_id = st.session_state.get("wizard_version_id")
                if proposal_id and version_id:
                    try:
                        from proposals.generator import upload_pdf
                        from database.proposals_db import save_pdf_path
                        path = upload_pdf(pdf_bytes, proposal_id, 1, client.get("name", "cliente"))
                        save_pdf_path(version_id, path)
                    except Exception:
                        pass  # Upload failure doesn't block download

            except Exception as e:
                st.error(f"Error generando PDF: {e}")
                st.exception(e)

    # ── Version locking ───────────────────────────────────────────────────────
    st.divider()
    version_id = st.session_state.get("wizard_version_id")

    # Check DB in case this version was locked outside this session
    is_locked = st.session_state.get("wizard_version_locked", False)
    if not is_locked and version_id:
        try:
            from database.proposals_db import get_version as _get_v
            _vrow = _get_v(version_id)
            if _vrow and _vrow.get("locked"):
                st.session_state["wizard_version_locked"] = True
                is_locked = True
        except Exception:
            pass

    if is_locked:
        st.success("✅ Versión bloqueada. Esta copia es inmutable.")
        lc1, lc2, lc3 = st.columns(3)
        with lc1:
            if st.button("📋 Nueva versión", key="w8_new_version"):
                try:
                    from database.proposals_db import create_version, get_version as _gv
                    from wizard.state import load_draft, clear_wizard_state
                    pid = st.session_state.get("wizard_proposal_id")
                    full_v = _gv(version_id)
                    data = full_v.get("data", {}) if full_v else {}
                    new_v = create_version(pid, data)
                    clear_wizard_state()
                    st.session_state["wizard_proposal_id"] = pid
                    st.session_state["wizard_version_id"] = new_v["id"]
                    load_draft(new_v["id"])
                    st.session_state["wizard_step"] = 1
                    st.rerun()
                except Exception as e:
                    st.error(f"Error creando nueva versión: {e}")
        with lc2:
            if st.button("📤 Marcar como enviada", key="w8_mark_sent"):
                try:
                    from database.proposals_db import mark_version_sent
                    mark_version_sent(version_id)
                    st.success("Marcada como enviada al cliente.")
                except Exception as e:
                    st.error(f"Error: {e}")
        with lc3:
            if st.button("📋 Ir a cotizaciones", key="w8_go_proposals"):
                st.switch_page("pages/01_proposals.py")

    elif version_id:
        st.markdown("#### Bloquear versión")
        st.caption(
            "Bloquear crea una copia inmutable. Cambios futuros requerirán crear una versión nueva."
        )
        version_note = st.text_input(
            "Nota de versión (opcional)",
            value="",
            placeholder="Ej: Precio reducido — cliente pidió 2 paneles menos",
            key="w8_version_note",
        )
        lk_col, _ = st.columns([2, 4])
        with lk_col:
            if st.button("🔒 Bloquear versión / Lock version", key="w8_lock"):
                try:
                    from database.proposals_db import lock_version as _lock_v
                    _lock_v(version_id, version_note or None)
                    st.session_state["wizard_version_locked"] = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Error bloqueando versión: {e}")
