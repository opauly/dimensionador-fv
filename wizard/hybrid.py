from __future__ import annotations
"""Wizard steps 4-8 for Hybrid proposals. Extends Off-Grid (critical-load
backup sizing, unchanged) with a bill-reduction dimension: a hybrid system
is grid-tied, so surplus solar (after critical loads + battery recharge)
AC-couples back to the main panel and offsets the rest of the site's grid
draw. See CONTEXT.md for the full design discussion."""
import streamlit as st

from wizard import off_grid
from wizard.state import autosave_if_possible as _autosave

_AC_COUPLING_NOTE_ES = (
    "Este sistema es híbrido: mantiene conexión a la red eléctrica además del banco de "
    "baterías. El excedente solar no consumido en sitio ni almacenado en batería se "
    "acopla en corriente alterna (AC) hacia la red — sin crédito por excedentes "
    "(no hay medición neta)."
)
_AC_COUPLING_NOTE_EN = (
    "This system is hybrid: it keeps a grid connection in addition to the battery "
    "bank. Solar excess not consumed on-site or stored in the battery is AC-coupled "
    "to the grid — no export credit (no net metering)."
)

# ── Panel scope: does the critical-loads list already represent the whole
# site, or is it a backup-only subset with a separate main panel carrying
# additional (non-backed-up) load? Determines whether Step 6's bill-
# reduction estimate can read the critical-load profile directly (primary)
# or needs a second, independent whole-home consumption input (secondary).
_PANEL_SCOPE_LABELS = {
    "primary": "Tablero principal — estas cargas representan el consumo total del sitio",
    "secondary": "Tablero secundario (respaldo) — hay un tablero principal aparte con cargas adicionales",
}
_PANEL_SCOPE_KEYS = list(_PANEL_SCOPE_LABELS.keys())

_MAIN_PANEL_MODE_LABELS = {"bill": "Factura eléctrica", "loads": "Lista de cargas"}
_MAIN_PANEL_MODE_KEYS = list(_MAIN_PANEL_MODE_LABELS.keys())


def _render_utility_block(current: dict) -> dict | None:
    """
    Distributor + tariff type for the site's single electric meter — needed
    to estimate a bill (and therefore bill reduction) regardless of panel
    scope. Mirrors wizard/grid_zero.py's step4_utility() field shape (so
    calculations/tariff_calculator.py:estimate_bill_crc() works unchanged)
    but lives inside Step 4 here rather than as its own wizard step, since
    Hybrid doesn't dedicate a full step to it the way Grid Zero does.
    """
    from database.tariffs_db import list_distributors, list_tariff_types, get_tariff_tiers

    try:
        distributors = list_distributors()
    except Exception as e:
        st.error(f"No se pudo cargar distribuidoras: {e}")
        return None
    if not distributors:
        st.warning("No hay distribuidoras registradas.")
        return None

    dist_options = {f"{d['abbreviation']} — {d['name']}": d for d in distributors}
    default_dist_idx = next(
        (i for i, d in enumerate(distributors) if d["abbreviation"] == current.get("distributor_abbrev")), 0,
    )
    col1, col2 = st.columns(2)
    with col1:
        dist_label = st.selectbox("Distribuidora *", list(dist_options.keys()), index=default_dist_idx, key="w4h_dist")
    selected_dist = dist_options[dist_label]

    try:
        tariff_types = list_tariff_types(selected_dist["id"])
    except Exception as e:
        st.error(f"No se pudo cargar tarifas: {e}")
        tariff_types = []

    if not tariff_types:
        st.warning("No hay tarifas registradas para esta distribuidora.")
        return None

    with col2:
        tariff_options = {f"{t['code']} — {t['name']}": t for t in tariff_types}
        default_code = current.get("tariff_code", tariff_types[0]["code"])
        default_tariff_idx = next((i for i, t in enumerate(tariff_types) if t["code"] == default_code), 0)
        tariff_label = st.selectbox(
            "Tipo de tarifa *", list(tariff_options.keys()), index=default_tariff_idx, key="w4h_tariff",
        )
    selected_tariff = tariff_options[tariff_label]

    st.caption(
        f"Cargo fijo: ₡{selected_tariff['access_charge_crc']:,.0f}/mes · "
        f"Bomberos: {selected_tariff['bomberos_pct']*100:.2f}% · "
        f"Umbral IVA: {selected_tariff['iva_threshold_kwh']} kWh"
    )

    try:
        tiers = get_tariff_tiers(selected_tariff["id"])
    except Exception as e:
        st.error(f"No se pudo cargar los tramos de tarifa: {e}")
        tiers = []

    return {
        "distributor_id": selected_dist["id"],
        "distributor_name": selected_dist["name"],
        "distributor_abbrev": selected_dist["abbreviation"],
        "tariff_type_id": selected_tariff["id"],
        "tariff_code": selected_tariff["code"],
        "tariff_name": selected_tariff["name"],
        "access_charge_crc": selected_tariff.get("access_charge_crc", 0),
        "bomberos_pct": selected_tariff.get("bomberos_pct", 0.0175),
        "iva_threshold_kwh": selected_tariff.get("iva_threshold_kwh", 280),
        "tiers": tiers,
    }


