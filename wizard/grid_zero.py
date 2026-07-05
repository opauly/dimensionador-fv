from __future__ import annotations
"""Wizard steps 4–8 for Grid Zero proposals. Phase 2."""
import pandas as pd
import streamlit as st

from wizard.state import autosave_if_possible as _autosave

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
        client_nise = st.session_state.get("wizard_client", {}).get("nise", "N/A")
        nise = st.text_input("NISE (número de cliente)", value=current.get("nise", client_nise), key="w4_nise")

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
            _autosave()
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
                # Save tariff rate fields so step 5 can estimate bills without extra DB calls
                "access_charge_crc":  selected_tariff.get("access_charge_crc", 0),
                "bomberos_pct":       selected_tariff.get("bomberos_pct", 0.0175),
                "iva_threshold_kwh":  selected_tariff.get("iva_threshold_kwh", 280),
            }
            st.session_state["wizard_utility"] = result
            return result

    return None


# ── Step 5 — Consumption ─────────────────────────────────────────────────────

_MONTH_NAMES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
_MONTH_ABBR_ES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

_SOURCE_LABELS = {"bill": "Factura eléctrica", "loads": "Cargas instaladas", "manual": "Ingreso manual"}

_DEFAULT_LOADS = [
    {"Descripción": "Refrigerador",        "W": 150,  "Und": 1, "h/día": 24, "días/mes": 30},
    {"Descripción": "Iluminación general", "W": 200,  "Und": 1, "h/día": 6,  "días/mes": 30},
    {"Descripción": "TV + entretenimiento","W": 150,  "Und": 1, "h/día": 5,  "días/mes": 30},
    {"Descripción": "Aire acondicionado",  "W": 1200, "Und": 1, "h/día": 8,  "días/mes": 20},
    {"Descripción": "Lavadora",            "W": 500,  "Und": 1, "h/día": 1,  "días/mes": 8},
]


def _render_bill_section() -> None:
    """Bill PDF upload, Claude extraction, and apply-to-table action."""
    st.markdown("**Subir factura eléctrica (ICE, CNFL, JASEC…)**")
    st.caption("Sube una o más facturas en PDF. La IA extrae el historial de consumo automáticamente.")

    uploaded_files = st.file_uploader(
        "Seleccionar facturas en PDF",
        type=["pdf"],
        accept_multiple_files=True,
        key="w5_bill_files",
    )

    if not uploaded_files:
        st.session_state.pop("w5_bill_history", None)
        st.session_state.pop("w5_bill_meta", None)
        return

    if st.button("🔍 Extraer historial de consumo", key="w5_bill_extract"):
        with st.spinner("Analizando facturas…"):
            from calculations.bill_parser import parse_bill_pdf
            all_history = []
            meta = {}
            errors = []
            for f in uploaded_files:
                try:
                    result = parse_bill_pdf(f.read())
                    all_history.extend(result.get("history", []))
                    meta = {"distributor": result.get("distributor", ""), "nise": result.get("nise", "")}
                except Exception as e:
                    errors.append(f"{f.name}: {e}")
            if errors:
                for err in errors:
                    st.error(f"⚠ {err}")
            if all_history:
                # Auto-fill Factura (₡) from the tariff selected in Step 4
                utility = st.session_state.get("wizard_utility", {})
                tariff_id = utility.get("tariff_type_id")
                if tariff_id:
                    try:
                        from database.tariffs_db import get_tariff_tiers
                        from calculations.tariff_calculator import fill_bill_amounts
                        tariff_info = {
                            "access_charge_crc": utility.get("access_charge_crc", 0),
                            "bomberos_pct":       utility.get("bomberos_pct", 0.0175),
                            "iva_threshold_kwh":  utility.get("iva_threshold_kwh", 280),
                            "tiers": get_tariff_tiers(tariff_id),
                        }
                        all_history = fill_bill_amounts(all_history, tariff_info)
                    except Exception:
                        pass  # fail silently — bill amounts stay as extracted
                st.session_state["w5_bill_history"] = all_history
                st.session_state["w5_bill_meta"] = meta

    history = st.session_state.get("w5_bill_history", [])
    meta = st.session_state.get("w5_bill_meta", {})

    if history:
        dist = meta.get("distributor", "—")
        nise = meta.get("nise", "—")
        st.success(f"Distribuidora: **{dist}** · NISE: **{nise}** · {len(history)} meses extraídos")

        preview_df = pd.DataFrame(history).rename(
            columns={"month": "Mes", "year": "Año", "kwh": "kWh", "bill_crc": "Factura (₡)"}
        )
        preview_df["Factura (₡)"] = preview_df["Factura (₡)"].fillna(0).astype(float)
        st.dataframe(preview_df, hide_index=True, use_container_width=True, height=240)

        # Overwrite warning
        existing_meta = st.session_state.get("w5_applied_source_meta", {})
        if existing_meta.get("source") and existing_meta["source"] != "bill":
            st.warning(
                f"⚠ La tabla tiene datos de **{existing_meta.get('label', _SOURCE_LABELS.get(existing_meta['source'], ''))}**. "
                "Al aplicar se reemplazarán."
            )

        if st.button("✅ Aplicar al historial de 12 meses", key="w5_bill_apply", type="primary"):
            with st.spinner("Estimando meses faltantes con IA…"):
                from calculations.bill_parser import build_12_month_grid
                utility = st.session_state.get("wizard_utility", {})
                tariff_id = utility.get("tariff_type_id")
                tariff_info = None
                if tariff_id:
                    try:
                        from database.tariffs_db import get_tariff_tiers
                        tariff_info = {
                            "access_charge_crc": utility.get("access_charge_crc", 0),
                            "bomberos_pct":       utility.get("bomberos_pct", 0.0175),
                            "iva_threshold_kwh":  utility.get("iva_threshold_kwh", 280),
                            "tiers": get_tariff_tiers(tariff_id),
                        }
                    except Exception:
                        pass
                site = st.session_state.get("wizard_site", {})
                location = ", ".join(filter(None, [site.get("city"), site.get("province"), "Costa Rica"]))
                grid = build_12_month_grid(history, location=location, tariff_info=tariff_info)
            # Build source badge label from bill date range
            months_with_data = [(h["month"], h["year"]) for h in history if float(h.get("kwh") or 0) > 0]
            if months_with_data:
                mn_m, mn_y = min(months_with_data, key=lambda x: (x[1], x[0]))
                mx_m, mx_y = max(months_with_data, key=lambda x: (x[1], x[0]))
                range_str = f"{_MONTH_ABBR_ES[mn_m-1]} {mn_y} – {_MONTH_ABBR_ES[mx_m-1]} {mx_y}"
            else:
                range_str = f"{len(history)} meses"
            st.session_state["w5_applied_source_meta"] = {
                "source": "bill",
                "label": f"Factura {meta.get('distributor', '')} · {range_str}",
            }
            st.session_state["w5_applied_months"] = grid
            st.session_state["w5_table_ver"] = st.session_state.get("w5_table_ver", 0) + 1
            st.rerun()


