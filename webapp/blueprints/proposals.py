"""Proposals list + detail panel + version lifecycle — port of
pages/01_proposals.py's table, search/filter bar, "Generar PDF de prueba" dev
panel (_render_test_pdf_panel there), and _render_detail_panel()'s expandable
row (status transitions, Continuar/Nueva versión, per-version PDF affordance).

Scope (Phase 20 Step 2 — see PLAN_PHASE20_PROPOSALS_JINJA.md): list + filter +
sample-PDF harness (Step 1) plus the detail panel and version lifecycle (this
step). The wizard itself (Step 3+) and the Projects module are not built here:
- "Continuar" links straight to /cotizaciones/asistente/<vid>/paso/<n>, and
  "Nueva versión" 303s there too — that blueprint doesn't exist until Step 3,
  so both 404 for now. That is expected; the routes are wired correctly so
  Step 3 only needs to add the target.
- "Ver proyecto →" links to `url_for("projects.detalle", ...)` and "Mover a
  Proyecto" hx-gets `url_for("projects.promover_form", ...)` — the Projects
  blueprint was a stub when this module was first built (§0.3 Q4), but Phase
  22 (PLAN_PHASE22_PROJECTS_JINJA.md §1.9) has since built it out and wired
  both here for real.

Status/system-type labels, colours and the search+status filtering logic are
copied verbatim from pages/01_proposals.py (STATUS_BADGE / STATUS_DOT /
SYSTEM_TYPE_LABELS / FILTER_MAP / STATUS_TRANSITIONS) so the two apps show
identical rows and identical status flows for the same Supabase data.
Streamlit's page is unmodified and stays the reference.
"""
from __future__ import annotations

from io import BytesIO

from flask import Blueprint, abort, redirect, render_template, request, send_file, url_for

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

# Valid next states for each status — enforces a directed flow, no free-form
# changes. Copied verbatim from pages/01_proposals.py.
STATUS_TRANSITIONS: dict[str, list[tuple[str, str]]] = {
    "draft":     [("active", "→ Enviada")],
    "active":    [("won", "✓ Ganada"), ("lost", "✕ Perdida"), ("cancelled", "✕ Cancelar"), ("draft", "← Borrador")],
    "won":       [],
    "lost":      [("draft", "↺ Borrador")],
    "cancelled": [("draft", "↺ Borrador")],
}

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


# ── Detail panel + version lifecycle (Phase 20 Step 2) ─────────────────────


def _signed_url(pdf_path: str) -> str | None:
    """Port of pages/01_proposals.py:_signed_url() — same bucket, same TTL."""
    try:
        from database.supabase_client import get_client

        resp = get_client().storage.from_("solar-tool").create_signed_url(pdf_path, 3600)
        return resp.get("signedURL") or resp.get("signedUrl")
    except Exception:
        return None


def _generate_pdf_bytes(vid: str, proposal: dict, vquote: str) -> bytes:
    """Same call shape as pages/01_proposals.py:_generate_pdf_bytes() — the
    single PDF-data-dict builder per §1.8 of the plan. Raises on failure;
    callers turn that into a user-facing error string."""
    from database.proposals_db import get_version
    from proposals.generator import build_from_wizard_blob, generate_pdf

    full_v = get_version(vid)
    blob = (full_v or {}).get("data", {})
    lang = blob.get("meta", {}).get("language", "es")
    # Use the date the version was locked (or created) so archived PDFs show the original date.
    raw_date = (full_v or {}).get("locked_at") or (full_v or {}).get("created_at") or ""
    if raw_date:
        p = raw_date[:10].split("-")  # "2026-07-04" -> ["2026", "07", "04"]
        version_date = f"{p[2]}/{p[1]}/{p[0]}"
    else:
        version_date = None
    data = build_from_wizard_blob(blob, proposal, vquote, version_date=version_date)
    return generate_pdf(data, proposal.get("system_type", "grid_zero"), lang)


