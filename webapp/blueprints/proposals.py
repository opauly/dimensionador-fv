"""Proposals list — read-only port of pages/01_proposals.py's table + search/filter
bar, plus the "Generar PDF de prueba" dev panel (_render_test_pdf_panel there).

Scope (Phase 20 Step 1): list + filter + sample-PDF harness only. The expandable
detail panel, status transitions, version lifecycle and the wizard itself are
later steps in PLAN_PHASE20_PROPOSALS_JINJA.md — not built here.

Status/system-type labels, colours and the search+status filtering logic are
copied verbatim from pages/01_proposals.py (STATUS_BADGE / STATUS_DOT /
SYSTEM_TYPE_LABELS / FILTER_MAP) so the two apps show identical rows for the
same Supabase data. Streamlit's page is unmodified and stays the reference.
"""
from __future__ import annotations

from io import BytesIO

from flask import Blueprint, render_template, request, send_file

bp = Blueprint("proposals", __name__, url_prefix="/cotizaciones")

STATUS_DOT = {
    "draft": "#94a3b8",
    "active": "#3b82f6",
    "won": "#22c55e",
    "lost": "#ef4444",
}
STATUS_BADGE = {
    "draft": ("Borrador", "#f1f5f9", "#64748b"),
    "active": ("Enviada", "#dbeafe", "#1d4ed8"),
    "won": ("Ganada", "#dcfce7", "#16a34a"),
    "lost": ("Perdida", "#fee2e2", "#dc2626"),
}
SYSTEM_TYPE_LABELS = {
    "grid_zero": "Grid Zero",
    "off_grid": "Off-Grid",
    "hybrid": "Híbrido",
}
FILTER_OPTIONS = ["Todas", "Borrador", "Enviada", "Ganada", "Perdida"]
FILTER_MAP = {"Todas": None, "Borrador": "draft", "Enviada": "active", "Ganada": "won", "Perdida": "lost"}

# Sample fixture data for the dev PDF harness — same three datasets Streamlit's
# _render_test_pdf_panel() and Step 0's validation both use.
_SAMPLE_TYPES = {
    "grid_zero": "Grid Zero",
    "off_grid": "Off-Grid",
    "hybrid": "Híbrido",
}


def _row(proposal: dict) -> dict:
    """Compute the display fields for one table row — mirrors _render_row()."""
    from database.proposals_db import format_quote_number

    client_name = proposal.get("client_name") or "Sin nombre"
    sys_label = SYSTEM_TYPE_LABELS.get(proposal.get("system_type", ""), "—")
    status = proposal.get("status", "draft")
    cur_vnum = proposal.get("current_version_number", 1)
    updated = (proposal.get("updated_at") or "")[:10] or "—"

    versions_emb = proposal.get("proposal_versions") or []
    cur_ver = next(
        (v for v in versions_emb if v.get("version_number") == cur_vnum),
        versions_emb[-1] if versions_emb else {},
    )
    total_usd = cur_ver.get("total_usd")
    total_str = f"${total_usd:,.0f}" if total_usd else "—"
    quote_str = format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), cur_vnum)
    badge_label, badge_bg, badge_fg = STATUS_BADGE.get(status, ("—", "#f1f5f9", "#64748b"))

    return {
        "id": proposal["id"],
        "client_name": client_name,
        "sys_label": sys_label,
        "status": status,
        "dot_color": STATUS_DOT.get(status, "#94a3b8"),
        "quote_str": quote_str,
        "total_str": total_str,
        "updated": updated,
        "badge_label": badge_label,
        "badge_bg": badge_bg,
        "badge_fg": badge_fg,
    }


def _load_rows(estado: str, q: str) -> list[dict]:
    from database.proposals_db import list_proposals

    proposals = list_proposals(status=FILTER_MAP.get(estado))

    qq = (q or "").strip().lower()
    if qq:
        proposals = [
            p for p in proposals
            if qq in (p.get("client_name") or "").lower()
            or qq in str(p.get("quote_number") or "").lower()
        ]
    return [_row(p) for p in proposals]


@bp.route("/")
def index():
    q = request.args.get("q", "")
    estado = request.args.get("estado") or "Todas"
    if estado not in FILTER_MAP:
        estado = "Todas"

    try:
        rows = _load_rows(estado, q)
        error = None
    except Exception as exc:
        rows, error = [], str(exc)

    return render_template(
        "proposals/page.html",
        rows=rows, q=q, estado=estado, filter_options=FILTER_OPTIONS, error=error,
        sample_types=_SAMPLE_TYPES, tipo="grid_zero",
    )


@bp.route("/filtrar")
def filtrar():
    q = request.args.get("q", "")
    estado = request.args.get("estado") or "Todas"
    if estado not in FILTER_MAP:
        estado = "Todas"

    try:
        rows = _load_rows(estado, q)
        error = None
    except Exception as exc:
        rows, error = [], str(exc)

    return render_template("proposals/_list.html", rows=rows, error=error)


@bp.route("/dev/pdf-muestra")
def dev_pdf():
    tipo = request.args.get("tipo") or "grid_zero"
    if tipo not in _SAMPLE_TYPES:
        tipo = "grid_zero"
    return render_template("proposals/dev_pdf.html", sample_types=_SAMPLE_TYPES, tipo=tipo)


@bp.route("/dev/pdf-muestra/generar")
def dev_pdf_generar():
    """Direct-download route behind the dev panel's ES/EN buttons — calls
    generate_pdf() against the sample fixtures with no wizard/draft involved,
    the fastest smoke test for the PDF engine."""
    from proposals.generator import HYBRID_DATA, JORGE_RAMIREZ_DATA, MARIA_JOSE_DATA, generate_pdf

    tipo = request.args.get("tipo") or "grid_zero"
    lang = request.args.get("lang") or "es"
    if lang not in ("es", "en"):
        lang = "es"

    sample_data = {
        "grid_zero": (MARIA_JOSE_DATA, "muestra_grid_zero"),
        "off_grid": (JORGE_RAMIREZ_DATA, "muestra_off_grid"),
        "hybrid": (HYBRID_DATA, "muestra_hibrido"),
    }
    if tipo not in sample_data:
        tipo = "grid_zero"
    data, filename_base = sample_data[tipo]

    pdf = generate_pdf(data, tipo, lang)
    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{filename_base}_{lang}.pdf",
    )
