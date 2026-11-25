"""Finanzas: one view over every real money movement (PLAN_PHASE25_FINANZAS.md).

Pure module — no database imports — so it can be checked with plain dicts
(see scripts/validate_phase25_finanzas.py).

Where money lives:
  - Project income   → project_payments rows with paid = true (gross amount_usd;
                       an ONVO commission is its own Banco expense, if recorded)
  - Project expenses → project_expenses rows with paid = true
                       + project_labor.advances (each {amount, date})
  - Everything else  → fin_transactions (company_expense, other_income,
                       owner_draw, transfer)

Sign convention for `amount_usd` on a movement: + money in, − money out.
Transfers are 0 for income/expense totals; they only move account balances.
"""
from __future__ import annotations

from datetime import date

KIND_LABELS = {
    "client_payment": "Pago de cliente",
    "other_income": "Otro ingreso",
    "project_expense": "Gasto de proyecto",
    "company_expense": "Gasto de empresa",
    "owner_draw": "Retiro del dueño",
    "transfer": "Transferencia",
}
INCOME_KINDS = ("client_payment", "other_income")
EXPENSE_KINDS = ("project_expense", "company_expense")


def _num(v) -> float:
    return float(v) if v not in (None, "") else 0.0


def _d(v) -> str:
    return str(v)[:10] if v else ""


def to_usd(amount: float, currency: str, fx_rate: float | None) -> float:
    if (currency or "USD") == "USD":
        return round(amount, 2)
    if not fx_rate:
        raise ValueError("Falta el tipo de cambio para convertir colones a USD")
    return round(amount / float(fx_rate), 2)


def _native(amount_usd: float, amount: float | None, currency: str | None,
            fx_rate: float | None, account_currency: str) -> float:
    """What a movement did to an account, in that account's own currency."""
    currency = currency or "USD"
    if currency == account_currency and amount is not None:
        return float(amount)
    if account_currency == "USD":
        return amount_usd
    return amount_usd * float(fx_rate or 0)


def default_account_id(accounts: list[dict]) -> str | None:
    for a in accounts:
        if a.get("is_default"):
            return a["id"]
    usd = [a for a in accounts if a.get("currency") == "USD"]
    return usd[0]["id"] if usd else (accounts[0]["id"] if accounts else None)


def payment_account_id(payment: dict, accounts: list[dict], default_id: str | None) -> str | None:
    """Explicit account_id wins; otherwise match the free-text bank_account to
    an account name; otherwise the default USD account."""
    if payment.get("account_id"):
        return payment["account_id"]
    text = (payment.get("bank_account") or "").strip().lower()
    if text:
        for a in accounts:
            if a["name"].strip().lower() == text:
                return a["id"]
    return default_id


def build_movements(
    accounts: list[dict],
    fin_txs: list[dict],
    payments: list[dict],
    expenses: list[dict],
    labor: list[dict],
    projects: dict,
    categories: dict,
    invoice_payments: list[dict] | None = None,
) -> list[dict]:
    """Every movement, newest first. `projects` is {id: project row};
    `categories` is {id: category row}; `invoice_payments` are payments of
    invoices not linked to a project, each with its `invoice` row."""
    acc = {a["id"]: a for a in accounts}
    default_id = default_account_id(accounts)

    def proj_name(pid):
        p = projects.get(pid) or {}
        name = p.get("client_name") or ""
        return f"{name} · {p['title']}" if p.get("title") else name

    out: list[dict] = []

    for t in fin_txs:
        kind = t["kind"]
        amount_usd = _num(t.get("amount_usd"))
        sign = 1 if kind == "other_income" else -1
        cat = categories.get(t.get("category_id")) or {}
        out.append({
            "date": _d(t.get("tx_date")), "kind": kind, "kind_label": KIND_LABELS[kind],
            "account_id": t["account_id"], "to_account_id": t.get("to_account_id"),
            "amount_usd": 0.0 if kind == "transfer" else sign * amount_usd,
            "transfer_usd": amount_usd if kind == "transfer" else 0.0,
            "amount": _num(t.get("amount")), "currency": t.get("currency") or "USD",
            "to_amount": _num(t.get("to_amount")) if t.get("to_amount") is not None else None,
            "fx_rate": t.get("fx_rate"),
            "description": t.get("description") or "", "vendor": t.get("vendor") or "",
            "category": cat.get("name") or "", "project_id": None, "project_name": "",
            "source": "fin", "ref_id": t["id"], "recurring": bool(t.get("recurring_id")),
        })

    for p in payments:
        if not p.get("paid"):
            continue
        amount_usd = _num(p.get("amount_usd"))
        out.append({
            "date": _d(p.get("paid_date") or p.get("created_at")), "kind": "client_payment",
            "kind_label": KIND_LABELS["client_payment"],
            "account_id": payment_account_id(p, accounts, default_id), "to_account_id": None,
            "amount_usd": amount_usd, "transfer_usd": 0.0, "amount": amount_usd, "currency": "USD",
            "to_amount": None, "fx_rate": None,
            "description": f"Pago {p.get('payment_number') or ''}".strip(), "vendor": "",
            "category": "", "project_id": p.get("project_id"), "project_name": proj_name(p.get("project_id")),
            "source": "payment", "ref_id": p["id"],
        })

    for p in invoice_payments or []:
        inv = p.get("invoice") or {}
        currency = inv.get("currency") or "USD"
        out.append({
            "date": _d(p.get("paid_date")), "kind": "client_payment",
            "kind_label": KIND_LABELS["client_payment"],
            "account_id": p.get("account_id") or default_id, "to_account_id": None,
            "amount_usd": _num(p.get("amount_usd")), "transfer_usd": 0.0,
            "amount": _num(p.get("amount")), "currency": currency, "to_amount": None,
            "fx_rate": p.get("fx_rate"),
            "description": f"Invoice {inv.get('number') or ''}".strip(), "vendor": "",
            "category": "", "project_id": None, "project_name": inv.get("client_name") or "",
            "source": "invoice", "ref_id": p["id"], "invoice_id": p.get("invoice_id"),
        })

    for e in expenses:
        if not e.get("paid"):
            continue
        total_usd = _num(e.get("total_with_iva")) or _num(e.get("amount_usd"))
        currency = e.get("currency") or "USD"
        out.append({
            "date": _d(e.get("expense_date") or e.get("created_at")), "kind": "project_expense",
            "kind_label": KIND_LABELS["project_expense"],
            "account_id": e.get("account_id") or default_id, "to_account_id": None,
            "amount_usd": -total_usd, "transfer_usd": 0.0,
            "amount": _num(e.get("amount_original")) if currency != "USD" else total_usd,
            "currency": currency, "to_amount": None, "fx_rate": e.get("fx_rate"),
            "description": e.get("description") or "", "vendor": "",
            "category": e.get("category") or "", "project_id": e.get("project_id"),
            "project_name": proj_name(e.get("project_id")),
            "source": "expense", "ref_id": e["id"],
        })

    for l in labor:
        for adv in l.get("advances") or []:
            amount_usd = _num(adv.get("amount"))
            out.append({
                "date": _d(adv.get("date")), "kind": "project_expense",
                "kind_label": KIND_LABELS["project_expense"],
                "account_id": default_id, "to_account_id": None,
                "amount_usd": -amount_usd, "transfer_usd": 0.0, "amount": amount_usd, "currency": "USD",
                "to_amount": None, "fx_rate": None,
                "description": f"Adelanto {adv.get('number') or ''} — {l.get('worker_name') or ''}".strip(),
                "vendor": l.get("worker_name") or "", "category": "mano_de_obra",
                "project_id": l.get("project_id"), "project_name": proj_name(l.get("project_id")),
                "source": "labor", "ref_id": l["id"],
            })

    for m in out:
        a = acc.get(m["account_id"]) or {}
        m["account_name"] = a.get("name") or "—"
        t = acc.get(m.get("to_account_id")) or {}
        m["to_account_name"] = t.get("name") or ""

    out.sort(key=lambda m: (m["date"], m["kind"]), reverse=True)
    return out


