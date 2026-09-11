"""Admin section: equipment catalog, services, ARESEP tariffs, clients,
sites and settings — read-only views for now (see module docstrings on
each database/*.py function for the write-side calls still to port:
upsert_panel/upsert_inverter/etc., the AI tariff updater, client/site
forms). Faithful to pages/05_admin.py's section layout.
"""
from __future__ import annotations

from flask import Blueprint, abort, render_template

bp = Blueprint("admin", __name__, url_prefix="/admin")

SECTIONS = {
    "equipos": {"label": "Equipos", "sub": ["paneles", "inversores", "baterias", "controladores", "monitoreo"]},
    "servicios": {"label": "Servicios", "sub": None},
    "aresep": {"label": "ARESEP", "sub": ["tarifas", "actualizar"]},
    "clientes": {"label": "Clientes", "sub": ["clientes", "prospectos"]},
    "sitios": {"label": "Sitios", "sub": None},
    "ajustes": {"label": "Ajustes", "sub": None},
}
SECTION_ORDER = ["equipos", "servicios", "aresep", "clientes", "sitios", "ajustes"]

SUB_LABELS = {
    "paneles": "Paneles", "inversores": "Inversores", "baterias": "Baterías",
    "controladores": "Controladores de carga", "monitoreo": "Monitoreo",
    "tarifas": "Tarifas actuales", "actualizar": "Actualizar tarifas",
    "clientes": "Clientes", "prospectos": "Prospectos",
}


def _usd(v):
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "—"


def _pct(v):
    return f"{v * 100:.0f}%" if isinstance(v, (int, float)) else "—"


def _crc(v):
    return f"₡{v:,.2f}" if isinstance(v, (int, float)) else "—"


def _yn(v):
    return "Sí" if v else "No"


def _equipment_table(rows, columns):
    out = []
    for r in rows:
        out.append({k: r.get(k) if fmt is None else fmt(r.get(k)) for k, _, fmt in columns})
    return out


PANEL_COLS = [("brand", "Marca", None), ("model", "Modelo", None), ("wp", "Wp", None),
              ("voc", "Voc", None), ("vmp", "Vmp", None), ("isc", "Isc", None),
              ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]
INVERTER_COLS = [("brand", "Marca", None), ("model", "Modelo", None), ("kw", "kW", None),
                 ("type", "Tipo", None), ("phase", "Fase", None), ("mppt_channels", "MPPT", None),
                 ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]
BATTERY_COLS = [("brand", "Marca", None), ("model", "Modelo", None), ("chemistry", "Química", None),
                ("capacity_kwh", "kWh", None), ("voltage_v", "V", None), ("cycles", "Ciclos", None),
                ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]
CC_COLS = [("brand", "Marca", None), ("model", "Modelo", None), ("type", "Tipo", None),
           ("vin_max", "Vin máx", None), ("imax_out", "Imax salida", None),
           ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]
MONITORING_COLS = [("brand", "Marca", None), ("model", "Modelo", None),
                    ("compatible_with", "Compatible con", None),
                    ("cost_usd", "Costo", _usd), ("cost_iva_rate", "IVA", _pct)]
SERVICE_COLS = [("item", "Servicio", None), ("unit_cost_usd", "Costo unitario", _usd),
                ("iva_pct", "IVA", _pct), ("enabled", "Activo", _yn)]
CLIENT_COLS = [("name", "Nombre", None), ("empresa", "Empresa", None),
               ("phone", "Teléfono", None), ("email", "Correo", None)]
SITE_COLS = [("display_name", "Sitio", None), ("client_name", "Cliente", None),
             ("brand", "Marca", None), ("active", "Activo", _yn)]
TARIFF_COLS = [("distributor", "Distribuidora", None), ("tariff", "Tarifa", None),
               ("access_charge", "Cargo fijo", _crc), ("last_updated", "Actualizada", None)]


@bp.route("/")
def root():
    from flask import redirect, url_for
    return redirect(url_for("admin.index", section="equipos"))


@bp.route("/<section>")
def index(section):
    if section not in SECTIONS:
        abort(404)
    sub_list = SECTIONS[section]["sub"]
    default_sub = sub_list[0] if sub_list else None
    panel_html = _render_panel(section, default_sub)
    return render_template(
        "admin/page.html",
        sections=SECTION_ORDER, section_meta=SECTIONS, active_section=section,
        sub_list=sub_list, sub_labels=SUB_LABELS, active_sub=default_sub,
        panel_html=panel_html,
    )


