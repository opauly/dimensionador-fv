"""New-proposal wizard (Phase 20 Steps 3-4 — see PLAN_PHASE20_PROPOSALS_JINJA.md
§1.2/§1.3). Blueprint owns routing/dispatch; webapp/wizard_steps/*.py own
each step's build_context()/persistence logic — same split as
webapp/blueprints/admin.py + admin_*.py.

Step numbering follows the *displayed* order (1 Cliente, 2 Tipo e idioma,
3 Sitio, 4..8) — this port drops pages/02_new_proposal.py's legacy
step1_system_type()/step2_client() name inversion. Not a behaviour change.

Row creation (§0.3 Q3, revised from the original Streamlit-matching plan —
deliberate simplification Oscar signed off on, not a bug): Step 1's own POST
(`/nueva`) creates the proposal row and burns the quote number immediately,
via create_prospect()/upsert_client() + create_proposal(). There is no
`flask.session` carry — every step from 1 onward operates on a real `vid`.
Step 2's POST just patches `meta` into that same row.

Steps 1-3 (Cliente / Tipo e idioma / Sitio e irradiancia) are shared by all
three system types. Steps 4-5 are wired for Grid Zero only so far
(gz_s4_utility.py / gz_s5_consumption.py, Phase 20 Step 4 of the plan) —
STEP_MODULES/STEP_TEMPLATES are keyed by `{n: {system_type: module}}` with a
"*" fallback for the shared steps, exactly mirroring PLAN §1.2's "single
dispatch table keyed on meta.system_type". Off-Grid/Hybrid steps 4+ and Grid
Zero steps 6-8 are later phase-20 steps and are not wired in yet — requesting
one renders a plain "not built yet" placeholder rather than erroring, so
manual exploration during review doesn't 500.
"""
from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from wizard import draft
from webapp.wizard_steps import common as step_common
from webapp.wizard_steps import gz_s4_utility, gz_s5_consumption, s1_client, s2_type, s3_site

bp = Blueprint("wizard", __name__, url_prefix="/cotizaciones/asistente")

STEP_MODULES = {
    1: {"*": s1_client},
    2: {"*": s2_type},
    3: {"*": s3_site},
    4: {"grid_zero": gz_s4_utility},
    5: {"grid_zero": gz_s5_consumption},
}
STEP_TEMPLATES = {
    1: {"*": "wizard/s1_client.html"},
    2: {"*": "wizard/s2_type.html"},
    3: {"*": "wizard/s3_site.html"},
    4: {"grid_zero": "wizard/gz_s4_utility.html"},
    5: {"grid_zero": "wizard/gz_s5_consumption.html"},
}


# ── shared helpers ───────────────────────────────────────────────────────


def _get_version(vid):
    from database.proposals_db import get_version

    try:
        return get_version(vid)
    except Exception:
        return None


def _title(vid: str | None, blob: dict) -> str:
    client_name = (blob.get("client") or {}).get("name") or ""
    if vid and client_name:
        return f"Cotización — {client_name}"
    if vid:
        return "Editar cotización"
    return "Nueva cotización"


def shell_ctx(vid: str | None, n: int, blob: dict, **extra) -> dict:
    """Everything wizard/shell.html needs — built once per request, same
    build_context spirit as the per-step modules, so the breadcrumb/title
    never drift from what the step itself is showing."""
    meta = blob.get("meta") or {}
    system_type = meta.get("system_type") or step_common.DEFAULT_SYSTEM_TYPE
    step_reached = meta.get("step_reached", 1) or 1
    return {
        "vid": vid,
        "n": n,
        "labels": step_common.step_labels(system_type),
        "step_reached": step_reached,
        "title": _title(vid, blob),
        **extra,
    }


def _system_type(blob: dict) -> str:
    return (blob.get("meta") or {}).get("system_type") or step_common.DEFAULT_SYSTEM_TYPE


def _step_module(n: int, blob: dict):
    modules = STEP_MODULES.get(n)
    if not modules:
        return None
    return modules.get(_system_type(blob)) or modules.get("*")


def _step_template(n: int, blob: dict) -> str | None:
    templates = STEP_TEMPLATES.get(n)
    if not templates:
        return None
    return templates.get(_system_type(blob)) or templates.get("*")


