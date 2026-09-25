from __future__ import annotations
"""Pagos / ONVO tab — Phase 22 Step 8 (plan §1.4 items 43-50, §1.6, §1.10.2-5,
`PLAN_PHASE6.md` §1.4 + Step 8). **New construction** — there is no
Streamlit page behind this; §1.10.5's hand-computed reference numbers are
the oracle, not a side-by-side diff.

**⚠ There is no `method` column** (§1.10.2). `project_payments` carries
exactly two rates, `onvo_commission_pct` / `onvo_iva_pct`, and this whole
module is built around that: the "método" toggle in `_pagos.html` is a pure
client-side convenience that fills those two `<input>` fields (item 45) —
`Transferencia` -> `0 / 0`, `ONVO tarjeta` -> `config.DEFAULT_ONVO_COMMISSION`
(0.024) / `projects_common.ONVO_IVA_PCT` (0.13) — and nothing here ever
writes a third "method" value anywhere. Both rates stay editable by hand
after the toggle fires.

**⚠ Every displayed money figure is a freshly computed `onvo_breakdown()`
call** (item 46), built here in `render_panel()` from each row's *persisted*
`onvo_commission_pct`/`onvo_iva_pct` — never from the persisted
`net_deposited` column, which exists only for reporting/export and must
never be trusted as a source of a displayed number (a stale or corrupted
value there must not be able to misreport). `net_deposited` **is** written
on save (`pago_onvo_guardar` below), computed the same way, but only as a
write-time side effect.

**Two write routes**, both registered onto `webapp.blueprints.projects.bp`
the same way every other Phase 22 tab module does:

- `POST /<pid>/pago/<payment_id>/onvo` — this tab's own per-payment
  `Guardar`. Persists `onvo_commission_pct`, `onvo_iva_pct`, the
  server-computed `net_deposited`, plus `paid`/`paid_date`/`bank_account`/
  `notes` — all editable in this tab's own row block (item 44). ⚠ This is a
  **different URL** from `projects_budget.py`'s `pago_guardar`
  (`POST /<pid>/pago/<payment_id>`), which is the Presupuesto tab's own
  payment editor and deliberately never sends these three ONVO fields
  (item 50) — the two routes must never merge, or a save from either tab
  could silently clobber the other's fields.
- `POST /<pid>/pago/<payment_id>/banco-expense` — "Registrar comisión como
  gasto Banco" (item 49). Never automatic: inserts exactly one
  `project_expenses` row (`category='banco'`, `amount_usd = comisión + IVA
  sobre comisión`, `iva_rate=0`, `notes` containing the marker
  `onvo:{payment_id}`), and refuses — with a visible message, never an
  exception — if a `banco` expense carrying that marker already exists for
  this payment, so double-clicking can never double-count a bank charge that
  was, in reality, charged once.

Both routes re-render the whole Pagos panel from a fresh `detail_ctx()` call
after the write (plan §1.6), so the footer and the row itself can never drift
from what was just saved — same discipline as `projects_budget.py`.

⚠ **This tab never touches `utilidad_bruta`/`iva_a_pagar`/`utilidad_neta`**
(item 48, the single most important assertion on this screen): no route
here calls `summarize()` with anything other than the untouched
`bundle["payments"]`, and `onvo_breakdown()`/`payments_summary()` are never
fed into any profit figure. The footer's `Total pagado…`/`Comisión
total`/`IVA sobre comisión total`/`Total por depositar` come from
`payments_summary()` over paid payments; the `Recibido … / Pendiente …`
line reuses `detail_ctx()`'s own `recibido_line` string verbatim (already
computed once, from `summarize()`, and merged into every tab's context) so
this tab's Recibido figure can never disagree with the Presupuesto tab's
(plan §1.3 rule 7, item 47).
"""
from flask import render_template, request

from webapp.blueprints.projects_common import detail_ctx, fmt_usd