def account_balances(accounts: list[dict], movements: list[dict], usd_per_crc_rate: float | None) -> list[dict]:
    """Balance of each account in its own currency, plus a USD equivalent at
    `usd_per_crc_rate` (CRC per USD, today's). Movements dated before an
    account's opening_date are already inside its opening balance."""
    rows = []
    for a in accounts:
        cur = a["currency"]
        opening_date = _d(a.get("opening_date"))
        bal = _num(a.get("opening_balance"))
        for m in movements:
            if opening_date and m["date"] < opening_date:
                continue
            if m["account_id"] == a["id"]:
                if m["kind"] == "transfer":
                    bal -= _native(m["transfer_usd"], m["amount"], m["currency"], m["fx_rate"], cur)
                else:
                    # abs(): a negative expense (e.g. a supplier discount) carries a
                    # negative `amount`; its direction is already in amount_usd's sign.
                    native = abs(_native(abs(m["amount_usd"]), m["amount"], m["currency"], m["fx_rate"], cur))
                    bal += native if m["amount_usd"] >= 0 else -native
            if m["kind"] == "transfer" and m.get("to_account_id") == a["id"]:
                to_amount = m.get("to_amount")
                bal += to_amount if to_amount is not None else _native(
                    m["transfer_usd"], None, "USD", m["fx_rate"], cur)
        usd = bal if cur == "USD" else (bal / usd_per_crc_rate if usd_per_crc_rate else None)
        rows.append({**a, "balance": round(bal, 2), "balance_usd": round(usd, 2) if usd is not None else None})
    return rows


def totals(movements: list[dict]) -> dict:
    t = {"income": 0.0, "project_expense": 0.0, "company_expense": 0.0, "owner_draw": 0.0}
    for m in movements:
        k = m["kind"]
        if k in INCOME_KINDS:
            t["income"] += m["amount_usd"]
        elif k in ("project_expense", "company_expense", "owner_draw"):
            t[k] += -m["amount_usd"]
    t["expenses"] = t["project_expense"] + t["company_expense"]
    t["operating_profit"] = t["income"] - t["expenses"]
    t["net_after_draws"] = t["operating_profit"] - t["owner_draw"]
    return {k: round(v, 2) for k, v in t.items()}


def filter_movements(movements: list[dict], *, desde: str = "", hasta: str = "", kind: str = "",
                     account_id: str = "", project_id: str = "") -> list[dict]:
    out = []
    for m in movements:
        if desde and m["date"] < desde:
            continue
        if hasta and m["date"] > hasta:
            continue
        if kind and m["kind"] != kind:
            continue
        if account_id and account_id not in (m["account_id"], m.get("to_account_id")):
            continue
        if project_id and m.get("project_id") != project_id:
            continue
        out.append(m)
    return out


def month_bounds(d: date) -> tuple[str, str]:
    first = d.replace(day=1)
    nxt = (first.replace(year=first.year + 1, month=1) if first.month == 12
           else first.replace(month=first.month + 1))
    from datetime import timedelta

    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()
