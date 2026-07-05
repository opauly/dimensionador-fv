"""Admin panel — Tariff updater and future admin tools."""
from __future__ import annotations
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Administración — Pauly&Co Solar", layout="wide")

TARIFF_META = {
    "T-RE": {"name": "Tarifa Residencial",      "sector": "residential", "iva_threshold_kwh": 280},
    "T-CO": {"name": "Comercios y Servicios",   "sector": "commercial",  "iva_threshold_kwh": 0},
}


# ── formatting helpers ────────────────────────────────────────────────────────

def _fmt_crc(v: float) -> str:
    return f"₡{v:,.2f}"

def _fmt_rate(v: float) -> str:
    return f"₡{v:.4f}/kWh"

def _fmt_demand(rate: float, threshold: int) -> str:
    if not rate:
        return "—"
    if threshold:
        return f"₡{rate:,.2f}/kW  (>  {threshold} kW)"
    return f"₡{rate:,.2f}/kW"

def _tier_label(t: dict) -> str:
    hi = t.get("to_kwh")
    return f"{t['from_kwh']}–{hi} kWh" if hi else f"{t['from_kwh']} kWh en adelante"


# ── diff helpers ──────────────────────────────────────────────────────────────

def _tiers_changed(cur: list[dict], new: list[dict]) -> bool:
    if len(cur) != len(new):
        return True
    return any(
        abs(ct.get("rate_crc", 0) - nt["rate_crc"]) > 0.001
        or ct.get("from_kwh") != nt["from_kwh"]
        or ct.get("to_kwh") != nt["to_kwh"]
        for ct, nt in zip(cur, new)
    )

def _build_changes(parsed: dict, current_db: dict) -> list[dict]:
    """Build a flat list of change records (one per distributor × tariff code)."""
    changes = []
    for abbrev, tariffs in parsed.items():
        for code, new_data in tariffs.items():
            cur = current_db.get(abbrev, {}).get(code)
            if cur is None:
                # New tariff type — mark as change so it gets created
                changes.append({
                    "abbrev": abbrev,
                    "code": code,
                    "tariff_type_id": None,
                    "has_change": True,
                    "is_new": True,
                    "new": new_data,
                    "cur": {},
                })
                continue

            new_access = new_data["access_charge_crc"]
            cur_access = cur.get("access_charge_crc") or 0.0
            new_demand = new_data.get("demand_rate_crc", 0.0)
            cur_demand = cur.get("demand_rate_crc") or 0.0
            new_thresh = new_data.get("demand_threshold_kw", 0)
            cur_thresh = cur.get("demand_threshold_kw") or 0

            has_change = (
                abs(new_access - cur_access) > 0.01
                or abs(new_demand - cur_demand) > 0.01
                or new_thresh != cur_thresh
                or _tiers_changed(cur.get("tiers", []), new_data.get("tiers", []))
            )
            changes.append({
                "abbrev": abbrev,
                "code": code,
                "tariff_type_id": cur["id"],
                "has_change": has_change,
                "is_new": False,
                "new": new_data,
                "cur": cur,
            })
    return changes


# ── tariff updater tab ────────────────────────────────────────────────────────

