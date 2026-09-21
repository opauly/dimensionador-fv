from __future__ import annotations
"""Mantenimiento section: site register & preventive-maintenance scheduler —
port of pages/07_maintenance.py onto Flask/Jinja2/htmx (Phase 21).

Step 1 scope (see PLAN_PHASE21_MAINTENANCE_JINJA.md, "Step 1 — Blueprint
shell + Resumen tab"): the blueprint, tab dispatch and a fully working,
read-only Resumen tab (webapp/blueprints/maintenance_overview.py). Calendario
anual and Configurar propiedades render "en construcción" placeholders until
Step 3.

Step 2 scope ("Property detail (all the write paths)"): the property detail
page and its write routes — visit logging, due-date override reset, site
linking and on-demand credentials — live in
webapp/blueprints/maintenance_detail.py, registered onto this blueprint the
same way admin.py registers admin_sites.register(bp) etc.

Step 3 scope ("Calendario anual + Configurar propiedades"): the yearly
calendar (current-year grid, future-cycle box, historical mode, move/reset
picker) lives in webapp/blueprints/maintenance_calendar.py; the property
setup tools (seed, create, merge, delete) live in
webapp/blueprints/maintenance_setup.py. Both register their write routes onto
this blueprint the same way maintenance_detail does.

This file owns tab routing + dispatch only, mirroring admin.py: one module
per tab/section owns that section's logic.
"""
from datetime import date

from flask import Blueprint, render_template, request

from webapp.blueprints import maintenance_calendar, maintenance_detail, maintenance_overview, maintenance_setup

bp = Blueprint("maintenance", __name__, url_prefix="/mantenimiento")
maintenance_detail.register(bp)
maintenance_calendar.register(bp)
maintenance_setup.register(bp)

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


@bp.route("/")
def index():
    return _render("resumen", maintenance_overview.render_overview_panel())


@bp.route("/calendario")
def calendario():
    year_raw = request.args.get("anio")
    try:
        year = int(year_raw) if year_raw else date.today().year
    except ValueError:
        year = date.today().year
    return _render("calendario", maintenance_calendar.render_calendar_panel(year, error=request.args.get("error")))


@bp.route("/configurar")
def configurar():
    panel = maintenance_setup.render_setup_panel(
        created=request.args.get("created"),
        seeded=request.args.get("seeded"),
        merged=request.args.get("merged"),
        keep=request.args.get("keep"),
        error=request.args.get("error"),
    )
    return _render("configurar", panel)
