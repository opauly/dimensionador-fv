from __future__ import annotations
"""Wizard steps 1–3 shared across all system types. Phase 2."""
import streamlit as st

from config import BRAND_GREEN, BRAND_NAVY
from wizard.state import autosave_if_possible as _autosave


def _metric_card(label: str, value: str, sublabel: str | None = None) -> None:
    """Plain bordered card for a quantity/insight — no pass/fail semantics.
    Same style as wizard/off_grid.py's _metric_card(), ported here for visual
    consistency (this module is shared by all three system types)."""
    sub_html = f'<div style="font-size:0.75rem;color:#6b7280;margin-top:2pt;">{sublabel}</div>' if sublabel else ""
    st.markdown(
        f'<div style="border:1px solid #e5e7eb;border-radius:8px;padding:0.7rem 0.9rem;'
        f'margin-bottom:0.5rem;min-height:5.5rem;">'
        f'<div style="font-size:0.78rem;color:#6b7280;">{label}</div>'
        f'<div style="font-size:1.4rem;font-weight:700;color:{BRAND_NAVY};margin-top:1pt;">{value}</div>'
        f'{sub_html}</div>',
        unsafe_allow_html=True,
    )


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
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w1_back"):
            st.session_state["wizard_step"] = 1
            _autosave()
            st.rerun()
    with col_next:
        if st.button("Siguiente →", key="w1_next", type="primary"):
            result = {"system_type": system_type, "language": language}
            st.session_state["wizard_meta"] = result
            return result

    return None


