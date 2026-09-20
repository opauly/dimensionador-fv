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
three system types. Grid Zero's wizard is wired end to end (gz_s4_utility.py
/ gz_s5_consumption.py / gz_s6_equipment.py / gz_s7_costs.py /
gz_s8_review.py — Phase 20 Steps 4-6). Off-Grid's Steps 4-5 (Cargas /
Demanda) are wired too (og_s4_loads.py / og_s5_demand.py — Phase 20 Step 7);
its Steps 6-8 (Equipos, Costos, Revisión) and all of Hybrid are later
phase-20 steps and are not wired in yet — requesting one renders a plain
"not built yet" placeholder rather than erroring, so manual exploration
during review doesn't 500. STEP_MODULES/STEP_TEMPLATES are keyed by
`{n: {system_type: module}}` with a "*" fallback for the shared steps,
exactly mirroring PLAN §1.2's "single dispatch table keyed on
meta.system_type".

Step 8's PDF routes deliberately import from webapp.blueprints.proposals
(`_generate_pdf_bytes()`, `_signed_url()`) rather than re-implementing PDF
generation here — PLAN §1.8's whole point is that the wizard and the
proposals list share exactly one `build_from_wizard_blob()`-based code path,
so a PDF generated from either place for the same saved version is
byte-identical by construction.
"""
from __future__ import annotations

from io import BytesIO

from flask import Blueprint, abort, redirect, render_template, request, send_file, url_for

from wizard import draft
from webapp.wizard_steps import common as step_common
from webapp.wizard_steps import (
    gz_s4_utility, gz_s5_consumption, gz_s6_equipment, gz_s7_costs, gz_s8_review,
    og_s4_loads, og_s5_demand, og_s6_equipment,
    s1_client, s2_type, s3_site,
)

bp = Blueprint("wizard", __name__, url_prefix="/cotizaciones/asistente")

STEP_MODULES = {
    1: {"*": s1_client},
    2: {"*": s2_type},
    3: {"*": s3_site},
    4: {"grid_zero": gz_s4_utility, "off_grid": og_s4_loads},
    5: {"grid_zero": gz_s5_consumption, "off_grid": og_s5_demand},
    6: {"grid_zero": gz_s6_equipment, "off_grid": og_s6_equipment},
    7: {"grid_zero": gz_s7_costs},
    8: {"grid_zero": gz_s8_review},
}
STEP_TEMPLATES = {
    1: {"*": "wizard/s1_client.html"},
    2: {"*": "wizard/s2_type.html"},
    3: {"*": "wizard/s3_site.html"},
    4: {"grid_zero": "wizard/gz_s4_utility.html", "off_grid": "wizard/og_s4_loads.html"},
    5: {"grid_zero": "wizard/gz_s5_consumption.html", "off_grid": "wizard/og_s5_demand.html"},
    6: {"grid_zero": "wizard/gz_s6_equipment.html", "off_grid": "wizard/og_s6_equipment.html"},
    7: {"grid_zero": "wizard/gz_s7_costs.html"},
    8: {"grid_zero": "wizard/gz_s8_review.html"},
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
    # gz_s8_review.build_context() and og_s6_equipment.build_context() both
    # take `vid` in addition to `blob` — see each module's own docstring for
    # why (gz_s8_review: lock/quote-number/pdf_path live on the
    # proposal_versions ROW; og_s6_equipment: the lazy daily-PVGIS-series
    # backfill needs `vid` to persist what it fetches). Every other step's
    # build_context() is blob-only.
    if module in (gz_s8_review, og_s6_equipment):
        ctx = module.build_context(blob, vid)
    else:
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

    elif n == 4 and _step_module(n, blob) is og_s4_loads:
        blob = draft.patch(vid, "consumption", og_s4_loads.save_step(request.form))
        ctx = og_s4_loads.build_context(blob)
        if not ctx["can_continue"]:
            return _render_step(vid, n, blob)

    elif n == 5 and _step_module(n, blob) is gz_s5_consumption:
        blob = draft.patch(vid, "consumption", gz_s5_consumption.save_step(request.form))
        ctx = gz_s5_consumption.build_context(blob)
        if not ctx["can_continue"]:
            return _render_step(vid, n, blob)

    elif n == 5 and _step_module(n, blob) is og_s5_demand:
        blob = draft.patch(vid, "consumption", og_s5_demand.save_step(blob))
        ctx = og_s5_demand.build_context(blob)
        if not ctx["can_continue"]:
            return _render_step(vid, n, blob)

    elif n == 6 and _step_module(n, blob) is gz_s6_equipment:
        # Do-not-drop item 15's server-side half: save_step() returns None
        # when neither a valid auto scenario nor a valid manual design
        # exists, and that rejection is enforced here regardless of what the
        # (client-side-disabled) Siguiente button in the browser looked like
        # — a raw POST cannot bypass it.
        result = gz_s6_equipment.save_step(blob)
        if result is None:
            return _render_step(
                vid, n, blob,
                error="Calcula los escenarios MPPT o configura un diseño manual válido para continuar.",
            )
        blob = draft.patch(vid, "equipment", result)

    elif n == 6 and _step_module(n, blob) is og_s6_equipment:
        # Same server-side rejection as Grid Zero's Step 6, Off-Grid's own
        # do-not-drop item 15 analogue (§1.10 item 15's "Siguiente disabled
        # unless a valid auto scenario or a valid manual design exists").
        result = og_s6_equipment.save_step(blob, vid)
        if result is None:
            return _render_step(
                vid, n, blob,
                error="Selecciona un escenario automático válido o configura un diseño manual válido para continuar.",
            )
        blob = draft.patch(vid, "equipment", result)

    elif n == 7 and _step_module(n, blob) is gz_s7_costs:
        blob = draft.patch(vid, "costs", gz_s7_costs.save_step(blob, request.form))
        ctx = gz_s7_costs.build_context(blob)
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
    elif n == 4 and _step_module(n, blob) is og_s4_loads:
        draft.patch(vid, "consumption", og_s4_loads.save_step(request.form))
    elif n == 5 and _step_module(n, blob) is gz_s5_consumption:
        draft.patch(vid, "consumption", gz_s5_consumption.save_step(request.form))
    elif n == 5 and _step_module(n, blob) is og_s5_demand:
        draft.patch(vid, "consumption", og_s5_demand.save_step(blob))
    elif n == 7 and _step_module(n, blob) is gz_s7_costs:
        draft.patch(vid, "costs", gz_s7_costs.save_step(blob, request.form))
    elif n == 8 and _step_module(n, blob) is gz_s8_review:
        # Step 8 has no scenario/table to persist — only the intro textarea,
        # which lives in the same wrapping <form> as this Atrás submit.
        intro_text = request.form.get("intro_text")
        if intro_text is not None:
            draft.patch(vid, "proposal_text", intro_text)

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


# ── Step 4 (Off-Grid) actions — catálogo, tablero/texto import (§1.7's
# exact routes), loads-table live sync, +Fila, quitar fila. Every one of
# these patches blob["scratch"][og_s4_loads.DEFAULT_SCRATCH_KEY] and
# re-renders wizard/_s4og_cargas.html from a fresh
# og_s4_loads.build_context(blob) call (PLAN §1.3) — same "one fragment,
# always the same build_context()" discipline as Grid Zero's Step 5 loads
# block, so a table edit and an import can never leave the page showing two
# different sources of truth.


def _s4og_render(vid: str, blob: dict, *, error: str | None = None):
    ctx = og_s4_loads.build_context(blob)
    ctx["error"] = error
    return render_template("wizard/_s4og_cargas.html", vid=vid, n=4, **ctx)


def _s4og_patch(vid: str, scratch_key: str, new_sub: dict) -> dict:
    return draft.patch(vid, "scratch", {scratch_key: new_sub})


@bp.route("/<vid>/paso/4/cargas/catalogo", methods=["POST"])
def paso4og_catalogo(vid):
    guard = _guard(vid, 4)
    if guard:
        return guard
    blob = draft.load(vid)
    scratch_key = og_s4_loads.DEFAULT_SCRATCH_KEY
    picks = request.form.getlist("picks")
    blob = _s4og_patch(vid, scratch_key, og_s4_loads.add_catalog_rows(blob, scratch_key, picks))
    return _s4og_render(vid, blob)


@bp.route("/<vid>/paso/4/tablero/extraer", methods=["POST"])
def paso4og_tablero_extraer(vid):
    guard = _guard(vid, 4)
    if guard:
        return guard
    blob = draft.load(vid)
    scratch_key = og_s4_loads.DEFAULT_SCRATCH_KEY
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return _s4og_render(vid, blob, error="Selecciona una imagen o PDF del tablero.")
    try:
        new_sub = og_s4_loads.extract_tablero(blob, scratch_key, uploaded.read(), uploaded.mimetype)
    except Exception as exc:
        return _s4og_render(vid, blob, error=f"Error al analizar el tablero: {exc}")
    blob = _s4og_patch(vid, scratch_key, new_sub)
    return _s4og_render(vid, blob)


@bp.route("/<vid>/paso/4/texto/extraer", methods=["POST"])
def paso4og_texto_extraer(vid):
    guard = _guard(vid, 4)
    if guard:
        return guard
    blob = draft.load(vid)
    scratch_key = og_s4_loads.DEFAULT_SCRATCH_KEY
    text = request.form.get("pasted_text", "")
    if not text.strip():
        return _s4og_render(vid, blob, error="Pega el texto de la tabla de cargas antes de extraer.")
    try:
        new_sub = og_s4_loads.extract_text(blob, scratch_key, text)
    except Exception as exc:
        return _s4og_render(vid, blob, error=f"Error al analizar el texto: {exc}")
    blob = _s4og_patch(vid, scratch_key, new_sub)
    return _s4og_render(vid, blob)


@bp.route("/<vid>/paso/4/cargas/tabla", methods=["POST"])
def paso4og_cargas_tabla(vid):
    guard = _guard(vid, 4)
    if guard:
        return guard
    blob = draft.load(vid)
    scratch_key = og_s4_loads.DEFAULT_SCRATCH_KEY
    blob = _s4og_patch(vid, scratch_key, og_s4_loads.update_table(blob, scratch_key, request.form))
    return _s4og_render(vid, blob)


@bp.route("/<vid>/paso/4/cargas/fila", methods=["POST"])
def paso4og_cargas_fila(vid):
    guard = _guard(vid, 4)
    if guard:
        return guard
    blob = draft.load(vid)
    scratch_key = og_s4_loads.DEFAULT_SCRATCH_KEY
    blob = _s4og_patch(vid, scratch_key, og_s4_loads.add_row(blob, scratch_key, request.form))
    return _s4og_render(vid, blob)


@bp.route("/<vid>/paso/4/cargas/fila/quitar", methods=["POST"])
def paso4og_cargas_fila_quitar(vid):
    guard = _guard(vid, 4)
    if guard:
        return guard
    blob = draft.load(vid)
    scratch_key = og_s4_loads.DEFAULT_SCRATCH_KEY
    blob = _s4og_patch(vid, scratch_key, og_s4_loads.remove_row(blob, scratch_key, request.form))
    return _s4og_render(vid, blob)


# ── Step 5 (Off-Grid) actions — calcular, recalcular (the user_confirmed
# override rule, PLAN §1.10 item 1), illustrative hourly shape (§1.7's exact
# route). Calcular/Recalcular re-render the WHOLE wizard/_s5og_demanda.html
# fragment from a fresh og_s5_demand.build_context() call (PLAN §1.3); the
# hourly-shape button targets ONLY the nested wizard/_s5og_horario.html
# fragment instead, deliberately narrower — see that template's own comment
# for why (an in-progress, not-yet-Recalculado Horas/día edit must survive
# a click on the hourly-shape button, the same way Streamlit's data_editor
# keeps its live edited state across an unrelated widget interaction).


def _s5og_render(vid: str, blob: dict, *, error: str | None = None):
    ctx = og_s5_demand.build_context(blob)
    ctx["error"] = error
    return render_template("wizard/_s5og_demanda.html", vid=vid, n=5, **ctx)


def _s5og_patch(vid: str, scratch_key: str, new_sub: dict) -> dict:
    return draft.patch(vid, "scratch", {scratch_key: new_sub})


@bp.route("/<vid>/paso/5/calcular", methods=["POST"])
def paso5og_calcular(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    scratch_key = og_s5_demand.DEFAULT_SCRATCH_KEY
    blob = _s5og_patch(vid, scratch_key, og_s5_demand.calculate(blob, scratch_key))
    return _s5og_render(vid, blob)


@bp.route("/<vid>/paso/5/recalcular", methods=["POST"])
def paso5og_recalcular(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    scratch_key = og_s5_demand.DEFAULT_SCRATCH_KEY
    blob = _s5og_patch(vid, scratch_key, og_s5_demand.recalculate(blob, scratch_key, request.form))
    return _s5og_render(vid, blob)


@bp.route("/<vid>/paso/5/perfil/horario", methods=["POST"])
def paso5og_horario(vid):
    guard = _guard(vid, 5)
    if guard:
        return guard
    blob = draft.load(vid)
    scratch_key = og_s5_demand.DEFAULT_SCRATCH_KEY
    blob = _s5og_patch(vid, scratch_key, og_s5_demand.generate_hourly_shape(blob, scratch_key))
    ctx = og_s5_demand.build_context(blob)
    return render_template("wizard/_s5og_horario.html", vid=vid, n=5, **ctx)


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


# ── Step 6 (Grid Zero) actions — equipment select, MPPT calc, scenario
# select, manual mode select/live-validate. Every one of these patches
# blob["scratch"]["s6"] and re-renders wizard/_s6_equipos.html from a fresh
# gz_s6_equipment.build_context(blob) call (PLAN §1.3) — see that module's
# own docstring for why this step in particular swaps ONE fragment for
# every action rather than several narrower ones.


def _s6_render(vid: str, blob: dict, *, error: str | None = None):
    ctx = gz_s6_equipment.build_context(blob)
    ctx["error"] = error
    return render_template("wizard/_s6_equipos.html", vid=vid, n=6, **ctx)


def _s6_patch(vid: str, new_s6: dict) -> dict:
    return draft.patch(vid, "scratch", {"s6": new_s6})


@bp.route("/<vid>/paso/6/equipo", methods=["POST"])
def paso6_equipo(vid):
    guard = _guard(vid, 6)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s6_patch(vid, gz_s6_equipment.select_equipment(blob, request.form))
    return _s6_render(vid, blob)


@bp.route("/<vid>/paso/6/mppt/calcular", methods=["POST"])
def paso6_mppt_calcular(vid):
    guard = _guard(vid, 6)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s6_patch(vid, gz_s6_equipment.calc_mppt(blob))
    return _s6_render(vid, blob)


@bp.route("/<vid>/paso/6/escenario/<label>", methods=["POST"])
def paso6_escenario(vid, label):
    guard = _guard(vid, 6)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s6_patch(vid, gz_s6_equipment.select_scenario(blob, label))
    return _s6_render(vid, blob)


@bp.route("/<vid>/paso/6/manual", methods=["POST"])
def paso6_manual(vid):
    guard = _guard(vid, 6)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s6_patch(vid, gz_s6_equipment.select_manual(blob))
    return _s6_render(vid, blob)


@bp.route("/<vid>/paso/6/manual/validar", methods=["POST"])
def paso6_manual_validar(vid):
    guard = _guard(vid, 6)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s6_patch(vid, gz_s6_equipment.validate_manual(blob, request.form))
    return _s6_render(vid, blob)


# ── Step 6 (Off-Grid) actions — equipment select, scenario select, manual
# mode select/live-validate. Every one of these patches
# blob["scratch"]["s6og"] and re-renders wizard/_s6og_equipos.html from a
# fresh og_s6_equipment.build_context(blob, vid) call (PLAN §1.3) — see that
# module's docstring for why there is deliberately NO
# "reliability/calcular" action route (unlike Grid Zero's MPPT calc, the
# reliability scenarios recompute automatically on every render, exactly
# matching wizard/off_grid.py's own step6_equipment(), which has no
# "Calcular" button either).


def _s6og_render(vid: str, blob: dict, *, error: str | None = None):
    ctx = og_s6_equipment.build_context(blob, vid)
    ctx["error"] = error
    return render_template("wizard/_s6og_equipos.html", vid=vid, n=6, **ctx)


def _s6og_patch(vid: str, new_s6: dict) -> dict:
    return draft.patch(vid, "scratch", {og_s6_equipment.DEFAULT_SCRATCH_KEY: new_s6})


@bp.route("/<vid>/paso/6/og/equipo", methods=["POST"])
def paso6og_equipo(vid):
    guard = _guard(vid, 6)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s6og_patch(vid, og_s6_equipment.select_equipment(blob, request.form))
    return _s6og_render(vid, blob)


@bp.route("/<vid>/paso/6/og/escenario/<label>", methods=["POST"])
def paso6og_escenario(vid, label):
    guard = _guard(vid, 6)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s6og_patch(vid, og_s6_equipment.select_scenario(blob, label))
    return _s6og_render(vid, blob)


@bp.route("/<vid>/paso/6/og/manual", methods=["POST"])
def paso6og_manual(vid):
    guard = _guard(vid, 6)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s6og_patch(vid, og_s6_equipment.select_manual(blob))
    return _s6og_render(vid, blob)


@bp.route("/<vid>/paso/6/og/manual/validar", methods=["POST"])
def paso6og_manual_validar(vid):
    guard = _guard(vid, 6)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = _s6og_patch(vid, og_s6_equipment.validate_manual(blob, request.form))
    return _s6og_render(vid, blob)


# ── Step 7 (Grid Zero) actions — row edit, +Fila, quitar fila, Refrescar
# precios. Every one of these patches blob["costs"] directly (this step has
# no scratch namespace of its own — see gz_s7_costs.py's module docstring)
# and re-renders wizard/_s7_costos.html from a fresh
# gz_s7_costs.build_context() call (PLAN §1.3).


def _s7_render(vid: str, blob: dict, *, refresh_message: str | None = None):
    ctx = gz_s7_costs.build_context(blob)
    ctx["refresh_message"] = refresh_message
    return render_template("wizard/_s7_costos.html", vid=vid, n=7, **ctx)


@bp.route("/<vid>/paso/7/tabla", methods=["POST"])
def paso7_tabla(vid):
    guard = _guard(vid, 7)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = draft.patch(vid, "costs", gz_s7_costs.recompute_table(blob, request.form))
    return _s7_render(vid, blob)


@bp.route("/<vid>/paso/7/fila", methods=["POST"])
def paso7_fila(vid):
    guard = _guard(vid, 7)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = draft.patch(vid, "costs", gz_s7_costs.add_line_row(blob, request.form))
    return _s7_render(vid, blob)


@bp.route("/<vid>/paso/7/fila/quitar", methods=["POST"])
def paso7_fila_quitar(vid):
    guard = _guard(vid, 7)
    if guard:
        return guard
    blob = draft.load(vid)
    blob = draft.patch(vid, "costs", gz_s7_costs.remove_line_row(blob, request.form))
    return _s7_render(vid, blob)


@bp.route("/<vid>/paso/7/refrescar", methods=["POST"])
def paso7_refrescar(vid):
    guard = _guard(vid, 7)
    if guard:
        return guard
    blob = draft.load(vid)
    new_costs, n_changed = gz_s7_costs.refresh_prices(blob)
    blob = draft.patch(vid, "costs", new_costs)
    message = f"✅ {n_changed} precio(s) actualizado(s)." if n_changed else "Los precios ya están al día."
    return _s7_render(vid, blob, refresh_message=message)


# ── Step 8 (Grid Zero) actions — intro-paragraph AI generation, PDF
# generate/download (PLAN §1.8), lock (do-not-drop item 21). Post-lock
# actions (Nueva versión / Marcar como enviada / Ir a cotizaciones) reuse
# the existing webapp.blueprints.proposals routes directly from the
# template — see wizard/_s8_lock.html — rather than duplicating them here.


@bp.route("/<vid>/paso/8/intro/generar", methods=["POST"])
def paso8_intro_generar(vid):
    guard = _guard(vid, 8)
    if guard:
        return guard
    blob = draft.load(vid)
    text = gz_s8_review.generate_intro_text(blob, vid)
    blob = draft.patch(vid, "proposal_text", text)
    ctx = gz_s8_review.build_context(blob, vid)
    return render_template("wizard/_s8_intro.html", vid=vid, n=8, **ctx)


@bp.route("/<vid>/paso/8/pdf", methods=["POST"])
def paso8_pdf(vid):
    """PLAN §1.8 step 1 — build_from_wizard_blob() -> generate_pdf() ->
    upload_pdf() + save_pdf_path(), via the exact same
    webapp.blueprints.proposals._generate_pdf_bytes() helper Step 2's
    list-page "Generar PDF" route uses, so the two are byte-identical by
    construction rather than by two implementations happening to agree."""
    guard = _guard(vid, 8)
    if guard:
        return guard
    blob = draft.load(vid)
    intro_text = request.form.get("intro_text")
    if intro_text is not None:
        blob = draft.patch(vid, "proposal_text", intro_text)

    from database.proposals_db import format_quote_number, get_proposal, get_version, save_pdf_path
    from proposals.generator import upload_pdf
    from webapp.blueprints.proposals import _generate_pdf_bytes

    version = get_version(vid)
    proposal = get_proposal(version["proposal_id"])
    vquote = format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), version["version_number"])
    language = (blob.get("meta") or {}).get("language", "es")
    lang_label = "ES" if language == "es" else "EN"

    error = None
    try:
        pdf_bytes = _generate_pdf_bytes(vid, proposal, vquote)
        path = upload_pdf(pdf_bytes, proposal["id"], version["version_number"], proposal.get("client_name") or "cliente")
        save_pdf_path(vid, path)
    except Exception as exc:
        error = f"Error generando PDF: {exc}"

    ctx = gz_s8_review.build_context(blob, vid)
    ctx["pdf_error"] = error
    ctx["pdf_ready"] = error is None
    ctx["pdf_lang_label"] = lang_label
    return render_template("wizard/_s8_pdf.html", vid=vid, n=8, **ctx)


@bp.route("/<vid>/paso/8/pdf/descargar", methods=["GET"])
def paso8_pdf_descargar(vid):
    """PLAN §1.8 step 2 — signed URL when a pdf_path already exists
    (reusing webapp.blueprints.proposals._signed_url(), same bucket/TTL as
    the list page), otherwise regenerate + send_file(). Guarded like every
    other paso/8 route: unreachable once locked, which is fine — the
    post-lock UI never links here (it links to the list page's own PDF
    affordance instead, built in Step 2)."""
    guard = _guard(vid, 8)
    if guard:
        return guard

    from database.proposals_db import format_quote_number, get_proposal, get_version
    from wizard.state import pdf_filename
    from webapp.blueprints.proposals import _generate_pdf_bytes, _signed_url

    version = get_version(vid)
    if not version:
        abort(404)
    proposal = get_proposal(version["proposal_id"])
    if not proposal:
        abort(404)

    pdf_path = version.get("pdf_path")
    if pdf_path:
        url = _signed_url(pdf_path)
        if url:
            return redirect(url, code=302)

    blob = draft.load(vid)
    language = (blob.get("meta") or {}).get("language", "es")
    lang_label = "ES" if language == "es" else "EN"
    vquote = format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), version["version_number"])
    pdf_bytes = _generate_pdf_bytes(vid, proposal, vquote)
    name = pdf_filename(vquote, proposal.get("client_name") or blob.get("client", {}).get("name", ""), lang_label)
    return send_file(BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=name)


@bp.route("/<vid>/paso/8/bloquear", methods=["POST"])
def paso8_bloquear(vid):
    """do-not-drop item 21 — locks the version via
    database.proposals_db.lock_version() (the actual Streamlit-side
    mechanism, wizard/grid_zero.py:step8_review()'s "Bloquear versión"
    button). The wizard shell's own _guard() above already makes any GET
    .../paso/<n> on this version unreachable from the next request
    onward (redirect to the list) — this route only needs to perform the
    lock itself and hand back the post-lock fragment for the current
    (still-live) page."""
    guard = _guard(vid, 8)
    if guard:
        return guard
    blob = draft.load(vid)
    intro_text = request.form.get("intro_text")
    if intro_text is not None:
        blob = draft.patch(vid, "proposal_text", intro_text)

    from database.proposals_db import lock_version

    note = (request.form.get("version_note") or "").strip() or None
    error = None
    try:
        lock_version(vid, note)
    except Exception as exc:
        error = f"Error bloqueando versión: {exc}"

    ctx = gz_s8_review.build_context(blob, vid)
    ctx["lock_error"] = error
    return render_template("wizard/_s8_lock.html", vid=vid, n=8, **ctx)
