from __future__ import annotations
"""The five shared expense ledgers — Banco / Equipo / Materiales / Viáticos /
Extras (gastos) — Phase 22 Step 5 (plan §1.4 items 21-27, §1.6, §0.4 Q4,
`webapp/blueprints/projects_ledger.py` per §1.7's route table).

One renderer, five categories. `<categoria>` is always validated against
`projects_common.LEDGER_TAB_CATEGORIES` (`config.EXPENSE_CATEGORIES` minus
`mano_de_obra` — that rubro has its own tab with no expense-entry form, plan
item 28) — every route below 404s on anything else, including `mano_de_obra`
itself, rather than silently rendering an empty ledger.

**Edit model (plan §1.6 / §0.4 Q4), mirrored from `projects_budget.py`'s
Pagos block:**
- `Guardar cambios` is one `<form hx-post>` per ledger. Rows carrying a
  hidden `id` are updated (`update_expense`); rows with no `id` are inserted
  (`add_expense`) — ⚠ **unless their `Rubro`/description is blank, in which
  case they are silently skipped, never inserted** (item 25). Htmx follows
  the write's `303` redirect back into `#subpanel`, so a save always ends on
  the freshly-persisted state; a write exception re-renders this same
  fragment with `pending_rows` preserved (§1.2's round-trip rule) instead of
  losing the operator's typing.
- `+ Fila` re-renders the whole fragment from the *posted* form values plus
  one blank row appended — nothing is persisted. This is the one behaviour
  Step 5's own validation calls "the easiest thing here to get wrong": two
  already-typed, still-unsaved rows must both survive the round trip.
- Row deletion is **never** inferred from a row's absence in the Guardar
  payload (§0.4 Q4 — a truncated POST or a stray missing `<input>` must never
  delete a money row). A *persisted* row's `✕` is an explicit
  GET-confirm/POST-delete pair (`_ledger_delete.html`, same shape as
  `maintenance/_delete_confirm.html`); an *unsaved* new row's `✕` just drops
  that `<tr>` from the DOM (nothing exists in the DB yet to delete, so no
  round trip is needed either).
- `Total` (`total_with_iva`) is display-only, straight from the Postgres
  generated column already present on every fetched row — it is never
  rendered as a named form field, so no Guardar payload can carry it, by
  construction, not only via `projects_db._clean()`'s server-side strip
  (plan item 23).

**Budget-skeleton dimming (item 24, §0.4 Q5's disclosed deviation — new
behaviour `st.data_editor` could not render, not something to diff against
Streamlit):** a row with `amount_usd == 0 and budgeted_usd > 0` renders
dimmed with a small "presupuesto" pill, computed from the row's *persisted*
values only — never from an unsaved, posted-but-not-yet-saved edit.

Every route re-derives its context from `projects_common.detail_ctx()`
(plan §1.3): this module never keeps its own copy of `bundle["expenses"]`
across a request, and the Presupuesto tab's GASTOS rubro / TOTAL always
reflect the same DB state this ledger just wrote.
"""
from flask import abort, redirect, render_template, request, url_for

from webapp.blueprints.projects_common import (
    LEDGER_TAB_CATEGORIES, RUBRO_LABELS, detail_ctx, fmt_usd, iva_label_to_rate, iva_rate_to_label,
)
from webapp.wizard_steps.common import parse_rows

_ROW_FIELDS = ["id", "description", "amount_usd", "iva_label", "expense_date", "paid", "notes"]
_BLANK_ROW = {field: None for field in _ROW_FIELDS}

_NEW_ROW_BASE = {
    "id": None, "description": "", "amount_str": "0.00", "iva_label": "0%",
    "expense_date": "", "paid": False, "notes": "", "total_str": fmt_usd(0), "dimmed": False,
}


def _parse_amount(raw) -> float:
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return amount if amount >= 0 else 0.0


def _row_from_db(expense: dict) -> dict:
    amount = float(expense.get("amount_usd") or 0)
    budgeted = float(expense.get("budgeted_usd") or 0)
    return {
        "id": expense.get("id"),
        "description": expense.get("description") or "",
        "amount_str": f"{amount:.2f}",
        "iva_label": iva_rate_to_label(expense.get("iva_rate")),
        "expense_date": expense.get("expense_date") or "",
        "paid": bool(expense.get("paid")),
        "notes": expense.get("notes") or "",
        "total_str": fmt_usd(expense.get("total_with_iva")),
        # ⚠ item 24: dimming is always computed off the row's own persisted
        # values, never off a pending/unsaved override.
        "dimmed": amount == 0 and budgeted > 0,
    }


def _merge_pending(base: dict, pending: dict) -> dict:
    """Overlay one posted (still-unsaved) row's editable fields onto `base`
    (either a persisted row's display dict, or `_NEW_ROW_BASE` for a row with
    no `id`). `id` / `total_str` / `dimmed` always come from `base` — the
    posted form never carries them (plan item 23; §1.2's round-trip rule only
    ever touches editable fields)."""
    merged = dict(base)
    if pending.get("description") is not None:
        merged["description"] = pending["description"]
    if pending.get("amount_usd") is not None:
        merged["amount_str"] = pending["amount_usd"]
    if pending.get("iva_label") is not None:
        merged["iva_label"] = pending["iva_label"]
    if pending.get("expense_date") is not None:
        merged["expense_date"] = pending["expense_date"]
    # Checkboxes are simply absent from the posted form when unchecked
    # (parse_rows then reports None) — there is no "blank means keep the old
    # value" case to preserve here, unlike the text fields above.
    merged["paid"] = pending.get("paid") == "on"
    if pending.get("notes") is not None:
        merged["notes"] = pending["notes"]
    return merged


