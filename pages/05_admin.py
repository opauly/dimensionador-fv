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

def _energy_changed(cur: dict, new_data: dict) -> bool:
    """True if the file's access charge or energy tiers differ from the DB.

    For T-CO these are NOT safe to auto-apply: they were hand-corrected from
    real <100kW CNFL invoices to a flat, no-access-charge structure, which
    genuinely differs from ARESEP's raw published T-CO (see
    aresep/tariff_parser.py's docstring) -- a routine sync must not silently
    revert that.
    """
    new_access = new_data["access_charge_crc"]
    cur_access = cur.get("access_charge_crc") or 0.0
    return (
        abs(new_access - cur_access) > 0.01
        or _tiers_changed(cur.get("tiers", []), new_data.get("tiers", []))
    )


def _demand_changed(cur: dict, new_data: dict) -> bool:
    """True if the file's demand rate/threshold differ from the DB.

    Safe to auto-apply: calculations/tariffs.py and
    calculations/tariff_calculator.py never read these fields, so keeping
    them in sync with ARESEP's real published structure can't affect any
    bill estimate.
    """
    new_demand = new_data.get("demand_rate_crc", 0.0)
    cur_demand = cur.get("demand_rate_crc") or 0.0
    new_thresh = new_data.get("demand_threshold_kw", 0)
    cur_thresh = cur.get("demand_threshold_kw") or 0
    return abs(new_demand - cur_demand) > 0.01 or new_thresh != cur_thresh


