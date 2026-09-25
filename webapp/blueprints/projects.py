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
`/proyectos/<new_id>`.

Step 3 scope ("Detail shell + Presupuesto tab, read-only", plan §1.4 items
8-20): the detail page itself — nine tab routes (`GET /<pid>`, `GET /<pid>/
gastos/<categoria>`, `GET /<pid>/mano-de-obra`, `GET /<pid>/facturacion`,
`GET /<pid>/pagos`) dispatching through `projects_common.detail_ctx(pid)`,
plus the status-pill handler (`POST /<pid>/estado`). Only Presupuesto has
real content this step; the other eight tabs render a one-line "en
construcción" placeholder (`projects/_en_construccion.html`) until Steps
5-8 build them out. `crear()`'s redirect and `_list.html`'s row link now use
`url_for("projects.detalle", ...)` — the hardcoded `f"/proyectos/{...}"`
Step 1/2 used (because the target route didn't exist yet) is gone.

Step 4 scope ("Pagos block write paths (Presupuesto)", plan §1.4 items
15/17): the per-payment `Guardar` and `+ Agregar pago` routes live in
`webapp/blueprints/projects_budget.py`, registered onto this same `bp`
immediately after it is created, the same way `maintenance.py` registers
`maintenance_detail.register(bp)`.

Step 5 scope ("The five expense ledgers", plan §1.4 items 21-27): the
Banco/Equipo/Materiales/Viáticos/Extras (gastos) tabs go from the Step 3
placeholder to real content — `_panel_for()` now routes any tab key in
`LEDGER_TAB_CATEGORIES` to `projects_ledger.render_panel(ctx, tab)` instead of
`_placeholder_panel()`. All four of `projects_ledger.py`'s write routes
(Guardar cambios / +Fila / delete-confirm / delete) register onto this same
`bp`, same convention as Step 4.

Step 6 scope ("Mano de obra + adelantos", plan §1.4 items 28-34): the Mano de
obra tab goes from the Step 3 placeholder to real content — `_panel_for()`
now routes `"mano_de_obra"` to `projects_labor.render_panel(ctx)` instead of
`_placeholder_panel()`. `projects_labor.py`'s write routes (add/edit/delete
worker, add/delete adelanto) register onto this same `bp`, same convention as
Steps 4-5. ⚠ There is deliberately no expense-entry route here — see
`projects_labor.py`'s module docstring (item 28).

This file owns list/create/tab-dispatch routing only, mirroring
`webapp/blueprints/maintenance.py`: one module per tab/section owns that
section's logic and registers onto this same `bp` via `register(bp)` — never
a second `Blueprint` instance, or the nav's `request.blueprint == 'projects'`
rule silently breaks for that module's routes only (Phase 21 §5.5 finding
#1, restated in plan §1.7 for this phase's six companion modules). Steps
4-9's write-path modules (`projects_budget.py`, `projects_ledger.py`,
`projects_labor.py`, `projects_invoicing.py`, `projects_payments.py`,
`projects_promote.py`) register onto this same `bp` the same way.

Step 7 scope ("Facturación", plan §1.4 items 35-42, §1.10): new construction,
not a port. `_panel_for()` now routes `"facturacion"` to
`projects_invoicing.render_panel(ctx)` instead of `_placeholder_panel()`.
`projects_invoicing.py`'s write routes (Guardar cambios / +Fila /
delete-confirm / delete) register onto this same `bp`, same convention as
Steps 4-6.

Step 8 scope ("Pagos / ONVO", plan §1.4 items 43-50, §1.10.2-5): new
construction, not a port. `_panel_for()` now routes `"pagos"` to
`projects_payments.render_panel(ctx)` instead of `_placeholder_panel()`.
`projects_payments.py`'s write routes (per-payment `Guardar` on
`onvo_commission_pct`/`onvo_iva_pct`/`net_deposited`, plus "Registrar
comisión como gasto Banco") register onto this same `bp`, same convention
as Steps 4-7 — on URLs distinct from `projects_budget.py`'s own
Presupuesto-tab payment editor (item 50).

