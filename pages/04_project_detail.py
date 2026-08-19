"""Project detail: Presupuesto + all ledger tabs. Phase 6."""
from __future__ import annotations
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Proyecto — Pauly&Co Solar", layout="wide")

from config import (
    BRAND_NAVY, BRAND_GREEN, EXPENSE_CATEGORIES, PROJECT_STATUSES, SYSTEM_TYPE_LABELS,
)
from utils.formatting import fmt_usd, fmt_pct

STATUS_LABELS = {
    "active":    "Activo",
    "completed": "Completado",
    "paused":    "Pausado",
    "cancelled": "Cancelado",
}

RUBRO_LABELS = {
    "banco":         "Banco",
    "equipo":        "Equipo",
    "materiales":    "Materiales",
    "mano_de_obra":  "Mano de obra",
    "viaticos":      "Viáticos",
    "extras":        "Extras",
}

TABS = [
    "Presupuesto", "Banco", "Equipo", "Materiales", "Mano de obra",
    "Viáticos", "Extras (gastos)", "Facturación", "Pagos",
]

# Tab index -> EXPENSE_CATEGORIES value, for the five tabs backed by the
# shared _render_expense_ledger() renderer (Step 4). Mano de obra (4) is
# built in Step 5 (_render_labor_tab, below) — it does NOT go through
# _render_expense_ledger, since project_labor is a separate table with no
# expense-entry path (§1.6). Facturación (7) and Pagos (8) are Steps 7/8 —
# left as placeholders here.
_LEDGER_TABS: list[tuple[int, str]] = [
    (1, "banco"),
    (2, "equipo"),
    (3, "materiales"),
    (5, "viaticos"),
    (6, "extras"),
]
_LABOR_TAB_INDEX = 4

_CSS = """
<style>
[data-testid="column"] {
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
[data-testid="stHorizontalBlock"] {
    gap: 8px !important;
    align-items: center !important;
}
div[data-testid="stPills"] button[aria-selected="true"] {
    background-color: #0f172a !important;
    color: #ffffff !important;
    border-color: #0f172a !important;
}
.pf-card {
    border-left: 4px solid #4BAE6A;
    background: #f8f9fa;
    border-radius: 6px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 4px;
}
.pf-card .pf-label { font-weight: 600; font-size: 0.82rem; color: #475569; }
.pf-card .pf-value { font-size: 1.3rem; font-weight: 700; margin-top: 2px; }
.pf-row {
    display: grid;
    grid-template-columns: 1.6fr 0.9fr 0.9fr 0.9fr 0.9fr 0.9fr 0.9fr;
    gap: 8px; align-items: center; padding: 8px 6px;
    border-bottom: 1px solid #f1f5f9; font-size: 0.82rem;
}
.pf-row-header {
    font-size: 0.68rem; font-weight: 700; color: #94a3b8;
    text-transform: uppercase; letter-spacing: 0.05em;
    border-bottom: 2px solid #e2e8f0;
}
</style>
"""


def _metric_card(label: str, value: float, positive_good: bool = True) -> str:
    is_positive = value >= 0
    color = BRAND_GREEN if is_positive else "#dc2626"
    bg = "#e8f5ee" if is_positive else "#fee2e2"
    return (
        f'<div class="pf-card" style="border-left-color:{color};background:{bg};">'
        f'<div class="pf-label">{label}</div>'
        f'<div class="pf-value" style="color:{color};">{fmt_usd(value)}</div>'
        f'</div>'
    )


# ── Presupuesto tab ─────────────────────────────────────────────────────────

