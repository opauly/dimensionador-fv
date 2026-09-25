from __future__ import annotations
"""Facturación tab — line-item editor over `project_invoice_items`, plus the
per-category summary and the contract-reconciliation line — Phase 22 Step 7
(plan §1.4 items 35-42, §1.6, §1.10.1/§1.10.4, `webapp/blueprints/
projects_invoicing.py` per §1.7's route table). **New construction** — there
is no Streamlit page to port; the design basis is §1.10 and the oracle is
§1.10.5's hand-computed reference numbers, not a side-by-side diff.

Structurally this is `projects_ledger.py`'s edit model applied to a
different table and a reconciliation summary instead of a straight TOTAL sum
(plan §1.6: "Same shape as the Facturación editor" is stated the other way
around in that module's docstring — read it for the full round-trip
rationale, only lightly restated here):

- `Guardar cambios` is one `<form hx-post>`. Rows carrying a hidden `id` are
  updated (`update_invoice_item`); rows with no `id` are inserted
  (`add_invoice_item`) — ⚠ **unless `Artículo` (description) is blank, in
  which case they are silently skipped, never inserted** (item 41/25's
  ledger-equivalent rule).
- `+ Fila` re-renders the whole fragment from the *posted* values plus one
  blank row appended — nothing persisted (plan §1.2's round-trip rule).
- Row deletion is **never** inferred from a row's absence in the Guardar
  payload — a persisted row's "✕" is its own explicit GET-confirm/POST-delete
  pair (`_factura_delete.html`).
- ⚠ **`iva_amount`/`total_usd` are Postgres GENERATED columns (plan item 36,
  §1.10.1).** They are never rendered as named form fields here, so no
  Guardar payload can carry them by construction — `database/projects_db.py`'s
  `_clean()` also strips them server-side, but this module does not rely on
  that as its only guard.
- ⚠ **`Categoría` has a DB CHECK constraint** (`config.INVOICE_CATEGORIES`).
  Both the insert and the update path validate it explicitly and raise a
  friendly, caught `ValueError` instead of letting a raw Postgres
  constraint-violation exception surface as a 500 (item 8 of this step's
  validation) — a tampered/invalid posted value never reaches the DB layer.
- A **new** row (via "+ Fila") defaults to `category="equipos"`, `iva_label
  ="0%"` (§1.10.1's documented convenience — "0% when equipos, 13%
  otherwise" — fully editable, never enforced; there is no reactive
  category->rate sync once the row is on screen, only this one starting
  default).

**⚠ The summary block (per-category totals, TOTAL GENERAL, Δ) is always
computed from the *persisted* `bundle["invoice_items"]`, never from
`pending_rows`** — exactly mirroring `projects_ledger.py`'s TOTAL line, which
sums the original fetched rows regardless of in-progress edits (plan §4 risk
#7's split, applied here). This keeps Facturación's reconciliation line
honest about what is actually saved, and keeps it from ever looking like it
moves before a save does.

⚠ **This tab never touches `utilidad_bruta`/`iva_a_pagar`/`utilidad_neta`**
(plan item 40) — `invoice_summary()` is a pure function fed only
`bundle["invoice_items"]`/`project`/`bundle["extras"]`, and no route in this
module calls `summarize()` or writes anything outside `project_invoice_items`.
"""
from flask import abort, redirect, render_template, request, url_for

from webapp.blueprints.projects_common import (
    INVOICE_CATEGORY_LABELS, detail_ctx, fmt_usd, iva_label_to_rate, iva_rate_to_label,
)
from webapp.wizard_steps.common import parse_rows

_ROW_FIELDS = ["id", "description", "category", "amount_usd", "iva_label"]
_BLANK_ROW = {field: None for field in _ROW_FIELDS}


def _parse_amount(raw) -> float:
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return amount if amount >= 0 else 0.0


def _new_row_base() -> dict:
    from config import INVOICE_CATEGORIES

    # §1.10.1's documented convenience: a brand-new row defaults to the first
    # category (equipos) at 0% — fully editable afterwards, never enforced.
    return {
        "id": None, "description": "", "category": INVOICE_CATEGORIES[0],
        "amount_str": "0.00", "iva_label": "0%", "iva_str": fmt_usd(0), "total_str": fmt_usd(0),
    }


def _row_from_db(item: dict) -> dict:
    amount = float(item.get("amount_usd") or 0)
    return {
        "id": item.get("id"),
        "description": item.get("description") or "",
        "category": item.get("category") or "",
        "amount_str": f"{amount:.2f}",
        "iva_label": iva_rate_to_label(item.get("iva_rate")),
        # ⚠ display-only, straight from the Postgres-generated columns
        # already present on every fetched row (plan item 36) — never
        # recomputed from a pending edit, same rule as the ledger's own
        # per-row Total.
        "iva_str": fmt_usd(item.get("iva_amount")),
        "total_str": fmt_usd(item.get("total_usd")),
    }


def _merge_pending(base: dict, pending: dict) -> dict:
    """Overlay one posted (still-unsaved) row's editable fields onto `base`
    (either a persisted row's display dict, or a fresh new-row base). `id` /
    `iva_str` / `total_str` always come from `base` — the posted form never
    carries the generated columns (plan item 36; §1.2's round-trip rule only
    ever touches editable fields)."""
    merged = dict(base)
    if pending.get("description") is not None:
        merged["description"] = pending["description"]
    if pending.get("category") is not None:
        merged["category"] = pending["category"]
    if pending.get("amount_usd") is not None:
        merged["amount_str"] = pending["amount_usd"]
    if pending.get("iva_label") is not None:
        merged["iva_label"] = pending["iva_label"]
    return merged


