from __future__ import annotations
"""Mano de obra tab — worker cards + adelantos — Phase 22 Step 6 (plan §1.4
items 28-34, `webapp/blueprints/projects_labor.py` per §1.7's route table).

⚠ **No expense-entry form anywhere on this tab.** `PLAN_PHASE6.md` §1.6 and
`pages/04_project_detail.py::_render_labor_tab()`'s own docstring explain why:
an `add_expense(..., category="mano_de_obra")` path would double-count this
rubro in `calculations/project_finance.py::_summarize_by_category()` — the
ONLY way this rubro's cost moves is an adelanto on a worker row, via
`add_advance()` / `delete_advance()`. Do not add one (item 28). This module
never imports `add_expense`.

**Shape, one card per `project_labor` row:**
- `{worker_name} · {role}` (role suffix only when set), then Cotización /
  Total adelantado / Saldo pendiente — the last from
  `calculations/project_finance.py::labor_balance()`, red when negative
  (item 29).
- An adelantos table (`Adelanto · Monto · Fecha · (Eliminar)`, item 30) —
  `Eliminar` is `delete_advance(labor_id, number)`, which ⚠ **renumbers the
  survivors 1..N** (`projects_db.py` L531-557) — a real, deliberate behaviour,
  not a bug. `Sin adelantos registrados.` when a worker has none (item 31).
- `+ Adelanto` (Monto USD + free-text Fecha -> `add_advance()`, item 32) and
  `Editar / eliminar trabajador` (-> `update_labor()` with Streamlit's exact
  blank-name fallback, plus `Eliminar trabajador` -> `delete_labor()`, item
  33) live in `<details>` blocks per worker card — Streamlit's `st.expander`
  translated per plan §1.2's table, no server-side widget state.
- `Sin trabajadores registrados.` when the project has no workers (item 31),
  and `+ Agregar trabajador` (-> `add_labor()`, `Ingresa un nombre para el
  trabajador.` on a blank name, item 34) below the card list.

**htmx shape (plan §1.6's table: "Labor add/edit/delete, advance add/
delete" -> "form POST + 303"):** every mutating form here is a *plain*
`<form method="post">` (no `hx-post`), so a successful write's `303` causes a
normal full-page navigation back onto the freshly rendered Mano de obra tab —
the same shape `_header.html`'s status pills and "Crear proyecto" already use
in this app. The two destructive actions (`Eliminar trabajador`, an
adelanto's `✕`) get an inline htmx GET-confirm first (`_labor_delete.html`,
same shape as `maintenance/_delete_confirm.html` / `_ledger_delete.html`) —
Streamlit deletes on the first click; this is the same disclosed hardening
Step 5 added for the expense ledgers (plan §4 risk #3).

Every route re-derives its context from `projects_common.detail_ctx()` (plan
§1.3): this module never keeps its own copy of `bundle["labor"]` across a
request, so a card's own numbers and the Presupuesto tab's `mano_de_obra`
rubro can never drift from what was just written.
"""
from flask import redirect, render_template, request, url_for

from webapp.blueprints.projects_common import detail_ctx, fmt_usd


def _parse_amount(raw) -> float:
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return amount if amount >= 0 else 0.0


def _worker_ctx(row: dict, *, error: str | None = None) -> dict:
    from calculations.project_finance import labor_balance

    quoted = float(row.get("quoted_amount") or 0)
    total_advanced = float(row.get("total_advanced") or 0)
    balance = labor_balance(row)
    advances = sorted(row.get("advances") or [], key=lambda a: a.get("number") or 0)
    return {
        "id": row["id"],
        "worker_name": row.get("worker_name") or "",
        "role": row.get("role") or "",
        "quoted_str": fmt_usd(quoted),
        "quoted_raw": f"{quoted:.2f}",
        "total_advanced_str": fmt_usd(total_advanced),
        "balance_str": fmt_usd(balance),
        # ⚠ item 29: red when negative (advances exceed the cotización).
        "balance_negative": balance < 0,
        "advances": [
            {
                "number": a.get("number"),
                "amount_str": fmt_usd(a.get("amount")),
                "date": a.get("date") or "—",
            }
            for a in advances
        ],
        "error": error,
    }


def render_panel(ctx: dict, *, nuevo_error: str | None = None, worker_errors: dict | None = None) -> str:
    """Renders `projects/_labor.html` — the one place a `detail_ctx()` result
    becomes the Mano de obra fragment, shared by `projects.py`'s GET tab
    dispatch and every write route below (plan §1.3)."""
    worker_errors = worker_errors or {}
    workers = [_worker_ctx(row, error=worker_errors.get(row.get("id"))) for row in ctx["bundle"]["labor"]]
    return render_template(
        "projects/_labor.html",
        pid=ctx["project"]["id"], workers=workers, nuevo_error=nuevo_error,
    )


