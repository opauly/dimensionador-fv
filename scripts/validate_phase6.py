from __future__ import annotations
"""Phase 6 (Projects Module) numeric validation — no DB, no Streamlit.

Feeds hand-built dicts into `calculations/project_finance.py` and asserts
the reference numbers from PLAN_PHASE6.md. This is the tester agent's
primary artifact for Phase 6 — extend it in each build step rather than
writing a parallel ad-hoc check.

Usage:
    python -m scripts.validate_phase6
    (or)  python scripts/validate_phase6.py
"""

import os
import sys

# Allow `python scripts/validate_phase6.py` (direct run) as well as
# `python -m scripts.validate_phase6` (module run) — both are documented
# entry points, so make the repo root importable either way.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from calculations.project_finance import (
    summarize, labor_balance, onvo_breakdown, invoice_summary, payments_summary,
)

_failures: list[str] = []


def check(label: str, actual, expected) -> None:
    ok = actual == expected
    mark = "✅" if ok else "❌"
    print(f"  {mark} {label}: expected {expected!r}, got {actual!r}")
    if not ok:
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


# ── Step 3 — Jorge Ramírez reference case (PHASES.md / PLAN_PHASE6.md) ──────
# Off-Grid quote, zero IVA anywhere. Pago 1 ($7,224.00) paid, zero expenses/
# labor/extras.

section("Step 3 — Jorge Ramírez (zero-IVA contract)")

jorge_project = {"contract_usd": 10320.00, "contract_iva_usd": 0.0}
jorge_payments = [{"amount_usd": 7224.00, "paid": True}]
jorge_result = summarize(jorge_project, jorge_payments, [], [], [])

check("ingresos_total", jorge_result["ingresos_total"], 10320.00)
check("recibido", jorge_result["recibido"], 7224.00)
check("pendiente", jorge_result["pendiente"], 3096.00)
check("utilidad_bruta", jorge_result["utilidad_bruta"], 10320.00)
check("iva_a_pagar", jorge_result["iva_a_pagar"], 0.00)
check("utilidad_neta", jorge_result["utilidad_neta"], 10320.00)


# ── Step 3 — Oscar Pauly mixed-IVA case ──────────────────────────────────────
# The case that actually exercises the contract_iva_usd subtraction — Jorge's
# case alone can't catch a regression back to the old buggy formula, since his
# contract_iva_usd is 0 either way.

section("Step 3 — Oscar Pauly (mixed-IVA contract, catches the old bug)")

oscar_project = {"contract_usd": 12674.00, "contract_iva_usd": 949.00}
oscar_result = summarize(oscar_project, [], [], [], [])

check("ingresos_base", oscar_result["ingresos_base"], 11725.00)
check("iva_repercutido", oscar_result["iva_repercutido"], 949.00)
check("ingresos_total", oscar_result["ingresos_total"], 12674.00)
# The bug this catches: an earlier version used raw contract_usd (12,674.00)
# for utilidad_bruta instead of stripping contract_iva_usd first, overstating
# gross profit by exactly the embedded $949 tax.
check("utilidad_bruta (NOT 12674.00)", oscar_result["utilidad_bruta"], 11725.00)


# ── Step 4 — Jorge Ramírez + one Equipo expense ──────────────────────────────
# Same fixture as Step 3, plus one real `project_expenses` row: Equipo FV,
# $3,679.30, 0% IVA, paid. PLAN_PHASE6.md Step 4 validation.

section("Step 4 — Jorge Ramírez + Equipo expense $3,679.30")

jorge_expenses_step4 = [
    {"category": "equipo", "amount_usd": 3679.30, "iva_rate": 0.0, "paid": True},
]
jorge_result_step4 = summarize(jorge_project, jorge_payments, jorge_expenses_step4, [], [])

check("gastos_total", jorge_result_step4["gastos_total"], 3679.30)
check("utilidad_bruta", jorge_result_step4["utilidad_bruta"], 6640.70)
check("iva_a_pagar", jorge_result_step4["iva_a_pagar"], 0.00)
check("utilidad_neta", jorge_result_step4["utilidad_neta"], 6640.70)
check("by_category.equipo.costo_total", jorge_result_step4["by_category"]["equipo"]["costo_total"], 3679.30)
check("by_category.equipo.pagado", jorge_result_step4["by_category"]["equipo"]["pagado"], 3679.30)


# ── Step 5 — Mano de obra / adelantos ────────────────────────────────────────
# Worker "Cuadrilla instalación", cotización $1,380.00, two adelantos of
# $460.00 each -> total_advanced $920.00, saldo pendiente $460.00.
# PLAN_PHASE6.md Step 5 validation.

section("Step 5 — Mano de obra (labor_balance + Presupuesto wiring)")