def _parse_pct(raw) -> float:
    """A posted commission/IVA percent field (e.g. `"2.4"` meaning 2.4%) ->
    a rate (`0.024`). Blank/unparseable/negative -> `0.0` — a payment with a
    bad rate reads as a bank transfer, never as a guess (§1.10.3's rule,
    applied to hand input as well as to the DB default)."""
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return pct / 100 if pct > 0 else 0.0


def _pct_input(rate) -> str:
    """A persisted rate (`0.024`) -> the percent string an editable `<input
    type="number">` should show (`"2.4"`), trimmed of a trailing `.0`."""
    pct = round(float(rate or 0) * 100, 4)
    text = f"{pct:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _has_banco_expense(expenses: list[dict], payment_id) -> bool:
    """§1.10.3/item 49's guard: has "Registrar comisión como gasto Banco"
    already run for this payment? Checked by the `onvo:{payment_id}` marker
    in a `category='banco'` expense's `notes` — never inferred from amount,
    so a manually entered, unrelated Banco row can never be mistaken for
    this one."""
    marker = f"onvo:{payment_id}"
    return any(
        e.get("category") == "banco" and marker in (e.get("notes") or "")
        for e in expenses
    )


def render_panel(ctx: dict, *, error: str | None = None, banco_message: str | None = None) -> str:
    """Renders `projects/_pagos.html` — the one place a `detail_ctx()`
    result becomes a Pagos fragment, shared by `projects.py`'s GET tab
    dispatch and both write routes below (plan §1.3)."""
    from calculations.project_finance import onvo_breakdown, payments_summary
    from config import DEFAULT_ONVO_COMMISSION
    from webapp.blueprints.projects_common import ONVO_IVA_PCT

    project = ctx["project"]
    payments = ctx["bundle"]["payments"]
    expenses = ctx["bundle"]["expenses"]

    payment_rows = []
    for p in payments:
        amount = float(p.get("amount_usd") or 0)
        commission_pct = float(p.get("onvo_commission_pct") or 0)
        iva_pct = float(p.get("onvo_iva_pct") or 0)
        # ⚠ item 46: always freshly computed from the persisted rates —
        # never from the persisted `net_deposited` column.
        breakdown = onvo_breakdown(amount, commission_pct, iva_pct)
        fee_total = round(breakdown["commission"] + breakdown["iva_on_commission"], 2)
        payment_rows.append({
            "id": p.get("id"),
            "payment_number": p.get("payment_number"),
            "amount_str": fmt_usd(amount),
            "is_transferencia": commission_pct == 0 and iva_pct == 0,
            "commission_pct_input": _pct_input(commission_pct),
            "iva_pct_input": _pct_input(iva_pct),
            "commission_str": fmt_usd(breakdown["commission"]),
            "iva_str": fmt_usd(breakdown["iva_on_commission"]),
            "net_str": fmt_usd(breakdown["net_deposited"]),
            "paid": bool(p.get("paid")),
            "paid_date": p.get("paid_date") or "",
            "bank_account": p.get("bank_account") or "",
            "notes": p.get("notes") or "",
            "banco_registered": _has_banco_expense(expenses, p.get("id")),
            "banco_fee_total": fee_total,
        })

    summary = payments_summary(payments)

    return render_template(
        "projects/_pagos.html",
        pid=project["id"],
        client_name=ctx["client_name"],
        contract_str=ctx["contract_str"],
        payment_rows=payment_rows,
        default_commission_pct=_pct_input(DEFAULT_ONVO_COMMISSION),
        default_iva_pct=_pct_input(ONVO_IVA_PCT),
        summary_gross_str=fmt_usd(summary["gross_paid"]),
        summary_commission_str=fmt_usd(summary["commission_total"]),
        summary_iva_str=fmt_usd(summary["iva_on_commission_total"]),
        summary_net_str=fmt_usd(summary["net_deposited_total"]),
        recibido_line=ctx["recibido_line"],
        error=error,
        banco_message=banco_message,
    )


def _fresh_panel_or_error(pid: str, *, error=None, banco_message=None):
    try:
        ctx = detail_ctx(pid, active_tab="pagos")
    except Exception as exc:
        return render_template("admin/_error.html", message=f"Error cargando proyecto: {exc}")
    if ctx is None:
        return render_template("admin/_error.html", message="Proyecto no encontrado.")
    return render_panel(ctx, error=error, banco_message=banco_message)


