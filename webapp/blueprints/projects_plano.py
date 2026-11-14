from __future__ import annotations
"""Plano de taller tab — where the equipment hangs on one wall and the smallest wall that holds it (PDF, one sheet).

The equipment, the Chint boxes, the load centers and the Lynx bars come from the same design and materials list the Lista and Unifilar tabs
read; the sizes come from the datasheets stored in the catalog (`plano/design.py`). The user types the proposed wall (metres) and the tool says
whether it fits. The answers live in `projects.tech_spec["plano"]`.
"""
from io import BytesIO

from flask import Response, render_template, request

from materials import engine
from plano import generate_plano, service


def _inputs(project: dict):
    from webapp.blueprints import projects_design

    d = projects_design.load(project)
    if d["empty"]:
        return d, None, None
    result = engine.build_list(d["eq"], d["wiring"], d["spec"], engine.layout_from_blob(d["blob"]), project.get("system_type"))
    lines = [ln for ln in result["lines"] if ln["qty"]]
    answers = service.clean_answers((d["spec"] or {}).get("plano"))
    return d, lines, answers


def _pdf_name(project: dict) -> str:
    safe = "".join(ch for ch in (project.get("client_name") or "Proyecto").replace(" ", "_") if ch.isalnum() or ch == "_") or "Proyecto"
    return f"Proyecto_{safe}_Plano_de_taller_RevA.pdf"


def render_panel(ctx: dict) -> str:
    project = ctx["project"]
    d, lines, answers = _inputs(project)
    if d["empty"]:
        return render_template("projects/_plano.html", pid=project["id"], empty=d["empty"])
    comp = service.compute(project, d, lines, answers)
    return render_template("projects/_plano.html", pid=project["id"], empty=None, answers=answers, comp=comp, pdf_name=_pdf_name(project))


def register(bp):
    @bp.route("/<pid>/plano/guardar", methods=["POST"])
    def plano_guardar(pid):
        from database.projects_db import get_project, update_tech_spec
        from webapp.blueprints.projects_common import detail_ctx

        project = get_project(pid)
        if not project:
            return render_template("admin/_error.html", message="Proyecto no encontrado.")
        spec = dict(project.get("tech_spec") or {})
        spec["plano"] = service.answers_from_form(request.form)
        update_tech_spec(pid, spec)
        return render_panel(detail_ctx(pid, active_tab="plano"))

    @bp.route("/<pid>/plano.pdf")
    def plano_pdf(pid):
        from database.projects_db import get_project

        project = get_project(pid)
        if not project:
            return Response("Proyecto no encontrado.", status=404)
        d, lines, answers = _inputs(project)
        if d["empty"]:
            return Response(d["empty"], status=409)
        comp = service.compute(project, d, lines, answers)
        out = BytesIO()
        generate_plano.build(service.pdf_data(project, d, comp), out)
        return Response(out.getvalue(), mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{_pdf_name(project)}"'})