def _render_loads_section() -> None:
    """Editable electrical loads table with tablero import and kWh/month estimator."""
    st.markdown("**Cargas eléctricas instaladas**")

    # ── Tablero import ────────────────────────────────────────────────────────
    with st.expander("📋 Importar desde tablero eléctrico", expanded=False):
        st.caption("Sube una imagen o PDF del tablero eléctrico. La IA extrae los circuitos y estima horas de uso.")
        uploaded_tablero = st.file_uploader(
            "Imagen (JPG/PNG) o PDF del tablero",
            type=["jpg", "jpeg", "png", "pdf"],
            key="w5_tablero_file",
        )
        if uploaded_tablero and st.button("⚡ Extraer cargas del tablero", key="w5_tablero_extract"):
            with st.spinner("Analizando tablero con IA…"):
                try:
                    from calculations.tablero_parser import parse_tablero
                    loads = parse_tablero(uploaded_tablero.read(), uploaded_tablero.type)
                    st.session_state["w5_loads_data"] = loads
                    st.session_state["w5_loads_ver"] = st.session_state.get("w5_loads_ver", 0) + 1
                    st.success(f"{len(loads)} circuitos extraídos. Revisa y ajusta la tabla.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al analizar el tablero: {e}")

    # ── Loads data editor ─────────────────────────────────────────────────────
    st.caption("Edita los equipos instalados. El consumo estimado se aplica a los 12 meses.")
    loads_ver = st.session_state.get("w5_loads_ver", 0)
    base_loads = st.session_state.get("w5_loads_data", _DEFAULT_LOADS)

    edited_loads = st.data_editor(
        pd.DataFrame(base_loads),
        column_config={
            "Descripción": st.column_config.TextColumn("Descripción", width="medium"),
            "W": st.column_config.NumberColumn("Potencia (W)", min_value=0, format="%.0f"),
            "Und": st.column_config.NumberColumn("Cantidad", min_value=1, step=1, format="%d"),
            "h/día": st.column_config.NumberColumn("Horas/día", min_value=0.0, max_value=24.0, format="%.1f"),
            "días/mes": st.column_config.NumberColumn("Días/mes", min_value=0, max_value=31, step=1, format="%d"),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"w5_loads_{loads_ver}",
    )

    total_kwh = 0.0
    for _, row in edited_loads.iterrows():
        w = float(row.get("W") or 0)
        qty = float(row.get("Und") or 1)
        h = float(row.get("h/día") or 0)
        d = float(row.get("días/mes") or 0)
        total_kwh += w * qty * h * d / 1000

    # Overwrite warning (shown above metric/button when there is data from another source)
    existing_meta = st.session_state.get("w5_applied_source_meta", {})
    if total_kwh > 0 and existing_meta.get("source") and existing_meta["source"] != "loads":
        st.warning(
            f"⚠ La tabla tiene datos de **{existing_meta.get('label', _SOURCE_LABELS.get(existing_meta['source'], ''))}**. "
            "Al aplicar se reemplazarán."
        )

    col_metric, col_btn = st.columns([2, 1])
    with col_metric:
        st.metric("Consumo nominal", f"{total_kwh:,.0f} kWh/mes")
    with col_btn:
        if total_kwh > 0 and st.button("Aplicar a 12 meses →", key="w5_loads_apply", type="primary"):
            with st.spinner("Estimando variación estacional con IA…"):
                from calculations.load_estimator import estimate_loads_12_months_ai
                from calculations.tariff_calculator import estimate_bill_crc
                loads_data = edited_loads.to_dict("records")
                site = st.session_state.get("wizard_site", {})
                location = ", ".join(filter(None, [site.get("city"), site.get("province"), "Costa Rica"]))
                monthly_kwh = estimate_loads_12_months_ai(loads_data, location=location)
                utility = st.session_state.get("wizard_utility", {})
                tariff_id = utility.get("tariff_type_id")
                tariff_info = None
                if tariff_id:
                    try:
                        from database.tariffs_db import get_tariff_tiers
                        tariff_info = {
                            "access_charge_crc": utility.get("access_charge_crc", 0),
                            "bomberos_pct":       utility.get("bomberos_pct", 0.0175),
                            "iva_threshold_kwh":  utility.get("iva_threshold_kwh", 280),
                            "tiers": get_tariff_tiers(tariff_id),
                        }
                    except Exception:
                        pass
                grid = [
                    {
                        "month": _MONTH_NAMES[i],
                        "kwh": round(monthly_kwh[i], 1),
                        "bill_crc": float(estimate_bill_crc(monthly_kwh[i], tariff_info)) if tariff_info and monthly_kwh[i] > 0 else 0.0,
                    }
                    for i in range(12)
                ]
            from_tablero = st.session_state.get("w5_loads_ver", 0) > 0
            n = len(loads_data)
            st.session_state["w5_applied_source_meta"] = {
                "source": "loads",
                "label": f"Tablero · {n} circuitos" if from_tablero else f"Cargas instaladas · {n} equipos",
            }
            st.session_state["w5_applied_months"] = grid
            st.session_state["w5_table_ver"] = st.session_state.get("w5_table_ver", 0) + 1
            st.rerun()


def step5_consumption() -> dict | None:
    """12-month kWh / bill table with three input modes. Returns consumption dict."""
    st.markdown("### Paso 5 — Historial de consumo eléctrico")

    current = st.session_state.get("wizard_consumption", {})

    # Restore applied months and source metadata from saved draft on first load
    if "w5_applied_months" not in st.session_state:
        saved = current.get("months_data", [])
        st.session_state["w5_applied_months"] = saved if (saved and len(saved) == 12) else None
    if "w5_applied_source_meta" not in st.session_state and current.get("source"):
        saved_src = current["source"]
        st.session_state["w5_applied_source_meta"] = {
            "source": saved_src,
            "label": _SOURCE_LABELS.get(saved_src, saved_src) + " (guardado)",
        }

    # ── Source selector ───────────────────────────────────────────────────────
    SOURCE_OPTS = {
        "📄 Subir factura (PDF)": "bill",
        "⚡ Cargas instaladas": "loads",
        "✍️ Manual": "manual",
    }
    saved_source = current.get("source", "manual")
    source_label = st.radio(
        "Fuente del historial de consumo",
        list(SOURCE_OPTS.keys()),
        index=list(SOURCE_OPTS.values()).index(
            saved_source if saved_source in SOURCE_OPTS.values() else "manual"
        ),
        horizontal=True,
        key="w5_source",
    )
    source = SOURCE_OPTS[source_label]

    # ── Source helper section ─────────────────────────────────────────────────
    if source == "bill":
        _render_bill_section()
    elif source == "loads":
        _render_loads_section()

    # ── 12-month editable table ───────────────────────────────────────────────
    st.divider()
    st.caption("Historial mensual — ajusta los valores si es necesario.")

    src_meta = st.session_state.get("w5_applied_source_meta")
    if src_meta and src_meta.get("label"):
        st.markdown(
            f'<span style="background:#f0f7f0;border:1px solid #4BAE6A;border-radius:4px;'
            f'padding:2px 8px;font-size:0.75rem;color:#2d7a4f;">📊 Fuente: {src_meta["label"]}</span>',
            unsafe_allow_html=True,
        )

    applied = st.session_state.get("w5_applied_months")
    if applied and len(applied) == 12:
        df_init = pd.DataFrame(applied)[["month", "kwh", "bill_crc"]]
    else:
        df_init = pd.DataFrame({
            "month": _MONTH_NAMES,
            "kwh": [0.0] * 12,
            "bill_crc": [0.0] * 12,
        })

    table_ver = st.session_state.get("w5_table_ver", 0)
    edited_df = st.data_editor(
        df_init,
        column_config={
            "month": st.column_config.TextColumn("Mes", disabled=True, width="small"),
            "kwh": st.column_config.NumberColumn("kWh", min_value=0, format="%.0f", width="small"),
            "bill_crc": st.column_config.NumberColumn("Factura (₡)", min_value=0, format="%.0f", width="medium"),
        },
        use_container_width=True,
        hide_index=True,
        key=f"w5_table_{table_ver}",
    )

    kwh_values = edited_df["kwh"].tolist()
    bill_values = edited_df["bill_crc"].tolist()

    # ── Auto-recalculate Factura when kWh changes (any mode) ─────────────────
    old_kwh = [round(v or 0) for v in df_init["kwh"].tolist()]
    new_kwh = [round(v or 0) for v in kwh_values]
    if old_kwh != new_kwh:
        utility = st.session_state.get("wizard_utility", {})
        tariff_id = utility.get("tariff_type_id")
        if tariff_id:
            try:
                from database.tariffs_db import get_tariff_tiers
                from calculations.tariff_calculator import estimate_bill_crc
                tariff_info = {
                    "access_charge_crc": utility.get("access_charge_crc", 0),
                    "bomberos_pct":       utility.get("bomberos_pct", 0.0175),
                    "iva_threshold_kwh":  utility.get("iva_threshold_kwh", 280),
                    "tiers": get_tariff_tiers(tariff_id),
                }
                new_bills = [float(estimate_bill_crc(k, tariff_info)) for k in new_kwh]
                st.session_state["w5_applied_months"] = [
                    {"month": _MONTH_NAMES[i], "kwh": float(new_kwh[i]), "bill_crc": new_bills[i]}
                    for i in range(12)
                ]
                # Update source badge: manual edits on top of another source get an "· editada" suffix
                prev_meta = st.session_state.get("w5_applied_source_meta", {})
                if source == "manual" or not prev_meta.get("source"):
                    new_meta = {"source": "manual", "label": "Ingreso manual"}
                else:
                    base_label = prev_meta.get("label", _SOURCE_LABELS.get(prev_meta["source"], prev_meta["source"]))
                    if not base_label.endswith("· editada"):
                        base_label = base_label + " · editada"
                    new_meta = {"source": prev_meta["source"], "label": base_label}
                st.session_state["w5_applied_source_meta"] = new_meta
                st.session_state["w5_table_ver"] = st.session_state.get("w5_table_ver", 0) + 1
                st.rerun()
            except Exception:
                pass

    filled = [v for v in kwh_values if v and v > 0]
    avg_kwh = round(sum(filled) / len(filled), 2) if filled else 0.0
    filled_bills = [v for v in bill_values if v and v > 0]
    avg_bill = round(sum(filled_bills) / len(filled_bills)) if filled_bills else 0

    if avg_kwh > 0:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Consumo promedio", f"{avg_kwh:,.0f} kWh/mes")
        with col2:
            st.metric("Factura promedio", f"₡{avg_bill:,.0f}/mes")

        if len(filled) >= 3:
            import plotly.graph_objects as go
            fig = go.Figure(go.Bar(
                x=_MONTH_NAMES,
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

    # ── Interconnection permit ────────────────────────────────────────────────
    icpe_cost = st.number_input(
        "Costo del permiso de interconexión (USD)",
        value=float(current.get("interconnection_permit_usd", 1000.0)),
        min_value=0.0,
        step=100.0,
        format="%.2f",
        key="w5_icpe",
    )

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w5_back"):
            st.session_state["wizard_step"] = 4
            _autosave()
            st.rerun()
    with col_next:
        can_continue = avg_kwh > 0
        if st.button("Siguiente →", key="w5_next", type="primary", disabled=not can_continue):
            months_data = [
                {"month": _MONTH_NAMES[i], "kwh": float(kwh_values[i] or 0), "bill_crc": float(bill_values[i] or 0)}
                for i in range(12)
            ]
            result = {
                "source": source,
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

def _mppt_param_row(label: str, value: str, ok: bool, limit_str: str) -> None:
    color  = "#166534" if ok else "#991b1b"
    bg     = "#f0fdf4" if ok else "#fef2f2"
    border = "#86efac" if ok else "#fca5a5"
    icon   = "✓" if ok else "✗"
    # CSS grid gives stable 3-column alignment regardless of label length
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


def _estimate_daytime_fraction_ai(loads: list[dict], location: str) -> tuple[float, str]:
    """
    Call Claude Haiku to estimate the fraction of daily consumption that
    occurs during solar-production hours (roughly 7 am – 5 pm).

    Returns (daytime_fraction, explanatory_note).
    Falls back to 0.45 if the AI call fails.
    """
    import os, json
    try:
        import anthropic
        loads_text = json.dumps(loads, ensure_ascii=False) if loads else "No hay datos de cargas disponibles."
        prompt = (
            "Eres un ingeniero solar en Costa Rica. Analiza el perfil de cargas eléctricas de este proyecto "
            f"y estima qué fracción del consumo total ocurre durante las horas de producción solar (7:00–17:00).\n\n"
            f"Ubicación: {location}\n"
            f"Cargas instaladas (JSON):\n{loads_text}\n\n"
            "Considera: uso diurno de electrodomésticos, AC, bombas de agua, iluminación, etc. "
            "Considera que la noche, la madrugada y días nublados también consumen energía de la red.\n\n"
            "Responde SOLO con JSON (sin markdown):\n"
            '{"daytime_fraction": 0.48, "note": "El perfil tiene uso significativo de AC y bomba de agua durante el día..."}'
        )
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
        data = json.loads(text)
        fraction = float(data.get("daytime_fraction") or 0.45)
        fraction = max(0.1, min(0.9, fraction))
        note = str(data.get("note") or "")
        return fraction, note
    except Exception:
        return 0.45, ""


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

    Only the portion of generation that coincides with daytime consumption
    can be used. Nighttime consumption is always sourced from the grid.

      daytime_kwh   = avg_kwh × daytime_fraction   (consumption during solar hours)
      self_consumed = min(gen, daytime_kwh)          (solar actually used on-site)
      curtailed     = max(0, gen − daytime_kwh)      (solar that can't be absorbed)
      grid_kwh      = avg_kwh − self_consumed        (still drawn from grid)
      coverage      = self_consumed / avg_kwh         (always < 100 % due to nights)
    """
    from calculations.tariff_calculator import estimate_bill_crc as _est
    gen = round(system_kw * avg_irradiance)

    daytime_kwh   = avg_kwh * daytime_fraction
    self_consumed = min(float(gen), daytime_kwh)
    curtailed     = max(0, gen - int(daytime_kwh))       # wasted solar (curtailed)
    grid_kwh      = max(0.0, avg_kwh - self_consumed)    # always > 0 because of nights

    coverage = round(self_consumed / avg_kwh * 100, 1) if avg_kwh > 0 else 0.0
    self_consumption_pct = round(self_consumed / gen * 100) if gen > 0 else 0

    if tariff_info:
        new_bill = _est(grid_kwh, tariff_info)
        savings  = max(0, round(avg_bill_crc - new_bill))
    else:
        new_bill = None
        savings  = None
    return {
        "gen": int(gen),
        "grid_kwh": int(grid_kwh),
        "coverage": coverage,
        "curtailed": curtailed,
        "new_bill": int(new_bill) if new_bill is not None else None,
        "savings": savings,
        "self_consumption_pct": self_consumption_pct,
    }


def step6_equipment() -> dict | None:
    """Panel + inverter selection, MPPT validation, 3 auto scenarios + manual mode."""
    st.markdown("### Paso 6 — Equipos")

    from database.equipment_db import list_panels, list_inverters, list_monitoring_devices
    from calculations.mppt import validate_string_design, check_design

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

    default_panel_idx = next((i for i, p in enumerate(panels) if p["id"] == current.get("panel_id")), 0)
    default_inv_idx   = next((i for i, inv in enumerate(inverters) if inv["id"] == current.get("inverter_id")), 0)

    col1, col2 = st.columns(2)
    with col1:
        panel_label    = st.selectbox("Panel solar *", list(panel_options.keys()), index=default_panel_idx, key="w6_panel")
        selected_panel = panel_options[panel_label]
        area_panel     = float(selected_panel.get("width_m") or 0) * float(selected_panel.get("height_m") or 0)

        st.markdown(
            f'<div style="background:{BRAND_GREEN_LIGHT};border-radius:6px;padding:0.6rem 1rem;font-size:0.85rem;line-height:1.8;">'
            f'<b>{selected_panel["brand"]} {selected_panel["model"]}</b><br>'
            f'Voc: {selected_panel["voc"]} V<br>'
            f'Vmp: {selected_panel["vmp"]} V<br>'
            f'Isc: {selected_panel["isc"]} A<br>'
            f'Imp: {selected_panel["imp"]} A<br>'
            f'Área: {area_panel:.2f} m²<br>'
            f'Garantía producto: {selected_panel.get("warranty_product_yr", "—")} años<br>'
            f'Garantía potencia: {selected_panel.get("warranty_power_yr", "—")} años'
            f'</div>',
            unsafe_allow_html=True,
        )

    with col2:
        inv_label        = st.selectbox("Inversor *", list(inverter_options.keys()), index=default_inv_idx, key="w6_inv")
        selected_inverter = inverter_options[inv_label]

        st.markdown(
            f'<div style="background:{BRAND_GREEN_LIGHT};border-radius:6px;padding:0.6rem 1rem;font-size:0.85rem;line-height:1.8;">'
            f'<b>{selected_inverter["brand"]} {selected_inverter["model"]}</b><br>'
            f'Vmax: {selected_inverter.get("vmax", "—")} V<br>'
            f'MPPT: {selected_inverter.get("vmin_mppt", "—")}–{selected_inverter.get("vmax_mppt", "—")} V<br>'
            f'Imax MPPT: {selected_inverter.get("imax_mppt", "—")} A<br>'
            f'Canales MPPT: {selected_inverter.get("mppt_channels", "—")}<br>'
            f'Garantía: {selected_inverter.get("warranty_yr", "—")} años'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Clear manual selection when equipment changes
    equip_key = f"{selected_panel['id']}_{selected_inverter['id']}"
    if st.session_state.get("w6_equip_key") != equip_key:
        st.session_state["w6_equip_key"] = equip_key
        st.session_state.pop("w6_use_manual", None)
        st.session_state.pop("w6_scenarios", None)
        st.session_state.pop("w6_selected_scenario", None)

    # ── Consumption + tariff context ──────────────────────────────────────────
    avg_kwh        = consumption.get("avg_kwh", 0)
    avg_bill_crc   = consumption.get("avg_bill_crc", 0)
    pvgis_monthly  = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp", [])
    avg_irradiance = sum(pvgis_monthly) / 12 if pvgis_monthly else 127.0

    # Read AI coverage estimate early — it informs target_kw for MPPT sizing.
    # Defaults to 0.45 until the AI call runs; after first "Calcular MPPT" the
    # cached fraction is used so re-clicking recalculates with the real value.
    coverage_ai      = st.session_state.get("w6_coverage_ai", {})
    daytime_fraction = float(coverage_ai.get("fraction") or 0.45)
    ai_note          = str(coverage_ai.get("note") or "")

    # Zero-export target: size system to cover daytime consumption (not 100%),
    # so scenarios span the useful range around the saturation point.
    daytime_kwh = avg_kwh * daytime_fraction
    target_kw   = (daytime_kwh / avg_irradiance) if avg_irradiance > 0 else None

    utility = st.session_state.get("wizard_utility", {})
    tariff_id = utility.get("tariff_type_id")
    tariff_info: dict | None = None
    if tariff_id:
        try:
            from database.tariffs_db import get_tariff_tiers
            tariff_info = {
                "access_charge_crc": utility.get("access_charge_crc", 0),
                "bomberos_pct":      utility.get("bomberos_pct", 0.0175),
                "iva_threshold_kwh": utility.get("iva_threshold_kwh", 280),
                "tiers": get_tariff_tiers(tariff_id),
            }
        except Exception:
            pass

    # ── Auto MPPT scenarios ───────────────────────────────────────────────────

    loads    = st.session_state.get("w5_loads_data", [])
    location = site.get("city") or "Costa Rica"

    st.divider()
    if st.button("⚡ Calcular configuración MPPT", key="w6_calc_mppt"):
        with st.spinner("Estimando autoconsumo con IA…"):
            fraction, ai_note_new = _estimate_daytime_fraction_ai(loads, location)
            st.session_state["w6_coverage_ai"] = {"fraction": fraction, "note": ai_note_new}
            # Update locals so target_kw reflects the fresh AI fraction immediately
            daytime_fraction = fraction
            ai_note          = ai_note_new
            daytime_kwh      = avg_kwh * daytime_fraction
            target_kw        = (daytime_kwh / avg_irradiance) if avg_irradiance > 0 else None
        with st.spinner("Calculando escenarios de strings…"):
            scenarios = validate_string_design(selected_panel, selected_inverter, target_kw)
            st.session_state["w6_scenarios"] = scenarios
            st.session_state.pop("w6_use_manual", None)

    scenarios = st.session_state.get("w6_scenarios", current.get("scenarios"))
    using_manual = st.session_state.get("w6_use_manual", False)
    selected_scenario_label = st.session_state.get("w6_selected_scenario", current.get("mppt_scenario", "B"))

    if scenarios:
        st.markdown("#### 🔁 Opción 1 — Configuración automática")
        st.caption("El sistema calcula y propone tres configuraciones MPPT basadas en tu consumo y equipo seleccionado.")
        scenario_data = []
        for s in scenarios:
            ok_icon = "✅" if s["within_limits"] else "⚠️"
            scenario_data.append({
                "Escenario":       f"Escenario {s['scenario']}",
                "Paneles/string":  s["panels_per_string"],
                "Strings":         s["strings"],
                "Total paneles":   s["total_panels"],
                "Sistema (kW)":    s["system_kw"],
                "Área (m²)":       s.get("area_m2") or round(s["total_panels"] * area_panel, 1),
                "Voc total (V)":   s["voc_total"],
                "Vmp total (V)":   s["vmp_total"],
                "Estado":          ok_icon,
                "Notas":           s["notes"],
            })
        st.dataframe(pd.DataFrame(scenario_data), use_container_width=True, hide_index=True)

        valid_scenarios = [s for s in scenarios if s["within_limits"]]
        if not valid_scenarios:
            st.warning("Ningún escenario es válido con este par panel/inversor.")
        else:
            # ── Projection cards with inline selector ─────────────────────────
            # Each column: [select button] + [card] — radio and card are aligned.
            if not using_manual:
                # Ensure selected_scenario_label is valid among valid scenarios
                valid_labels = [s["scenario"] for s in valid_scenarios]
                if selected_scenario_label not in valid_labels:
                    selected_scenario_label = valid_labels[min(1, len(valid_labels) - 1)]

            proj_cols = st.columns(len(scenarios))
            for col, s in zip(proj_cols, scenarios):
                is_sel   = (s["scenario"] == selected_scenario_label) and not using_manual
                is_valid = s["within_limits"]
                p = _scenario_projection(
                    s["system_kw"], avg_irradiance, avg_kwh, avg_bill_crc,
                    tariff_info, daytime_fraction,
                )
                border = BRAND_GREEN if is_sel else "#d1d5db"
                bg     = BRAND_GREEN_LIGHT if is_sel else "#f9fafb"
                curtailed_line = (
                    f'<span style="color:#92400e;">✂ Recorte solar: <b>{p["curtailed"]:,} kWh/mes</b></span><br>'
                    if p["curtailed"] > 0 else
                    f'<span style="color:#166534;font-size:0.75rem;">✓ Sin recorte solar</span><br>'
                )
                bill_line = (
                    f'💳 Factura est.: <b>₡{p["new_bill"]:,}/mes</b><br>'
                    if p["new_bill"] is not None else ""
                )
                savings_line = (
                    f'<span style="color:#166534;">💰 Ahorro/mes: <b>₡{p["savings"]:,}</b></span><br>'
                    if p["savings"] is not None else ""
                )
                desc = s.get("description", "")
                ok_tag = "✅" if is_valid else "⚠️"
                with col:
                    # Selector button aligned above the card
                    if is_valid:
                        btn_label = f"{'●' if is_sel else '○'} Escenario {s['scenario']} — {s['total_panels']} paneles ({s['system_kw']} kW)"
                        if st.button(btn_label, key=f"w6_sel_{s['scenario']}", use_container_width=True):
                            st.session_state["w6_selected_scenario"] = s["scenario"]
                            st.session_state["w6_use_manual"] = False
                            st.rerun()
                    elif not is_valid:
                        st.markdown(
                            f'<div style="font-size:0.8rem;color:#9ca3af;padding:0.3rem 0;">⚠️ Escenario {s["scenario"]} — fuera de límites</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        f'<div style="border:2px solid {border};border-radius:8px;'
                        f'padding:0.65rem 0.8rem;background:{bg};font-size:0.82rem;line-height:1.9;">'
                        f'<div style="font-weight:700;font-size:0.88rem;color:#1E2D54;margin-bottom:0.2rem;">'
                        f'Escenario {s["scenario"]} · {s["system_kw"]} kW</div>'
                        f'<div style="font-size:0.72rem;color:#6b7280;margin-bottom:0.4rem;">{ok_tag} {desc}</div>'
                        f'🔆 Generación: <b>{p["gen"]:,} kWh/mes</b><br>'
                        f'📊 Cobertura: <b>{p["coverage"]}%</b><br>'
                        f'🌙 Red (noches+nublados): <b>{p["grid_kwh"]:,} kWh/mes</b><br>'
                        f'{curtailed_line}'
                        f'{bill_line}'
                        f'{savings_line}'
                        f'<span style="color:#1d4ed8;">⚡ Autoconsumo: <b>{p["self_consumption_pct"]}%</b></span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            st.markdown("&nbsp;", unsafe_allow_html=True)  # spacing after cards
            # Warn if all scenarios exceed the daytime saturation point
            all_saturated = all(
                _scenario_projection(s["system_kw"], avg_irradiance, avg_kwh, avg_bill_crc, tariff_info, daytime_fraction)["curtailed"] > 0
                for s in scenarios
            )
            if all_saturated and len(scenarios) > 1:
                optimal_kw = round(daytime_kwh / avg_irradiance, 2) if avg_irradiance > 0 else "—"
                st.warning(
                    f"⚠️ Los tres escenarios generan más que el consumo diurno estimado "
                    f"({int(daytime_kwh):,} kWh/mes), por lo que la factura estimada es igual en todos. "
                    f"Tamaño óptimo sin recorte para este perfil de cargas: **≈ {optimal_kw} kW**. "
                    f"Recalcula MPPT para ver escenarios ajustados."
                )
            note_parts = []
            if ai_note:
                note_parts.append(f"🤖 <b>IA — Perfil de consumo:</b> {ai_note}")
            note_parts.append(
                "ℹ️ <b>Zero-export:</b> el excedente solar no se inyecta a la red — se descarta. "
                "La cobertura está limitada por el consumo diurno estimado. "
                "<b>Autoconsumo</b> = fracción de la generación que efectivamente desplaza consumo de la red."
            )
            st.markdown(
                " &nbsp;·&nbsp; ".join(
                    f'<span style="font-size:0.73rem;color:#6b7280;">{p}</span>'
                    for p in note_parts
                ),
                unsafe_allow_html=True,
            )
    else:
        st.info("Haz clic en 'Calcular configuración MPPT' para ver los escenarios.")

    # ── Manual design ─────────────────────────────────────────────────────────
    st.divider()
    st.markdown("#### ⚙️ Opción 2 — Configuración manual")
    st.caption("Ajusta los parámetros libremente y verifica los límites del inversor en tiempo real.")

    b_scenario = next((s for s in (scenarios or []) if s["scenario"] == "B"), None)
    default_series   = b_scenario["panels_per_string"] if b_scenario else 6
    default_parallel = b_scenario["strings"]           if b_scenario else 2

    mc1, mc2 = st.columns(2)
    m_series   = mc1.number_input("Paneles en serie (por string)", min_value=1, max_value=50,
                                   value=default_series, step=1, key="w6_m_series")
    m_parallel = mc2.number_input("Strings en paralelo (total)",   min_value=1, max_value=50,
                                   value=default_parallel, step=1, key="w6_m_parallel")

    m = check_design(selected_panel, selected_inverter, m_series, m_parallel)

    # Summary chips row
    area_m2 = m.get("area_m2") or round(m["total_panels"] * area_panel, 1)
    st.markdown(
        f'<div style="display:flex;gap:0.6rem;flex-wrap:wrap;margin:0.4rem 0 0.7rem;">'
        f'<span style="background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;padding:2px 10px;font-size:0.82rem;">'
        f'🔢 <b>{m["total_panels"]}</b> paneles</span>'
        f'<span style="background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;padding:2px 10px;font-size:0.82rem;">'
        f'⚡ <b>{m["system_kw"]} kW</b></span>'
        f'<span style="background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;padding:2px 10px;font-size:0.82rem;">'
        f'📐 <b>{area_m2} m²</b></span>'
        f'<span style="background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;padding:2px 10px;font-size:0.82rem;">'
        f'🔀 <b>{m["strings_per_mppt"]}</b> string/MPPT</span>'
        f'<span style="background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;padding:2px 10px;font-size:0.82rem;">'
        f'Voc <b>{m["voc_total"]} V</b></span>'
        f'<span style="background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;padding:2px 10px;font-size:0.82rem;">'
        f'Vmp <b>{m["vmp_total"]} V</b></span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Two-column layout: validation bars left, projection card right
    vmax      = float(selected_inverter.get("vmax") or 0)
    vmin_mppt = float(selected_inverter.get("vmin_mppt") or 0)
    vmax_mppt = float(selected_inverter.get("vmax_mppt") or 0)
    imax_mppt = float(selected_inverter.get("imax_mppt") or 0)

    left_col, right_col = st.columns([1, 1])

    with left_col:
        _mppt_param_row("Voc total",          f"{m['voc_total']} V",
                        m["voc_total"] <= vmax,       f"≤ {vmax:.0f} V")
        _mppt_param_row("Vmp total",          f"{m['vmp_total']} V",
                        vmin_mppt <= m["vmp_total"] <= vmax_mppt, f"{vmin_mppt:.0f}–{vmax_mppt:.0f} V")
        _mppt_param_row("Corriente por MPPT", f"{m['imp_per_mppt']} A",
                        m["imp_per_mppt"] <= imax_mppt, f"≤ {imax_mppt:.0f} A")

    with right_col:
        # Selector button above the card — mirrors auto scenario buttons
        can_select = m["within_limits"]
        if can_select:
            btn_label = f"{'●' if using_manual else '○'} Usar configuración manual — {m['total_panels']} paneles ({m['system_kw']} kW)"
            if st.button(btn_label, key="w6_manual_on", use_container_width=True):
                st.session_state["w6_use_manual"] = True
                st.rerun()
        else:
            st.markdown(
                '<div style="font-size:0.8rem;color:#9ca3af;padding:0.3rem 0;">'
                '⚠️ Configuración manual — corrige los errores en rojo para poder seleccionarla</div>',
                unsafe_allow_html=True,
            )

        if avg_kwh > 0:
            mp = _scenario_projection(
                m["system_kw"], avg_irradiance, avg_kwh, avg_bill_crc,
                tariff_info, daytime_fraction,
            )
            m_curtailed_line = (
                f'<span style="color:#92400e;">✂ Recorte solar: <b>{mp["curtailed"]:,} kWh/mes</b></span><br>'
                if mp["curtailed"] > 0 else
                f'<span style="color:#166534;font-size:0.75rem;">✓ Sin recorte solar</span><br>'
            )
            m_bill_line    = f'💳 Factura est.: <b>₡{mp["new_bill"]:,}/mes</b><br>' if mp["new_bill"] is not None else ""
            m_savings_line = (
                f'<span style="color:#166534;">💰 Ahorro/mes: <b>₡{mp["savings"]:,}</b></span><br>'
                if mp["savings"] is not None else ""
            )
            oversized_note = (
                f'<div style="margin-top:0.4rem;font-size:0.72rem;color:#92400e;">'
                f'⚠️ Solo el {mp["self_consumption_pct"]}% de la generación se usa — sistema sobredimensionado.</div>'
                if mp["self_consumption_pct"] < 50 else ""
            )
            m_border = "#6366f1" if using_manual else "#d1d5db"
            m_bg     = "#f5f3ff" if using_manual else "#f9fafb"
            st.markdown(
                f'<div style="border:2px solid {m_border};border-radius:8px;'
                f'padding:0.65rem 0.8rem;background:{m_bg};font-size:0.82rem;line-height:1.9;">'
                f'<div style="font-weight:700;font-size:0.88rem;color:#1E2D54;margin-bottom:0.3rem;">'
                f'Proyección · {m["system_kw"]} kW</div>'
                f'🔆 Generación: <b>{mp["gen"]:,} kWh/mes</b><br>'
                f'📊 Cobertura: <b>{mp["coverage"]}%</b><br>'
                f'🌙 Red (noches+nublados): <b>{mp["grid_kwh"]:,} kWh/mes</b><br>'
                f'{m_curtailed_line}'
                f'{m_bill_line}'
                f'{m_savings_line}'
                f'<span style="color:#1d4ed8;">⚡ Autoconsumo: <b>{mp["self_consumption_pct"]}%</b></span>'
                f'{oversized_note}'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── Monitoring + navigation ───────────────────────────────────────────────
    st.divider()
    mon_label = st.selectbox("Sistema de monitoreo (opcional)", list(monitoring_options.keys()), key="w6_mon")
    selected_monitoring = monitoring_options[mon_label]

    st.divider()
    col_back, _, col_next = st.columns([1, 3, 1])
    with col_back:
        if st.button("← Atrás", key="w6_back"):
            st.session_state["wizard_step"] = 5
            _autosave()
            st.rerun()

    with col_next:
        can_continue = using_manual or (scenarios is not None and any(s["within_limits"] for s in scenarios))
        if st.button("Siguiente →", key="w6_next", type="primary", disabled=not can_continue):
            if using_manual:
                chosen_scenario = check_design(selected_panel, selected_inverter, m_series, m_parallel)
                chosen_scenario["scenario"] = "M"
                active_label = "M"
            else:
                chosen_scenario = next(
                    (s for s in scenarios if s["scenario"] == selected_scenario_label),
                    scenarios[0],
                )
                active_label = selected_scenario_label

            result = {
                "panel_id":        selected_panel["id"],
                "panel":           selected_panel,
                "inverter_id":     selected_inverter["id"],
                "inverter":        selected_inverter,
                "mppt_scenario":   active_label,
                "chosen_scenario": chosen_scenario,
                "scenarios":       scenarios or [],
                "monitoring_id":   selected_monitoring["id"] if selected_monitoring else None,
                "monitoring":      selected_monitoring,
            }
            st.session_state["wizard_equipment"] = result
            return result

    if not can_continue:
        st.caption("Calcula los escenarios MPPT o configura un diseño manual válido para continuar.")

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
            _autosave()
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
            _autosave()
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
            _actual_vnum = 1
            try:
                from database.proposals_db import format_quote_number, get_proposal, get_version as _gv
                proposal_id = st.session_state.get("wizard_proposal_id")
                version_id_now = st.session_state.get("wizard_version_id")
                if proposal_id and version_id_now:
                    _prop = get_proposal(proposal_id)
                    _ver = _gv(version_id_now)
                    if _prop and _prop.get("quote_number"):
                        _actual_vnum = (_ver.get("version_number") or 1) if _ver else 1
                        _quote_num_str = format_quote_number(
                            _prop["quote_number"], _prop.get("created_at", ""), _actual_vnum
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
                        path = upload_pdf(pdf_bytes, proposal_id, _actual_vnum, client.get("name", "cliente"))
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