def _tariff_updater() -> None:
    st.markdown("### Actualizar tarifas ARESEP")
    st.markdown(
        "Sube el archivo **Cuadro E-8** de ARESEP (`.xlsx`). "
        "El sistema leerá únicamente las hojas **Vigentes** de cada distribuidora "
        "y extraerá las tarifas **T-RE** (residencial) y **T-CO** (comercial)."
    )

    uploaded = st.file_uploader(
        "Archivo ARESEP Cuadro E-8",
        type=["xlsx"],
        key="admin_aresep_file",
    )
    if uploaded is None:
        st.caption("Descarga el archivo actualizado en aresep.go.cr → Estadísticas → Cuadro E-8.")
        return

    with st.spinner("Leyendo archivo y extrayendo tarifas vigentes…"):
        try:
            from aresep.tariff_parser import parse_vigentes
            parsed = parse_vigentes(uploaded)
        except Exception as e:
            st.error(f"Error al leer el archivo: {e}")
            return

    if not parsed:
        st.error("No se encontraron tarifas en el archivo. Verifica que sea el Cuadro E-8 correcto.")
        return

    # Load current DB values for every distributor × code combination
    with st.spinner("Cargando valores actuales de la base de datos…"):
        from database.tariffs_db import get_tariff_info
        current_db: dict[str, dict] = {}
        for abbrev, tariffs in parsed.items():
            current_db[abbrev] = {}
            for code in tariffs:
                try:
                    info = get_tariff_info(abbrev, code)
                    if info:
                        current_db[abbrev][code] = info
                except Exception:
                    pass

    changes = _build_changes(parsed, current_db)
    to_update = [c for c in changes if c["has_change"]]

    if not to_update:
        st.success("Los valores del archivo coinciden con la base de datos. No hay cambios que aplicar.")
        return

    st.markdown("#### Comparación: valores actuales vs. archivo ARESEP")

    # Group by distributor for display
    abbrevs_with_changes = sorted({c["abbrev"] for c in to_update})

    for abbrev in sorted(parsed.keys()):
        dist_changes = [c for c in changes if c["abbrev"] == abbrev]
        any_dist_change = any(c["has_change"] for c in dist_changes)
        icon = "🟢" if any_dist_change else "⚪"

        with st.expander(f"{icon} **{abbrev}**", expanded=any_dist_change):
            if not any_dist_change:
                st.caption("Sin cambios.")
                continue

            for ch in dist_changes:
                code = ch["code"]
                label = f"**T-RE** — Residencial" if code == "T-RE" else f"**T-CO** — Comercial"
                st.markdown(f"##### {label}")
                if not ch["has_change"]:
                    st.caption("Sin cambios.")
                    continue
                if ch["is_new"]:
                    st.info(f"Nuevo: {code} no existe en la base de datos para {abbrev}. Se creará.")

                col_cur, col_new = st.columns(2)
                new_data = ch["new"]
                cur_data = ch["cur"]

                with col_cur:
                    st.markdown("**Actual en DB**" if not ch["is_new"] else "**Actual en DB (no existe)**")
                    st.markdown(f"Cargo fijo: {_fmt_crc(cur_data.get('access_charge_crc') or 0)}")
                    if code == "T-CO":
                        st.markdown(f"Cargo demanda: {_fmt_demand(cur_data.get('demand_rate_crc') or 0, cur_data.get('demand_threshold_kw') or 0)}")
                    for t in cur_data.get("tiers", []):
                        st.markdown(f"- {_tier_label(t)}: {_fmt_rate(t['rate_crc'])}")

                with col_new:
                    st.markdown("**Nuevo (ARESEP)**")
                    st.markdown(f"Cargo fijo: {_fmt_crc(new_data['access_charge_crc'])}")
                    if code == "T-CO":
                        st.markdown(f"Cargo demanda: {_fmt_demand(new_data.get('demand_rate_crc', 0), new_data.get('demand_threshold_kw', 0))}")
                    for t in new_data.get("tiers", []):
                        st.markdown(f"- {_tier_label(t)}: {_fmt_rate(t['rate_crc'])}")

                st.divider()

    # Apply button
    n = len(to_update)
    st.warning(
        f"Se actualizarán **{n} tarifa(s)** en {len(abbrevs_with_changes)} distribuidora(s). "
        "Esta acción reemplaza los bloques tarifarios en la base de datos."
    )
    if st.button("✅ Aplicar actualización", key="admin_apply_tariffs", type="primary"):
        from database.tariffs_db import upsert_tariff_type_row, replace_tariff_tiers
        errors = []
        updated = 0
        progress = st.progress(0)

        for i, ch in enumerate(to_update):
            try:
                meta = TARIFF_META[ch["code"]]
                new_data = ch["new"]
                tt_id = upsert_tariff_type_row(
                    distributor_abbrev=ch["abbrev"],
                    code=ch["code"],
                    name=meta["name"],
                    sector=meta["sector"],
                    access_charge_crc=new_data["access_charge_crc"],
                    demand_rate_crc=new_data.get("demand_rate_crc", 0.0),
                    demand_threshold_kw=new_data.get("demand_threshold_kw", 0),
                    iva_threshold_kwh=meta["iva_threshold_kwh"],
                )
                replace_tariff_tiers(tt_id, new_data.get("tiers", []))
                updated += 1
            except Exception as e:
                errors.append(f"{ch['abbrev']} {ch['code']}: {e}")
            progress.progress((i + 1) / len(to_update))

        progress.empty()
        if errors:
            st.error("Errores:\n" + "\n".join(errors))
        if updated:
            st.success(f"✅ {updated} tarifa(s) actualizadas correctamente.")
            st.balloons()


