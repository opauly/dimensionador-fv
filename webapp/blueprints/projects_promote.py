from __future__ import annotations
"""The Cotizaciones -> Proyectos integration — "Mover a Proyecto" — Phase 22
Step 9 (plan §1.9, §1.4 items 51-53, `webapp/blueprints/projects_promote.py`
per §1.7's route table). **Closes the disabled placeholder Phase 20 left in
proposals/_detail.html** — everything below only exists to turn that
placeholder into `promote_to_project()` calls; it is otherwise a small,
self-contained module by design.

**Three routes, exactly** (plan §1.9's own enumeration — no fourth route is
added for "+ Fila"; both budget-row and custom-schedule-row "+ Fila"
affordances repost to the same `.../tabla` route below with an `accion`
flag, so the route count stays three):

- `GET /promover/<pid>/<vid>` — read-only, writes nothing. Renders the form
  seeded by `derive_contract_terms()` + `derive_budget_rows()` (the *only*
  two calls to those functions in this whole module — item 53: no
  derivation of any kind happens anywhere else here).
- `POST /promover/<pid>/<vid>/tabla` — re-renders the same fragment from
  **posted** values only (plan §1.2's round-trip rule, the same one every
  other editable table in this app follows). Touches no database row.
  `payment_schedule_for_preset()` is called here only to *preview* the two
  named presets (70/30, 50/40/10) — never to compute "Personalizado", which
  is round-tripped verbatim from whatever the operator typed.
- `POST /promover/<pid>/<vid>` — the actual `promote_to_project()` call.
  Skips blank-Concepto budget rows exactly as `pages/01_proposals.py`
  L562-563 does, then either 303s to `/proyectos/<new_id>` or — on a
  `ValueError` (the already-promoted case, item 52, `projects_db.py`
  L240-250) or any other exception — re-renders this same fragment with the
  message inline. **Never a 500.**

**Confirmar is a genuine (non-htmx) `<form method="post">`**, the same
"form POST + 303" convention `projects/_nuevo.html`'s `Crear proyecto` and
`webapp/blueprints/projects.py:crear()` already establish: a successful
promotion is a real browser navigation to the new project's own URL (not an
htmx-swapped fragment still living under `/cotizaciones/<pid>`), and an
inline error re-render returns the same bare fragment `crear()`'s own error
path returns — an accepted, already-shipped precedent, not something this
module invents.

**Nowhere in this module is there a duplicate-id situation.** The form is
loaded into `proposals/_detail.html`'s persistent, empty `#promote-{{ pid
}}` div (plan item 4) via `hx-swap="innerHTML"`, and every round trip in
this module — the live `change`-triggered preview, both "+ Fila" buttons and
"Cancelar" — targets that *same* persistent div with `hx-swap="innerHTML"`
too. This fragment's own root therefore never needs (and never declares) an
id of its own, unlike the outerHTML-swapped fragments elsewhere in this
section (`_ledger.html`, `_facturacion.html`).

**What this module does not touch:** `_detail_ctx()`'s `project`/
`project_error` keys and the "Ver proyecto →" branch stay entirely inside
`proposals/_detail.html` (plan §1.9's "what does not change") — this module
is only ever reached from the `{% else %}` branch (no project yet), so it
never needs to re-derive or duplicate that check itself. `database/
projects_db.py` is not modified.
"""
from flask import redirect, render_template, request, url_for

from webapp.wizard_steps.common import parse_rows

_BUDGET_FIELDS = ["description", "category", "budgeted_usd"]
_SCHEDULE_FIELDS = ["payment_number", "amount_usd"]
PRESET_OPTIONS = ["70/30", "50/40/10", "Personalizado"]


def _parse_money(raw, default: float = 0.0) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _budget_display(pending: list[dict]) -> list[dict]:
    """`row-<i>-*` posted values -> this form's display rows. Unlike the
    ledgers/Facturación, nothing here is ever persisted before Confirmar, so
    there is no DB row to merge onto — the posted string is the only source
    of truth, kept verbatim so a still-unsaved edit is never lost across a
    round trip (plan §1.2)."""
    return [
        {
            "description": row.get("description") or "",
            "category": row.get("category") or "",
            "budgeted_str": row.get("budgeted_usd") if row.get("budgeted_usd") is not None else "0.00",
        }
        for row in pending
    ]