def _build_changes(parsed: dict, current_db: dict) -> list[dict]:
    """Build a flat list of change records (one per distributor × tariff code)."""
    changes = []
    for abbrev, tariffs in parsed.items():
        for code, new_data in tariffs.items():
            cur = current_db.get(abbrev, {}).get(code)
            if cur is None:
                # New tariff type — mark as change so it gets created. Nothing
                # exists yet to protect, so the file's raw values are fine.
                changes.append({
                    "abbrev": abbrev,
                    "code": code,
                    "tariff_type_id": None,
                    "has_change": True,
                    "is_new": True,
                    "energy_changed": True,
                    "demand_changed": True,
                    "energy_confirmed": True,
                    "new": new_data,
                    "cur": {},
                })
                continue

            energy_changed = _energy_changed(cur, new_data)
            demand_changed = _demand_changed(cur, new_data)
            # Only T-CO's energy fields carry the hand-corrected-vs-ARESEP-raw
            # conflict, so only T-CO needs the UI's explicit checkbox gate.
            # T-RE (and anything else) syncs its energy fields as before.
            needs_confirmation = code == "T-CO" and energy_changed
            changes.append({
                "abbrev": abbrev,
                "code": code,
                "tariff_type_id": cur["id"],
                "has_change": energy_changed or demand_changed,
                "is_new": False,
                "energy_changed": energy_changed,
                "demand_changed": demand_changed,
                "energy_confirmed": not needs_confirmation,
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

    if not any(c["has_change"] for c in changes):
        st.success("Los valores del archivo coinciden con la base de datos. No hay cambios que aplicar.")
        return

    st.markdown("#### Comparación: valores actuales vs. archivo ARESEP")

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

                if code == "T-CO" and ch["energy_changed"] and not ch["is_new"]:
                    st.warning(
                        "⚠️ El archivo ARESEP trae la estructura binomial oficial de T-CO "
                        "(bloques de energía + cargo por demanda). El valor actual en la "
                        "base de datos fue corregido a mano a partir de facturas reales de "
                        "clientes <100kW monofásicos sin medidor de demanda, donde nunca se "
                        "cobra ese cargo — sobrescribirlo cambiará las estimaciones de "
                        "factura de todos los proyectos que usan esta tarifa."
                    )
                    ch["energy_confirmed"] = st.checkbox(
                        f"Sí, sobrescribir el cargo fijo y los bloques de energía de "
                        f"T-CO para {abbrev} con los valores del archivo",
                        key=f"admin_confirm_energy_{abbrev}_{code}",
                    )
                elif code == "T-CO" and ch["demand_changed"] and not ch["is_new"]:
                    st.caption(
                        "El cargo por demanda es solo informativo (no se usa en ninguna "
                        "estimación de factura) — se actualizará automáticamente."
                    )

                st.divider()

    to_update = [
        c for c in changes
        if c["has_change"] and (c["is_new"] or c["demand_changed"] or c["energy_confirmed"])
    ]

    if not to_update:
        st.info("No hay cambios confirmados para aplicar.")
        return

    # Apply button
    n = len(to_update)
    abbrevs_with_changes = sorted({c["abbrev"] for c in to_update})
    st.warning(
        f"Se actualizarán **{n} tarifa(s)** en {len(abbrevs_with_changes)} distribuidora(s). "
        "Esta acción reemplaza los bloques tarifarios en la base de datos."
    )
    if st.button("Aplicar actualización", key="admin_apply_tariffs", type="primary"):
        from database.tariffs_db import upsert_tariff_type_row, replace_tariff_tiers
        errors = []
        updated = 0
        progress = st.progress(0)

        for i, ch in enumerate(to_update):
            try:
                meta = TARIFF_META[ch["code"]]
                new_data = ch["new"]
                cur_data = ch["cur"]
                use_new_energy = ch["is_new"] or ch["energy_confirmed"]
                access_charge = (
                    new_data["access_charge_crc"] if use_new_energy
                    else (cur_data.get("access_charge_crc") or 0.0)
                )
                tiers = (
                    new_data.get("tiers", []) if use_new_energy
                    else cur_data.get("tiers", [])
                )
                tt_id = upsert_tariff_type_row(
                    distributor_abbrev=ch["abbrev"],
                    code=ch["code"],
                    name=meta["name"],
                    sector=meta["sector"],
                    access_charge_crc=access_charge,
                    demand_rate_crc=new_data.get("demand_rate_crc", 0.0),
                    demand_threshold_kw=new_data.get("demand_threshold_kw", 0),
                    iva_threshold_kwh=meta["iva_threshold_kwh"],
                )
                replace_tariff_tiers(tt_id, tiers)
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
    try:
        from database.tariffs_db import list_distributors, list_tariff_types, get_tariff_tiers
        distributors = list_distributors()
    except Exception as e:
        st.error(f"No se pudo cargar la base de datos: {e}")
        return

    if not distributors:
        st.info("No hay distribuidoras registradas.")
        return

    # Distributor selector pills
    selected_abbrev = st.session_state.get("tariff_view_dist", distributors[0]["abbreviation"])

    cols_per_row = 5
    for i in range(0, len(distributors), cols_per_row):
        batch = distributors[i : i + cols_per_row]
        pill_cols = st.columns(cols_per_row)
        for j, dist in enumerate(batch):
            abbrev = dist["abbreviation"]
            btn_type = "primary" if abbrev == selected_abbrev else "secondary"
            if pill_cols[j].button(abbrev, key=f"tdist_{abbrev}", type=btn_type, use_container_width=True):
                st.session_state["tariff_view_dist"] = abbrev
                st.rerun()

    st.divider()

    # Selected distributor detail
    selected_dist = next((d for d in distributors if d["abbreviation"] == selected_abbrev), None)
    if not selected_dist:
        return

    st.markdown(f"#### {selected_dist['abbreviation']} — {selected_dist['name']}")

    tariff_types = list_tariff_types(selected_dist["id"])
    if not tariff_types:
        st.info("No hay tarifas registradas para esta distribuidora.")
        return

    import pandas as pd
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
            st.caption(
                "El cargo por demanda es la estructura oficial ARESEP, pero es solo "
                "informativo: ninguna estimación de factura lo usa (los clientes "
                "monofásicos <100kW nunca lo pagan)."
            )
        else:
            col3.metric("Umbral IVA", f"{tt['iva_threshold_kwh']} kWh")
            col4.metric("Última actualización", last_upd)

        tiers = get_tariff_tiers(tt["id"])
        if tiers:
            df = pd.DataFrame([
                {"Bloque": _tier_label(t), "Tarifa (CRC/kWh)": f"{t['rate_crc']:.4f}"}
                for t in tiers
            ])
            st.dataframe(df, use_container_width=True, hide_index=True)
        st.divider()


# ── service defaults ─────────────────────────────────────────────────────────

def _service_form(existing: dict | None = None) -> None:
    src = existing or {}
    is_edit = existing is not None

    with st.form(key="service_form"):
        st.markdown("#### " + ("Editar servicio" if is_edit else "Nuevo servicio"))
        col1, col2 = st.columns(2)
        with col1:
            item    = st.text_input("Nombre (ES) *", value=src.get("item") or "")
            item_en = st.text_input("Nombre (EN)", value=src.get("item_en") or "")
            cost    = st.number_input("Precio default (USD)", value=float(src.get("unit_cost_usd") or 0), min_value=0.0, format="%.2f")
        with col2:
            iva_idx  = 1 if float(src.get("iva_pct") or 0) >= 0.1 else 0
            iva      = st.selectbox("IVA", ["0%", "13%"], index=iva_idx)
            enabled  = st.checkbox("Habilitado", value=bool(src.get("enabled", True)))
            sort_ord = st.number_input("Orden", value=int(src.get("sort_order") or 0), min_value=0, step=10)

        specs    = st.text_area("Descripción / Specs (ES)", value=src.get("specs") or "", height=60)
        specs_en = st.text_area("Descripción / Specs (EN)", value=src.get("specs_en") or "", height=60)

        col_save, col_cancel = st.columns([1, 4])
        submitted = col_save.form_submit_button("Guardar", type="primary")
        cancelled = col_cancel.form_submit_button("Cancelar")

    if cancelled:
        st.session_state.pop("admin_edit_service", None)
        st.session_state.pop("admin_svc_mode", None)
        st.rerun()

    if submitted:
        if not str(item).strip():
            st.error("El nombre es obligatorio.")
            return
        from database.equipment_db import upsert_service_default
        payload: dict = {
            "item":          str(item).strip(),
            "item_en":       str(item_en).strip(),
            "unit_cost_usd": float(cost),
            "iva_pct":       0.13 if "13" in str(iva) else 0.0,
            "enabled":       bool(enabled),
            "specs":         str(specs).strip(),
            "specs_en":      str(specs_en).strip(),
            "sort_order":    int(sort_ord),
        }
        if is_edit and existing.get("id"):
            payload["id"] = existing["id"]
        try:
            upsert_service_default(payload)
            st.success("Servicio guardado." if not is_edit else "Servicio actualizado.")
            st.session_state.pop("admin_edit_service", None)
            st.session_state.pop("admin_svc_mode", None)
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")


def _services_section() -> None:
    from database.equipment_db import list_service_defaults, upsert_service_default, delete_service_default

    edit_svc = st.session_state.get("admin_edit_service")
    mode     = st.session_state.get("admin_svc_mode")   # None | "add"

    st.markdown("### Servicios y costos predeterminados")
    st.caption(
        "Define los servicios que aparecen por defecto en el Paso 7 de cada nueva propuesta. "
        "Los costos y el IVA pueden ajustarse individualmente en cada propuesta."
    )

    # ── Action bar (hidden when add form is open — form has its own Cancelar) ──
    if not edit_svc and mode != "add":
        c_add, _ = st.columns([2, 8])
        if c_add.button("Agregar servicio", key="admin_svc_toggle_add"):
            st.session_state["admin_svc_mode"] = "add"
            st.rerun()

    if mode == "add" and not edit_svc:
        st.divider()
        st.markdown("##### Nuevo servicio")
        _service_form()
        st.divider()

    # ── Service list ──────────────────────────────────────────────────────────
    try:
        rows = list_service_defaults()
    except Exception as e:
        st.error(f"Error al cargar servicios: {e}")
        return

    if not rows:
        st.info("No hay servicios configurados.")
        return

    # Header row
    h1, h2, h3, h4, h5 = st.columns([2.8, 1.6, 0.9, 0.9, 1.3])
    for hcol, label in zip([h1, h2, h3, h4, h5], ["Servicio", "Precio (USD)", "IVA", "Habilitado", "Acciones"]):
        hcol.markdown(
            f'<span style="font-size:0.78rem;font-weight:600;color:#6b7280;'
            f'text-transform:uppercase;letter-spacing:0.04em;">{label}</span>',
            unsafe_allow_html=True,
        )
    st.divider()

    for r in rows:
        c1, c2, c3, c4, c5 = st.columns([2.8, 1.6, 0.9, 0.9, 1.3])

        c1.markdown(f"**{r['item']}**")
        if r.get("item_en"):
            c1.caption(r["item_en"])

        c2.number_input(
            "Precio", value=float(r.get("unit_cost_usd") or 0),
            min_value=0.0, step=10.0, format="%.2f",
            key=f"svc_price_{r['id']}", label_visibility="collapsed",
        )

        iva_idx = 1 if float(r.get("iva_pct") or 0) >= 0.1 else 0
        c3.selectbox(
            "IVA", ["0%", "13%"], index=iva_idx,
            key=f"svc_iva_{r['id']}", label_visibility="collapsed",
        )

        c4.checkbox(
            "", value=bool(r.get("enabled", True)),
            key=f"svc_enabled_{r['id']}",
        )

        with c5:
            if st.button("Editar", key=f"esvc_{r['id']}", help="Editar", use_container_width=True):
                st.session_state["admin_edit_service"] = r
                st.session_state["admin_svc_mode"] = None
                st.rerun()
            if st.button("Eliminar", key=f"dsvc_{r['id']}", help="Eliminar", use_container_width=True):
                st.session_state[f"confirm_del_svc_{r['id']}"] = True
                st.rerun()

        if st.session_state.get(f"confirm_del_svc_{r['id']}"):
            st.warning(f"¿Eliminar **{r['item']}**? Esta acción no se puede deshacer.")
            cy, cn, _ = st.columns([1, 1, 6])
            if cy.button("Sí, eliminar", key=f"yes_del_svc_{r['id']}"):
                delete_service_default(r["id"])
                st.session_state.pop(f"confirm_del_svc_{r['id']}", None)
                st.rerun()
            if cn.button("Cancelar", key=f"no_del_svc_{r['id']}"):
                st.session_state.pop(f"confirm_del_svc_{r['id']}", None)
                st.rerun()

        # Inline edit form — shown only below the item being edited
        if edit_svc and edit_svc.get("id") == r["id"]:
            st.markdown("##### Editando servicio")
            _service_form(existing=edit_svc)

        st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #f1f5f9;">',
                    unsafe_allow_html=True)

    st.markdown("")
    if st.button("Guardar cambios", key="admin_svc_save_inline", type="primary"):
        saved = 0
        for r in rows:
            new_price   = float(st.session_state.get(f"svc_price_{r['id']}") or 0)
            new_iva     = 0.13 if "13" in str(st.session_state.get(f"svc_iva_{r['id']}") or "") else 0.0
            new_enabled = bool(st.session_state.get(f"svc_enabled_{r['id']}", True))

            old_price   = float(r.get("unit_cost_usd") or 0)
            old_iva     = float(r.get("iva_pct") or 0)
            old_enabled = bool(r.get("enabled", True))

            if abs(new_price - old_price) > 0.001 or abs(new_iva - old_iva) > 0.001 or new_enabled != old_enabled:
                upsert_service_default({
                    "id": r["id"], "item": r["item"],
                    "unit_cost_usd": new_price,
                    "iva_pct": new_iva,
                    "enabled": new_enabled,
                })
                saved += 1

        for r in rows:
            st.session_state.pop(f"svc_price_{r['id']}", None)
            st.session_state.pop(f"svc_iva_{r['id']}", None)
            st.session_state.pop(f"svc_enabled_{r['id']}", None)

        if saved:
            st.success(f"✅ {saved} servicio(s) actualizado(s).")
        else:
            st.info("Sin cambios.")
        st.rerun()


# ── clients / prospects ────────────────────────────────────────────────────────

def _client_form(existing: dict | None = None) -> None:
    src = existing or {}
    is_edit = existing is not None

    with st.form(key="client_form"):
        st.markdown("#### " + ("Editar cliente" if is_edit else "Nuevo cliente"))
        st.caption(
            "Agregar un cliente aquí es una acción intencional — este registro entra "
            "directamente a la lista de Clientes, no a Prospectos."
        )
        col1, col2 = st.columns(2)
        with col1:
            name    = st.text_input("Nombre *", value=src.get("name") or "")
            empresa = st.text_input("Empresa", value=src.get("empresa") or "")
        with col2:
            phone = st.text_input("Teléfono", value=src.get("phone") or "")
            email = st.text_input("Email", value=src.get("email") or "")
        notes = st.text_area("Notas", value=src.get("notes") or "", height=60)

        col_save, col_cancel = st.columns([1, 4])
        submitted = col_save.form_submit_button("Guardar", type="primary")
        cancelled = col_cancel.form_submit_button("Cancelar")

    if cancelled:
        st.session_state.pop("admin_edit_client", None)
        st.session_state.pop("admin_client_mode", None)
        st.rerun()

    if submitted:
        if not str(name).strip():
            st.error("El nombre es obligatorio.")
            return
        try:
            if is_edit and src.get("id"):
                from database.clients_db import update_client
                update_client(
                    client_id=src["id"], name=name, empresa=empresa,
                    phone=phone, email=email, notes=notes,
                )
                st.success("Cliente actualizado.")
            else:
                from database.clients_db import upsert_client
                upsert_client(name=name, empresa=empresa, phone=phone, email=email, notes=notes)
                st.success("Cliente agregado.")
            st.session_state.pop("admin_edit_client", None)
            st.session_state.pop("admin_client_mode", None)
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")


def _client_sites_linker(client: dict) -> None:
    """Checkbox list linking a client to their monitored sites — merged
    across both `monitoring.sites` (Oscar's own Node-RED/Cerbo-GX fleet,
    any brand) and `vrm.sites` (the VRM Monitor product's VRM-Portal-synced
    sites, always Victron Energy by construction — VRM Portal has no other
    brand). Each row is tagged with its brand and routed back to the right
    table's own link column (`monitoring.sites.client_id` vs
    `vrm.sites.public_client_id`) on check/uncheck.
    """
    from database.monitoring_sites_db import list_monitoring_sites, set_site_client
    from database.vrm_sites_db import list_vrm_sites_for_linking, set_site_public_client

    try:
        monitoring_sites = list_monitoring_sites()
    except Exception as e:
        st.caption(f"No se pudieron cargar los sitios de monitoreo: {e}")
        monitoring_sites = []

    try:
        vrm_sites = list_vrm_sites_for_linking()
    except Exception as e:
        st.caption(f"No se pudieron cargar los sitios de VRM Monitor: {e}")
        vrm_sites = []

    combined = [
        {
            "site_id": s["site_id"],
            "display_name": s.get("display_name") or s["site_id"],
            "brand": s.get("brand") or "Victron Energy",
            "linked_client_id": s.get("client_id"),
            "set_client": set_site_client,
        }
        for s in monitoring_sites
    ] + [
        {
            "site_id": s["site_id"],
            "display_name": s.get("display_name") or s["site_id"],
            "brand": "Victron Energy",
            "linked_client_id": s.get("public_client_id"),
            "set_client": set_site_public_client,
        }
        for s in vrm_sites
    ]
    combined.sort(key=lambda s: s["display_name"])

    if not combined:
        st.caption("No hay sitios registrados en Victron Monitor.")
        return

    st.markdown("###### Proyectos vinculados:")
    for s in combined:
        linked = s["linked_client_id"] == client["id"]
        checked = st.checkbox(
            f'{s["display_name"]} — {s["brand"]}',
            value=linked,
            key=f"site_link_{client['id']}_{s['site_id']}",
        )
        if checked != linked:
            new_client_id = client["id"] if checked else None
            try:
                s["set_client"](s["site_id"], new_client_id)
                st.rerun()
            except Exception as e:
                st.error(f"Error al vincular {s['site_id']}: {e}")


def _clients_section() -> None:
    from database.clients_db import list_all_clients

    edit_client = st.session_state.get("admin_edit_client")
    mode        = st.session_state.get("admin_client_mode")   # None | "add"

    st.markdown("### Clientes")
    st.caption(
        "Personas o empresas que han comprado un proyecto. Los interesados que aún "
        "no compran aparecen en la pestaña Prospectos y se mueven aquí automáticamente "
        "cuando una propuesta se marca como Ganada."
    )

    if not edit_client and mode != "add":
        c_add, _ = st.columns([2, 8])
        if c_add.button("Nuevo cliente", key="admin_client_toggle_add"):
            st.session_state["admin_client_mode"] = "add"
            st.rerun()

    if mode == "add" and not edit_client:
        st.divider()
        _client_form()
        st.divider()

    try:
        rows = list_all_clients()
    except Exception as e:
        st.error(f"Error al cargar clientes: {e}")
        return

    if not rows:
        st.info("No hay clientes todavía.")
        return

    for r in rows:
        c1, c2, c3 = st.columns([2.9, 2.9, 1.6])
        c1.markdown(f"**{r['name']}**" + (f" — {r['empresa']}" if r.get("empresa") else ""))
        c2.caption(" · ".join(filter(None, [r.get("phone"), r.get("email")])) or "—")
        with c3:
            if st.button("Editar", key=f"eclient_{r['id']}", help="Editar", use_container_width=True):
                st.session_state["admin_edit_client"] = r
                st.session_state["admin_client_mode"] = None
                st.rerun()
            if st.button("Eliminar", key=f"dclient_{r['id']}", help="Eliminar", use_container_width=True):
                st.session_state[f"confirm_del_client_{r['id']}"] = True
                st.rerun()

        if st.session_state.get(f"confirm_del_client_{r['id']}"):
            st.warning(f"¿Eliminar **{r['name']}**? Esta acción no se puede deshacer.")
            cy, cn, _ = st.columns([1, 1, 6])
            if cy.button("Sí, eliminar", key=f"yes_del_client_{r['id']}"):
                try:
                    from database.supabase_client import get_client
                    get_client().table("clients").delete().eq("id", r["id"]).execute()
                except Exception as e:
                    st.error(f"No se pudo eliminar (¿tiene propuestas asociadas?): {e}")
                st.session_state.pop(f"confirm_del_client_{r['id']}", None)
                st.rerun()
            if cn.button("Cancelar", key=f"no_del_client_{r['id']}"):
                st.session_state.pop(f"confirm_del_client_{r['id']}", None)
                st.rerun()

        if edit_client and edit_client.get("id") == r["id"]:
            st.markdown("##### Editando cliente")
            _client_form(existing=edit_client)
            _client_sites_linker(r)

        st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #f1f5f9;">',
                    unsafe_allow_html=True)