# ── current tariff viewer ─────────────────────────────────────────────────────

def _current_tariffs() -> None:
    st.markdown("### Tarifas vigentes en base de datos")

    try:
        from database.tariffs_db import list_distributors, list_tariff_types, get_tariff_tiers
        distributors = list_distributors()
    except Exception as e:
        st.error(f"No se pudo cargar la base de datos: {e}")
        return

    if not distributors:
        st.info("No hay distribuidoras registradas.")
        return

    for dist in distributors:
        tariff_types = list_tariff_types(dist["id"])
        if not tariff_types:
            continue

        with st.expander(f"**{dist['abbreviation']}** — {dist['name']}", expanded=False):
            for tt in tariff_types:
                code = tt["code"]
                label = "Residencial (T-RE)" if code == "T-RE" else "Comercial (T-CO)" if code == "T-CO" else code
                st.markdown(f"##### {label}")

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Cargo fijo mensual", _fmt_crc(tt["access_charge_crc"]))
                col2.metric("Bomberos", f"{tt['bomberos_pct']*100:.2f}%")
                last_upd = (tt.get("last_updated") or "")[:10] or "—"
                if tt.get("demand_rate_crc"):
                    col3.metric("Demanda", f"₡{tt['demand_rate_crc']:,.0f}/kW")
                    col4.metric("Última actualización", last_upd)
                else:
                    col3.metric("Umbral IVA", f"{tt['iva_threshold_kwh']} kWh")
                    col4.metric("Última actualización", last_upd)

                tiers = get_tariff_tiers(tt["id"])
                if tiers:
                    import pandas as pd
                    df = pd.DataFrame([
                        {"Bloque": _tier_label(t), "Tarifa (CRC/kWh)": f"{t['rate_crc']:.4f}"}
                        for t in tiers
                    ])
                    st.dataframe(df, use_container_width=True, hide_index=True)
                st.divider()


# ── equipment catalog ─────────────────────────────────────────────────────────

