from __future__ import annotations
"""Proyectos section: projects list + (from Step 3 on) the project financial
workspace — port of pages/03_projects.py / pages/04_project_detail.py onto
Flask/Jinja2/htmx (Phase 22, PLAN_PHASE22_PROJECTS_JINJA.md).

Step 1 scope ("Blueprint shell + projects list (read-only) + nav cutover"):
the blueprint, the list route with its `?estado=` status filter, and the nav
cutover away from `dashboard.stub`. Manual project creation (Step 2), the
detail page and its nine tabs (Steps 3-9) are not built here — the
"+ Nuevo proyecto" button below links to a route (`/proyectos/nuevo`) that
does not exist until Step 2, exactly as `webapp/blueprints/proposals.py`
once hardcoded `/proyectos/<id>` before this blueprint existed (plan §1.9).

This file owns list routing + (later) tab dispatch only, mirroring
`webapp/blueprints/maintenance.py`: one module per tab/section owns that
section's logic and registers onto this same `bp` via `register(bp)` — never
a second `Blueprint` instance, or the nav's `request.blueprint == 'projects'`
rule silently breaks for that module's routes only (Phase 21 §5.5 finding
#1, restated in plan §1.7 for this phase's six companion modules).
"""
from flask import Blueprint, render_template, request

from webapp.blueprints.projects_common import FILTER_MAP, FILTER_OPTIONS, STATUS_BADGE, fmt_usd

bp = Blueprint("projects", __name__, url_prefix="/proyectos")


def _row_ctx(project: dict) -> dict:
    """Display fields for one list row — port of pages/03_projects.py's
    _render_row() (L108-128). client_name/sys_label/contract_str/badge are
    computed here, once, exactly as Streamlit computes them once per row."""
    from config import SYSTEM_TYPE_LABELS

    status = project.get("status", "active")
    badge_label, badge_bg, badge_fg = STATUS_BADGE.get(status, ("—", "#f1f5f9", "#64748b"))
    return {
        "id": project["id"],
        "client_name": project.get("client_name") or "Sin nombre",
        "sys_label": SYSTEM_TYPE_LABELS.get(project.get("system_type", ""), "—"),
        "contract_str": fmt_usd(project.get("contract_usd")),
        "badge_label": badge_label,
        "badge_bg": badge_bg,
        "badge_fg": badge_fg,
    }


def _load_rows(estado: str) -> list[dict]:
    from database.projects_db import list_projects

    # list_projects() already orders created_at desc (projects_db.py) — do
    # not re-sort here (plan §1.4 item 2).
    projects = list_projects(status=FILTER_MAP.get(estado))
    return [_row_ctx(p) for p in projects]


@bp.route("/")
def index():
    estado = request.args.get("estado") or "Todos"
    if estado not in FILTER_MAP:
        estado = "Todos"

    try:
        rows = _load_rows(estado)
        error = None
    except Exception as exc:
        rows, error = [], f"Error cargando proyectos: {exc}"

    panel_html = render_template("projects/_list.html", rows=rows, estado=estado, error=error)

    if request.headers.get("HX-Request"):
        return panel_html

    return render_template(
        "projects/list.html",
        panel_html=panel_html, estado=estado, filter_options=FILTER_OPTIONS,
    )
