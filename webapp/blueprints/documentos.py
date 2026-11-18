from __future__ import annotations
"""«Ver» on a quote version — one small menu (PDF, Lista de materiales, Unifilar, Plano de taller, Wizard) and read-only previews.

The engineering documents (Lista, Unifilar, Plano) normally exist only inside a Proyecto. Here they are built from the quote
version itself through a *virtual project* (nothing is saved, no project is created) using the very same code the Proyectos tabs use
(`projects_design.load`, `materials.engine`, `unifilar.config_builder`, `plano.service`), so what you see before «Ganada» is what the
project will show afterwards. Answers the design cannot give (grid injection, wall size) come from the page's query string and are
never stored.
"""
from io import BytesIO

from flask import Blueprint, Response, abort, render_template, request, url_for

bp = Blueprint("documentos", __name__, url_prefix="/documentos")


def _load(vid: str):
    """(version, proposal, virtual_project, design) — 404 for an unknown version."""
    from database.proposals_db import get_proposal, get_version
    from webapp.blueprints import projects_design
    from wizard import draft

    try:
        version = get_version(vid)
    except Exception:                                   # noqa: BLE001
        version = None
    if not version:
        abort(404)
    proposal = get_proposal(version["proposal_id"]) or {}
    blob = draft.load(vid)
    project = {
        "id": None, "proposal_id": version["proposal_id"], "client_name": proposal.get("client_name") or (blob.get("client") or {}).get("name"),
        "system_type": (blob.get("meta") or {}).get("system_type") or proposal.get("system_type"), "tech_spec": {"version_id": vid},
    }
    return version, proposal, project, projects_design.load(project)


def _vquote(version: dict, proposal: dict) -> str:
    from database.proposals_db import format_quote_number

    return format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), version.get("version_number", 1))


def _safe(name: str | None) -> str:
    return "".join(ch for ch in (name or "Cotizacion").replace(" ", "_") if ch.isalnum() or ch == "_") or "Cotizacion"


def _unifilar_answers(args) -> dict:
    from unifilar import config_builder as CB

    return CB.clean_answers({"export": args.get("export") or None, "revision": args.get("revision") or "A", "draft": True})


def _plano_answers(args) -> dict:
    from plano import service

    return service.clean_answers({"wall_w_m": args.get("wall_w_m"), "wall_h_m": args.get("wall_h_m"), "margin_mm": args.get("margin_mm")})


def _lista(project: dict, d: dict):
    from materials import engine

    return engine.build_list(d["eq"], d["wiring"], d["spec"], engine.layout_from_blob(d["blob"]), project.get("system_type"))


# ── menu (modal) ─────────────────────────────────────────────────────────


@bp.route("/<vid>/menu")
def menu(vid):
    from webapp.blueprints.proposals import _signed_url

    version, proposal, project, d = _load(vid)
    pdf_url = _signed_url(version["pdf_path"]) if version.get("pdf_path") else None
    items = [
        {"icon": "📄", "title": "Propuesta (PDF)", "sub": "Lo que ve el cliente" if pdf_url else "Esta versión aún no tiene PDF generado",
         "href": pdf_url, "new_tab": True},
        {"icon": "🧾", "title": "Lista de materiales (BOM)", "sub": d["empty"] or "Lo que se compra; descarga en PDF o Excel",
         "href": None if d["empty"] else url_for("documentos.lista", vid=vid)},
        {"icon": "⚡", "title": "Diagrama unifilar", "sub": d["empty"] or "Dibujo de una hoja con calibres y breakers",
         "href": None if d["empty"] else url_for("documentos.unifilar", vid=vid)},
        {"icon": "📐", "title": "Plano de taller", "sub": d["empty"] or "Acomodo de equipos en una pared y pared mínima",
         "href": None if d["empty"] else url_for("documentos.plano", vid=vid)},
        {"icon": "👁", "title": "Cotización completa (wizard)", "sub": "Los 9 pasos, solo lectura",
         "href": url_for("wizard.abrir", vid=vid) if version.get("locked") else None},
    ]
    return render_template("documentos/_menu.html", title=_vquote(version, proposal), client=project.get("client_name") or "", items=items,
                           note="Vista previa: no crea proyecto ni guarda nada.")


@bp.route("/proyecto/<pid>/menu")
def menu_proyecto(pid):
    """Same menu inside Proyectos (its «Ver» button): the project's own, editable pages for the engineering documents."""
    from database.projects_db import get_project
    from webapp.blueprints import projects_design
    from webapp.blueprints.proposals import _signed_url

    project = get_project(pid)
    if not project:
        abort(404)
    d = projects_design.load(project)
    chosen = d.get("chosen") or {}
    pdf_url = _signed_url(chosen["pdf_path"]) if chosen.get("pdf_path") else None
    empty = d["empty"]
    items = [
        {"icon": "📄", "title": "Propuesta (PDF)", "sub": "Lo que ve el cliente" if pdf_url else "La cotización no tiene PDF generado",
         "href": pdf_url, "new_tab": True},
        {"icon": "🧾", "title": "Lista de materiales (BOM)", "sub": empty or "Editable: cantidades, comentarios y extras; descarga en PDF o Excel", "href": None if empty else url_for("projects.lista", pid=pid)},
        {"icon": "⚡", "title": "Diagrama unifilar", "sub": empty or "Editable: responde las preguntas del diseño y descarga el dibujo", "href": None if empty else url_for("projects.unifilar", pid=pid)},
        {"icon": "📐", "title": "Plano de taller", "sub": empty or "Editable: pared, márgenes y acomodo de equipos", "href": None if empty else url_for("projects.plano", pid=pid)},
        {"icon": "👁", "title": "Cotización completa (wizard)", "sub": "Los 9 pasos, solo lectura",
         "href": url_for("wizard.abrir", vid=chosen["id"]) if chosen.get("locked") else None},
    ]
    return render_template("documentos/_menu.html", title=project.get("client_name") or "Proyecto", client="Documentos del proyecto", items=items, note=None)