def _schedule_display(pending: list[dict]) -> list[dict]:
    display = []
    for i, row in enumerate(pending, start=1):
        try:
            number = int(float(row.get("payment_number")))
        except (TypeError, ValueError):
            number = i
        display.append({
            "payment_number": number,
            "amount_str": row.get("amount_usd") if row.get("amount_usd") is not None else "0.00",
        })
    return display


def render_panel(
    pid: str, vid: str, *,
    contract_usd, contract_iva_usd, budget_rows: list[dict], preset: str,
    schedule_rows: list[dict], error: str | None = None,
) -> str:
    """Renders `projects/_promote.html` — the one place this form's state
    becomes HTML, shared by all three routes below (plan §1.3's discipline,
    applied to a form that writes nothing until Confirmar).

    ⚠ Item 53: **no derivation happens here.** `payment_schedule_for_preset()`
    is the only `projects_db` function this module calls anywhere, and only
    to preview the two named presets — "Personalizado" is never computed,
    only round-tripped from `schedule_rows`.
    """
    from config import EXPENSE_CATEGORIES
    from database.projects_db import payment_schedule_for_preset
    from webapp.blueprints.projects_common import RUBRO_LABELS, fmt_usd

    contract_total = _parse_money(contract_usd)
    budget_total = sum(_parse_money(r.get("budgeted_str")) for r in budget_rows)

    # ⚠ plan item 51: verbatim from pages/01_proposals.py L513-518. The two
    # figures genuinely differ — budget is estimated cost, contract is the
    # quoted price — do not "reconcile" them into agreement.
    recon_caption = (
        f"Presupuesto de costos (rubros, sin IVA por renglón): {budget_total:,.2f} USD  ·  "
        f"Monto del contrato (cotizado): {contract_total:,.2f} USD — "
        "no son el mismo concepto: el presupuesto es costo estimado, el contrato es el precio "
        "cotizado al cliente."
    )

    # contract_usd is already the FULL total (§1.5) — no `* (1 + rate)` here,
    # matching pages/01_proposals.py L525's own comment.
    total_with_iva = round(contract_total, 2)
    schedule_preview = None
    if preset == "Personalizado":
        if not schedule_rows:
            # First switch to "Personalizado" this session — seed from the
            # 70/30 split, exactly as pages/01_proposals.py L528 does, then
            # let the operator's own edits take over on every later round
            # trip (schedule_rows is non-empty from then on).
            seed = payment_schedule_for_preset(total_with_iva, "70/30")
            schedule_rows = [
                {"payment_number": r["payment_number"], "amount_str": f"{r['amount_usd']:.2f}"}
                for r in seed
            ]
    else:
        computed = payment_schedule_for_preset(total_with_iva, preset)
        schedule_preview = " · ".join(
            f"Pago {r['payment_number']}: {fmt_usd(r['amount_usd'])}" for r in computed
        )
        schedule_rows = [
            {"payment_number": r["payment_number"], "amount_str": f"{r['amount_usd']:.2f}"}
            for r in computed
        ]

    return render_template(
        "projects/_promote.html",
        pid=pid, vid=vid,
        contract_usd=f"{contract_total:.2f}",
        contract_iva_usd=f"{_parse_money(contract_iva_usd):.2f}",
        budget_rows=budget_rows,
        category_options=[(cat, RUBRO_LABELS.get(cat, cat)) for cat in EXPENSE_CATEGORIES],
        preset=preset, preset_options=PRESET_OPTIONS,
        schedule_rows=schedule_rows,
        schedule_preview=schedule_preview,
        recon_caption=recon_caption,
        error=error,
    )