def _render_main_panel_bill_block(mp_current: dict, utility: dict | None) -> dict:
    """
    "Factura" mode for the main panel's whole-home consumption — average
    monthly kWh, optionally pre-filled from a bill PDF (calculations/
    bill_parser.py, the same AI extraction Grid Zero uses). Deliberately
    lighter than Grid Zero's full Step 5 (12-month table + AI seasonal
    estimation): this is a supporting figure for computing one blended
    bill-reduction estimate, not the proposal's primary consumption driver
    the way it is for Grid Zero.
    """
    st.caption(
        "Sube una factura para prellenar el consumo promedio, o ingrésalo directamente — no se "
        "necesita el historial mes a mes, solo un consumo promedio representativo."
    )
    uploaded_bill = st.file_uploader(
        "PDF de factura (opcional)", type=["pdf"], key="w4h_mp_bill_file", label_visibility="collapsed",
    )
    if st.button("Extraer consumo de la factura", key="w4h_mp_bill_extract", disabled=not uploaded_bill):
        with st.spinner("Analizando factura con IA…"):
            try:
                from calculations.bill_parser import parse_bill_pdf
                data = parse_bill_pdf(uploaded_bill.read())
                kwh_values = [h["kwh"] for h in data["history"] if h.get("kwh")]
                if not kwh_values:
                    st.warning("No se encontró consumo en la factura.")
                else:
                    st.session_state["w4h_mp_avg_kwh_prefill"] = round(sum(kwh_values) / len(kwh_values))
                    st.success(
                        f"Consumo promedio extraído: {st.session_state['w4h_mp_avg_kwh_prefill']} kWh/mes "
                        f"({len(kwh_values)} meses)."
                    )
                    st.rerun()
            except Exception as e:
                st.error(f"Error al analizar la factura: {e}")

    prefill_kwh = st.session_state.pop("w4h_mp_avg_kwh_prefill", None)
    avg_kwh_month = st.number_input(
        "Consumo promedio mensual del tablero principal (kWh) *", min_value=0.0, step=10.0,
        value=float(prefill_kwh if prefill_kwh is not None else (mp_current.get("avg_kwh_month") or 0.0)),
        key="w4h_mp_avg_kwh",
    )

    if utility and avg_kwh_month > 0:
        try:
            from calculations.tariff_calculator import estimate_bill_crc
            current_bill = estimate_bill_crc(avg_kwh_month, utility)
            st.caption(f"Factura estimada actual (sin solar): ₡{current_bill:,.0f}/mes")
        except Exception:
            pass

    return {"mode": "bill", "avg_kwh_month": float(avg_kwh_month)}