def step2_client() -> dict | None:
    """
    Client search with live filtering, auto-populate fields, previous proposals
    dropdown, and Empresa field. Returns client dict or None.
    """
    st.markdown("### Paso 2 — Datos del cliente")

    current = st.session_state.get("wizard_client", {})

    # Initialize form widget keys from saved state (only on first render;
    # callbacks may overwrite these later without triggering the conflict error).
    _defaults = {
        "w2_name":     current.get("name") or "",
        "w2_empresa":  current.get("empresa") or "",
        "w2_phone":    current.get("phone") or "",
        "w2_email":    current.get("email") or "",
        "w2_location": current.get("location") or "",
        "w2_nise":     current.get("nise") or "N/A",
    }
    for _k, _v in _defaults.items():
        st.session_state.setdefault(_k, _v)

    # Track which client is actively selected (persists across reruns)
    active_client_id: str | None = (
        st.session_state.get("_w2_selected_client_id") or current.get("client_id")
    )

    # ── Live client search ────────────────────────────────────────────────────
    search_query = st.text_input(
        "Buscar cliente existente",
        placeholder="Escribe el nombre para buscar…",
        key="w2_search",
        on_change=lambda: None,  # triggers rerun on every change, not just Enter
    )

    if search_query and len(search_query) >= 2:
        try:
            from database.clients_db import search_clients
            matches = search_clients(search_query)
            if matches:
                options = {
                    f"{m['name']} — {m.get('phone') or ''} {m.get('email') or ''}".strip(" —"): m
                    for m in matches
                }
                st.session_state["_w2_client_options"] = options

                def _on_client_select() -> None:
                    sel = st.session_state.get("w2_match")
                    opts = st.session_state.get("_w2_client_options", {})
                    if sel and sel != "— Nuevo cliente —" and sel in opts:
                        c = opts[sel]
                        st.session_state["w2_name"]     = c.get("name") or ""
                        st.session_state["w2_empresa"]  = c.get("empresa") or ""
                        st.session_state["w2_phone"]    = c.get("phone") or ""
                        st.session_state["w2_email"]    = c.get("email") or ""
                        st.session_state["w2_location"] = c.get("location") or ""
                        st.session_state["w2_nise"]     = c.get("nise") or "N/A"
                        st.session_state["_w2_selected_client_id"] = c["id"]
                    else:
                        st.session_state["_w2_selected_client_id"] = None

                sel = st.selectbox(
                    "Seleccionar cliente",
                    ["— Nuevo cliente —"] + list(options.keys()),
                    key="w2_match",
                    on_change=_on_client_select,
                )
                if sel != "— Nuevo cliente —" and sel in options:
                    active_client_id = options[sel]["id"]
                    st.session_state["_w2_selected_client_id"] = active_client_id
            else:
                st.caption("No se encontraron clientes con ese nombre.")
        except Exception as e:
            st.caption(f"No se pudo buscar clientes: {e}")

    # ── Previous proposals for selected client ────────────────────────────────
    if active_client_id or st.session_state.get("w2_name"):
        try:
            from database.proposals_db import list_proposals_by_client, format_quote_number
            prev = list_proposals_by_client(
                client_id=active_client_id or "",
                client_name=st.session_state.get("w2_name", ""),
            )
            version_opts: dict[str, dict] = {}
            for p in prev:
                for v in sorted(
                    p.get("proposal_versions") or [],
                    key=lambda x: x["version_number"],
                ):
                    qn = format_quote_number(
                        p.get("quote_number"), p.get("created_at", ""), v["version_number"]
                    )
                    icons = (
                        (" [Enviada]" if v.get("sent_to_client") else "")
                        + (" [Bloqueada]" if v.get("locked") else "")
                    )
                    label = f"{qn} — {p.get('system_type') or ''} — ${v.get('total_usd') or 0:,.0f}{icons}"
                    version_opts[label] = {"proposal_id": p["id"], "version_id": v["id"]}

            if version_opts:
                st.session_state["_w2_version_opts"] = version_opts

                def _on_prev_prop() -> None:
                    sel_v = st.session_state.get("w2_prev_prop")
                    vo = st.session_state.get("_w2_version_opts", {})
                    if sel_v and sel_v != "— Nueva cotización —" and sel_v in vo:
                        from wizard.state import load_draft
                        ch = vo[sel_v]
                        load_draft(ch["version_id"])
                        st.session_state["wizard_proposal_id"] = ch["proposal_id"]
                        st.session_state["wizard_version_id"]  = ch["version_id"]
                        loaded = st.session_state.get("wizard_client", {})
                        st.session_state["w2_name"]     = loaded.get("name") or ""
                        st.session_state["w2_empresa"]  = loaded.get("empresa") or ""
                        st.session_state["w2_phone"]    = loaded.get("phone") or ""
                        st.session_state["w2_email"]    = loaded.get("email") or ""
                        st.session_state["w2_location"] = loaded.get("location") or ""
                        st.session_state["w2_nise"]     = loaded.get("nise") or "N/A"

                st.selectbox(
                    "Cotizaciones anteriores (opcional)",
                    ["— Nueva cotización —"] + list(version_opts.keys()),
                    key="w2_prev_prop",
                    on_change=_on_prev_prop,
                )
        except Exception as e:
            st.caption(f"Error cargando cotizaciones anteriores: {e}")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        name     = st.text_input("Nombre completo *",   key="w2_name")
        empresa  = st.text_input("Empresa (opcional)",  key="w2_empresa")
        phone    = st.text_input("Teléfono",            key="w2_phone")
    with col2:
        email    = st.text_input("Correo electrónico",  key="w2_email")
        location = st.text_input(
            "Ubicación (ciudad, provincia)",
            placeholder="Ej: Atenas, Alajuela",
            key="w2_location",
        )
        nise = st.text_input(
            "NISE (número de cliente en distribuidora)",
            key="w2_nise",
        )

    if not name.strip():
        st.caption("* El nombre del cliente es requerido.")

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Cotizaciones", key="w2_back"):
            st.switch_page("pages/01_proposals.py")
    with col_next:
        if st.button("Siguiente →", key="w2_next", type="primary", disabled=(not name.strip())):
            result = {
                "name":     name.strip(),
                "empresa":  empresa.strip(),
                "phone":    phone.strip(),
                "email":    email.strip(),
                "location": location.strip(),
                "nise":     nise.strip() or "N/A",
            }
            if active_client_id:
                result["client_id"] = active_client_id
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
    pvgis_daily = current.get("pvgis_daily")
    lat = current.get("lat")
    lon = current.get("lon")
    system_type = st.session_state.get("wizard_meta", {}).get("system_type", "grid_zero")
    needs_daily_series = system_type in ("off_grid", "hybrid")

    col_pvgis, _ = st.columns([2, 3])
    with col_pvgis:
        if st.button("Obtener irradiancia solar (PVGIS)", key="w3_pvgis"):
            from calculations.pvgis import fetch_irradiance, fetch_daily_series, geocode_cr

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
                        # Off-Grid/Hybrid also need a real daily-resolution
                        # series for the Step 6 battery-SoC simulation — Grid
                        # Zero has no battery reliability concept, so skip the
                        # extra PVGIS call for it.
                        if needs_daily_series:
                            pvgis_daily = fetch_daily_series(lat, lon)
                        # Persist immediately so subsequent reruns don't lose the data
                        st.session_state["wizard_site"] = {
                            **st.session_state.get("wizard_site", {}),
                            "lat": lat,
                            "lon": lon,
                            "pvgis_data": pvgis_data,
                            "pvgis_daily": pvgis_daily,
                        }
                        st.success(f"Irradiancia obtenida para {lat:.3f}, {lon:.3f}")
                    except Exception as e:
                        st.error(f"Error PVGIS: {e}")

    if pvgis_data:
        monthly = pvgis_data.get("monthly_kwh_kwp", [])
        yearly = pvgis_data.get("yearly_kwh_kwp", 0)
        avg_monthly = round(sum(monthly) / 12, 1) if monthly else 0

        m1, m2 = st.columns(2)
        with m1:
            _metric_card("Irradiancia promedio", f"{avg_monthly} kWh/kWp/mes")
        with m2:
            _metric_card("Irradiancia anual", f"{yearly:.0f} kWh/kWp")

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
                # Explicit headroom above the tallest bar — textposition="outside"
                # doesn't auto-pad the y-axis, so without this the top label (the
                # peak month, e.g. Marzo) gets clipped by the plot area's edge.
                yaxis=dict(title="kWh/kWp", range=[0, max(monthly) * 1.18]),
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
            _autosave()
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
                "pvgis_daily": pvgis_daily,
            }
            st.session_state["wizard_site"] = result
            return result

    if not pvgis_data:
        st.caption("Es necesario obtener los datos de irradiancia para continuar.")

    return None