def _fresh_panel_or_error(pid: str, *, nuevo_error: str | None = None, worker_errors: dict | None = None):
    """Shared `detail_ctx()` fetch + two-state error handling (plan item 13's
    shape, reused here exactly as `projects_ledger.py`'s helper of the same
    name does) for the write routes below."""
    try:
        ctx = detail_ctx(pid, active_tab="mano_de_obra")
    except Exception as exc:
        return render_template("admin/_error.html", message=f"Error cargando proyecto: {exc}")
    if ctx is None:
        return render_template("admin/_error.html", message="Proyecto no encontrado.")
    return render_panel(ctx, nuevo_error=nuevo_error, worker_errors=worker_errors)


def register(bp):
    @bp.route("/<pid>/trabajador", methods=["POST"])
    def trabajador_agregar(pid):
        from database.projects_db import add_labor

        form = request.form
        name = (form.get("worker_name") or "").strip()
        role = (form.get("role") or "").strip()
        quoted = _parse_amount(form.get("quoted_amount"))

        if not name:
            # ⚠ item 34: blank-name error, nothing written.
            return _fresh_panel_or_error(pid, nuevo_error="Ingresa un nombre para el trabajador.")

        try:
            add_labor(pid, name, quoted, role=role)
        except Exception as exc:
            return _fresh_panel_or_error(pid, nuevo_error=f"Error: {exc}")

        return redirect(url_for("projects.mano_de_obra", pid=pid), code=303)

    @bp.route("/<pid>/trabajador/<lid>", methods=["POST"])
    def trabajador_editar(pid, lid):
        from database.projects_db import update_labor

        form = request.form
        edit_name = (form.get("worker_name") or "").strip()
        edit_role = (form.get("role") or "").strip()
        quoted = _parse_amount(form.get("quoted_amount"))

        try:
            ctx = detail_ctx(pid, active_tab="mano_de_obra")
        except Exception as exc:
            return render_template("admin/_error.html", message=f"Error cargando proyecto: {exc}")
        if ctx is None:
            return render_template("admin/_error.html", message="Proyecto no encontrado.")

        current = next((w for w in ctx["bundle"]["labor"] if w.get("id") == lid), None)
        old_name = (current or {}).get("worker_name") or ""

        try:
            # ⚠ item 33: Streamlit's exact fallback — a blank name keeps the
            # old one, it does not clear it or error.
            update_labor(lid, worker_name=edit_name or old_name, role=edit_role, quoted_amount=quoted)
        except Exception as exc:
            return render_panel(ctx, worker_errors={lid: f"Error: {exc}"})

        return redirect(url_for("projects.mano_de_obra", pid=pid), code=303)

    @bp.route("/<pid>/trabajador/<lid>/eliminar")
    def trabajador_eliminar_confirmar(pid, lid):
        confirm = not request.args.get("cancel")
        return render_template(
            "projects/_labor_delete.html", pid=pid, kind="trabajador", lid=lid, number=None,
            confirm=confirm, error=None,
        )

    @bp.route("/<pid>/trabajador/<lid>/eliminar", methods=["POST"])
    def trabajador_eliminar(pid, lid):
        from database.projects_db import delete_labor

        try:
            delete_labor(lid)
        except Exception as exc:
            return render_template(
                "projects/_labor_delete.html", pid=pid, kind="trabajador", lid=lid, number=None,
                confirm=True, error=f"Error al eliminar: {exc}",
            )
        return redirect(url_for("projects.mano_de_obra", pid=pid), code=303)

    @bp.route("/<pid>/trabajador/<lid>/adelanto", methods=["POST"])
    def adelanto_agregar(pid, lid):
        from database.projects_db import add_advance

        form = request.form
        amount = _parse_amount(form.get("amount"))
        date = (form.get("date") or "").strip() or None

        try:
            add_advance(lid, amount, date)
        except Exception as exc:
            return _fresh_panel_or_error(pid, worker_errors={lid: f"Error: {exc}"})

        return redirect(url_for("projects.mano_de_obra", pid=pid), code=303)

    @bp.route("/<pid>/trabajador/<lid>/adelanto/<int:number>/eliminar")
    def adelanto_eliminar_confirmar(pid, lid, number):
        confirm = not request.args.get("cancel")
        return render_template(
            "projects/_labor_delete.html", pid=pid, kind="adelanto", lid=lid, number=number,
            confirm=confirm, error=None,
        )

    @bp.route("/<pid>/trabajador/<lid>/adelanto/<int:number>/eliminar", methods=["POST"])
    def adelanto_eliminar(pid, lid, number):
        from database.projects_db import delete_advance

        try:
            # ⚠ item 30: delete_advance() renumbers the survivors 1..N —
            # deliberate, not a bug to route around.
            delete_advance(lid, number)
        except Exception as exc:
            return render_template(
                "projects/_labor_delete.html", pid=pid, kind="adelanto", lid=lid, number=number,
                confirm=True, error=f"Error al eliminar: {exc}",
            )
        return redirect(url_for("projects.mano_de_obra", pid=pid), code=303)
