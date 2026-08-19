from __future__ import annotations
"""Project financial math: Presupuesto (ingresos/gastos/utilidad), labor
balance, and ONVO payment-processor breakdowns. Phase 6.

Pure module — no `database/` or `streamlit` imports — so it can be exercised
directly by `scripts/validate_phase6.py` and the tester agent with zero
setup. All rows passed in are already-fetched dicts (as returned by
`database/projects_db.py`'s list_*/get_project_bundle functions).

Formulas are PLAN_PHASE6.md §1.2 verbatim (revised 2026-08-17, migration 022):
`contract_usd` is the FULL quoted total, already including each line item's
own IVA where it applies — `contract_iva_usd` is the real dollar amount of
IVA embedded in it, and has to be stripped back out before comparing against
`gastos_base` (genuinely ex-IVA), or gross profit is overstated by exactly
the embedded tax. See `database/projects_db.py::derive_contract_terms` for
the full reasoning.

    ingresos_base   = (contract_usd - contract_iva_usd) + Σ extras.amount_usd
    iva_repercutido = contract_iva_usd + Σ (extras.amount_usd * extras.iva_rate)
    ingresos_total  = ingresos_base + iva_repercutido

    gastos_base     = Σ expenses.amount_usd + Σ labor.total_advanced
    iva_soportado   = Σ (expenses.amount_usd * expenses.iva_rate)
    gastos_total    = gastos_base + iva_soportado

    utilidad_bruta  = ingresos_base - gastos_base
    iva_a_pagar     = iva_repercutido - iva_soportado
    utilidad_neta   = utilidad_bruta - iva_a_pagar

    recibido        = Σ payments where paid = true (amount_usd)
    pendiente       = ingresos_total - recibido

Rounding: every named top-level figure is rounded to 2dp only at the very
end — never round an intermediate, or the ONVO $7,028.08 case (and others)
drift by a cent (PLAN_PHASE6.md §4 risk #7).
"""

from config import EXPENSE_CATEGORIES


def _num(value) -> float:
    """Tolerant float coercion — DB rows may carry None for optional numerics."""
    return float(value) if value is not None else 0.0


def summarize(
    project: dict,
    payments: list[dict],
    expenses: list[dict],
    labor: list[dict],
    extras: list[dict],
) -> dict:
    """Compute the Presupuesto dashboard figures for one project.

    Returns a dict with every named figure from PLAN_PHASE6.md §1.2 plus
    `by_category`, a dict keyed by every `config.EXPENSE_CATEGORIES` value
    (present even when a category has zero rows — PLAN_PHASE6.md §4 risk #6),
    each holding `{costo, iva, costo_total, pagado, presupuestado, remanente}`.
    """
    contract_usd = _num(project.get("contract_usd"))
    contract_iva_usd = _num(project.get("contract_iva_usd"))

    extras_amount_sum = sum(_num(e.get("amount_usd")) for e in extras)
    extras_iva_sum = sum(_num(e.get("amount_usd")) * _num(e.get("iva_rate")) for e in extras)

    expenses_amount_sum = sum(_num(e.get("amount_usd")) for e in expenses)
    expenses_iva_sum = sum(_num(e.get("amount_usd")) * _num(e.get("iva_rate")) for e in expenses)
    labor_advanced_sum = sum(_num(l.get("total_advanced")) for l in labor)

    ingresos_base = (contract_usd - contract_iva_usd) + extras_amount_sum
    iva_repercutido = contract_iva_usd + extras_iva_sum
    ingresos_total = ingresos_base + iva_repercutido

    gastos_base = expenses_amount_sum + labor_advanced_sum
    iva_soportado = expenses_iva_sum
    gastos_total = gastos_base + iva_soportado

    utilidad_bruta = ingresos_base - gastos_base
    iva_a_pagar = iva_repercutido - iva_soportado
    utilidad_neta = utilidad_bruta - iva_a_pagar

    recibido = sum(_num(p.get("amount_usd")) for p in payments if p.get("paid"))
    pendiente = ingresos_total - recibido

    by_category = _summarize_by_category(expenses, labor)

    return {
        "ingresos_base": round(ingresos_base, 2),
        "iva_repercutido": round(iva_repercutido, 2),
        "ingresos_total": round(ingresos_total, 2),
        "gastos_base": round(gastos_base, 2),
        "iva_soportado": round(iva_soportado, 2),
        "gastos_total": round(gastos_total, 2),
        "utilidad_bruta": round(utilidad_bruta, 2),
        "iva_a_pagar": round(iva_a_pagar, 2),
        "utilidad_neta": round(utilidad_neta, 2),
        "recibido": round(recibido, 2),
        "pendiente": round(pendiente, 2),
        "by_category": by_category,
    }


