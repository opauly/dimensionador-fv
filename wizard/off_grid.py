from __future__ import annotations
"""Wizard steps 4-8 for Off-Grid proposals. Phase 5."""
import pandas as pd
import streamlit as st

from wizard.state import autosave_if_possible as _autosave
from proposals.generator import _site_location
from config import BRAND_GREEN, BRAND_GREEN_LIGHT, BRAND_NAVY

from calculations.load_profile_off_grid import CATEGORY_LABELS_ES, COMMON_LOADS_CATALOG_V1, BEHAVIOR_KWH_PER_BEDROOM_DAY_V1

_CATEGORY_AUTO_LABEL = "(Automático)"
_CATEGORY_LABEL_TO_KEY = {v: k for k, v in CATEGORY_LABELS_ES.items()}
_CATEGORY_SELECT_OPTIONS = [_CATEGORY_AUTO_LABEL] + list(CATEGORY_LABELS_ES.values())

_DEFAULT_LOADS = [
    {"Descripción": "Refrigerador", "Cantidad": 1, "Potencia (kW)": 0.5, "Categoría": CATEGORY_LABELS_ES["fixed_cycling"]},
]
# Iluminación general / Tomacorrientes are deliberately NOT default rows — general
# lighting/outlet use is always covered by the habitaciones/espacios × nivel de uso
# aggregate (Paso 5), never by an individual load's own wattage, so listing them
# here would suggest they need to be itemized when they don't.

_HOME_CLASS_LABELS = {
    "Básica": "basic",
    "Estándar": "standard",
    "Premium": "premium",
}

# Applies to homes (dormitorios) and small businesses (oficinas/espacios) alike —
# "espacio" is deliberately generic rather than "dormitorio" so off-grid/hybrid
# quotes for commercial sites don't read as residential-only.
# Describes ONLY lighting + always-on receptacle load. Electrodomésticos
# (microondas, TV, lavadora, cafetera, plantilla) are no longer covered here —
# they're listed individually below and sized on their own. Keep this text in
# sync with BEHAVIOR_KWH_PER_BEDROOM_DAY_V1's scope or the two will drift.
_USAGE_LEVEL_DESCRIPTIONS = {
    "Básica": "iluminación LED puntual y pocos tomacorrientes en uso (cargadores, reloj).",
    "Estándar": "iluminación completa y tomacorrientes de uso continuo (computadora, router, cargadores).",
    "Premium": "iluminación amplia y varios equipos siempre conectados (computadoras, router, equipo de red).",
}
_USAGE_LEVEL_EXAMPLE_SPACES = 3  # reference count used in the visible kWh/day examples below

_CONFIDENCE_BADGES = {
    "measured": ("📏 Medido", "#166534"),
    "api_calculated": ("🌐 API climática", "#1d4ed8"),
    "benchmark": ("📊 Tabla de referencia", "#6b7280"),
    "user_confirmed": ("✅ Confirmado por cliente", "#166534"),
    "default_assumed": ("⚠️ Estimado genérico", "#b45309"),
    # Peak-watts-only line: its energy is already inside the "Uso general"
    # aggregate, so kWh/día shows 0 by design. Deliberately NOT reusing
    # default_assumed — that badge drives the "revísalas antes de continuar"
    # warning, and there's nothing to review here.
    "power_only": ("⚡ Solo potencia (W)", "#1d4ed8"),
}

# Distinct color per load category for the Step 5 consumption-by-category chart.
_CATEGORY_CHART_COLORS = {
    "fixed_cycling": BRAND_GREEN,
    "behavior_driven": BRAND_NAVY,
    "climate_driven": "#1d4ed8",
    "discretionary": "#b45309",
    "ignition_only": "#6b7280",
    "appliance": "#7c3aed",
}


# ── Step 4 — Cargas eléctricas y perfil de consumo general ───────────────────

