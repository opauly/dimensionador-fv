"""Admin section: equipment catalog, services, ARESEP tariffs, clients,
sites and settings. Full CRUD parity with pages/05_admin.py, split across
one module per section (admin_equipment.py, admin_services.py, etc.) —
this file owns routing/dispatch, the modules own each section's logic.

Not ported: equipment/AI datasheet extraction ("Extraer de datasheet"),
and Ajustes' logo/signature upload (depends on wizard.state functions —
get_asset_b64/save_asset — that don't exist yet in this snapshot).
"""
from __future__ import annotations

from flask import Blueprint, abort, render_template

from webapp.blueprints import (
    admin_aresep, admin_clients, admin_equipment, admin_services, admin_settings, admin_sites,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")
admin_equipment.register(bp)
admin_services.register(bp)
admin_clients.register(bp)
admin_sites.register(bp)
admin_settings.register(bp)
admin_aresep.register(bp)

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


CLIENT_COLS = [("name", "Nombre", None), ("empresa", "Empresa", None),
               ("phone", "Teléfono", None), ("email", "Correo", None)]
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
    from flask import request

    try:
        return admin_equipment.render_equipos_panel(sub, request)
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))


def _render_servicios():
    from flask import request

    try:
        return admin_services.render_services_panel(request)
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))


def _render_aresep(sub):
    if sub == "actualizar":
        try:
            return admin_aresep.render_aresep_actualizar()
        except Exception as exc:
            return render_template("admin/_error.html", message=str(exc))
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
    from flask import request

    try:
        if sub == "clientes":
            return admin_clients.render_clients_panel(request)
        if sub == "prospectos":
            from database.prospects_db import list_all_prospects
            return _table_partial(CLIENT_COLS, list_all_prospects(), "Sin prospectos registrados.")
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))
    abort(404)


def _render_sitios():
    from flask import request

    try:
        return admin_sites.render_sites_panel(request)
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))


def _render_ajustes():
    try:
        return admin_settings.render_settings_panel()
    except Exception as exc:
        return render_template("admin/_error.html", message=str(exc))
