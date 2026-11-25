"""Finanzas data access (PLAN_PHASE25_FINANZAS.md). Tables from migration 070."""
from __future__ import annotations

from database.supabase_client import get_client


# ── Accounts ─────────────────────────────────────────────────────────────
def list_accounts(active_only: bool = True) -> list[dict]:
    q = get_client().table("fin_accounts").select("*")
    if active_only:
        q = q.eq("active", True)
    return q.order("sort_order").order("name").execute().data


def update_account(account_id: str, **fields) -> dict:
    return get_client().table("fin_accounts").update(fields).eq("id", account_id).execute().data[0]


# ── Categories ───────────────────────────────────────────────────────────
def list_categories(kind: str | None = None, active_only: bool = True) -> list[dict]:
    q = get_client().table("fin_categories").select("*")
    if kind:
        q = q.eq("kind", kind)
    if active_only:
        q = q.eq("active", True)
    return q.order("kind").order("sort_order").order("name").execute().data


def _all(make_query) -> list[dict]:
    """Supabase returns at most 1000 rows per request: page through them all."""
    out, start = [], 0
    while True:
        rows = make_query().range(start, start + 999).execute().data
        out += rows
        if len(rows) < 1000:
            return out
        start += 1000


# ── Transactions ─────────────────────────────────────────────────────────
def list_transactions() -> list[dict]:
    return _all(lambda: get_client().table("fin_transactions").select("*").order("tx_date", desc=True).order("id"))


def get_transaction(tx_id: str) -> dict | None:
    rows = get_client().table("fin_transactions").select("*").eq("id", tx_id).limit(1).execute().data
    return rows[0] if rows else None


def add_transaction(payload: dict) -> dict:
    clean = {k: v for k, v in payload.items() if v not in (None, "")}
    return get_client().table("fin_transactions").insert(clean).execute().data[0]


def delete_transaction(tx_id: str) -> None:
    get_client().table("fin_transactions").delete().eq("id", tx_id).execute()


# ── Everything the Finanzas page needs, in one go ───────────────────────
def load_all() -> dict:
    db = get_client()
    projects = _all(lambda: db.table("projects").select("id,client_name,title,status,source").order("id"))
    return {
        "accounts": list_accounts(active_only=False),
        "categories": list_categories(active_only=False),
        "fin_txs": list_transactions(),
        "payments": _all(lambda: db.table("project_payments").select("*").eq("paid", True).order("id")),
        "expenses": _all(lambda: db.table("project_expenses").select("*").eq("paid", True).order("id")),
        "labor": _all(lambda: db.table("project_labor").select("id,project_id,worker_name,advances").order("id")),
        "projects": {p["id"]: p for p in projects},
        "invoice_payments": _invoice_payments(),
    }


def _invoice_payments() -> list[dict]:
    try:
        from database.invoices_db import list_open_payments

        return list_open_payments()
    except Exception:
        return []  # migration 074 not run yet: Finanzas still works


# ── Recurring expenses (migration 072) ───────────────────────────────────
def list_recurring() -> list[dict]:
    return get_client().table("fin_recurring").select("*").order("active", desc=True).order("name").execute().data


def get_recurring(rule_id: str) -> dict | None:
    rows = get_client().table("fin_recurring").select("*").eq("id", rule_id).execute().data
    return rows[0] if rows else None


def save_recurring(payload: dict, rule_id: str | None = None) -> dict:
    db = get_client().table("fin_recurring")
    if rule_id:
        return db.update(payload).eq("id", rule_id).execute().data[0]
    return db.insert({k: v for k, v in payload.items() if v not in (None, "")}).execute().data[0]


def delete_recurring(rule_id: str) -> None:
    """The movements it already created stay (they are real money)."""
    get_client().table("fin_recurring").delete().eq("id", rule_id).execute()


def generate_recurring(today=None) -> int:
    """Create the movement of every recurring rule whose date has arrived and
    that month isn't there yet. Returns how many were created. CRC rules use
    the BCCR rate of the charge date."""
    from calculations.recurring import due_dates, memo, period
    from utils.fx_history import today_cr

    today = today or today_cr()
    rules = [r for r in list_recurring() if r.get("active")]
    if not rules:
        return 0
    accounts = {a["id"]: a for a in list_accounts(active_only=False)}
    done = {}
    for t in _all(lambda: get_client().table("fin_transactions").select("recurring_id,period")
                  .not_.is_("recurring_id", "null").order("id")):
        done.setdefault(t["recurring_id"], set()).add(t["period"])
    created = 0
    for r in rules:
        acc = accounts.get(r["account_id"])
        if not acc:
            continue
        for d in due_dates(r, today, done.get(r["id"], set())):
            amount = float(r["amount"])
            fx = None
            if acc["currency"] == "CRC":
                from utils.fx_history import get_rate

                fx, _ = get_rate(d.isoformat())
            payload = {
                "tx_date": d.isoformat(), "kind": r["kind"], "account_id": acc["id"],
                "category_id": r.get("category_id"), "description": memo(r["memo_template"], d),
                "vendor": r.get("vendor"), "currency": acc["currency"], "amount": amount,
                "fx_rate": fx, "amount_usd": round(amount / fx, 2) if fx else amount,
                "notes": "Recurrente", "recurring_id": r["id"], "period": period(d),
            }
            try:
                add_transaction(payload)
                created += 1
            except Exception:
                # another request created it first (unique recurring_id + period)
                pass
    return created


# ── Vendors (migration 073) ──────────────────────────────────────────────
def list_vendors() -> list[str]:
    rows = _all(lambda: get_client().table("fin_vendors").select("name").eq("active", True).order("name"))
    return sorted({r["name"] for r in rows}, key=str.lower)


def add_vendors(names, source: str = "manual") -> int:
    """Add names that aren't in the list yet (case-insensitive). Returns how many were added."""
    existing = {r["name"].lower() for r in _all(lambda: get_client().table("fin_vendors").select("name").order("id"))}
    new, seen = [], set()
    for n in names:
        n = " ".join(str(n or "").split())
        if n and n.lower() not in existing and n.lower() not in seen:
            seen.add(n.lower())
            new.append({"name": n, "source": source})
    if new:
        get_client().table("fin_vendors").insert(new).execute()
    return len(new)
