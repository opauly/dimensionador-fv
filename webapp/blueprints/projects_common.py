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

Step 3 ("Detail shell + Presupuesto tab, read-only") adds this module's other
load-bearing piece: `detail_ctx(pid)`, the one context builder every route on
`/proyectos/<pid>...` renders from (full-page GET and, from Step 4 on, every
write route's re-render) — same discipline as
`maintenance_detail.detail_ctx()` (Phase 21) and `maintenance_common.
property_rows()`. `TAB_SPECS`/`TAB_KEYS`/`tab_url()` are the tab-routing
vocabulary `webapp/blueprints/projects.py`'s GET dispatch and `_header.html`'s
status-pill redirect both read, so the tab order and URLs are declared once.
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

# Same nine tabs, keyed for routing (`detail_ctx()`/`tab_url()` below and
# `webapp/blueprints/projects.py`'s tab-dispatch routes). "category" is set
# for the five tabs backed by the shared expense-ledger renderer (Step 5) —
# it is what `GET /<pid>/gastos/<categoria>` validates against and what a
# ledger row's own `category` column carries. Order matches TAB_LABELS/
# `pages/04_project_detail.py` L30-33 exactly; do not reorder.
TAB_SPECS = [
    {"key": "presupuesto", "label": "Presupuesto"},
    {"key": "banco", "label": "Banco", "category": "banco"},
    {"key": "equipo", "label": "Equipo", "category": "equipo"},
    {"key": "materiales", "label": "Materiales", "category": "materiales"},
    {"key": "mano_de_obra", "label": "Mano de obra"},
    {"key": "viaticos", "label": "Viáticos", "category": "viaticos"},
    {"key": "extras", "label": "Extras (gastos)", "category": "extras"},
    {"key": "facturacion", "label": "Facturación"},
    {"key": "pagos", "label": "Pagos"},
]
TAB_KEYS = [t["key"] for t in TAB_SPECS]
LEDGER_TAB_CATEGORIES = {t["category"] for t in TAB_SPECS if "category" in t}


def tab_url(pid: str, key: str) -> str:
    """The URL for one detail-page tab — the only place this section
    translates a tab key into an `url_for()` call, so
    `projects.py`'s GET dispatch, `_header.html`'s status-pill redirect
    target and `page.html`'s tab bar can never point at three different
    URLs for the same tab."""
    from flask import url_for

    if key not in TAB_KEYS:
        key = "presupuesto"
    if key == "presupuesto":
        return url_for("projects.detalle", pid=pid)
    if key == "mano_de_obra":
        return url_for("projects.mano_de_obra", pid=pid)
    if key == "facturacion":
        return url_for("projects.facturacion", pid=pid)
    if key == "pagos":
        return url_for("projects.pagos", pid=pid)
    return url_for("projects.gastos", pid=pid, categoria=key)

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


# ── Presupuesto tab figures — the only other money math on this page,
#    computed here (never in a route, never in a template) per plan §1.3
#    rules 2/3/5. Both figures `summarize()` deliberately leaves out —
#    the INGRESOS extras card and each ledger's own TOTAL — are computed
#    once, in Python, exactly where Streamlit computes them
#    (pages/04_project_detail.py L117, L389). ─────────────────────────────
def _presupuesto_ctx(bundle: dict, result: dict) -> dict:
    from config import EXPENSE_CATEGORIES

    project = bundle["project"]
    extras_amount_sum = sum(float(e.get("amount_usd") or 0) for e in bundle["extras"])

    ingresos_cards = [
        {"label": "Monto del contrato", "value": fmt_usd(project.get("contract_usd")), "navy_border": False},
        {"label": "IVA incluido", "value": fmt_usd(project.get("contract_iva_usd")), "navy_border": False},
        {"label": "Extras (órdenes adicionales)", "value": fmt_usd(extras_amount_sum), "navy_border": False},
        {"label": "Gran total", "value": fmt_usd(result["ingresos_total"]), "navy_border": True},
    ]

    # Step 4: each row now carries its `id` (for the per-row Guardar form's
    # POST target) alongside the read-only display fields Step 3 already had.
    payment_rows = [
        {
            "id": p.get("id"),
            "payment_number": p.get("payment_number"),
            "amount_str": fmt_usd(p.get("amount_usd")),
            "paid": bool(p.get("paid")),
            "paid_date": p.get("paid_date") or "",
            "bank_account": p.get("bank_account") or "",
        }
        for p in bundle["payments"]
    ]

    # ⚠ plan §1.4 item 17: "+ Agregar pago"'s `Pago #` field defaults to
    # `max(existing payment_number) + 1` — 1 when there are none yet.
    existing_numbers = [p.get("payment_number") or 0 for p in bundle["payments"]]
    next_payment_number = (max(existing_numbers) + 1) if existing_numbers else 1

    # ⚠ plan §1.4 item 18: 0.0, never a divide-by-zero, when ingresos_total
    # is falsy. `result["recibido"]`/`ingresos_total"]` are the only inputs —
    # never a second sum over `bundle["payments"]` (§1.3 rule 7).
    ingresos_total = result["ingresos_total"]
    pct_recibido = (result["recibido"] / ingresos_total * 100) if ingresos_total else 0.0
    recibido_line = (
        f"Recibido {fmt_usd(result['recibido'])} de {fmt_usd(ingresos_total)} "
        f"({fmt_pct(pct_recibido)})"
    )

    by_category = result["by_category"]
    gastos_rows = [
        {
            "label": RUBRO_LABELS.get(cat, cat),
            "costo": fmt_usd(by_category.get(cat, {}).get("costo")),
            "iva": fmt_usd(by_category.get(cat, {}).get("iva")),
            "costo_total": fmt_usd(by_category.get(cat, {}).get("costo_total")),
            "pagado": fmt_usd(by_category.get(cat, {}).get("pagado")),
            "presupuestado": fmt_usd(by_category.get(cat, {}).get("presupuestado")),
            "remanente": fmt_usd(by_category.get(cat, {}).get("remanente")),
        }
        for cat in EXPENSE_CATEGORIES
    ]

    def _utilidad_card(label: str, value: float) -> dict:
        is_positive = value >= 0
        return {
            "label": label,
            "value": fmt_usd(value),
            "color": "#4BAE6A" if is_positive else "#dc2626",
            "bg": "#e8f5ee" if is_positive else "#fee2e2",
        }

    iva_a_pagar = result["iva_a_pagar"]
    # ⚠ plan §1.4 item 20: label switches when iva_a_pagar < 0.
    iva_label = "IVA a pagar" if iva_a_pagar >= 0 else "Crédito IVA (a favor)"
    utilidad_cards = [
        _utilidad_card("Utilidad bruta", result["utilidad_bruta"]),
        _utilidad_card(iva_label, iva_a_pagar),
        _utilidad_card("Utilidad neta", result["utilidad_neta"]),
    ]

    return {
        "ingresos_cards": ingresos_cards,
        "payment_rows": payment_rows,
        "next_payment_number": next_payment_number,
        "recibido_line": recibido_line,
        "gastos_rows": gastos_rows,
        "utilidad_cards": utilidad_cards,
    }


def detail_ctx(project_id: str, active_tab: str = "presupuesto") -> dict | None:
    """The one function every Proyectos detail-page route renders from,
    including after a mutation (plan §1.3): one `get_project_bundle()` call,
    one `summarize()` call, and every header/label/Presupuesto figure
    derived from that single pair of calls — no route or template
    recomputes any of it.

    Returns `None` when `project_id` doesn't resolve to a row — the "Proyecto
    no encontrado." state (pages/04_project_detail.py L590). Lets any
    exception `get_project_bundle()` raises propagate to the caller, which
    renders it as "Error cargando proyecto: {e}" (L585) — same two-state
    shape as the Streamlit page, deliberately not collapsed into one.
    """
    from calculations.project_finance import summarize
    from config import PROJECT_STATUSES, SYSTEM_TYPE_LABELS
    from database.projects_db import get_project_bundle

    bundle = get_project_bundle(project_id)
    project = bundle.get("project")
    if not project:
        return None

    result = summarize(
        project, bundle["payments"], bundle["expenses"], bundle["labor"], bundle["extras"],
    )

    status = project.get("status") or "active"
    if active_tab not in TAB_KEYS:
        active_tab = "presupuesto"

    ctx = {
        "project": project,
        "bundle": bundle,
        "result": result,
        "client_name": project.get("client_name") or "Sin nombre",
        "sys_label": SYSTEM_TYPE_LABELS.get(project.get("system_type", ""), "—"),
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "contract_str": fmt_usd(project.get("contract_usd")),
        "status_options": [(s, STATUS_LABELS.get(s, s), s == status) for s in PROJECT_STATUSES],
        "proposal_caption": (
            f"Promovido desde cotización — proposal_id {project['proposal_id']}"
            if project.get("proposal_id") else None
        ),
        "active_tab": active_tab,
        "tabs": [{"key": t["key"], "label": t["label"], "url": tab_url(project_id, t["key"])} for t in TAB_SPECS],
    }
    ctx.update(_presupuesto_ctx(bundle, result))
    return ctx