cuadrilla_labor = {"quoted_amount": 1380.00, "total_advanced": 920.00}
check("labor_balance", labor_balance(cuadrilla_labor), 460.00)

# Extend the Step 4 fixture (Jorge + Equipo expense $3,679.30) with this
# labor row, to assert utilidad_bruta drops by exactly $920.00 more than
# the Step 4 figure ($6,640.70 -> $5,720.70), and that the labor cost is
# picked up by the mano_de_obra rubro (§1.6) without a second write path.
jorge_labor_step5 = [cuadrilla_labor]
jorge_result_step5 = summarize(
    jorge_project, jorge_payments, jorge_expenses_step4, jorge_labor_step5, [],
)

check("gastos_total", jorge_result_step5["gastos_total"], 4599.30)
check("utilidad_bruta", jorge_result_step5["utilidad_bruta"], 5720.70)
check(
    "utilidad_bruta drops by exactly $920.00 vs Step 4",
    round(jorge_result_step4["utilidad_bruta"] - jorge_result_step5["utilidad_bruta"], 2),
    920.00,
)
check("iva_a_pagar", jorge_result_step5["iva_a_pagar"], 0.00)
check("utilidad_neta", jorge_result_step5["utilidad_neta"], 5720.70)
check(
    "by_category.mano_de_obra.costo",
    jorge_result_step5["by_category"]["mano_de_obra"]["costo"],
    920.00,
)


# ── Step 7 — Facturación (invoice_summary reconciliation view) ──────────────
# Jorge's contract ($10,320.00) plus the Step 6 extra ($500 @ 13% -> $565.00,
# supplied here as a hand-built dict with no `total_with_iva` key, to exercise
# invoice_summary()'s amount_usd * (1 + iva_rate) fallback per PLAN_PHASE22
# §1.10.4). PLAN_PHASE6.md Step 7's own hand-computed fixture (§1.10.5).

section("Step 7 — Facturación (invoice_summary + contract reconciliation)")

invoice_items_step7 = [
    {"category": "equipos", "amount_usd": 8000.00, "iva_rate": 0.0},
    {"category": "materiales", "amount_usd": 1000.00, "iva_rate": 0.13},
    {"category": "servicios", "amount_usd": 1000.00, "iva_rate": 0.13},
]
extra_step6 = {"amount_usd": 500.00, "iva_rate": 0.13}  # no total_with_iva -> fallback path
invoice_result = invoice_summary(invoice_items_step7, jorge_project, [extra_step6])

check("by_category.equipos", invoice_result["by_category"]["equipos"], {"subtotal": 8000.00, "iva": 0.00, "total": 8000.00})
check("by_category.materiales", invoice_result["by_category"]["materiales"], {"subtotal": 1000.00, "iva": 130.00, "total": 1130.00})
check("by_category.servicios", invoice_result["by_category"]["servicios"], {"subtotal": 1000.00, "iva": 130.00, "total": 1130.00})
check("subtotal", invoice_result["subtotal"], 10000.00)
check("iva", invoice_result["iva"], 260.00)
check("total_general", invoice_result["total_general"], 10260.00)
check("delta (amber, extra present)", invoice_result["delta"], -625.00)

# Empty-items case (plan item 42): zero items -> three zeroed categories, and
# with no contract/extras in play here, total_general/delta are also zero.
empty_invoice_result = invoice_summary([], {"contract_usd": 0.0}, [])
for cat in ("equipos", "materiales", "servicios"):
    check(f"empty by_category.{cat}", empty_invoice_result["by_category"][cat], {"subtotal": 0.00, "iva": 0.00, "total": 0.00})
check("empty total_general", empty_invoice_result["total_general"], 0.00)
check("empty delta", empty_invoice_result["delta"], 0.00)

# ⚠ item 40: invoice_summary() must never feed summarize() / move the P&L —
# assert the Jorge+Equipo+labor (Step 5) figures are untouched by the presence
# of invoice items above (they are computed from entirely separate inputs, so
# this is really "invoice_summary() has no side effects", not a live UI check,
# but it documents the invariant the UI-level check exercises for real).
check("utilidad_bruta unaffected by invoice_summary", jorge_result_step5["utilidad_bruta"], 5720.70)
check("iva_a_pagar unaffected by invoice_summary", jorge_result_step5["iva_a_pagar"], 0.00)
check("utilidad_neta unaffected by invoice_summary", jorge_result_step5["utilidad_neta"], 5720.70)


# ── Step 8 — ONVO (payments_summary + onvo_breakdown fixture, §1.10.5) ──────
# Jorge's Pago 1 ($7,224.00) as Transferencia (0/0) vs ONVO tarjeta
# (0.024/0.13) — PLAN_PHASE6.md Step 8's own hand-computed fixture, also the
# proof numbers for the Step-0 migration's live check. Plus the utilidad-
# invariance assertion (item 48): the two variants of the same payment must
# never move utilidad_bruta/utilidad_neta, since ONVO fees are a bank cost,
# never a revenue reduction.