def _panel_form(existing: dict | None = None, prefill: dict | None = None) -> None:
    """Render add/edit form for a solar panel. existing=edit mode, prefill=from datasheet."""
    src = prefill or existing or {}
    is_edit = existing is not None

    with st.form(key="panel_form"):
        st.markdown("#### " + ("Editar panel" if is_edit else "Nuevo panel"))
        col1, col2 = st.columns(2)
        with col1:
            brand = st.text_input("Marca *", value=src.get("brand") or "")
            model = st.text_input("Modelo *", value=src.get("model") or "")
            wp    = st.number_input("Potencia (Wp) *", value=float(src.get("wp") or 0), min_value=0.0, step=5.0)
            voc   = st.number_input("Voc (V)", value=float(src.get("voc") or 0), min_value=0.0, format="%.2f")
            vmp   = st.number_input("Vmp (V)", value=float(src.get("vmp") or 0), min_value=0.0, format="%.2f")
        with col2:
            isc   = st.number_input("Isc (A)", value=float(src.get("isc") or 0), min_value=0.0, format="%.2f")
            imp   = st.number_input("Imp (A)", value=float(src.get("imp") or 0), min_value=0.0, format="%.2f")
            tc    = st.number_input("Coef. temp. Pmax (%/°C)", value=float(src.get("temp_coeff_pmax") or -0.35), format="%.3f")
            width = st.number_input("Ancho (m)", value=float(src.get("width_m") or 0), min_value=0.0, format="%.4f")
            height= st.number_input("Alto (m)", value=float(src.get("height_m") or 0), min_value=0.0, format="%.4f")

        col3, col4, col5 = st.columns(3)
        with col3:
            warr_prod = st.number_input("Garantía producto (años)", value=int(src.get("warranty_product_yr") or 12), min_value=0, step=1)
        with col4:
            warr_pow  = st.number_input("Garantía potencia (años)", value=int(src.get("warranty_power_yr") or 25), min_value=0, step=1)
        with col5:
            cost_usd  = st.number_input("Costo (USD)", value=float(src.get("cost_usd") or 0), min_value=0.0, format="%.2f")

        notes = st.text_area("Notas", value=src.get("notes") or "", height=60)

        col_save, col_cancel = st.columns([1, 4])
        submitted = col_save.form_submit_button("💾 Guardar", type="primary")
        cancelled = col_cancel.form_submit_button("Cancelar")

    if cancelled:
        st.session_state.pop("admin_edit_panel", None)
        st.session_state.pop("admin_prefill_panel", None)
        st.rerun()

    if submitted:
        if not brand.strip() or not model.strip() or wp <= 0:
            st.error("Marca, modelo y potencia son obligatorios.")
            return
        from database.equipment_db import upsert_panel
        payload = {
            "brand": brand.strip(), "model": model.strip(), "wp": int(wp),
            "voc": voc or None, "vmp": vmp or None,
            "isc": isc or None, "imp": imp or None,
            "temp_coeff_pmax": tc or None,
            "width_m": width or None, "height_m": height or None,
            "warranty_product_yr": warr_prod, "warranty_power_yr": warr_pow,
            "cost_usd": cost_usd or None, "notes": notes.strip() or None,
        }
        if is_edit:
            payload["id"] = existing["id"]
        try:
            upsert_panel(payload)
            st.success("Panel guardado." if not is_edit else "Panel actualizado.")
            st.session_state.pop("admin_edit_panel", None)
            st.session_state.pop("admin_prefill_panel", None)
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")


