"""Checks for calculations/qb_import.py (Phase 25.2). No database needed.

    .venv/bin/python scripts/validate_phase25_import.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculations.qb_import import parse_journal, propose, reconcile  # noqa: E402

C, AR, IVA, S, COS, OFF = ("Cash and cash equivalents", "Accounts Receivable (A/R)", "IVA Control", "Sales",
                           "Cost of sales", "Office expenses")


def tx(date, ty, name, memo, *lines, no=None):
    first, *rest = lines
    out = [(None, date, ty, no, name, memo, first[0], first[1], first[2])]
    for acct, dr, cr, *lm in rest:
        out.append((None, None, None, None, None, lm[0] if lm else None, acct, dr, cr))
    out.append((None,) * 9)
    return out


rows = [("Empresa",), ("Journal",), ("All Dates",), (None,),
        (None, "Date", "Transaction Type", "No.", "Name", "Memo/Description", "Account", "Debit", "Credit")]
# two invoices for Ana, one for Luis (whose job already lives in the app)
rows += tx("01/10/2024", "Invoice", "Ana Mora", None, (AR, 1000, None), (S, None, 1000, "Sistema solar Escazú"), no=1)
rows += tx("03/01/2024", "Invoice", "Ana Mora", None, (AR, 500, None), (S, None, 500, "Portón eléctrico"), no=2)
rows += tx("05/01/2024", "Invoice", "Luis Castro", None, (AR, 800, None), (S, None, 800, "Proyecto FV Rosa Castro"), no=3)
# Ana pays 1,200 then 300: the first payment covers invoice 1 and 200 of invoice 2
rows += tx("01/15/2024", "Payment", "Ana Mora", None, (C, 1200, None), (AR, None, 1200))
rows += tx("03/05/2024", "Payment", "Ana Mora", None, (C, 300, None), (AR, None, 300))
# Luis' payment is already recorded in the app
rows += tx("05/02/2024", "Payment", "Luis Castro", None, (C, 800, None), (AR, None, 800))
# expenses: 113 with 13 IVA for Escazú; personal card; office; unknown cost
rows += tx("01/12/2024", "Expense", "Ditesa", None, (C, None, 113),
           (COS, 100, None, "Proyecto Escazú Ana Mora · Ditesa 1"), (IVA, 13, None))
rows += tx("02/01/2024", "Expense", "Oscar Pauly", None, (C, None, 400), (COS, 400, None, "Pago Visa enero"))
rows += tx("02/02/2024", "Expense", "Kolbi", None, (C, None, 30), (OFF, 30, None, "Teléfono febrero"))
rows += tx("02/03/2024", "Expense", "Ferretería", None, (C, None, 70), (COS, 70, None, "Tornillos varios"))
rows += tx("05/03/2024", "Expense", "HCG", None, (C, None, 250), (COS, 250, None, "Proyecto FV Rosa Castro · Inversor"))
rows += [("TOTAL", None, None, None, None, None, None, 0, 0)]

cats = [{"id": "c-tel", "name": "Teléfono e internet", "kind": "company_expense"},
        {"id": "c-otros", "name": "Otros", "kind": "company_expense"},
        {"id": "c-card", "name": "Pago de tarjetas", "kind": "owner_draw"},
        {"id": "c-draw", "name": "Retiro personal", "kind": "owner_draw"}]
app_projects = [{"id": "p-rosa", "client_name": "Rosa Castro", "contract_usd": 800}]
app_payments = [{"project_id": "p-rosa", "amount_usd": 800, "paid": True, "paid_date": "2024-05-01"}]

txs = parse_journal(rows)
assert len(txs) == 11, len(txs)
r = propose(txs, cats, app_projects, app_payments)
jobs = {j["invoice_no"]: j for j in r["jobs"]}
assert [j["action"] for j in r["jobs"]] == ["project", "project", "existing"], r["jobs"]
assert jobs["1"]["title"] == "Sistema solar Escazú"

pays = [i for i in r["items"] if i["qb_type"] == "Payment"]
by_job = {}
for i in pays:
    by_job[(i["job_key"], i["kind"])] = round(by_job.get((i["job_key"], i["kind"]), 0) + i["amount_usd"], 2)
assert by_job[(jobs["1"]["job_key"], "client_payment")] == 1000, by_job
assert by_job[(jobs["2"]["job_key"], "client_payment")] == 500, by_job
assert by_job[(jobs["3"]["job_key"], "skip")] == 800, by_job      # already in the app

exp = {i["memo"]: i for i in r["items"] if i["qb_type"] != "Payment"}
e = exp["Proyecto Escazú Ana Mora · Ditesa 1"]
assert e["kind"] == "project_expense" and e["job_key"] == jobs["1"]["job_key"] and e["amount_usd"] == 113, e
assert e["rubro"] == "materiales", e
assert exp["Pago Visa enero"]["kind"] == "owner_draw" and exp["Pago Visa enero"]["category_id"] == "c-card"
assert exp["Teléfono febrero"]["kind"] == "company_expense" and exp["Teléfono febrero"]["category_id"] == "c-tel"
assert exp["Tornillos varios"]["kind"] == "project_expense" and exp["Tornillos varios"]["job_key"] is None
assert exp["Tornillos varios"]["confidence"] == "ninguna"
assert exp["Proyecto FV Rosa Castro · Inversor"]["kind"] == "skip"  # cost of the app project

rec = reconcile(r["items"], r["totals"])
assert rec["ok"] and rec["qb_in"] == 2300 and rec["qb_out"] == 863, rec
assert rec["skipped_in"] == 800 and rec["skipped_out"] == 250, rec

# the same file gives the same references (no duplicates on a second read)
assert sorted(i["external_ref"] for i in propose(parse_journal(rows), cats, app_projects, app_payments)["items"]) \
    == sorted(i["external_ref"] for i in r["items"])
assert len({i["external_ref"] for i in r["items"]}) == len(r["items"])

print("Phase 25.2 QuickBooks import checks: all passed")
