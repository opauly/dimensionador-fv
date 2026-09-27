"""Dashboard (port of the Streamlit app.py landing page) and nav stubs
for pages not yet migrated off Streamlit.
"""
from flask import Blueprint, abort, render_template

bp = Blueprint("dashboard", __name__)

# Corrected 2026-09-27 — this list had gone stale the same way PHASES.md's
# own table went stale before its 2026-09-02 correction (see that file's own
# note): it stopped at Fase 8 and never picked up Fase 10 (Mantenimiento,
# part of this same app) or Fases 20–23 (the Flask/Jinja2 port + Phase 23's
# margin mechanism, all live on this exact branch). Fases 9, 12–19 are
# VRM Monitor — a separate product with its own UI — and are deliberately
# left off this app's own front page; see PHASES.md for that product's
# phase history. Three statuses now, not two ("Parcial" added) — Fases 6/7
# were previously shown as "Completa"/"Pendiente" respectively, neither of
# which was accurate (PHASES.md's own corrected rows call both "🔶 Partial").
PHASES = [
    ("Fase 0 — Fundación", "Completa"),
    ("Fase 1 — Motor PDF", "Completa"),
    ("Fase 2 — Asistente Grid Zero", "Completa"),
    ("Fase 3 — Gestión de cotizaciones", "Completa"),
    ("Fase 4 — Funciones AI", "Completa"),
    ("Fase 5 — Off-Grid + Híbrido", "Completa"),
    ("Fase 6 — Módulo Proyectos", "Parcial"),
    ("Fase 7 — Admin + Pulido", "Parcial"),
    ("Fase 8 — QA + Entrega", "Pendiente"),
    ("Fase 10 — Mantenimiento (registro de sitios)", "Completa"),
    ("Fase 11 — Calibración de diseño desde datos de flota", "Pendiente"),
    ("Fase 20 — Cotizaciones: puerto a Flask/Jinja2", "Completa"),
    ("Fase 21 — Mantenimiento: puerto a Flask/Jinja2", "Completa"),
    ("Fase 22 — Proyectos: puerto a Flask/Jinja2 + Facturación/Pagos", "Completa"),
    ("Fase 23 — Distribución de utilidad (margen único)", "Completa"),
]

# Nav entries not yet ported to this branch — each renders a stub page so the
# sidebar shape matches the target app while pages migrate one at a time.
# "proposals" is ported (webapp/blueprints/proposals.py); "maintenance" is
# ported as of Phase 21 (webapp/blueprints/maintenance.py); "projects" is
# ported as of Phase 22 Step 1 (webapp/blueprints/projects.py) and no longer
# listed here. This dict is empty until a future nav entry is stubbed again;
# the route below stays (Phase 22 §2 Step 10's working assumption) since
# removing it is a separate, no-benefit cleanup.
STUBS = {}


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
