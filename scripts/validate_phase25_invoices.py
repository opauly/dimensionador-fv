"""Checks for calculations/invoices.py and invoice money in Finanzas. No database needed.

    .venv/bin/python scripts/validate_phase25_invoices.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculations.finance import account_balances, build_movements, totals as fin_totals  # noqa: E402
from calculations.invoices import balance, check_payment, clean_lines, fmt, status_after, totals  # noqa: E402

# lines → totals, empty rows dropped
lines = clean_lines([{"description": "Visita técnica", "quantity": "1", "unit_price": "80"},
                     {"description": "Fusible", "quantity": "2", "unit_price": "22.50"},
                     {"description": "", "quantity": "1", "unit_price": ""}])
assert len(lines) == 2
t = totals(lines, 13)
assert t == {"subtotal": 125.0, "iva": 16.25, "total": 141.25}, t
assert totals(lines, 0)["total"] == 125.0

inv = {"total": 141.25, "status": "open"}
# partial payment keeps it open; full payment closes it
p1 = [{"amount": 100}]
assert balance(inv, p1) == {"paid": 100.0, "saldo": 41.25}
assert status_after(inv, p1) == "open"
p2 = p1 + [{"amount": 41.25}]
assert balance(inv, p2)["saldo"] == 0 and status_after(inv, p2) == "paid"
# removing a payment reopens it
assert status_after({**inv, "status": "paid"}, p1) == "open"
# void / linked stay put
assert status_after({**inv, "status": "void"}, p2) == "void"
assert status_after({**inv, "status": "linked"}, []) == "linked"

# payment checks
assert check_payment(inv, p1, 41.25) is None
assert "mayor que el saldo" in check_payment(inv, p1, 50)
assert check_payment(inv, p1, 0)
assert check_payment({**inv, "status": "linked"}, [], 10)

# CRC invoice payment shows in Finanzas in USD, and in colones in a CRC account
USD = {"id": "u", "name": "BAC USD", "currency": "USD", "is_default": True, "opening_balance": 0}
CRC = {"id": "c", "name": "BAC CRC", "currency": "CRC", "opening_balance": 0}
ipay = [{"id": "ip1", "invoice_id": "i1", "paid_date": "2026-11-20", "amount": 50000, "fx_rate": 500,
         "amount_usd": 100.0, "account_id": "c", "invoice": {"number": 7, "client_name": "Ana", "currency": "CRC"}},
        {"id": "ip2", "invoice_id": "i2", "paid_date": "2026-11-21", "amount": 40, "fx_rate": None,
         "amount_usd": 40.0, "account_id": "u", "invoice": {"number": 8, "client_name": "Luis", "currency": "USD"}}]
mv = build_movements([USD, CRC], [], [], [], [], {}, {}, ipay)
assert len(mv) == 2 and all(m["kind"] == "client_payment" for m in mv)
assert fin_totals(mv)["income"] == 140.0
bal = {b["id"]: b["balance"] for b in account_balances([USD, CRC], mv, 500)}
assert bal == {"u": 40.0, "c": 50000.0}, bal
assert mv[1]["description"] == "Invoice 7" and mv[1]["project_name"] == "Ana"
# old callers (no invoice payments) still work
assert build_movements([USD], [], [], [], [], {}, {}) == []

assert fmt(1234.5, "CRC") == "₡1,234.50" and fmt(-3, "USD") == "-$3.00"
print("OK — invoices")
