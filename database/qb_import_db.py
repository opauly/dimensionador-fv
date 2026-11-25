"""QuickBooks import — staging, commit and undo (fase 25.2, migration 071).

Flow: `create_batch()` stores the suggestion from `calculations.qb_import`
as a draft; the review page edits jobs/items; `commit_batch()` writes the
real rows (completed projects + their payments and expenses, and
fin_transactions for everything outside projects); `undo_batch()` removes
everything that batch wrote.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from database.supabase_client import get_client

CHUNK = 400
# QuickBooks "suppliers" that were really categories (scripts/seed_fin_vendors.py skips them too).
GENERIC_PAYEES = {"ajustes", "comidas", "extras", "materiales", "otros", "transporte de equipo", "viáticos", "viaticos"}


def _insert(table: str, rows: list[dict]) -> list[dict]:
    out = []
    for i in range(0, len(rows), CHUNK):
        if rows[i:i + CHUNK]:
            out += get_client().table(table).insert(rows[i:i + CHUNK]).execute().data
    return out


def _all(query_fn) -> list[dict]:
    """Supabase returns at most 1000 rows per call: page through."""
    out, start = [], 0
    while True:
        rows = query_fn().range(start, start + 999).execute().data
        out += rows
        if len(rows) < 1000:
            return out
        start += 1000


# ── Batches ──────────────────────────────────────────────────────────────
def create_batch(filename: str, proposal: dict) -> str:
    db = get_client()
    batch = db.table("fin_import_batches").insert(
        {"filename": filename, "summary": proposal["totals"]}).execute().data[0]
    bid = batch["id"]
    _insert("fin_import_jobs", [{**j, "batch_id": bid} for j in proposal["jobs"]])
    _insert("fin_import_items", [{**i, "batch_id": bid} for i in proposal["items"]])
    return bid


def get_batch(batch_id: str) -> dict | None:
    rows = get_client().table("fin_import_batches").select("*").eq("id", batch_id).execute().data
    return rows[0] if rows else None


def draft_batch() -> dict | None:
    rows = (get_client().table("fin_import_batches").select("*").eq("status", "draft")
            .order("created_at", desc=True).limit(1).execute().data)
    return rows[0] if rows else None


def list_batches() -> list[dict]:
    return get_client().table("fin_import_batches").select("*").order("created_at", desc=True).execute().data


def discard_batch(batch_id: str) -> None:
    get_client().table("fin_import_batches").delete().eq("id", batch_id).eq("status", "draft").execute()


# ── Jobs / items ─────────────────────────────────────────────────────────
def list_jobs(batch_id: str) -> list[dict]:
    return _all(lambda: get_client().table("fin_import_jobs").select("*").eq("batch_id", batch_id)
                .order("invoice_date").order("customer").order("id"))


def list_items(batch_id: str) -> list[dict]:
    return _all(lambda: get_client().table("fin_import_items").select("*").eq("batch_id", batch_id)
                .order("tx_date").order("external_ref").order("id"))


def get_item(item_id: str) -> dict | None:
    rows = get_client().table("fin_import_items").select("*").eq("id", item_id).execute().data
    return rows[0] if rows else None


def update_job(job_id: str, **fields) -> dict:
    return get_client().table("fin_import_jobs").update(fields).eq("id", job_id).execute().data[0]


def update_item(item_id: str, **fields) -> dict:
    return get_client().table("fin_import_items").update(fields).eq("id", item_id).execute().data[0]


def mark_reviewed(item_ids: list[str]) -> None:
    for i in range(0, len(item_ids), 200):
        get_client().table("fin_import_items").update({"reviewed": True}).in_("id", item_ids[i:i + 200]).execute()


def split_item(item_id: str, amount: float) -> dict:
    """Move `amount` of an item into a new item (same date/memo) that can be
    classified on its own — e.g. one supplier invoice covering two projects."""
    item = get_item(item_id)
    if not item:
        raise ValueError("No existe ese movimiento.")
    total = round(float(item["amount_usd"]), 2)
    amount = round(float(amount), 2)
    if not 0 < amount < total:
        raise ValueError(f"El monto debe estar entre 0 y {total:,.2f}.")
    db = get_client()
    n = len(db.table("fin_import_items").select("id").eq("batch_id", item["batch_id"])
            .like("external_ref", item["external_ref"] + "%").execute().data)
    update_item(item_id, amount_usd=round(total - amount, 2))
    new = {k: v for k, v in item.items() if k not in ("id",)}
    new.update(external_ref=f"{item['external_ref']}:{n + 1}", amount_usd=amount, reviewed=False,
               reason="Parte dividida de un movimiento")
    return db.table("fin_import_items").insert(new).execute().data[0]


# ── Commit / undo ────────────────────────────────────────────────────────
def commit_batch(batch_id: str) -> dict:
    """Write the reviewed batch to the real tables. Refuses if another import
    is already saved (undo it first), so nothing can be imported twice."""
    db = get_client()
    batch = get_batch(batch_id)
    if not batch or batch["status"] != "draft":
        raise ValueError("Esta importación ya no está en borrador.")
    if db.table("fin_import_batches").select("id").eq("status", "committed").execute().data:
        raise ValueError("Ya hay una importación guardada. Deshágala antes de guardar otra.")

    accounts = db.table("fin_accounts").select("*").execute().data
    usd = next((a for a in accounts if a.get("is_default")), None) or next(a for a in accounts if a["currency"] == "USD")
    cats = db.table("fin_categories").select("*").execute().data
    cat = {(c["kind"], c["name"]): c["id"] for c in cats}
    jobs = {j["job_key"]: j for j in list_jobs(batch_id)}
    items = list_items(batch_id)

    # 1. projects (one per invoice kept as a project)
    new_projects = []
    for j in jobs.values():
        if j["action"] != "project":
            continue
        notes = "Importado de QuickBooks"
        if j.get("invoice_no"):
            notes += f" · factura {j['invoice_no']}"
        if j.get("description"):
            notes += f" · {j['description']}"
        new_projects.append({
            "client_name": j["customer"], "title": (j.get("title") or "").strip() or None,
            "system_type": "historico", "status": "completed",
            "contract_usd": float(j["total_usd"]), "contract_iva_rate": 0,
            "contract_iva_usd": float(j["iva_usd"] or 0),
            "notes": notes, "source": "quickbooks", "external_ref": j["job_key"],
            "import_batch_id": batch_id,
            "created_at": f"{j['invoice_date']}T12:00:00+00:00" if j.get("invoice_date") else None,
        })
    created = _insert("projects", [{k: v for k, v in p.items() if v is not None} for p in new_projects])
    pid_by_key = {p["external_ref"]: p["id"] for p in created}

    # 2. money
    payments, expenses, fin = [], [], []
    pay_no = defaultdict(int)

    def fin_row(kind, i, category_name=None, category_id=None):
        return {"tx_date": i["tx_date"], "kind": kind, "account_id": usd["id"],
                "category_id": category_id or cat.get((kind, category_name or "Otros")),
                "description": (i.get("memo") or i.get("payee") or "Movimiento de QuickBooks")[:300],
                "vendor": None if (i.get("payee") or "").strip().lower() in GENERIC_PAYEES else i.get("payee"),
                "currency": "USD", "amount": abs(float(i["amount_usd"])),
                "amount_usd": abs(float(i["amount_usd"])), "source": "quickbooks",
                "external_ref": i["external_ref"], "import_batch_id": batch_id}

    for i in items:
        kind, job = i["kind"], jobs.get(i.get("job_key"))
        pid = pid_by_key.get(i.get("job_key"))
        if kind == "skip":
            continue
        if kind == "client_payment":
            if pid:
                pay_no[pid] += 1
                payments.append({"project_id": pid, "payment_number": pay_no[pid],
                                 "amount_usd": float(i["amount_usd"]), "paid": True, "paid_date": i["tx_date"],
                                 "bank_account": usd["name"], "account_id": usd["id"],
                                 "onvo_commission_pct": 0, "notes": i.get("memo"),
                                 "external_ref": i["external_ref"], "import_batch_id": batch_id})
            elif job and job["action"] in ("existing", "skip"):
                continue
            else:
                fin.append(fin_row("other_income", i, "Mantenimientos" if job else "Otros"))
        elif kind == "project_expense":
            if pid:
                desc = " · ".join(x for x in (i.get("payee"), i.get("memo")) if x) or "Gasto de QuickBooks"
                expenses.append({"project_id": pid, "category": i.get("rubro") or "extras",
                                 "description": desc[:300], "amount_usd": float(i["amount_usd"]),
                                 "iva_rate": 0, "paid": True, "expense_date": i["tx_date"],
                                 "account_id": usd["id"], "notes": "Importado de QuickBooks",
                                 "external_ref": i["external_ref"], "import_batch_id": batch_id})
            elif job and job["action"] in ("existing", "skip"):
                continue
            else:
                fin.append(fin_row("company_expense", i, "Otros"))
        elif kind in ("company_expense", "owner_draw", "other_income"):
            default = {"owner_draw": "Retiro personal"}.get(kind, "Otros")
            fin.append(fin_row(kind, i, default, i.get("category_id")))

    _insert("project_payments", payments)
    _insert("project_expenses", expenses)
    _insert("fin_transactions", fin)
    result = {"projects": len(created), "payments": len(payments), "expenses": len(expenses),
              "other": len(fin)}
    db.table("fin_import_batches").update({
        "status": "committed", "committed_at": datetime.now(timezone.utc).isoformat(),
        "summary": {**(batch.get("summary") or {}), "written": result},
    }).eq("id", batch_id).execute()
    return result


def undo_batch(batch_id: str) -> None:
    db = get_client()
    db.table("fin_transactions").delete().eq("import_batch_id", batch_id).execute()
    db.table("project_expenses").delete().eq("import_batch_id", batch_id).execute()
    db.table("project_payments").delete().eq("import_batch_id", batch_id).execute()
    db.table("projects").delete().eq("import_batch_id", batch_id).execute()
    db.table("fin_import_batches").update({"status": "undone"}).eq("id", batch_id).execute()