def _prospects_section() -> None:
    from database.prospects_db import list_all_prospects

    st.markdown("### Prospectos")
    st.caption(
        "Personas interesadas que han recibido una cotización pero aún no han comprado. "
        "Se agregan automáticamente desde el asistente de cotizaciones y se mueven a "
        "Clientes cuando su propuesta se marca como Ganada — no se editan aquí."
    )

    try:
        rows = list_all_prospects()
    except Exception as e:
        st.error(f"Error al cargar prospectos: {e}")
        return

    if not rows:
        st.info("No hay prospectos todavía.")
        return

    for r in rows:
        c1, c2, c3 = st.columns([3, 3, 2])
        c1.markdown(f"**{r['name']}**" + (f" — {r['empresa']}" if r.get("empresa") else ""))
        c2.caption(" · ".join(filter(None, [r.get("phone"), r.get("email")])) or "—")
        c3.caption((r.get("created_at") or "")[:10])
        st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #f1f5f9;">',
                    unsafe_allow_html=True)


# ── equipment catalog ─────────────────────────────────────────────────────────

_INV_TYPE_LABELS = {
    "string_inverter": "Inversor de string",
    "microinverter":   "Microinversor",
    "hybrid":          "Híbrido",
}
_PHASE_LABELS = {
    "single": "Monofásico",
    "three":  "Trifásico",
}

_IVA_OPTIONS = [0.0, 0.13]
_IVA_LABELS = {0.0: "0% (exento)", 0.13: "13%"}


def _cost_iva_block(key_prefix: str, cost_usd_default: float, iva_rate_default: float) -> tuple[float, float]:
    """
    Cost + IVA + computed total sub-block, shared by every equipment form
    (panel/inverter/battery/charge controller/monitoring) so pricing always
    reads the same way across the catalog. Returns (cost_usd, iva_rate) —
    the caller persists both; total is display-only, recomputed from them.

    Must be called OUTSIDE the caller's st.form(...) block — widgets inside
    a form don't trigger a rerun until submit, so "Total" would only reflect
    stale values. Rendered as plain (non-buffered) widgets instead so it
    updates on every keystroke. key_prefix must be unique per open form
    instance (the caller varies it by equipment id when editing) so
    switching between add/edit forms doesn't leak a stale value in.
    """
    st.markdown("###### Costo")
    c1, c2, c3 = st.columns(3)
    with c1:
        cost_usd = st.number_input(
            "Costo (USD)", value=float(cost_usd_default or 0), min_value=0.0, format="%.2f",
            key=f"{key_prefix}_cost_usd",
        )
    with c2:
        default_idx = _IVA_OPTIONS.index(iva_rate_default) if iva_rate_default in _IVA_OPTIONS else 0
        iva_rate = st.selectbox(
            "IVA", _IVA_OPTIONS, index=default_idx, format_func=lambda v: _IVA_LABELS[v],
            key=f"{key_prefix}_iva_rate",
        )
    with c3:
        st.metric("Total (USD)", f"${cost_usd * (1 + iva_rate):,.2f}")
    return cost_usd, iva_rate


def _pop_cost_iva_keys(key_prefix: str) -> None:
    st.session_state.pop(f"{key_prefix}_cost_usd", None)
    st.session_state.pop(f"{key_prefix}_iva_rate", None)


def _find_duplicate_equipment(
    items: list[dict], brand: str, model: str, exclude_id: str | None = None,
) -> dict | None:
    """Case-insensitive brand+model match against the current catalog,
    excluding the row being edited (if any) — the same name/model can't
    coincidentally collide with itself mid-edit."""
    b, m = (brand or "").strip().lower(), (model or "").strip().lower()
    if not b or not m:
        return None
    for it in items:
        if exclude_id and it.get("id") == exclude_id:
            continue
        if (it.get("brand") or "").strip().lower() == b and (it.get("model") or "").strip().lower() == m:
            return it
    return None


def _render_duplicate_confirm(state_prefix: str, upsert_fn, kind_label: str) -> bool:
    """
    Renders the "Sobrescribir / Mantener el actual" choice when a form's
    submit handler found an existing catalog row with the same brand+model
    (see _find_duplicate_equipment()) and stashed the pending save under
    f"{state_prefix}_dup_payload"/f"{state_prefix}_dup_existing". Two
    choices only, by design — this tool doesn't allow two catalog rows with
    the same brand+model to coexist, so there's no third "add anyway".

    Returns True if a pending confirm was rendered (caller should render
    nothing else for this form on this run), False if there's nothing
    pending.
    """
    payload = st.session_state.get(f"{state_prefix}_dup_payload")
    dup = st.session_state.get(f"{state_prefix}_dup_existing")
    if not payload or not dup:
        return False

    st.warning(
        f"Ya existe **{dup.get('brand', '')} {dup.get('model', '')}** en el catálogo. "
        f"¿Sobrescribir con los datos nuevos, o mantener el {kind_label} actual sin cambios?"
    )
    c1, c2 = st.columns(2)
    if c1.button(f"Sobrescribir {kind_label} existente", key=f"{state_prefix}_dup_overwrite", type="primary"):
        upsert_fn({**payload, "id": dup["id"]})
        st.success(f"{kind_label.capitalize()} actualizado.")
        st.session_state.pop(f"{state_prefix}_dup_payload", None)
        st.session_state.pop(f"{state_prefix}_dup_existing", None)
        st.rerun()
    if c2.button("Mantener el actual (descartar cambios)", key=f"{state_prefix}_dup_keep"):
        st.session_state.pop(f"{state_prefix}_dup_payload", None)
        st.session_state.pop(f"{state_prefix}_dup_existing", None)
        st.info(f"Se mantuvo el {kind_label} existente sin cambios.")
        st.rerun()
    return True


def _panel_form(existing: dict | None = None, prefill: dict | None = None) -> None:
    """Render add/edit form for a solar panel. existing=edit mode, prefill=from datasheet."""
    src = prefill or existing or {}
    is_edit = existing is not None
    cost_key = f"admin_panel_cost_{existing['id']}" if is_edit else "admin_panel_cost_new"

    st.markdown("#### " + ("Editar panel" if is_edit else "Nuevo panel"))
    cost_usd, iva_rate = _cost_iva_block(cost_key, src.get("cost_usd"), src.get("cost_iva_rate") or 0.0)
    st.divider()

    with st.form(key="panel_form"):
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

        col3, col4 = st.columns(2)
        with col3:
            warr_prod = st.number_input("Garantía producto (años)", value=int(src.get("warranty_product_yr") or 12), min_value=0, step=1)
        with col4:
            warr_pow  = st.number_input("Garantía potencia (años)", value=int(src.get("warranty_power_yr") or 25), min_value=0, step=1)

        notes = st.text_area("Notas", value=src.get("notes") or "", height=60)

        col_save, col_cancel = st.columns([1, 4])
        submitted = col_save.form_submit_button("Guardar", type="primary")
        cancelled = col_cancel.form_submit_button("Cancelar")

    if cancelled:
        st.session_state.pop("admin_edit_panel", None)
        st.session_state.pop("admin_prefill_panel", None)
        st.session_state.pop("admin_panel_mode", None)
        _pop_cost_iva_keys(cost_key)
        st.rerun()

    if submitted:
        if not brand.strip() or not model.strip() or wp <= 0:
            st.error("Marca, modelo y potencia son obligatorios.")
            return
        from database.equipment_db import upsert_panel, list_panels
        payload = {
            "brand": brand.strip(), "model": model.strip(), "wp": int(wp),
            "voc": voc or None, "vmp": vmp or None,
            "isc": isc or None, "imp": imp or None,
            "temp_coeff_pmax": tc or None,
            "width_m": width or None, "height_m": height or None,
            "warranty_product_yr": warr_prod, "warranty_power_yr": warr_pow,
            "cost_usd": cost_usd or None, "cost_iva_rate": iva_rate, "notes": notes.strip() or None,
        }
        if is_edit:
            payload["id"] = existing["id"]

        exclude_id = existing["id"] if is_edit else None
        dup = _find_duplicate_equipment(list_panels(), brand, model, exclude_id=exclude_id)
        if dup:
            st.session_state["admin_panel_dup_payload"] = payload
            st.session_state["admin_panel_dup_existing"] = dup
            st.rerun()
            return

        try:
            upsert_panel(payload)
            st.success("Panel guardado." if not is_edit else "Panel actualizado.")
            st.session_state.pop("admin_edit_panel", None)
            st.session_state.pop("admin_prefill_panel", None)
            st.session_state.pop("admin_panel_mode", None)
            _pop_cost_iva_keys(cost_key)
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")

    from database.equipment_db import upsert_panel as _upsert_panel_for_confirm
    _render_duplicate_confirm("admin_panel", _upsert_panel_for_confirm, "panel")