def monthly_coverage_chart(
    generation_kwh: list[float],
    consumption_kwh: list[float],
    recharge_kwh: list[float] | None = None,
    flag_shortfall: bool = True,
):
    """
    Interactive Plotly twin of proposals/charts.py's monthly_coverage_svg() —
    same monthly data, same color family (imported from there so the two
    never drift apart), hoverable — for live review in the wizard (Step 6).
    The PDF keeps the static SVG version since WeasyPrint can't render
    Plotly; this is only for on-screen use.

    Generación gets its own bar per month; Consumo (+ Recarga de batería,
    stacked on top, when given) gets a second bar alongside it — same
    grouped-then-stacked layout as the PDF chart, built with Plotly's
    offsetgroup mechanism (bars sharing an offsetgroup stack; different
    offsetgroups sit side by side).
    """
    import plotly.graph_objects as go
    from calculations.sizing_grid_zero import MONTHS_ES
    from proposals.charts import GREEN, MINT, AMBER, NAVY

    gen_colors = [
        AMBER if (flag_shortfall and g < c) else GREEN
        for g, c in zip(generation_kwh, consumption_kwh)
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=MONTHS_ES, y=generation_kwh, name="Generación", marker_color=gen_colors,
        offsetgroup=0, hovertemplate="%{x}<br>Generación: %{y:,.0f} kWh<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=MONTHS_ES, y=consumption_kwh, name="Consumo", marker_color=MINT,
        offsetgroup=1, hovertemplate="%{x}<br>Consumo: %{y:,.0f} kWh<extra></extra>",
    ))
    if recharge_kwh:
        fig.add_trace(go.Bar(
            x=MONTHS_ES, y=recharge_kwh, name="Recarga de batería", marker_color=NAVY,
            offsetgroup=1, base=consumption_kwh,
            hovertemplate="%{x}<br>Recarga de batería: %{y:,.0f} kWh<extra></extra>",
        ))
    fig.update_layout(
        barmode="group",
        yaxis_title="kWh/mes",
        height=280,
        margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    return fig


def inject_step6_heading_css() -> None:
    """Two-tier heading system for Step 6 'Equipos', shared by both wizards so
    section/subsection font, weight, color and spacing are identical instead
    of drifting per st.markdown() call across wizard/off_grid.py and
    wizard/grid_zero.py.

    Section (`#### `) marks a major, self-contained topic and is always
    preceded by st.divider(). Subsection (`##### `) elaborates on the
    section directly above it — a secondary chart or detail — and is never
    preceded by a divider; its spacing comes entirely from margin-top here.
    Before this existed, a subsection right after its section (no divider
    between them, by design) had no guaranteed spacing at all and could
    visually collide with the block above it (CONTEXT.md 2026-07-31: the
    Validación del diseño → Margen de diseño case that surfaced this).

    Only affects whichever step is actually mounted in the DOM at render
    time (Streamlit reruns the whole script per step change), so calling
    this from step6_equipment() doesn't leak into other steps' `####`/`#####`
    headings even though the CSS selector itself is unscoped.
    """
    st.markdown(
        """
        <style>
        [data-testid="stMarkdownContainer"] h4 {
            font-size: 1.15rem;
            font-weight: 700;
            color: #1E2D54;
            margin-top: 1.75rem;
            margin-bottom: 0.6rem;
        }
        [data-testid="stMarkdownContainer"] h5 {
            font-size: 0.95rem;
            font-weight: 600;
            color: #374151;
            margin-top: 1.25rem;
            margin-bottom: 0.4rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
