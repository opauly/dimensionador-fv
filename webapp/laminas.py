"""The three engineering sheets in ONE pdf, in delivery order: Diagrama unifilar (hoja 1), Plano de techo (2) and Plano de taller (3).

Each sheet is built by the same code its own download uses; this module only collects them and joins them with bookmarks. The separate downloads stay.
`ValueError` carries a user-facing reason when a sheet cannot be built (no aerial photo yet, a blocking question in the unifilar, ...).
"""
from __future__ import annotations

import io
from io import BytesIO

ORDER = ("unifilar", "techo", "taller")
LABELS = {"unifilar": "Diagrama unifilar", "techo": "Plano de techo", "taller": "Plano de taller"}


def merge(parts: list[tuple[str, bytes]], title: str) -> bytes:
    """Join pdfs (label, bytes) into one, with a bookmark per sheet."""
    from pypdf import PdfReader, PdfWriter

    w = PdfWriter()
    for label, data in parts:
        start = len(w.pages)
        for page in PdfReader(io.BytesIO(data)).pages:
            w.add_page(page)
        w.add_outline_item(label, start)
    w.add_metadata({"/Title": title, "/Author": "Pauly y Compañía Ingenieros y Arquitectos S.A."})
    out = BytesIO()
    w.write(out)
    return out.getvalue()


def _unifilar(project: dict, d: dict, answers: dict, string_a) -> bytes:
    from unifilar import config_builder as CB
    from unifilar.generate_unifilar import build

    cfg, problems = CB.build_config(project, d, answers, string_a)
    if cfg is None:
        raise ValueError("No se puede generar el unifilar: " + " ".join(problems["blockers"]))
    out = BytesIO()
    build(cfg, out)
    return out.getvalue()


def _taller(project: dict, d: dict, lines: list, answers: dict) -> bytes:
    from plano import generate_plano, service

    comp = service.compute(project, d, lines, answers)
    out = BytesIO()
    generate_plano.build(service.pdf_data(project, d, comp), out)
    return out.getvalue()


def for_project(pid: str) -> tuple[bytes, str]:
    """(pdf, client name) for a project."""
    from database.projects_db import get_project
    from webapp.blueprints import projects_plano, projects_unifilar, techo

    project = get_project(pid)
    if not project:
        raise ValueError("Proyecto no encontrado.")
    d, answers, string_a = projects_unifilar._inputs(project)
    if d["empty"]:
        raise ValueError(d["empty"])
    pd, lines, plano_answers = projects_plano._inputs(project)
    parts = [(LABELS["unifilar"], _unifilar(project, d, answers, string_a)),
             (LABELS["techo"], techo.pdf_bytes(techo._ctx("p", pid))),
             (LABELS["taller"], _taller(project, pd, lines, plano_answers))]
    name = project.get("client_name") or "Proyecto"
    return merge(parts, f"{name} - Láminas"), name


def for_version(vid: str, args=None) -> tuple[bytes, str]:
    """(pdf, client name) for a quote version, built through the same virtual project the «Ver» pages use. `args` are the answers the Ver pages keep in
    the query string (injection to the grid, wall size): without them the unifilar may ask for the injection choice first."""
    args = args or {}
    from webapp.blueprints import documentos, techo

    version, proposal, project, d = documentos._load(vid)
    if d["empty"]:
        raise ValueError(d["empty"])
    lines = [ln for ln in documentos._lista(project, d)["lines"] if ln["qty"]]
    try:
        unifilar = _unifilar(project, d, documentos._unifilar_answers(args), None)
    except ValueError as exc:
        raise ValueError(f"{exc} (En una cotización esa respuesta no se guarda: el paquete completo se arma desde el proyecto, o agrega ?export=grid_zero / ?export=inyeccion a la dirección.)") from exc
    parts = [(LABELS["unifilar"], unifilar),
             (LABELS["techo"], techo.pdf_bytes(techo._ctx("c", vid))),
             (LABELS["taller"], _taller(project, d, lines, documentos._plano_answers(args)))]
    name = project.get("client_name") or "Cotización"
    return merge(parts, f"{name} - Láminas"), name