def _guard(vid: str, n: int):
    """Locked-version + step-ahead guards, shared by every GET/POST/action
    route below (PLAN §1.2). Returns a redirect Response to short-circuit
    the caller, or None if the request may proceed."""
    version = _get_version(vid)
    if not version:
        abort(404)
    if version.get("locked"):
        return redirect(url_for("proposals.index", aviso="bloqueada"), code=303)

    blob = draft.load(vid)
    step_reached = (blob.get("meta") or {}).get("step_reached", 1) or 1
    if n > step_reached + 1:
        return redirect(url_for("wizard.paso", vid=vid, n=step_reached), code=303)
    return None


def _render_step(vid: str, n: int, blob: dict, *, error: str | None = None):
    module = _step_module(n, blob)
    if module is None:
        return render_template(
            "wizard/not_built.html",
            **shell_ctx(vid, n, blob),
        )
    ctx = module.build_context(blob)
    ctx.setdefault("error", None)
    if error is not None:
        ctx["error"] = error
    return render_template(_step_template(n, blob), **shell_ctx(vid, n, blob), **ctx)


# ── Step 1: /nueva (no row yet) ─────────────────────────────────────────


@bp.route("/nueva", methods=["GET"])
def nueva():
    ctx = s1_client.build_context(None)
    ctx.setdefault("error", None)
    return render_template(
        "wizard/s1_client.html",
        **shell_ctx(None, 1, {}),
        post_url=url_for("wizard.nueva"),
        **ctx,
    )


@bp.route("/nueva", methods=["POST"])
def nueva_post():
    result = s1_client.parse_form(request.form)
    if not result["name"]:
        ctx = s1_client.build_context({"client": result})
        ctx["error"] = "El nombre del cliente es requerido."
        return render_template(
            "wizard/s1_client.html",
            **shell_ctx(None, 1, {}),
            post_url=url_for("wizard.nueva"),
            **ctx,
        ), 400

    result = s1_client.resolve_client(result)

    from database.proposals_db import create_proposal

    prop = create_proposal(
        client_name=result["name"],
        system_type=step_common.DEFAULT_SYSTEM_TYPE,
        client_id=result.get("client_id"),
        prospect_id=result.get("prospect_id"),
    )
    vid = prop["id"]

    blob = draft.load(vid)
    blob["client"] = result
    blob["meta"] = {**blob.get("meta", {}), "step_reached": 1}
    draft.save(vid, blob)
    draft.set_step(vid, 2)

    return redirect(url_for("wizard.paso", vid=vid, n=2), code=303)


# ── Client search / select / previous-proposals fragments ──────────────
# Shared by both /nueva (vid="") and an existing draft's Step 1 — see
# s1_client.py's module docstring for why the same build_context() covers
# both an ephemeral (pre-row) and a real persisted blob.


@bp.route("/clientes/buscar")
def clientes_buscar():
    q = request.args.get("q", "")
    vid = request.args.get("vid") or None
    matches = s1_client.search_matches(q)
    return render_template("wizard/_s1_search_results.html", matches=matches, vid=vid, q=q)


@bp.route("/clientes/seleccionar")
def clientes_seleccionar():
    client_id = request.args.get("id", "")
    vid = request.args.get("vid") or None
    fields = s1_client.client_fields_by_id(client_id)

    if vid:
        blob = draft.patch(vid, "client", fields)
        if fields.get("client_id"):
            from database.proposals_db import get_version, update_proposal_client

            proposal_id = (get_version(vid) or {}).get("proposal_id")
            if proposal_id:
                update_proposal_client(proposal_id, fields["name"], client_id=fields.get("client_id"))
    else:
        blob = {"client": fields}

    ctx = s1_client.build_context(blob)
    return render_template("wizard/_s1_fields.html", vid=vid, **ctx)


@bp.route("/clientes/previas")
def clientes_previas():
    client_id = request.args.get("client_id") or None
    name = request.args.get("name") or ""
    options = s1_client.prev_options(client_id, name)
    return render_template("wizard/_s1_prev.html", prev_options=options)


