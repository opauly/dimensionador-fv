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

from calculations.project_finance import summarize, labor_balance, onvo_breakdown

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
