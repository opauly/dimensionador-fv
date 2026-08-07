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

from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from config import BRAND_GREEN, BRAND_GREEN_LIGHT, BRAND_NAVY, COUNTRIES  # noqa: E402
from database import vrm_report_db as rdb  # noqa: E402
from victron import ingest, vrm_csv, weekly_report as wr  # noqa: E402
from victron import report_svg as rsvg  # noqa: E402
from victron import savings as vrm_savings  # noqa: E402

st.set_page_config(page_title="VRM Monitor — Pauly&Co Solar", layout="wide")

# ══════════════════════════════════════════════════════════════════
# Small visual-insight components — same style as wizard/off_grid.py's
# _metric_card()/_chip_row() (CONTEXT.md 2026-08-03), so the operator's quick
# look here reads like the proposal wizard's review step instead of the bare
# st.metric row it replaces. Kept local rather than imported: those are
# private, wizard-scoped helpers for an unrelated feature.
# ══════════════════════════════════════════════════════════════════
def _metric_card(label: str, value: str, sublabel: str | None = None,
                 color: str = BRAND_NAVY) -> None:
    sub_html = (f'<div style="font-size:0.75rem;color:#6b7280;margin-top:2pt;">'
               f'{sublabel}</div>' if sublabel else "")
    st.markdown(
        f'<div style="border:1px solid #e5e7eb;border-radius:8px;padding:0.7rem 0.9rem;'
        f'margin-bottom:0.5rem;min-height:5.5rem;">'
        f'<div style="font-size:0.78rem;color:#6b7280;">{label}</div>'
        f'<div style="font-size:1.4rem;font-weight:700;color:{color};margin-top:1pt;">{value}</div>'
        f'{sub_html}</div>',
        unsafe_allow_html=True,
    )


def _chip_row(chips: list[str]) -> None:
    spans = "".join(
        f'<span style="background:#f1f5f9;border:1px solid #cbd5e1;border-radius:4px;'
        f'padding:2px 9px;font-size:0.8rem;">{c}</span>' for c in chips)
    st.markdown(f'<div style="display:flex;gap:0.5rem;flex-wrap:wrap;'
               f'margin:0.4rem 0 0.9rem;">{spans}</div>', unsafe_allow_html=True)


SYSTEM_TYPES = ["hybrid", "off_grid", "grid_zero"]
LANGS = {"es": "Español", "en": "English"}
_COUNTRY_CODES = list(COUNTRIES)
_DEFAULT_COUNTRY_IDX = _COUNTRY_CODES.index("CR")


@st.cache_data(ttl=3600)
def _timezones() -> list[str]:
    """Full IANA list — searchable via Streamlit's selectbox filter-as-you-type,
    so 598 entries is navigable despite not being curated. Falls back to a
    short common list if the host has no tz database (zoneinfo needs one; not
    expected on this machine, but the report tool must not crash without it)."""
    try:
        from zoneinfo import available_timezones
        return sorted(available_timezones())
    except Exception:  # noqa: BLE001
        return ["America/Costa_Rica", "America/New_York", "America/Mexico_City",
                "America/Bogota", "America/Sao_Paulo", "Europe/Madrid", "UTC"]