def step4_loads() -> dict | None:
    """Critical loads (off_grid's reusable block) + panel-scope selector +
    optional main-panel consumption (needed only when the critical loads
    are a backup-only subset, not the whole site)."""
    st.markdown("### Paso 4 — Cargas eléctricas y perfil de consumo general")
    st.info("Sistema Híbrido: conserva conexión a la red eléctrica además del banco de baterías.")

    current = st.session_state.get("wizard_consumption", {})
    grid_connected = st.checkbox(
        "Conexión a la red en el panel principal",
        value=current.get("grid_connected", True),
        key="w4h_grid_connected",
        help="Desmarcar solo si, a pesar de ser híbrido, no habrá conexión activa a la red en este momento.",
    )

    col1, col2 = st.columns(2)
    with col1:
        autonomy_days = st.slider(
            "Días de autonomía", min_value=0.5, max_value=7.0, step=0.5,
            value=float(current.get("autonomy_days") or 1.0), key="w4og_autonomy",
            help="Días que el banco de baterías debe cubrir sin generación solar. "
                 "Acepta medios días (p. ej. 0.5 para una cabaña de uso ocasional).",
        )
    with col2:
        voltage_label = st.radio(
            "Voltaje de salida requerido",
            ["120V", "120/240V (split-phase)"],
            index=(1 if current.get("voltage_v") == 240 else 0),
            key="w4og_voltage",
            horizontal=True,
        )
        voltage_v = 240 if "240" in voltage_label else 120

    utility: dict | None = None
    panel_scope = current.get("panel_scope", "primary")
    main_panel_result: dict | None = None

    if grid_connected:
        st.divider()
        st.markdown("### Distribuidora y tarifa")
        st.caption("Necesaria para estimar la factura eléctrica y la reducción esperada (Paso 6).")
        utility = _render_utility_block(current.get("utility") or {})

    st.divider()
    st.markdown("### Cargas críticas (respaldo)")
    st.caption(
        "Las cargas que este sistema debe mantener energizadas durante un corte — dimensionan la "
        "batería y el arreglo para autonomía real, simulada día por día (Paso 6)."
    )
    num_bedrooms, home_class, loads_data = off_grid._render_loads_block("w4og", current)

    if grid_connected:
        st.divider()
        st.markdown("### Alcance de las cargas ingresadas")
        st.caption(
            "¿Las cargas críticas de arriba representan todo el consumo del sitio, o son solo un "
            "subconjunto respaldado por batería, con un tablero principal aparte que también "
            "consume de la red?"
        )
        scope_idx = _PANEL_SCOPE_KEYS.index(panel_scope) if panel_scope in _PANEL_SCOPE_KEYS else 0
        panel_scope = st.radio(
            "Alcance", _PANEL_SCOPE_KEYS, index=scope_idx, key="w4h_scope",
            format_func=lambda k: _PANEL_SCOPE_LABELS[k],
        )

        if panel_scope == "secondary":
            st.divider()
            # Bordered container + an st.info() banner (not just a heading) —
            # the loads-mode branch below renders the exact same widgets as
            # the critical-loads block above it (same _render_loads_block()),
            # so without a real visual boundary the two read as one long,
            # confusing repeat of the same form rather than two independent
            # inputs. A plain "###" heading wasn't enough of a break.
            with st.container(border=True):
                st.info(
                    "**Consumo del tablero principal** — independiente de las cargas críticas de "
                    "arriba. El excedente solar (después de cubrir las cargas críticas y recargar la "
                    "batería) se acopla en AC hacia este tablero; esto estima cuánto de esa energía "
                    "realmente reduce la factura."
                )
                mp_current = current.get("main_panel") or {}
                mode_default = mp_current.get("mode", "bill")
                mode_idx = _MAIN_PANEL_MODE_KEYS.index(mode_default) if mode_default in _MAIN_PANEL_MODE_KEYS else 0
                mp_mode = st.radio(
                    "¿Cómo quieres ingresar el consumo del tablero principal?",
                    _MAIN_PANEL_MODE_KEYS, index=mode_idx, key="w4h_mp_mode", horizontal=True,
                    format_func=lambda k: _MAIN_PANEL_MODE_LABELS[k],
                )
                if mp_mode == "bill":
                    main_panel_result = _render_main_panel_bill_block(mp_current, utility)
                else:
                    st.markdown("##### Cargas del tablero principal")
                    st.caption(
                        "Mismo método que las cargas críticas de arriba, pero para un tablero "
                        "distinto — útil cuando el sitio aún no tiene factura (p. ej. una casa no "
                        "construida, solo con planos eléctricos)."
                    )
                    mp_num_bedrooms, mp_home_class, mp_loads_data = off_grid._render_loads_block("w4h_mp", mp_current)
                    main_panel_result = {
                        "mode": "loads",
                        "num_bedrooms": mp_num_bedrooms,
                        "home_class": mp_home_class,
                        "loads_display": mp_loads_data,
                        "loads": off_grid._loads_to_taxonomy_list(mp_loads_data),
                        # profile/avg_kwh_month computed in Step 5 once build_load_profile() runs
                        "profile": mp_current.get("profile"),
                        "avg_kwh_month": mp_current.get("avg_kwh_month"),
                    }

    def _build_consumption_result() -> dict:
        return {
            **current,
            "grid_connected": grid_connected,
            "autonomy_days": float(autonomy_days),
            "voltage_v": voltage_v,
            "num_bedrooms": num_bedrooms,
            "home_class": home_class,
            "loads_display": loads_data,
            "loads": off_grid._loads_to_taxonomy_list(loads_data),
            "utility": utility,
            "panel_scope": panel_scope,
            "main_panel": main_panel_result,
        }

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w4h_back"):
            st.session_state["wizard_consumption"] = _build_consumption_result()
            st.session_state["wizard_step"] = 3
            _autosave()
            st.rerun()
    with col_next:
        has_loads = len(loads_data) > 0
        if st.button("Siguiente →", key="w4h_next", type="primary", disabled=not has_loads):
            result = _build_consumption_result()
            st.session_state["wizard_consumption"] = result
            return result

    return None


