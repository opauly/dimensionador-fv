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

import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from config import BRAND_GREEN, BRAND_GREEN_LIGHT, BRAND_NAVY, COUNTRIES  # noqa: E402
from database import vrm_report_db as rdb  # noqa: E402
from victron import ingest, vrm_csv, vrm_remote, vrm_series, weekly_report as wr  # noqa: E402
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


def _feature_card(icon: str, title: str, desc: str) -> None:
    st.markdown(
        f'<div style="border:1px solid #e5e7eb;border-radius:8px;padding:0.7rem 0.9rem;'
        f'margin-bottom:0.6rem;min-height:6.2rem;">'
        f'<div style="font-size:0.85rem;font-weight:700;color:{BRAND_NAVY};">'
        f'{icon} {title}</div>'
        f'<div style="font-size:0.75rem;color:#6b7280;margin-top:3pt;">{desc}</div>'
        f'</div>', unsafe_allow_html=True,
    )


def _report_feature_cards(lang: str, num_days: int, is_overview: bool,
                          system_type: str, with_narrative: bool,
                          with_weather: bool) -> None:
    """Preview of the report's actual sections, reusing the exact same
    title/subtitle strings `report_i18n.get()` feeds the PDF — never a
    second, hand-written copy of that text to keep in sync by hand. Wording
    (and which cards appear) reacts to the same inputs the report itself
    reacts to, so this preview can't say something the generated PDF
    doesn't: is_overview for the daily-vs-monthly text (plan doc §22/§23),
    system_type for which blocks a given site even has, and the two
    "Incluir" checkboxes for the optional ones.
    """
    from victron import report_i18n
    t = report_i18n.get(lang, num_days, is_overview=is_overview)
    has_batt = system_type != "grid_zero"
    has_grid = system_type != "off_grid"
    es = lang == "es"

    cards = [("📈", t["healthScore"],
             "Puntaje 0-100 con generación solar, independencia de red y "
             "eventos del período." if es else
             "0-100 score alongside solar generation, grid independence, "
             "and period events.")]
    if with_narrative:
        cards.append(("🤖", "Narrativa (IA)" if es else "Narrative (AI)",
                      "Resumen en prosa generado por IA sobre lo más "
                      "relevante del período." if es else
                      "AI-generated prose summary of the period's key "
                      "story."))
    cards.append(("📊", t["sectionDaily"], t["subDaily"]))
    cards.append(("🥧", t["energyMix"], t["subEnergyMix"]))
    if has_batt:
        cards.append(("🔋", t["sectionBattery"], t["subBattery"]))
    if has_grid:
        cards.append(("⚡", t["sectionGrid"], t["subGrid"]))
    # Preview-only simplification: the real PDF's Events section always
    # renders (alarm episodes stay for off-grid — only its "Cortes de Red"
    # row is dropped, see weekly_report.py's _rows()). Gated on has_grid here
    # anyway, matching the surrounding cards, since this list is a preview
    # of section *titles*, not a line-by-line replica of PDF row content.
    if has_grid:
        cards.append(("🔔", t["sectionEvents"], t["subEvents"]))
    if has_batt:
        cards.append(("📉", t["socTimeline"], t["subSocChart"]))
    cards.append(("☀️", t["solarPerformance"], t["subSolarPerf"]))
    if with_weather:
        cards.append(("🌦️", t["weatherTitle"], t["subWeather"]))
    cards.append(("📅", t["fourWeekChart"], t["sub4Week"]))
    cards.append(("💰", t["tariffSavings"], t["subSavings"]))

    st.caption(
        "Vista previa de las secciones del reporte" if es else
        "Preview of the report's sections")
    cols = st.columns(3)
    for i, (icon, title, desc) in enumerate(cards):
        with cols[i % 3]:
            _feature_card(icon, title, desc)


SYSTEM_TYPES = ["hybrid", "off_grid", "grid_zero"]
LANGS = {"es": "Spanish", "en": "English"}
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


@st.cache_data(ttl=300)
def _fleet_installations() -> list[dict]:
    """Oscar's whole VRM fleet, live from Victron (PLAN_PHASE15.md §3.3) —
    called directly, no `vrm_api` hop, exactly like `_customers()`/`_sites()`
    call `database`/`victron` directly: this tool already runs server-side
    with the service-role key, the same trust level `vrm_api` itself has.
    Cached for 5 minutes (Victron's own rate limit, §0.2) rather than
    `_customers()`/`_sites()`'s 30 s — this hits a real external API, not
    just Postgres. Returns `[]` (never raises into the page) if
    `VRM_ADMIN_TOKEN` is missing or Victron rejects it; the caller shows a
    warning instead of crashing the whole tab.
    """
    token = os.environ.get("VRM_ADMIN_TOKEN")
    if not token:
        return []
    try:
        client = vrm_remote.VrmRemoteClient(token)
        me = client.get_me()
        user_id = (me.get("user") or {}).get("id")
        if user_id is None:
            return []
        installations = client.list_installations(user_id, extended=True)
    except vrm_remote.VrmRemoteError:
        return []
    return [r for r in (installations.get("records") or [])
           if isinstance(r, dict) and r.get("idSite") is not None]