def _panels_section() -> None:
    from database.equipment_db import list_panels, delete_panel, upsert_panel

    mode         = st.session_state.get("admin_panel_mode")   # None | "extract" | "add"
    edit_panel   = st.session_state.get("admin_edit_panel")
    prefill_panel= st.session_state.get("admin_prefill_panel")

    # ── Action bar (hidden when add form is open — form has its own Cancelar) ──
    if not edit_panel and not prefill_panel:
        if mode == "extract":
            c_ext, _ = st.columns([2, 7])
            if c_ext.button("Cerrar", key="admin_panel_toggle_extract"):
                st.session_state["admin_panel_mode"] = None
                st.session_state.pop("admin_panel_variants", None)
                st.rerun()
        elif mode is None:
            c_ext, c_add, _ = st.columns([2, 2, 5])
            if c_ext.button("Extraer de datasheet", key="admin_panel_toggle_extract"):
                st.session_state["admin_panel_mode"] = "extract"
                st.rerun()
            if c_add.button("Agregar panel", key="admin_panel_toggle_add"):
                st.session_state["admin_panel_mode"] = "add"
                st.rerun()

    # ── Active form (add/extract/prefill only — edit appears inline below item) ─
    if prefill_panel:
        st.divider()
        st.markdown("##### Nuevo panel — datos del datasheet")
        _panel_form(prefill=prefill_panel)
        st.divider()
    elif mode == "add":
        st.divider()
        st.markdown("##### Nuevo panel")
        _panel_form()
        st.divider()
    elif mode == "extract":
        st.divider()
        st.markdown("##### Extraer especificaciones de datasheet")
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
                    idx = st.selectbox("Selecciona el modelo", range(len(opts)),
                                       format_func=lambda i: opts[i], key="admin_panel_var_idx")
                    selected = variants[idx]
                else:
                    selected = variants[0]
                    st.success(f"Extraído: {selected.get('brand')} {selected.get('model')} — {selected.get('wp')}W")
                if st.button("Usar estos datos →", key="admin_panel_use", type="primary"):
                    st.session_state["admin_prefill_panel"] = selected
                    st.session_state.pop("admin_edit_panel", None)
                    st.session_state.pop("admin_panel_variants", None)
                    st.session_state["admin_panel_mode"] = None
                    st.rerun()
        st.divider()

    # ── Panel list ────────────────────────────────────────────────────────────
    st.markdown("#### Paneles en catálogo")
    try:
        panels = list_panels()
    except Exception as e:
        st.error(f"Error al cargar paneles: {e}")
        return

    if not panels:
        st.info("No hay paneles en el catálogo.")
        return

    # Header row
    h1, h2, h3, h4 = st.columns([2.3, 2.9, 1.5, 1.3])
    for hcol, label in zip([h1, h2, h3, h4], ["Panel", "Eléctrico", "Precio (USD)", "Acciones"]):
        hcol.markdown(
            f'<span style="font-size:0.78rem;font-weight:600;color:#6b7280;'
            f'text-transform:uppercase;letter-spacing:0.04em;">{label}</span>',
            unsafe_allow_html=True,
        )
    st.divider()

    for p in panels:
        area = round((p.get("width_m") or 0) * (p.get("height_m") or 0), 2)
        c1, c2, c3, c4 = st.columns([2.3, 2.9, 1.5, 1.3])

        c1.markdown(
            f'<div style="line-height:1.8;">'
            f'<strong>{p["brand"]} {p["model"]}</strong><br>'
            f'<span style="background:#f1f5f9;border:1.5px solid #cbd5e1;border-radius:5px;'
            f'padding:2px 10px;font-size:0.92rem;font-weight:700;color:#1e293b;">'
            f'{p["wp"]} Wp</span><br>'
            f'<span style="font-size:0.8rem;color:#6b7280;">{area} m²</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        c2.markdown(
            f'<div style="font-size:0.82rem;color:#6b7280;line-height:1.8;">'
            f'Voc {p.get("voc") or "—"} V<br>'
            f'Vmp {p.get("vmp") or "—"} V<br>'
            f'Isc {p.get("isc") or "—"} A<br>'
            f'Imp {p.get("imp") or "—"} A'
            f'</div>',
            unsafe_allow_html=True,
        )

        c3.number_input(
            "Precio", value=float(p.get("cost_usd") or 0),
            min_value=0.0, step=10.0, format="%.2f",
            key=f"p_price_{p['id']}", label_visibility="collapsed",
        )

        with c4:
            if st.button("Editar", key=f"ep_{p['id']}", help="Editar", use_container_width=True):
                st.session_state["admin_edit_panel"] = p
                st.session_state.pop("admin_prefill_panel", None)
                st.session_state["admin_panel_mode"] = None
                st.rerun()
            confirm_key = f"confirm_del_panel_{p['id']}"
            if st.button("Eliminar", key=f"dp_{p['id']}", help="Eliminar", use_container_width=True):
                st.session_state[confirm_key] = True
                st.rerun()

        if st.session_state.get(f"confirm_del_panel_{p['id']}"):
            st.warning(f"¿Eliminar **{p['brand']} {p['model']}**? Esta acción no se puede deshacer.")
            cy, cn, _ = st.columns([1, 1, 6])
            if cy.button("Sí, eliminar", key=f"yes_del_panel_{p['id']}"):
                delete_panel(p["id"])
                st.session_state.pop(f"confirm_del_panel_{p['id']}", None)
                st.rerun()
            if cn.button("Cancelar", key=f"no_del_panel_{p['id']}"):
                st.session_state.pop(f"confirm_del_panel_{p['id']}", None)
                st.rerun()

        # Inline edit form — shown only below the item being edited
        if edit_panel and edit_panel.get("id") == p["id"]:
            st.markdown("##### Editando panel")
            _panel_form(existing=edit_panel)

        st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #f1f5f9;">',
                    unsafe_allow_html=True)

    st.markdown("")
    if st.button("Guardar precios de paneles", key="save_panel_prices"):
        saved = 0
        for p in panels:
            new_price = float(st.session_state.get(f"p_price_{p['id']}") or 0)
            if abs(new_price - float(p.get("cost_usd") or 0)) > 0.001:
                upsert_panel({"id": p["id"], "cost_usd": new_price})
                saved += 1
            st.session_state.pop(f"p_price_{p['id']}", None)
        if saved:
            st.success(f"✅ {saved} precio(s) actualizado(s).")
        else:
            st.info("Sin cambios en los precios.")
        st.rerun()


