from __future__ import annotations
"""Presupuesto tab — Pagos block write paths (Phase 22 Step 4, plan §1.4
items 15/17, §1.7's `projects_budget.py`).

Two routes, registered onto `webapp.blueprints.projects.bp` the same way
`maintenance_detail.register(bp)` does for Mantenimiento:

- `POST /<pid>/pago/<payment_id>` — the per-payment `Guardar` action. Calls
  `update_payment(payment_id, paid=…, paid_date=…, bank_account=…)`, **never**
  `mark_payment_paid()` (plan item 15 — the checkbox must be able to
  *un*-mark a payment, and `mark_payment_paid()` always sets `paid=True`).
  Re-renders the whole Presupuesto panel from a fresh `detail_ctx()` call
  (plan §1.6: "swap the whole Presupuesto panel, so the Recibido line and
  UTILIDAD cards can never drift from the row").

  ⚠ Item 50/§1.10.3, the load-bearing rule this module exists to protect:
  the payload sent to `update_payment()` here is `{paid, paid_date,
  bank_account}` and **nothing else** — never `onvo_commission_pct`,
  `onvo_iva_pct` or `net_deposited`. `update_payment(payment_id, **fields)`
  (database/projects_db.py) issues a Postgrest `.update(payload)` — a partial
  column update, not a full-row overwrite — so simply never *including* those
  three keys in `fields` is sufficient to leave them untouched; there is no
  need to fetch-and-preserve them first. A future edit to this module that
  adds more fields to the payload MUST NOT add those three; that is Step 8's
  `projects_payments.py:.../onvo` route's job, on a different URL.

- `POST /<pid>/pago` — `+ Agregar pago`. Calls `add_payment(project_id,
  int(number), float(amount))` with no extra kwargs, so the two ONVO rate
  columns and `net_deposited` are left to their (post-migration-048) table
  defaults `0 / 0 / NULL` (plan item 17, §1.10.3 Step 0). Plain form POST +
  303 back to the project (plan §1.6's table), unlike the Guardar action
  above.
"""
from flask import redirect, render_template, request, url_for

from webapp.blueprints.projects_common import detail_ctx


def _parse_amount(raw) -> float:
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return amount if amount > 0 else 0.0


def register(bp):
    @bp.route("/<pid>/pago/<payment_id>", methods=["POST"])
    def pago_guardar(pid, payment_id):
        from database.projects_db import update_payment

        form = request.form
        paid = form.get("paid") == "on"
        paid_date = (form.get("paid_date") or "").strip() or None
        bank_account = (form.get("bank_account") or "").strip() or None

        error = None
        try:
            # ⚠ Exactly these three keys — see the module docstring's item
            # 50 note. Never add onvo_commission_pct / onvo_iva_pct /
            # net_deposited to this payload.
            update_payment(payment_id, paid=paid, paid_date=paid_date, bank_account=bank_account)
        except Exception as exc:
            error = f"Error al guardar el pago: {exc}"

        try:
            ctx = detail_ctx(pid, active_tab="presupuesto")
        except Exception as exc:
            return render_template("admin/_error.html", message=f"Error cargando proyecto: {exc}")
        if ctx is None:
            return render_template("admin/_error.html", message="Proyecto no encontrado.")

        return render_template("projects/_presupuesto.html", pago_error=error, **ctx)

    @bp.route("/<pid>/pago", methods=["POST"])
    def pago_agregar(pid):
        from database.projects_db import add_payment

        form = request.form
        # ⚠ plan item 17: default is computed server-side in
        # projects_common._presupuesto_ctx (`next_payment_number`) and
        # rendered into the form's own input `value`, so the normal path
        # never reaches this fallback. Only re-fetched here (one extra
        # detail_ctx() call) on the edge case of a blank/unparseable field.
        try:
            number = int(str(form.get("payment_number")).strip())
        except (TypeError, ValueError):
            try:
                ctx = detail_ctx(pid, active_tab="presupuesto")
            except Exception:
                ctx = None
            number = (ctx or {}).get("next_payment_number", 1)

        amount = _parse_amount(form.get("amount_usd"))

        add_payment(pid, number, amount)

        return redirect(url_for("projects.detalle", pid=pid), code=303)