def _read_customer_vrm_token(customer_id: str) -> str | None:
    """Bug-fix pass 2026-08-18 (Bug 2) — the same Vault-backed RPC
    `vrm_api/secrets.py:read_customer_vrm_token()` calls
    (`vrm.read_customer_vrm_token`, migration 024's `SECURITY DEFINER`
    wrapper), reached directly rather than through `vrm_api`/HTTP: this tool
    already has full service-role DB access, the same trust level `vrm_api`
    itself has (the same reasoning `_fleet_installations()`'s own docstring
    gives for calling `victron.vrm_remote` directly). Returns `None` when
    the customer has never connected a token, has disconnected it, or
    doesn't exist — one case, not three, matching
    `vrm_api/secrets.py`'s own contract.

    Same token-handling discipline as that module: never logged, never
    displayed, held by the caller only as long as the one Victron call that
    needs it takes.
    """
    from database.supabase_client import get_client
    result = (get_client().schema("vrm")
             .rpc("read_customer_vrm_token", {"p_customer_id": customer_id})
             .execute())
    return result.data


@st.cache_data(ttl=300)
def _customer_fleet_installations(customer_id: str) -> list[dict]:
    """Bug-fix pass 2026-08-18 (Bug 2) — same shape as `_fleet_installations()`
    above, but scoped to one customer's OWN connected VRM token instead of
    `VRM_ADMIN_TOKEN`, for the "Token propio del cliente" mode in
    `tab_upload()`. Cached by `customer_id`, not by the token itself, so the
    token value never becomes part of a Streamlit cache key — it is read
    fresh inside this function and discarded the moment `list_installations()`
    returns. Returns `[]` if the customer has no live token or Victron
    rejects it — same "never raise into the page" contract as
    `_fleet_installations()`.
    """
    token = _read_customer_vrm_token(customer_id)
    if not token:
        return []
    try:
        client = vrm_remote.VrmRemoteClient(token)
        me = client.get_me()
        user_id = (me.get("user") or {}).get("id")
        if user_id is None:
            return []
        installations = client.list_installations(user_id, extended=True)
    except vrm_remote.VrmRemoteError:
        return []
    return [r for r in (installations.get("records") or [])
           if isinstance(r, dict) and r.get("idSite") is not None]


def _stamp_customer_vrm_token_ok(customer_id: str) -> None:
    """Bug-fix pass 2026-08-18 (Bug 2) — replicates the customer-token
    success stamp `vrm_api/routers/vrm_sync.py:_do_sync()` writes for a
    REAL customer-token call (`is_customer_token=True` branch): a
    successful Victron call with this customer's own token genuinely proves
    their connection is alive, so `vrm_token_last_checked_at`/
    `vrm_token_last_ok_at` are stamped and any previous error cleared —
    same columns, same values, same reasoning as that function's own
    docstring. Not reached through `_do_sync()` itself (this tool has no
    HTTP dependency on `vrm_api` and never will, per this file's own
    established pattern of calling `victron`/`database` directly) — the
    stamping is small enough to restate here rather than import across that
    boundary.
    """
    from database.supabase_client import get_client
    now = datetime.now(timezone.utc).isoformat()
    get_client().schema("vrm").table("customers").update({
        "vrm_token_last_checked_at": now,
        "vrm_token_last_ok_at": now,
        "vrm_token_last_error": None,
    }).eq("id", customer_id).execute()


def _stamp_customer_vrm_token_auth_error(customer_id: str) -> None:
    """The failure-side twin of `_stamp_customer_vrm_token_ok()` — mirrors
    `_do_sync()`'s `VrmRemoteAuthError` handling for the customer-token
    branch: `vrm_token_revoked_at` is set (the same mechanism that makes
    `vrm.read_customer_vrm_token()` return `NULL` on the very next attempt,
    disabling further use without a separate flag check), and the error is
    recorded for the customer-facing "your VRM connection stopped working"
    state `vrm_api/routers/vrm_link.py:get_status()` already surfaces.
    """
    from database.supabase_client import get_client
    now = datetime.now(timezone.utc).isoformat()
    get_client().schema("vrm").table("customers").update({
        "vrm_token_revoked_at": now,
        "vrm_token_last_checked_at": now,
        "vrm_token_last_error": "Victron rejected the stored VRM token.",
    }).eq("id", customer_id).execute()


def _clear_caches() -> None:
    _customers.clear()
    _sites.clear()
    _fleet_installations.clear()
    _customer_fleet_installations.clear()


