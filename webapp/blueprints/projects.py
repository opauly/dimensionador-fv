from __future__ import annotations
"""Proyectos section: projects list + manual creation + (from Step 3 on) the
project financial workspace — port of pages/03_projects.py /
pages/04_project_detail.py onto Flask/Jinja2/htmx (Phase 22,
PLAN_PHASE22_PROJECTS_JINJA.md).

Step 1 scope ("Blueprint shell + projects list (read-only) + nav cutover"):
the blueprint, the list route with its `?estado=` status filter, and the nav
cutover away from `dashboard.stub`.

Step 2 scope ("Manual project creation", plan §1.4 item 7 / §1.6): the
"+ Nuevo proyecto" form fragment (`GET /nuevo`), its client typeahead
(`GET /nuevo/clientes`, `GET /nuevo/clientes/seleccionar`) and the create
POST (`POST /`) that calls `create_project_manual(...)` and 303s to
`/proyectos/<new_id>`. That target route (the detail page, Step 3) does not
exist yet, so the redirect is hardcoded (`f"/proyectos/{...}"`, not
`url_for()`) exactly as `webapp/templates/projects/_list.html`'s own row
link already is (plan §1.9 / Step 1's scope note) — it will 404 until Step 3
lands, which is expected. The detail page and its nine tabs (Steps 3-9)
remain out of scope here.

This file owns list/create routing + (later) tab dispatch only, mirroring
`webapp/blueprints/maintenance.py`: one module per tab/section owns that
section's logic and registers onto this same `bp` via `register(bp)` — never
a second `Blueprint` instance, or the nav's `request.blueprint == 'projects'`
rule silently breaks for that module's routes only (Phase 21 §5.5 finding
#1, restated in plan §1.7 for this phase's six companion modules).
"""
from flask import Blueprint, redirect, render_template, request

from webapp.blueprints.projects_common import FILTER_MAP, FILTER_OPTIONS, STATUS_BADGE, fmt_usd

bp = Blueprint("projects", __name__, url_prefix="/proyectos")


def _parse_money(value) -> float:
    """`st.number_input(..., min_value=0.0)`'s server-side equivalent: blank
    or unparseable -> 0.0, negative clamped to 0.0."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return 0.0
    return amount if amount > 0 else 0.0


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


# ── Manual project creation (Step 2) ────────────────────────────────────────

def _render_nuevo_form(*, error: str | None = None, client_name: str = "", client_id: str | None = None,
                        system_type: str | None = None, contract_usd: str = "0",
                        contract_iva_usd: str = "0", notes: str = "") -> str:
    """Renders `projects/_nuevo.html` — used both for a fresh `GET /nuevo`
    and, on a validation/DB error, by `crear()` to re-render the same
    fragment with every posted value preserved and `error` set (plan §1.2's
    round-trip rule; precedent: `webapp/blueprints/maintenance_setup.py:
    propiedades_crear()`)."""
    from config import SYSTEM_TYPES, SYSTEM_TYPE_LABELS

    return render_template(
        "projects/_nuevo.html",
        error=error,
        client_name=client_name,
        client_id=client_id or "",
        system_type=system_type if system_type in SYSTEM_TYPES else SYSTEM_TYPES[0],
        contract_usd=contract_usd,
        contract_iva_usd=contract_iva_usd,
        notes=notes,
        system_type_options=[(s, SYSTEM_TYPE_LABELS.get(s, s)) for s in SYSTEM_TYPES],
    )


@bp.route("/nuevo")
def nuevo():
    """`+ Nuevo proyecto` toggle target (plan §1.6 pattern 2). `?cancel=1`
    (sent by the fragment's own "Cancelar" button) collapses it back to the
    empty `#nuevo` div instead of opening the form."""
    if request.args.get("cancel"):
        return render_template("projects/_nuevo_closed.html")
    return _render_nuevo_form()


@bp.route("/nuevo/clientes")
def nuevo_clientes():
    """Client typeahead (plan §1.6 pattern 3, `keyup changed delay:300ms`) —
    port of `search_clients(query)` (pages/03_projects.py L155), same 2-char
    minimum enforced by `search_clients` itself."""
    from database.clients_db import search_clients

    query = (request.args.get("client_name") or "").strip()
    matches = search_clients(query) if query else []
    return render_template("projects/_nuevo_clientes.html", q=query, matches=matches)


@bp.route("/nuevo/clientes/seleccionar")
def nuevo_clientes_seleccionar():
    """A typeahead row was clicked (a real match, carrying `client_id`, or
    the always-first "usar texto libre" option, carrying none) — re-renders
    `#client-field` with the chosen name filled in, exactly as
    `wizard.clientes_seleccionar` re-renders `#s1-fields`."""
    client_id = (request.args.get("client_id") or "").strip() or None
    name = (request.args.get("name") or "").strip()
    return render_template("projects/_client_field.html", client_name=name, client_id=client_id)


@bp.route("/", methods=["POST"])
def crear():
    """`Crear proyecto` — port of pages/03_projects.py L190-207. A plain
    form POST + 303 on success (this app's convention for every
    successful write); a blank client name or a `create_project_manual()`
    exception re-renders `_nuevo.html` inline with every other posted field
    preserved, never a 500 (plan §1.4 item 7)."""
    from config import SYSTEM_TYPES
    from database.projects_db import create_project_manual

    form = request.form
    client_name = (form.get("client_name") or "").strip()
    client_id = (form.get("client_id") or "").strip() or None
    system_type = form.get("system_type") or SYSTEM_TYPES[0]
    if system_type not in SYSTEM_TYPES:
        system_type = SYSTEM_TYPES[0]
    contract_usd_raw = form.get("contract_usd") or "0"
    contract_iva_usd_raw = form.get("contract_iva_usd") or "0"
    notes_raw = form.get("notes") or ""

    if not client_name:
        return _render_nuevo_form(
            error="Ingresa un nombre de cliente.",
            client_name=client_name, client_id=client_id, system_type=system_type,
            contract_usd=contract_usd_raw, contract_iva_usd=contract_iva_usd_raw, notes=notes_raw,
        )

    try:
        project = create_project_manual(
            client_name=client_name,
            system_type=system_type,
            contract_usd=_parse_money(contract_usd_raw),
            contract_iva_usd=_parse_money(contract_iva_usd_raw),
            client_id=client_id,
            notes=notes_raw.strip() or None,
        )
    except Exception as exc:
        return _render_nuevo_form(
            error=f"Error: {exc}",
            client_name=client_name, client_id=client_id, system_type=system_type,
            contract_usd=contract_usd_raw, contract_iva_usd=contract_iva_usd_raw, notes=notes_raw,
        )

    # /proyectos/<id> (the detail page) doesn't exist until Step 3 — hardcoded
    # for the same reason _list.html's own row link is (plan §1.9 note).
    return redirect(f"/proyectos/{project['id']}", code=303)
