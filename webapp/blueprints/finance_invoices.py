"""Invoices sueltos — /finanzas/invoices (migration 074).

Charges to a client without a project in the app: detail lines, USD or CRC,
partial payments, closes itself at saldo 0, and can be linked to a project
later (its money then moves into the project's payments). Routes live on the
Finanzas blueprint so the nav stays on Finanzas.
"""
from __future__ import annotations

from datetime import date

from flask import redirect, render_template, request, url_for

from calculations.invoices import IVA_RATES, STATUS_LABELS, fmt
from webapp.blueprints.finance import _parse_float, _project_options, bp, fmt_usd

FILTERS = [("abiertos", "Pendientes"), ("pagados", "Pagados"), ("todos", "Todos")]


def _today() -> str:
    from utils.fx_history import today_cr

    return today_cr().isoformat()


@bp.route("/invoices")
def invoices():
    from database.invoices_db import list_invoices

    estado = request.args.get("estado", "abiertos")
    try:
        rows = list_invoices()
    except Exception as exc:
        return render_template("finance/invoices.html", load_error=str(exc))
    keep = {"abiertos": ("open",), "pagados": ("paid", "linked")}.get(estado)
    shown = [r for r in rows if not keep or r["status"] in keep]
    today = _today()
    por_cobrar = {"USD": 0.0, "CRC": 0.0}
    for r in rows:
        if r["status"] == "open":
            por_cobrar[r["currency"]] += r["saldo"]
    return render_template(
        "finance/invoices.html", estado=estado, filters=FILTERS,
        rows=[{**r, "total_str": fmt(r["total"], r["currency"]), "paid_str": fmt(r["paid"], r["currency"]),
               "saldo_str": fmt(r["saldo"], r["currency"]), "status_label": STATUS_LABELS[r["status"]],
               "overdue": r["status"] == "open" and r.get("due_date") and r["due_date"] < today} for r in shown],
        por_cobrar={k: fmt(v, k) for k, v in por_cobrar.items() if v},
        n_open=sum(1 for r in rows if r["status"] == "open"),
        ok=request.args.get("ok"),
    )


def _form_page(values: dict, lines: list[dict], error: str | None = None, invoice_id: str | None = None):
    from database.invoices_db import client_names

    return render_template("finance/invoice_form.html", v=values, lines=lines or [{}], error=error,
                           invoice_id=invoice_id, clients=client_names(), iva_rates=IVA_RATES)


def _read_form(form) -> tuple[dict, list[dict]]:
    values = {k: (form.get(k) or "").strip() for k in
              ("client_name", "issue_date", "due_date", "currency", "iva_rate", "notes")}
    if values["currency"] not in ("USD", "CRC"):
        values["currency"] = "USD"
    lines = [{"description": d, "quantity": q, "unit_price": (p or "").replace(",", "")}
             for d, q, p in zip(form.getlist("line_desc"), form.getlist("line_qty"), form.getlist("line_price"))]
    return values, lines


@bp.route("/invoices/nuevo", methods=["GET", "POST"])
def invoice_nuevo():
    from database.invoices_db import save_invoice

    if request.method == "GET":
        return _form_page({"issue_date": _today(), "currency": "USD", "iva_rate": "13",
                           "client_name": request.args.get("cliente", "")}, [])
    values, lines = _read_form(request.form)
    try:
        inv = save_invoice(values, lines)
    except Exception as exc:
        return _form_page(values, lines, str(exc))
    return redirect(url_for("finance.invoice_detalle", invoice_id=inv["id"], ok="creado"), code=303)


@bp.route("/invoices/<invoice_id>/editar", methods=["GET", "POST"])
def invoice_editar(invoice_id):
    from database.invoices_db import get_invoice, save_invoice

    inv = get_invoice(invoice_id)
    if not inv:
        return redirect(url_for("finance.invoices"))
    if request.method == "GET":
        values = {k: ("" if inv.get(k) is None else str(inv[k])) for k in
                  ("client_name", "issue_date", "due_date", "currency", "notes")}
        values["iva_rate"] = f"{float(inv['iva_rate']):g}"
        lines = [{"description": l["description"], "quantity": f"{float(l['quantity']):g}",
                  "unit_price": f"{float(l['unit_price']):.2f}"} for l in inv["lines"]]
        return _form_page(values, lines, invoice_id=invoice_id)
    values, lines = _read_form(request.form)
    try:
        save_invoice(values, lines, invoice_id)
    except Exception as exc:
        return _form_page(values, lines, str(exc), invoice_id)
    return redirect(url_for("finance.invoice_detalle", invoice_id=invoice_id, ok="guardado"), code=303)


