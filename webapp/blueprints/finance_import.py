"""Importar QuickBooks (fase 25.2) — /finanzas/importar.

Upload the Journal export → the app suggests how to classify every movement →
Oscar reviews (doubtful ones first) → Guardar writes completed historical
projects, their payments and expenses, and the company expenses / owner
draws. Every import can be undone as a whole.
"""
from __future__ import annotations

from collections import defaultdict

from flask import Blueprint, redirect, render_template, request, url_for

bp = Blueprint("finance_import", __name__, url_prefix="/finanzas/importar")

KINDS = [
    ("client_payment", "Pago de cliente"),
    ("project_expense", "Gasto de proyecto"),
    ("company_expense", "Gasto de empresa"),
    ("owner_draw", "Retiro del dueño"),
    ("other_income", "Otro ingreso"),
    ("skip", "No importar"),
]
JOB_ACTIONS = [
    ("project", "Proyecto completado"),
    ("income", "Otro ingreso (sin proyecto)"),
    ("existing", "Ya está en la app"),
    ("skip", "No importar"),
]
VIEWS = [
    ("revisar", "Por revisar"),
    ("sin_proyecto", "Costos sin proyecto"),
    ("retiros", "Retiros"),
    ("oscar", "Pagos a Oscar Pauly"),
    ("empresa", "Gastos de empresa"),
    ("banco", "Agregados del banco"),
    ("pagos", "Pagos de clientes"),
    ("todos", "Todos"),
]
PAGE = 100


def fmt_usd(v) -> str:
    v = float(v or 0)
    return f"{'-' if v < 0 else ''}${abs(v):,.2f}"


def _filter(items: list[dict], view: str, q: str) -> list[dict]:
    def keep(i):
        if view == "revisar":
            ok = i["confidence"] != "alta" and not i["reviewed"]
        elif view == "sin_proyecto":
            ok = i["kind"] == "project_expense" and not i.get("job_key")
        elif view == "retiros":
            ok = i["kind"] == "owner_draw"
        elif view == "oscar":
            ok = (i.get("payee") or "").strip().lower() == "oscar pauly"
        elif view == "empresa":
            ok = i["kind"] == "company_expense"
        elif view == "banco":
            ok = i["qb_type"] == "Banco"
        elif view == "pagos":
            ok = i["qb_type"] == "Payment"
        else:
            ok = True
        if ok and q:
            ok = q.lower() in f"{i.get('memo') or ''} {i.get('payee') or ''} {i['amount_usd']}".lower()
        return ok
    return [i for i in items if keep(i)]