def _render_presupuesto_tab(project_id: str, bundle: dict) -> None:
    from calculations.project_finance import summarize
    from database.projects_db import add_payment, update_payment

    project  = bundle["project"]
    payments = bundle["payments"]
    expenses = bundle["expenses"]
    labor    = bundle["labor"]
    extras   = bundle["extras"]

    result = summarize(project, payments, expenses, labor, extras)

    # ── INGRESOS ─────────────────────────────────────────────────────────
    st.markdown("##### Ingresos")
    extras_sum = sum(float(e.get("amount_usd") or 0) for e in extras)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="pf-card"><div class="pf-label">Monto del contrato</div>'
            f'<div class="pf-value" style="color:{BRAND_NAVY};">{fmt_usd(project.get("contract_usd"))}</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="pf-card"><div class="pf-label">IVA incluido</div>'
            f'<div class="pf-value" style="color:{BRAND_NAVY};">{fmt_usd(project.get("contract_iva_usd"))}</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="pf-card"><div class="pf-label">Extras (órdenes adicionales)</div>'
            f'<div class="pf-value" style="color:{BRAND_NAVY};">{fmt_usd(extras_sum)}</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f'<div class="pf-card" style="border-left-color:{BRAND_NAVY};">'
            f'<div class="pf-label">Gran total</div>'
            f'<div class="pf-value" style="color:{BRAND_NAVY};">{fmt_usd(result["ingresos_total"])}</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")

    # ── PAGOS ────────────────────────────────────────────────────────────
    st.markdown("##### Pagos")
    if not payments:
        st.caption("Sin pagos programados.")
    else:
        hdr_cols = st.columns([0.6, 1.1, 1.1, 1.3, 1.6, 1])
        for hdr_col, hdr_text in zip(
            hdr_cols, ["Pago", "Monto", "Pagado", "Fecha", "Cuenta bancaria", ""]
        ):
            with hdr_col:
                st.markdown(
                    f'<div style="font-size:0.68rem;font-weight:700;color:#94a3b8;'
                    f'text-transform:uppercase;letter-spacing:0.05em;">{hdr_text}</div>',
                    unsafe_allow_html=True,
                )
        for p in payments:
            pid = p["id"]
            cols = st.columns([0.6, 1.1, 1.1, 1.3, 1.6, 1])
            with cols[0]:
                st.markdown(f'<div style="font-weight:600;">Pago {p.get("payment_number")}</div>', unsafe_allow_html=True)
            with cols[1]:
                st.markdown(fmt_usd(p.get("amount_usd")), unsafe_allow_html=True)
            with cols[2]:
                paid_key = f"pf_{project_id}_pago_{pid}_paid"
                paid = st.checkbox("Pagado", value=bool(p.get("paid")), key=paid_key, label_visibility="collapsed")
            with cols[3]:
                date_key = f"pf_{project_id}_pago_{pid}_fecha"
                paid_date = st.text_input(
                    "Fecha", value=p.get("paid_date") or "", key=date_key,
                    placeholder="YYYY-MM-DD", label_visibility="collapsed",
                )
            with cols[4]:
                bank_key = f"pf_{project_id}_pago_{pid}_cuenta"
                bank_account = st.text_input(
                    "Cuenta", value=p.get("bank_account") or "", key=bank_key,
                    placeholder="Cuenta bancaria", label_visibility="collapsed",
                )
            with cols[5]:
                if st.button("Guardar", key=f"pf_{project_id}_pago_{pid}_save", use_container_width=True):
                    try:
                        update_payment(
                            pid,
                            paid=paid,
                            paid_date=paid_date or None,
                            bank_account=bank_account or None,
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    with st.expander("+ Agregar pago"):
        next_number = max([p.get("payment_number", 0) for p in payments], default=0) + 1
        np_col1, np_col2 = st.columns(2)
        with np_col1:
            new_number = st.number_input(
                "Pago #", min_value=1, value=next_number, step=1,
                key=f"pf_{project_id}_newpago_num",
            )
        with np_col2:
            new_amount = st.number_input(
                "Monto USD", min_value=0.0, step=10.0,
                key=f"pf_{project_id}_newpago_amt",
            )
        if st.button("Agregar", key=f"pf_{project_id}_newpago_confirm"):
            try:
                add_payment(project_id, int(new_number), float(new_amount))
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    ingresos_total = result["ingresos_total"]
    pct_recibido = (result["recibido"] / ingresos_total * 100) if ingresos_total else 0.0
    # st.caption renders markdown, and two literal "$" in one string (from
    # two fmt_usd() calls) makes Streamlit parse everything between them as
    # inline LaTeX math instead of plain text (same bug as the payment-
    # schedule caption in pages/01_proposals.py) — escape both.
    recibido_line = (
        f"Recibido {fmt_usd(result['recibido'])} de {fmt_usd(ingresos_total)} "
        f"({fmt_pct(pct_recibido)})"
    ).replace("$", "\\$")
    st.caption(recibido_line)

    st.write("")

    # ── GASTOS ───────────────────────────────────────────────────────────
    st.markdown("##### Gastos por rubro")
    by_category = result["by_category"]
    header_html = (
        '<div class="pf-row pf-row-header">'
        '<div>Rubro</div><div>Costo</div><div>IVA</div><div>Costo total</div>'
        '<div>Pagado</div><div>Presupuestado</div><div>Remanente</div></div>'
    )
    st.markdown(header_html, unsafe_allow_html=True)
    for cat in EXPENSE_CATEGORIES:
        row = by_category.get(cat, {})
        label = RUBRO_LABELS.get(cat, cat)
        st.markdown(
            f'<div class="pf-row">'
            f'<div style="font-weight:600;">{label}</div>'
            f'<div>{fmt_usd(row.get("costo"))}</div>'
            f'<div>{fmt_usd(row.get("iva"))}</div>'
            f'<div>{fmt_usd(row.get("costo_total"))}</div>'
            f'<div>{fmt_usd(row.get("pagado"))}</div>'
            f'<div>{fmt_usd(row.get("presupuestado"))}</div>'
            f'<div>{fmt_usd(row.get("remanente"))}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.write("")

    # ── UTILIDAD ─────────────────────────────────────────────────────────
    st.markdown("##### Utilidad")
    u1, u2, u3 = st.columns(3)
    with u1:
        st.markdown(_metric_card("Utilidad bruta", result["utilidad_bruta"]), unsafe_allow_html=True)
    with u2:
        iva_label = "IVA a pagar" if result["iva_a_pagar"] >= 0 else "Crédito IVA (a favor)"
        st.markdown(_metric_card(iva_label, result["iva_a_pagar"]), unsafe_allow_html=True)
    with u3:
        st.markdown(_metric_card("Utilidad neta", result["utilidad_neta"]), unsafe_allow_html=True)


# ── Expense ledger tabs (Banco / Equipo / Materiales / Viáticos / Extras) ──

_LEDGER_COLUMNS = ["Rubro", "Valor USD", "IVA", "Total", "Fecha", "Pagado", "Comentarios"]
_IVA_OPTIONS = ["0%", "13%"]


def _iva_rate_to_label(rate) -> str:
    try:
        return f"{int(round(float(rate or 0) * 100))}%"
    except (TypeError, ValueError):
        return "0%"


def _iva_label_to_rate(label) -> float:
    try:
        return float(str(label or "0%").rstrip("%")) / 100
    except (TypeError, ValueError):
        return 0.0


def _render_expense_ledger(project_id: str, category: str, rows: list[dict]) -> None:
    """Shared editable ledger for the Banco/Equipo/Materiales/Viáticos/Extras
    (gastos) tabs — reads/writes `project_expenses` rows for `category`.

    Edit pattern per PLAN_PHASE6.md Step 4: `st.data_editor(..., num_rows=
    "dynamic")` over a DataFrame carrying a hidden `id` column (excluded from
    display via `column_order`), plus an explicit "Guardar cambios" button
    that reads the widget's own delta-tracking state
    (`added_rows`/`edited_rows`/`deleted_rows`) rather than diffing
    DataFrames by value. `Total` (`total_with_iva`) is display-only — a
    Postgres GENERATED column, never written (§4 risk #1).
    """
    import pandas as pd
    from database.projects_db import add_expense, update_expense, delete_expense

    editor_key = f"ed_{project_id}_{category}"  # namespaced per §4 risk #8

    df = pd.DataFrame([
        {
            "id": r.get("id"),
            "Rubro": r.get("description") or "",
            "Valor USD": float(r.get("amount_usd") or 0),
            "IVA": _iva_rate_to_label(r.get("iva_rate")),
            "Total": float(r.get("total_with_iva") or 0),
            "Fecha": r.get("expense_date") or "",
            "Pagado": bool(r.get("paid")),
            "Comentarios": r.get("notes") or "",
        }
        for r in rows
    ], columns=["id", *_LEDGER_COLUMNS]) if rows else pd.DataFrame(columns=["id", *_LEDGER_COLUMNS])

    edited = st.data_editor(
        df,
        column_order=_LEDGER_COLUMNS,  # "id" stays out of the display/edit surface
        column_config={
            "Rubro": st.column_config.TextColumn(width="medium", required=True),
            "Valor USD": st.column_config.NumberColumn(min_value=0.0, format="$%.2f", width="small", default=0.0),
            "IVA": st.column_config.SelectboxColumn(options=_IVA_OPTIONS, width="small", required=True, default="0%"),
            "Total": st.column_config.NumberColumn(format="$%.2f", width="small", disabled=True,
                                                     help="Calculado automáticamente (Valor USD × (1 + IVA))."),
            "Fecha": st.column_config.TextColumn(width="small", help="YYYY-MM-DD"),
            "Pagado": st.column_config.CheckboxColumn(width="small", default=False),
            "Comentarios": st.column_config.TextColumn(width="large"),
        },
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=editor_key,
    )

    if st.button("Guardar cambios", key=f"save_{editor_key}"):
        state = st.session_state.get(editor_key) or {}
        added_rows = state.get("added_rows", [])
        edited_rows = state.get("edited_rows", {})
        deleted_rows = state.get("deleted_rows", [])

        try:
            for row_pos, changes in edited_rows.items():
                row_id = df.iloc[int(row_pos)]["id"]
                if not row_id:
                    continue
                payload = {}
                if "Rubro" in changes:
                    payload["description"] = changes["Rubro"]
                if "Valor USD" in changes:
                    payload["amount_usd"] = float(changes["Valor USD"] or 0)
                if "IVA" in changes:
                    payload["iva_rate"] = _iva_label_to_rate(changes["IVA"])
                if "Fecha" in changes:
                    payload["expense_date"] = changes["Fecha"] or None
                if "Pagado" in changes:
                    payload["paid"] = bool(changes["Pagado"])
                if "Comentarios" in changes:
                    payload["notes"] = changes["Comentarios"] or None
                if payload:
                    update_expense(row_id, **payload)

            for row_pos in deleted_rows:
                row_id = df.iloc[int(row_pos)]["id"]
                if row_id:
                    delete_expense(row_id)

            for new_row in added_rows:
                description = (new_row.get("Rubro") or "").strip()
                if not description:
                    continue  # blank added row (e.g. accidental "+") — nothing to persist
                add_expense(
                    project_id, category, description,
                    float(new_row.get("Valor USD") or 0),
                    iva_rate=_iva_label_to_rate(new_row.get("IVA")),
                    paid=bool(new_row.get("Pagado") or False),
                    expense_date=new_row.get("Fecha") or None,
                    notes=new_row.get("Comentarios") or None,
                )

            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

    total_with_iva = sum(float(r.get("total_with_iva") or 0) for r in rows)
    # Only one $ figure in this line — safe as plain st.markdown, but build
    # via HTML anyway for visual consistency with the rest of the tab (§4 risk #9).
    st.markdown(
        f'<p style="text-align:right;font-weight:700;color:{BRAND_NAVY};margin-top:4px;">'
        f'TOTAL: {fmt_usd(total_with_iva)}</p>',
        unsafe_allow_html=True,
    )


# ── Mano de obra tab (Step 5) ────────────────────────────────────────────

def _render_labor_tab(project_id: str, labor: list[dict]) -> None:
    """One card per `project_labor` row: nombre/rol/cotización, its adelantos
    (jsonb array), total adelantado, and saldo pendiente (`labor_balance()`).

    Per PLAN_PHASE6.md §1.6, this tab has NO expense-entry form — the only
    way to record labor cash is an adelanto on a worker row, which is what
    keeps the Presupuesto's `mano_de_obra` rubro from double counting (see
    `calculations/project_finance.py::_summarize_by_category`). Do not add
    an `add_expense(..., category="mano_de_obra")` path here.

    Every widget key is namespaced `mod_{project_id}_{labor_id}_...` (§4
    risk #8), so switching projects can't resurrect a stale card's widget
    state.
    """
    from calculations.project_finance import labor_balance
    from database.projects_db import (
        add_labor, add_advance, delete_advance, update_labor, delete_labor,
    )

    if not labor:
        st.caption("Sin trabajadores registrados.")
    else:
        for row in labor:
            labor_id = row["id"]
            worker_name = row.get("worker_name") or ""
            role = row.get("role") or ""
            quoted = float(row.get("quoted_amount") or 0)
            total_advanced = float(row.get("total_advanced") or 0)
            balance = labor_balance(row)
            advances = row.get("advances") or []
            balance_color = BRAND_GREEN if balance >= 0 else "#dc2626"

            # Built as HTML (unsafe_allow_html=True) rather than a plain
            # st.caption/st.markdown string, since this card composes three
            # money figures (cotización, total adelantado, saldo pendiente)
            # in one place — the §4 risk #9 LaTeX-math bug (2+ literal "$"
            # in a non-HTML markdown call gets partially eaten as inline
            # math). Same pattern as the Presupuesto INGRESOS cards above.
            role_suffix = f" &nbsp;·&nbsp; {role}" if role else ""
            st.markdown(
                f'<div class="pf-card">'
                f'<div class="pf-label" style="font-size:0.95rem;">{worker_name}{role_suffix}</div>'
                f'<div style="display:flex;gap:28px;margin-top:6px;flex-wrap:wrap;">'
                f'<div><div style="font-size:0.72rem;color:#94a3b8;">Cotización</div>'
                f'<div style="font-weight:700;">{fmt_usd(quoted)}</div></div>'
                f'<div><div style="font-size:0.72rem;color:#94a3b8;">Total adelantado</div>'
                f'<div style="font-weight:700;">{fmt_usd(total_advanced)}</div></div>'
                f'<div><div style="font-size:0.72rem;color:#94a3b8;">Saldo pendiente</div>'
                f'<div style="font-weight:700;color:{balance_color};">{fmt_usd(balance)}</div></div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            if advances:
                adv_hdr = st.columns([0.8, 1, 1, 0.8])
                for hdr_col, hdr_text in zip(adv_hdr, ["Adelanto", "Monto", "Fecha", ""]):
                    with hdr_col:
                        st.markdown(
                            f'<div style="font-size:0.68rem;font-weight:700;color:#94a3b8;'
                            f'text-transform:uppercase;letter-spacing:0.05em;">{hdr_text}</div>',
                            unsafe_allow_html=True,
                        )
                for adv in advances:
                    adv_number = adv.get("number")
                    adv_cols = st.columns([0.8, 1, 1, 0.8])
                    with adv_cols[0]:
                        st.markdown(str(adv_number))
                    with adv_cols[1]:
                        st.markdown(fmt_usd(adv.get("amount")))
                    with adv_cols[2]:
                        st.markdown(adv.get("date") or "—")
                    with adv_cols[3]:
                        if st.button(
                            "Eliminar",
                            key=f"mod_{project_id}_{labor_id}_adv_{adv_number}_del",
                            use_container_width=True,
                        ):
                            try:
                                delete_advance(labor_id, adv_number)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.caption("Sin adelantos registrados.")

            with st.expander("+ Adelanto", expanded=False):
                adv_c1, adv_c2 = st.columns(2)
                with adv_c1:
                    new_adv_amount = st.number_input(
                        "Monto USD", min_value=0.0, step=10.0,
                        key=f"mod_{project_id}_{labor_id}_newadv_amt",
                    )
                with adv_c2:
                    new_adv_date = st.text_input(
                        "Fecha", placeholder="YYYY-MM-DD",
                        key=f"mod_{project_id}_{labor_id}_newadv_date",
                    )
                if st.button("Agregar adelanto", key=f"mod_{project_id}_{labor_id}_newadv_confirm"):
                    try:
                        add_advance(labor_id, float(new_adv_amount), new_adv_date or None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

            with st.expander("Editar / eliminar trabajador", expanded=False):
                e1, e2, e3 = st.columns(3)
                with e1:
                    edit_name = st.text_input(
                        "Nombre", value=worker_name, key=f"mod_{project_id}_{labor_id}_edit_name",
                    )
                with e2:
                    edit_role = st.text_input(
                        "Rol", value=role, key=f"mod_{project_id}_{labor_id}_edit_role",
                    )
                with e3:
                    edit_quoted = st.number_input(
                        "Cotización USD", min_value=0.0, step=10.0, value=quoted,
                        key=f"mod_{project_id}_{labor_id}_edit_quoted",
                    )
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("Guardar cambios", key=f"mod_{project_id}_{labor_id}_edit_save"):
                        try:
                            update_labor(
                                labor_id,
                                worker_name=edit_name.strip() or worker_name,
                                role=edit_role.strip(),
                                quoted_amount=float(edit_quoted),
                            )
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                with b2:
                    if st.button(
                        "Eliminar trabajador", key=f"mod_{project_id}_{labor_id}_delete",
                    ):
                        try:
                            delete_labor(labor_id)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

            st.divider()

    with st.expander("+ Agregar trabajador"):
        n1, n2, n3 = st.columns(3)
        with n1:
            new_worker_name = st.text_input("Nombre", key=f"mod_{project_id}_newworker_name")
        with n2:
            new_role = st.text_input("Rol", key=f"mod_{project_id}_newworker_role")
        with n3:
            new_quoted = st.number_input(
                "Cotización USD", min_value=0.0, step=10.0, key=f"mod_{project_id}_newworker_quoted",
            )
        if st.button("Agregar trabajador", key=f"mod_{project_id}_newworker_confirm"):
            if not new_worker_name.strip():
                st.error("Ingresa un nombre para el trabajador.")
            else:
                try:
                    add_labor(
                        project_id, new_worker_name.strip(), float(new_quoted),
                        role=new_role.strip(),
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")


def main() -> None:
    from database.projects_db import get_project_bundle, update_project_status

    st.markdown(_CSS, unsafe_allow_html=True)

    if st.button("← Proyectos", key="p4_back"):
        st.switch_page("pages/03_projects.py")

    project_id = st.session_state.get("selected_project_id")
    if not project_id:
        st.info("Selecciona un proyecto desde la lista.")
        return

    try:
        bundle = get_project_bundle(project_id)
    except Exception as e:
        st.error(f"Error cargando proyecto: {e}")
        return

    project = bundle.get("project")
    if not project:
        st.error("Proyecto no encontrado.")
        return

    client_name = project.get("client_name") or "Sin nombre"
    sys_label   = SYSTEM_TYPE_LABELS.get(project.get("system_type", ""), "—")
    status      = project.get("status", "active")
    contract_str = fmt_usd(project.get("contract_usd"))

    st.markdown(
        f'<p style="color:{BRAND_NAVY};font-size:1.4rem;font-weight:700;margin:0 0 4px;">{client_name}</p>'
        f'<p style="color:#64748b;font-size:0.9rem;margin:0 0 8px;">'
        f'{sys_label} &nbsp;·&nbsp; Contrato {contract_str}</p>',
        unsafe_allow_html=True,
    )

    status_options = [STATUS_LABELS.get(s, s) for s in PROJECT_STATUSES]
    current_label  = STATUS_LABELS.get(status, status)
    choice = st.pills(
        "Estado", status_options, default=current_label,
        key=f"p4_status_pills_{project_id}",
        label_visibility="collapsed",
    )
    if choice and choice != current_label:
        new_status = next((s for s in PROJECT_STATUSES if STATUS_LABELS.get(s, s) == choice), None)
        if new_status:
            try:
                update_project_status(project_id, new_status)
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

    if project.get("proposal_id"):
        st.caption(f"Promovido desde cotización — proposal_id {project['proposal_id']}")

    st.write("")

    tabs = st.tabs(TABS)
    with tabs[0]:
        _render_presupuesto_tab(project_id, bundle)

    expenses = bundle.get("expenses") or []
    ledger_tab_indices = {idx for idx, _ in _LEDGER_TABS}
    for idx, category in _LEDGER_TABS:
        with tabs[idx]:
            rows = [e for e in expenses if e.get("category") == category]
            st.markdown(f"##### {RUBRO_LABELS.get(category, category)}")
            _render_expense_ledger(project_id, category, rows)

    with tabs[_LABOR_TAB_INDEX]:
        st.markdown("##### Mano de obra")
        _render_labor_tab(project_id, bundle.get("labor") or [])

    for idx in range(1, len(tabs)):
        if idx in ledger_tab_indices or idx == _LABOR_TAB_INDEX:
            continue
        with tabs[idx]:
            st.info("Disponible en el siguiente paso.")


main()