@bp.route("/<vid>/abrir")
def abrir(vid):
    blob = draft.load(vid)
    step_reached = (blob.get("meta") or {}).get("step_reached", 1) or 1
    return redirect(url_for("wizard.paso", vid=vid, n=step_reached), code=303)


# ── Steps 2+: /<vid>/paso/<n> ────────────────────────────────────────────


@bp.route("/<vid>/paso/<int:n>", methods=["GET"])
def paso(vid, n):
    guard = _guard(vid, n)
    if guard:
        return guard
    blob = draft.load(vid)
    return _render_step(vid, n, blob)


@bp.route("/<vid>/paso/<int:n>", methods=["POST"])
def paso_post(vid, n):
    guard = _guard(vid, n)
    if guard:
        return guard
    blob = draft.load(vid)

    if n == 1:
        result = s1_client.parse_form(request.form)
        if not result["name"]:
            return _render_step(vid, n, {**blob, "client": result},
                                 error="El nombre del cliente es requerido.")
        result = s1_client.resolve_client(result)
        blob = draft.patch(vid, "client", result)
        from database.proposals_db import get_version, update_proposal_client

        proposal_id = (get_version(vid) or {}).get("proposal_id")
        if proposal_id:
            update_proposal_client(
                proposal_id, result["name"],
                client_id=result.get("client_id"), prospect_id=result.get("prospect_id"),
            )

    elif n == 2:
        values = s2_type.parse_form(request.form)
        blob = draft.patch(vid, "meta", values)
        from database.proposals_db import get_version, update_proposal_system_type

        proposal_id = (get_version(vid) or {}).get("proposal_id")
        if proposal_id:
            update_proposal_system_type(proposal_id, values["system_type"])

    elif n == 3:
        blob = draft.patch(vid, "site", s3_site.save_step(request.form))
        ctx = s3_site.build_context(blob)
        if not ctx["can_continue"]:
            return _render_step(vid, n, blob)

    elif n == 4 and _step_module(n, blob) is gz_s4_utility:
        blob = draft.patch(vid, "utility", gz_s4_utility.save_step(request.form))
        ctx = gz_s4_utility.build_context(blob)
        if not ctx["can_continue"]:
            return _render_step(vid, n, blob)

    elif n == 5 and _step_module(n, blob) is gz_s5_consumption:
        blob = draft.patch(vid, "consumption", gz_s5_consumption.save_step(request.form))
        ctx = gz_s5_consumption.build_context(blob)
        if not ctx["can_continue"]:
            return _render_step(vid, n, blob)

    else:
        return _render_step(vid, n, blob)

    draft.set_step(vid, n + 1)
    return redirect(url_for("wizard.paso", vid=vid, n=n + 1), code=303)


@bp.route("/<vid>/paso/<int:n>/atras", methods=["POST"])
def paso_atras(vid, n):
    guard = _guard(vid, n)
    if guard:
        return guard
    blob = draft.load(vid)

    if n == 2:
        values = s2_type.parse_form(request.form)
        draft.patch(vid, "meta", values)
    elif n == 3:
        draft.patch(vid, "site", s3_site.save_step(request.form))
    elif n == 4 and _step_module(n, blob) is gz_s4_utility:
        draft.patch(vid, "utility", gz_s4_utility.save_step(request.form))
    elif n == 5 and _step_module(n, blob) is gz_s5_consumption:
        draft.patch(vid, "consumption", gz_s5_consumption.save_step(request.form))

    return redirect(url_for("wizard.paso", vid=vid, n=n - 1), code=303)


@bp.route("/<vid>/paso/<int:n>/<action>", methods=["POST"])
def paso_action(vid, n, action):
    guard = _guard(vid, n)
    if guard:
        return guard

    if n == 3 and action == "pvgis":
        blob = draft.load(vid)
        values, error = s3_site.run_pvgis(blob, request.form)
        blob = draft.patch(vid, "site", values)
        ctx = s3_site.build_context(blob)
        ctx["error"] = error
        return render_template("wizard/_s3_irradiancia.html", vid=vid, n=n, **ctx)

    abort(404)


