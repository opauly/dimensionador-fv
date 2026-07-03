from __future__ import annotations
"""Wizard steps 1–3 shared across all system types. Phase 2."""
import streamlit as st

from config import BRAND_GREEN


def step1_system_type() -> dict | None:
    """
    Select system type and language.
    Returns dict with 'system_type' and 'language', or None if not yet confirmed.
    """
    st.markdown("### Paso 1 — Tipo de sistema e idioma")
    st.markdown("Selecciona el tipo de sistema solar y el idioma de la cotización.")

    current = st.session_state.get("wizard_meta", {})

    col_sys, col_lang = st.columns(2)

    with col_sys:
        system_options = {
            "Grid Zero (sin exportación de excedentes)": "grid_zero",
            "Off-Grid (sistema aislado)": "off_grid",
            "Híbrido (Grid Zero + respaldo)": "hybrid",
        }
        sys_label = st.radio(
            "Tipo de sistema",
            list(system_options.keys()),
            index=list(system_options.values()).index(current.get("system_type", "grid_zero")),
            key="w1_system_type_radio",
        )
        system_type = system_options[sys_label]

        if system_type != "grid_zero":
            st.info("Off-Grid e Híbrido disponibles en Fase 5. Por ahora solo Grid Zero está habilitado.")

    with col_lang:
        lang_options = {"Español": "es", "English": "en"}
        lang_label = st.radio(
            "Idioma de la cotización",
            list(lang_options.keys()),
            index=list(lang_options.values()).index(current.get("language", "es")),
            key="w1_language_radio",
        )
        language = lang_options[lang_label]

    st.divider()
    _, _, col_next = st.columns([3, 1, 1])
    with col_next:
        if st.button("Siguiente →", key="w1_next", type="primary", disabled=(system_type != "grid_zero")):
            result = {"system_type": system_type, "language": language}
            st.session_state["wizard_meta"] = result
            return result

    return None


def step2_client() -> dict | None:
    """
    Client name, phone, email with typeahead autocomplete from clients table.
    Returns client dict or None.
    """
    st.markdown("### Paso 2 — Datos del cliente")

    current = st.session_state.get("wizard_client", {})

    # Typeahead search
    search_query = st.text_input(
        "Buscar cliente existente",
        placeholder="Escribe el nombre para buscar…",
        key="w2_search",
    )

    client_id: str | None = None
    if search_query and len(search_query) >= 2:
        try:
            from database.clients_db import search_clients
            matches = search_clients(search_query)
            if matches:
                options = {f"{m['name']} — {m.get('phone', '')} {m.get('email', '')}".strip(" —"): m for m in matches}
                sel = st.selectbox("Seleccionar cliente", ["— Nuevo cliente —"] + list(options.keys()), key="w2_match")
                if sel != "— Nuevo cliente —":
                    chosen = options[sel]
                    client_id = chosen["id"]
                    current = {
                        "client_id": client_id,
                        "name": chosen.get("name", ""),
                        "phone": chosen.get("phone", ""),
                        "email": chosen.get("email", ""),
                    }
        except Exception as e:
            st.caption(f"⚠ No se pudo buscar clientes: {e}")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("Nombre completo *", value=current.get("name", ""), key="w2_name")
        phone = st.text_input("Teléfono", value=current.get("phone", ""), key="w2_phone")
    with col2:
        email = st.text_input("Correo electrónico", value=current.get("email", ""), key="w2_email")
        location = st.text_input(
            "Ubicación (ciudad, provincia)",
            value=current.get("location", ""),
            placeholder="Ej: Atenas, Alajuela",
            key="w2_location",
        )
        nise = st.text_input("NISE (número de cliente en distribuidora)", value=current.get("nise", "N/A"), key="w2_nise")

    if not name.strip():
        st.caption("* El nombre del cliente es requerido.")

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w2_back"):
            st.session_state["wizard_step"] = 1
            st.rerun()
    with col_next:
        if st.button("Siguiente →", key="w2_next", type="primary", disabled=(not name.strip())):
            result = {
                "name": name.strip(),
                "phone": phone.strip(),
                "email": email.strip(),
                "location": location.strip(),
                "nise": nise.strip() or "N/A",
            }
            if client_id:
                result["client_id"] = client_id
            st.session_state["wizard_client"] = result
            return result

    return None