def step4_loads() -> dict | None:
    """Loads table (name + qty + nameplate kW, no hours), general-use profile, autonomy, voltage."""
    st.markdown("### Paso 4 — Cargas eléctricas y perfil de consumo general")

    current = st.session_state.get("wizard_consumption", {})

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

    st.divider()
    st.markdown("### Cargas eléctricas")

    # ── Subsection A: general-use aggregate (behavior_driven) ───────────────
    st.markdown("##### Uso general")
    st.caption(
        "Cubre iluminación y el consumo de fondo de tomacorrientes — lo que está siempre "
        "conectado (computadora, router, reloj, cargadores). **No cubre electrodomésticos** "
        "(microondas, TV, lavadora, cafetera, plantilla): esos se listan abajo y se dimensionan "
        "por separado. Aplica tanto para viviendas (usa dormitorios) como para negocios pequeños "
        "(usa oficinas u otros espacios equivalentes)."
    )
    col1, col2 = st.columns(2)
    with col1:
        num_bedrooms = st.number_input(
            "Habitaciones / espacios", min_value=1, max_value=15,
            value=int(current.get("num_bedrooms") or 3), key="w4og_bedrooms",
            help="Para una vivienda: número de dormitorios. Para un negocio: número de oficinas "
                 "u otros espacios equivalentes. Se usa como el multiplicador directo del consumo "
                 "general (Paso 5): kWh/día/espacio × espacios.",
        )
    with col2:
        class_label = st.selectbox(
            "Nivel de uso general", list(_HOME_CLASS_LABELS.keys()),
            index=list(_HOME_CLASS_LABELS.values()).index(current.get("home_class", "standard")),
            key="w4og_class",
        )
        home_class = _HOME_CLASS_LABELS[class_label]

    # Visible explanation with a concrete kWh/day example per tier — kWh/day alone
    # isn't a tangible unit for most customers, so tie it to a fixed reference
    # space count and pull rates straight from the benchmark table (never
    # hardcoded here) so the copy can't drift out of sync with the calculation.
    n = _USAGE_LEVEL_EXAMPLE_SPACES
    st.markdown("\n".join(
        f"- **{label}** ({BEHAVIOR_KWH_PER_BEDROOM_DAY_V1[key]:.1f} kWh/día/espacio) — "
        f"{_USAGE_LEVEL_DESCRIPTIONS[label]} "
        f"*Ej.: {n} espacios ≈ {BEHAVIOR_KWH_PER_BEDROOM_DAY_V1[key] * n:.1f} kWh/día.*"
        for label, key in _HOME_CLASS_LABELS.items()
    ))

    st.divider()

    # ── Subsection B: individually-sized loads ───────────────────────────────
    st.markdown("##### Cargas individuales")
    st.caption(
        "Ingresa nombre, cantidad y potencia nominal de cada carga que necesita dimensionamiento "
        "individual: refrigerador/bombas, A/C, electrodomésticos (microondas, TV, lavadora, "
        "cafetera, plantilla), cargas discrecionales (EV, piscina, riego) y calentadores/cocinas "
        "a gas. **No se pide horas de uso** — el sistema estima el consumo diario real según el "
        "tipo de carga (ver Paso 5)."
    )

    # ── Import desde tablero (photo/PDF, no hours asked — see module docstring) ──
    with st.expander("📋 Importar desde tablero eléctrico", expanded=False):
        st.caption(
            "Sube una imagen o PDF del tablero eléctrico. La IA extrae nombre, cantidad y "
            "potencia nominal — no estima horas de uso ni categoriza (eso ocurre en el Paso 5)."
        )
        uploaded_tablero = st.file_uploader(
            "Imagen (JPG/PNG) o PDF del tablero",
            type=["jpg", "jpeg", "png", "pdf"],
            key="w4og_tablero_file",
        )
        if uploaded_tablero and st.button("⚡ Extraer cargas del tablero", key="w4og_tablero_extract"):
            with st.spinner("Analizando tablero con IA…"):
                try:
                    from calculations.tablero_parser import parse_tablero_off_grid
                    extracted = parse_tablero_off_grid(uploaded_tablero.read(), uploaded_tablero.type)
                    new_rows = [
                        {"Descripción": r["Descripción"], "Cantidad": r["Cantidad"],
                         "Potencia (kW)": r["Potencia (kW)"], "Categoría": _CATEGORY_AUTO_LABEL}
                        for r in extracted
                    ]
                    st.session_state["w4og_loads_data"] = (
                        st.session_state.get("w4og_loads_data", []) + new_rows
                    )
                    st.session_state["w4og_loads_ver"] = st.session_state.get("w4og_loads_ver", 0) + 1
                    st.success(f"{len(extracted)} circuitos extraídos. Revisa y ajusta la tabla abajo.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al analizar el tablero: {e}")

    # ── Add from common-loads catalog ────────────────────────────────────────
    # The multiselect uses a versioned key (mirrors grid_zero.py's w5_loads_{ver}
    # pattern) so "Agregar" can reset the picker by rendering a fresh widget
    # instance next run — writing directly to an already-instantiated widget's
    # session_state key raises StreamlitAPIException, which is what a first
    # version of this control did.
    catalog_options = {f"{c['name']} ({c['nameplate_kw']} kW)": c for c in COMMON_LOADS_CATALOG_V1}
    catalog_ver = st.session_state.get("w4og_catalog_ver", 0)
    col_pick, col_add = st.columns([4, 1])
    with col_pick:
        picked_labels = st.multiselect(
            "Agregar cargas comunes",
            list(catalog_options.keys()),
            key=f"w4og_catalog_pick_{catalog_ver}",
            help="Cada carga trae potencia típica y categoría precargadas — ambas editables después de agregar.",
        )
    with col_add:
        st.markdown("<div style='height:1.7rem;'></div>", unsafe_allow_html=True)
        if st.button("+ Agregar", key="w4og_catalog_add", disabled=not picked_labels, use_container_width=True):
            new_rows = [
                {
                    "Descripción": catalog_options[lbl]["name"],
                    "Cantidad": 1,
                    "Potencia (kW)": catalog_options[lbl]["nameplate_kw"],
                    "Categoría": CATEGORY_LABELS_ES[catalog_options[lbl]["category"]],
                }
                for lbl in picked_labels
            ]
            st.session_state["w4og_loads_data"] = (
                st.session_state.get("w4og_loads_data", []) + new_rows
            )
            st.session_state["w4og_loads_ver"] = st.session_state.get("w4og_loads_ver", 0) + 1
            st.session_state["w4og_catalog_ver"] = catalog_ver + 1
            st.rerun()

    loads_ver = st.session_state.get("w4og_loads_ver", 0)
    base_loads = st.session_state.get("w4og_loads_data", current.get("loads_display") or _DEFAULT_LOADS)
    for row in base_loads:
        row.setdefault("Categoría", _CATEGORY_AUTO_LABEL)

    edited_loads = st.data_editor(
        pd.DataFrame(base_loads),
        column_config={
            "Descripción": st.column_config.TextColumn("Descripción", width="large"),
            "Cantidad": st.column_config.NumberColumn(min_value=1, step=1, format="%d", width="small"),
            "Potencia (kW)": st.column_config.NumberColumn(min_value=0.0, format="%.2f", width="small"),
            "Categoría": st.column_config.SelectboxColumn(
                options=_CATEGORY_SELECT_OPTIONS, width="medium", required=True,
                help="Deja en '(Automático)' para que la IA clasifique el tipo de carga en el Paso 5, "
                     "o elige manualmente si ya sabes a cuál de las 5 categorías pertenece.",
            ),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"w4og_loads_{loads_ver}",
    )
    loads_data = edited_loads.to_dict("records")
    st.session_state["w4og_loads_data"] = loads_data

    def _build_consumption_result() -> dict:
        return {
            **current,
            "num_bedrooms": int(num_bedrooms),
            "home_class": home_class,
            "autonomy_days": float(autonomy_days),
            "voltage_v": voltage_v,
            "loads_display": loads_data,  # keeps the Categoría column round-trippable across reruns
            "loads": [
                {
                    "name": r.get("Descripción", ""),
                    "quantity": int(r.get("Cantidad") or 1),
                    "nameplate_kw": float(r.get("Potencia (kW)") or 0),
                    "category": _CATEGORY_LABEL_TO_KEY.get(r.get("Categoría")),
                }
                for r in loads_data
                if r.get("Descripción")
            ],
        }

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w4og_back"):
            # Persist the table exactly like "Siguiente" does before leaving
            # the page — otherwise any rows added/edited here since the last
            # "Siguiente" click only live in st.session_state["w4og_loads_data"]
            # (this step's own live-edit cache), never reach
            # wizard_consumption, and so never reach _autosave()'s Supabase
            # write. A session that ends before "Siguiente" is clicked again
            # (browser closed, draft resumed later) would silently lose them
            # — the resumed Step 4 table would show the last-saved (shorter)
            # list even though Step 5 onward, in that lost session, had
            # already computed a profile from the fuller one.
            st.session_state["wizard_consumption"] = _build_consumption_result()
            st.session_state["wizard_step"] = 3
            _autosave()
            st.rerun()
    with col_next:
        has_loads = len(loads_data) > 0
        if st.button("Siguiente →", key="w4og_next", type="primary", disabled=not has_loads):
            result = _build_consumption_result()
            st.session_state["wizard_consumption"] = result
            return result

    return None


# ── Step 5 — Perfil de demanda calculado ─────────────────────────────────────

def step5_demand() -> dict | None:
    """Runs build_load_profile(), shows the confidence-tagged breakdown, allows manual override."""
    st.markdown("### Paso 5 — Perfil de demanda diaria")

    current = st.session_state.get("wizard_consumption", {})
    loads = current.get("loads", [])
    site = st.session_state.get("wizard_site", {})
    lat, lon = site.get("lat"), site.get("lon")

    profile = st.session_state.get("w5og_profile") or current.get("profile")

    if st.button("🔄 Calcular perfil de consumo", key="w5og_calc"):
        with st.spinner("Clasificando cargas y calculando consumo diario…"):
            from calculations.load_profile_off_grid import build_load_profile
            profile = build_load_profile(
                loads,
                num_bedrooms=current.get("num_bedrooms", 3),
                home_class=current.get("home_class", "standard"),
                lat=lat, lon=lon,
            )
            st.session_state["w5og_profile"] = profile

    if not profile:
        st.info("Haz clic en 'Calcular perfil de consumo' para continuar.")
        return None

    rows = []
    for line in profile["lines"]:
        badge, color = _CONFIDENCE_BADGES.get(line["confidence"], (line["confidence"], "#6b7280"))
        rows.append({
            "Carga": line["load_name"],
            "Categoría": line["category"],
            "Cant.": line["quantity"],
            "kWh/día": line["estimated_kwh_day"],
            "Fuente": badge,
            "_color": color,
            "Detalle": line["source_detail"],
        })
    if profile.get("behavior_aggregate"):
        agg = profile["behavior_aggregate"]
        badge, color = _CONFIDENCE_BADGES.get(agg["confidence"], (agg["confidence"], "#6b7280"))
        # "Cant." shows num_bedrooms (espacios) — the actual multiplier behind kWh/día —
        # not agg["load_count"] (how many *individually listed* loads happened to be
        # tagged behavior_driven, often 0 since lighting/outlets are rarely itemized).
        # Showing load_count here previously made the row read as "0 units × rate =
        # kWh", which looks like a bug even though the aggregate is intentionally
        # always applied regardless of load_count (see build_load_profile()).
        rows.append({
            "Carga": "Cargas generales (uso general agregado)",
            "Categoría": "behavior_driven",
            "Cant.": current.get("num_bedrooms", 0),
            "kWh/día": agg["kwh_day"],
            "Fuente": badge,
            "_color": color,
            "Detalle": agg["source_detail"],
        })

    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df.drop(columns=["_color"]),
        column_config={
            "Carga": st.column_config.TextColumn(disabled=True, width="medium"),
            "Categoría": st.column_config.TextColumn(disabled=True, width="small"),
            "Cant.": st.column_config.NumberColumn(disabled=True, width="small"),
            "kWh/día": st.column_config.NumberColumn(
                min_value=0.0, format="%.2f", width="small",
                help="Editable — ajusta manualmente si el ingeniero tiene mejor información.",
            ),
            "Fuente": st.column_config.TextColumn(disabled=True, width="medium"),
            "Detalle": st.column_config.TextColumn(disabled=True, width="large"),
        },
        use_container_width=True,
        hide_index=True,
        key="w5og_table",
    )

    default_count = sum(1 for r in rows if r["Fuente"] == _CONFIDENCE_BADGES["default_assumed"][0])
    if default_count:
        st.warning(
            f"⚠️ {default_count} línea(s) usan un estimado genérico (sin datos climáticos, tabla o "
            "respuesta del cliente) — revísalas antes de continuar."
        )

    total_kwh_day = round(edited["kWh/día"].sum(), 2)
    st.metric("Consumo diario total estimado", f"{total_kwh_day:,.2f} kWh/día")

    if total_kwh_day > 0:
        st.markdown("##### Consumo por categoría")
        st.caption("Cómo se distribuye el consumo diario estimado entre las 5 categorías de carga.")
        cat_totals = edited.groupby("Categoría")["kWh/día"].sum().sort_values()
        import plotly.graph_objects as go
        fig = go.Figure(go.Bar(
            x=cat_totals.values,
            y=[CATEGORY_LABELS_ES.get(k, k) for k in cat_totals.index],
            orientation="h",
            marker_color=[_CATEGORY_CHART_COLORS.get(k, "#9ca3af") for k in cat_totals.index],
            text=[f"{v:.2f} kWh/día" for v in cat_totals.values],
            textposition="outside",
        ))
        fig.update_layout(
            xaxis=dict(title="kWh/día", range=[0, cat_totals.max() * 1.25]),
            height=220,
            margin=dict(t=10, b=10, l=10, r=10),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("##### Perfil horario ilustrativo (IA)")
        st.caption(
            "⚠️ Ilustrativo únicamente — generado por IA para ayudar a visualizar cuándo cada tipo de "
            "carga tiende a consumir durante el día. No se usa para el dimensionamiento del sistema "
            "(ese cálculo sigue siendo determinístico, por categoría, en kWh/día)."
        )
        shape_key = "w5og_hourly_shape"
        if st.button("🎨 Generar perfil horario ilustrativo", key="w5og_hourly_btn"):
            with st.spinner("Generando perfil horario con IA…"):
                from calculations.load_profile_off_grid import estimate_hourly_shape_illustrative
                load_names = [r["Carga"] for r in rows if r["Categoría"] != "behavior_driven"] or None
                st.session_state[shape_key] = estimate_hourly_shape_illustrative(
                    list(cat_totals.index), load_names=load_names,
                )
        shapes = st.session_state.get(shape_key)
        if shapes:
            hours = list(range(24))
            hourly_fig = go.Figure()
            for cat in cat_totals.index:
                weights = shapes.get(cat)
                if not weights:
                    continue
                total_w = sum(weights) or 1
                kwh_day = cat_totals[cat]
                values = [kwh_day * w / total_w for w in weights]
                hourly_fig.add_trace(go.Scatter(
                    x=hours, y=values, mode="lines", stackgroup="one",
                    name=CATEGORY_LABELS_ES.get(cat, cat),
                    line=dict(width=0.5, color=_CATEGORY_CHART_COLORS.get(cat, "#9ca3af")),
                    fillcolor=_CATEGORY_CHART_COLORS.get(cat, "#9ca3af"),
                ))
            hourly_fig.update_layout(
                xaxis=dict(title="Hora del día", tickmode="linear", tick0=0, dtick=2),
                yaxis_title="kWh (ilustrativo)",
                height=280,
                margin=dict(t=10, b=10, l=10, r=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(hourly_fig, use_container_width=True)

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w5og_back"):
            # Same fix as Step 4's Atrás: persist the calculated profile
            # before navigating away, or a session that ends here (without
            # ever clicking "Siguiente") loses it on resume.
            st.session_state["wizard_consumption"] = {
                **current,
                "profile": profile,
                "daily_kwh": total_kwh_day,
            }
            st.session_state["wizard_step"] = 4
            _autosave()
            st.rerun()
    with col_next:
        if st.button("Siguiente →", key="w5og_next", type="primary", disabled=(total_kwh_day <= 0)):
            result = {
                **current,
                "profile": profile,
                "daily_kwh": total_kwh_day,
            }
            st.session_state["wizard_consumption"] = result
            return result

    return None


# ── Step 6 — Equipos ─────────────────────────────────────────────────────────

_MAX_CHARGE_CONTROLLERS = 4  # cap on how many CCs we'll parallel before calling the array unbuildable


def _og_scenario_projection(
    combo: dict,
    avg_peak_sun_hours: float,
    daily_kwh: float,
    autonomy_days: float,
    dod_pct: float,
    battery_voltage_v: float,
    battery_capacity_kwh: float,
    daily_kwh_kwp: list[float] | None = None,
) -> dict:
    """
    Per-scenario projection for the Opción 1/2 cards: what a given array
    combo (panels_per_string/strings/system_kw) actually delivers — daily
    generation, the battery bank it would need at the current autonomy
    setting, and whether it covers the site's daily consumption. Mirrors
    wizard/grid_zero.py's _scenario_projection(), off-grid flavored (battery
    coverage instead of zero-export grid savings).

    `daily_kwh_kwp`, when given (the real PVGIS daily series — see
    calculations/pvgis.py: fetch_daily_series()), also runs
    simulate_battery_soc() against this specific manual array + the battery
    bank it sizes here, so the manual-mode card gets the same real
    "Aprovechamiento solar" number as the auto scenarios instead of an
    approximation — omitted (utilization_pct=None) if the series isn't
    available (e.g. an older draft that never fetched it).
    """
    from calculations.sizing_off_grid import size_battery_bank
    derating = 1 - 0.20  # matches size_array()'s default system_losses_pct
    daily_generation = round(combo["system_kw"] * avg_peak_sun_hours * derating, 2)
    bank = size_battery_bank(
        daily_kwh=daily_generation, autonomy_days=autonomy_days, dod_pct=dod_pct,
        battery_voltage_v=battery_voltage_v, battery_capacity_kwh=battery_capacity_kwh,
    )
    margin_kwh = round(max(0, daily_generation - daily_kwh), 2)

    utilization_pct = None
    if daily_kwh_kwp and len(daily_kwh_kwp) >= 300 and bank["total_kwh_installed"] > 0:
        from calculations.sizing_off_grid import simulate_battery_soc
        daily_gen_series = [v * combo["system_kw"] * derating for v in daily_kwh_kwp]
        sim = simulate_battery_soc(
            daily_gen_series, daily_kwh, bank["total_kwh_installed"], dod_pct, 100 - dod_pct,
        )
        utilization_pct = sim["utilization_pct"]

    return {
        "daily_generation": daily_generation,
        "battery_count": bank["battery_count"],
        "battery_kwh": bank["total_kwh_installed"],
        "covers": daily_generation >= daily_kwh,
        "margin_kwh": margin_kwh,
        "utilization_pct": utilization_pct,
    }


def _spec_card(title: str, lines: list[str]) -> None:
    """Equipment spec card — one spec per line, matching grid_zero.py's established pattern
    (CONTEXT.md Phase 4: "one spec per line, no multi-value concatenation")."""
    rows = "<br>".join(lines)
    st.markdown(
        f'<div style="background:{BRAND_GREEN_LIGHT};border-radius:6px;padding:0.6rem 1rem;'
        f'font-size:0.85rem;line-height:1.8;margin-bottom:0.75rem;">'
        f'<b>{title}</b><br>{rows}</div>',
        unsafe_allow_html=True,
    )


def _metric_card(label: str, value: str, sublabel: str | None = None) -> None:
    """Plain bordered card for a quantity/insight — no pass/fail semantics."""
    sub_html = f'<div style="font-size:0.75rem;color:#6b7280;margin-top:2pt;">{sublabel}</div>' if sublabel else ""
    st.markdown(
        f'<div style="border:1px solid #e5e7eb;border-radius:8px;padding:0.7rem 0.9rem;'
        f'margin-bottom:0.5rem;min-height:5.5rem;">'
        f'<div style="font-size:0.78rem;color:#6b7280;">{label}</div>'
        f'<div style="font-size:1.4rem;font-weight:700;color:{BRAND_NAVY};margin-top:1pt;">{value}</div>'
        f'{sub_html}</div>',
        unsafe_allow_html=True,
    )


_CHECK_STATUS_STYLE = {
    "ok":   {"icon": "✅", "border": "#16a34a", "bg": "#f0fdf4"},
    "fail": {"icon": "❌", "border": "#dc2626", "bg": "#fef2f2"},
    "info": {"icon": "ℹ️", "border": "#9ca3af", "bg": "#f9fafb"},
}


_CHIP_STYLE = "background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;padding:2px 9px;font-size:0.8rem;"


def _chip_row(chips: list[str]) -> None:
    """Compact horizontal info-chip row — matches wizard/grid_zero.py's Opción 2
    manual-config chip row style, ported here for visual consistency across
    both wizards (CONTEXT.md 2026-07-25 chart-feedback round)."""
    spans = "".join(f'<span style="{_CHIP_STYLE}">{c}</span>' for c in chips)
    st.markdown(f'<div style="display:flex;gap:0.5rem;flex-wrap:wrap;margin:0.4rem 0 0.9rem;">{spans}</div>', unsafe_allow_html=True)


def _param_row(label: str, value: str, ok: bool, limit_str: str) -> None:
    """Inline label/value/limit validation row — same CSS-grid pattern as
    wizard/grid_zero.py's _mppt_param_row(), ported here for visual
    consistency (CONTEXT.md 2026-07-25 chart-feedback round)."""
    color  = "#166534" if ok else "#991b1b"
    bg     = "#f0fdf4" if ok else "#fef2f2"
    border = "#86efac" if ok else "#fca5a5"
    icon   = "✓" if ok else "✗"
    st.markdown(
        f'<div style="display:grid;grid-template-columns:44% 28% 28%;align-items:center;'
        f'background:{bg};border:1px solid {border};border-radius:4px;'
        f'padding:3px 10px;margin-bottom:3px;font-size:0.83rem;">'
        f'<span style="color:{color};font-weight:600;">{icon}&nbsp;{label}</span>'
        f'<span style="color:{color};text-align:center;">{value}</span>'
        f'<span style="color:#6b7280;font-size:0.75rem;text-align:right;">{limit_str}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def step6_equipment() -> dict | None:
    """Panel + inverter (type='hybrid') + battery + charge controller selection, sizing, split-phase check."""
    st.markdown("### Paso 6 — Equipos")
    from wizard.common import inject_step6_heading_css
    inject_step6_heading_css()

    from database.equipment_db import (
        list_panels, list_inverters, list_batteries, list_charge_controllers, list_monitoring_devices,
    )
    from calculations.sizing_off_grid import size_battery_bank, check_split_phase, generate_reliability_scenarios
    from calculations.mppt import check_charge_controller_design_multi

    current = st.session_state.get("wizard_equipment", {})
    consumption = st.session_state.get("wizard_consumption", {})
    site = st.session_state.get("wizard_site", {})

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
        st.warning(
            "Faltan equipos en el catálogo (panel, inversor híbrido, batería o controlador de carga)."
        )
        return None

    panel_options = {f"{p['brand']} {p['model']} — {p['wp']}W": p for p in panels}
    inverter_options = {f"{i['brand']} {i['model']} — {i['kw']} kW": i for i in inverters}
    battery_options = {f"{b['brand']} {b['model']} — {b['capacity_kwh']} kWh": b for b in batteries}
    cc_options = {f"{c['brand']} {c['model']} — {c['vin_max']:.0f}V/{c['imax_in']:.0f}A": c for c in charge_controllers}
    monitoring_options = {"— Sin monitoreo —": None} | {f"{m['brand']} {m['model']}": m for m in monitoring_devices}

    default_panel_idx = next((i for i, p in enumerate(panels) if p["id"] == current.get("panel_id")), 0)
    default_inv_idx = next((i for i, inv in enumerate(inverters) if inv["id"] == current.get("inverter_id")), 0)
    default_bat_idx = next((i for i, b in enumerate(batteries) if b["id"] == current.get("battery_id")), 0)
    default_cc_idx = next((i for i, c in enumerate(charge_controllers) if c["id"] == current.get("charge_controller_id")), 0)
    default_mon_label = next(
        (lbl for lbl, m in monitoring_options.items() if m and m["id"] == current.get("monitoring_id")),
        "— Sin monitoreo —",
    )

    st.markdown("#### Selección de equipos")
    # Paired per-row columns (Panel|Inversor, Controlador|Batería, Monitoreo)
    # instead of one 2-column split holding 3 stacked items on one side and 2
    # on the other — that layout let a taller card (or the split-phase
    # warning) on one side push everything below it out of alignment with
    # its counterpart on the other side. Each row here is its own independent
    # st.columns(2) call, so row N always starts level regardless of how tall
    # row N-1's cards were — matches wizard/grid_zero.py's clean one-pair-per-row
    # equipment block alignment (CONTEXT.md 2026-07-25 entry).
    row1_col1, row1_col2 = st.columns(2)
    with row1_col1:
        panel_label = st.selectbox("Panel solar *", list(panel_options.keys()), index=default_panel_idx, key="w6og_panel")
        panel = panel_options[panel_label]
        panel_area = round(float(panel.get("width_m") or 0) * float(panel.get("height_m") or 0), 2)
        _spec_card(f"{panel['brand']} {panel['model']}", [
            f"Potencia: {panel['wp']} W",
            f"Voc: {panel['voc']} V",
            f"Vmp: {panel['vmp']} V",
            f"Isc: {panel['isc']} A",
            f"Imp: {panel['imp']} A",
            f"Área: {panel_area} m²",
            f"Garantía producto: {panel.get('warranty_product_yr', '—')} años",
            f"Garantía potencia: {panel.get('warranty_power_yr', '—')} años",
        ])
    with row1_col2:
        inv_label = st.selectbox("Inversor/cargador *", list(inverter_options.keys()), index=default_inv_idx, key="w6og_inv")
        inverter = inverter_options[inv_label]
        _spec_card(f"{inverter['brand']} {inverter['model']}", [
            f"Potencia: {inverter['kw']} kW",
            f"Tipo: {inverter.get('type', '—')}",
            f"Voltaje de salida: {inverter.get('output_v', '—')} V",
            f"Fase: {inverter.get('phase', '—')}",
            f"Garantía: {inverter.get('warranty_yr', '—')} años",
        ])
        split_phase = check_split_phase(inverter, consumption.get("voltage_v", 120))
        if split_phase["requires_split_phase"]:
            st.warning(f"⚠️ {split_phase['warning_message']}")

    row2_col1, row2_col2 = st.columns(2)
    with row2_col1:
        cc_label = st.selectbox("Controlador de carga *", list(cc_options.keys()), index=default_cc_idx, key="w6og_cc")
        cc = cc_options[cc_label]
        _spec_card(f"{cc['brand']} {cc['model']}", [
            f"Tipo: {cc.get('type', '—')}",
            f"Vin máx: {cc['vin_max']:.0f} V",
            f"Vout: {cc.get('vout', '—')} V",
            f"Imax entrada: {cc['imax_in']:.0f} A",
            f"Imax salida: {cc.get('imax_out', '—')} A",
        ])
    with row2_col2:
        bat_label = st.selectbox("Batería *", list(battery_options.keys()), index=default_bat_idx, key="w6og_bat")
        battery = battery_options[bat_label]
        _spec_card(f"{battery['brand']} {battery['model']}", [
            f"Química: {battery.get('chemistry', '—')}",
            f"Capacidad: {battery['capacity_kwh']} kWh",
            f"Voltaje: {battery['voltage_v']} V",
            f"Descarga máxima (DoD): {battery.get('dod_pct', '—')}%",
            f"Ciclos: {battery.get('cycles', '—')}",
            f"Garantía: {battery.get('warranty_yr', '—')} años",
        ])

    row3_col1, _row3_col2 = st.columns(2)
    with row3_col1:
        mon_label = st.selectbox(
            "Monitoreo", list(monitoring_options.keys()),
            index=list(monitoring_options.keys()).index(default_mon_label), key="w6og_mon",
        )
        monitoring = monitoring_options[mon_label]
        if monitoring:
            _spec_card(f"{monitoring['brand']} {monitoring['model']}", [
                f"Compatible con: {monitoring.get('compatible_with', '—')}",
            ])

    st.divider()

    daily_kwh = consumption.get("daily_kwh", 0)
    pvgis_monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp", [])
    avg_peak_sun_hours = (sum(pvgis_monthly) / 12 / 30.4) if pvgis_monthly else 4.5

    # Real daily-resolution series for the Step 6 battery-SoC simulation
    # (calculations/sizing_off_grid.py: simulate_battery_soc()) — richer than
    # the monthly averages above, which can't see a multi-day cloudy streak.
    # Drafts created before this existed won't have it cached on wizard_site
    # yet; fetch it once here rather than forcing the user back to Step 3
    # (calculations/pvgis.py caches it by lat/lon, so this only hits the
    # network the first time per site).
    pvgis_daily_series = (site.get("pvgis_daily") or {}).get("daily_kwh_kwp", [])
    if not pvgis_daily_series and site.get("lat") and site.get("lon"):
        try:
            from calculations.pvgis import fetch_daily_series
            pvgis_daily = fetch_daily_series(site["lat"], site["lon"])
            pvgis_daily_series = pvgis_daily.get("daily_kwh_kwp", [])
            site = {**site, "pvgis_daily": pvgis_daily}
            st.session_state["wizard_site"] = site
        except Exception:
            pass

    if daily_kwh <= 0:
        st.warning("Vuelve al Paso 5 y calcula el perfil de consumo diario primero.")
        return None

    autonomy_days = consumption.get("autonomy_days", 1)
    dod_pct = battery.get("dod_pct", 80)
    # Inverter count/power don't vary by array scenario (only the array and
    # battery bank do) — computed once here so Opción 1/2's tables and cards
    # can show the full system spec (paneles + inversor + baterías) per
    # scenario, not just the array.
    inverter_qty = 2 if split_phase["requires_split_phase"] else 1
    inverter_power_w = round(inverter_qty * float(inverter.get("kw") or 0) * 1000)

    # Sum of individually-rated loads from Step 4 (quantity × nameplate kW) —
    # a lower bound on true simultaneous connected load, since it excludes
    # the "Uso general" behavior-driven aggregate (no defined peak-watts
    # figure, only kWh/día). Used below to check inverter headroom: scenario
    # 3 shouldn't add panels/battery for future growth while leaving zero
    # room on the inverter itself.
    profile = consumption.get("profile") or {}
    total_connected_load_kw = sum(
        line.get("quantity", 1) * line.get("connected_power_kw", 0)
        for line in profile.get("lines", [])
    )

    # Reset scenario/manual selection when panel, controller, or battery
    # changes — the scenario set itself is keyed to this triple (battery now
    # matters too, since scenarios 1/2/3 size the bank directly rather than
    # deriving it from the array). Mirrors wizard/grid_zero.py's w6_equip_key
    # reset logic in step6_equipment().
    equip_key = f"{panel['id']}_{cc['id']}_{battery['id']}"
    if st.session_state.get("w6og_equip_key") != equip_key:
        st.session_state["w6og_equip_key"] = equip_key
        st.session_state.pop("w6og_use_manual", None)
        st.session_state.pop("w6og_selected_scenario", None)

    scenarios = (
        generate_reliability_scenarios(
            panel, cc, battery, daily_kwh, pvgis_daily_series, autonomy_days,
            inverter_qty, float(inverter.get("kw") or 0), total_connected_load_kw,
            _MAX_CHARGE_CONTROLLERS,
        ) if pvgis_daily_series and len(pvgis_daily_series) >= 300 else []
    )
    using_manual = st.session_state.get("w6og_use_manual", False)
    selected_scenario_label = st.session_state.get("w6og_selected_scenario", "2")
    valid_scenarios = [s for s in scenarios if s["within_limits"]]
    if not using_manual and valid_scenarios:
        valid_labels = [s["scenario"] for s in valid_scenarios]
        if selected_scenario_label not in valid_labels:
            selected_scenario_label = valid_labels[min(1, len(valid_labels) - 1)]

    # ── Opción 1 — Auto A/B/C scenarios, same UX as wizard/grid_zero.py's
    # Scenario 1 = "mínimo aceptable" (SoC mínimo ~20%, recarga completa la
    # mayoría de los días); Scenario 2 = "recomendado" (~40%, casi todos los
    # días); Scenario 3 = "máxima autonomía + crecimiento" (~50%, siempre,
    # con una string extra de margen). MPPT/controlador es consecuencia del
    # arreglo que resulta de cada búsqueda, nunca un objetivo en sí mismo.
    st.markdown("#### Opción 1 — Configuración automática")
    st.caption(
        "Cada escenario fija un SoC mínimo objetivo (qué tan profundo se descarga la batería en un día "
        "típico) y se valida simulando día por día un año real de irradiancia del sitio — no solo un "
        "promedio mensual — para confirmar que la batería nunca se descargue por debajo de su límite más "
        "veces de lo tolerado. El arreglo y el banco de baterías se dimensionan para cumplir ambos; el "
        "controlador de carga es una consecuencia del arreglo resultante, no un objetivo aparte. El "
        "Escenario 3 también revisa la potencia del inversor: si la carga conectada ya usa la mayor parte "
        "de su capacidad, duplica los inversores para dejar margen de crecimiento futuro."
    )

    if scenarios:
        scenario_table = [{
            "Escenario": f"{s['scenario']} · {s['label']}",
            "SoC objetivo": f"~{s['min_soc_target_pct']:.0f}%",
            "Días con recarga completa": f"{s['battery']['days_full_pct']:.0f}%",
            "Días sin cubrir/año": s["battery"]["unmet_load_days"],
            "Aprovechamiento solar": f"{s['battery']['utilization_pct']:.0f}%",
            "Paneles/string": s["panels_per_string"],
            "Strings": s["strings"],
            "Controladores": s["charge_controller_qty"],
            "Total paneles": s["total_panels"],
            "Sistema (kW)": s["system_kw"],
            "Área (m²)": s["area_m2"],
            "Voc total (V)": s["voc_total"],
            "Corriente total (A)": s["imp_total"],
            "Inversores": s["inverter_qty"],
            "Potencia inversor (W)": s["inverter_power_w"],
            "Carga conectada / inversor": f"{s['inverter_load_ratio_pct']:.0f}%",
            "Baterías": s["battery"]["battery_count"],
            "Capacidad batería (kWh)": s["battery"]["total_kwh_installed"],
            "SoC mínimo real": f"{s['battery']['min_soc_actual_pct']:.0f}%",
            "Estado": "✅" if s["within_limits"] else "⚠️",
            "Notas": s["notes"],
        } for s in scenarios]
        st.dataframe(pd.DataFrame(scenario_table), use_container_width=True, hide_index=True)

        if not valid_scenarios:
            st.warning("Ningún escenario es válido con este panel + controlador.")
        else:
            proj_cols = st.columns(len(scenarios))
            for col, s in zip(proj_cols, scenarios):
                is_sel = (s["scenario"] == selected_scenario_label) and not using_manual
                is_valid_s = s["within_limits"]
                bank = s["battery"]
                border = BRAND_GREEN if is_sel else "#d1d5db"
                bg = BRAND_GREEN_LIGHT if is_sel else "#f9fafb"
                unmet_days = bank["unmet_load_days"]
                reliability_line = (
                    f'<span style="color:#166534;">✅ Recarga completa: <b>{bank["days_full_pct"]:.0f}%</b> de los días '
                    f'(simulado sobre un año real de irradiancia)</span><br>'
                    if unmet_days == 0 else
                    f'<span style="color:#92400e;">⚠️ Recarga completa: <b>{bank["days_full_pct"]:.0f}%</b> de los días · '
                    f'<b>{unmet_days}</b> día(s)/año por debajo del mínimo de la batería</span><br>'
                )
                cc_line = f'🎛️ Controladores: <b>{s["charge_controller_qty"]}</b><br>'
                growth_line = (
                    f'<span style="color:#1d4ed8;">🌱 Incluye {s["growth_strings"]} string extra para crecimiento futuro</span><br>'
                    if s.get("growth_strings") else ""
                )
                inverter_growth_line = (
                    f'<span style="color:#1d4ed8;">🔌➕ Inversores duplicados — carga actual usa el '
                    f'{s["inverter_load_ratio_pct"]:.0f}% de un solo juego, sin margen para crecer</span><br>'
                    if s.get("inverter_growth_added") else ""
                )
                inverter_tight_warning = (
                    f'<div style="font-size:0.68rem;color:#92400e;margin-top:0.3rem;">'
                    f'⚠️ Carga conectada usa el {s["inverter_load_ratio_pct"]:.0f}% de la capacidad del '
                    f'inversor — poco margen para agregar cargas más adelante.</div>'
                    if s.get("inverter_headroom_tight") and not s.get("inverter_growth_added") else ""
                )
                autonomy_floor_note = (
                    '<div style="font-size:0.68rem;color:#92400e;margin-top:0.3rem;">'
                    'ℹ️ Banco dimensionado por los días de autonomía (Paso 4), no por el SoC objetivo — '
                    'la autonomía configurada exige más batería que el objetivo de este escenario.</div>'
                    if bank.get("driven_by") == "autonomy_floor" else ""
                )
                low_streak_note = (
                    f'<div style="font-size:0.68rem;color:#92400e;margin-top:0.3rem;">'
                    f'ℹ️ Hasta {bank["longest_low_soc_streak_days"]} días seguidos por debajo del SoC objetivo '
                    f'en el año simulado — no implica falla, pero es ciclado más profundo/prolongado de lo ideal.</div>'
                    if unmet_days == 0 and bank["longest_low_soc_streak_days"] > 5 else ""
                )
                utilization_pct = bank["utilization_pct"]
                # Below 50%: more than half of what the array generates all
                # year is curtailed (battery already full, nowhere to send
                # the surplus) — worth a visible flag, same 50% threshold and
                # framing as wizard/grid_zero.py's "sistema sobredimensionado"
                # note, so both wizards read consistently on this point.
                oversized_note = (
                    f'<div style="margin-top:0.4rem;font-size:0.72rem;color:#92400e;">'
                    f'⚠️ Solo el {utilization_pct:.0f}% de la generación se aprovecha — arreglo '
                    f'sobredimensionado para esta batería/consumo.</div>'
                    if utilization_pct < 50 else ""
                )
                ok_tag = "✅" if is_valid_s else "⚠️"
                with col:
                    if is_valid_s:
                        btn_label = f"{'●' if is_sel else '○'} Escenario {s['scenario']} — {s['total_panels']} paneles ({s['system_kw']} kW)"
                        if st.button(btn_label, key=f"w6og_sel_{s['scenario']}", use_container_width=True):
                            st.session_state["w6og_selected_scenario"] = s["scenario"]
                            st.session_state["w6og_use_manual"] = False
                            st.rerun()
                    else:
                        st.markdown(
                            f'<div style="font-size:0.8rem;color:#9ca3af;padding:0.3rem 0;">⚠️ Escenario {s["scenario"]} — fuera de límites</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        f'<div style="border:2px solid {border};border-radius:8px;'
                        f'padding:0.65rem 0.8rem;background:{bg};font-size:0.82rem;line-height:1.9;">'
                        f'<div style="font-weight:700;font-size:0.88rem;color:#1E2D54;margin-bottom:0.2rem;">'
                        f'{s["scenario"]} · {s["label"]} · {s["system_kw"]} kW</div>'
                        f'<div style="font-size:0.72rem;color:#6b7280;margin-bottom:0.4rem;">{ok_tag} SoC objetivo ~{s["min_soc_target_pct"]:.0f}%</div>'
                        f'{reliability_line}'
                        f'🔢 Paneles: <b>{s["total_panels"]}</b> '
                        f'({s["panels_per_string"]} en serie × {s["strings"]} en paralelo)<br>'
                        f'🔌 Inversores: <b>{s["inverter_qty"]}</b> ({s["inverter_power_w"]:,} W)<br>'
                        f'🔋 Baterías: <b>{bank["battery_count"]}</b> ({bank["total_kwh_installed"]:.1f} kWh) '
                        f'— SoC mín. real: <b>{bank["min_soc_actual_pct"]:.0f}%</b><br>'
                        f'☀️ Aprovechamiento solar: <b>{utilization_pct:.0f}%</b><br>'
                        f'{cc_line}'
                        f'{growth_line}'
                        f'{inverter_growth_line}'
                        f'</div>'
                        f'{autonomy_floor_note}'
                        f'{low_streak_note}'
                        f'{oversized_note}'
                        f'{inverter_tight_warning}',
                        unsafe_allow_html=True,
                    )
            st.markdown("&nbsp;", unsafe_allow_html=True)
    elif not (pvgis_daily_series and len(pvgis_daily_series) >= 300):
        st.warning("Vuelve al Paso 3 y obtén la irradiancia PVGIS del sitio (serie diaria) para calcular los escenarios.")
    else:
        st.markdown(
            '<div style="background:#fef2f2;border-left:4px solid #dc2626;border-radius:6px;'
            'padding:0.6rem 0.9rem;margin-bottom:0.6rem;">'
            f'❌ <b>Ningún escenario alcanza su meta de confiabilidad para este panel + controlador, '
            f'ni siquiera paralelizando hasta {_MAX_CHARGE_CONTROLLERS} controladores.</b> '
            'Prueba un panel de menor corriente, un controlador de mayor Imax, o reduce la carga.</div>',
            unsafe_allow_html=True,
        )

    # ── Opción 2 — Manual design, live-recomputed on every slider change ────
    st.divider()
    st.markdown("#### Opción 2 — Configuración manual")
    st.caption("Ajusta los parámetros libremente y verifica los límites del controlador en tiempo real.")

    default_scenario = next((s for s in scenarios if s["scenario"] == "2"), None)
    default_series = default_scenario["panels_per_string"] if default_scenario else 1
    default_parallel = default_scenario["strings"] if default_scenario else 1

    left_col, right_col = st.columns([1, 1])
    with left_col:
        m_series = st.number_input("Paneles en serie (por string)", min_value=1, max_value=50,
                                    value=default_series, step=1, key="w6og_m_series")
        m_strings = st.number_input("Strings en paralelo (total)", min_value=1, max_value=50,
                                     value=default_parallel, step=1, key="w6og_m_strings")

        m = check_charge_controller_design_multi(panel, cc, m_series, m_strings, _MAX_CHARGE_CONTROLLERS)

        if m is None:
            st.markdown(
                '<div style="background:#fef2f2;border-left:4px solid #dc2626;border-radius:6px;'
                'padding:0.5rem 0.8rem;font-size:0.83rem;">'
                f'❌ Esta combinación excede {_MAX_CHARGE_CONTROLLERS} controladores en paralelo — reduce los strings.</div>',
                unsafe_allow_html=True,
            )
        else:
            _chip_row([
                f"🔢 <b>{m['total_panels']}</b> paneles",
                f"⚡ <b>{m['system_kw']} kW</b>",
                f"📐 <b>{m['area_m2']} m²</b>",
                f"🎛️ <b>{m['charge_controller_qty']}</b> controlador(es)",
                f"Voc <b>{m['voc_total']} V</b>",
                f"Corriente <b>{m['imp_total']} A</b>",
            ])
            imp_limit_m = cc["imax_in"] * m["charge_controller_qty"]
            _param_row("Voc total", f"{m['voc_total']} V", m["voc_total"] <= cc["vin_max"], f"≤ {cc['vin_max']:.0f} V")
            _param_row(
                "Corriente total", f"{m['imp_total']} A", m["imp_total"] <= imp_limit_m,
                f"≤ {imp_limit_m:.0f} A" + (f" ({m['charge_controller_qty']}×{cc['imax_in']:.0f}A)" if m["charge_controller_qty"] > 1 else ""),
            )

    with right_col:
        if m is not None:
            if m["within_limits"]:
                btn_label = f"{'●' if using_manual else '○'} Usar configuración manual — {m['total_panels']} paneles ({m['system_kw']} kW)"
                if st.button(btn_label, key="w6og_manual_on", use_container_width=True):
                    st.session_state["w6og_use_manual"] = True
                    st.rerun()
            else:
                st.markdown(
                    '<div style="font-size:0.8rem;color:#9ca3af;padding:0.3rem 0;">'
                    '⚠️ Configuración manual — corrige los errores en rojo para poder seleccionarla</div>',
                    unsafe_allow_html=True,
                )

            mp = _og_scenario_projection(
                m, avg_peak_sun_hours, daily_kwh, autonomy_days, dod_pct,
                battery["voltage_v"], battery["capacity_kwh"],
                daily_kwh_kwp=pvgis_daily_series,
            )
            m_cover_line = (
                '<span style="color:#166534;">✅ Cubre el consumo diario</span><br>' if mp["covers"] else
                '<span style="color:#92400e;">⚠️ No cubre el consumo diario</span><br>'
            )
            m_utilization_line = (
                f'☀️ Aprovechamiento solar: <b>{mp["utilization_pct"]:.0f}%</b><br>'
                if mp["utilization_pct"] is not None else ""
            )
            m_border = "#6366f1" if using_manual else "#d1d5db"
            m_bg = "#f5f3ff" if using_manual else "#f9fafb"
            st.markdown(
                f'<div style="border:2px solid {m_border};border-radius:8px;'
                f'padding:0.65rem 0.8rem;background:{m_bg};font-size:0.82rem;line-height:1.9;">'
                f'<div style="font-weight:700;font-size:0.88rem;color:#1E2D54;margin-bottom:0.3rem;">'
                f'Proyección · {m["system_kw"]} kW</div>'
                f'☀️ Generación: <b>{mp["daily_generation"]:.2f} kWh/día</b><br>'
                f'🔢 Paneles: <b>{m["total_panels"]}</b> '
                f'({m["panels_per_string"]} en serie × {m["strings"]} en paralelo)<br>'
                f'🔌 Inversores: <b>{inverter_qty}</b> ({inverter_power_w:,} W)<br>'
                f'🔋 Baterías: <b>{mp["battery_count"]}</b> ({mp["battery_kwh"]:.1f} kWh)<br>'
                f'{m_cover_line}'
                f'{m_utilization_line}'
                f'🎛️ Controladores: <b>{m["charge_controller_qty"]}</b>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Resolve the active configuration (auto scenario or manual) — every
    # metric/chart from here down reads from `chosen`, so switching scenarios
    # or dragging the manual sliders updates everything live.
    if using_manual:
        # Only treat manual as active if it's currently within limits — if the
        # user drags the sliders into an invalid zone after selecting manual,
        # `chosen` should reflect "nothing valid selected" rather than
        # silently keep the last valid manual numbers or fall back to an
        # auto scenario the user didn't pick.
        chosen = {**m, "scenario": "M"} if (m is not None and m["within_limits"]) else None
    else:
        chosen = next((s for s in scenarios if s["scenario"] == selected_scenario_label), None) or (scenarios[0] if scenarios else None)

    st.divider()

    if chosen is None:
        st.error("No hay una configuración de arreglo seleccionada. Ajusta el panel/controlador arriba, o corrige la configuración manual.")
        panels_per_string = n_strings = cc_qty = actual_panel_count = 0
        display_array_kw = display_area_m2 = display_daily_generation = 0
        is_valid = False
        battery_bank = {"battery_count": 0, "total_kwh_installed": 0, "discharge_pct": 0}
        final_inverter_qty, final_inverter_power_w = inverter_qty, inverter_power_w
    else:
        panels_per_string = chosen["panels_per_string"]
        n_strings = chosen["strings"]
        cc_qty = chosen["charge_controller_qty"]
        actual_panel_count = chosen["total_panels"]
        display_array_kw = chosen["system_kw"]
        display_area_m2 = chosen["area_m2"]
        derating = 1 - 0.20  # matches size_array()'s default system_losses_pct
        display_daily_generation = round(display_array_kw * avg_peak_sun_hours * derating, 2)
        is_valid = chosen["within_limits"]
        if chosen["scenario"] == "M":
            # Manual mode has no min-SoC target of its own — battery bank is
            # sized off THIS array's actual generation (autonomy_days-driven
            # backup), same formula as always, so switching sliders still
            # visibly changes the battery count. Inverter count also stays at
            # the base split-phase-driven value — manual mode has no
            # growth-headroom concept either.
            battery_bank = size_battery_bank(
                daily_kwh=display_daily_generation, autonomy_days=autonomy_days, dod_pct=dod_pct,
                battery_voltage_v=battery["voltage_v"], battery_capacity_kwh=battery["capacity_kwh"],
            )
            if pvgis_daily_series and len(pvgis_daily_series) >= 300 and battery_bank["total_kwh_installed"] > 0:
                from calculations.sizing_off_grid import simulate_battery_soc as _sim_soc
                _m_gen = [v * display_array_kw * derating for v in pvgis_daily_series]
                battery_bank["utilization_pct"] = _sim_soc(
                    _m_gen, daily_kwh, battery_bank["total_kwh_installed"], dod_pct, 100 - dod_pct,
                )["utilization_pct"]
            final_inverter_qty, final_inverter_power_w = inverter_qty, inverter_power_w
        else:
            # Auto scenarios (1/2/3) already carry their own min-SoC-driven
            # battery bank and headroom-checked inverter count from
            # generate_reliability_scenarios() — reuse them directly.
            battery_bank = chosen["battery"]
            final_inverter_qty = chosen["inverter_qty"]
            final_inverter_power_w = chosen["inverter_power_w"]

    st.session_state["w6og_last_battery_count"] = battery_bank["battery_count"]

    if split_phase["requires_split_phase"]:
        inverter_arrangement = "Split-phase 120/240V (master/slave)"
    else:
        inverter_arrangement = f"{consumption.get('voltage_v', 120):.0f}V"
    panel_arrangement = (
        f"{panels_per_string} en serie × {n_strings} en paralelo" if chosen else "—"
    )

    # ── Validación del diseño — moved above "Dimensionamiento calculado" per
    # user feedback 2026-07-30, so the pass/fail check is the first thing
    # shown for whichever scenario/manual config is active, before the specs
    # themselves. Reads only from `chosen`/`battery_bank`/`cc` (all resolved
    # above), so it doesn't need `display_daily_generation > 0` the way
    # "Generación vs. consumo" below still does — guarded on `chosen` alone.
    if chosen:
        st.markdown("#### Validación del diseño")
        voc_ok = chosen["voc_total"] <= cc["vin_max"]
        imp_limit = cc["imax_in"] * cc_qty
        imp_ok = chosen["imp_total"] <= imp_limit

        banner_status = "ok" if is_valid else "fail"
        banner_style = _CHECK_STATUS_STYLE[banner_status]
        banner_text = "Configuración válida" if is_valid else "Configuración inválida"
        st.markdown(
            f'<div style="background:{banner_style["bg"]};border-left:4px solid {banner_style["border"]};'
            f'border-radius:6px;padding:0.6rem 0.9rem;margin-bottom:0.6rem;font-weight:700;'
            f'color:{BRAND_NAVY};">{banner_style["icon"]} {banner_text}</div>',
            unsafe_allow_html=True,
        )
        if cc_qty > 1:
            st.caption(
                f"ℹ️ Este arreglo requiere {cc_qty} controladores de carga en paralelo — "
                f"un solo {cc['brand']} {cc['model']} no soporta la corriente total del arreglo."
            )

        min_safe_soc_pct = round(100 - dod_pct, 1)
        # min_soc_actual_pct comes from simulate_battery_soc() — the real
        # worst-case SoC across a simulated year — not from discharge_pct,
        # which is still a single average-day ratio and no longer tracks the
        # same number now that the scenario search validates against a real
        # daily series. Also gate on unmet_load_days: if the battery ever hit
        # its hard floor, the simulated min lands exactly at min_safe_soc_pct
        # by construction (see simulate_battery_soc()'s clamping), which
        # would otherwise read as a false "OK" even though a real blackout
        # day occurred.
        unmet_days = battery_bank.get("unmet_load_days", 0)
        design_min_soc_pct = battery_bank.get("min_soc_actual_pct", round(100 - battery_bank["discharge_pct"], 1))
        soc_ok = design_min_soc_pct >= min_safe_soc_pct and unmet_days == 0
        discharge_ok = battery_bank["discharge_pct"] <= 100

        _param_row("Voc total", f"{chosen['voc_total']} V", voc_ok, f"≤ {cc['vin_max']:.0f} V")
        _param_row(
            "Corriente total", f"{chosen['imp_total']} A", imp_ok,
            f"≤ {imp_limit:.0f} A" + (f" ({cc_qty}×{cc['imax_in']:.0f}A)" if cc_qty > 1 else ""),
        )
        _param_row("Profundidad de descarga (día típico)", f"{battery_bank['discharge_pct']}%", discharge_ok, "≤ 100%")
        _param_row(
            "SoC mínimo real (año simulado)",
            f"diseño llega a {design_min_soc_pct:.0f}%" + (f" · {unmet_days} día(s)/año sin cubrir" if unmet_days else ""),
            soc_ok, f"≥ {min_safe_soc_pct:.0f}%",
        )

        if not is_valid and not voc_ok and chosen.get("notes"):
            st.caption(f"⚠️ {chosen['notes']}")

        # ── Margen de diseño — grouped with Validación del diseño (both are
        # electrical-limits checks against equipment ratings) instead of
        # sitting inside the energy-flow chart run below, which it used to
        # interrupt.
        st.markdown("##### Margen de diseño")
        st.caption(
            "Qué tan cerca está el diseño de sus límites eléctricos — del **controlador de carga** "
            "(Voc, corriente) y de la **batería** (profundidad de descarga). No incluye el inversor "
            "(su compatibilidad de voltaje se valida aparte, junto a su selección arriba)."
        )

        def _margin_pct_color(pct: float) -> str:
            if pct > 95:
                return "#dc2626"
            if pct > 80:
                return "#b45309"
            return BRAND_GREEN

        import plotly.graph_objects as go
        margin_items = [
            ("Voc del arreglo (vs. controlador)", (chosen["voc_total"] / cc["vin_max"] * 100) if cc["vin_max"] else 0),
            ("Corriente del arreglo (vs. controlador)", (chosen["imp_total"] / imp_limit * 100) if imp_limit else 0),
            ("Profundidad de descarga (vs. batería)", (battery_bank["discharge_pct"] / dod_pct * 100) if dod_pct else 0),
        ]
        margin_fig = go.Figure(go.Bar(
            x=[v for _, v in margin_items],
            y=[k for k, _ in margin_items],
            orientation="h",
            marker_color=[_margin_pct_color(v) for _, v in margin_items],
            text=[f"{v:.0f}%" for _, v in margin_items],
            textposition="outside",
        ))
        margin_fig.add_vline(x=100, line_dash="dash", line_color="#9ca3af")
        margin_fig.update_layout(
            xaxis=dict(title="% del límite", range=[0, max(110, max(v for _, v in margin_items) * 1.15)]),
            height=220,
            margin=dict(t=10, b=10, l=10, r=30),
        )
        st.plotly_chart(margin_fig, use_container_width=True)
        st.caption("Verde: margen cómodo (<80% del límite). Ámbar: 80–95%. Rojo: >95%, revisar diseño.")

    st.divider()
    st.markdown("#### Dimensionamiento calculado")
    if chosen:
        scenario_note = "manual" if chosen["scenario"] == "M" else f"Escenario {chosen['scenario']} · {chosen['label']}"
        st.caption(f"Configuración activa: {scenario_note}")

    _chip_row([
        f"🔢 <b>{actual_panel_count}</b> paneles",
        f"🔀 <b>{panel_arrangement}</b>",
        f"⚡ <b>{display_array_kw} kW</b>",
        f"📐 <b>{display_area_m2} m²</b>",
        f"🔌 <b>{final_inverter_qty}</b> inversor(es) ({inverter_arrangement})",
        f"🎛️ <b>{cc_qty or 1}</b> controlador(es)",
        f"🔋 <b>{battery_bank['battery_count']}</b> baterías",
    ])

    st.caption("Resultado del dimensionamiento")
    i1, i2 = st.columns(2)
    with i1:
        _metric_card("Generación diaria", f"{display_daily_generation} kWh/día")
    with i2:
        _metric_card("Capacidad del banco", f"{battery_bank['total_kwh_installed']} kWh")

    if display_daily_generation > 0:
        st.markdown("##### Generación vs. consumo")
        st.caption(
            "Balance de energía de un día típico: lo que genera el arreglo, lo que consume el sitio, "
            "y el excedente que queda para recargar el banco de baterías."
        )
        import plotly.graph_objects as go
        margin_kwh_gen = round(max(0, display_daily_generation - daily_kwh), 2)
        gen_fig = go.Figure(go.Bar(
            x=[display_daily_generation, daily_kwh, margin_kwh_gen],
            y=["Generación diaria", "Consumo diario", "Recarga de batería"],
            orientation="h",
            marker_color=[BRAND_GREEN, BRAND_NAVY, "#86efac"],
            text=[f"{display_daily_generation:.2f} kWh/día", f"{daily_kwh:.2f} kWh/día", f"{margin_kwh_gen:.2f} kWh/día"],
            textposition="outside",
        ))
        gen_fig.update_layout(
            xaxis=dict(title="kWh/día", range=[0, max(display_daily_generation, daily_kwh, margin_kwh_gen) * 1.3]),
            height=220,
            margin=dict(t=10, b=10, l=10, r=10),
        )
        st.plotly_chart(gen_fig, use_container_width=True)
        covers = display_daily_generation >= daily_kwh
        cover_icon = "✅" if covers else "⚠️"
        st.caption(
            f"{cover_icon} El arreglo genera {display_daily_generation:.2f} kWh/día para un consumo de "
            f"{daily_kwh:.2f} kWh/día. El excedente ({margin_kwh_gen:.2f} kWh/día) recarga el banco, que "
            f"almacena {battery_bank['total_kwh_installed']} kWh "
            f"(~{autonomy_days:.1f} día(s) de autonomía) para cubrir consumo en días sin sol."
        )

        st.divider()

        # ── Estadísticas — groups the four parallel chart-driven analyses
        # (monthly coverage, solar utilization, seasonal coverage, energy
        # flow) as subsections of one section, rather than four independent
        # divider-bounded sections — they're all read-only analysis of the
        # same chosen config, not separate decisions.
        st.markdown("#### Estadísticas")

        # ── Same monthly data/colors as the PDF's "Cobertura mensual estimada" —
        # rendered here with Plotly (hoverable) instead of the PDF's static SVG,
        # since this is an on-screen review tool, not a WeasyPrint target. Live:
        # recomputed from whichever scenario/manual config is currently selected
        # above, via the same helper Step 8 uses (_og_monthly_coverage_and_sim()),
        # just fed this step's live array/battery_bank instead of the final
        # persisted equipment.
        _step6_coverage, _step6_sim = _og_monthly_coverage_and_sim(
            {"array_kw": display_array_kw}, battery, battery_bank,
            {"daily_kwh": daily_kwh}, site,
        )
        if _step6_coverage:
            from wizard.common import monthly_coverage_chart
            st.markdown("##### Cobertura mensual estimada")
            st.caption(
                "Generación mensual real (PVGIS) frente a consumo y recarga de batería, para la "
                "configuración seleccionada arriba."
            )
            st.plotly_chart(
                monthly_coverage_chart(
                    _step6_coverage.get("generation"), _step6_coverage.get("consumption"),
                    recharge_kwh=_step6_coverage.get("recharge"), flag_shortfall=True,
                ),
                use_container_width=True,
            )

        # ── Aprovechamiento de generación solar ───────────────────────────
        # Real simulated split of a year of generation into what actually gets
        # used (consumption + battery charging) vs. curtailed (battery already
        # full, no grid to export the surplus to). Lives here, not in Step 8,
        # because this is the step where the user can still act on it — pick a
        # bigger battery or a smaller array and watch the split change. Step 8
        # only echoes the resulting percentage as a summary KV.
        st.markdown("##### Aprovechamiento de generación solar")
        if _step6_sim:
            util_pct = _step6_sim["utilization_pct"]
            used_kwh = round(_step6_sim["total_generation_kwh"] - _step6_sim["curtailed_kwh"])
            curtailed_kwh = round(_step6_sim["curtailed_kwh"])
            st.caption(
                "Del total generado en un año real de irradiancia, qué fracción se usa (consumo directo + "
                "recarga de batería) frente a lo que se pierde porque la batería ya está llena y no hay red "
                "a la cual exportar el excedente."
            )
            import plotly.graph_objects as go
            util_fig = go.Figure()
            util_fig.add_trace(go.Bar(
                y=["Generación anual"], x=[used_kwh], name="Aprovechado", orientation="h",
                marker_color=BRAND_GREEN, text=[f"{util_pct:.0f}% · {used_kwh:,} kWh"], textposition="inside",
            ))
            util_fig.add_trace(go.Bar(
                y=["Generación anual"], x=[curtailed_kwh], name="Curtailed (no aprovechado)", orientation="h",
                marker_color="#d1d5db", text=[f"{100 - util_pct:.0f}% · {curtailed_kwh:,} kWh"], textposition="inside",
            ))
            util_fig.update_layout(
                barmode="stack", height=130, margin=dict(t=10, b=10, l=10, r=10),
                xaxis_title="kWh/año", showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(util_fig, use_container_width=True)
            if util_pct < 50:
                st.warning(
                    f"⚠️ Solo el {util_pct:.0f}% de la generación anual se aprovecha — el arreglo está "
                    "sobredimensionado para esta batería/consumo. Considera una batería más grande o menos paneles."
                )
        else:
            st.info(
                "No hay una serie diaria real de irradiancia disponible para este borrador (vuelve al Paso 3 "
                "y obtén la irradiancia PVGIS del sitio) — no se puede calcular el aprovechamiento solar."
            )

        # ── Seasonal coverage: monthly generation (real PVGIS variation) vs.
        # the flat daily-consumption reference — the array is validated above
        # against an *average* month; this shows whether the weakest month
        # (rainy season) still clears the load.
        if pvgis_monthly and len(pvgis_monthly) == 12:
            from calculations.sizing_grid_zero import MONTHS_ES
            import calendar
            _days_in_month = [calendar.monthrange(2026, m)[1] for m in range(1, 13)]
            monthly_gen_kwh_day = [
                round(m_kwhkwp * display_array_kw * (1 - 0.20) / d, 2)
                for m_kwhkwp, d in zip(pvgis_monthly, _days_in_month)
            ]
            worst_idx = min(range(12), key=lambda i: monthly_gen_kwh_day[i])
            st.markdown("##### Cobertura estacional")
            st.caption(
                "Generación bruta mensual del arreglo (según irradiancia real de PVGIS) frente al "
                "consumo diario — **no incluye el efecto de buffer del banco de baterías**, que puede "
                "cubrir déficits de días puntuales dentro de un mes. Si un mes completo queda por "
                "debajo de la línea, el déficit es estructural y la batería sola no lo resuelve."
            )
            season_fig = go.Figure()
            season_fig.add_trace(go.Scatter(
                x=MONTHS_ES, y=monthly_gen_kwh_day, mode="lines+markers", name="Generación",
                line=dict(color=BRAND_GREEN, width=3), marker=dict(size=7),
                fill="tozeroy", fillcolor="rgba(75,174,106,0.12)",
            ))
            season_fig.add_hline(
                y=daily_kwh, line_dash="dash", line_color=BRAND_NAVY,
                annotation_text="Consumo diario", annotation_position="top left",
            )
            if monthly_gen_kwh_day[worst_idx] < daily_kwh:
                season_fig.add_trace(go.Scatter(
                    x=[MONTHS_ES[worst_idx]], y=[monthly_gen_kwh_day[worst_idx]], mode="markers",
                    marker=dict(size=14, color="#dc2626", symbol="x", line=dict(width=3)),
                    name="Mes más débil",
                ))
            season_fig.update_layout(
                yaxis_title="kWh/día", height=260,
                margin=dict(t=10, b=10, l=10, r=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(season_fig, use_container_width=True)
            if monthly_gen_kwh_day[worst_idx] < daily_kwh:
                deficit = round(daily_kwh - monthly_gen_kwh_day[worst_idx], 2)
                st.caption(
                    f"⚠️ En {MONTHS_ES[worst_idx]} la generación estimada ({monthly_gen_kwh_day[worst_idx]:.2f} "
                    f"kWh/día) cae {deficit:.2f} kWh/día por debajo del consumo — el banco de baterías "
                    "absorbe el déficit ese mes, pero el margen de autonomía se reduce."
                )
            else:
                st.caption(
                    f"✅ La generación cubre el consumo en los 12 meses del año, incluso en "
                    f"{MONTHS_ES[worst_idx]} (el mes más débil, {monthly_gen_kwh_day[worst_idx]:.2f} kWh/día)."
                )

        # ── Energy flow Sankey: gross generation → system losses / useful
        # energy → load categories (+ any surplus above the load, which is
        # what recharges the battery bank day to day). Category shares come
        # from Step 5's own profile, rescaled to the (possibly manually
        # edited) daily_kwh total so the diagram stays internally consistent.
        profile = consumption.get("profile") or {}
        if profile and daily_kwh > 0:
            raw_cat_kwh: dict[str, float] = {}
            for line in profile.get("lines", []):
                raw_cat_kwh[line["category"]] = raw_cat_kwh.get(line["category"], 0) + line["estimated_kwh_day"]
            if profile.get("behavior_aggregate"):
                agg = profile["behavior_aggregate"]
                raw_cat_kwh["behavior_driven"] = raw_cat_kwh.get("behavior_driven", 0) + agg["kwh_day"]
            raw_total = sum(raw_cat_kwh.values())
            if raw_total > 0:
                scale = daily_kwh / raw_total
                cat_kwh = {k: round(v * scale, 3) for k, v in raw_cat_kwh.items()}

                gross_kwh = round(display_array_kw * avg_peak_sun_hours, 2)
                losses_kwh = round(max(0, gross_kwh - display_daily_generation), 2)
                margin_kwh = round(max(0, display_daily_generation - daily_kwh), 2)

                st.markdown("##### Flujo de energía")
                st.caption("De dónde sale la energía generada: pérdidas del sistema y el resto hacia cada categoría de carga o hacia la batería.")
                labels = ["Generación bruta", "Pérdidas del sistema", "Energía útil"]
                node_colors = [BRAND_GREEN, "#9ca3af", BRAND_NAVY]
                sources = [0, 0]
                targets = [1, 2]
                values = [losses_kwh, display_daily_generation]
                link_colors = ["rgba(156,163,175,0.45)", "rgba(75,174,106,0.4)"]
                for cat, kwh in sorted(cat_kwh.items(), key=lambda x: -x[1]):
                    if kwh <= 0:
                        continue
                    labels.append(CATEGORY_LABELS_ES.get(cat, cat))
                    node_colors.append(_CATEGORY_CHART_COLORS.get(cat, "#9ca3af"))
                    sources.append(2)
                    targets.append(len(labels) - 1)
                    values.append(kwh)
                    link_colors.append("rgba(30,45,84,0.3)")
                if margin_kwh > 0.01:
                    labels.append("Margen / recarga batería")
                    node_colors.append("#86efac")
                    sources.append(2)
                    targets.append(len(labels) - 1)
                    values.append(margin_kwh)
                    link_colors.append("rgba(75,174,106,0.25)")
                sankey_fig = go.Figure(go.Sankey(
                    node=dict(label=labels, color=node_colors, pad=20, thickness=16,
                              line=dict(color="white", width=0.5)),
                    link=dict(source=sources, target=targets, value=values, color=link_colors),
                    textfont=dict(color=BRAND_NAVY, size=13, family="Arial, sans-serif"),
                ))
                sankey_fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(sankey_fig, use_container_width=True)
                st.caption(
                    "Ilustra el reparto de la energía generada: pérdidas del sistema (20% asumido) y el "
                    "resto hacia cada categoría de carga, proporcional al consumo diario estimado."
                )

    st.divider()
    can_continue = bool(chosen) and is_valid
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w6og_back"):
            st.session_state["wizard_step"] = 5
            _autosave()
            st.rerun()
    with col_next:
        if st.button("Siguiente →", key="w6og_next", type="primary", disabled=not can_continue):
            result = {
                "panel_id": panel["id"], "panel": panel,
                "inverter_id": inverter["id"], "inverter": inverter,
                "battery_id": battery["id"], "battery": battery,
                "charge_controller_id": cc["id"], "charge_controller": cc,
                "charge_controller_qty": cc_qty,
                "inverter_qty": final_inverter_qty,
                "monitoring_id": monitoring["id"] if monitoring else None, "monitoring": monitoring,
                "panels_per_string": panels_per_string,
                "n_strings": n_strings,
                "panel_count": actual_panel_count,
                "array_scenario": chosen["scenario"],
                "array_scenarios": scenarios,
                "array": {"array_kw": display_array_kw, "panel_count": actual_panel_count, "area_m2": display_area_m2, "daily_generation_kwh": display_daily_generation},
                "battery_bank": battery_bank,
                "split_phase": split_phase,
            }
            st.session_state["wizard_equipment"] = result
            return result

    if not can_continue:
        st.caption("Selecciona un escenario automático válido o configura un diseño manual válido para continuar.")

    return None


# ── Step 7 — Costos ──────────────────────────────────────────────────────────

def step7_costs() -> dict | None:
    """Line items including array, inverter, battery bank, charge controller. IVA always shown."""
    st.markdown("### Paso 7 — Detalles de costos")

    current = st.session_state.get("wizard_costs", {})
    equipment = st.session_state.get("wizard_equipment", {})

    panel = equipment.get("panel", {})
    inverter = equipment.get("inverter", {})
    battery = equipment.get("battery", {})
    cc = equipment.get("charge_controller", {})
    cc_qty = equipment.get("charge_controller_qty", 1)
    panel_count = equipment.get("panel_count", 0)
    battery_count = equipment.get("battery_bank", {}).get("battery_count", 0)
    split_phase = equipment.get("split_phase", {})
    # Prefer the qty resolved in Step 6 (accounts for Scenario 3's inverter
    # doubling when connected load is close to the base setup's capacity —
    # see generate_reliability_scenarios()); fall back to the split-phase-only
    # formula for proposals saved before this existed.
    inverter_qty = equipment.get("inverter_qty") or (2 if split_phase.get("requires_split_phase") else 1)

    if current.get("line_items"):
        line_items = current["line_items"]
    else:
        line_items = []
        if panel:
            line_items.append({
                "item": "Paneles solares", "item_en": "Solar panels",
                "qty": panel_count, "unit_cost": float(panel.get("cost_usd") or 0), "iva_pct": 0.0,
                "specs": f"{panel.get('brand','')} {panel.get('model','')} {panel.get('wp','')}W".strip(),
                "specs_en": f"{panel.get('brand','')} {panel.get('model','')} {panel.get('wp','')}W".strip(),
            })
        if inverter:
            line_items.append({
                "item": "Inversor/cargador", "item_en": "Inverter/charger",
                "qty": inverter_qty, "unit_cost": float(inverter.get("cost_usd") or 0), "iva_pct": 0.0,
                "specs": f"{inverter.get('brand','')} {inverter.get('model','')}".strip(),
                "specs_en": f"{inverter.get('brand','')} {inverter.get('model','')}".strip(),
            })
        if battery:
            line_items.append({
                "item": "Baterías", "item_en": "Batteries",
                "qty": battery_count, "unit_cost": float(battery.get("cost_usd") or 0), "iva_pct": 0.0,
                "specs": f"{battery.get('brand','')} {battery.get('model','')} {battery.get('capacity_kwh','')}kWh".strip(),
                "specs_en": f"{battery.get('brand','')} {battery.get('model','')} {battery.get('capacity_kwh','')}kWh".strip(),
            })
        if cc:
            line_items.append({
                "item": "Controlador de carga", "item_en": "Charge controller",
                "qty": cc_qty, "unit_cost": float(cc.get("cost_usd") or 0), "iva_pct": 0.0,
                "specs": f"{cc.get('brand','')} {cc.get('model','')}".strip(),
                "specs_en": f"{cc.get('brand','')} {cc.get('model','')}".strip(),
            })
        monitoring = equipment.get("monitoring")
        if monitoring:
            line_items.append({
                "item": "Monitoreo", "item_en": "Monitoring",
                "qty": 1, "unit_cost": float(monitoring.get("cost_usd") or 0), "iva_pct": 0.0,
                "specs": f"{monitoring.get('brand','')} {monitoring.get('model','')}".strip(),
                "specs_en": f"{monitoring.get('brand','')} {monitoring.get('model','')}".strip(),
            })
        line_items.append({
            "item": "Estructura de montaje", "item_en": "Mounting structure",
            "qty": None, "unit_cost": 0.0, "iva_pct": 0.13,
            "specs": "Arreglo de módulos", "specs_en": "Module array",
        })
        try:
            from database.equipment_db import list_service_defaults
            meta = st.session_state.get("wizard_meta", {})
            is_off_grid = meta.get("system_type") == "off_grid"
            for svc in list_service_defaults():
                if not svc.get("enabled", True):
                    continue
                if is_off_grid and svc["item"] == "Permiso de Interconexión":
                    # A true Off-Grid system has no utility connection to interconnect —
                    # this line only applies to grid-tied types (Grid Zero, Hybrid).
                    continue
                line_items.append({
                    "item": svc["item"], "item_en": svc.get("item_en", svc["item"]),
                    "qty": None, "unit_cost": float(svc.get("unit_cost_usd") or 0),
                    "iva_pct": float(svc.get("iva_pct") or 0),
                    "specs": svc.get("specs", ""), "specs_en": svc.get("specs_en", svc.get("specs", "")),
                })
        except Exception:
            pass

    df = pd.DataFrame([{
        "Descripción (ES)": r["item"], "Descripción (EN)": r.get("item_en", r["item"]),
        "Qty": float(r["qty"]) if r.get("qty") not in (None, "") else None,
        "Precio unit. (USD)": float(r["unit_cost"] or 0),
        "IVA": f"{int(round(r.get('iva_pct', 0) * 100))}%",
        "Especificaciones": r.get("specs", ""),
    } for r in line_items])

    edited = st.data_editor(
        df,
        column_config={
            "Descripción (ES)": st.column_config.TextColumn(width="medium"),
            "Descripción (EN)": st.column_config.TextColumn(width="medium"),
            "Qty": st.column_config.NumberColumn(min_value=0, step=1, format="%.0f", width="small"),
            "Precio unit. (USD)": st.column_config.NumberColumn(min_value=0, format="$%.2f", width="small"),
            "IVA": st.column_config.SelectboxColumn(options=["0%", "13%"], width="small", required=True),
            "Especificaciones": st.column_config.TextColumn(width="large"),
        },
        use_container_width=True, num_rows="dynamic", hide_index=True, key="w7og_table",
    )

    edited["IVA"] = edited["IVA"].fillna("0%")

    def _row_subtotal(row: pd.Series) -> float:
        qty_raw = row["Qty"]
        try:
            qty = 1.0 if pd.isna(qty_raw) or qty_raw is None else float(qty_raw)
        except (ValueError, TypeError):
            qty = 1.0
        return round(qty * float(row["Precio unit. (USD)"] or 0), 2)

    row_subtotals = edited.apply(_row_subtotal, axis=1)
    row_iva_pcts = edited["IVA"].apply(lambda s: float(s.rstrip("%")) / 100)
    row_iva_amts = (row_subtotals * row_iva_pcts).round(2)

    subtotal = round(row_subtotals.sum(), 2)
    iva_amount = round(row_iva_amts.sum(), 2)
    total = round(subtotal + iva_amount, 2)

    panel_wp_total = panel_count * panel.get("wp", 0)
    cost_per_wp = round(total / panel_wp_total, 3) if panel_wp_total else 0.0

    st.markdown(
        f'<div style="display:flex;justify-content:flex-end;margin-top:4px;">'
        f'<table style="border-collapse:collapse;font-size:0.9rem;">'
        f'<tr><td style="padding:5px 20px;color:#6b7280;">Subtotal (sin IVA)</td>'
        f'<td style="padding:5px 20px;text-align:right;font-weight:500;">${subtotal:,.2f}</td></tr>'
        f'<tr><td style="padding:5px 20px;color:#6b7280;">IVA</td>'
        f'<td style="padding:5px 20px;text-align:right;font-weight:500;">${iva_amount:,.2f}</td></tr>'
        f'<tr style="border-top:2px solid #e5e7eb;"><td style="padding:8px 20px;font-weight:700;font-size:1.05rem;">TOTAL</td>'
        f'<td style="padding:8px 20px;text-align:right;font-weight:700;font-size:1.05rem;">${total:,.2f}</td></tr>'
        f'</table></div>',
        unsafe_allow_html=True,
    )
    if cost_per_wp:
        st.caption(f"${cost_per_wp:.2f}/Wp")

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w7og_back"):
            st.session_state["wizard_step"] = 6
            _autosave()
            st.rerun()
    with col_next:
        if st.button("Siguiente →", key="w7og_next", type="primary", disabled=not (total > 0)):
            updated_items = []
            for _, row in edited.iterrows():
                qty_raw = row["Qty"]
                qty_parsed = None if pd.isna(qty_raw) or qty_raw is None else qty_raw
                updated_items.append({
                    "item": row["Descripción (ES)"], "item_en": row["Descripción (EN)"],
                    "qty": qty_parsed, "unit_cost": float(row["Precio unit. (USD)"] or 0),
                    "total": float(_row_subtotal(row)), "iva_pct": float(row["IVA"].rstrip("%")) / 100,
                    "specs": row["Especificaciones"], "specs_en": row["Especificaciones"],
                })
            result = {
                "line_items": updated_items, "subtotal_usd": subtotal,
                "iva_usd": iva_amount, "total_usd": total, "cost_per_wp": cost_per_wp,
            }
            st.session_state["wizard_costs"] = result
            return result

    return None


def _og_monthly_coverage_and_sim(
    array: dict, battery: dict, battery_bank: dict, consumption: dict, site: dict,
) -> tuple[dict, dict | None]:
    """
    Real day-by-day simulation (calculations/sizing_off_grid.py:
    simulate_battery_soc()) against the site's real PVGIS reference year —
    shared by the PDF's "Cobertura mensual" chart, Step 8's "Aprovechamiento
    solar" summary, and Step 6's live preview of the same chart (called with
    that step's currently-selected scenario/manual array and battery_bank,
    not the final persisted equipment). One implementation so all three stay
    numerically identical instead of drifting into separate approximations.

    Falls back to a coarse monthly-average approximation (no `recharge` key,
    no utilization sim) when the draft has no cached daily series — e.g. an
    older draft from before fetch_daily_series() existed.

    Returns (monthly_coverage_dict_for_pdf, sim_dict_or_None).
    """
    import calendar as _cal

    kw = array.get("array_kw", 0)
    daily = consumption.get("daily_kwh", 0)
    pvgis_daily_blob = site.get("pvgis_daily") or {}
    pvgis_daily = pvgis_daily_blob.get("daily_kwh_kwp", [])
    pvgis_daily_year = pvgis_daily_blob.get("year")
    monthly_coverage: dict = {}
    sim = None

    if pvgis_daily and pvgis_daily_year and len(pvgis_daily) >= 300:
        from calculations.sizing_off_grid import simulate_battery_soc

        daily_gen = [v * kw * 0.80 for v in pvgis_daily]
        capacity_kwh = battery_bank.get("total_kwh_installed", 0)
        dod_pct = battery.get("dod_pct", 80)
        sim = (
            simulate_battery_soc(daily_gen, daily, capacity_kwh, dod_pct, 100 - dod_pct)
            if capacity_kwh > 0 else None
        )
        if sim:
            days_in_month = [_cal.monthrange(pvgis_daily_year, m)[1] for m in range(1, 13)]
            gen_m, cons_m, rec_m, idx = [], [], [], 0
            for d in days_in_month:
                gen_m.append(round(sum(daily_gen[idx:idx + d]), 1))
                cons_m.append(round(daily * d, 1))
                rec_m.append(round(sum(sim["daily_charge_in_kwh"][idx:idx + d]), 1))
                idx += d
            monthly_coverage = {"generation": gen_m, "consumption": cons_m, "recharge": rec_m}

    if not monthly_coverage:
        pvgis_monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp", [])
        if pvgis_monthly and len(pvgis_monthly) == 12:
            from datetime import date as _dt
            days = [_cal.monthrange(_dt.today().year, m)[1] for m in range(1, 13)]
            monthly_coverage = {
                "generation": [round(v * kw * 0.80, 1) for v in pvgis_monthly],
                "consumption": [round(daily * d, 1) for d in days],
            }

    return monthly_coverage, sim


# ── Step 8 — Revisión + Generar PDF ──────────────────────────────────────────

def step8_review(
    site: dict | None = None,
    loads: dict | None = None,
    equipment: dict | None = None,
    costs: dict | None = None,
    language: str = "es",
) -> None:
    """Technical summary + costs review + Generate PDF."""
    st.markdown("### Paso 8 — Revisión y generación de PDF")

    site = site or st.session_state.get("wizard_site", {})
    consumption = st.session_state.get("wizard_consumption", {})
    equipment = equipment or st.session_state.get("wizard_equipment", {})
    costs = costs or st.session_state.get("wizard_costs", {})
    client = st.session_state.get("wizard_client", {})
    meta = st.session_state.get("wizard_meta", {})

    array = equipment.get("array", {})
    battery_bank = equipment.get("battery_bank", {})
    split_phase = equipment.get("split_phase", {})
    panel = equipment.get("panel", {})
    inverter = equipment.get("inverter", {})
    battery = equipment.get("battery", {})
    cc = equipment.get("charge_controller", {})
    panel_count = equipment.get("panel_count", 0)
    cc_qty = equipment.get("charge_controller_qty", 1)
    inverter_qty = equipment.get("inverter_qty") or (2 if split_phase.get("requires_split_phase") else 1)

    # Computed once here (not inside the "Generar PDF" click handler) so the
    # "Aprovechamiento solar" KV below has a real simulated number to show
    # before the button is ever pressed, and so the PDF's chart/technical-table
    # numbers are the exact same values, not a second independent computation.
    _og_monthly_coverage, _og_sim = _og_monthly_coverage_and_sim(array, battery, battery_bank, consumption, site)

    # Same sectioned HTML-card pattern as wizard/grid_zero.py's step8_review()
    # summary panel (_kv() helper + flex rows), ported here for visual
    # consistency across both wizards (CONTEXT.md 2026-07-25 chart-feedback
    # round). No "Facturación estimada" / "Proyección financiera" sections —
    # off-grid has no utility bill to compare against, so there's nothing
    # equivalent to show; a "Generación y autonomía" section takes their place.
    def _kv(label: str, value: str, subtitle: str = "", accent: bool = False) -> str:
        color = "#0d9488" if accent else "#1e293b"
        sub = (f'<div style="font-size:0.7rem;color:#9ca3af;margin-top:2px;'
               # Wraps instead of ellipsis-truncating: these subtitles are equipment
               # brand+model ("Victron Energy MultiPlus-II 48/3000/35-50"), and a
               # clipped model number is worse than a two-line one — the reader
               # can't tell which unit was quoted. Flex row just grows taller.
               f'white-space:normal;overflow-wrap:anywhere;line-height:1.35;max-width:190px;">'
               f'{subtitle}</div>') if subtitle else ""
        return (
            f'<div style="min-width:100px;">'
            f'<div style="font-size:0.68rem;color:#9ca3af;text-transform:uppercase;'
            f'letter-spacing:0.05em;margin-bottom:3px;">{label}</div>'
            f'<div style="font-size:0.95rem;font-weight:600;color:{color};">{value}</div>'
            f'{sub}</div>'
        )

    _hr  = '<div style="border-top:1px solid #e5e7eb;margin:14px 0;"></div>'
    _row = 'display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start;'
    _sec = ('font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;'
            'letter-spacing:0.07em;margin-bottom:10px;')

    html = '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:20px 24px;">'

    html += f'<div style="{_sec}">Técnico</div>'
    html += f'<div style="{_row}">'
    html += _kv("Sistema", f"{array.get('array_kw', 0)} kW")
    html += _kv("Paneles", str(panel_count), subtitle=f"{panel.get('brand','')} {panel.get('model','')}".strip())
    html += _kv("Inversores", str(inverter_qty), subtitle=f"{inverter.get('brand','')} {inverter.get('model','')}".strip())
    html += _kv("Área", f"{array.get('area_m2', 0)} m²")
    html += _kv("Controlador(es)", str(cc_qty), subtitle=f"{cc.get('brand','')} {cc.get('model','')}".strip())
    html += _kv("Baterías", str(battery_bank.get('battery_count', 0)), subtitle=f"{battery.get('brand','')} {battery.get('model','')}".strip())
    html += '</div>'

    html += _hr
    html += f'<div style="{_sec}">Generación y autonomía</div>'
    html += f'<div style="{_row}">'
    html += _kv("Generación diaria", f"{array.get('daily_generation_kwh', 0)} kWh/día")
    html += _kv("Banco de baterías", f"{battery_bank.get('total_kwh_installed', 0)} kWh")
    html += _kv("Descarga", f"{battery_bank.get('discharge_pct', 0)}%")
    html += _kv("Aprovechamiento solar", f"{_og_sim['utilization_pct']:.0f}%" if _og_sim else "—")
    html += '</div>'

    html += _hr
    html += f'<div style="{_sec}">Costos del proyecto</div>'
    html += f'<div style="{_row}">'
    html += _kv("$/Wp", f"${costs.get('cost_per_wp', 0):.2f}")
    html += _kv("Subtotal", f"${costs.get('subtotal_usd', 0):,.2f}")
    html += _kv("IVA", f"${costs.get('iva_usd', 0):,.2f}")
    html += _kv("Total", f"${costs.get('total_usd', 0):,.2f}", accent=True)
    html += '</div>'

    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)

    if split_phase.get("requires_split_phase"):
        st.warning(f"⚠️ {split_phase.get('warning_message', '')}")

    st.divider()

    st.markdown("#### Párrafo introductorio")
    st.caption(
        "Este texto abre la propuesta en el PDF. Puedes escribirlo a mano o generarlo con IA — "
        "la IA solo puede usar las cifras ya calculadas arriba (potencia, paneles, baterías, "
        "generación, autonomía); no inventa precios, plazos ni garantías. Revísalo siempre antes "
        "de enviar."
    )

    # Writing BOTH keys matters. Once a widget with key="w8og_intro" has been
    # instantiated, Streamlit keeps its value in session_state under that key
    # and that wins over the `value=` argument on the next run — so setting
    # only "wizard_proposal_text" leaves the textarea visibly empty even though
    # generation succeeded (observed in testing). Assigning the widget key
    # before the rerun is what actually makes the new text appear.
    if st.button("✨ Generar con IA", key="w8og_gen_intro"):
        from ai.proposal_writer import generate_intro

        with st.spinner("Redactando párrafo introductorio…"):
            params = {
                "system_type_key": meta.get("system_type", "off_grid"),
                "system_type": "Off-Grid (sistema aislado)"
                    if meta.get("system_type") == "off_grid" else "Híbrido (red + respaldo)",
                "client_name": client.get("name", ""),
                "location": client.get("location") or _site_location(site),
                "system_kw": array.get("array_kw", 0),
                "panel_count": panel_count,
                "panel_model": f"{panel.get('brand','')} {panel.get('model','')}".strip(),
                "inverter_count": inverter_qty,
                "inverter_model": f"{inverter.get('brand','')} {inverter.get('model','')}".strip(),
                "battery_count": battery_bank.get("battery_count", 0),
                "battery_kwh": battery_bank.get("total_kwh_installed", 0),
                "autonomy_days": consumption.get("autonomy_days", 0),
                "daily_generation_kwh": array.get("daily_generation_kwh", 0),
                "daily_consumption_kwh": consumption.get("daily_kwh", 0),
            }
            generated = generate_intro(params, language).get(language, "")
        st.session_state["wizard_proposal_text"] = generated
        st.session_state["w8og_intro"] = generated
        st.rerun()

    # Seed the widget's own key once, then let the widget own its value. Passing
    # `value=` AND assigning the key (which the IA button has to do — see above)
    # trips Streamlit's "created with a default value but also had its value set
    # via the Session State API" warning.
    st.session_state.setdefault("w8og_intro", st.session_state.get("wizard_proposal_text", ""))
    proposal_text = st.text_area(
        "Texto que aparecerá en la propuesta", height=140, key="w8og_intro",
    )
    st.session_state["wizard_proposal_text"] = proposal_text

    st.divider()
    col_back, _, col_gen = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w8og_back"):
            st.session_state["wizard_step"] = 7
            _autosave()
            st.rerun()
    with col_gen:
        if st.button("📄 Generar PDF", key="w8og_generate", type="primary"):
            from wizard.state import get_company_info, get_bank_info

            company = get_company_info()
            bank = get_bank_info()

            cost_items = []
            for li in costs.get("line_items", []):
                qty = li.get("qty")
                cost_items.append({
                    "item": li.get("item", ""), "item_en": li.get("item_en", li.get("item", "")),
                    "qty": qty, "specs": li.get("specs", ""),
                    "specs_en": li.get("specs_en", li.get("specs", "")),
                    "total": float(li.get("total", 0)),
                })

            quote_num_str = ""
            actual_vnum = 1
            try:
                from database.proposals_db import format_quote_number, get_proposal, get_version as _gv
                proposal_id = st.session_state.get("wizard_proposal_id")
                version_id_now = st.session_state.get("wizard_version_id")
                if proposal_id and version_id_now:
                    prop = get_proposal(proposal_id)
                    ver = _gv(version_id_now)
                    if prop and prop.get("quote_number"):
                        actual_vnum = (ver.get("version_number") or 1) if ver else 1
                        quote_num_str = format_quote_number(prop["quote_number"], prop.get("created_at", ""), actual_vnum)
            except Exception:
                pass

            inv_warranty = equipment.get("inverter", {}).get("warranty_yr", 5)
            battery_warranty = equipment.get("battery", {}).get("warranty_yr", 10)

            from datetime import date as _dt

            pdf_data = {
                "date": _dt.today().strftime("%d/%m/%Y"),
                "quote_number": quote_num_str,
                "monthly_coverage": _og_monthly_coverage,
                "client": {
                    "name": client.get("name", ""),
                    "location": client.get("location") or _site_location(site),
                    "nise": client.get("nise", "N/A"),
                },
                "system_type_label": "Off-Grid" if meta.get("system_type") == "off_grid" else "Híbrido",
                "intro_lines": [proposal_text] if proposal_text else [],
                "cost_items": cost_items,
                "subtotal_usd": costs.get("subtotal_usd", costs.get("total_usd", 0)),
                "iva_usd": costs.get("iva_usd", 0),
                "total_usd": costs.get("total_usd", 0),
                "technical": {
                    "system_kw": array.get("array_kw", 0),
                    "area_m2": array.get("area_m2", 0),
                    "panel_count": equipment.get("panel_count", 0),
                    "inverter_count": inverter_qty,
                    "daily_generation_kwh": array.get("daily_generation_kwh", 0),
                    "battery_kwh": battery_bank.get("total_kwh_installed", 0),
                    "battery_count": battery_bank.get("battery_count", 0),
                    "discharge_pct": battery_bank.get("discharge_pct", 0),
                    "autonomy_days": consumption.get("autonomy_days", 1),
                    "voltage_v": consumption.get("voltage_v", 120),
                    "utilization_pct": _og_sim["utilization_pct"] if _og_sim else battery_bank.get("utilization_pct"),
                },
                "cost_per_wp": costs.get("cost_per_wp", 0),
                "warranty_inverter_years": f"{inv_warranty} años",
                "warranty_inverter_years_en": f"{inv_warranty} years",
                "warranty_battery_years": f"{battery_warranty} años",
                "warranty_battery_years_en": f"{battery_warranty} years",
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
                system_type_key = meta.get("system_type", "off_grid")
                with st.spinner("Generando PDF…"):
                    pdf_bytes = generate_pdf(pdf_data, system_type_key, language)

                from wizard.state import pdf_filename

                lang_label = "ES" if language == "es" else "EN"
                st.success(f"PDF generado — {len(pdf_bytes):,} bytes")
                st.download_button(
                    label=f"⬇ Descargar PDF ({lang_label})", data=pdf_bytes,
                    file_name=pdf_filename(quote_num_str, client.get("name", ""), lang_label),
                    mime="application/pdf", key="w8og_download",
                )

                proposal_id = st.session_state.get("wizard_proposal_id")
                version_id = st.session_state.get("wizard_version_id")
                if proposal_id and version_id:
                    try:
                        from proposals.generator import upload_pdf
                        from database.proposals_db import save_pdf_path
                        path = upload_pdf(pdf_bytes, proposal_id, actual_vnum, client.get("name", "cliente"))
                        save_pdf_path(version_id, path)
                    except Exception:
                        pass
            except Exception as e:
                st.error(f"Error generando PDF: {e}")
                st.exception(e)