@bp.route("/<section>/<sub>")
def sub_view(section, sub):
    from flask import request

    if section not in SECTIONS or not SECTIONS[section]["sub"] or sub not in SECTIONS[section]["sub"]:
        abort(404)
    panel_html = _render_panel(section, sub)
    if request.headers.get("HX-Request"):
        return panel_html
    return render_template(
        "admin/page.html",
        sections=SECTION_ORDER, section_meta=SECTIONS, active_section=section,
        sub_list=SECTIONS[section]["sub"], sub_labels=SUB_LABELS, active_sub=sub,
        panel_html=panel_html,
    )


def _render_panel(section, sub):
    if section == "equipos":
        return _render_equipos(sub)
    if section == "servicios":
        return _render_servicios()
    if section == "aresep":
        return _render_aresep(sub)
    if section == "clientes":
        return _render_clientes(sub)
    if section == "sitios":
        return _render_sitios()
    if section == "ajustes":
        return _render_ajustes()
    abort(404)


def _table_partial(columns, rows, empty_message):
    return render_template(
        "admin/_table.html",
        columns=[{"key": k, "label": l} for k, l, _ in columns],
        rows=_equipment_table(rows, columns),
        empty_message=empty_message,
    )


def _render_equipos(sub):
    from database.equipment_db import (
        list_batteries, list_charge_controllers, list_inverters,
        list_monitoring_devices, list_panels,
    )
    try:
        if sub == "paneles":
            return _table_partial(PANEL_COLS, list_panels(), "Sin paneles registrados.")
        if sub == "inversores":
            return _table_partial(INVERTER_COLS, list_inverters(), "Sin inversores registrados.")
        if sub == "baterias":
            return _table_partial(BATTERY_COLS, list_batteries(), "Sin baterías registradas.")
        if sub == "controladores":
            return _table_partial(CC_COLS, list_charge_controllers(), "Sin controladores registrados.")
        if sub == "monitoreo":
            return _table_partial(MONITORING_COLS, list_monitoring_devices(), "Sin equipos de monitoreo registrados.")
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))
    abort(404)


def _render_servicios():
    from database.equipment_db import list_service_defaults
    try:
        return _table_partial(SERVICE_COLS, list_service_defaults(), "Sin servicios registrados.")
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))


def _render_aresep(sub):
    if sub == "actualizar":
        return render_template(
            "admin/_stub_panel.html",
            message="El actualizador de tarifas (parseo AI de resoluciones ARESEP) aún no se ha migrado a Flask/Jinja2. Use la versión Streamlit (puerto 8501) por ahora.",
        )
    from database.tariffs_db import list_distributors, list_tariff_types
    try:
        rows = []
        for dist in list_distributors():
            for tt in list_tariff_types(dist["id"]):
                rows.append({
                    "distributor": dist.get("abbreviation"),
                    "tariff": tt.get("name") or tt.get("code"),
                    "access_charge": tt.get("access_charge_crc"),
                    "last_updated": (tt.get("last_updated") or "—")[:10],
                })
        return _table_partial(TARIFF_COLS, rows, "Sin tarifas registradas.")
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))


def _render_clientes(sub):
    try:
        if sub == "clientes":
            from database.clients_db import list_all_clients
            return _table_partial(CLIENT_COLS, list_all_clients(), "Sin clientes registrados.")
        if sub == "prospectos":
            from database.prospects_db import list_all_prospects
            return _table_partial(CLIENT_COLS, list_all_prospects(), "Sin prospectos registrados.")
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))
    abort(404)


def _render_sitios():
    try:
        from database.clients_db import list_all_clients
        from database.monitoring_sites_db import list_monitoring_sites

        client_names = {c["id"]: c["name"] for c in list_all_clients()}
        rows = []
        for s in list_monitoring_sites():
            rows.append({
                "display_name": s.get("display_name") or s.get("site_id"),
                "client_name": client_names.get(s.get("client_id"), "—"),
                "brand": s.get("brand"),
                "active": s.get("active"),
            })
        return _table_partial(SITE_COLS, rows, "Sin sitios registrados.")
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))


def _render_ajustes():
    try:
        from wizard.state import get_bank_info, get_company_info

        return render_template(
            "admin/_ajustes.html",
            company=get_company_info(),
            bank=get_bank_info(),
        )
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))
