"""Dashboard (port of the Streamlit app.py landing page) and nav stubs
for pages not yet migrated off Streamlit.
"""
from flask import Blueprint, abort, render_template

bp = Blueprint("dashboard", __name__)

PHASES = [
    ("Fase 0 — Fundación", "Completa"),
    ("Fase 1 — Motor PDF", "Completa"),
    ("Fase 2 — Asistente Grid Zero", "Completa"),
    ("Fase 3 — Gestión de cotizaciones", "Completa"),
    ("Fase 4 — Funciones AI", "Pendiente"),
    ("Fase 5 — Off-Grid + Híbrido", "Pendiente"),
    ("Fase 6 — Módulo Proyectos", "Pendiente"),
    ("Fase 7 — Admin + Pulido", "Pendiente"),
    ("Fase 8 — QA + Entrega", "Pendiente"),
]

# Nav entries not yet ported to this branch — each renders a stub page so the
# sidebar shape matches the target app while pages migrate one at a time.
STUBS = {
    "proposals": "Cotizaciones",
    "projects": "Proyectos",
    "maintenance": "Mantenimiento",
}


@bp.route("/")
def index():
    drafts_count = "—"
    sent_count = "—"
    try:
        from database.proposals_db import list_proposals

        drafts_count = len(list_proposals(status="draft"))
        sent_count = len(list_proposals(status="active"))
    except Exception:
        pass

    active_count = "—"
    active_received_pct = "—"
    active_profit_pct = "—"
    try:
        from calculations.project_finance import summarize
        from database.projects_db import get_project_bundle, list_projects

        active_projects = list_projects(status="active")
        active_count = len(active_projects)

        agg_ingresos = agg_recibido = agg_utilidad = 0.0
        for project in active_projects:
            bundle = get_project_bundle(project["id"])
            s = summarize(
                bundle["project"], bundle["payments"],
                bundle["expenses"], bundle["labor"], bundle["extras"],
            )
            agg_ingresos += s["ingresos_total"]
            agg_recibido += s["recibido"]
            agg_utilidad += s["utilidad_neta"]

        if agg_ingresos:
            active_received_pct = f"{agg_recibido / agg_ingresos * 100:.0f}%"
            active_profit_pct = f"{agg_utilidad / agg_ingresos * 100:.0f}%"
    except Exception:
        pass

    return render_template(
        "dashboard.html",
        drafts_count=drafts_count,
        sent_count=sent_count,
        active_count=active_count,
        active_received_pct=active_received_pct,
        active_profit_pct=active_profit_pct,
        phases=PHASES,
    )


@bp.route("/<section>")
def stub(section):
    if section not in STUBS:
        abort(404)
    return render_template("stub.html", section_label=STUBS[section])