def register(bp):
    @bp.route("/promover/<pid>/<vid>")
    def promover_form(pid, vid):
        """Item 1: read-only, writes nothing. `?cancel=1` (sent by this
        form's own "Cancelar") collapses the persistent `#promote-{{ pid }}`
        div back to empty, mirroring `projects.nuevo(cancel=1)`'s pattern."""
        if request.args.get("cancel"):
            return ""

        from database.projects_db import derive_budget_rows, derive_contract_terms
        from database.proposals_db import get_version

        try:
            version = get_version(vid)
        except Exception as exc:
            return render_template("admin/_error.html", message=f"Error cargando versión: {exc}")
        if not version:
            return render_template("admin/_error.html", message="Versión no encontrada.")

        derived = derive_contract_terms(version)
        seeded = derive_budget_rows(version)
        budget_rows = [
            {
                "description": r["description"], "category": r["category"],
                "budgeted_str": f"{r['budgeted_usd']:.2f}",
            }
            for r in seeded
        ]
        return render_panel(
            pid, vid,
            contract_usd=derived["contract_usd"], contract_iva_usd=derived["contract_iva_usd"],
            budget_rows=budget_rows, preset="70/30", schedule_rows=[],
        )

    @bp.route("/promover/<pid>/<vid>/tabla", methods=["POST"])
    def promover_tabla(pid, vid):
        """Item 2: re-renders the fragment from *posted* values only — no
        database read, no `derive_*` call (item 53). The two "+ Fila"
        buttons repost here with `accion=fila_presupuesto` /
        `accion=fila_calendario` to append one blank row to the relevant
        table before re-rendering, exactly like every other editable table's
        "+ Fila" round trip in this app (plan §1.2), just without a second
        route."""
        form = request.form
        preset = form.get("preset") or "70/30"
        if preset not in PRESET_OPTIONS:
            preset = "70/30"

        pending_budget = parse_rows(form, "row", _BUDGET_FIELDS)
        if form.get("accion") == "fila_presupuesto":
            pending_budget.append({"description": None, "category": None, "budgeted_usd": None})

        pending_schedule = parse_rows(form, "sched", _SCHEDULE_FIELDS)
        if form.get("accion") == "fila_calendario":
            pending_schedule.append({"payment_number": str(len(pending_schedule) + 1), "amount_usd": None})

        return render_panel(
            pid, vid,
            contract_usd=form.get("contract_usd"), contract_iva_usd=form.get("contract_iva_usd"),
            budget_rows=_budget_display(pending_budget), preset=preset,
            schedule_rows=_schedule_display(pending_schedule) if preset == "Personalizado" else [],
        )

    @bp.route("/promover/<pid>/<vid>", methods=["POST"])
    def promote_confirmar(pid, vid):
        """Item 3: the one write in this module. Builds `budget_rows`
        (skipping blank-Concepto rows, exactly as pages/01_proposals.py
        L562-563 does) and `payment_schedule`, then a single
        `promote_to_project()` call — the only source of truth for the
        write itself (item 53). A `ValueError` (item 52 — already promoted)
        or any other exception re-renders this same fragment with the
        message inline, never a 500."""
        from config import EXPENSE_CATEGORIES
        from database.projects_db import payment_schedule_for_preset, promote_to_project

        form = request.form
        contract_usd = _parse_money(form.get("contract_usd"))
        contract_iva_usd = _parse_money(form.get("contract_iva_usd"))
        preset = form.get("preset") or "70/30"
        if preset not in PRESET_OPTIONS:
            preset = "70/30"

        pending_budget = parse_rows(form, "row", _BUDGET_FIELDS)
        budget_rows = []
        for row in pending_budget:
            description = row.get("description")
            if not description:
                continue  # ⚠ item 3 / pages/01_proposals.py L562-563
            category = row.get("category")
            if category not in EXPENSE_CATEGORIES:
                category = EXPENSE_CATEGORIES[0]
            budget_rows.append({
                "description": description, "category": category,
                "budgeted_usd": _parse_money(row.get("budgeted_usd")),
            })

        pending_schedule = parse_rows(form, "sched", _SCHEDULE_FIELDS)
        if preset == "Personalizado":
            payment_schedule = []
            for i, row in enumerate(pending_schedule, start=1):
                amount = row.get("amount_usd")
                if amount is None:
                    continue
                try:
                    number = int(float(row.get("payment_number") or i))
                except (TypeError, ValueError):
                    number = i
                payment_schedule.append({"payment_number": number, "amount_usd": _parse_money(amount)})
        else:
            # ⚠ item 53: the only place this module calls a `projects_db`
            # derivation function on the write path — to reproduce the same
            # named-preset split the preview already showed, never a new one.
            payment_schedule = payment_schedule_for_preset(round(contract_usd, 2), preset)

        try:
            project = promote_to_project(
                pid, vid, contract_usd,
                contract_iva_usd=contract_iva_usd,
                budget_rows=budget_rows,
                payment_schedule=payment_schedule,
            )
        except Exception as exc:
            return render_panel(
                pid, vid,
                contract_usd=form.get("contract_usd"), contract_iva_usd=form.get("contract_iva_usd"),
                budget_rows=_budget_display(pending_budget), preset=preset,
                schedule_rows=_schedule_display(pending_schedule) if preset == "Personalizado" else [],
                error=f"Error: {exc}",
            )

        return redirect(url_for("projects.detalle", pid=project["id"]), code=303)