@bp.route("/invoices/<invoice_id>")
def invoice_detalle(invoice_id):
    from database.finance_db import list_accounts, load_all
    from database.invoices_db import get_invoice

    inv = get_invoice(invoice_id)
    if not inv:
        return redirect(url_for("finance.invoices"))
    cur = inv["currency"]
    accounts = list_accounts()
    acc_name = {a["id"]: a["name"] for a in list_accounts(active_only=False)}
    # Default account: one in the invoice's currency (the default USD one for USD).
    default_acc = next((a["id"] for a in accounts if a["currency"] == cur and (a.get("is_default") or cur == "CRC")),
                       next((a["id"] for a in accounts if a.get("is_default")), ""))
    projects = load_all()["projects"] if inv["status"] in ("open", "paid") else {}
    options = _project_options(projects)
    same = [o for o in options if o["label"].lower().startswith(inv["client_name"].lower())]
    project = None
    if inv.get("project_id"):
        from database.projects_db import get_project

        project = get_project(inv["project_id"])
    return render_template(
        "finance/invoice_detalle.html", inv=inv, cur=cur,
        status_label=STATUS_LABELS[inv["status"]],
        lines=[{**l, "price_str": fmt(l["unit_price"], cur),
                "amount_str": fmt(float(l["quantity"]) * float(l["unit_price"]), cur),
                "qty_str": f"{float(l['quantity']):g}"} for l in inv["lines"]],
        payments=[{**p, "amount_str": fmt(p["amount"], cur), "usd_str": fmt_usd(float(p["amount_usd"])),
                   "account_name": acc_name.get(p["account_id"], "—")} for p in inv["payments"]],
        t={"subtotal": fmt(inv["subtotal"], cur), "iva": fmt(inv["iva"], cur), "total": fmt(inv["total"], cur),
           "paid": fmt(inv["paid"], cur), "saldo": fmt(inv["saldo"], cur)},
        accounts=accounts, default_acc=default_acc, today=_today(),
        default_amount=f"{inv['saldo']:.2f}" if inv["saldo"] > 0 else "",
        same_client=same, other_projects=[o for o in options if o not in same],
        project=project, ok=request.args.get("ok"), error=request.args.get("error"),
    )


def _back(invoice_id, **kw):
    return redirect(url_for("finance.invoice_detalle", invoice_id=invoice_id, **kw), code=303)


@bp.route("/invoices/<invoice_id>/pago", methods=["POST"])
def invoice_pago(invoice_id):
    from database.invoices_db import add_payment

    f = request.form
    amount = _parse_float(f.get("amount"))
    if amount is None:
        return _back(invoice_id, error="Escriba el monto recibido.")
    try:
        add_payment(invoice_id, f.get("paid_date") or _today(), amount, f.get("account_id"), f.get("notes"))
    except Exception as exc:
        return _back(invoice_id, error=str(exc))
    return _back(invoice_id, ok="pago")


@bp.route("/invoices/pago/<payment_id>/eliminar", methods=["POST"])
def invoice_pago_eliminar(payment_id):
    from database.invoices_db import delete_payment

    inv_id = request.form.get("invoice_id")
    try:
        inv_id = delete_payment(payment_id) or inv_id
    except Exception as exc:
        return _back(inv_id, error=str(exc))
    return _back(inv_id, ok="pago_borrado")


@bp.route("/invoices/<invoice_id>/ligar", methods=["POST"])
def invoice_ligar(invoice_id):
    from database.invoices_db import link_to_project

    pid = request.form.get("project_id")
    if not pid:
        return _back(invoice_id, error="Elija el proyecto.")
    try:
        link_to_project(invoice_id, pid)
    except Exception as exc:
        return _back(invoice_id, error=str(exc))
    return _back(invoice_id, ok="ligado")


@bp.route("/invoices/<invoice_id>/anular", methods=["POST"])
def invoice_anular(invoice_id):
    from database.invoices_db import set_void

    try:
        set_void(invoice_id, request.form.get("void") == "1")
    except Exception as exc:
        return _back(invoice_id, error=str(exc))
    return _back(invoice_id, ok="estado")


@bp.route("/invoices/<invoice_id>/eliminar", methods=["POST"])
def invoice_eliminar(invoice_id):
    from database.invoices_db import delete_invoice

    try:
        delete_invoice(invoice_id)
    except Exception as exc:
        return _back(invoice_id, error=str(exc))
    return redirect(url_for("finance.invoices", ok="borrado"), code=303)