def register(bp):
    @bp.route("/<pid>/pago/<payment_id>/onvo", methods=["POST"])
    def pago_onvo_guardar(pid, payment_id):
        from calculations.project_finance import onvo_breakdown
        from database.projects_db import update_payment

        form = request.form
        commission_pct = _parse_pct(form.get("commission_pct"))
        iva_pct = _parse_pct(form.get("iva_pct"))
        paid = form.get("paid") == "on"
        paid_date = (form.get("paid_date") or "").strip() or None
        bank_account = (form.get("bank_account") or "").strip() or None
        notes = (form.get("notes") or "").strip() or None

        error = None
        try:
            ctx = detail_ctx(pid, active_tab="pagos")
        except Exception as exc:
            return render_template("admin/_error.html", message=f"Error cargando proyecto: {exc}")
        if ctx is None:
            return render_template("admin/_error.html", message="Proyecto no encontrado.")

        payment = next((p for p in ctx["bundle"]["payments"] if str(p.get("id")) == str(payment_id)), None)
        if payment is None:
            error = "Pago no encontrado."
        else:
            # The gross amount always comes from the persisted row, never
            # from the posted form — this tab's block never makes
            # `amount_usd` an editable field (item 44's "Monto bruto" is
            # display-only here, same as the Presupuesto tab's own payment
            # editor).
            amount = float(payment.get("amount_usd") or 0)
            breakdown = onvo_breakdown(amount, commission_pct, iva_pct)
            try:
                # ⚠ item 50, the other half of it: THIS is the one route
                # allowed to write these three fields. projects_budget.py's
                # pago_guardar() must never gain them.
                update_payment(
                    payment_id,
                    onvo_commission_pct=commission_pct,
                    onvo_iva_pct=iva_pct,
                    net_deposited=breakdown["net_deposited"],
                    paid=paid, paid_date=paid_date, bank_account=bank_account, notes=notes,
                )
            except Exception as exc:
                error = f"Error al guardar el pago: {exc}"

        return _fresh_panel_or_error(pid, error=error)

    @bp.route("/<pid>/pago/<payment_id>/banco-expense", methods=["POST"])
    def pago_banco_expense(pid, payment_id):
        from calculations.project_finance import onvo_breakdown
        from database.projects_db import add_expense

        try:
            ctx = detail_ctx(pid, active_tab="pagos")
        except Exception as exc:
            return render_template("admin/_error.html", message=f"Error cargando proyecto: {exc}")
        if ctx is None:
            return render_template("admin/_error.html", message="Proyecto no encontrado.")

        payment = next((p for p in ctx["bundle"]["payments"] if str(p.get("id")) == str(payment_id)), None)
        banco_message = None
        if payment is None:
            banco_message = "Pago no encontrado."
        elif _has_banco_expense(ctx["bundle"]["expenses"], payment_id):
            # ⚠ item 49: refused with a visible message, never an
            # exception, and never a second row.
            banco_message = "Ya existe un gasto de Banco registrado para este pago."
        else:
            amount = float(payment.get("amount_usd") or 0)
            commission_pct = float(payment.get("onvo_commission_pct") or 0)
            iva_pct = float(payment.get("onvo_iva_pct") or 0)
            breakdown = onvo_breakdown(amount, commission_pct, iva_pct)
            fee_total = round(breakdown["commission"] + breakdown["iva_on_commission"], 2)
            if fee_total <= 0:
                banco_message = "Este pago no tiene comisión ONVO que registrar."
            else:
                try:
                    add_expense(
                        pid, "banco",
                        f"Comisión ONVO — Pago {payment.get('payment_number')}",
                        fee_total, iva_rate=0,
                        notes=f"onvo:{payment_id}",
                    )
                except Exception as exc:
                    banco_message = f"Error al registrar el gasto: {exc}"

        return _fresh_panel_or_error(pid, banco_message=banco_message)