def step5_demand() -> dict | None:
    """Critical-load profile (off_grid's block) + main-panel profile when
    panel_scope="secondary" and mode="loads" (bill mode needs no extra
    computation — avg_kwh_month was already collected in Step 4)."""
    st.markdown("### Paso 5 — Perfil de demanda diaria")

    current = st.session_state.get("wizard_consumption", {})
    loads = current.get("loads", [])
    site = st.session_state.get("wizard_site", {})
    lat, lon = site.get("lat"), site.get("lon")

    st.markdown("##### Cargas críticas (respaldo)")
    profile, total_kwh_day = off_grid._render_demand_profile_block(
        "w5og", loads, current.get("num_bedrooms", 3), current.get("home_class", "standard"), lat, lon,
    )

    main_panel = current.get("main_panel")
    mp_profile = main_panel.get("profile") if main_panel else None
    mp_daily_kwh = 0.0
    mp_loads_mode = bool(main_panel and main_panel.get("mode") == "loads")
    if mp_loads_mode:
        st.divider()
        st.markdown("##### Tablero principal")
        mp_profile, mp_daily_kwh = off_grid._render_demand_profile_block(
            "w5h_mp", main_panel.get("loads", []),
            main_panel.get("num_bedrooms", 3), main_panel.get("home_class", "standard"),
            lat, lon, show_charts=False,
        )

    # Atrás/Siguiente render unconditionally — neither profile being None
    # (not yet calculated) should strand the engineer with no way back to
    # Step 4. Siguiente is disabled until every profile this draft actually
    # needs (critical, plus main-panel when in loads mode) is calculated.
    can_continue = profile is not None and total_kwh_day > 0 and (not mp_loads_mode or mp_profile is not None)

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w5h_back"):
            st.session_state["wizard_consumption"] = _build_step5_result(
                current, profile, total_kwh_day, main_panel, mp_profile, mp_daily_kwh,
            )
            st.session_state["wizard_step"] = 4
            _autosave()
            st.rerun()
    with col_next:
        if st.button("Siguiente →", key="w5h_next", type="primary", disabled=not can_continue):
            result = _build_step5_result(current, profile, total_kwh_day, main_panel, mp_profile, mp_daily_kwh)
            st.session_state["wizard_consumption"] = result
            return result

    return None


def _build_step5_result(
    current: dict, profile: dict, total_kwh_day: float,
    main_panel: dict | None, mp_profile: dict | None, mp_daily_kwh: float,
) -> dict:
    result = {**current, "profile": profile, "daily_kwh": total_kwh_day}
    if main_panel and main_panel.get("mode") == "loads":
        result["main_panel"] = {
            **main_panel,
            "profile": mp_profile,
            "avg_kwh_month": round(mp_daily_kwh * 30.4, 1),
        }
    return result


def step6_equipment() -> dict | None:
    return off_grid.step6_equipment()


def step7_costs() -> dict | None:
    return off_grid.step7_costs()


def step8_review(site=None, loads=None, equipment=None, costs=None, language: str = "es") -> None:
    """Includes the AC coupling note in the proposal text before generating the PDF."""
    note = _AC_COUPLING_NOTE_ES if language == "es" else _AC_COUPLING_NOTE_EN
    current_text = st.session_state.get("wizard_proposal_text", "")
    if note not in current_text:
        st.session_state["wizard_proposal_text"] = (current_text + "\n\n" + note).strip()

    off_grid.step8_review(site=site, loads=loads, equipment=equipment, costs=costs, language=language)