def _panels_section() -> None:
    from database.equipment_db import list_panels, delete_panel

    # ── Datasheet upload → AI fill ────────────────────────────────────────────
    with st.expander("📄 Extraer especificaciones de datasheet (PDF)", expanded=False):
        st.caption("Sube el datasheet del fabricante. La IA extrae las especificaciones técnicas.")
        pdf_file = st.file_uploader("Datasheet PDF", type=["pdf"], key="admin_panel_ds")
        if pdf_file:
            variants = st.session_state.get("admin_panel_variants")
            if st.button("Extraer especificaciones", key="admin_panel_extract"):
                with st.spinner("Analizando datasheet…"):
                    try:
                        from calculations.datasheet_parser import parse_panel_datasheet
                        variants = parse_panel_datasheet(pdf_file.read())
                        st.session_state["admin_panel_variants"] = variants
                    except Exception as e:
                        st.error(f"Error al procesar el datasheet: {e}")
                        variants = None

            if variants:
                if len(variants) > 1:
                    opts = [f"{v.get('brand','')} {v.get('model','')} — {v.get('wp','')}W" for v in variants]
                    idx = st.selectbox("Selecciona el modelo a agregar", range(len(opts)), format_func=lambda i: opts[i], key="admin_panel_var_idx")
                    selected = variants[idx]
                else:
                    selected = variants[0]
                    st.success(f"Extraído: {selected.get('brand')} {selected.get('model')} — {selected.get('wp')}W")

                if st.button("Usar estos datos en el formulario", key="admin_panel_use"):
                    st.session_state["admin_prefill_panel"] = selected
                    st.session_state.pop("admin_edit_panel", None)
                    st.session_state.pop("admin_panel_variants", None)
                    st.rerun()

    st.divider()

    # ── Add / Edit form ───────────────────────────────────────────────────────
    edit_panel   = st.session_state.get("admin_edit_panel")
    prefill_panel= st.session_state.get("admin_prefill_panel")

    if edit_panel or prefill_panel:
        _panel_form(existing=edit_panel, prefill=prefill_panel if not edit_panel else None)
        st.divider()

    if not edit_panel and not prefill_panel:
        with st.expander("➕ Agregar panel manualmente", expanded=False):
            _panel_form()

    # ── Existing panels ───────────────────────────────────────────────────────
    st.markdown("#### Paneles en catálogo")
    try:
        panels = list_panels()
    except Exception as e:
        st.error(f"Error al cargar paneles: {e}")
        return

    if not panels:
        st.info("No hay paneles en el catálogo.")
        return

    for p in panels:
        area = round((p.get("width_m") or 0) * (p.get("height_m") or 0), 2)
        label = f"**{p['brand']} {p['model']}** — {p['wp']} Wp"
        with st.expander(label, expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"Voc **{p.get('voc','—')}V** · Vmp **{p.get('vmp','—')}V**")
            c1.markdown(f"Isc **{p.get('isc','—')}A** · Imp **{p.get('imp','—')}A**")
            c2.markdown(f"Área **{area} m²** ({p.get('width_m','—')} × {p.get('height_m','—')} m)")
            c2.markdown(f"TC Pmax **{p.get('temp_coeff_pmax','—')}%/°C**")
            c3.markdown(f"Garantía **{p.get('warranty_product_yr','—')}a** prod / **{p.get('warranty_power_yr','—')}a** potencia")
            if p.get("cost_usd"):
                c3.markdown(f"Costo **${p['cost_usd']:.2f}**")
            if p.get("notes"):
                st.caption(p["notes"])

            btn1, btn2, _ = st.columns([1, 1, 5])
            if btn1.button("✏️ Editar", key=f"ep_{p['id']}"):
                st.session_state["admin_edit_panel"] = p
                st.session_state.pop("admin_prefill_panel", None)
                st.rerun()
            confirm_key = f"confirm_del_panel_{p['id']}"
            if st.session_state.get(confirm_key):
                st.warning(f"¿Eliminar **{p['brand']} {p['model']}**? Esta acción no se puede deshacer.")
                c_yes, c_no, _ = st.columns([1, 1, 5])
                if c_yes.button("Sí, eliminar", key=f"yes_del_panel_{p['id']}"):
                    delete_panel(p["id"])
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
                if c_no.button("Cancelar", key=f"no_del_panel_{p['id']}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            else:
                if btn2.button("🗑️", key=f"dp_{p['id']}", help="Eliminar panel"):
                    st.session_state[confirm_key] = True
                    st.rerun()


def _inverter_form(existing: dict | None = None, prefill: dict | None = None) -> None:
    src = prefill or existing or {}
    is_edit = existing is not None

    with st.form(key="inverter_form"):
        st.markdown("#### " + ("Editar inversor" if is_edit else "Nuevo inversor"))
        col1, col2 = st.columns(2)
        with col1:
            brand  = st.text_input("Marca *", value=src.get("brand") or "")
            model  = st.text_input("Modelo *", value=src.get("model") or "")
            kw     = st.number_input("Potencia (kW) *", value=float(src.get("kw") or 0), min_value=0.0, step=0.1, format="%.1f")
            inv_type = st.selectbox("Tipo", ["string_inverter", "microinverter", "hybrid"],
                                    index=["string_inverter", "microinverter", "hybrid"].index(src.get("type") or "string_inverter"))
            phase  = st.selectbox("Fase", ["single", "three"],
                                  index=["single", "three"].index(src.get("phase") or "single"))
        with col2:
            vmax      = st.number_input("V máx entrada DC (V)", value=float(src.get("vmax") or 0), min_value=0.0, step=10.0)
            vmin_mppt = st.number_input("Vmin MPPT (V)", value=float(src.get("vmin_mppt") or 0), min_value=0.0)
            vmax_mppt = st.number_input("Vmax MPPT (V)", value=float(src.get("vmax_mppt") or 0), min_value=0.0)
            imax_mppt = st.number_input("Imax por MPPT (A)", value=float(src.get("imax_mppt") or 0), min_value=0.0, format="%.1f")
            mppt_ch   = st.number_input("Canales MPPT", value=int(src.get("mppt_channels") or 1), min_value=1, step=1)

        col3, col4, col5 = st.columns(3)
        with col3:
            output_v  = st.number_input("Tensión salida AC (V)", value=float(src.get("output_v") or 240), min_value=0.0)
        with col4:
            warr_yr   = st.number_input("Garantía (años)", value=int(src.get("warranty_yr") or 5), min_value=0, step=1)
        with col5:
            cost_usd  = st.number_input("Costo (USD)", value=float(src.get("cost_usd") or 0), min_value=0.0, format="%.2f")

        notes = st.text_area("Notas", value=src.get("notes") or "", height=60)

        col_save, col_cancel = st.columns([1, 4])
        submitted = col_save.form_submit_button("💾 Guardar", type="primary")
        cancelled = col_cancel.form_submit_button("Cancelar")

    if cancelled:
        st.session_state.pop("admin_edit_inverter", None)
        st.session_state.pop("admin_prefill_inverter", None)
        st.rerun()

    if submitted:
        if not brand.strip() or not model.strip() or kw <= 0:
            st.error("Marca, modelo y potencia son obligatorios.")
            return
        from database.equipment_db import upsert_inverter
        payload = {
            "brand": brand.strip(), "model": model.strip(), "kw": kw,
            "type": inv_type, "phase": phase,
            "vmax": vmax or None, "vmin_mppt": vmin_mppt or None,
            "vmax_mppt": vmax_mppt or None, "imax_mppt": imax_mppt or None,
            "mppt_channels": mppt_ch, "output_v": output_v or None,
            "warranty_yr": warr_yr, "cost_usd": cost_usd or None,
            "notes": notes.strip() or None,
        }
        if is_edit:
            payload["id"] = existing["id"]
        try:
            upsert_inverter(payload)
            st.success("Inversor guardado." if not is_edit else "Inversor actualizado.")
            st.session_state.pop("admin_edit_inverter", None)
            st.session_state.pop("admin_prefill_inverter", None)
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")


def _inverters_section() -> None:
    from database.equipment_db import list_inverters, delete_inverter

    # ── Datasheet upload → AI fill ────────────────────────────────────────────
    with st.expander("📄 Extraer especificaciones de datasheet (PDF)", expanded=False):
        st.caption("Sube el datasheet del fabricante. La IA extrae las especificaciones técnicas.")
        pdf_file = st.file_uploader("Datasheet PDF", type=["pdf"], key="admin_inv_ds")
        if pdf_file:
            variants = st.session_state.get("admin_inv_variants")
            if st.button("Extraer especificaciones", key="admin_inv_extract"):
                with st.spinner("Analizando datasheet…"):
                    try:
                        from calculations.datasheet_parser import parse_inverter_datasheet
                        variants = parse_inverter_datasheet(pdf_file.read())
                        st.session_state["admin_inv_variants"] = variants
                    except Exception as e:
                        st.error(f"Error al procesar el datasheet: {e}")
                        variants = None

            if variants:
                if len(variants) > 1:
                    opts = [f"{v.get('brand','')} {v.get('model','')} — {v.get('kw','')} kW" for v in variants]
                    idx = st.selectbox("Selecciona el modelo a agregar", range(len(opts)), format_func=lambda i: opts[i], key="admin_inv_var_idx")
                    selected = variants[idx]
                else:
                    selected = variants[0]
                    st.success(f"Extraído: {selected.get('brand')} {selected.get('model')} — {selected.get('kw')} kW")

                if st.button("Usar estos datos en el formulario", key="admin_inv_use"):
                    st.session_state["admin_prefill_inverter"] = selected
                    st.session_state.pop("admin_edit_inverter", None)
                    st.session_state.pop("admin_inv_variants", None)
                    st.rerun()

    st.divider()

    # ── Add / Edit form ───────────────────────────────────────────────────────
    edit_inv    = st.session_state.get("admin_edit_inverter")
    prefill_inv = st.session_state.get("admin_prefill_inverter")

    if edit_inv or prefill_inv:
        _inverter_form(existing=edit_inv, prefill=prefill_inv if not edit_inv else None)
        st.divider()

    if not edit_inv and not prefill_inv:
        with st.expander("➕ Agregar inversor manualmente", expanded=False):
            _inverter_form()

    # ── Existing inverters ────────────────────────────────────────────────────
    st.markdown("#### Inversores en catálogo")
    try:
        inverters = list_inverters()
    except Exception as e:
        st.error(f"Error al cargar inversores: {e}")
        return

    if not inverters:
        st.info("No hay inversores en el catálogo.")
        return

    for inv in inverters:
        label = f"**{inv['brand']} {inv['model']}** — {inv['kw']} kW"
        with st.expander(label, expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"Vmax **{inv.get('vmax','—')}V** · MPPT **{inv.get('vmin_mppt','—')}–{inv.get('vmax_mppt','—')}V**")
            c1.markdown(f"Imax MPPT **{inv.get('imax_mppt','—')}A** · Canales **{inv.get('mppt_channels','—')}**")
            c2.markdown(f"Tipo **{inv.get('type','—')}** · Fase **{inv.get('phase','—')}**")
            c2.markdown(f"Salida **{inv.get('output_v','—')}V AC**")
            c3.markdown(f"Garantía **{inv.get('warranty_yr','—')} años**")
            if inv.get("cost_usd"):
                c3.markdown(f"Costo **${inv['cost_usd']:.2f}**")
            if inv.get("notes"):
                st.caption(inv["notes"])

            btn1, btn2, _ = st.columns([1, 1, 5])
            if btn1.button("✏️ Editar", key=f"ei_{inv['id']}"):
                st.session_state["admin_edit_inverter"] = inv
                st.session_state.pop("admin_prefill_inverter", None)
                st.rerun()
            confirm_key = f"confirm_del_inv_{inv['id']}"
            if st.session_state.get(confirm_key):
                st.warning(f"¿Eliminar **{inv['brand']} {inv['model']}**? Esta acción no se puede deshacer.")
                c_yes, c_no, _ = st.columns([1, 1, 5])
                if c_yes.button("Sí, eliminar", key=f"yes_del_inv_{inv['id']}"):
                    delete_inverter(inv["id"])
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
                if c_no.button("Cancelar", key=f"no_del_inv_{inv['id']}"):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()
            else:
                if btn2.button("🗑️", key=f"di_{inv['id']}", help="Eliminar inversor"):
                    st.session_state[confirm_key] = True
                    st.rerun()


def _equipment_catalog() -> None:
    tab_panels, tab_inverters = st.tabs(["☀️ Paneles solares", "⚡ Inversores"])
    with tab_panels:
        _panels_section()
    with tab_inverters:
        _inverters_section()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.markdown(
        '<p style="color:#1E2D54;font-size:1.4rem;font-weight:700;margin:0;">Administración</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    tab_equip, tab_tariff_update, tab_tariff_view = st.tabs([
        "🔧 Catálogo de equipos",
        "📤 Actualizar tarifas ARESEP",
        "📋 Tarifas actuales",
    ])

    with tab_equip:
        _equipment_catalog()

    with tab_tariff_update:
        _tariff_updater()

    with tab_tariff_view:
        _current_tariffs()


main()