section("Step 8 — ONVO (onvo_breakdown + payments_summary + invariance)")

transferencia_breakdown = onvo_breakdown(7224.00, 0.0, 0.0)
check("transferencia commission", transferencia_breakdown["commission"], 0.00)
check("transferencia iva_on_commission", transferencia_breakdown["iva_on_commission"], 0.00)
check("transferencia net_deposited", transferencia_breakdown["net_deposited"], 7224.00)

onvo_card_breakdown = onvo_breakdown(7224.00, 0.024, 0.13)
check("onvo commission", onvo_card_breakdown["commission"], 173.38)
check("onvo iva_on_commission", onvo_card_breakdown["iva_on_commission"], 22.54)
check("onvo net_deposited", onvo_card_breakdown["net_deposited"], 7028.08)

payment_transferencia = {
    "amount_usd": 7224.00, "paid": True, "onvo_commission_pct": 0.0, "onvo_iva_pct": 0.0,
}
payment_onvo = {
    "amount_usd": 7224.00, "paid": True, "onvo_commission_pct": 0.024, "onvo_iva_pct": 0.13,
}

summary_transferencia = payments_summary([payment_transferencia])
check("payments_summary transferencia gross_paid", summary_transferencia["gross_paid"], 7224.00)
check("payments_summary transferencia commission_total", summary_transferencia["commission_total"], 0.00)
check(
    "payments_summary transferencia iva_on_commission_total",
    summary_transferencia["iva_on_commission_total"], 0.00,
)
check("payments_summary transferencia net_deposited_total", summary_transferencia["net_deposited_total"], 7224.00)

summary_onvo = payments_summary([payment_onvo])
check("payments_summary onvo gross_paid", summary_onvo["gross_paid"], 7224.00)
check("payments_summary onvo commission_total", summary_onvo["commission_total"], 173.38)
check("payments_summary onvo iva_on_commission_total", summary_onvo["iva_on_commission_total"], 22.54)
check("payments_summary onvo net_deposited_total", summary_onvo["net_deposited_total"], 7028.08)

# Unpaid rows are excluded entirely, and an empty list renders an
# empty-state footer of zeros, never a crash (plan Step 8 validation, last
# bullet — the pure-function half of that check).
summary_unpaid = payments_summary([{**payment_onvo, "paid": False}])
check("payments_summary excludes unpaid gross_paid", summary_unpaid["gross_paid"], 0.00)
check("payments_summary excludes unpaid commission_total", summary_unpaid["commission_total"], 0.00)

summary_empty = payments_summary([])
check("payments_summary empty gross_paid", summary_empty["gross_paid"], 0.00)
check("payments_summary empty commission_total", summary_empty["commission_total"], 0.00)
check("payments_summary empty iva_on_commission_total", summary_empty["iva_on_commission_total"], 0.00)
check("payments_summary empty net_deposited_total", summary_empty["net_deposited_total"], 0.00)

# ⚠ item 48 — the invariance assertion: reuse the Step 5 fixture (Jorge +
# Equipo expense + Cuadrilla labor, utilidad_bruta/neta $5,720.70) with the
# same payment paid as either Transferencia or ONVO tarjeta — the fee
# variant must not move utilidad_bruta/utilidad_neta by even one cent.
result_transferencia = summarize(
    jorge_project, [payment_transferencia], jorge_expenses_step4, jorge_labor_step5, [],
)
result_onvo = summarize(
    jorge_project, [payment_onvo], jorge_expenses_step4, jorge_labor_step5, [],
)
check("invariance: utilidad_bruta (transferencia)", result_transferencia["utilidad_bruta"], 5720.70)
check("invariance: utilidad_bruta (onvo)", result_onvo["utilidad_bruta"], 5720.70)
check(
    "invariance: utilidad_bruta identical across método",
    result_transferencia["utilidad_bruta"], result_onvo["utilidad_bruta"],
)
check("invariance: utilidad_neta (transferencia)", result_transferencia["utilidad_neta"], 5720.70)
check("invariance: utilidad_neta (onvo)", result_onvo["utilidad_neta"], 5720.70)
check(
    "invariance: utilidad_neta identical across método",
    result_transferencia["utilidad_neta"], result_onvo["utilidad_neta"],
)


# ── Summary ───────────────────────────────────────────────────────────────

print()
print("=" * 60)
if _failures:
    print(f"FAILED — {len(_failures)} assertion(s) did not match:")
    for f in _failures:
        print(f"  - {f}")
    print("=" * 60)
    sys.exit(1)
else:
    print("PASSED — all assertions matched.")
    print("=" * 60)
    sys.exit(0)
