"""Invoices sueltos — data access (migration 074). Rules live in
calculations/invoices.py; this module only reads and writes."""
from __future__ import annotations

from datetime import datetime, timezone

from calculations.invoices import balance, check_payment, clean_lines, status_after, totals
from database.supabase_client import get_client


def _db():
    return get_client()


def _fx(d) -> float:
    from utils.fx_history import get_rate

    return get_rate(d)[0]


# ── Clients ──────────────────────────────────────────────────────────────
def client_names() -> list[str]:
    """Clients from the client list plus every project's client, A→Z."""
    db = _db()
    names = {(r["name"] or "").strip() for r in db.table("clients").select("name").execute().data}
    from database.finance_db import _all

    names |= {(r["client_name"] or "").strip()
              for r in _all(lambda: db.table("projects").select("client_name").order("id"))}
    return sorted((n for n in names if n), key=str.lower)


def _client_id(name: str) -> str | None:
    """The client-list id for `name`; a new name is added to the list."""
    from database.clients_db import upsert_client

    try:
        return upsert_client(name).get("id")
    except Exception:
        return None


# ── Invoices ─────────────────────────────────────────────────────────────
def list_invoices() -> list[dict]:
    """Every invoice with its payments and balance, newest first."""
    db = _db()
    invs = db.table("fin_invoices").select("*").order("number", desc=True).execute().data
    pays = db.table("fin_invoice_payments").select("*").order("paid_date").execute().data
    lines = db.table("fin_invoice_lines").select("invoice_id,description,sort_order").order("sort_order").execute().data
    by_inv, first_line = {}, {}
    for p in pays:
        by_inv.setdefault(p["invoice_id"], []).append(p)
    for l in lines:
        first_line.setdefault(l["invoice_id"], l["description"])
    out = []
    for i in invs:
        p = by_inv.get(i["id"], [])
        out.append({**i, "payments": p, "first_line": first_line.get(i["id"], ""), **balance(i, p)})
    return out


def get_invoice(invoice_id: str) -> dict | None:
    db = _db()
    rows = db.table("fin_invoices").select("*").eq("id", invoice_id).execute().data
    if not rows:
        return None
    inv = rows[0]
    inv["lines"] = (db.table("fin_invoice_lines").select("*").eq("invoice_id", invoice_id)
                    .order("sort_order").execute().data)
    inv["payments"] = (db.table("fin_invoice_payments").select("*").eq("invoice_id", invoice_id)
                       .order("paid_date").order("created_at").execute().data)
    inv.update(balance(inv, inv["payments"]))
    return inv


def _next_number() -> int:
    rows = _db().table("fin_invoices").select("number").order("number", desc=True).limit(1).execute().data
    return (rows[0]["number"] if rows else 0) + 1


def save_invoice(fields: dict, lines: list[dict], invoice_id: str | None = None) -> dict:
    """Create or update an invoice and replace its lines. `fields`: client_name,
    issue_date, due_date, currency, iva_rate, notes."""
    lines = clean_lines(lines)
    if not lines:
        raise ValueError("Agregue al menos una línea con monto.")
    if not (fields.get("client_name") or "").strip():
        raise ValueError("Elija o escriba el cliente.")
    db = _db()
    t = totals(lines, fields.get("iva_rate") or 0)
    payload = {
        "client_name": fields["client_name"].strip(),
        "client_id": _client_id(fields["client_name"].strip()),
        "issue_date": fields["issue_date"], "due_date": fields.get("due_date") or None,
        "currency": fields["currency"], "iva_rate": float(fields.get("iva_rate") or 0),
        "notes": (fields.get("notes") or "").strip() or None, **t,
        "fx_rate": _fx(fields["issue_date"]) if fields["currency"] == "CRC" else None,
    }
    if invoice_id:
        current = get_invoice(invoice_id)
        if not current:
            raise ValueError("Ese invoice no existe.")
        if current["status"] in ("void", "linked"):
            raise ValueError("Este invoice ya no se puede editar.")
        if current["payments"] and payload["currency"] != current["currency"]:
            raise ValueError("No se puede cambiar la moneda de un invoice que ya tiene pagos.")
        if t["total"] + 0.009 < current["paid"]:
            raise ValueError("El nuevo total es menor que lo que ya se cobró.")
        payload["status"] = status_after({**current, **payload}, current["payments"])
        inv = db.table("fin_invoices").update(payload).eq("id", invoice_id).execute().data[0]
        db.table("fin_invoice_lines").delete().eq("invoice_id", invoice_id).execute()
    else:
        payload["number"] = _next_number()
        payload["status"] = "open"
        inv = db.table("fin_invoices").insert(payload).execute().data[0]
    db.table("fin_invoice_lines").insert(
        [{**l, "invoice_id": inv["id"], "sort_order": n} for n, l in enumerate(lines)]).execute()
    return inv


def delete_invoice(invoice_id: str) -> None:
    inv = get_invoice(invoice_id)
    if inv and inv["payments"]:
        raise ValueError("Tiene pagos registrados: bórrelos primero o anúlelo.")
    _db().table("fin_invoices").delete().eq("id", invoice_id).execute()