def _inverter_form(existing: dict | None = None, prefill: dict | None = None) -> None:
    src = prefill or existing or {}
    is_edit = existing is not None
    cost_key = f"admin_inv_cost_{existing['id']}" if is_edit else "admin_inv_cost_new"

    st.markdown("#### " + ("Editar inversor" if is_edit else "Nuevo inversor"))
    cost_usd, iva_rate = _cost_iva_block(cost_key, src.get("cost_usd"), src.get("cost_iva_rate") or 0.0)
    st.divider()

    with st.form(key="inverter_form"):
        col1, col2 = st.columns(2)
        with col1:
            brand  = st.text_input("Marca *", value=src.get("brand") or "")
            model  = st.text_input("Modelo *", value=src.get("model") or "")
            kw     = st.number_input("Potencia (kW) *", value=float(src.get("kw") or 0), min_value=0.0, step=0.1, format="%.1f")
            inv_type = st.selectbox(
                "Tipo", ["string_inverter", "microinverter", "hybrid"],
                index=["string_inverter", "microinverter", "hybrid"].index(src.get("type") or "string_inverter"),
                format_func=lambda x: _INV_TYPE_LABELS.get(x, x),
            )
            phase = st.selectbox(
                "Fase", ["single", "three"],
                index=["single", "three"].index(src.get("phase") or "single"),
                format_func=lambda x: _PHASE_LABELS.get(x, x),
            )
        with col2:
            vmax      = st.number_input("V máx entrada DC (V)", value=float(src.get("vmax") or 0), min_value=0.0, step=10.0)
            vmin_mppt = st.number_input("Vmin MPPT (V)", value=float(src.get("vmin_mppt") or 0), min_value=0.0)
            vmax_mppt = st.number_input("Vmax MPPT (V)", value=float(src.get("vmax_mppt") or 0), min_value=0.0)
            imax_mppt = st.number_input("Imax por MPPT (A)", value=float(src.get("imax_mppt") or 0), min_value=0.0, format="%.1f")
            mppt_ch   = st.number_input("Canales MPPT", value=int(src.get("mppt_channels") or 1), min_value=1, step=1)

        col3, col4 = st.columns(2)
        with col3:
            output_v  = st.number_input("Tensión salida AC (V)", value=float(src.get("output_v") or 240), min_value=0.0)
            ac_out_a  = st.number_input(
                "Corriente AC salida continua (A)", value=float(src.get("ac_output_current_a") or 0),
                min_value=0.0, step=1.0, format="%.1f",
                help="Corriente CA nominal/continua del datasheet — no la calcules de kW/V, usa el dato impreso.",
            )
        with col4:
            ac_in_a   = st.number_input(
                "Corriente AC entrada máx. — passthrough (A)", value=float(src.get("ac_input_current_max_a") or 0),
                min_value=0.0, step=1.0, format="%.1f",
                help="Solo inversores híbridos: corriente máxima de entrada/passthrough AC (red o generador). Dejar en 0 si no aplica.",
            )
            warr_yr   = st.number_input("Garantía (años)", value=int(src.get("warranty_yr") or 5), min_value=0, step=1)

        notes = st.text_area("Notas", value=src.get("notes") or "", height=60)

        col_save, col_cancel = st.columns([1, 4])
        submitted = col_save.form_submit_button("Guardar", type="primary")
        cancelled = col_cancel.form_submit_button("Cancelar")

    if cancelled:
        st.session_state.pop("admin_edit_inverter", None)
        st.session_state.pop("admin_prefill_inverter", None)
        st.session_state.pop("admin_inv_mode", None)
        _pop_cost_iva_keys(cost_key)
        st.rerun()

    if submitted:
        if not brand.strip() or not model.strip() or kw <= 0:
            st.error("Marca, modelo y potencia son obligatorios.")
            return
        from database.equipment_db import upsert_inverter, list_inverters
        payload = {
            "brand": brand.strip(), "model": model.strip(), "kw": kw,
            "type": inv_type, "phase": phase,
            "vmax": vmax or None, "vmin_mppt": vmin_mppt or None,
            "vmax_mppt": vmax_mppt or None, "imax_mppt": imax_mppt or None,
            "mppt_channels": mppt_ch, "output_v": output_v or None,
            "ac_output_current_a": ac_out_a or None, "ac_input_current_max_a": ac_in_a or None,
            "warranty_yr": warr_yr, "cost_usd": cost_usd or None, "cost_iva_rate": iva_rate,
            "notes": notes.strip() or None,
        }
        if is_edit:
            payload["id"] = existing["id"]

        exclude_id = existing["id"] if is_edit else None
        dup = _find_duplicate_equipment(list_inverters(), brand, model, exclude_id=exclude_id)
        if dup:
            st.session_state["admin_inv_dup_payload"] = payload
            st.session_state["admin_inv_dup_existing"] = dup
            st.rerun()
            return

        try:
            upsert_inverter(payload)
            st.success("Inversor guardado." if not is_edit else "Inversor actualizado.")
            st.session_state.pop("admin_edit_inverter", None)
            st.session_state.pop("admin_prefill_inverter", None)
            st.session_state.pop("admin_inv_mode", None)
            _pop_cost_iva_keys(cost_key)
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")

    from database.equipment_db import upsert_inverter as _upsert_inverter_for_confirm
    _render_duplicate_confirm("admin_inv", _upsert_inverter_for_confirm, "inversor")


def _inverters_section() -> None:
    from database.equipment_db import list_inverters, delete_inverter, upsert_inverter

    mode      = st.session_state.get("admin_inv_mode")   # None | "extract" | "add"
    edit_inv  = st.session_state.get("admin_edit_inverter")
    prefill_inv = st.session_state.get("admin_prefill_inverter")

    # ── Action bar (hidden when add form is open — form has its own Cancelar) ──
    if not edit_inv and not prefill_inv:
        if mode == "extract":
            c_ext, _ = st.columns([2, 7])
            if c_ext.button("Cerrar", key="admin_inv_toggle_extract"):
                st.session_state["admin_inv_mode"] = None
                st.session_state.pop("admin_inv_variants", None)
                st.rerun()
        elif mode is None:
            c_ext, c_add, _ = st.columns([2, 2, 5])
            if c_ext.button("Extraer de datasheet", key="admin_inv_toggle_extract"):
                st.session_state["admin_inv_mode"] = "extract"
                st.rerun()
            if c_add.button("Agregar inversor", key="admin_inv_toggle_add"):
                st.session_state["admin_inv_mode"] = "add"
                st.rerun()

    # ── Active form (add/extract/prefill only — edit appears inline below item) ─
    if prefill_inv:
        st.divider()
        st.markdown("##### Nuevo inversor — datos del datasheet")
        _inverter_form(prefill=prefill_inv)
        st.divider()
    elif mode == "add":
        st.divider()
        st.markdown("##### Nuevo inversor")
        _inverter_form()
        st.divider()
    elif mode == "extract":
        st.divider()
        st.markdown("##### Extraer especificaciones de datasheet")
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
                    idx = st.selectbox("Selecciona el modelo", range(len(opts)),
                                       format_func=lambda i: opts[i], key="admin_inv_var_idx")
                    selected = variants[idx]
                else:
                    selected = variants[0]
                    st.success(f"Extraído: {selected.get('brand')} {selected.get('model')} — {selected.get('kw')} kW")
                if st.button("Usar estos datos →", key="admin_inv_use", type="primary"):
                    st.session_state["admin_prefill_inverter"] = selected
                    st.session_state.pop("admin_edit_inverter", None)
                    st.session_state.pop("admin_inv_variants", None)
                    st.session_state["admin_inv_mode"] = None
                    st.rerun()
        st.divider()

    # ── Inverter list ─────────────────────────────────────────────────────────
    st.markdown("#### Inversores en catálogo")
    try:
        inverters = list_inverters()
    except Exception as e:
        st.error(f"Error al cargar inversores: {e}")
        return

    if not inverters:
        st.info("No hay inversores en el catálogo.")
        return

    # Header row
    h1, h2, h3, h4 = st.columns([2.3, 2.9, 1.5, 1.3])
    for hcol, label in zip([h1, h2, h3, h4], ["Inversor", "MPPT / Tensión", "Precio (USD)", "Acciones"]):
        hcol.markdown(
            f'<span style="font-size:0.78rem;font-weight:600;color:#6b7280;'
            f'text-transform:uppercase;letter-spacing:0.04em;">{label}</span>',
            unsafe_allow_html=True,
        )
    st.divider()

    for inv in inverters:
        c1, c2, c3, c4 = st.columns([2.3, 2.9, 1.5, 1.3])

        type_label  = _INV_TYPE_LABELS.get(inv.get("type") or "", inv.get("type") or "—")
        phase_label = _PHASE_LABELS.get(inv.get("phase") or "", inv.get("phase") or "—")

        c1.markdown(
            f'<div style="line-height:1.8;">'
            f'<strong>{inv["brand"]} {inv["model"]}</strong><br>'
            f'<span style="background:#f1f5f9;border:1.5px solid #cbd5e1;border-radius:5px;'
            f'padding:2px 10px;font-size:0.92rem;font-weight:700;color:#1e293b;">'
            f'{inv["kw"]} kW</span><br>'
            f'<span style="font-size:0.8rem;color:#6b7280;">{type_label} · {phase_label}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        c2.markdown(
            f'<div style="font-size:0.82rem;color:#6b7280;line-height:1.8;">'
            f'Vmax {inv.get("vmax") or "—"} V<br>'
            f'MPPT {inv.get("vmin_mppt") or "—"}–{inv.get("vmax_mppt") or "—"} V<br>'
            f'Imax MPPT {inv.get("imax_mppt") or "—"} A<br>'
            f'{inv.get("mppt_channels") or "—"} canales<br>'
            f'AC salida {inv.get("ac_output_current_a") or "—"} A · '
            f'AC entrada máx {inv.get("ac_input_current_max_a") or "—"} A'
            f'</div>',
            unsafe_allow_html=True,
        )

        c3.number_input(
            "Precio", value=float(inv.get("cost_usd") or 0),
            min_value=0.0, step=50.0, format="%.2f",
            key=f"inv_price_{inv['id']}", label_visibility="collapsed",
        )

        with c4:
            if st.button("Editar", key=f"ei_{inv['id']}", help="Editar", use_container_width=True):
                st.session_state["admin_edit_inverter"] = inv
                st.session_state.pop("admin_prefill_inverter", None)
                st.session_state["admin_inv_mode"] = None
                st.rerun()
            confirm_key = f"confirm_del_inv_{inv['id']}"
            if st.button("Eliminar", key=f"di_{inv['id']}", help="Eliminar", use_container_width=True):
                st.session_state[confirm_key] = True
                st.rerun()

        if st.session_state.get(f"confirm_del_inv_{inv['id']}"):
            st.warning(f"¿Eliminar **{inv['brand']} {inv['model']}**? Esta acción no se puede deshacer.")
            cy, cn, _ = st.columns([1, 1, 6])
            if cy.button("Sí, eliminar", key=f"yes_del_inv_{inv['id']}"):
                delete_inverter(inv["id"])
                st.session_state.pop(f"confirm_del_inv_{inv['id']}", None)
                st.rerun()
            if cn.button("Cancelar", key=f"no_del_inv_{inv['id']}"):
                st.session_state.pop(f"confirm_del_inv_{inv['id']}", None)
                st.rerun()

        # Inline edit form — shown only below the item being edited
        if edit_inv and edit_inv.get("id") == inv["id"]:
            st.markdown("##### Editando inversor")
            _inverter_form(existing=edit_inv)

        st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #f1f5f9;">',
                    unsafe_allow_html=True)

    st.markdown("")
    if st.button("Guardar precios de inversores", key="save_inv_prices"):
        saved = 0
        for inv in inverters:
            new_price = float(st.session_state.get(f"inv_price_{inv['id']}") or 0)
            if abs(new_price - float(inv.get("cost_usd") or 0)) > 0.001:
                upsert_inverter({"id": inv["id"], "cost_usd": new_price})
                saved += 1
            st.session_state.pop(f"inv_price_{inv['id']}", None)
        if saved:
            st.success(f"✅ {saved} precio(s) actualizado(s).")
        else:
            st.info("Sin cambios en los precios.")
        st.rerun()