def _summarize_by_category(expenses: list[dict], labor: list[dict]) -> dict:
    """Per-rubro breakdown, all six `EXPENSE_CATEGORIES` always present.

    Mano de obra rule (PLAN_PHASE6.md §1.6 — one source of truth, no double
    counting): `project_labor` is the *only* place worker cash is recorded.
    The `mano_de_obra` rubro's `costo` is `Σ expenses[category=mano_de_obra]
    .amount_usd` (which — by design — only ever picks up the zero-amount
    budget-seed row, since the MOD tab has no expense-entry form) **plus**
    `Σ labor.total_advanced`. Do not "simplify" this to just the expenses
    sum, or worker advances silently disappear from the Presupuesto; and do
    not add a second path that writes a `mano_de_obra` expense with a
    nonzero `amount_usd` alongside real advances, or the rubro double-counts.
    """
    by_category: dict[str, dict] = {
        cat: {"costo": 0.0, "iva": 0.0, "costo_total": 0.0, "pagado": 0.0, "presupuestado": 0.0}
        for cat in EXPENSE_CATEGORIES
    }

    for e in expenses:
        cat = e.get("category")
        if cat not in by_category:
            continue
        amount = _num(e.get("amount_usd"))
        iva_rate = _num(e.get("iva_rate"))
        iva = amount * iva_rate
        row = by_category[cat]
        row["costo"] += amount
        row["iva"] += iva
        row["presupuestado"] += _num(e.get("budgeted_usd"))
        if e.get("paid"):
            row["pagado"] += amount + iva

    if "mano_de_obra" in by_category:
        by_category["mano_de_obra"]["costo"] += sum(_num(l.get("total_advanced")) for l in labor)

    for cat, row in by_category.items():
        row["costo"] = round(row["costo"], 2)
        row["iva"] = round(row["iva"], 2)
        row["costo_total"] = round(row["costo"] + row["iva"], 2)
        row["pagado"] = round(row["pagado"], 2)
        row["presupuestado"] = round(row["presupuestado"], 2)
        row["remanente"] = round(row["presupuestado"] - row["costo_total"], 2)

    return by_category


def labor_balance(row: dict) -> float:
    """Saldo pendiente for one `project_labor` row (PLAN_PHASE6.md §1.3)."""
    quoted = _num(row.get("quoted_amount"))
    advanced = _num(row.get("total_advanced"))
    return round(quoted - advanced, 2)


def onvo_breakdown(amount_usd: float, commission_pct: float, iva_pct: float) -> dict:
    """ONVO (or transferencia) payment fee breakdown (PLAN_PHASE6.md §1.4).

    IVA is charged on the commission, not on the payment. Round the
    commission first, then compute IVA on the *rounded* commission —
    deterministic, and matches how a processor statement actually reads.
    Bank transfers pass `commission_pct=0, iva_pct=0` → `net_deposited ==
    amount_usd`. These fees never reduce `ingresos` — they are a bank cost,
    tracked separately as an optional `project_expenses` row with
    `category='banco'` (see the ONVO tab, Step 8).
    """
    amount_usd = _num(amount_usd)
    commission = round(amount_usd * _num(commission_pct), 2)
    iva = round(commission * _num(iva_pct), 2)
    net = round(amount_usd - commission - iva, 2)
    return {
        "gross": amount_usd,
        "commission": commission,
        "iva_on_commission": iva,
        "net_deposited": net,
    }