def set_void(invoice_id: str, void: bool) -> None:
    inv = get_invoice(invoice_id)
    if not inv:
        return
    if void and inv["payments"]:
        raise ValueError("Tiene pagos registrados: bórrelos primero.")
    if inv["status"] == "linked":
        raise ValueError("Ya está ligado a un proyecto.")
    status = "void" if void else status_after({**inv, "status": "open"}, inv["payments"])
    _db().table("fin_invoices").update({"status": status}).eq("id", invoice_id).execute()


# ── Payments ─────────────────────────────────────────────────────────────
def add_payment(invoice_id: str, paid_date: str, amount: float, account_id: str, notes: str | None = None) -> None:
    inv = get_invoice(invoice_id)
    if not inv:
        raise ValueError("Ese invoice no existe.")
    amount = round(float(amount), 2)
    err = check_payment(inv, inv["payments"], amount)
    if err:
        raise ValueError(err)
    fx = _fx(paid_date) if inv["currency"] == "CRC" else None
    db = _db()
    db.table("fin_invoice_payments").insert({
        "invoice_id": invoice_id, "paid_date": paid_date, "amount": amount, "fx_rate": fx,
        "amount_usd": round(amount / fx, 2) if fx else amount, "account_id": account_id,
        "notes": (notes or "").strip() or None,
    }).execute()
    pays = inv["payments"] + [{"amount": amount}]
    db.table("fin_invoices").update({"status": status_after(inv, pays)}).eq("id", invoice_id).execute()


def delete_payment(payment_id: str) -> str | None:
    db = _db()
    rows = db.table("fin_invoice_payments").select("invoice_id").eq("id", payment_id).execute().data
    if not rows:
        return None
    inv = get_invoice(rows[0]["invoice_id"])
    if inv["status"] == "linked":
        raise ValueError("Ya está ligado a un proyecto: corríjalo en el proyecto.")
    db.table("fin_invoice_payments").delete().eq("id", payment_id).execute()
    pays = [p for p in inv["payments"] if p["id"] != payment_id]
    db.table("fin_invoices").update({"status": status_after(inv, pays)}).eq("id", inv["id"]).execute()
    return inv["id"]


def list_open_payments() -> list[dict]:
    """Payments of invoices whose money still lives here (not linked), with
    the invoice fields Finanzas shows."""
    from database.finance_db import _all

    db = _db()
    invs = {i["id"]: i for i in db.table("fin_invoices").select("id,number,client_name,currency,status")
            .neq("status", "linked").execute().data}
    pays = _all(lambda: db.table("fin_invoice_payments").select("*").order("id"))
    return [{**p, "invoice": invs[p["invoice_id"]]} for p in pays if p["invoice_id"] in invs]


# ── Link to a project ────────────────────────────────────────────────────
def link_to_project(invoice_id: str, project_id: str) -> dict:
    """Move the invoice into a project: each payment becomes a paid project
    payment, the balance (if any) a pending one, and the invoice stays here
    only as history ("Ligado a proyecto")."""
    from database.projects_db import add_payment as add_project_payment, get_project, list_payments

    inv = get_invoice(invoice_id)
    if not inv:
        raise ValueError("Ese invoice no existe.")
    if inv["status"] in ("void", "linked"):
        raise ValueError("Este invoice ya no se puede ligar.")
    project = get_project(project_id)
    if not project:
        raise ValueError("Ese proyecto no existe.")
    accounts = {a["id"]: a for a in _db().table("fin_accounts").select("id,name").execute().data}
    number = max([int(p.get("payment_number") or 0) for p in list_payments(project_id)] + [0])
    tag = f"Invoice {inv['number']}"
    for p in inv["payments"]:
        number += 1
        note = tag + (f" · ₡{float(p['amount']):,.2f}" if inv["currency"] == "CRC" else "")
        if p.get("notes"):
            note += f" · {p['notes']}"
        add_project_payment(project_id, number, float(p["amount_usd"]), paid=True, paid_date=p["paid_date"],
                            account_id=p["account_id"], bank_account=(accounts.get(p["account_id"]) or {}).get("name"),
                            notes=note)
    saldo_usd = 0.0
    if inv["saldo"] > 0:
        from utils.fx_history import today_cr

        saldo_usd = round(inv["saldo"] / _fx(today_cr()), 2) if inv["currency"] == "CRC" else inv["saldo"]
        add_project_payment(project_id, number + 1, saldo_usd, notes=f"Saldo del {tag}")
    rate = float(inv["fx_rate"]) if inv["currency"] == "CRC" else 1.0
    if not float(project.get("contract_usd") or 0):
        # An empty project takes the invoice as its contract (total incl. IVA, plus that IVA).
        _db().table("projects").update({"contract_usd": round(float(inv["total"]) / rate, 2),
                                        "contract_iva_usd": round(float(inv["iva"]) / rate, 2)}
                                       ).eq("id", project_id).execute()
    _db().table("fin_invoices").update({
        "status": "linked", "project_id": project_id,
        "linked_at": datetime.now(timezone.utc).isoformat()}).eq("id", invoice_id).execute()
    return {"payments": len(inv["payments"]), "saldo_usd": saldo_usd}