def _battery_form(existing: dict | None = None, prefill: dict | None = None) -> None:
    """Add/edit form for a battery. existing=edit mode, prefill=from datasheet."""
    src = prefill or existing or {}
    is_edit = existing is not None
    cost_key = f"admin_battery_cost_{existing['id']}" if is_edit else "admin_battery_cost_new"

    st.markdown("#### " + ("Editar batería" if is_edit else "Nueva batería"))
    cost_usd, iva_rate = _cost_iva_block(cost_key, src.get("cost_usd"), src.get("cost_iva_rate") or 0.0)
    st.divider()

    with st.form(key="battery_form"):
        col1, col2 = st.columns(2)
        with col1:
            brand = st.text_input("Marca *", value=src.get("brand") or "")
            model = st.text_input("Modelo *", value=src.get("model") or "")
            chemistry = st.text_input("Química", value=src.get("chemistry") or "LiFePO4")
            capacity_kwh = st.number_input("Capacidad (kWh) *", value=float(src.get("capacity_kwh") or 0), min_value=0.0, format="%.2f")
            capacity_ah = st.number_input("Capacidad (Ah)", value=float(src.get("capacity_ah") or 0), min_value=0.0, format="%.1f")
        with col2:
            voltage_v = st.number_input("Voltaje (V) *", value=float(src.get("voltage_v") or 48), min_value=0.0)
            dod_pct   = st.number_input("Descarga máxima DoD (%)", value=int(src.get("dod_pct") or 80), min_value=0, max_value=100, step=1)
            cycles    = st.number_input("Ciclos", value=int(src.get("cycles") or 0), min_value=0, step=100)
            warr_yr   = st.number_input("Garantía (años)", value=int(src.get("warranty_yr") or 10), min_value=0, step=1)

        notes = st.text_area("Notas", value=src.get("notes") or "", height=60)

        col_save, col_cancel = st.columns([1, 4])
        submitted = col_save.form_submit_button("Guardar", type="primary")
        cancelled = col_cancel.form_submit_button("Cancelar")

    if cancelled:
        st.session_state.pop("admin_edit_battery", None)
        st.session_state.pop("admin_prefill_battery", None)
        st.session_state.pop("admin_battery_mode", None)
        _pop_cost_iva_keys(cost_key)
        st.rerun()

    if submitted:
        if not brand.strip() or not model.strip() or capacity_kwh <= 0 or voltage_v <= 0:
            st.error("Marca, modelo, capacidad y voltaje son obligatorios.")
            return
        from database.equipment_db import upsert_battery, list_batteries
        payload = {
            "brand": brand.strip(), "model": model.strip(),
            "chemistry": chemistry.strip() or "LiFePO4",
            "capacity_kwh": capacity_kwh, "capacity_ah": capacity_ah or None,
            "voltage_v": voltage_v, "dod_pct": dod_pct, "cycles": cycles or None,
            "warranty_yr": warr_yr, "cost_usd": cost_usd or None, "cost_iva_rate": iva_rate,
            "notes": notes.strip() or None,
        }
        if is_edit:
            payload["id"] = existing["id"]

        exclude_id = existing["id"] if is_edit else None
        dup = _find_duplicate_equipment(list_batteries(), brand, model, exclude_id=exclude_id)
        if dup:
            st.session_state["admin_battery_dup_payload"] = payload
            st.session_state["admin_battery_dup_existing"] = dup
            st.rerun()
            return

        try:
            upsert_battery(payload)
            st.success("Batería guardada." if not is_edit else "Batería actualizada.")
            st.session_state.pop("admin_edit_battery", None)
            st.session_state.pop("admin_prefill_battery", None)
            st.session_state.pop("admin_battery_mode", None)
            _pop_cost_iva_keys(cost_key)
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")

    from database.equipment_db import upsert_battery as _upsert_battery_for_confirm
    _render_duplicate_confirm("admin_battery", _upsert_battery_for_confirm, "batería")


def _batteries_section() -> None:
    from database.equipment_db import list_batteries, delete_battery

    mode         = st.session_state.get("admin_battery_mode")   # None | "extract" | "add"
    edit_battery = st.session_state.get("admin_edit_battery")
    prefill_battery = st.session_state.get("admin_prefill_battery")

    # ── Action bar (hidden when add form is open — form has its own Cancelar) ──
    if not edit_battery and not prefill_battery:
        if mode == "extract":
            c_ext, _ = st.columns([2, 7])
            if c_ext.button("Cerrar", key="admin_battery_toggle_extract"):
                st.session_state["admin_battery_mode"] = None
                st.session_state.pop("admin_battery_variants", None)
                st.rerun()
        elif mode is None:
            c_ext, c_add, _ = st.columns([2, 2, 5])
            if c_ext.button("Extraer de datasheet", key="admin_battery_toggle_extract"):
                st.session_state["admin_battery_mode"] = "extract"
                st.rerun()
            if c_add.button("Agregar batería", key="admin_battery_toggle_add"):
                st.session_state["admin_battery_mode"] = "add"
                st.rerun()

    # ── Active form (add/extract/prefill only — edit appears inline below item) ─
    if prefill_battery:
        st.divider()
        st.markdown("##### Nueva batería — datos del datasheet")
        _battery_form(prefill=prefill_battery)
        st.divider()
    elif mode == "add":
        st.divider()
        st.markdown("##### Nueva batería")
        _battery_form()
        st.divider()
    elif mode == "extract":
        st.divider()
        st.markdown("##### Extraer especificaciones de datasheet")
        st.caption("Sube el datasheet del fabricante. La IA extrae las especificaciones técnicas.")
        pdf_file = st.file_uploader("Datasheet PDF", type=["pdf"], key="admin_battery_ds")
        if pdf_file:
            variants = st.session_state.get("admin_battery_variants")
            if st.button("Extraer especificaciones", key="admin_battery_extract"):
                with st.spinner("Analizando datasheet…"):
                    try:
                        from calculations.datasheet_parser import parse_battery_datasheet
                        variants = parse_battery_datasheet(pdf_file.read())
                        st.session_state["admin_battery_variants"] = variants
                    except Exception as e:
                        st.error(f"Error al procesar el datasheet: {e}")
                        variants = None
            if variants:
                if len(variants) > 1:
                    opts = [f"{v.get('brand','')} {v.get('model','')} — {v.get('capacity_kwh','')} kWh" for v in variants]
                    idx = st.selectbox("Selecciona el modelo", range(len(opts)),
                                       format_func=lambda i: opts[i], key="admin_battery_var_idx")
                    selected = variants[idx]
                else:
                    selected = variants[0]
                    st.success(f"Extraído: {selected.get('brand')} {selected.get('model')} — {selected.get('capacity_kwh')} kWh")
                if st.button("Usar estos datos →", key="admin_battery_use", type="primary"):
                    st.session_state["admin_prefill_battery"] = selected
                    st.session_state.pop("admin_edit_battery", None)
                    st.session_state.pop("admin_battery_variants", None)
                    st.session_state["admin_battery_mode"] = None
                    st.rerun()
        st.divider()

    st.markdown("#### Baterías en catálogo")
    try:
        batteries = list_batteries()
    except Exception as e:
        st.error(f"Error al cargar baterías: {e}")
        return

    if not batteries:
        st.info("No hay baterías en el catálogo.")
        return

    h1, h2, h3, h4 = st.columns([2.3, 2.9, 1.5, 1.3])
    for hcol, label in zip([h1, h2, h3, h4], ["Batería", "Eléctrico", "Precio (USD)", "Acciones"]):
        hcol.markdown(
            f'<span style="font-size:0.78rem;font-weight:600;color:#6b7280;'
            f'text-transform:uppercase;letter-spacing:0.04em;">{label}</span>',
            unsafe_allow_html=True,
        )
    st.divider()

    for b in batteries:
        c1, c2, c3, c4 = st.columns([2.3, 2.9, 1.5, 1.3])
        c1.markdown(
            f'<div style="line-height:1.8;">'
            f'<strong>{b["brand"]} {b["model"]}</strong><br>'
            f'<span style="background:#f1f5f9;border:1.5px solid #cbd5e1;border-radius:5px;'
            f'padding:2px 10px;font-size:0.92rem;font-weight:700;color:#1e293b;">'
            f'{b["capacity_kwh"]} kWh</span><br>'
            f'<span style="font-size:0.8rem;color:#6b7280;">{b.get("chemistry") or "—"}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        c2.markdown(
            f'<div style="font-size:0.82rem;color:#6b7280;line-height:1.8;">'
            f'Voltaje {b.get("voltage_v") or "—"} V<br>'
            f'DoD máx {b.get("dod_pct") or "—"}%<br>'
            f'Ciclos {b.get("cycles") or "—"}<br>'
            f'Capacidad {b.get("capacity_ah") or "—"} Ah'
            f'</div>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f'<div style="font-size:0.92rem;padding-top:0.4rem;">${float(b.get("cost_usd") or 0):,.2f}</div>',
            unsafe_allow_html=True,
        )
        with c4:
            if st.button("Editar", key=f"eb_{b['id']}", help="Editar", use_container_width=True):
                st.session_state["admin_edit_battery"] = b
                st.session_state["admin_battery_mode"] = None
                st.rerun()
            confirm_key = f"confirm_del_battery_{b['id']}"
            if st.button("Eliminar", key=f"db_{b['id']}", help="Eliminar", use_container_width=True):
                st.session_state[confirm_key] = True
                st.rerun()

        if st.session_state.get(f"confirm_del_battery_{b['id']}"):
            st.warning(f"¿Eliminar **{b['brand']} {b['model']}**? Esta acción no se puede deshacer.")
            cy, cn, _ = st.columns([1, 1, 6])
            if cy.button("Sí, eliminar", key=f"yes_del_battery_{b['id']}"):
                delete_battery(b["id"])
                st.session_state.pop(f"confirm_del_battery_{b['id']}", None)
                st.rerun()
            if cn.button("Cancelar", key=f"no_del_battery_{b['id']}"):
                st.session_state.pop(f"confirm_del_battery_{b['id']}", None)
                st.rerun()

        if edit_battery and edit_battery.get("id") == b["id"]:
            st.markdown("##### Editando batería")
            _battery_form(existing=edit_battery)

        st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #f1f5f9;">',
                    unsafe_allow_html=True)


