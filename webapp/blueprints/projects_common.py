from __future__ import annotations
"""Shared constants and helpers for the Proyectos section (Phase 22) —
labels, badge colors, filter/tab vocabulary and money-formatting wrappers
used by every module registered onto `webapp.blueprints.projects.bp`.

⚠ Invariant this module exists to protect (plan §1.3, restated here because
every later Phase 22 step depends on it): **every money or status figure the
Proyectos pages show comes from exactly one function of truth, called once
per render, and nothing downstream recomputes it independently.**
`calculations.project_finance.summarize()` is that function for every P&L
figure on the Presupuesto tab (and, once Steps 7-8 exist, `invoice_summary()`
/ `payments_summary()` / `onvo_breakdown()` play the same role for
Facturación and Pagos). This module's own job is smaller but the same in
kind: `STATUS_LABELS`, `STATUS_BADGE`, `RUBRO_LABELS`, `INVOICE_CATEGORY_LABELS`
and the filter/tab tables below are copied verbatim from
`pages/03_projects.py` / `pages/04_project_detail.py` exactly once, here —
no other module in this section is allowed to re-declare or re-derive any of
them. `fmt_usd`/`fmt_pct` are thin wrappers over `utils/formatting.py` so
every panel formats money the same way; no template ever does money
arithmetic (plan §1.3 rule 2) or reimplements a label/color/percent lookup
that belongs in this file.
"""
from utils import formatting as _fmt

# ── Status labels / badges — verbatim from pages/03_projects.py L14-25 and
#    pages/04_project_detail.py L14-19 (the two pages define the same dict
#    independently; this module is the single Flask-side copy of it) ──────────
STATUS_LABELS = {
    "active": "Activo",
    "completed": "Completado",
    "paused": "Pausado",
    "cancelled": "Cancelado",
}

STATUS_BADGE = {
    "active": ("Activo", "#dcfce7", "#16a34a"),
    "completed": ("Completado", "#dbeafe", "#1d4ed8"),
    "paused": ("Pausado", "#fef9c3", "#a16207"),
    "cancelled": ("Cancelado", "#fee2e2", "#dc2626"),
}

# ── Projects-list status filter — verbatim from pages/03_projects.py L26-33 ──
FILTER_OPTIONS = ["Todos", "Activos", "Completados", "Pausados", "Cancelados"]
FILTER_MAP = {
    "Todos": None,
    "Activos": "active",
    "Completados": "completed",
    "Pausados": "paused",
    "Cancelados": "cancelled",
}

# ── Expense-ledger rubro labels — verbatim from pages/04_project_detail.py
#    L21-28. Order matches config.EXPENSE_CATEGORIES; used both for the GASTOS
#    table rows (plan §1.3 rule 4) and each ledger's section heading (item 27) ──
RUBRO_LABELS = {
    "banco": "Banco",
    "equipo": "Equipo",
    "materiales": "Materiales",
    "mano_de_obra": "Mano de obra",
    "viaticos": "Viáticos",
    "extras": "Extras",
}

# ── Detail-page tab order — verbatim from pages/04_project_detail.py L30-33.
#    "Extras (gastos)" keeps its parenthetical suffix here — it is a tab
#    label, distinct from RUBRO_LABELS["extras"] ("Extras") used on the
#    ledger's own section heading (plan §1.4 item 12 vs item 27). ────────────
TAB_LABELS = [
    "Presupuesto", "Banco", "Equipo", "Materiales", "Mano de obra",
    "Viáticos", "Extras (gastos)", "Facturación", "Pagos",
]

# ── Facturación category labels — new construction (§1.10.1); config.py has
#    no label dict for config.INVOICE_CATEGORIES, so this is the one place
#    Step 7 (and this step, since the module is built now) defines it. Order
#    matches config.INVOICE_CATEGORIES and PLAN_PHASE6.md Step 7's fixture
#    ("Equipos" / "Materiales" / "Servicios"). ───────────────────────────────
INVOICE_CATEGORY_LABELS = {
    "equipos": "Equipos",
    "materiales": "Materiales",
    "servicios": "Servicios",
}

# IVA sobre comisión — always 13%, the standard Costa Rican rate applied to
# the ONVO commission itself (PLAN_PHASE6.md §1.4 / REQUIREMENTS.md §5.6).
# Not in config.py: it is not a general-purpose IVA rate like
# config.DEFAULT_IVA_RATE, it is specific to this one screen's commission
# math, and putting it here keeps every Pagos/ONVO constant in one module.
ONVO_IVA_PCT = 0.13

# ── IVA-rate <-> label round trip — copied verbatim from
#    pages/04_project_detail.py L276-287 (§1.8: the only Streamlit-side logic
#    small enough to copy rather than import; that page stays untouched). ───
IVA_OPTIONS = ["0%", "13%"]


def iva_rate_to_label(rate) -> str:
    try:
        return f"{int(round(float(rate or 0) * 100))}%"
    except (TypeError, ValueError):
        return "0%"


def iva_label_to_rate(label) -> float:
    try:
        return float(str(label or "0%").rstrip("%")) / 100
    except (TypeError, ValueError):
        return 0.0


# ── Money/percent formatting — thin wrappers so every Proyectos template
#    formats the same way, per §1.3 rule 3 (`fmt_usd(None)` -> "—";
#    `fmt_pct` takes 0-100, not 0-1). No template computes these itself. ─────
def fmt_usd(amount) -> str:
    return _fmt.fmt_usd(amount)


def fmt_pct(amount, decimals: int = 2) -> str:
    return _fmt.fmt_pct(amount, decimals=decimals)