def _ledger_rows(expenses: list[dict], pending_rows: list[dict] | None) -> tuple[list[dict], str]:
    """`expenses` is `bundle["expenses"]` already filtered to one category,
    in `created_at` order (plan item 21 — the caller does the filtering, this
    function never re-fetches). Returns the display rows plus the TOTAL
    line's already-formatted string.

    ⚠ TOTAL is `Σ total_with_iva` over `expenses` — the persisted, Postgres-
    generated values — regardless of `pending_rows`, exactly mirroring
    `pages/04_project_detail.py` L389 (its own TOTAL line sums the *original*
    `rows` argument, never the data_editor's in-progress edits). A ledger's
    TOTAL and the Presupuesto tab's `costo_total` are two independently
    computed figures by design (plan §4 risk #7) — this function is the one
    place the ledger side of that split lives.
    """
    total_with_iva = sum(float(e.get("total_with_iva") or 0) for e in expenses)
    total_str = fmt_usd(total_with_iva)

    if pending_rows is None:
        return [_row_from_db(e) for e in expenses], total_str

    by_id = {e["id"]: e for e in expenses if e.get("id")}
    display = []
    for pending in pending_rows:
        row_id = pending.get("id")
        base = _row_from_db(by_id[row_id]) if row_id and row_id in by_id else dict(_NEW_ROW_BASE)
        display.append(_merge_pending(base, pending))
    return display, total_str


def render_panel(ctx: dict, categoria: str, *, pending_rows: list[dict] | None = None,
                  error: str | None = None) -> str:
    """Renders `projects/_ledger.html` for one category — the one place a
    `detail_ctx()` result becomes a ledger fragment, shared by
    `projects.py`'s GET tab dispatch and every write route below (plan §1.3:
    one context builder, rendered from everywhere)."""
    expenses = [e for e in ctx["bundle"]["expenses"] if e.get("category") == categoria]
    rows, total_str = _ledger_rows(expenses, pending_rows)
    return render_template(
        "projects/_ledger.html",
        pid=ctx["project"]["id"], categoria=categoria,
        label=RUBRO_LABELS.get(categoria, categoria),
        rows=rows, total_str=total_str, error=error,
    )


def _fresh_panel_or_error(pid: str, categoria: str, *, pending_rows=None, error=None):
    """Shared `detail_ctx()` fetch + two-state error handling (plan item 13's
    shape, reused here exactly as `projects_budget.py:pago_guardar` reuses
    it) for the write routes below, which don't go through
    `projects.py:_project_page()`."""
    try:
        ctx = detail_ctx(pid, active_tab=categoria)
    except Exception as exc:
        return render_template("admin/_error.html", message=f"Error cargando proyecto: {exc}")
    if ctx is None:
        return render_template("admin/_error.html", message="Proyecto no encontrado.")
    return render_panel(ctx, categoria, pending_rows=pending_rows, error=error)


def register(bp):
    @bp.route("/<pid>/gastos/<categoria>", methods=["POST"])
    def gastos_guardar(pid, categoria):
        if categoria not in LEDGER_TAB_CATEGORIES:
            abort(404)
        from database.projects_db import add_expense, update_expense

        pending = parse_rows(request.form, "row", _ROW_FIELDS)
        error = None
        try:
            for row in pending:
                row_id = row.get("id")
                description = row.get("description")
                amount = _parse_amount(row.get("amount_usd"))
                iva_rate = iva_label_to_rate(row.get("iva_label"))
                expense_date = row.get("expense_date")
                paid = row.get("paid") == "on"
                notes = row.get("notes")
                if row_id:
                    update_expense(
                        row_id,
                        description=description if description is not None else "",
                        amount_usd=amount, iva_rate=iva_rate,
                        expense_date=expense_date, paid=paid, notes=notes,
                    )
                else:
                    if not description:
                        continue  # ⚠ item 25: blank-Rubro new rows are skipped, not inserted
                    add_expense(
                        pid, categoria, description, amount,
                        iva_rate=iva_rate, paid=paid, expense_date=expense_date, notes=notes,
                    )
        except Exception as exc:
            error = f"Error al guardar cambios: {exc}"

        if error:
            return _fresh_panel_or_error(pid, categoria, pending_rows=pending, error=error)

        return redirect(url_for("projects.gastos", pid=pid, categoria=categoria), code=303)

    @bp.route("/<pid>/gastos/<categoria>/fila", methods=["POST"])
    def gastos_fila(pid, categoria):
        if categoria not in LEDGER_TAB_CATEGORIES:
            abort(404)
        pending = parse_rows(request.form, "row", _ROW_FIELDS)
        pending.append(dict(_BLANK_ROW))
        return _fresh_panel_or_error(pid, categoria, pending_rows=pending)

    @bp.route("/<pid>/gasto/<eid>/eliminar")
    def gasto_eliminar_confirmar(pid, eid):
        categoria = request.args.get("categoria", "")
        if categoria not in LEDGER_TAB_CATEGORIES:
            abort(404)
        confirm = not request.args.get("cancel")
        return render_template(
            "projects/_ledger_delete.html", pid=pid, eid=eid, categoria=categoria, confirm=confirm, error=None,
        )

    @bp.route("/<pid>/gasto/<eid>/eliminar", methods=["POST"])
    def gasto_eliminar(pid, eid):
        from database.projects_db import delete_expense

        categoria = request.form.get("categoria", "")
        if categoria not in LEDGER_TAB_CATEGORIES:
            abort(404)
        try:
            delete_expense(eid)
        except Exception as exc:
            return render_template(
                "projects/_ledger_delete.html", pid=pid, eid=eid, categoria=categoria, confirm=True,
                error=f"Error al eliminar: {exc}",
            )
        return redirect(url_for("projects.gastos", pid=pid, categoria=categoria), code=303)