def _charge_controller_form(existing: dict | None = None, prefill: dict | None = None) -> None:
    """Add/edit form for a charge controller. existing=edit mode, prefill=from datasheet."""
    src = prefill or existing or {}
    is_edit = existing is not None
    cost_key = f"admin_cc_cost_{existing['id']}" if is_edit else "admin_cc_cost_new"

    st.markdown("#### " + ("Editar controlador de carga" if is_edit else "Nuevo controlador de carga"))
    cost_usd, iva_rate = _cost_iva_block(cost_key, src.get("cost_usd"), src.get("cost_iva_rate") or 0.0)
    st.divider()

    with st.form(key="cc_form"):
        col1, col2 = st.columns(2)
        with col1:
            brand   = st.text_input("Marca *", value=src.get("brand") or "")
            model   = st.text_input("Modelo *", value=src.get("model") or "")
            _cc_type_default = src.get("type") if src.get("type") in ("MPPT", "PWM") else "MPPT"
            cc_type = st.selectbox("Tipo *", ["MPPT", "PWM"], index=["MPPT", "PWM"].index(_cc_type_default))
        with col2:
            vin_max  = st.number_input("Vin máx (V) *", value=float(src.get("vin_max") or 0), min_value=0.0)
            vout     = st.number_input("Vout (V) *", value=float(src.get("vout") or 0), min_value=0.0)
            imax_in  = st.number_input("Imax entrada (A) *", value=float(src.get("imax_in") or 0), min_value=0.0, format="%.1f")
            imax_out = st.number_input("Imax salida (A) *", value=float(src.get("imax_out") or 0), min_value=0.0, format="%.1f")

        notes = st.text_area("Notas", value=src.get("notes") or "", height=60)

        col_save, col_cancel = st.columns([1, 4])
        submitted = col_save.form_submit_button("Guardar", type="primary")
        cancelled = col_cancel.form_submit_button("Cancelar")

    if cancelled:
        st.session_state.pop("admin_edit_cc", None)
        st.session_state.pop("admin_prefill_cc", None)
        st.session_state.pop("admin_cc_mode", None)
        _pop_cost_iva_keys(cost_key)
        st.rerun()

    if submitted:
        if not brand.strip() or not model.strip() or vin_max <= 0 or imax_in <= 0:
            st.error("Marca, modelo, Vin máx e Imax entrada son obligatorios.")
            return
        from database.equipment_db import upsert_charge_controller, list_charge_controllers
        payload = {
            "brand": brand.strip(), "model": model.strip(), "type": cc_type,
            "vin_max": vin_max, "vout": vout or None,
            "imax_in": imax_in, "imax_out": imax_out or None,
            "cost_usd": cost_usd or None, "cost_iva_rate": iva_rate,
            "notes": notes.strip() or None,
        }
        if is_edit:
            payload["id"] = existing["id"]

        exclude_id = existing["id"] if is_edit else None
        dup = _find_duplicate_equipment(list_charge_controllers(), brand, model, exclude_id=exclude_id)
        if dup:
            st.session_state["admin_cc_dup_payload"] = payload
            st.session_state["admin_cc_dup_existing"] = dup
            st.rerun()
            return

        try:
            upsert_charge_controller(payload)
            st.success("Controlador guardado." if not is_edit else "Controlador actualizado.")
            st.session_state.pop("admin_edit_cc", None)
            st.session_state.pop("admin_prefill_cc", None)
            st.session_state.pop("admin_cc_mode", None)
            _pop_cost_iva_keys(cost_key)
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")

    from database.equipment_db import upsert_charge_controller as _upsert_cc_for_confirm
    _render_duplicate_confirm("admin_cc", _upsert_cc_for_confirm, "controlador de carga")


def _charge_controllers_section() -> None:
    from database.equipment_db import list_charge_controllers, delete_charge_controller

    mode    = st.session_state.get("admin_cc_mode")   # None | "extract" | "add"
    edit_cc = st.session_state.get("admin_edit_cc")
    prefill_cc = st.session_state.get("admin_prefill_cc")

    # ── Action bar (hidden when add form is open — form has its own Cancelar) ──
    if not edit_cc and not prefill_cc:
        if mode == "extract":
            c_ext, _ = st.columns([2, 7])
            if c_ext.button("Cerrar", key="admin_cc_toggle_extract"):
                st.session_state["admin_cc_mode"] = None
                st.session_state.pop("admin_cc_variants", None)
                st.rerun()
        elif mode is None:
            c_ext, c_add, _ = st.columns([2, 2, 5])
            if c_ext.button("Extraer de datasheet", key="admin_cc_toggle_extract"):
                st.session_state["admin_cc_mode"] = "extract"
                st.rerun()
            if c_add.button("Agregar controlador de carga", key="admin_cc_toggle_add"):
                st.session_state["admin_cc_mode"] = "add"
                st.rerun()

    # ── Active form (add/extract/prefill only — edit appears inline below item) ─
    if prefill_cc:
        st.divider()
        st.markdown("##### Nuevo controlador de carga — datos del datasheet")
        _charge_controller_form(prefill=prefill_cc)
        st.divider()
    elif mode == "add":
        st.divider()
        st.markdown("##### Nuevo controlador de carga")
        _charge_controller_form()
        st.divider()
    elif mode == "extract":
        st.divider()
        st.markdown("##### Extraer especificaciones de datasheet")
        st.caption("Sube el datasheet del fabricante. La IA extrae las especificaciones técnicas.")
        pdf_file = st.file_uploader("Datasheet PDF", type=["pdf"], key="admin_cc_ds")
        if pdf_file:
            variants = st.session_state.get("admin_cc_variants")
            if st.button("Extraer especificaciones", key="admin_cc_extract"):
                with st.spinner("Analizando datasheet…"):
                    try:
                        from calculations.datasheet_parser import parse_charge_controller_datasheet
                        variants = parse_charge_controller_datasheet(pdf_file.read())
                        st.session_state["admin_cc_variants"] = variants
                    except Exception as e:
                        st.error(f"Error al procesar el datasheet: {e}")
                        variants = None
            if variants:
                if len(variants) > 1:
                    opts = [f"{v.get('brand','')} {v.get('model','')} — {v.get('imax_out','')} A" for v in variants]
                    idx = st.selectbox("Selecciona el modelo", range(len(opts)),
                                       format_func=lambda i: opts[i], key="admin_cc_var_idx")
                    selected = variants[idx]
                else:
                    selected = variants[0]
                    st.success(f"Extraído: {selected.get('brand')} {selected.get('model')}")
                if st.button("Usar estos datos →", key="admin_cc_use", type="primary"):
                    st.session_state["admin_prefill_cc"] = selected
                    st.session_state.pop("admin_edit_cc", None)
                    st.session_state.pop("admin_cc_variants", None)
                    st.session_state["admin_cc_mode"] = None
                    st.rerun()
        st.divider()

    st.markdown("#### Controladores de carga en catálogo")
    try:
        ccs = list_charge_controllers()
    except Exception as e:
        st.error(f"Error al cargar controladores: {e}")
        return

    if not ccs:
        st.info("No hay controladores de carga en el catálogo.")
        return

    h1, h2, h3, h4 = st.columns([2.3, 2.9, 1.5, 1.3])
    for hcol, label in zip([h1, h2, h3, h4], ["Controlador", "Eléctrico", "Precio (USD)", "Acciones"]):
        hcol.markdown(
            f'<span style="font-size:0.78rem;font-weight:600;color:#6b7280;'
            f'text-transform:uppercase;letter-spacing:0.04em;">{label}</span>',
            unsafe_allow_html=True,
        )
    st.divider()

    for c in ccs:
        c1, c2, c3, c4 = st.columns([2.3, 2.9, 1.5, 1.3])
        c1.markdown(
            f'<div style="line-height:1.8;">'
            f'<strong>{c["brand"]} {c["model"]}</strong><br>'
            f'<span style="background:#f1f5f9;border:1.5px solid #cbd5e1;border-radius:5px;'
            f'padding:2px 10px;font-size:0.92rem;font-weight:700;color:#1e293b;">'
            f'{c.get("type") or "—"}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        c2.markdown(
            f'<div style="font-size:0.82rem;color:#6b7280;line-height:1.8;">'
            f'Vin máx {c.get("vin_max") or "—"} V · Vout {c.get("vout") or "—"} V<br>'
            f'Imax entrada {c.get("imax_in") or "—"} A · Imax salida {c.get("imax_out") or "—"} A'
            f'</div>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f'<div style="font-size:0.92rem;padding-top:0.4rem;">${float(c.get("cost_usd") or 0):,.2f}</div>',
            unsafe_allow_html=True,
        )
        with c4:
            if st.button("Editar", key=f"ecc_{c['id']}", help="Editar", use_container_width=True):
                st.session_state["admin_edit_cc"] = c
                st.session_state["admin_cc_mode"] = None
                st.rerun()
            confirm_key = f"confirm_del_cc_{c['id']}"
            if st.button("Eliminar", key=f"dcc_{c['id']}", help="Eliminar", use_container_width=True):
                st.session_state[confirm_key] = True
                st.rerun()

        if st.session_state.get(f"confirm_del_cc_{c['id']}"):
            st.warning(f"¿Eliminar **{c['brand']} {c['model']}**? Esta acción no se puede deshacer.")
            cy, cn, _ = st.columns([1, 1, 6])
            if cy.button("Sí, eliminar", key=f"yes_del_cc_{c['id']}"):
                delete_charge_controller(c["id"])
                st.session_state.pop(f"confirm_del_cc_{c['id']}", None)
                st.rerun()
            if cn.button("Cancelar", key=f"no_del_cc_{c['id']}"):
                st.session_state.pop(f"confirm_del_cc_{c['id']}", None)
                st.rerun()

        if edit_cc and edit_cc.get("id") == c["id"]:
            st.markdown("##### Editando controlador de carga")
            _charge_controller_form(existing=edit_cc)

        st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #f1f5f9;">',
                    unsafe_allow_html=True)