Step 9 scope ("Mover a Proyecto": the Cotizaciones integration, plan §1.9,
§1.4 items 51-53): `projects_promote.py`'s three routes (`GET
/promover/<pid>/<vid>`, `POST /promover/<pid>/<vid>/tabla`, `POST
/promover/<pid>/<vid>`) register onto this same `bp`, same convention as
Steps 4-8. This closes the disabled placeholder Phase 20 left in
`proposals/_detail.html` — the corresponding edits on the Cotizaciones side
(the real button, and `proposals.py`'s `url_for()` fix) live in that
blueprint, not here.
"""
from flask import Blueprint, abort, redirect, render_template, request, url_for

from webapp.blueprints import (
    projects_budget, projects_invoicing, projects_ledger, projects_labor, projects_payments,
    projects_promote,
)
from webapp.blueprints.projects_common import (
    FILTER_MAP, FILTER_OPTIONS, LEDGER_TAB_CATEGORIES, STATUS_BADGE, detail_ctx, fmt_usd, tab_url,
)

bp = Blueprint("projects", __name__, url_prefix="/proyectos")
projects_budget.register(bp)
projects_ledger.register(bp)
projects_labor.register(bp)
projects_invoicing.register(bp)
projects_payments.register(bp)
projects_promote.register(bp)


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

    return redirect(url_for("projects.detalle", pid=project["id"]), code=303)


# ── Detail page: tab shell + Presupuesto (Step 3) ───────────────────────────

def _placeholder_panel(ctx: dict, key: str) -> str:
    """Renders the "en construcción" fragment for one of the eight tabs not
    yet built (plan Step 3 scope note — explicitly not Streamlit's
    `Disponible en el siguiente paso.` copy, see the template's own comment).
    Looks the label up from `ctx["tabs"]` rather than re-deriving it, so this
    module never re-declares `projects_common.TAB_SPECS`'s labels."""
    label = next((t["label"] for t in ctx["tabs"] if t["key"] == key), key)
    return render_template("projects/_en_construccion.html", tab_label=label)


def _panel_for(ctx: dict, tab: str) -> str:
    """The one place a tab key becomes a rendered panel — shared by every
    GET route below and by `estado()`'s error re-render, so a failed status
    change re-renders the *same* panel the user was looking at."""
    if tab == "presupuesto":
        return render_template("projects/_presupuesto.html", **ctx)
    if tab in LEDGER_TAB_CATEGORIES:
        return projects_ledger.render_panel(ctx, tab)
    if tab == "mano_de_obra":
        return projects_labor.render_panel(ctx)
    if tab == "facturacion":
        return projects_invoicing.render_panel(ctx)
    if tab == "pagos":
        return projects_payments.render_panel(ctx)
    return _placeholder_panel(ctx, tab)


def _project_page(pid: str, tab: str):
    """Shared shell for every `/<pid>...` GET route (plan §1.4 item 13): one
    `detail_ctx()` call, then either the requested tab's panel (htmx tab
    swap) or the full `projects/page.html` shell around it. This is the only
    place the two detail-page error states are rendered, so no route repeats
    the try/except."""
    is_hx = bool(request.headers.get("HX-Request"))
    try:
        ctx = detail_ctx(pid, active_tab=tab)
    except Exception as exc:
        error = f"Error cargando proyecto: {exc}"
        if is_hx:
            return render_template("admin/_error.html", message=error)
        return render_template("projects/page.html", error=error, project=None)

    if ctx is None:
        if is_hx:
            return render_template("admin/_error.html", message="Proyecto no encontrado.")
        return render_template("projects/page.html", error=None, project=None)

    panel_html = _panel_for(ctx, tab)
    if is_hx:
        return panel_html
    return render_template("projects/page.html", error=None, panel_html=panel_html, status_error=None, **ctx)


@bp.route("/<pid>")
def detalle(pid):
    return _project_page(pid, "presupuesto")


@bp.route("/<pid>/gastos/<categoria>")
def gastos(pid, categoria):
    if categoria not in LEDGER_TAB_CATEGORIES:
        abort(404)
    return _project_page(pid, categoria)


@bp.route("/<pid>/mano-de-obra")
def mano_de_obra(pid):
    return _project_page(pid, "mano_de_obra")


@bp.route("/<pid>/facturacion")
def facturacion(pid):
    return _project_page(pid, "facturacion")


@bp.route("/<pid>/pagos")
def pagos(pid):
    return _project_page(pid, "pagos")


@bp.route("/<pid>/estado", methods=["POST"])
def estado(pid):
    """Status-pill change (plan §1.4 item 10). Server-side validation is not
    cosmetic here: `projects.status` has a DB CHECK constraint, but this
    rejects an out-of-vocabulary value with a plain 400 before it ever
    reaches `update_project_status()`, rather than relying on the DB to
    reject it silently or surface a raw 500."""
    from config import PROJECT_STATUSES
    from database.projects_db import update_project_status

    status = request.form.get("status")
    tab = request.form.get("tab") or "presupuesto"
    if status not in PROJECT_STATUSES:
        abort(400)

    try:
        update_project_status(pid, status)
    except Exception as exc:
        try:
            ctx = detail_ctx(pid, active_tab=tab)
        except Exception:
            ctx = None
        if ctx is None:
            abort(404)
        panel_html = _panel_for(ctx, tab)
        return render_template(
            "projects/page.html", error=None, panel_html=panel_html,
            status_error=f"Error: {exc}", **ctx,
        )

    return redirect(tab_url(pid, tab), code=303)
