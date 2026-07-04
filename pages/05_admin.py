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


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.markdown(
        '<p style="color:#1E2D54;font-size:1.4rem;font-weight:700;margin:0;">Administración</p>',
        unsafe_allow_html=True,
    )
    st.divider()

    tab_update, tab_view = st.tabs(["📤 Actualizar tarifas ARESEP", "📋 Tarifas actuales"])

    with tab_update:
        _tariff_updater()

    with tab_view:
        _current_tariffs()


main()