# ── pages ────────────────────────────────────────────────────────────────


@bp.route("/<vid>/lista")
def lista(vid):
    version, proposal, project, d = _load(vid)
    sections: list[dict] = []
    if not d["empty"]:
        result = _lista(project, d)
        for ln in (x for x in result["lines"] if x["qty"]):
            if not sections or sections[-1]["name"] != ln["section"]:
                sections.append({"name": ln["section"], "groups": []})
            groups = sections[-1]["groups"]
            if not groups or groups[-1]["name"] != (ln["group"] or ""):
                groups.append({"name": ln["group"] or "", "lines": []})
            groups[-1]["lines"].append(ln)
    return render_template("documentos/page.html", vid=vid, active="lista", title=_vquote(version, proposal),
                           client=project.get("client_name") or "", empty=d["empty"], sections=sections)


@bp.route("/<vid>/lista.pdf")
def lista_pdf(vid):
    version, proposal, project, d = _load(vid)
    if d["empty"]:
        return Response(d["empty"], status=409)
    try:
        from materials.export_pdf import build_pdf
    except ModuleNotFoundError:
        return Response("Falta instalar reportlab: pip install -r requirements.txt", status=500)
    name = project.get("client_name") or "Cotización"
    data = build_pdf(_lista(project, d)["lines"], "Solicitud de materiales", f"Cotización {_vquote(version, proposal)} - {name}")
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{_safe(name)}_Lista_de_materiales.pdf"'})


@bp.route("/<vid>/lista.xlsx")
def lista_xlsx(vid):
    from materials.export_xlsx import build_workbook

    version, proposal, project, d = _load(vid)
    if d["empty"]:
        return Response(d["empty"], status=409)
    name = project.get("client_name") or "Cotización"
    data = build_workbook(_lista(project, d)["lines"], f"Solicitud de materiales — {name}")
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{_safe(name)}_Solicitud_de_materiales.xlsx"'})


@bp.route("/<vid>/unifilar")
def unifilar(vid):
    from unifilar import config_builder as CB

    version, proposal, project, d = _load(vid)
    ctx = {}
    if not d["empty"]:
        answers = _unifilar_answers(request.args)
        cfg, problems = CB.build_config(project, d, answers, None)
        kind = CB.drawing_kind(project, d["wiring"])
        ctx = dict(answers=answers, problems=problems, kind=kind, kind_text=CB.KIND_TEXT.get(kind, ""), export_choices=CB.EXPORT_CHOICES,
                   ready=cfg is not None, qs=request.query_string.decode())
    return render_template("documentos/page.html", vid=vid, active="unifilar", title=_vquote(version, proposal),
                           client=project.get("client_name") or "", empty=d["empty"], **ctx)


@bp.route("/<vid>/unifilar.pdf")
def unifilar_pdf(vid):
    from unifilar import config_builder as CB
    from unifilar.generate_unifilar import build

    version, proposal, project, d = _load(vid)
    if d["empty"]:
        return Response(d["empty"], status=409)
    cfg, problems = CB.build_config(project, d, _unifilar_answers(request.args), None)
    if cfg is None:
        return Response("No se puede generar el unifilar: " + " ".join(problems["blockers"]), status=409)
    out = BytesIO()
    build(cfg, out)
    return Response(out.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_safe(project.get("client_name"))}_Unifilar_borrador.pdf"'})


@bp.route("/<vid>/plano")
def plano(vid):
    from plano import service

    version, proposal, project, d = _load(vid)
    ctx = {}
    if not d["empty"]:
        lines = [ln for ln in _lista(project, d)["lines"] if ln["qty"]]
        answers = _plano_answers(request.args)
        ctx = dict(answers=answers, comp=service.compute(project, d, lines, answers), qs=request.query_string.decode())
    return render_template("documentos/page.html", vid=vid, active="plano", title=_vquote(version, proposal),
                           client=project.get("client_name") or "", empty=d["empty"], **ctx)


@bp.route("/<vid>/plano.pdf")
def plano_pdf(vid):
    from plano import generate_plano, service

    version, proposal, project, d = _load(vid)
    if d["empty"]:
        return Response(d["empty"], status=409)
    lines = [ln for ln in _lista(project, d)["lines"] if ln["qty"]]
    comp = service.compute(project, d, lines, _plano_answers(request.args))
    out = BytesIO()
    generate_plano.build(service.pdf_data(project, d, comp), out)
    return Response(out.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_safe(project.get("client_name"))}_Plano_de_taller.pdf"'})
