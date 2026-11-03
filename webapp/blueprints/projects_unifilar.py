from __future__ import annotations
"""Unifilar tab — the single-line diagram (PDF, one sheet) of an AC-coupled hybrid project.

The drawing is `unifilar/generate_unifilar.py` (the `unifilar-hibrido-ac` skill); its configuration is
built from the same sized design the Técnico tab and the materials list read
(`unifilar/config_builder.py`), so a gauge or breaker cannot differ between the plan and the purchase
list. The two questions the design cannot answer (grid injection, DC bus with or without Lynx
Distributor) are asked here and kept in `projects.tech_spec["unifilar"]`; engineering checks are shown
on screen and never drawn inside the PDF.
"""
from io import BytesIO

from flask import Response, render_template, url_for

from unifilar import config_builder as CB


def _inputs(project: dict):
    from webapp.blueprints import projects_design

    d = projects_design.load(project)
    spec = d["spec"]
    answers = CB.clean_answers(spec.get("unifilar"))
    string_a = ((spec.get("materials") or {}).get("options") or {}).get("string_breaker_a")
    return d, answers, string_a


def render_panel(ctx: dict, *, message: str | None = None) -> str:
    project = ctx["project"]
    d, answers, string_a = _inputs(project)
    if d["empty"]:
        return render_template("projects/_unifilar.html", pid=project["id"], empty=d["empty"])
    cfg, problems = CB.build_config(project, d, answers, string_a)
    return render_template(
        "projects/_unifilar.html", pid=project["id"], empty=None, answers=answers, cfg=cfg, problems=problems,
        export_choices=CB.EXPORT_CHOICES, lynx_choices=CB.LYNX_CHOICES, message=message,
        pdf_name=_pdf_name(project, d) if cfg else None, ready=cfg is not None,
    )


def _pdf_name(project: dict, d: dict) -> str:
    site = d["blob"].get("site") or {}
    clean = lambda s: "".join(ch for ch in (s or "").replace(" ", "_") if ch.isalnum() or ch == "_")  # noqa: E731
    parts = [clean(project.get("client_name") or "Proyecto"), clean(site.get("city") or "")]
    return "Proyecto_" + "_".join(p for p in parts if p) + "_Unifilar_RevA.pdf"


def register(bp):
    from flask import request

    @bp.route("/<pid>/unifilar/guardar", methods=["POST"])
    def unifilar_guardar(pid):
        from database.projects_db import get_project, update_tech_spec
        from webapp.blueprints.projects_common import detail_ctx

        project = get_project(pid)
        if not project:
            return render_template("admin/_error.html", message="Proyecto no encontrado.")
        spec = dict(project.get("tech_spec") or {})
        spec["unifilar"] = CB.answers_from_form(request.form)
        update_tech_spec(pid, spec)
        return render_panel(detail_ctx(pid, active_tab="unifilar"))

    @bp.route("/<pid>/unifilar.pdf")
    def unifilar_pdf(pid):
        from database.projects_db import get_project
        from unifilar.generate_unifilar import build

        project = get_project(pid)
        if not project:
            return Response("Proyecto no encontrado.", status=404)
        d, answers, string_a = _inputs(project)
        if d["empty"]:
            return Response(d["empty"], status=409)
        cfg, problems = CB.build_config(project, d, answers, string_a)
        if cfg is None:
            return Response("No se puede generar el unifilar: " + " ".join(problems["blockers"]), status=409)
        out = BytesIO()
        build(cfg, out)
        return Response(out.getvalue(), mimetype="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{_pdf_name(project, d)}"'})
