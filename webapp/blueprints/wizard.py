"""New-proposal wizard (Phase 20 Step 3 — see PLAN_PHASE20_PROPOSALS_JINJA.md
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

Only Steps 1-3 are built here (Cliente / Tipo e idioma / Sitio e
irradiancia). Steps 4-8 (Distribuidora, Consumo, Equipos, Costos, Revisión)
are later phase-20 steps and are not wired into STEP_MODULES yet — requesting
one renders a plain "not built yet" placeholder rather than erroring, so
manual exploration during review doesn't 500.
"""
from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from wizard import draft
from webapp.wizard_steps import common as step_common
from webapp.wizard_steps import s1_client, s2_type, s3_site

bp = Blueprint("wizard", __name__, url_prefix="/cotizaciones/asistente")

STEP_MODULES = {1: s1_client, 2: s2_type, 3: s3_site}
STEP_TEMPLATES = {1: "wizard/s1_client.html", 2: "wizard/s2_type.html", 3: "wizard/s3_site.html"}


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
    module = STEP_MODULES.get(n)
    if module is None:
        return render_template(
            "wizard/not_built.html",
            **shell_ctx(vid, n, blob),
        )
    ctx = module.build_context(blob)
    ctx.setdefault("error", None)
    if error is not None:
        ctx["error"] = error
    return render_template(STEP_TEMPLATES[n], **shell_ctx(vid, n, blob), **ctx)


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