def _invoice_rows(items: list[dict], pending_rows: list[dict] | None) -> list[dict]:
    if pending_rows is None:
        return [_row_from_db(i) for i in items]

    by_id = {i["id"]: i for i in items if i.get("id")}
    display = []
    for pending in pending_rows:
        row_id = pending.get("id")
        base = _row_from_db(by_id[row_id]) if row_id and row_id in by_id else _new_row_base()
        display.append(_merge_pending(base, pending))
    return display


def render_panel(ctx: dict, *, pending_rows: list[dict] | None = None, error: str | None = None) -> str:
    """Renders `projects/_facturacion.html` — the one place a `detail_ctx()`
    result becomes a Facturación fragment, shared by `projects.py`'s GET tab
    dispatch and every write route below (plan §1.3).

    ⚠ The summary block always reads `ctx["bundle"]["invoice_items"]` (the
    persisted rows) — never `pending_rows` — so Δ and the per-category totals
    can never appear to move before a save actually happens.
    """
    from calculations.project_finance import invoice_summary
    from config import INVOICE_CATEGORIES

    project = ctx["project"]
    items = ctx["bundle"]["invoice_items"]
    extras = ctx["bundle"]["extras"]

    rows = _invoice_rows(items, pending_rows)
    summary = invoice_summary(items, project, extras)

    category_rows = [
        {
            "label": INVOICE_CATEGORY_LABELS.get(cat, cat),
            "subtotal": fmt_usd(summary["by_category"][cat]["subtotal"]),
            "iva": fmt_usd(summary["by_category"][cat]["iva"]),
            "total": fmt_usd(summary["by_category"][cat]["total"]),
        }
        for cat in INVOICE_CATEGORIES
    ]

    delta = summary["delta"]
    delta_ok = abs(delta) < 0.01

    return render_template(
        "projects/_facturacion.html",
        pid=project["id"],
        rows=rows,
        category_rows=category_rows,
        subtotal_str=fmt_usd(summary["subtotal"]),
        iva_str=fmt_usd(summary["iva"]),
        total_general_str=fmt_usd(summary["total_general"]),
        delta_str=fmt_usd(delta),
        delta_ok=delta_ok,
        category_options=[(cat, INVOICE_CATEGORY_LABELS.get(cat, cat)) for cat in INVOICE_CATEGORIES],
        error=error,
    )


def _fresh_panel_or_error(pid: str, *, pending_rows=None, error=None):
    """Shared `detail_ctx()` fetch + two-state error handling (plan item 13's
    shape, reused here exactly as `projects_ledger.py` reuses it) for the
    write routes below, which don't go through `projects.py:_project_page()`.
    """
    try:
        ctx = detail_ctx(pid, active_tab="facturacion")
    except Exception as exc:
        return render_template("admin/_error.html", message=f"Error cargando proyecto: {exc}")
    if ctx is None:
        return render_template("admin/_error.html", message="Proyecto no encontrado.")
    return render_panel(ctx, pending_rows=pending_rows, error=error)


def register(bp):
    @bp.route("/<pid>/facturacion", methods=["POST"])
    def facturacion_guardar(pid):
        from config import INVOICE_CATEGORIES
        from database.projects_db import add_invoice_item, update_invoice_item

        pending = parse_rows(request.form, "row", _ROW_FIELDS)
        error = None
        try:
            for row in pending:
                row_id = row.get("id")
                description = row.get("description")
                category = row.get("category")
                amount = _parse_amount(row.get("amount_usd"))
                iva_rate = iva_label_to_rate(row.get("iva_label"))
                if row_id:
                    # ⚠ item 8: a tampered/invalid category must be a
                    # friendly, caught error — never a raw CHECK-constraint
                    # violation surfacing as a 500.
                    if category not in INVOICE_CATEGORIES:
                        raise ValueError(f"Categoría inválida: {category!r}")
                    update_invoice_item(
                        row_id,
                        description=description if description is not None else "",
                        category=category, amount_usd=amount, iva_rate=iva_rate,
                    )
                else:
                    if not description:
                        continue  # ⚠ item 41: blank-Artículo new rows are skipped, not inserted
                    if category not in INVOICE_CATEGORIES:
                        raise ValueError(f"Categoría inválida: {category!r}")
                    add_invoice_item(pid, description, category, amount, iva_rate)
        except Exception as exc:
            error = f"Error al guardar cambios: {exc}"

        if error:
            return _fresh_panel_or_error(pid, pending_rows=pending, error=error)

        return redirect(url_for("projects.facturacion", pid=pid), code=303)

    @bp.route("/<pid>/facturacion/fila", methods=["POST"])
    def facturacion_fila(pid):
        pending = parse_rows(request.form, "row", _ROW_FIELDS)
        pending.append(dict(_BLANK_ROW))
        return _fresh_panel_or_error(pid, pending_rows=pending)

    @bp.route("/<pid>/factura/<iid>/eliminar")
    def factura_eliminar_confirmar(pid, iid):
        confirm = not request.args.get("cancel")
        return render_template("projects/_factura_delete.html", pid=pid, iid=iid, confirm=confirm, error=None)

    @bp.route("/<pid>/factura/<iid>/eliminar", methods=["POST"])
    def factura_eliminar(pid, iid):
        from database.projects_db import delete_invoice_item

        try:
            delete_invoice_item(iid)
        except Exception as exc:
            return render_template(
                "projects/_factura_delete.html", pid=pid, iid=iid, confirm=True,
                error=f"Error al eliminar: {exc}",
            )
        return redirect(url_for("projects.facturacion", pid=pid), code=303)
