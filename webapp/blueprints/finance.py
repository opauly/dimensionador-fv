"""Finanzas page (PLAN_PHASE25_FINANZAS.md, fase 25.1).

One page: account balances, period summary, a "Registrar movimiento" form and
the filterable list of every money movement (project + company).

Project money is still written where it always lived: a "Gasto de proyecto"
entered here becomes a paid `project_expenses` row (so the project's own
Presupuesto/ledger tabs see it), and a "Pago de cliente" marks a row of the
project's payment schedule paid (or adds an extra one) in `project_payments`.
Everything else goes to `fin_transactions`.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, redirect, render_template, request, url_for

from calculations.finance import (
    KIND_LABELS, account_balances, build_movements, filter_movements, month_bounds, to_usd, totals,
)

bp = Blueprint("finance", __name__, url_prefix="/finanzas")

# Kinds the form can create.
FORM_KINDS = [
    ("company_expense", "Gasto de empresa"),
    ("project_expense", "Gasto de proyecto"),
    ("client_payment", "Pago de cliente"),
    ("owner_draw", "Retiro del dueño"),
    ("other_income", "Otro ingreso"),
    ("transfer", "Transferencia entre cuentas"),
]


def fmt_usd(amount) -> str:
    if amount is None:
        return "—"
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def _fmt_native(amount, currency: str) -> str:
    if amount is None:
        return "—"
    if currency == "CRC":
        sign = "-" if amount < 0 else ""
        return f"{sign}₡{abs(amount):,.0f}"
    return fmt_usd(amount)


def _parse_float(raw) -> float | None:
    try:
        v = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return v


def _project_options(projects: dict) -> list[dict]:
    order = {"active": 0, "paused": 1, "completed": 2, "cancelled": 3}
    rows = sorted(projects.values(), key=lambda p: (order.get(p.get("status"), 9), p.get("client_name") or ""))
    return [{"id": p["id"], "status": p.get("status"),
             "label": (p.get("client_name") or "—") + (f" · {p['title']}" if p.get("title") else "")}
            for p in rows]


def _form_ctx(values: dict, accounts: list[dict], categories: list[dict], projects: dict,
              error: str | None = None) -> dict:
    from webapp.blueprints.projects_common import LEDGER_TAB_CATEGORIES, RUBRO_LABELS

    kind = values.get("kind") or "company_expense"
    acc = {a["id"]: a for a in accounts}
    account = acc.get(values.get("account_id")) or (accounts[0] if accounts else {})
    to_account = acc.get(values.get("to_account_id"))
    needs_fx = account.get("currency") == "CRC" or (kind == "transfer" and to_account
                                                       and to_account.get("currency") != account.get("currency"))
    fx_note = ""
    if needs_fx and not values.get("fx_rate"):
        try:
            from utils.fx_history import get_rate

            rate, estimated = get_rate(values.get("tx_date") or date.today().isoformat())
            values["fx_rate"] = f"{rate:.2f}"
            fx_note = "estimado (no hay dato de ese día)" if estimated else "BCCR venta"
        except Exception:
            fx_note = "no se pudo obtener; escríbalo"
    pending_payments = []
    if kind == "client_payment" and values.get("project_id"):
        from database.projects_db import list_payments

        pending_payments = [
            {"id": p["id"], "label": f"Pago {p['payment_number']} — {fmt_usd(float(p['amount_usd'] or 0))}",
             "amount": float(p["amount_usd"] or 0)}
            for p in list_payments(values["project_id"]) if not p.get("paid")
        ]
        ids = [p["id"] for p in pending_payments]
        if values.get("payment_id") not in ids + ["new"]:
            values["payment_id"] = ids[0] if ids else "new"
            values["amount"] = ""
        chosen = next((p for p in pending_payments if p["id"] == values["payment_id"]), None)
        if chosen and not values.get("amount") and account.get("currency") != "CRC":
            values["amount"] = f"{chosen['amount']:.2f}"
    try:
        from database.finance_db import list_vendors

        vendors = list_vendors()
    except Exception:
        vendors = []  # migration 073 not run yet
    return {
        "v": values, "kind": kind, "form_kinds": FORM_KINDS, "vendors": vendors,
        "pending_payments": pending_payments,
        "accounts": [a for a in accounts if a.get("active")],
        "account_currency": account.get("currency") or "USD",
        "to_currency": (to_account or {}).get("currency") or "",
        "categories": [c for c in categories if c["kind"] == kind and c.get("active")],
        "projects": _project_options(projects),
        "rubros": [(c, RUBRO_LABELS[c]) for c in LEDGER_TAB_CATEGORIES],
        "needs_fx": needs_fx, "fx_note": fx_note, "error": error,
    }


def _page_ctx(form_values: dict | None = None, form_error: str | None = None) -> dict:
    from database.finance_db import generate_recurring, load_all

    try:
        recurring_created = generate_recurring()
    except Exception:
        recurring_created = 0  # e.g. migration 072 not run yet; never block the page

    data = load_all()
    accounts = data["accounts"]
    categories = {c["id"]: c for c in data["categories"]}
    movements = build_movements(accounts, data["fin_txs"], data["payments"], data["expenses"],
                                data["labor"], data["projects"], categories,
                                data.get("invoice_payments"))

    first, last = month_bounds(date.today())
    args = request.args
    desde = args.get("desde", first)
    hasta = args.get("hasta", last)
    f_kind = args.get("tipo", "")
    f_acc = args.get("cuenta", "")
    f_proj = args.get("proyecto", "")
    shown = filter_movements(movements, desde=desde, hasta=hasta, kind=f_kind,
                             account_id=f_acc, project_id=f_proj)

    try:
        from utils.fx_history import get_rate

        today_rate, _ = get_rate(date.today())
    except Exception:
        today_rate = None
    balances = account_balances([a for a in accounts if a.get("active")], movements, today_rate)
    total_usd = sum(b["balance_usd"] for b in balances if b["balance_usd"] is not None)

    acc_cur = {a["id"]: a["currency"] for a in accounts}
    rows = []
    for m in shown:
        if m["kind"] == "transfer":
            amount_str = f"{_fmt_native(m['amount'], m['currency'])} → {_fmt_native(m['to_amount'], acc_cur.get(m['to_account_id'], 'USD'))}" \
                if m.get("to_amount") is not None else _fmt_native(m["amount"], m["currency"])
            usd_str = fmt_usd(m["transfer_usd"])
        else:
            amount_str = _fmt_native(m["amount"] if m["amount_usd"] >= 0 else -m["amount"], m["currency"]) \
                if m["currency"] != "USD" else ""
            usd_str = fmt_usd(m["amount_usd"])
        rows.append({**m, "amount_str": amount_str, "usd_str": usd_str,
                     "positive": m["amount_usd"] > 0, "is_transfer": m["kind"] == "transfer"})

    t = totals(shown)
    summary = [
        ("Ingresos", t["income"], "pos"),
        ("Gastos de proyecto", t["project_expense"], "neg"),
        ("Gastos de empresa", t["company_expense"], "neg"),
        ("Utilidad de operación", t["operating_profit"], "pos" if t["operating_profit"] >= 0 else "neg"),
        ("Retiros del dueño", t["owner_draw"], "neg"),
        ("Queda en la empresa", t["net_after_draws"], "pos" if t["net_after_draws"] >= 0 else "neg"),
    ]

    form_values = form_values or {"kind": "company_expense", "tx_date": date.today().isoformat(),
                                  "account_id": next((a["id"] for a in accounts if a.get("is_default")), "")}
    return {
        "balances": [{**b, "balance_str": _fmt_native(b["balance"], b["currency"]),
                      "usd_str": fmt_usd(b["balance_usd"]) if b["balance_usd"] is not None else "—"}
                     for b in balances],
        "total_usd_str": fmt_usd(total_usd),
        "today_rate": today_rate,
        "summary": [(label, fmt_usd(v), cls) for label, v, cls in summary],
        "rows": rows,
        "filters": {"desde": desde, "hasta": hasta, "tipo": f_kind, "cuenta": f_acc, "proyecto": f_proj},
        "kind_labels": KIND_LABELS,
        "all_accounts": accounts,
        "project_options": _project_options(data["projects"]),
        "form": _form_ctx(form_values, accounts, data["categories"], data["projects"], form_error),
        "ok": request.args.get("ok"),
        "recurring_created": recurring_created,
    }


@bp.route("/")
def index():
    try:
        ctx = _page_ctx()
    except Exception as exc:
        return render_template("finance/index.html", load_error=str(exc))
    if request.headers.get("HX-Request") and request.args.get("parcial") == "lista":
        return render_template("finance/_movimientos.html", **ctx)
    return render_template("finance/index.html", **ctx)


@bp.route("/formulario")
def formulario():
    """Re-render the form when tipo / cuenta / fecha change (htmx)."""
    from database.finance_db import list_accounts, list_categories

    db_projects = {}
    try:
        from database.supabase_client import get_client

        rows = get_client().table("projects").select("id,client_name,title,status,source").execute().data
        db_projects = {p["id"]: p for p in rows}
    except Exception:
        pass
    values = request.args.to_dict()
    if request.args.get("refx"):
        values["fx_rate"] = ""
    ctx = _form_ctx(values, list_accounts(active_only=False), list_categories(active_only=False), db_projects)
    return render_template("finance/_form.html", form=ctx)


def _save(form) -> str | None:
    """Create the movement. Returns an error message, or None on success."""
    from database.finance_db import add_transaction, list_accounts

    kind = form.get("kind")
    if kind not in dict(FORM_KINDS):
        return "Tipo de movimiento no válido."
    tx_date = (form.get("tx_date") or "").strip()
    if not tx_date:
        return "Falta la fecha."
    description = (form.get("description") or "").strip()
    if not description and kind != "client_payment":
        return "Falta la descripción."
    amount = _parse_float(form.get("amount"))
    if not amount or amount <= 0:
        return "El monto debe ser mayor que cero."

    accounts = {a["id"]: a for a in list_accounts(active_only=False)}
    account = accounts.get(form.get("account_id"))
    if not account:
        return "Elija la cuenta."
    currency = account["currency"]
    fx_rate = _parse_float(form.get("fx_rate"))
    if currency == "CRC" and not fx_rate:
        return "Falta el tipo de cambio."
    amount_usd = to_usd(amount, currency, fx_rate)

    if fx_rate and currency == "CRC" and form.get("fx_rate_manual"):
        from utils.fx_history import save_manual_rate

        save_manual_rate(tx_date, fx_rate)

    vendor_name = (form.get("vendor") or "").strip()
    if vendor_name and kind != "client_payment":
        try:
            from database.finance_db import add_vendors

            add_vendors([vendor_name])
        except Exception:
            pass  # the list is a convenience; never block saving the movement

    if kind == "client_payment":
        return _save_client_payment(form, account, tx_date, amount, amount_usd, fx_rate, description)

    if kind == "project_expense":
        from database.projects_db import add_expense
        from webapp.blueprints.projects_common import LEDGER_TAB_CATEGORIES

        pid = form.get("project_id")
        rubro = form.get("rubro")
        if not pid:
            return "Elija el proyecto."
        if rubro not in LEDGER_TAB_CATEGORIES:
            return "Elija el rubro."
        extra = {"account_id": account["id"]}
        if currency != "USD":
            extra.update(currency=currency, amount_original=amount, fx_rate=fx_rate)
        notes = (form.get("notes") or "").strip()
        vendor = (form.get("vendor") or "").strip()
        if vendor:
            notes = f"{vendor} · {notes}" if notes else vendor
        add_expense(pid, rubro, description, amount_usd, paid=True, expense_date=tx_date,
                    notes=notes or None, **extra)
        return None

    payload = {
        "tx_date": tx_date, "kind": kind, "account_id": account["id"], "description": description,
        "vendor": (form.get("vendor") or "").strip(), "currency": currency, "amount": amount,
        "fx_rate": fx_rate if currency == "CRC" else None, "amount_usd": amount_usd,
        "notes": (form.get("notes") or "").strip(),
    }
    if kind == "transfer":
        to_acc = accounts.get(form.get("to_account_id"))
        if not to_acc or to_acc["id"] == account["id"]:
            return "Elija una cuenta destino distinta."
        to_amount = _parse_float(form.get("to_amount"))
        if not to_amount:
            if to_acc["currency"] == currency:
                to_amount = amount
            elif not fx_rate:
                return "Falta el tipo de cambio o el monto recibido."
            else:
                to_amount = round(amount * fx_rate, 2) if to_acc["currency"] == "CRC" else round(amount / fx_rate, 2)
        payload.update(to_account_id=to_acc["id"], to_amount=to_amount)
        if to_acc["currency"] == "CRC" and currency == "USD":
            payload["fx_rate"] = fx_rate or round(to_amount / amount, 4)
    else:
        cat = form.get("category_id")
        if not cat:
            return "Elija la categoría."
        payload["category_id"] = cat
    add_transaction(payload)
    return None


def _save_client_payment(form, account, tx_date, amount, amount_usd, fx_rate, description) -> str | None:
    """Mark a scheduled payment paid, or add an extra paid one (shared with
    the project's Presupuesto tab: `projects_db.receive_payment`)."""
    from database.projects_db import receive_payment

    pid = form.get("project_id")
    if not pid:
        return "Elija el proyecto."
    notes = [x for x in (description, (form.get("notes") or "").strip()) if x]
    if account["currency"] == "CRC":
        notes.append(f"Recibido ₡{amount:,.2f} a ₡{fx_rate:,.2f} por $")
    payment_id = form.get("payment_id") or "new"
    try:
        receive_payment(pid, None if payment_id == "new" else payment_id, amount_usd, tx_date, account,
                        " · ".join(notes) or None)
    except ValueError as exc:
        return str(exc)
    return None


@bp.route("/movimiento", methods=["POST"])
def movimiento():
    try:
        error = _save(request.form)
    except Exception as exc:
        error = f"No se pudo guardar: {exc}"
    if error:
        ctx = _page_ctx(form_values=request.form.to_dict(), form_error=error)
        return render_template("finance/index.html", **ctx), 422
    return redirect(url_for("finance.index", ok=1), code=303)


@bp.route("/movimiento/<tx_id>/eliminar", methods=["POST"])
def eliminar(tx_id):
    from database.finance_db import delete_transaction

    delete_transaction(tx_id)
    return redirect(url_for("finance.index", **{k: v for k, v in request.args.items() if k != "ok"}), code=303)


@bp.route("/cuentas", methods=["GET", "POST"])
def cuentas():
    from database.finance_db import list_accounts, update_account

    error = None
    if request.method == "POST":
        try:
            for a in list_accounts(active_only=False):
                name = (request.form.get(f"name-{a['id']}") or "").strip()
                if not name:
                    continue
                opening = _parse_float(request.form.get(f"opening-{a['id']}")) or 0
                opening_date = (request.form.get(f"date-{a['id']}") or "").strip() or None
                update_account(a["id"], name=name, opening_balance=opening, opening_date=opening_date)
            return redirect(url_for("finance.index", ok="cuentas"), code=303)
        except Exception as exc:
            error = f"No se pudo guardar: {exc}"
    return render_template("finance/cuentas.html", accounts=list_accounts(active_only=False), error=error)


# ── Gastos recurrentes ───────────────────────────────────────────────────
RECURRING_KINDS = [("company_expense", "Gasto de empresa"), ("owner_draw", "Retiro del dueño"),
                   ("other_income", "Otro ingreso")]


def _recurring_payload(form) -> tuple[dict | None, str | None]:
    from datetime import date as _date

    name = (form.get("name") or "").strip()
    memo_t = (form.get("memo_template") or "").strip() or (f"{name} [mes]" if name else "")
    amount = _parse_float(form.get("amount"))
    try:
        day = int(form.get("day_of_month") or 0)
    except ValueError:
        day = 0
    kind = form.get("kind") if form.get("kind") in dict(RECURRING_KINDS) else "company_expense"
    if not name:
        return None, "Falta el nombre."
    if not amount or amount <= 0:
        return None, "El monto debe ser mayor que cero."
    if not 1 <= day <= 31:
        return None, "El día del mes debe estar entre 1 y 31."
    if not form.get("account_id"):
        return None, "Elija la cuenta."
    return {
        "name": name, "kind": kind, "category_id": form.get("category_id") or None,
        "account_id": form.get("account_id"), "amount": amount, "day_of_month": day,
        "memo_template": memo_t, "vendor": (form.get("vendor") or "").strip() or None,
        "start_date": form.get("start_date") or _date.today().isoformat(),
        "end_date": form.get("end_date") or None, "active": form.get("active", "on") == "on",
    }, None


@bp.route("/recurrentes", methods=["GET", "POST"])
def recurrentes():
    from calculations.recurring import memo, next_date
    from database.finance_db import (
        generate_recurring, get_recurring, list_accounts, list_categories, list_recurring, save_recurring,
    )
    from utils.fx_history import today_cr

    error, edit_id = None, request.values.get("editar")
    form_values = {}
    if request.method == "POST":
        payload, error = _recurring_payload(request.form)
        if payload:
            if request.form.get("rule_id"):
                payload.pop("active", None)  # editing never un-pauses
            try:
                save_recurring(payload, request.form.get("rule_id") or None)
                n = generate_recurring()
                return redirect(url_for("finance.recurrentes", ok=n if n else "1"), code=303)
            except Exception as exc:
                error = f"No se pudo guardar: {exc}"
        form_values = request.form.to_dict()
        edit_id = request.form.get("rule_id") or None
    elif edit_id:
        form_values = get_recurring(edit_id) or {}

    today = today_cr()
    accounts = list_accounts(active_only=False)
    acc = {a["id"]: a for a in accounts}
    cats = list_categories(active_only=False)
    cat = {c["id"]: c["name"] for c in cats}
    rules = []
    for r in list_recurring():
        a = acc.get(r["account_id"]) or {}
        nd = next_date(r, today)
        rules.append({**r, "account_name": a.get("name", "—"), "category_name": cat.get(r.get("category_id"), "Otros"),
                      "amount_str": _fmt_native(float(r["amount"]), a.get("currency", "USD")),
                      "next_str": nd.strftime("%d/%m/%Y") if nd else "—",
                      "example": memo(r["memo_template"], nd or today)})
    return render_template(
        "finance/recurrentes.html", rules=rules, error=error, ok=request.args.get("ok"),
        v=form_values, edit_id=edit_id, kinds=RECURRING_KINDS, kind_labels=dict(RECURRING_KINDS),
        accounts=[a for a in accounts if a.get("active")],
        cats_by_kind={k: [c for c in cats if c["kind"] == k and c.get("active")] for k, _ in RECURRING_KINDS},
        default_account=next((a["id"] for a in accounts if a.get("is_default")), ""),
        today=today.isoformat(),
    )


@bp.route("/recurrentes/<rule_id>/pausar", methods=["POST"])
def recurrente_pausar(rule_id):
    from database.finance_db import get_recurring, save_recurring

    r = get_recurring(rule_id)
    if r:
        save_recurring({"active": not r.get("active")}, rule_id)
    return redirect(url_for("finance.recurrentes"), code=303)


@bp.route("/recurrentes/<rule_id>/eliminar", methods=["POST"])
def recurrente_eliminar(rule_id):
    from database.finance_db import delete_recurring

    delete_recurring(rule_id)
    return redirect(url_for("finance.recurrentes"), code=303)


# Invoices sueltos register their routes on this blueprint.
from webapp.blueprints import finance_invoices  # noqa: E402,F401