def _monitoring_form(existing: dict | None = None, prefill: dict | None = None) -> None:
    """Add/edit form for a monitoring device. existing=edit mode, prefill=from datasheet."""
    src = prefill or existing or {}
    is_edit = existing is not None
    cost_key = f"admin_monitoring_cost_{existing['id']}" if is_edit else "admin_monitoring_cost_new"

    st.markdown("#### " + ("Editar equipo de monitoreo" if is_edit else "Nuevo equipo de monitoreo"))
    cost_usd, iva_rate = _cost_iva_block(cost_key, src.get("cost_usd"), src.get("cost_iva_rate") or 0.0)
    st.divider()

    with st.form(key="monitoring_form"):
        col1, col2 = st.columns(2)
        with col1:
            brand = st.text_input("Marca *", value=src.get("brand") or "")
            model = st.text_input("Modelo *", value=src.get("model") or "")
        with col2:
            compatible_with = st.text_input(
                "Compatible con", value=src.get("compatible_with") or "",
                help="Ej.: Victron Cerbo GX, Victron Ekrano GX",
            )

        notes = st.text_area("Notas", value=src.get("notes") or "", height=60)

        col_save, col_cancel = st.columns([1, 4])
        submitted = col_save.form_submit_button("Guardar", type="primary")
        cancelled = col_cancel.form_submit_button("Cancelar")

    if cancelled:
        st.session_state.pop("admin_edit_monitoring", None)
        st.session_state.pop("admin_prefill_monitoring", None)
        st.session_state.pop("admin_monitoring_mode", None)
        _pop_cost_iva_keys(cost_key)
        st.rerun()

    if submitted:
        if not brand.strip() or not model.strip():
            st.error("Marca y modelo son obligatorios.")
            return
        from database.equipment_db import upsert_monitoring_device, list_monitoring_devices
        payload = {
            "brand": brand.strip(), "model": model.strip(),
            "compatible_with": compatible_with.strip() or None,
            "cost_usd": cost_usd or None, "cost_iva_rate": iva_rate,
            "notes": notes.strip() or None,
        }
        if is_edit:
            payload["id"] = existing["id"]

        exclude_id = existing["id"] if is_edit else None
        dup = _find_duplicate_equipment(list_monitoring_devices(), brand, model, exclude_id=exclude_id)
        if dup:
            st.session_state["admin_monitoring_dup_payload"] = payload
            st.session_state["admin_monitoring_dup_existing"] = dup
            st.rerun()
            return

        try:
            upsert_monitoring_device(payload)
            st.success("Equipo de monitoreo guardado." if not is_edit else "Equipo de monitoreo actualizado.")
            st.session_state.pop("admin_edit_monitoring", None)
            st.session_state.pop("admin_prefill_monitoring", None)
            st.session_state.pop("admin_monitoring_mode", None)
            _pop_cost_iva_keys(cost_key)
            st.rerun()
        except Exception as e:
            st.error(f"Error al guardar: {e}")

    from database.equipment_db import upsert_monitoring_device as _upsert_monitoring_for_confirm
    _render_duplicate_confirm("admin_monitoring", _upsert_monitoring_for_confirm, "equipo de monitoreo")


def _monitoring_section() -> None:
    from database.equipment_db import list_monitoring_devices, delete_monitoring_device

    mode     = st.session_state.get("admin_monitoring_mode")   # None | "extract" | "add"
    edit_mon = st.session_state.get("admin_edit_monitoring")
    prefill_mon = st.session_state.get("admin_prefill_monitoring")

    # ── Action bar (hidden when add form is open — form has its own Cancelar) ──
    if not edit_mon and not prefill_mon:
        if mode == "extract":
            c_ext, _ = st.columns([2, 7])
            if c_ext.button("Cerrar", key="admin_monitoring_toggle_extract"):
                st.session_state["admin_monitoring_mode"] = None
                st.session_state.pop("admin_monitoring_variants", None)
                st.rerun()
        elif mode is None:
            c_ext, c_add, _ = st.columns([2, 2, 5])
            if c_ext.button("Extraer de datasheet", key="admin_monitoring_toggle_extract"):
                st.session_state["admin_monitoring_mode"] = "extract"
                st.rerun()
            if c_add.button("Agregar equipo de monitoreo", key="admin_monitoring_toggle_add"):
                st.session_state["admin_monitoring_mode"] = "add"
                st.rerun()

    # ── Active form (add/extract/prefill only — edit appears inline below item) ─
    if prefill_mon:
        st.divider()
        st.markdown("##### Nuevo equipo de monitoreo — datos del datasheet")
        _monitoring_form(prefill=prefill_mon)
        st.divider()
    elif mode == "add":
        st.divider()
        st.markdown("##### Nuevo equipo de monitoreo")
        _monitoring_form()
        st.divider()
    elif mode == "extract":
        st.divider()
        st.markdown("##### Extraer especificaciones de datasheet")
        st.caption("Sube el datasheet del fabricante. La IA extrae las especificaciones técnicas.")
        pdf_file = st.file_uploader("Datasheet PDF", type=["pdf"], key="admin_monitoring_ds")
        if pdf_file:
            variants = st.session_state.get("admin_monitoring_variants")
            if st.button("Extraer especificaciones", key="admin_monitoring_extract"):
                with st.spinner("Analizando datasheet…"):
                    try:
                        from calculations.datasheet_parser import parse_monitoring_datasheet
                        variants = parse_monitoring_datasheet(pdf_file.read())
                        st.session_state["admin_monitoring_variants"] = variants
                    except Exception as e:
                        st.error(f"Error al procesar el datasheet: {e}")
                        variants = None
            if variants:
                if len(variants) > 1:
                    opts = [f"{v.get('brand','')} {v.get('model','')}" for v in variants]
                    idx = st.selectbox("Selecciona el modelo", range(len(opts)),
                                       format_func=lambda i: opts[i], key="admin_monitoring_var_idx")
                    selected = variants[idx]
                else:
                    selected = variants[0]
                    st.success(f"Extraído: {selected.get('brand')} {selected.get('model')}")
                if st.button("Usar estos datos →", key="admin_monitoring_use", type="primary"):
                    st.session_state["admin_prefill_monitoring"] = selected
                    st.session_state.pop("admin_edit_monitoring", None)
                    st.session_state.pop("admin_monitoring_variants", None)
                    st.session_state["admin_monitoring_mode"] = None
                    st.rerun()
        st.divider()

    st.markdown("#### Equipos de monitoreo en catálogo")
    try:
        devices = list_monitoring_devices()
    except Exception as e:
        st.error(f"Error al cargar equipos de monitoreo: {e}")
        return

    if not devices:
        st.info("No hay equipos de monitoreo en el catálogo.")
        return

    h1, h2, h3 = st.columns([3.2, 2.8, 1.5])
    for hcol, label in zip([h1, h2, h3], ["Equipo", "Precio (USD)", "Acciones"]):
        hcol.markdown(
            f'<span style="font-size:0.78rem;font-weight:600;color:#6b7280;'
            f'text-transform:uppercase;letter-spacing:0.04em;">{label}</span>',
            unsafe_allow_html=True,
        )
    st.divider()

    for m in devices:
        c1, c2, c3 = st.columns([3.2, 2.8, 1.5])
        c1.markdown(
            f'<div style="line-height:1.8;">'
            f'<strong>{m["brand"]} {m["model"]}</strong><br>'
            f'<span style="font-size:0.8rem;color:#6b7280;">Compatible con: {m.get("compatible_with") or "—"}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        c2.markdown(
            f'<div style="font-size:0.92rem;padding-top:0.4rem;">${float(m.get("cost_usd") or 0):,.2f}</div>',
            unsafe_allow_html=True,
        )
        with c3:
            if st.button("Editar", key=f"em_{m['id']}", help="Editar", use_container_width=True):
                st.session_state["admin_edit_monitoring"] = m
                st.session_state["admin_monitoring_mode"] = None
                st.rerun()
            confirm_key = f"confirm_del_monitoring_{m['id']}"
            if st.button("Eliminar", key=f"dm_{m['id']}", help="Eliminar", use_container_width=True):
                st.session_state[confirm_key] = True
                st.rerun()

        if st.session_state.get(f"confirm_del_monitoring_{m['id']}"):
            st.warning(f"¿Eliminar **{m['brand']} {m['model']}**? Esta acción no se puede deshacer.")
            cy, cn, _ = st.columns([1, 1, 6])
            if cy.button("Sí, eliminar", key=f"yes_del_monitoring_{m['id']}"):
                delete_monitoring_device(m["id"])
                st.session_state.pop(f"confirm_del_monitoring_{m['id']}", None)
                st.rerun()
            if cn.button("Cancelar", key=f"no_del_monitoring_{m['id']}"):
                st.session_state.pop(f"confirm_del_monitoring_{m['id']}", None)
                st.rerun()

        if edit_mon and edit_mon.get("id") == m["id"]:
            st.markdown("##### Editando equipo de monitoreo")
            _monitoring_form(existing=edit_mon)

        st.markdown('<hr style="margin:4px 0;border:none;border-top:1px solid #f1f5f9;">',
                    unsafe_allow_html=True)


def _equipment_catalog() -> None:
    tab_panels, tab_inverters, tab_batteries, tab_cc, tab_monitoring = st.tabs([
        "Paneles solares", "Inversores", "Baterías", "Controladores de carga", "Monitoreo",
    ])
    with tab_panels:
        _panels_section()
    with tab_inverters:
        _inverters_section()
    with tab_batteries:
        _batteries_section()
    with tab_cc:
        _charge_controllers_section()
    with tab_monitoring:
        _monitoring_section()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.markdown(
        '<p style="color:#1E2D54;font-size:1.4rem;font-weight:700;margin:0;">Administración</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    tab_equip, tab_services, tab_aresep, tab_clients = st.tabs([
        "Catálogo de equipos",
        "Servicios",
        "Tarifas ARESEP",
        "Clientes",
    ])

    with tab_equip:
        _equipment_catalog()

    with tab_services:
        _services_section()

    with tab_aresep:
        sub_update, sub_view = st.tabs(["Actualizar tarifas", "Tarifas actuales"])
        with sub_update:
            _tariff_updater()
        with sub_view:
            _current_tariffs()

    with tab_clients:
        sub_clients, sub_prospects = st.tabs(["Clientes", "Prospectos"])
        with sub_clients:
            _clients_section()
        with sub_prospects:
            _prospects_section()


main()
