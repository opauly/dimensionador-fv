"""VRM Monitor — customer sites, CSV ingestion, and weekly reports.

Operator-facing side of the VRM report product. Three tabs:

  Sitios    — customers and their sites (the `vrm` schema)
  Cargar    — upload a VRM CSV export, preview it, then ingest
  Reporte   — render the weekly PDF from `vrm` or `monitoring`

Reads go through `database/vrm_report_db.py`, which is schema-agnostic, so the
Reporte tab can also render Pauly & Co's own Node-RED sites out of `monitoring`
— useful for comparing the two ingestion paths against each other.

Plan and design notes: victron-monitor/docs/vrm-report-v1-implementation-plan.md
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from config import BRAND_GREEN, BRAND_GREEN_LIGHT  # noqa: E402
from database import vrm_report_db as rdb  # noqa: E402
from victron import ingest, vrm_csv, weekly_report as wr  # noqa: E402

st.set_page_config(page_title="VRM Monitor — Pauly&Co Solar", layout="wide")

SYSTEM_TYPES = ["hybrid", "off_grid", "grid_zero"]
LANGS = {"es": "Español", "en": "English"}


def _flash(msg: str, kind: str = "success") -> None:
    getattr(st, kind)(msg)


@st.cache_data(ttl=30)
def _customers() -> list[dict]:
    from database.supabase_client import get_client
    return (get_client().schema("vrm").table("customers").select("*")
            .order("name").execute().data or [])


@st.cache_data(ttl=30)
def _sites(schema: str) -> list[dict]:
    return rdb.list_sites(schema, active_only=False)


def _clear_caches() -> None:
    _customers.clear()
    _sites.clear()


# ══════════════════════════════════════════════════════════════════
# Tab 1 — Sitios
# ══════════════════════════════════════════════════════════════════
def tab_sites() -> None:
    st.markdown("### Clientes y sitios")
    st.caption(
        "Clientes externos del producto VRM. Es un esquema aparte de `clients` "
        "(el CRM de Pauly & Co) y del esquema `monitoring` de los sitios propios."
    )

    customers = _customers()
    sites = _sites("vrm")

    c1, c2 = st.columns(2)
    c1.metric("Clientes", len(customers))
    c2.metric("Sitios", len(sites))

    if sites:
        by_customer = {c["id"]: c["name"] for c in customers}
        df = pd.DataFrame([{
            "Cliente": by_customer.get(s.get("customer_id"), "—"),
            "Sitio": s["display_name"],
            "site_id": s["site_id"],
            "Instalación VRM": s.get("vrm_installation_id") or "—",
            "Tipo": s.get("system_type"),
            "kWp": s.get("pv_kwp"),
            "Batería kWh": s.get("battery_usable_kwh"),
            "Idioma": s.get("report_language"),
            "Activo": "Sí" if s.get("active") else "No",
        } for s in sites])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Todavía no hay sitios. Se crean automáticamente al cargar un CSV.")

    with st.expander("➕ Crear o actualizar un sitio manualmente"):
        st.caption(
            "No es obligatorio: la pestaña **Cargar** crea el cliente y el sitio "
            "a partir del CSV. Esto sirve para corregir datos después."
        )
        with st.form("vrm_site_form"):
            a, b = st.columns(2)
            cust_name = a.text_input("Cliente", placeholder="Vista Atenas")
            site_name = b.text_input("Sitio", placeholder="2 Floor Pool")
            a, b, c = st.columns(3)
            pv_kwp = a.number_input("Potencia FV (kWp)", min_value=0.0, step=0.1, value=0.0)
            batt = b.number_input("Batería utilizable (kWh)", min_value=0.0, step=0.1, value=0.0)
            stype = c.selectbox("Tipo de sistema", SYSTEM_TYPES)
            a, b, c = st.columns(3)
            lang = a.selectbox("Idioma del reporte", list(LANGS), format_func=LANGS.get)
            location = b.text_input("Ubicación", placeholder="Atenas, Alajuela")
            tz = c.text_input("Zona horaria", value="America/Costa_Rica")
            a, b = st.columns(2)
            lat = a.number_input("Latitud", value=0.0, format="%.6f")
            lng = b.number_input("Longitud", value=0.0, format="%.6f")

            if st.form_submit_button("Guardar", type="primary"):
                if not cust_name.strip() or not site_name.strip():
                    st.error("Cliente y sitio son obligatorios.")
                else:
                    try:
                        cust = ingest.upsert_customer(cust_name.strip())
                        site_id = ingest.make_site_id(cust["slug"], site_name.strip())
                        ingest.upsert_site(
                            cust["id"], site_id, site_name.strip(),
                            pv_kwp=pv_kwp or None,
                            battery_usable_kwh=batt or None,
                            system_type=stype, report_language=lang,
                            location=location or None, timezone=tz or "America/Costa_Rica",
                            # Weather (and therefore the performance ratio) needs
                            # coordinates; 0,0 is Null Island, not "unknown".
                            latitude=lat or None, longitude=lng or None,
                        )
                        _clear_caches()
                        _flash(f"Sitio guardado: `{site_id}`")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"No se pudo guardar: {exc}")


# ══════════════════════════════════════════════════════════════════
# Tab 2 — Cargar CSV
# ══════════════════════════════════════════════════════════════════
def tab_upload() -> None:
    st.markdown("### Cargar exportación CSV de VRM")
    st.caption(
        "Exportá el log desde el portal VRM (Advanced → Download) y subilo acá. "
        "El archivo se procesa y se muestra un resumen **antes** de escribir nada "
        "en la base de datos."
    )

    a, b = st.columns(2)
    cust_name = a.text_input("Cliente", key="up_cust", placeholder="Vista Atenas")
    site_name = b.text_input("Sitio", key="up_site", placeholder="2 Floor Pool")
    a, b, c = st.columns(3)
    pv_kwp = a.number_input("Potencia FV (kWp)", min_value=0.0, step=0.1, key="up_kwp")
    batt = b.number_input("Batería utilizable (kWh)", min_value=0.0, step=0.1, key="up_batt")
    stype = c.selectbox("Tipo de sistema", SYSTEM_TYPES, key="up_type")

    up = st.file_uploader("Archivo CSV de VRM", type=["csv"], key="up_file")
    st.caption("Límite de carga: 200 MB (una exportación de ~80 días pesa ~140 MB).")

    if up is None:
        return

    if st.button("🔍 Procesar y previsualizar", type="primary"):
        if not cust_name.strip() or not site_name.strip():
            st.error("Indicá cliente y sitio antes de procesar.")
            return
        with st.spinner("Procesando el CSV…"):
            try:
                slug = ingest.slugify(cust_name)
                site_id = ingest.make_site_id(slug, site_name)
                parsed = vrm_csv.parse_export(
                    up, site_id=site_id, filename=up.name,
                    pv_kwp=pv_kwp or None, battery_usable_kwh=batt or None,
                )
            except vrm_csv.VrmCsvError as exc:
                st.error(f"El archivo no es una exportación de VRM válida: {exc}")
                return
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo procesar: {exc}")
                return
        st.session_state["vrm_parsed"] = parsed
        st.session_state["vrm_parsed_meta"] = {
            "customer": cust_name.strip(), "site": site_name.strip(),
            "filename": up.name, "pv_kwp": pv_kwp or None,
            "battery_usable_kwh": batt or None, "system_type": stype,
        }

    parsed = st.session_state.get("vrm_parsed")
    if not parsed:
        return

    meta = st.session_state["vrm_parsed_meta"]
    st.divider()
    st.markdown("#### Resumen de lo que se va a importar")

    a, b, c, d = st.columns(4)
    a.metric("Días", len(parsed["rows"]))
    b.metric("Muestras", f"{parsed['sample_count']:,}")
    c.metric("Eventos de alarma", len(parsed["alarm_events"]))
    d.metric("Cortes de red", len(parsed["outages"]))
    st.caption(
        f"Instalación VRM **{parsed['installation_id'] or '—'}** · periodo "
        f"{parsed['period_start'][:10]} → {parsed['period_end'][:10]} · "
        f"zona horaria del archivo: {parsed['timezone_label']}"
    )

    for w in parsed["warnings"]:
        st.warning(w)

    rows = pd.DataFrame(parsed["rows"])
    show = ["date", "pv_kwh", "load_kwh", "grid_kwh", "battery_charge_kwh",
            "battery_discharge_kwh", "min_soc", "max_soc", "outage_count",
            "outage_minutes", "hours_covered", "complete_day"]
    st.dataframe(rows[[c for c in show if c in rows.columns]],
                 use_container_width=True, hide_index=True, height=280)

    partial = int((~rows["complete_day"]).sum()) if "complete_day" in rows else 0
    if partial:
        st.info(
            f"{partial} día(s) parcial(es) — normalmente el primero y el último "
            "del archivo. Se guardan igual, marcados como incompletos, para que "
            "el reporte pueda excluirlos en vez de mostrarlos como días de baja "
            "generación."
        )

    if st.button("💾 Importar a la base de datos", type="primary"):
        with st.spinner("Escribiendo…"):
            try:
                cust = ingest.upsert_customer(meta["customer"])
                site_id = ingest.make_site_id(cust["slug"], meta["site"])
                fields = {"pv_kwp": meta["pv_kwp"],
                          "battery_usable_kwh": meta["battery_usable_kwh"],
                          "system_type": meta["system_type"]}
                if parsed.get("installation_id"):
                    fields["vrm_installation_id"] = int(parsed["installation_id"])
                ingest.upsert_site(cust["id"], site_id, meta["site"], **fields)
                summary = ingest.ingest_parsed(parsed, site_id,
                                               filename=meta["filename"])
            except Exception as exc:  # noqa: BLE001
                st.error(f"Falló la importación: {exc}")
                return
        _clear_caches()
        st.session_state.pop("vrm_parsed", None)
        _flash(
            f"Importados {summary['rows_written']} días y "
            f"{summary['alarm_events_written']} eventos de alarma en `{site_id}`."
        )
        st.info("Ya podés generar el reporte en la pestaña **Reporte**.")


# ══════════════════════════════════════════════════════════════════
# Tab 3 — Reporte
# ══════════════════════════════════════════════════════════════════
def tab_report() -> None:
    st.markdown("### Reporte semanal")
    st.caption(
        "El mismo generador sirve para los dos esquemas: `vrm` (clientes "
        "externos, desde CSV) y `monitoring` (sitios propios con Cerbo GX y "
        "Node-RED). Útil para comparar ambas rutas sobre el mismo sitio."
    )

    a, b = st.columns([1, 2])
    schema = a.radio("Origen", [rdb.VRM, rdb.MONITORING], horizontal=True,
                     format_func=lambda s: ("vrm — clientes externos"
                                            if s == rdb.VRM
                                            else "monitoring — sitios propios"))
    sites = _sites(schema)
    if not sites:
        st.info(f"No hay sitios en el esquema `{schema}`.")
        return

    labels = {s["site_id"]: f"{s['display_name']} ({s['site_id']})" for s in sites}
    site_id = b.selectbox("Sitio", list(labels), format_func=labels.get)

    dates = rdb.get_available_dates(site_id, schema)
    if not dates:
        st.warning("Ese sitio todavía no tiene datos diarios.")
        return

    st.caption(f"Datos disponibles: **{dates[0]} → {dates[-1]}** ({len(dates)} días)")

    a, b = st.columns([1, 2])
    # Only dates that actually have data — a free date input would happily
    # produce an empty report for a week nobody has data for.
    week_ending = a.selectbox("Semana que termina el", list(reversed(dates)))
    opts = b.multiselect("Incluir", ["Narrativa (IA)", "Clima (Open-Meteo)"],
                         default=["Narrativa (IA)", "Clima (Open-Meteo)"])

    start = (date.fromisoformat(week_ending) - timedelta(days=6)).isoformat()
    covered = [d for d in dates if start <= d <= week_ending]
    if len(covered) < 7:
        st.warning(
            f"La semana {start} → {week_ending} tiene {len(covered)} de 7 días "
            "con datos. El reporte se genera igual, pero los totales no son "
            "comparables con una semana completa."
        )

    if st.button("📄 Generar reporte", type="primary"):
        with st.spinner("Generando…"):
            try:
                data = wr.build_report_data(
                    site_id, week_ending, schema,
                    with_narrative="Narrativa (IA)" in opts,
                    with_weather="Clima (Open-Meteo)" in opts,
                )
                pdf = wr.render_pdf(data)
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo generar el reporte: {exc}")
                return
        st.session_state["vrm_report"] = {
            "pdf": pdf, "data": data,
            "name": f"Weekly Report - {data['siteName']} - {data['endStr']}.pdf",
        }

    rep = st.session_state.get("vrm_report")
    if not rep:
        return

    d = rep["data"]
    st.divider()
    a, b, c, e = st.columns(4)
    a.metric("Generación solar", f"{d['totals']['pv']:.1f} kWh")
    b.metric("Consumo", f"{d['totals']['load']:.1f} kWh")
    c.metric("Independencia", f"{d['gridIndependencePct']}%")
    e.metric("Salud", f"{d['avgHealth']}/100", d["healthStatus"])
    st.caption(f"Periodo {d['startStr']} → {d['endStr']} · "
               f"{len(d['dailyGrouped'])} días · esquema `{d['schema']}`")

    st.download_button("⬇️ Descargar PDF", data=rep["pdf"],
                       file_name=rep["name"], mime="application/pdf",
                       type="primary")


# ══════════════════════════════════════════════════════════════════
st.markdown(
    f"<h2 style='margin-bottom:2px'>VRM Monitor</h2>"
    f"<div style='color:#6b7280;margin-bottom:18px'>Reportes semanales para "
    f"clientes externos, desde exportaciones CSV de Victron VRM</div>",
    unsafe_allow_html=True,
)

t1, t2, t3 = st.tabs(["🏠 Sitios", "📤 Cargar CSV", "📄 Reporte"])
with t1:
    tab_sites()
with t2:
    tab_upload()
with t3:
    tab_report()