# ── Step 4 (Grid Zero): distributor -> tariff hx-get ────────────────────
# Mirrors clientes_seleccionar()'s shape (a GET that mutates the draft the
# instant a selection is made — PLAN §1.1 "every mutation is a save"), not
# the POST-only /<n>/<action> dispatcher above, since this fragment lives
# nested a level deeper (paso/4/distribuidor, not a bare action name).


@bp.route("/<vid>/paso/4/distribuidor")
def paso4_distribuidor(vid):
    guard = _guard(vid, 4)
    if guard:
        return guard
    distributor_id = request.args.get("distributor_id") or None
    blob = draft.patch(vid, "utility", gz_s4_utility.select_distributor(distributor_id))
    ctx = gz_s4_utility.build_context(blob)
    return render_template("wizard/_s4_tarifa.html", vid=vid, n=4, **ctx)


# ── Step 5 (Grid Zero) actions — source switch, bill upload, tablero
# upload, loads table, 12-month table recompute. Every one of these patches
# blob["scratch"]["s5"] and re-renders wizard/_s5_consumo.html from a fresh
# gz_s5_consumption.build_context(blob) call (PLAN §1.3) — never a
# hand-built fragment — so the badge/table/metrics/chart can't drift apart.


def _s5_render(vid: str, blob: dict, *, error: str | None = None):
    ctx = gz_s5_consumption.build_context(blob)
    ctx["error"] = error
    return render_template("wizard/_s5_consumo.html", vid=vid, n=5, **ctx)


def _s5_patch(vid: str, new_s5: dict) -> dict:
    return draft.patch(vid, "scratch", {"s5": new_s5})


@bp.route("/<vid>/paso/5/fuente", methods=["POST"])
def paso5_fuente(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    current_s5 = (blob.get("scratch") or {}).get("s5") or {}
    new_s5 = {**current_s5, **gz_s5_consumption.select_source(request.form.get("source", ""))}
    blob = _s5_patch(vid, new_s5)
    return _s5_render(vid, blob)


@bp.route("/<vid>/paso/5/factura/extraer", methods=["POST"])
def paso5_factura_extraer(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    files = request.files.getlist("files")
    blob = _s5_patch(vid, gz_s5_consumption.extract_bills(blob, files))
    return _s5_render(vid, blob)


@bp.route("/<vid>/paso/5/factura/aplicar", methods=["POST"])
def paso5_factura_aplicar(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s5_patch(vid, gz_s5_consumption.apply_bill_history(blob))
    return _s5_render(vid, blob)


@bp.route("/<vid>/paso/5/tablero/extraer", methods=["POST"])
def paso5_tablero_extraer(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return _s5_render(vid, blob, error="Selecciona una imagen o PDF del tablero.")
    try:
        new_s5 = gz_s5_consumption.extract_tablero(blob, uploaded.read(), uploaded.mimetype)
    except Exception as exc:
        return _s5_render(vid, blob, error=f"Error al analizar el tablero: {exc}")
    blob = _s5_patch(vid, new_s5)
    return _s5_render(vid, blob)


@bp.route("/<vid>/paso/5/cargas/tabla", methods=["POST"])
def paso5_cargas_tabla(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s5_patch(vid, gz_s5_consumption.update_loads_table(blob, request.form))
    return _s5_render(vid, blob)


@bp.route("/<vid>/paso/5/cargas/fila", methods=["POST"])
def paso5_cargas_fila(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s5_patch(vid, gz_s5_consumption.add_loads_row(blob, request.form))
    return _s5_render(vid, blob)


@bp.route("/<vid>/paso/5/cargas/fila/quitar", methods=["POST"])
def paso5_cargas_fila_quitar(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s5_patch(vid, gz_s5_consumption.remove_loads_row(blob, request.form))
    return _s5_render(vid, blob)


@bp.route("/<vid>/paso/5/cargas/aplicar", methods=["POST"])
def paso5_cargas_aplicar(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s5_patch(vid, gz_s5_consumption.apply_loads(blob))
    return _s5_render(vid, blob)


@bp.route("/<vid>/paso/5/tabla", methods=["POST"])
def paso5_tabla(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s5_patch(vid, gz_s5_consumption.recompute_table(blob, request.form))
    return _s5_render(vid, blob)
