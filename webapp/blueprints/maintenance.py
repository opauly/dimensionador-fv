from __future__ import annotations
"""Mantenimiento section: site register & preventive-maintenance scheduler —
port of pages/07_maintenance.py onto Flask/Jinja2/htmx (Phase 21).

Step 1 scope (see PLAN_PHASE21_MAINTENANCE_JINJA.md, "Step 1 — Blueprint
shell + Resumen tab"): the blueprint, tab dispatch and a fully working,
read-only Resumen tab (webapp/blueprints/maintenance_overview.py). Calendario
anual and Configurar propiedades render "en construcción" placeholders until
Step 3. The property detail view (credentials, visit logging, site linking)
is Step 2 and does not exist yet — there is deliberately no
/propiedad/<pid> route in this file.

This file owns routing + tab dispatch only, mirroring admin.py: one module
per tab owns that tab's logic.
"""
from flask import Blueprint, abort, render_template, request

from webapp.blueprints import maintenance_overview

bp = Blueprint("maintenance", __name__, url_prefix="/mantenimiento")

SECTIONS = {
    "resumen": {"label": "Resumen", "endpoint": "maintenance.index"},
    "calendario": {"label": "Calendario anual", "endpoint": "maintenance.calendario"},
    "configurar": {"label": "Configurar propiedades", "endpoint": "maintenance.configurar"},
}
SECTION_ORDER = ["resumen", "calendario", "configurar"]


def _render(active_section: str, panel_html: str):
    if request.headers.get("HX-Request"):
        return panel_html
    return render_template(
        "maintenance/page.html",
        sections=SECTION_ORDER, section_meta=SECTIONS, active_section=active_section,
        panel_html=panel_html,
    )


def _render_panel(section: str) -> str:
    if section == "resumen":
        return maintenance_overview.render_overview_panel()
    if section in ("calendario", "configurar"):
        return render_template("maintenance/_placeholder.html", label=SECTIONS[section]["label"])
    abort(404)


@bp.route("/")
def index():
    return _render("resumen", _render_panel("resumen"))


@bp.route("/calendario")
def calendario():
    return _render("calendario", _render_panel("calendario"))


@bp.route("/configurar")
def configurar():
    return _render("configurar", _render_panel("configurar"))