def step3_site() -> dict | None:
    """
    City/province → geocode → PVGIS fetch.
    Returns site dict with lat, lon, pvgis_data or None.
    """
    st.markdown("### Paso 3 — Ubicación e irradiancia solar")

    current = st.session_state.get("wizard_site", {})
    client = st.session_state.get("wizard_client", {})

    # Pre-fill from client location if available
    default_location = client.get("location", "")
    default_city = current.get("city", "")
    default_province = current.get("province", "")

    if not default_city and default_location and "," in default_location:
        parts = [p.strip() for p in default_location.split(",", 1)]
        default_city = parts[0]
        default_province = parts[1] if len(parts) > 1 else ""

    col1, col2 = st.columns(2)
    with col1:
        city = st.text_input("Ciudad", value=default_city, key="w3_city")
    with col2:
        province = st.text_input("Provincia", value=default_province, key="w3_province")

    # Manual lat/lon override
    with st.expander("Coordenadas manuales (opcional)"):
        col_lat, col_lon = st.columns(2)
        with col_lat:
            lat_manual = st.number_input(
                "Latitud",
                value=float(current.get("lat", 0.0) or 0.0),
                format="%.5f",
                key="w3_lat",
            )
        with col_lon:
            lon_manual = st.number_input(
                "Longitud",
                value=float(current.get("lon", 0.0) or 0.0),
                format="%.5f",
                key="w3_lon",
            )

    pvgis_data = current.get("pvgis_data")
    lat = current.get("lat")
    lon = current.get("lon")

    col_pvgis, _ = st.columns([2, 3])
    with col_pvgis:
        if st.button("🌤 Obtener irradiancia solar (PVGIS)", key="w3_pvgis"):
            from calculations.pvgis import fetch_irradiance, geocode_cr

            with st.spinner("Geocodificando y consultando PVGIS…"):
                # Use manual coords if non-zero, else geocode
                if lat_manual != 0.0 and lon_manual != 0.0:
                    lat, lon = lat_manual, lon_manual
                else:
                    coords = geocode_cr(city, province)
                    if coords:
                        lat, lon = coords
                    else:
                        st.error(f"No se encontraron coordenadas para '{city}, {province} Costa Rica'. Ingresa lat/lon manualmente.")
                        lat, lon = None, None

                if lat and lon:
                    try:
                        pvgis_data = fetch_irradiance(lat, lon)
                        st.success(f"Irradiancia obtenida para {lat:.3f}, {lon:.3f}")
                    except Exception as e:
                        st.error(f"Error PVGIS: {e}")

    if pvgis_data:
        monthly = pvgis_data.get("monthly_kwh_kwp", [])
        yearly = pvgis_data.get("yearly_kwh_kwp", 0)
        avg_monthly = round(sum(monthly) / 12, 1) if monthly else 0

        st.markdown(f"**Irradiancia promedio:** {avg_monthly} kWh/kWp/mes · Anual: {yearly:.0f} kWh/kWp")

        if monthly and len(monthly) == 12:
            import plotly.graph_objects as go
            from calculations.sizing_grid_zero import MONTHS_ES

            fig = go.Figure(go.Bar(
                x=MONTHS_ES,
                y=monthly,
                marker_color=BRAND_GREEN,
                text=[f"{v:.0f}" for v in monthly],
                textposition="outside",
            ))
            fig.update_layout(
                title="Irradiancia mensual (kWh/kWp)",
                yaxis_title="kWh/kWp",
                height=260,
                margin=dict(t=40, b=10, l=10, r=10),
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Haz clic en 'Obtener irradiancia solar' para cargar datos de PVGIS.")

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w3_back"):
            st.session_state["wizard_step"] = 2
            st.rerun()
    with col_next:
        can_continue = pvgis_data is not None and lat is not None
        if st.button("Siguiente →", key="w3_next", type="primary", disabled=not can_continue):
            result = {
                "city": city.strip(),
                "province": province.strip(),
                "lat": lat,
                "lon": lon,
                "pvgis_data": pvgis_data,
            }
            st.session_state["wizard_site"] = result
            return result

    if not pvgis_data:
        st.caption("Es necesario obtener los datos de irradiancia para continuar.")

    return None