def _version_row_ctx(v: dict, proposal: dict) -> dict:
    """Fields for one _version_row.html — mirrors _render_version_row_compact()."""
    from database.proposals_db import format_quote_number

    vpdf = v.get("pdf_path")
    total = v.get("total_usd")
    return {
        "id": v["id"],
        "pid": proposal["id"],
        "vquote": format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), v["version_number"]),
        "locked": v.get("locked", False),
        "sent": v.get("sent_to_client", False),
        "note": v.get("version_note") or "",
        "total_str": f"${total:,.0f}" if total else "—",
        "created": (v.get("created_at") or "")[:10] or "—",
        "pdf_path": vpdf,
        "signed_url": _signed_url(vpdf) if vpdf else None,
        "error": None,
    }


def _detail_ctx(proposal: dict, versions: list[dict], versions_error: str | None = None, message: tuple[str, str] | None = None) -> dict:
    """Everything proposals/_detail.html needs to render — built once and
    reused by every route that renders any part of the detail panel (GET
    detalle, POST estado, POST enviada), per §1.3's build_context rule."""
    from database.proposals_db import format_quote_number

    pid = proposal["id"]
    status = proposal.get("status", "draft")
    cur_vnum = proposal.get("current_version_number", 1)
    cur_ver = next(
        (v for v in versions if v.get("version_number") == cur_vnum),
        versions[-1] if versions else {},
    )
    cur_vid = cur_ver.get("id", "")
    cur_vlocked = cur_ver.get("locked", False)

    # "Continuar" resumes wherever the draft was left — load_draft()'s own
    # fallback (wizard/state.py) is meta.step_reached, defaulting to 1.
    step_reached = 1
    if cur_vid:
        try:
            from database.proposals_db import get_version

            full_v = get_version(cur_vid)
            step_reached = ((full_v or {}).get("data") or {}).get("meta", {}).get("step_reached", 1)
        except Exception:
            pass

    project = None
    project_error = None
    if status == "won":
        try:
            from database.projects_db import get_project_by_proposal

            project = get_project_by_proposal(pid)
        except Exception as exc:
            project_error = str(exc)

    badge_label, badge_bg, badge_fg = STATUS_BADGE.get(status, ("—", "#f1f5f9", "#64748b"))

    return {
        "pid": pid,
        "status": status,
        "badge_label": badge_label,
        "badge_bg": badge_bg,
        "badge_fg": badge_fg,
        "client_name": proposal.get("client_name") or "Sin nombre",
        "sys_label": SYSTEM_TYPE_LABELS.get(proposal.get("system_type", ""), "—"),
        "quote_str": format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), cur_vnum),
        "transitions": [{"status": s, "label": l} for s, l in STATUS_TRANSITIONS.get(status, [])],
        "cur_version_id": cur_vid,
        "cur_version_locked": cur_vlocked,
        # Hardcoded, not url_for() — the wizard blueprint doesn't exist until
        # Step 3 (see module docstring). This is a real 404 today, by design.
        "wizard_step_url": f"/cotizaciones/asistente/{cur_vid}/paso/{step_reached}" if cur_vid else None,
        "versions": [_version_row_ctx(v, proposal) for v in reversed(versions)],
        "versions_error": versions_error,
        "project": project,
        "project_url": url_for("projects.detalle", pid=project["id"]) if project else None,
        "project_error": project_error,
        "message": message,
    }


def _load_detail(pid: str) -> tuple[dict | None, list[dict], str | None]:
    from database.proposals_db import get_proposal, list_versions

    try:
        proposal = get_proposal(pid)
    except Exception:
        # get_proposal()'s .single().execute() raises (rather than returning
        # None) when the id matches no row — only reachable via a stale/
        # tampered URL, since real navigation always passes a real row's id.
        proposal = None
    if not proposal:
        return None, [], None
    try:
        versions = list_versions(pid)
        versions_error = None
    except Exception as exc:
        versions, versions_error = [], str(exc)
    return proposal, versions, versions_error