# ══════════════════════════════════════════════════════════════════
# Tab 1 — Sitios
# ══════════════════════════════════════════════════════════════════
def tab_sites() -> None:
    st.markdown("### Customers and sites")
    st.caption(
        "External customers of the VRM product. This is a separate schema from "
        "`clients` (Pauly & Co's own CRM) and from the `monitoring` schema of "
        "our own sites."
    )

    customers = _customers()
    sites = _sites("vrm")

    c1, c2 = st.columns(2)
    c1.metric("Customers", len(customers))
    c2.metric("Sites", len(sites))

    if sites:
        by_customer = {c["id"]: c["name"] for c in customers}
        df = pd.DataFrame([{
            "Customer": by_customer.get(s.get("customer_id"), "—"),
            "Site": s["display_name"],
            "site_id": s["site_id"],
            "VRM installation": s.get("vrm_installation_id") or "—",
            "Type": s.get("system_type"),
            "kWp": s.get("pv_kwp"),
            "Nominal battery kWh": s.get("battery_nominal_kwh"),
            "DoD %": s.get("battery_dod_pct"),
            "Usable battery kWh": s.get("battery_usable_kwh"),
            "Language": s.get("report_language"),
            "Country": s.get("country") or "CR",
            "Savings rate": (f"{s['savings_rate']} {s['savings_currency']}"
                             if s.get("savings_rate") else "—"),
            "Active": "Yes" if s.get("active") else "No",
        } for s in sites])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No sites yet. They're created automatically when you upload a CSV.")

    with st.expander("Create or update a site manually"):
        st.caption(
            "Not required: the **Upload CSV** tab creates the customer and site "
            "from the CSV. This is for fixing data afterward."
        )
        with st.form("vrm_site_form"):
            a, b = st.columns(2)
            cust_name = a.text_input("Customer", placeholder="Vista Atenas")
            site_name = b.text_input("Site", placeholder="2 Floor Pool")
            a, b, c, d = st.columns(4)
            pv_kwp = a.number_input("PV power (kWp)", min_value=0.0, step=0.1, value=0.0)
            batt_nominal = b.number_input(
                "Nominal battery (kWh)", min_value=0.0, step=0.1, value=0.0,
                help="Nameplate/datasheet capacity — the value printed on the "
                     "battery's technical spec sheet, before applying DoD.",
            )
            batt_dod = c.number_input(
                "DoD (%)", min_value=0.0, max_value=100.0, step=1.0, value=0.0,
                help="Datasheet depth of discharge (e.g. 97% for typical "
                     "LiFePO4). Usable = nominal × DoD/100 is calculated "
                     "automatically.",
            )
            stype = d.selectbox("System type", SYSTEM_TYPES)
            batt = round(batt_nominal * batt_dod / 100, 2) if batt_nominal and batt_dod else None
            if batt:
                st.caption(f"Usable battery: **{batt:.2f} kWh**")
            a, b, c = st.columns(3)
            lang = a.selectbox("Report language", list(LANGS), format_func=LANGS.get)
            location = b.text_input("Location", placeholder="Atenas, Alajuela")
            tz_list = _timezones()
            tz = c.selectbox("Timezone", tz_list, index=_tz_index(tz_list))
            a, b, c = st.columns(3)
            lat = a.number_input("Latitude", value=0.0, format="%.6f")
            lng = b.number_input("Longitude", value=0.0, format="%.6f")
            country = c.selectbox(
                "Country", _COUNTRY_CODES, format_func=lambda k: COUNTRIES[k],
                index=_DEFAULT_COUNTRY_IDX,
                help="CR calculates savings using ARESEP tariffs; any other "
                     "country uses the flat rate below.")
            a, b = st.columns(2)
            savings_rate = a.number_input("Savings rate (per kWh)", min_value=0.0,
                                          step=0.01, format="%.4f",
                                          help="Only used if Country is not CR.")
            savings_currency = b.selectbox("Currency", vrm_savings.SUPPORTED_FLAT_CURRENCIES)

            if st.form_submit_button("Save", type="primary"):
                if not cust_name.strip() or not site_name.strip():
                    st.error("Customer and site are required.")
                else:
                    try:
                        cust = ingest.upsert_customer(cust_name.strip())
                        site_id = ingest.make_site_id(cust["slug"], site_name.strip())
                        ingest.upsert_site(
                            cust["id"], site_id, site_name.strip(),
                            pv_kwp=pv_kwp or None,
                            battery_nominal_kwh=batt_nominal or None,
                            battery_dod_pct=batt_dod or None,
                            # battery_usable_kwh is a generated column
                            # (migration 019) — Postgres computes it from the
                            # two fields above and rejects a direct write.
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
                        _flash(f"Site saved: `{site_id}`")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Could not save: {exc}")


# ══════════════════════════════════════════════════════════════════
# Tab 2 — Cargar CSV
# ══════════════════════════════════════════════════════════════════
def tab_upload() -> None:
    st.markdown("### Upload VRM CSV export")
    st.caption(
        "Export the log from the VRM portal (Advanced → Download) and upload "
        "it here. The file is processed and a summary is shown **before** "
        "anything is written to the database."
    )

    # PLAN_PHASE15.md §3.3 — a second, parallel way to fill the same
    # "process, preview, import" flow below: instead of a file uploaded by
    # hand, pull directly from Victron's VRM cloud with Pauly&Co's own
    # VRM_ADMIN_TOKEN. Everything from the customer/site fields down through
    # the summary + "Importar" button is shared between both modes —
    # only the "how do we get `parsed`" step (file uploader vs. fleet
    # picker) and a couple of `source`/`triggered_by` keywords differ.
    mode = st.radio(
        "Upload mode", ["Upload CSV", "Sync from VRM API"],
        key="up_mode", horizontal=True,
        help="\"Upload CSV\" is still the primary path, unchanged. "
             "\"Sync from VRM API\" pulls data directly from the VRM cloud "
             "instead of exporting and uploading a file by hand — using "
             "Pauly&Co's token (VRM_ADMIN_TOKEN) or, if the customer has "
             "already connected their own VRM account, that customer's own "
             "token (selectable below).",
    )
    st.divider()

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
    cust_name = a.text_input("Customer", key="up_cust", placeholder="Vista Atenas")
    site_name = b.text_input("Site", key="up_site", placeholder="2 Floor Pool")
    a, b, c, d, e = st.columns(5)
    pv_kwp = a.number_input("PV power (kWp)", min_value=0.0, step=0.1, key="up_kwp")
    batt_nominal = b.number_input(
        "Nominal battery (kWh)", min_value=0.0, step=0.1, key="up_batt_nominal",
        help="Nameplate/datasheet capacity, before applying DoD.",
    )
    batt_dod = c.number_input(
        "DoD (%)", min_value=0.0, max_value=100.0, step=1.0, key="up_batt_dod",
        help="Datasheet depth of discharge. Usable = nominal × DoD/100.",
    )
    stype = d.selectbox("System type", SYSTEM_TYPES, key="up_type")
    lang = e.selectbox("Report language", list(LANGS), format_func=LANGS.get,
                       key="up_lang")
    batt = round(batt_nominal * batt_dod / 100, 2) if batt_nominal and batt_dod else None
    if batt:
        st.caption(f"Usable battery: **{batt:.2f} kWh**")

    # Location drives the Open-Meteo call, which in turn drives the weather
    # block AND the expected-output figure behind the performance ratio.
    # Without coordinates the report falls back to a flat 4.5 peak-sun-hours
    # assumption, and the "ratio" degenerates into actual-vs-assumption.
    st.markdown("##### Location")
    st.caption(
        "Needed for weather and the performance ratio. Enter "
        "Latitude/Longitude (from Google Maps or the installer) and use the "
        "button below to fill in Location, Timezone, and Country "
        "automatically — works for any country. All three fields stay "
        "editable by hand if something needs correcting."
    )
    tz_list = _timezones()
    a, b, c = st.columns([1, 1, 1.3])
    lat = a.number_input("Latitude", value=0.0, format="%.6f", key="up_lat")
    lng = b.number_input("Longitude", value=0.0, format="%.6f", key="up_lng")
    with c:
        st.write("")
        if st.button("Look up by coordinates", key="up_revgeo",
                     help="Fills in Location, Timezone, and Country from "
                          "Latitude/Longitude — any country."):
            if not lat and not lng:
                st.warning("Enter latitude and longitude first.")
            else:
                from calculations.pvgis import reverse_geocode
                got = reverse_geocode(lat, lng)
                if not got:
                    st.warning("Could not resolve those coordinates.")
                else:
                    if got.get("location"):
                        st.session_state["_up_pending_loc"] = got["location"]
                    if got.get("timezone") in tz_list:
                        st.session_state["_up_pending_tz"] = got["timezone"]
                    code = got.get("country_code")
                    if code and code in COUNTRIES:
                        st.session_state["_up_pending_country"] = code
                    elif code:
                        st.warning(f"Detected country ({code}) is not in "
                                   f"the list — select it manually.")
                    st.rerun()

    a, b, c = st.columns([2, 1, 1])
    location = a.text_input("Location", key="up_loc",
                            placeholder="Atenas, Alajuela")
    # `index=` is only a first-render default. Once the reverse-geocode button
    # has staged a value into session_state (see the pending-key block above),
    # passing `index=` again on top of that makes Streamlit warn — "created
    # with a default value but also had its value set via the Session State
    # API" — even though it still resolves correctly. Omitting it once the key
    # already governs the widget avoids the warning outright.
    tz_kwargs = {} if "up_tz" in st.session_state else {"index": _tz_index(tz_list)}
    tz = b.selectbox("Timezone", tz_list, key="up_tz", **tz_kwargs)
    country_kwargs = ({} if "up_country" in st.session_state
                      else {"index": _DEFAULT_COUNTRY_IDX})
    country = c.selectbox(
        "Country", _COUNTRY_CODES, format_func=lambda k: COUNTRIES[k], key="up_country",
        help="Determines how savings are estimated: Costa Rica uses ARESEP "
             "tariffs automatically; any other country uses the flat rate "
             "below.",
        **country_kwargs,
    )

    # No electric-company picker anywhere — Costa Rica needs none (blended
    # ARESEP average, computed automatically from `país`), and everywhere else
    # gets one flat rate typed in once, not a distributor list.
    st.markdown("##### Estimated savings")
    if stype == "off_grid":
        st.caption(
            "This site is off-grid: it has no connection to the grid. The "
            "report will show savings as a hypothetical figure — what would "
            "have been paid for this energy if the site were grid-connected, "
            "not savings on a real bill."
        )
    else:
        st.caption(
            "For sites in Costa Rica (country = CR) savings are calculated "
            "automatically, using the average of ARESEP T-RE tariffs — "
            "nothing else needs to be entered here. For any other country, "
            "enter a flat rate; if left at 0, the report won't show a "
            "savings figure instead of making one up."
        )
    a, b = st.columns(2)
    savings_rate = a.number_input("Rate (per kWh)", min_value=0.0, step=0.01,
                                  format="%.4f", key="up_rate")
    savings_currency = b.selectbox("Currency", vrm_savings.SUPPORTED_FLAT_CURRENCIES,
                                   key="up_currency")

    exports = st.checkbox(
        "This system exports energy to the grid",
        key="up_export",
        help=(
            "Hybrid/ESS systems with feed-in send surplus to the grid "
            "(negative Grid L1/L2 readings). Turn this on so the report "
            "shows exported energy. Grid consumption is always measured as "
            "import only."
        ),
    )

    is_api_mode = mode == "Sync from VRM API"
    id_site = None
    sync_start = sync_end = None

    if not is_api_mode:
        up = st.file_uploader("VRM CSV file", type=["csv"], key="up_file")
        st.caption("Upload limit: 200 MB (an ~80-day export weighs about 140 MB).")
        if up is None:
            return
        process_clicked = st.button("Process and preview", type="primary", key="up_process_csv")
    else:
        # Bug-fix pass 2026-08-18 (Bug 2) — this mode used to ALWAYS use
        # Oscar's own fleet token, with no way to sync via a customer's own
        # already-connected VRM account. `token_source_options` only offers
        # "Token propio del cliente" when the typed-in customer actually has
        # a live token — "disable/hide this option ... rather than a
        # confusing failure after the fact" (this bug's own instruction),
        # not a widget that's always there and fails when clicked.
        token_source_options = ["My fleet (Pauly&Co)"]
        customer_row = None
        if cust_name.strip():
            slug = ingest.slugify(cust_name)
            customer_row = next((c for c in _customers() if c.get("slug") == slug), None)
        customer_has_token = bool(customer_row and _read_customer_vrm_token(customer_row["id"]))
        if customer_has_token:
            token_source_options.append("Customer's own token")

        # Same "stale session-state value" guard the reverse-geocode
        # pending-key block above this function protects against, applied
        # here to a widget whose OPTION LIST itself can shrink (e.g. the
        # customer name changed, or their token got disconnected) —
        # Streamlit raises if a keyed widget's stored value is no longer
        # among its options.
        if st.session_state.get("up_token_source") not in token_source_options:
            st.session_state.pop("up_token_source", None)

        token_source = st.radio(
            "VRM token source", token_source_options, key="up_token_source",
            horizontal=True,
            help="\"My fleet (Pauly&Co)\" uses VRM_ADMIN_TOKEN — Oscar's "
                 "whole fleet. \"Customer's own token\" uses the VRM account "
                 "that customer connected themselves from /app/sites — this "
                 "option only appears if the customer typed above has an "
                 "active connection.",
        )
        use_customer_token = token_source == "Customer's own token"

        if not cust_name.strip():
            st.caption("Type the customer's name above to see if they have their own connected VRM account.")
        elif customer_row and not customer_has_token:
            st.caption(f"\"{cust_name.strip()}\" doesn't have a connected VRM account — you can only sync with Pauly&Co's fleet.")
        elif not customer_row:
            st.caption("That customer doesn't exist yet in `vrm.customers` — it will be created on import, syncing with Pauly&Co's fleet.")

        if use_customer_token:
            installs = _customer_fleet_installations(customer_row["id"])
            if not installs:
                st.warning("Could not fetch installations with this customer's token.")
                return
        else:
            installs = _fleet_installations()
            if not installs:
                st.warning(
                    "Could not fetch the VRM fleet (check that `VRM_ADMIN_TOKEN` "
                    "is configured in the environment and is a valid token)."
                )
                return
        fleet_labels = {
            r["idSite"]: f"{r.get('name') or '—'} (idSite {r['idSite']}, {r.get('identifier') or '—'})"
            for r in installs
        }
        if st.session_state.get("up_fleet_install") not in fleet_labels:
            st.session_state.pop("up_fleet_install", None)
        id_site = st.selectbox("VRM installation", list(fleet_labels),
                               format_func=fleet_labels.get, key="up_fleet_install")
        a, b = st.columns(2)
        default_end = date.today() - timedelta(days=1)
        default_start = default_end - timedelta(days=30)  # §0.5 Q4's 31-day backfill default
        sync_start = a.date_input("From", value=default_start, key="up_fleet_start")
        sync_end = b.date_input("To", value=default_end, key="up_fleet_end")
        st.caption(
            "Pulls data directly from the VRM cloud for the chosen range "
            "(defaults to the last 31 days up to yesterday)."
        )
        process_clicked = st.button("Process and preview", type="primary", key="up_process_api")

    if process_clicked:
        if not cust_name.strip() or not site_name.strip():
            st.error("Enter customer and site before processing.")
            return
        slug = ingest.slugify(cust_name)
        site_id = ingest.make_site_id(slug, site_name)

        if not is_api_mode:
            with st.spinner("Processing the CSV…"):
                try:
                    parsed = vrm_csv.parse_export(
                        up, site_id=site_id, filename=up.name,
                        pv_kwp=pv_kwp or None, battery_usable_kwh=batt or None,
                    )
                except vrm_csv.VrmCsvError as exc:
                    st.error(f"The file is not a valid VRM export: {exc}")
                    return
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not process: {exc}")
                    return
            filename = up.name
        else:
            # Bug-fix pass 2026-08-18 (Bug 2): `use_customer_token`/
            # `customer_row` come from the `is_api_mode` branch above, in
            # this same script run — `token` is resolved from whichever
            # source the operator picked there, read fresh right here (never
            # cached, never stored beyond this local variable), matching the
            # token-handling discipline `vrm_api/secrets.py` documents.
            if use_customer_token:
                if not customer_row:
                    st.error("That customer doesn't exist — they can't have a connected VRM token.")
                    return
                token = _read_customer_vrm_token(customer_row["id"])
                if not token:
                    st.error("This customer doesn't have a connected VRM account.")
                    return
            else:
                token = os.environ.get("VRM_ADMIN_TOKEN")
                if not token:
                    st.error("`VRM_ADMIN_TOKEN` is not configured in the environment.")
                    return
            with st.spinner("Syncing with VRM…"):
                try:
                    client = vrm_remote.VrmRemoteClient(token)
                    parsed = vrm_series.fetch_and_map(
                        client, id_site, site_id, sync_start, sync_end,
                        pv_kwp=pv_kwp or None, battery_usable_kwh=batt or None,
                        tz=tz or "America/Costa_Rica",
                    )
                except vrm_series.VrmSeriesError as exc:
                    st.error(f"Could not map VRM data: {exc}")
                    return
                except vrm_remote.VrmRemoteAuthError:
                    if use_customer_token:
                        # A real customer credential failing IS that
                        # customer's connection state changing — stamp it
                        # the same way `vrm_api/routers/vrm_sync.py:
                        # _do_sync()`'s customer-token branch does, so the
                        # very next sync attempt (from here, or from the
                        # customer's own "Sync now") sees "no live token"
                        # and fails clean instead of repeating a call
                        # Victron already rejected.
                        _stamp_customer_vrm_token_auth_error(customer_row["id"])
                        st.error("Victron rejected this customer's token — their VRM connection stopped working.")
                    else:
                        st.error("Victron rejected `VRM_ADMIN_TOKEN` — check that it's still valid.")
                    return
                except vrm_remote.VrmRemoteNotFound:
                    st.error("That installation is no longer visible with this token.")
                    return
                except (vrm_remote.VrmRemoteRateLimited, vrm_remote.VrmRemoteUnavailable,
                        vrm_remote.VrmRemoteBudgetExceeded) as exc:
                    st.error(f"Could not reach the VRM API: {exc}")
                    return
            if use_customer_token:
                # A real, successful call to Victron with this customer's
                # OWN token — this IS "when we last knew it was alive"
                # (migration 024's own framing; `_do_sync()`'s identical
                # stamp for its customer-token branch). Never stamped on the
                # admin-fleet branch: VRM_ADMIN_TOKEN's health says nothing
                # about whether this customer has ever connected their own
                # token at all.
                _stamp_customer_vrm_token_ok(customer_row["id"])
            # No uploaded file for this mode — `ingestion_log.filename` stays
            # NULL (`victron.ingest.ingest_parsed()`'s own `filename or None`),
            # same as `vrm_api/routers/vrm_sync.py:_do_sync()`'s admin/customer
            # sync jobs leave it.
            filename = ""

        st.session_state["vrm_parsed"] = parsed
        st.session_state["vrm_parsed_meta"] = {
            "customer": cust_name.strip(), "site": site_name.strip(),
            "filename": filename, "pv_kwp": pv_kwp or None,
            "battery_nominal_kwh": batt_nominal or None,
            "battery_dod_pct": batt_dod or None,
            "battery_usable_kwh": batt, "system_type": stype,
            "report_language": lang,
            "location": location or None, "timezone": tz or "America/Costa_Rica",
            # 0,0 is Null Island, not "unknown" — store NULL so the report can
            # tell the difference and say weather is unavailable.
            "latitude": lat or None, "longitude": lng or None,
            "exports_to_grid": exports,
            "country": (country or "CR").strip().upper() or "CR",
            "savings_rate": savings_rate or None,
            "savings_currency": savings_currency if savings_rate else None,
            # PLAN_PHASE15.md §3.3 — drives the source='vrm_api'/
            # vrm_sync_enabled=True site fields and the ingestion_log
            # source/triggered_by values below, at import time. "csv" leaves
            # every downstream call exactly as it was before this mode
            # existed (byte-identical to the plan's own CSV-path guarantee).
            "mode": "vrm_api" if is_api_mode else "csv",
        }

    parsed = st.session_state.get("vrm_parsed")
    if not parsed:
        return

    meta = st.session_state["vrm_parsed_meta"]
    st.divider()
    st.markdown("#### Summary of what will be imported")

    a, b, c, d = st.columns(4)
    a.metric("Days", len(parsed["rows"]))
    b.metric("Samples", f"{parsed['sample_count']:,}")
    c.metric("Alarm events", len(parsed["alarm_events"]))
    d.metric("Grid outages", len(parsed["outages"]))
    _tz_source = "from sync" if meta.get("mode") == "vrm_api" else "from file"
    st.caption(
        f"VRM installation **{parsed['installation_id'] or '—'}** · period "
        f"{parsed['period_start'][:10]} → {parsed['period_end'][:10]} · "
        f"timezone {_tz_source}: {parsed['timezone_label']} · "
        f"report in **{LANGS.get(meta['report_language'], meta['report_language'])}**"
    )
    _og_note = " (hypothetical — off-grid site)" if meta["system_type"] == "off_grid" else ""
    if meta["country"] == "CR":
        st.caption(f"Estimated savings: automatic, average of ARESEP T-RE tariffs{_og_note}.")
    elif meta["savings_rate"]:
        st.caption(
            f"Estimated savings: flat rate "
            f"{vrm_savings.format_money(meta['savings_rate'], meta['savings_currency'])}"
            f"/kWh{_og_note}."
        )
    else:
        st.caption("Estimated savings: won't be shown (non-CR country with no rate configured).")

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
            f"{partial} partial day(s) — usually the first and last in the "
            "file. They're saved anyway, marked incomplete, so the report "
            "can exclude them instead of showing them as low-generation "
            "days."
        )

    if st.button("Import to database", type="primary"):
        with st.spinner("Writing…"):
            try:
                cust = ingest.upsert_customer(meta["customer"])
                site_id = ingest.make_site_id(cust["slug"], meta["site"])
                fields = {"pv_kwp": meta["pv_kwp"],
                          "battery_nominal_kwh": meta["battery_nominal_kwh"],
                          "battery_dod_pct": meta["battery_dod_pct"],
                          # battery_usable_kwh is a generated column
                          # (migration 019) — not written directly, only used
                          # above as an argument to vrm_csv.parse_export()
                          # for the energy_daily.battery_kwh_snapshot value.
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
                if meta.get("mode") == "vrm_api":
                    # PLAN_PHASE15.md §3.3 — a site synced from the API this
                    # way is indistinguishable from one linked through
                    # `/admin/vrm-fleet` (`vrm_api/routers/vrm_fleet.py`'s
                    # own `post_link()`): same two fields, same meaning.
                    fields["source"] = "vrm_api"
                    fields["vrm_sync_enabled"] = True
                ingest.upsert_site(cust["id"], site_id, meta["site"], **fields)
                summary = ingest.ingest_parsed(
                    parsed, site_id, filename=meta["filename"],
                    # CSV mode: unchanged, exactly today's call (source
                    # defaults to "csv_upload", triggered_by stays None) —
                    # the byte-identical-behaviour guarantee this phase's
                    # plan requires for the untouched path. API mode: the
                    # same source/triggered_by values `vrm_api/routers/
                    # vrm_fleet.py:post_sync()`'s admin sync job writes.
                    **({"source": "vrm_api", "triggered_by": "admin"}
                      if meta.get("mode") == "vrm_api" else {}),
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Import failed: {exc}")
                return
        _clear_caches()
        st.session_state.pop("vrm_parsed", None)
        _flash(
            f"Imported {summary['rows_written']} days and "
            f"{summary['alarm_events_written']} alarm events into `{site_id}`."
        )
        st.info("You can now generate the report in the **Report** tab.")


# ══════════════════════════════════════════════════════════════════
# Tab 3 — Reporte
# ══════════════════════════════════════════════════════════════════
def tab_report() -> None:
    st.markdown("### Report")
    st.caption(
        "The same generator works for both schemas: `vrm` (external "
        "customers, from CSV) and `monitoring` (Pauly & Co's own sites with "
        "Cerbo GX and Node-RED). Useful for comparing both ingestion paths "
        "on the same site."
    )

    a, b = st.columns([1, 2])
    schema = a.radio("Source", [rdb.VRM, rdb.MONITORING], horizontal=True,
                     format_func=lambda s: ("vrm — external customers"
                                            if s == rdb.VRM
                                            else "monitoring — our own sites"))
    sites = _sites(schema)
    if not sites:
        st.info(f"No sites in the `{schema}` schema.")
        return

    labels = {s["site_id"]: f"{s['display_name']} ({s['site_id']})" for s in sites}
    site_id = b.selectbox("Site", list(labels), format_func=labels.get)
    site = next(s for s in sites if s["site_id"] == site_id)
    site_lang = "es" if (site.get("report_language") or "en").lower() == "es" else "en"
    site_system_type = site.get("system_type") or "hybrid"

    dates = rdb.get_available_dates(site_id, schema)
    if not dates:
        st.warning("That site doesn't have any daily data yet.")
        return

    st.caption(f"Data available: **{dates[0]} → {dates[-1]}** ({len(dates)} days)")

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
        week_ending = a.date_input("Week ending", value=max_d,
                                   min_value=min_d, max_value=max_d).isoformat()
        opts = b.multiselect("Include", ["Narrative (AI)", "Weather (Open-Meteo)"],
                             default=["Narrative (AI)", "Weather (Open-Meteo)"])
        start, end = rdb.week_bounds(week_ending)
        start, end = start.isoformat(), end.isoformat()
        covered = [d for d in dates if start <= d <= end]
        if len(covered) < 7:
            st.warning(
                f"The week {start} → {end} has {len(covered)} of 7 days "
                "with data. The report is generated anyway, but totals "
                "aren't comparable to a full week."
            )
        _report_feature_cards(site_lang, 7, False, site_system_type,
                              "Narrative (AI)" in opts, "Weather (Open-Meteo)" in opts)
    else:
        # vrm: operator picks any [start, end] up to MAX_OVERVIEW_RANGE_DAYS, one
        # calendar with range selection bounded to the site's real data span.
        # A calendar can't restrict individual days to only the ones with
        # data the way the old date-dropdowns did, but a sparse or fully
        # empty pick is already handled below (coverage warning) and in the
        # generate handler (caught exception) — so that's not a new gap
        # (plan doc §21, Phase A).
        default_start = dates[max(0, len(dates) - 7)]
        picked = st.date_input(
            "Report range", value=(date.fromisoformat(default_start), max_d),
            min_value=min_d, max_value=max_d,
        )
        opts = st.multiselect("Include", ["Narrative (AI)", "Weather (Open-Meteo)"],
                              default=["Narrative (AI)", "Weather (Open-Meteo)"])

        if not isinstance(picked, tuple) or len(picked) != 2:
            st.info("Pick a start date and an end date on the calendar.")
            valid = False
            start = end = None
        else:
            start, end = (d.isoformat() for d in picked)
            num_days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
            if num_days > rdb.MAX_OVERVIEW_RANGE_DAYS:
                st.error(
                    f"The selected range is {num_days} days; the maximum "
                    f"for this report is {rdb.MAX_OVERVIEW_RANGE_DAYS}. "
                    "Choose a shorter range."
                )
                valid = False
            else:
                # Which mode this pick will produce — shown for every valid
                # pick, not just past the boundary, so the operator always
                # knows before clicking Generar (plan doc §22: auto-switch,
                # no manual toggle, but never a silent one).
                if num_days > rdb.MAX_CUSTOM_RANGE_DAYS:
                    st.caption(
                        f"📊 **Overview** — {num_days} days, grouped by "
                        "month. Ranges longer than "
                        f"{rdb.MAX_CUSTOM_RANGE_DAYS} days are automatically "
                        "summarized instead of shown day by day."
                    )
                else:
                    st.caption(f"📅 **Detailed** — {num_days} days, day by day.")

                covered = [d for d in dates if start <= d <= end]
                if len(covered) < num_days:
                    st.warning(
                        f"The range {start} → {end} has {len(covered)} of "
                        f"{num_days} days with data. The report is "
                        "generated anyway, but totals aren't comparable to "
                        "a full range."
                    )

                _report_feature_cards(
                    site_lang, num_days, num_days > rdb.MAX_CUSTOM_RANGE_DAYS,
                    site_system_type, "Narrative (AI)" in opts,
                    "Weather (Open-Meteo)" in opts)

    if valid and st.button("Generate report", type="primary"):
        with st.spinner("Generating…"):
            try:
                data = wr.build_report_data(
                    site_id, start, end, schema,
                    with_narrative="Narrative (AI)" in opts,
                    with_weather="Weather (Open-Meteo)" in opts,
                )
                pdf = wr.render_pdf(data)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not generate the report: {exc}")
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
        _metric_card("Solar generation", f"{tot['pv']:.1f} kWh")
    with b:
        _metric_card("Consumption", f"{tot['load']:.1f} kWh")
    with c:
        _metric_card("Independence", f"{d['gridIndependencePct']}%")
    with e:
        _metric_card("Health", f"{d['avgHealth']}/100", d["healthStatus"],
                     color=score_text_color)

    # Reorganized 2026-08-19 at Oscar's request: this panel is a quick
    # "did this run correctly" glance before downloading, not a second copy
    # of the report — grid quality, outages, battery-stress cycle count, and
    # the energy-mix chart are all already their own dedicated PDF sections
    # (`report_svg.py`'s Grid Quality block, Events block, SALUD DE LA
    # BATERÍA block, and the DE DÓNDE VINO SU ENERGÍA donut, respectively).
    # Duplicating them here for both system types added detail without
    # adding a decision an operator makes differently because of it. Kept:
    # the four general headline numbers above, and system type/data
    # coverage — genuine "is this the right site/window" context, not a
    # restated PDF stat.
    _chip_row([
        f"⚙️ <b>{d['systemType']}</b>",
        f"📅 <b>{n}/{n + d['missingDays']}</b> days with data",
    ])

    st.caption(f"Period {d['startStr']} → {d['endStr']} · "
               f"{n} days · schema `{d['schema']}`")

    # `weatherErrors` only has entries when the site HAS coordinates and the
    # fetch still failed — distinct from simply not having lat/long, which the
    # report labels "Datos de clima no disponibles" with no error attached.
    # Kept (unlike the stat-duplicating warnings this reorganization
    # removed): this isn't a number the PDF already shows, it's a heads-up
    # that a PDF section silently came out empty because an external call
    # failed — an operator staring at a report generated moments after
    # saving coordinates would otherwise have no way to tell "not
    # configured" from "the weather service didn't answer, try again".
    if d.get("weatherErrors"):
        st.warning(
            "Could not fetch weather from Open-Meteo (the site does have "
            "coordinates). The PDF was generated anyway, without that "
            f"block. Detail: {d['weatherErrors'][-1]}"
        )

    st.download_button("⬇️ Download PDF", data=rep["pdf"],
                       file_name=rep["name"], mime="application/pdf",
                       type="primary")


# ══════════════════════════════════════════════════════════════════
st.markdown(
    f"<h2 style='margin-bottom:2px'>VRM Monitor</h2>"
    f"<div style='color:#6b7280;margin-bottom:18px'>Weekly reports for "
    f"external customers, from Victron VRM CSV exports</div>",
    unsafe_allow_html=True,
)

t1, t2, t3 = st.tabs(["Sites", "Upload CSV", "Report"])
with t1:
    tab_sites()
with t2:
    tab_upload()
with t3:
    tab_report()