def _review_ctx(batch: dict) -> dict:
    from calculations.qb_import import reconcile
    from database.finance_db import list_categories
    from database.qb_import_db import list_items, list_jobs
    from webapp.blueprints.projects_common import RUBRO_LABELS

    jobs = list_jobs(batch["id"])
    items = list_items(batch["id"])
    job_by = {j["job_key"]: j for j in jobs}

    paid = defaultdict(float)
    spent = defaultdict(float)
    for i in items:
        if i.get("job_key") and i["kind"] == "client_payment":
            paid[i["job_key"]] += float(i["amount_usd"])
        if i.get("job_key") and i["kind"] == "project_expense":
            spent[i["job_key"]] += float(i["amount_usd"])

    view = request.args.get("vista", "revisar")
    if view not in dict(VIEWS) and view != "trabajos":
        view = "revisar"
    q = (request.args.get("q") or "").strip()
    page = max(int(request.args.get("p", 1) or 1), 1)

    counts = {k: len(_filter(items, k, "")) for k, _ in VIEWS}
    shown = _filter(items, view, q) if view != "trabajos" else []
    total_shown = len(shown)
    shown = shown[(page - 1) * PAGE: page * PAGE]

    rec = reconcile([{**i, "amount_usd": float(i["amount_usd"])} for i in items], batch.get("summary") or {})
    by_kind = defaultdict(float)
    for i in items:
        by_kind[i["kind"]] += float(i["amount_usd"])

    job_options = sorted(
        [{"key": j["job_key"], "label": f"{j['customer']} · {j.get('title') or ''} ({j['invoice_date'][:7]})",
          "action": j["action"]} for j in jobs if j["action"] != "skip"],
        key=lambda o: o["label"].lower())
    cats = list_categories(active_only=False)
    return {
        "batch": batch, "view": view, "views": VIEWS, "counts": counts, "q": q,
        "page": page, "pages": max((total_shown + PAGE - 1) // PAGE, 1), "total_shown": total_shown,
        "items": [{**i, "job_label": (lambda j: f"{j['customer']} · {j.get('title') or ''}" if j else "")(
                       job_by.get(i.get("job_key"))), "amount_str": fmt_usd(i["amount_usd"])} for i in shown],
        "jobs": [{**j, "paid_str": fmt_usd(paid[j["job_key"]]), "spent_str": fmt_usd(spent[j["job_key"]]),
                  "total_str": fmt_usd(j["total_usd"]),
                  "margin_str": fmt_usd(paid[j["job_key"]] - spent[j["job_key"]])} for j in jobs],
        "job_options": job_options, "kinds": KINDS, "job_actions": JOB_ACTIONS,
        "rubros": list(RUBRO_LABELS.items()),
        "cats_by_kind": {k: [c for c in cats if c["kind"] == k] for k in ("company_expense", "owner_draw", "other_income")},
        "rec": {k: (fmt_usd(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and k != "bank_count" else v)
                for k, v in rec.items()},
        "by_kind": {k: fmt_usd(v) for k, v in by_kind.items()},
        "n_projects": sum(1 for j in jobs if j["action"] == "project"),
        "n_items": len(items),
        "error": request.args.get("error"),
    }


@bp.route("/", methods=["GET"])
def index():
    from database.qb_import_db import draft_batch, list_batches

    try:
        batch = draft_batch()
    except Exception as exc:
        return render_template("finance/importar.html", load_error=str(exc), batch=None)
    if batch:
        return render_template("finance/importar.html", **_review_ctx(batch))
    return render_template("finance/importar.html", batch=None, batches=list_batches(),
                           error=request.args.get("error"), done=request.args.get("hecho"))


@bp.route("/", methods=["POST"])
def subir():
    import openpyxl

    from calculations.qb_import import parse_journal, propose
    from database.finance_db import list_categories
    from database.qb_import_db import create_batch, draft_batch
    from database.supabase_client import get_client

    f = request.files.get("archivo")
    if not f or not f.filename:
        return redirect(url_for("finance_import.index", error="Elija el archivo Journal.xlsx."))
    if draft_batch():
        return redirect(url_for("finance_import.index"))
    try:
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        txs = parse_journal(wb.worksheets[0].iter_rows(values_only=True))
        db = get_client()
        proposal = propose(txs, list_categories(active_only=False),
                           db.table("projects").select("*").neq("source", "quickbooks").execute().data,
                           db.table("project_payments").select("*").execute().data)
        create_batch(f.filename, proposal)
    except Exception as exc:
        return redirect(url_for("finance_import.index", error=f"No se pudo leer el archivo: {exc}"))
    return redirect(url_for("finance_import.index"))


@bp.route("/item/<item_id>", methods=["POST"])
def item(item_id):
    """htmx: save one row's classification and return the row."""
    from database.qb_import_db import update_item

    f = request.form
    kind = f.get("kind")
    fields = {"reviewed": True}
    if kind in dict(KINDS):
        fields["kind"] = kind
    if "job_key" in f:
        fields["job_key"] = f.get("job_key") or None
    if "rubro" in f:
        fields["rubro"] = f.get("rubro") or None
    if "category_id" in f:
        fields["category_id"] = f.get("category_id") or None
    if kind not in ("client_payment", "project_expense"):
        fields["job_key"] = None
    row = update_item(item_id, **fields)
    return _row_html(row)


def _row_html(row: dict) -> str:
    from database.finance_db import list_categories
    from database.qb_import_db import list_jobs
    from webapp.blueprints.projects_common import RUBRO_LABELS

    jobs = list_jobs(row["batch_id"])
    job_by = {j["job_key"]: j for j in jobs}
    j = job_by.get(row.get("job_key"))
    cats = list_categories(active_only=False)
    return render_template(
        "finance/_import_row.html",
        i={**row, "amount_str": fmt_usd(row["amount_usd"]),
           "job_label": f"{j['customer']} · {j.get('title') or ''}" if j else ""},
        kinds=KINDS, rubros=list(RUBRO_LABELS.items()),
        job_options=sorted([{"key": x["job_key"], "label": f"{x['customer']} · {x.get('title') or ''} ({x['invoice_date'][:7]})"}
                            for x in jobs if x["action"] != "skip"], key=lambda o: o["label"].lower()),
        cats_by_kind={k: [c for c in cats if c["kind"] == k] for k in ("company_expense", "owner_draw", "other_income")},
    )


@bp.route("/item/<item_id>/dividir", methods=["POST"])
def dividir(item_id):
    from database.qb_import_db import split_item

    try:
        split_item(item_id, float(str(request.form.get("monto", "")).replace(",", "")))
        err = None
    except Exception as exc:
        err = str(exc)
    args = {k: v for k, v in request.args.items()}
    if err:
        args["error"] = err
    return redirect(url_for("finance_import.index", **args))


@bp.route("/revisados", methods=["POST"])
def revisados():
    from database.qb_import_db import mark_reviewed

    ids = [x for x in request.form.getlist("ids") if x]
    mark_reviewed(ids)
    return redirect(url_for("finance_import.index", **request.args))


@bp.route("/trabajo/<job_id>", methods=["POST"])
def trabajo(job_id):
    from database.qb_import_db import update_job

    fields = {}
    if request.form.get("action") in dict(JOB_ACTIONS):
        fields["action"] = request.form["action"]
    if "title" in request.form:
        fields["title"] = (request.form.get("title") or "").strip() or None
    if fields:
        update_job(job_id, **fields)
    return ("", 204)


@bp.route("/guardar", methods=["POST"])
def guardar():
    from database.qb_import_db import commit_batch, draft_batch

    batch = draft_batch()
    if not batch:
        return redirect(url_for("finance_import.index"))
    try:
        res = commit_batch(batch["id"])
    except Exception as exc:
        return redirect(url_for("finance_import.index", vista="trabajos", error=str(exc)))
    return redirect(url_for("finance_import.index",
                            hecho=f"{res['projects']} proyectos, {res['payments']} pagos, "
                                  f"{res['expenses']} gastos de proyecto y {res['other']} movimientos de empresa."))


@bp.route("/descartar", methods=["POST"])
def descartar():
    from database.qb_import_db import discard_batch, draft_batch

    batch = draft_batch()
    if batch:
        discard_batch(batch["id"])
    return redirect(url_for("finance_import.index"))


@bp.route("/<batch_id>/deshacer", methods=["POST"])
def deshacer(batch_id):
    from database.qb_import_db import undo_batch

    undo_batch(batch_id)
    return redirect(url_for("finance_import.index", hecho="Importación deshecha."))