def _tz_index(tz_list: list[str], default: str = "America/Costa_Rica") -> int:
    try:
        return tz_list.index(default)
    except ValueError:
        return 0


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
            "País": s.get("country") or "CR",
            "Tarifa ahorro": (f"{s['savings_rate']} {s['savings_currency']}"
                             if s.get("savings_rate") else "—"),
            "Activo": "Sí" if s.get("active") else "No",
        } for s in sites])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Todavía no hay sitios. Se crean automáticamente al cargar un CSV.")

    with st.expander("Crear o actualizar un sitio manualmente"):
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
            tz_list = _timezones()
            tz = c.selectbox("Zona horaria", tz_list, index=_tz_index(tz_list))
            a, b, c = st.columns(3)
            lat = a.number_input("Latitud", value=0.0, format="%.6f")
            lng = b.number_input("Longitud", value=0.0, format="%.6f")
            country = c.selectbox(
                "País", _COUNTRY_CODES, format_func=lambda k: COUNTRIES[k],
                index=_DEFAULT_COUNTRY_IDX,
                help="CR calcula el ahorro con tarifas ARESEP; cualquier otro "
                     "país usa la tarifa fija de abajo.")
            a, b = st.columns(2)
            savings_rate = a.number_input("Tarifa de ahorro (por kWh)", min_value=0.0,
                                          step=0.01, format="%.4f",
                                          help="Solo se usa si País no es CR.")
            savings_currency = b.selectbox("Moneda", vrm_savings.SUPPORTED_FLAT_CURRENCIES)

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
                            country=(country or "CR").strip().upper() or "CR",
                            savings_rate=savings_rate or None,
                            savings_currency=savings_currency if savings_rate else None,
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

    # A geocode button's on_click code runs AFTER the widgets below have already
    # rendered in that same script pass, so it cannot write st.session_state["up_loc"]
    # etc. directly — Streamlit raises StreamlitAPIException for that. Instead the
    # button stages the new value under a "_pending_" key and reruns; this block,
    # which runs before any of those widgets are instantiated, consumes the staged
    # value into the widget's real key. Same pattern CONTEXT.md documents for the
    # wizard's versioned-key resets, applied here without needing a version counter
    # since these are single-shot overwrites, not list resets.
    for pending, real in [("_up_pending_lat", "up_lat"), ("_up_pending_lng", "up_lng"),
                          ("_up_pending_loc", "up_loc"), ("_up_pending_country", "up_country"),
                          ("_up_pending_tz", "up_tz")]:
        if pending in st.session_state:
            st.session_state[real] = st.session_state.pop(pending)

    a, b = st.columns(2)
    cust_name = a.text_input("Cliente", key="up_cust", placeholder="Vista Atenas")
    site_name = b.text_input("Sitio", key="up_site", placeholder="2 Floor Pool")
    a, b, c, d = st.columns(4)
    pv_kwp = a.number_input("Potencia FV (kWp)", min_value=0.0, step=0.1, key="up_kwp")
    batt = b.number_input("Batería utilizable (kWh)", min_value=0.0, step=0.1, key="up_batt")
    stype = c.selectbox("Tipo de sistema", SYSTEM_TYPES, key="up_type")
    lang = d.selectbox("Idioma del reporte", list(LANGS), format_func=LANGS.get,
                       key="up_lang")

    # Location drives the Open-Meteo call, which in turn drives the weather
    # block AND the expected-output figure behind the performance ratio.
    # Without coordinates the report falls back to a flat 4.5 peak-sun-hours
    # assumption, and the "ratio" degenerates into actual-vs-assumption.
    st.markdown("##### Ubicación")
    st.caption(
        "Necesaria para el clima y el índice de rendimiento. Ingresá "
        "Latitud/Longitud (de Google Maps o el instalador) y usá el botón "
        "para completar Ubicación, Zona horaria y País automáticamente — "
        "funciona en cualquier país. Los tres campos siguen siendo editables "
        "a mano si hace falta corregir algo."
    )
    tz_list = _timezones()
    a, b, c = st.columns([1, 1, 1.3])
    lat = a.number_input("Latitud", value=0.0, format="%.6f", key="up_lat")
    lng = b.number_input("Longitud", value=0.0, format="%.6f", key="up_lng")
    with c:
        st.write("")
        if st.button("Buscar por coordenadas", key="up_revgeo",
                     help="Completa Ubicación, Zona horaria y País a partir "
                          "de Latitud/Longitud — cualquier país."):
            if not lat and not lng:
                st.warning("Ingresá latitud y longitud primero.")
            else:
                from calculations.pvgis import reverse_geocode
                got = reverse_geocode(lat, lng)
                if not got:
                    st.warning("No se pudo resolver esas coordenadas.")
                else:
                    if got.get("location"):
                        st.session_state["_up_pending_loc"] = got["location"]
                    if got.get("timezone") in tz_list:
                        st.session_state["_up_pending_tz"] = got["timezone"]
                    code = got.get("country_code")
                    if code and code in COUNTRIES:
                        st.session_state["_up_pending_country"] = code
                    elif code:
                        st.warning(f"País detectado ({code}) no está en la "
                                   f"lista — seleccionalo manualmente.")
                    st.rerun()

    a, b, c = st.columns([2, 1, 1])
    location = a.text_input("Ubicación", key="up_loc",
                            placeholder="Atenas, Alajuela")
    # `index=` is only a first-render default. Once the reverse-geocode button
    # has staged a value into session_state (see the pending-key block above),
    # passing `index=` again on top of that makes Streamlit warn — "created
    # with a default value but also had its value set via the Session State
    # API" — even though it still resolves correctly. Omitting it once the key
    # already governs the widget avoids the warning outright.
    tz_kwargs = {} if "up_tz" in st.session_state else {"index": _tz_index(tz_list)}
    tz = b.selectbox("Zona horaria", tz_list, key="up_tz", **tz_kwargs)
    country_kwargs = ({} if "up_country" in st.session_state
                      else {"index": _DEFAULT_COUNTRY_IDX})
    country = c.selectbox(
        "País", _COUNTRY_CODES, format_func=lambda k: COUNTRIES[k], key="up_country",
        help="Determina cómo se estima el ahorro: Costa Rica usa tarifas "
             "ARESEP automáticamente; cualquier otro país usa la tarifa fija "
             "de abajo.",
        **country_kwargs,
    )

    # No electric-company picker anywhere — Costa Rica needs none (blended
    # ARESEP average, computed automatically from `país`), and everywhere else
    # gets one flat rate typed in once, not a distributor list.
    st.markdown("##### Ahorro estimado")
    if stype == "off_grid":
        st.caption(
            "Este sitio es off-grid: no tiene conexión a la red. El reporte "
            "mostrará el ahorro como una cifra hipotética — lo que se habría "
            "pagado por esta energía si el sitio estuviera conectado a la "
            "red, no un ahorro sobre una factura real."
        )
    else:
        st.caption(
            "Para sitios en Costa Rica (país = CR) el ahorro se calcula solo, "
            "con el promedio de tarifas ARESEP T-RE — no hace falta indicar "
            "nada más acá. Para cualquier otro país, indicá una tarifa fija; "
            "si se deja en 0, el reporte no muestra una cifra de ahorro en "
            "vez de inventar una."
        )
    a, b = st.columns(2)
    savings_rate = a.number_input("Tarifa (por kWh)", min_value=0.0, step=0.01,
                                  format="%.4f", key="up_rate")
    savings_currency = b.selectbox("Moneda", vrm_savings.SUPPORTED_FLAT_CURRENCIES,
                                   key="up_currency")

    exports = st.checkbox(
        "Este sistema exporta energía a la red",
        key="up_export",
        help=(
            "Los sistemas híbridos/ESS con inyección envían excedente a la red "
            "(lecturas negativas de Grid L1/L2). Actívalo para que el reporte "
            "muestre la energía exportada. El consumo de red siempre se mide "
            "solo como importación."
        ),
    )

    up = st.file_uploader("Archivo CSV de VRM", type=["csv"], key="up_file")
    st.caption("Límite de carga: 200 MB (una exportación de ~80 días pesa ~140 MB).")

    if up is None:
        return

    if st.button("Procesar y previsualizar", type="primary"):
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
            "report_language": lang,
            "location": location or None, "timezone": tz or "America/Costa_Rica",
            # 0,0 is Null Island, not "unknown" — store NULL so the report can
            # tell the difference and say weather is unavailable.
            "latitude": lat or None, "longitude": lng or None,
            "exports_to_grid": exports,
            "country": (country or "CR").strip().upper() or "CR",
            "savings_rate": savings_rate or None,
            "savings_currency": savings_currency if savings_rate else None,
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
        f"zona horaria del archivo: {parsed['timezone_label']} · "
        f"reporte en **{LANGS.get(meta['report_language'], meta['report_language'])}**"
    )
    _og_note = " (hipotético — sitio off-grid)" if meta["system_type"] == "off_grid" else ""
    if meta["country"] == "CR":
        st.caption(f"Ahorro estimado: automático, promedio de tarifas ARESEP T-RE{_og_note}.")
    elif meta["savings_rate"]:
        st.caption(
            f"Ahorro estimado: tarifa fija "
            f"{vrm_savings.format_money(meta['savings_rate'], meta['savings_currency'])}"
            f"/kWh{_og_note}."
        )
    else:
        st.caption("Ahorro estimado: no se mostrará (país no-CR sin tarifa configurada).")

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

    if st.button("Importar a la base de datos", type="primary"):
        with st.spinner("Escribiendo…"):
            try:
                cust = ingest.upsert_customer(meta["customer"])
                site_id = ingest.make_site_id(cust["slug"], meta["site"])
                fields = {"pv_kwp": meta["pv_kwp"],
                          "battery_usable_kwh": meta["battery_usable_kwh"],
                          "system_type": meta["system_type"],
                          "report_language": meta["report_language"],
                          "location": meta["location"],
                          "timezone": meta["timezone"],
                          "latitude": meta["latitude"],
                          "longitude": meta["longitude"],
                          "exports_to_grid": meta["exports_to_grid"],
                          "country": meta["country"],
                          "savings_rate": meta["savings_rate"],
                          "savings_currency": meta["savings_currency"]}
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
    st.markdown("### Reporte")
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

    min_d, max_d = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    valid = True
    if schema == rdb.MONITORING:
        # Unchanged: monitoring's report stays a fixed automatic 7-day
        # window, picked by its end date only — this is the UI that was
        # already calibrated against the reference PDF. A calendar rather
        # than a dropdown of exact dates — monitoring data is written daily
        # by Node-RED, so gap days inside the picked week are rare, and the
        # coverage warning below still catches it when one shows up.
        a, b = st.columns([1, 2])
        week_ending = a.date_input("Semana que termina el", value=max_d,
                                   min_value=min_d, max_value=max_d).isoformat()
        opts = b.multiselect("Incluir", ["Narrativa (IA)", "Clima (Open-Meteo)"],
                             default=["Narrativa (IA)", "Clima (Open-Meteo)"])
        start, end = rdb.week_bounds(week_ending)
        start, end = start.isoformat(), end.isoformat()
        covered = [d for d in dates if start <= d <= end]
        if len(covered) < 7:
            st.warning(
                f"La semana {start} → {end} tiene {len(covered)} de 7 días "
                "con datos. El reporte se genera igual, pero los totales no "
                "son comparables con una semana completa."
            )
    else:
        # vrm: operator picks any [start, end] up to MAX_CUSTOM_RANGE_DAYS, one
        # calendar with range selection bounded to the site's real data span.
        # A calendar can't restrict individual days to only the ones with
        # data the way the old date-dropdowns did, but a sparse or fully
        # empty pick is already handled below (coverage warning) and in the
        # generate handler (caught exception) — so that's not a new gap
        # (plan doc §21, Phase A).
        default_start = dates[max(0, len(dates) - 7)]
        picked = st.date_input(
            "Rango del reporte", value=(date.fromisoformat(default_start), max_d),
            min_value=min_d, max_value=max_d,
        )
        opts = st.multiselect("Incluir", ["Narrativa (IA)", "Clima (Open-Meteo)"],
                              default=["Narrativa (IA)", "Clima (Open-Meteo)"])

        if not isinstance(picked, tuple) or len(picked) != 2:
            st.info("Elegí una fecha de inicio y una de fin en el calendario.")
            valid = False
            start = end = None
        else:
            start, end = (d.isoformat() for d in picked)
            num_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
            if num_days > rdb.MAX_CUSTOM_RANGE_DAYS:
                st.error(
                    f"El rango elegido es de {num_days} días; el máximo para "
                    f"este reporte es {rdb.MAX_CUSTOM_RANGE_DAYS}. Elegí un "
                    "rango más corto."
                )
                valid = False
            else:
                covered = [d for d in dates if start <= d <= end]
                if len(covered) < num_days:
                    st.warning(
                        f"El rango {start} → {end} tiene {len(covered)} de "
                        f"{num_days} días con datos. El reporte se genera "
                        "igual, pero los totales no son comparables con un "
                        "rango completo."
                    )

    if valid and st.button("Generar reporte", type="primary"):
        with st.spinner("Generando…"):
            try:
                data = wr.build_report_data(
                    site_id, start, end, schema,
                    with_narrative="Narrativa (IA)" in opts,
                    with_weather="Clima (Open-Meteo)" in opts,
                )
                pdf = wr.render_pdf(data)
            except Exception as exc:  # noqa: BLE001
                st.error(f"No se pudo generar el reporte: {exc}")
                return
        st.session_state["vrm_report"] = {
            "pdf": pdf, "data": data,
            "name": f"Report - {data['siteName']} - {data['endStr']}.pdf",
        }

    rep = st.session_state.get("vrm_report")
    if not rep:
        return

    d = rep["data"]
    tot = d["totals"]
    n = len(d["dailyGrouped"])
    st.divider()

    _, _, score_text_color = rsvg.score_colors(d["avgHealth"])
    a, b, c, e = st.columns(4)
    with a:
        _metric_card("Generación solar", f"{tot['pv']:.1f} kWh")
    with b:
        _metric_card("Consumo", f"{tot['load']:.1f} kWh")
    with c:
        _metric_card("Independencia", f"{d['gridIndependencePct']}%")
    with e:
        _metric_card("Salud", f"{d['avgHealth']}/100", d["healthStatus"],
                     color=score_text_color)

    oc = tot["outageCount"]
    _chip_row([
        f"⚙️ <b>{d['systemType']}</b>",
        f"📅 <b>{n}/{n + d['missingDays']}</b> días con datos",
        f"🔋 <b style='color:{d['battStressColor']}'>{d['battStressLabel']}</b> "
        f"({d['batteryCycles']} cyc)",
        f"⚡ <b style='color:{d['gridQualityColor']}'>{d['gridQualityStatus']}</b> "
        f"({d['gridQualityScore']}/100)",
        (f"🔌 <b>{oc}</b> cortes ({tot['outageMinutes']} min)" if oc > 0
         else "🔌 <b>Sin cortes</b>"),
    ])

    st.caption(f"Periodo {d['startStr']} → {d['endStr']} · "
               f"{n} días · esquema `{d['schema']}`")

    total_energy = tot["pv"] + tot["grid"] + tot["discharge"]
    if total_energy > 0:
        import plotly.graph_objects as go
        mix_fig = go.Figure()
        for label, kwh, color in [
            ("Solar", tot["pv"], rsvg.GREEN),
            ("Batería", tot["discharge"], rsvg.BLUE),
            ("Red", tot["grid"], rsvg.MINT),
        ]:
            pct = kwh / total_energy * 100
            mix_fig.add_trace(go.Bar(
                y=["Energía"], x=[kwh], name=label, orientation="h",
                marker_color=color, text=[f"{pct:.0f}% · {kwh:.0f} kWh"],
                textposition="inside",
            ))
        mix_fig.update_layout(
            barmode="stack", height=150,
            # t/b give the legend row and the x-axis title their own space —
            # at the old t=10/b=10 both collided with the plot (legend into
            # the bar, "kWh" into the tick labels below it).
            margin=dict(t=40, b=40, l=10, r=10),
            xaxis_title="kWh", showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.05, x=0),
        )
        st.plotly_chart(mix_fig, use_container_width=True)

    # `weatherErrors` only has entries when the site HAS coordinates and the
    # fetch still failed — distinct from simply not having lat/long, which the
    # report labels "Datos de clima no disponibles" with no error attached.
    # Without this the two looked identical: an operator staring at a report
    # generated moments after saving coordinates would have no way to tell "not
    # configured" from "the weather service didn't answer, try again".
    if d.get("weatherErrors"):
        st.warning(
            "No se pudo obtener el clima de Open-Meteo (el sitio sí tiene "
            "coordenadas). El PDF se generó igual, sin ese bloque. "
            f"Detalle: {d['weatherErrors'][-1]}"
        )
    # Same thresholds the PDF itself uses (High stress tier, Poor/Irregular
    # grid quality) — an operator scanning this panel should catch these
    # before opening the PDF, not just when reading it line by line.
    if d["battStressLabel"] in ("Alto estrés", "High stress"):
        st.warning(f"🔋 Estrés de batería alto: {d['batteryCycles']} ciclos en {n} días.")
    if d["gridQualityScore"] < 70:
        st.warning(f"⚡ Calidad de red baja: {d['gridQualityScore']}/100 "
                   f"({d['gridQualityStatus']}).")

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

t1, t2, t3 = st.tabs(["Sitios", "Cargar CSV", "Reporte"])
with t1:
    tab_sites()
with t2:
    tab_upload()
with t3:
    tab_report()