@bp.route("/<pid>/detalle")
def detalle(pid):
    proposal, versions, versions_error = _load_detail(pid)
    if proposal is None:
        abort(404)
    return render_template("proposals/_detail.html", **_detail_ctx(proposal, versions, versions_error))


@bp.route("/<pid>/estado", methods=["POST"])
def estado(pid):
    from database.proposals_db import update_proposal_status

    proposal, _versions, _err = _load_detail(pid)
    if proposal is None:
        abort(404)

    next_status = request.form.get("status", "")
    valid_targets = {s for s, _ in STATUS_TRANSITIONS.get(proposal.get("status", "draft"), [])}

    message = None
    if next_status in valid_targets:
        try:
            update_proposal_status(pid, next_status)
        except Exception as exc:
            message = ("error", f"Error: {exc}")
        else:
            if next_status == "won":
                prospect_id = proposal.get("prospect_id")
                if prospect_id:
                    from database.clients_db import promote_prospect

                    try:
                        promote_prospect(prospect_id)
                        message = ("info", "🎉 Propuesta ganada — cliente movido de Prospectos a Clientes.")
                    except Exception as promo_err:
                        message = ("warn", f"Propuesta ganada, pero no se pudo promover el prospecto: {promo_err}")
                else:
                    message = ("info", "🎉 Propuesta ganada.")

    proposal, versions, versions_error = _load_detail(pid)
    if proposal is None:
        abort(404)
    return render_template("proposals/_detail.html", **_detail_ctx(proposal, versions, versions_error, message))


@bp.route("/<pid>/v/<vid>/pdf", methods=["POST"])
def generar_pdf(pid, vid):
    from database.proposals_db import format_quote_number, get_proposal, get_version, save_pdf_path
    from proposals.generator import upload_pdf

    try:
        proposal = get_proposal(pid)
    except Exception:
        proposal = None
    if not proposal:
        abort(404)
    try:
        full_v = get_version(vid)
    except Exception:
        full_v = None
    if not full_v:
        abort(404)

    vquote = format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), full_v["version_number"])

    error = None
    try:
        pdf_bytes = _generate_pdf_bytes(vid, proposal, vquote)
        path = upload_pdf(pdf_bytes, pid, full_v["version_number"], proposal.get("client_name") or "cliente")
        save_pdf_path(vid, path)
    except Exception as exc:
        error = f"Error generando PDF: {exc}"

    full_v = get_version(vid) or full_v
    ctx = _version_row_ctx(full_v, proposal)
    ctx["error"] = error
    return render_template("proposals/_version_row.html", v=ctx)


@bp.route("/<pid>/v/<vid>/nueva-version", methods=["POST"])
def nueva_version(pid, vid):
    from database.proposals_db import create_version, get_version

    full_v = get_version(vid)
    data = (full_v or {}).get("data", {})
    new_v = create_version(pid, data)
    # Hardcoded — see module docstring; the wizard blueprint lands in Step 3.
    return redirect(f"/cotizaciones/asistente/{new_v['id']}/paso/1", code=303)


@bp.route("/<pid>/v/<vid>/enviada", methods=["POST"])
def enviada(pid, vid):
    """Marks a version sent_to_client (also flips the proposal to "active" —
    see database.proposals_db.mark_version_sent()). In Streamlit this button
    lives on the wizard's Step 8 post-lock actions (wizard/grid_zero.py
    "Marcar como enviada"), not on the list's detail panel — there is no
    equivalent button here yet either. The route is built now, ahead of the
    wizard, so Step 3's Step-8 port only needs to POST to it."""
    from database.proposals_db import mark_version_sent

    mark_version_sent(vid)

    proposal, versions, versions_error = _load_detail(pid)
    if proposal is None:
        abort(404)
    return render_template("proposals/_detail.html", **_detail_ctx(proposal, versions, versions_error))
