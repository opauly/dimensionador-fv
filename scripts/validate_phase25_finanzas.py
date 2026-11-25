"""Checks for calculations/finance.py (Phase 25.1). No database needed.

    .venv/bin/python scripts/validate_phase25_finanzas.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculations.finance import account_balances, build_movements, filter_movements, to_usd, totals  # noqa: E402

USD = {"id": "usd", "name": "BAC San José (USD)", "currency": "USD", "is_default": True,
       "opening_balance": 1000, "opening_date": "2026-11-01", "active": True}
CRC = {"id": "crc", "name": "Cuenta en colones (CRC)", "currency": "CRC", "is_default": False,
       "opening_balance": 50000, "opening_date": "2026-11-01", "active": True}
accounts = [USD, CRC]
cats = {"c1": {"id": "c1", "name": "Software", "kind": "company_expense"},
        "c2": {"id": "c2", "name": "Retiro personal", "kind": "owner_draw"},
        "c3": {"id": "c3", "name": "Mantenimientos", "kind": "other_income"}}
projects = {"p1": {"id": "p1", "client_name": "María José", "status": "active"}}

fin_txs = [
    # company expense paid in colones: ₡22,500 at 450 = $50
    {"id": "t1", "tx_date": "2026-11-05", "kind": "company_expense", "account_id": "crc", "category_id": "c1",
     "description": "Licencia", "currency": "CRC", "amount": 22500, "fx_rate": 450, "amount_usd": 50},
    {"id": "t2", "tx_date": "2026-11-06", "kind": "owner_draw", "account_id": "usd", "category_id": "c2",
     "description": "Retiro", "currency": "USD", "amount": 300, "amount_usd": 300},
    {"id": "t3", "tx_date": "2026-11-07", "kind": "other_income", "account_id": "usd", "category_id": "c3",
     "description": "Mantenimiento", "currency": "USD", "amount": 200, "amount_usd": 200},
    # transfer $100 USD → ₡45,000
    {"id": "t4", "tx_date": "2026-11-08", "kind": "transfer", "account_id": "usd", "to_account_id": "crc",
     "description": "Cambio", "currency": "USD", "amount": 100, "fx_rate": 450, "amount_usd": 100, "to_amount": 45000},
    # before the opening date: must not move balances
    {"id": "t5", "tx_date": "2026-10-20", "kind": "company_expense", "account_id": "usd", "category_id": "c1",
     "description": "Viejo", "currency": "USD", "amount": 999, "amount_usd": 999},
]
payments = [
    {"id": "pay1", "project_id": "p1", "payment_number": 1, "amount_usd": 5000, "paid": True,
     "paid_date": "2026-11-02", "bank_account": "BAC San José (USD)"},
    {"id": "pay2", "project_id": "p1", "payment_number": 2, "amount_usd": 3000, "paid": False},
]
expenses = [
    {"id": "e1", "project_id": "p1", "category": "equipo", "amount_usd": 2000, "total_with_iva": 2000,
     "paid": True, "expense_date": "2026-11-03"},
    {"id": "e2", "project_id": "p1", "category": "materiales", "amount_usd": 20, "total_with_iva": 20,
     "paid": True, "expense_date": "2026-11-04", "account_id": "crc", "currency": "CRC",
     "amount_original": 9000, "fx_rate": 450},
    {"id": "e3", "project_id": "p1", "category": "viaticos", "amount_usd": 80, "paid": False},
]
labor = [{"id": "l1", "project_id": "p1", "worker_name": "Steven",
          "advances": [{"number": 1, "amount": 400, "date": "2026-11-09"}]}]

mv = build_movements(accounts, fin_txs, payments, expenses, labor, projects, cats)
assert len(mv) == 9, len(mv)  # 5 fin + 1 paid payment + 2 paid expenses + 1 advance
assert mv[0]["date"] >= mv[-1]["date"], "newest first"

t = totals(filter_movements(mv, desde="2026-11-01", hasta="2026-11-30"))
assert t["income"] == 5200, t
assert t["project_expense"] == 2420, t          # 2000 + 20 + 400
assert t["company_expense"] == 50, t            # the Oct one is filtered out
assert t["owner_draw"] == 300, t
assert t["operating_profit"] == 2730, t
assert t["net_after_draws"] == 2430, t

bal = {b["id"]: b for b in account_balances(accounts, mv, 450)}
# USD: 1000 + 5000 - 2000 - 300 + 200 - 100 - 400 = 3400
assert bal["usd"]["balance"] == 3400, bal["usd"]
# CRC: 50000 - 22500 - 9000 + 45000 = 63500
assert bal["crc"]["balance"] == 63500, bal["crc"]
assert abs(bal["crc"]["balance_usd"] - 141.11) < 0.01, bal["crc"]

assert to_usd(22500, "CRC", 450) == 50
assert to_usd(10, "USD", None) == 10
try:
    to_usd(1, "CRC", None)
    raise AssertionError("CRC without rate must fail")
except ValueError:
    pass

# payment with no account and an unknown bank name falls back to the default USD account
mv2 = build_movements(accounts, [], [{"id": "x", "project_id": "p1", "amount_usd": 1, "paid": True,
                                       "paid_date": "2026-11-10", "bank_account": "Otro banco"}], [], [], projects, cats)
assert mv2[0]["account_id"] == "usd"

# a negative project expense (supplier discount) raises the balance by its amount
mv3 = build_movements([USD], [], [], [{"id": "d", "project_id": "p1", "category": "equipo", "amount_usd": -50,
                                       "total_with_iva": -50, "paid": True, "expense_date": "2026-11-10"}],
                      [], projects, cats)
assert account_balances([USD], mv3, 450)[0]["balance"] == 1050, account_balances([USD], mv3, 450)

print("Phase 25.1 finance checks: all passed")
