"""Proposals list — table + inline detail panel. Phase 3+."""
from __future__ import annotations
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Cotizaciones — Pauly&Co Solar", layout="wide")

from config import BRAND_NAVY

# ── Constants ─────────────────────────────────────────────────────────────────

STATUS_LABELS = {
    "draft":     "Borrador",
    "active":    "Enviada",
    "won":       "Ganada",
    "lost":      "Perdida",
    "cancelled": "Cancelada",
}
STATUS_DOT = {
    "draft":  "#94a3b8",
    "active": "#3b82f6",
    "won":    "#22c55e",
    "lost":   "#ef4444",
}
STATUS_BADGE = {
    "draft":  ("Borrador", "#f1f5f9", "#64748b"),
    "active": ("Enviada",  "#dbeafe", "#1d4ed8"),
    "won":    ("Ganada",   "#dcfce7", "#16a34a"),
    "lost":   ("Perdida",  "#fee2e2", "#dc2626"),
}
SYSTEM_TYPE_LABELS = {
    "grid_zero": "Grid Zero",
    "off_grid":  "Off-Grid",
    "hybrid":    "Híbrido",
}
FILTER_OPTIONS = ["Todas", "Borrador", "Enviada", "Ganada", "Perdida"]
FILTER_MAP     = {"Todas": None, "Borrador": "draft", "Enviada": "active", "Ganada": "won", "Perdida": "lost"}

# Valid next states for each status — enforces a directed flow, no free-form changes.
STATUS_TRANSITIONS: dict[str, list[tuple[str, str]]] = {
    "draft":     [("active", "→ Enviada")],
    "active":    [("won", "✓ Ganada"), ("lost", "✕ Perdida"), ("cancelled", "✕ Cancelar"), ("draft", "← Borrador")],
    "won":       [],
    "lost":      [("draft", "↺ Borrador")],
    "cancelled": [("draft", "↺ Borrador")],
}

# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
<style>
/* Collapse column padding so rows are compact */
[data-testid="column"] {
    padding-top: 0 !important;
    padding-bottom: 0 !important;
}
[data-testid="column"] > [data-testid="element-container"] {
    margin-bottom: 0 !important;
    padding: 0 !important;
}
[data-testid="stMarkdownContainer"] p {
    margin: 0 !important;
    line-height: 1 !important;
}
/* Remove inter-element gap in vertical blocks */
[data-testid="stVerticalBlock"] > [data-testid="element-container"] {
    margin-bottom: 0 !important;
}
/* Compact row-selector buttons */
button[data-testid="baseButton-secondary"],
button[data-testid="baseButton-primary"] {
    min-height: 0 !important;
    height: 36px !important;
    padding: 0 10px !important;
    font-size: 0.8rem !important;
}
/* Reduce stHorizontalBlock gap */
[data-testid="stHorizontalBlock"] {
    gap: 4px !important;
    align-items: center !important;
}
/* Pills: selected = black */
div[data-testid="stPills"] button[aria-selected="true"] {
    background-color: #0f172a !important;
    color: #ffffff !important;
    border-color: #0f172a !important;
}
/* Version-row pill-style anchor (⬇ PDF download) — matches st.pills visual */
a.vrow-pill-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    height: 28px;
    padding: 0 12px;
    background: transparent;
    border: 1px solid rgba(49, 51, 63, 0.2);
    border-radius: 20px;
    color: #31333f;
    font-size: 0.8rem;
    font-weight: 400;
    text-decoration: none !important;
    cursor: pointer;
    white-space: nowrap;
    transition: border-color 0.15s, color 0.15s;
}
a.vrow-pill-btn:hover {
    border-color: #4BAE6A;
    color: #4BAE6A;
}
/* Detail-panel action buttons — brand navy instead of default Streamlit grey */
.st-key-det_continuar_wrap button {
    background-color: #1E2D54 !important;
    border-color: #1E2D54 !important;
    color: #ffffff !important;
}
.st-key-det_continuar_wrap button:hover:not(:disabled) {
    background-color: #16213f !important;
    border-color: #16213f !important;
    color: #ffffff !important;
}
.st-key-det_continuar_wrap button:disabled {
    background-color: #e2e8f0 !important;
    border-color: #e2e8f0 !important;
    color: #94a3b8 !important;
}
.st-key-det_newv_wrap button {
    background-color: transparent !important;
    border-color: #1E2D54 !important;
    color: #1E2D54 !important;
}
.st-key-det_newv_wrap button:hover:not(:disabled) {
    background-color: #eef1f6 !important;
}
.st-key-det_newv_wrap button:disabled {
    border-color: #e2e8f0 !important;
    color: #94a3b8 !important;
}
/* Detail-panel outer border — a real container, not the old open/close-div hack */
.st-key-det_panel_wrap {
    border: 1.5px solid #bfdbfe;
    border-radius: 8px;
    padding: 14px 16px 12px;
    margin: 4px 0 8px;
    background: white;
}
/* Promotion ("Mover a Proyecto") inline form — same bordered-container idiom
   as det_panel_wrap, nested one level in, so it reads as a sub-panel. */
.st-key-det_promote_wrap {
    border: 1.5px solid #bbf7d0;
    border-radius: 8px;
    padding: 12px 14px 10px;
    margin: 10px 0 4px;
    background: #f8fefb;
}
</style>
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _clear_wizard() -> None:
    keys = [k for k in list(st.session_state.keys())
            if k.startswith("wizard_")
            or (len(k) > 2 and k[0] == "w" and k[1].isdigit() and k[2] == "_")]
    for k in keys:
        del st.session_state[k]


def _open_version(proposal_id: str, version_id: str) -> None:
    _clear_wizard()
    from wizard.state import load_draft
    st.session_state["wizard_proposal_id"] = proposal_id
    st.session_state["wizard_version_id"]  = version_id
    load_draft(version_id)
    st.switch_page("pages/02_new_proposal.py")


def _new_version_from(proposal_id: str, source_version_id: str) -> None:
    from database.proposals_db import get_version, create_version
    from wizard.state import load_draft
    full_v = get_version(source_version_id)
    data   = (full_v or {}).get("data", {})
    new_v  = create_version(proposal_id, data)
    _clear_wizard()
    st.session_state["wizard_proposal_id"] = proposal_id
    st.session_state["wizard_version_id"]  = new_v["id"]
    load_draft(new_v["id"])
    st.session_state["wizard_step"] = 1
    st.switch_page("pages/02_new_proposal.py")


def _signed_url(pdf_path: str) -> str | None:
    try:
        from database.supabase_client import get_client
        resp = get_client().storage.from_("solar-tool").create_signed_url(pdf_path, 3600)
        return resp.get("signedURL") or resp.get("signedUrl")
    except Exception:
        return None


def _generate_pdf_bytes(vid: str, proposal: dict, vquote: str) -> bytes | None:
    try:
        from database.proposals_db import get_version
        from proposals.generator import generate_pdf, build_from_wizard_blob
        full_v = get_version(vid)
        blob   = (full_v or {}).get("data", {})
        lang   = blob.get("meta", {}).get("language", "es")
        # Use the date the version was locked (or created) so archived PDFs show the original date.
        raw_date = (full_v or {}).get("locked_at") or (full_v or {}).get("created_at") or ""
        if raw_date:
            p = raw_date[:10].split("-")          # "2026-07-04" → ["2026","07","04"]
            version_date = f"{p[2]}/{p[1]}/{p[0]}"  # → "04/07/2026"
        else:
            version_date = None
        data = build_from_wizard_blob(blob, proposal, vquote, version_date=version_date)
        return generate_pdf(data, proposal.get("system_type", "grid_zero"), lang)
    except Exception as e:
        st.error(f"Error generando PDF: {e}")
        return None


def _pill(label: str, bg: str, fg: str) -> str:
    return (
        f'<span style="display:inline-flex;align-items:center;height:20px;padding:0 9px;'
        f'border-radius:10px;font-size:0.7rem;font-weight:600;background:{bg};color:{fg};">'
        f'{label}</span>'
    )


def _badge(status: str) -> str:
    label, bg, fg = STATUS_BADGE.get(status, ("—", "#f1f5f9", "#64748b"))
    return _pill(label, bg, fg)


# ── Table row (HTML content column + selector button) ─────────────────────────

def _render_row(proposal: dict, is_selected: bool) -> bool:
    """Render one table row. Returns True if the selector button was clicked."""
    from database.proposals_db import format_quote_number

    pid         = proposal["id"]
    client_name = proposal.get("client_name") or "Sin nombre"
    sys_label   = SYSTEM_TYPE_LABELS.get(proposal.get("system_type", ""), "—")
    status      = proposal.get("status", "draft")
    cur_vnum    = proposal.get("current_version_number", 1)
    updated     = (proposal.get("updated_at") or "")[:10] or "—"

    versions_emb = proposal.get("proposal_versions") or []
    cur_ver = next(
        (v for v in versions_emb if v.get("version_number") == cur_vnum),
        versions_emb[-1] if versions_emb else {},
    )
    total_usd  = cur_ver.get("total_usd")
    total_str  = f"${total_usd:,.0f}" if total_usd else "—"
    quote_str  = format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), cur_vnum)
    dot_color  = STATUS_DOT.get(status, "#94a3b8")
    badge_html = _badge(status)

    bg     = "background:#eff6ff;" if is_selected else "background:white;"
    weight = "600" if total_usd else "400"

    row_html = f"""
<div style="{bg}display:grid;
  grid-template-columns:14px 1.3fr 1.9fr 0.9fr 0.9fr 0.9fr 80px;
  gap:10px;align-items:center;padding:9px 8px;
  border-bottom:1px solid #f1f5f9;border-radius:4px;">
  <div><span style="display:inline-block;width:9px;height:9px;border-radius:50%;
    background:{dot_color};"></span></div>
  <div style="font-size:0.82rem;font-weight:600;color:#1e293b;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{quote_str}</div>
  <div style="font-size:0.82rem;color:#1e293b;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{client_name}</div>
  <div style="font-size:0.78rem;color:#64748b;white-space:nowrap;">{sys_label}</div>
  <div style="font-size:0.82rem;font-weight:{weight};color:#1e293b;">{total_str}</div>
  <div style="font-size:0.76rem;color:#94a3b8;">{updated}</div>
  <div>{badge_html}</div>
</div>"""

    content_col, btn_col = st.columns([16, 1])
    with content_col:
        st.markdown(row_html, unsafe_allow_html=True)
    with btn_col:
        label = "▾" if is_selected else "›"
        return st.button(label, key=f"sel_{pid}", type="secondary", use_container_width=True)


# ── Table header ──────────────────────────────────────────────────────────────

_HEADER_HTML = """
<div style="display:grid;
  grid-template-columns:14px 1.3fr 1.9fr 0.9fr 0.9fr 0.9fr 80px;
  gap:10px;align-items:center;padding:5px 8px;
  border-bottom:2px solid #e2e8f0;margin-bottom:2px;">
  <div></div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Cotización</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Cliente</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Sistema</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Total</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Fecha</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Estado</div>
</div>"""


# ── Detail panel ──────────────────────────────────────────────────────────────

def _render_detail_panel(proposal: dict) -> None:
    from database.proposals_db import (
        list_versions, update_proposal_status, format_quote_number,
    )

    pid         = proposal["id"]
    client_name = proposal.get("client_name") or "Sin nombre"
    status      = proposal.get("status", "draft")
    sys_label   = SYSTEM_TYPE_LABELS.get(proposal.get("system_type", ""), "—")
    cur_vnum    = proposal.get("current_version_number", 1)
    quote_str   = format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), cur_vnum)

    try:
        versions = list_versions(pid)
    except Exception as e:
        st.error(f"Error cargando versiones: {e}")
        versions = []

    # Find current version for action context
    cur_ver = next((v for v in versions if v.get("version_number") == cur_vnum), versions[-1] if versions else {})
    vlocked = cur_ver.get("locked", False)
    vsent   = cur_ver.get("sent_to_client", False)
    vnote   = cur_ver.get("version_note") or ""
    vtotal  = cur_ver.get("total_usd")
    vcreated = (cur_ver.get("created_at") or "")[:10]
    vid     = cur_ver.get("id", "")
    vquote_cur = format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), cur_vnum)

    total_str = f"${vtotal:,.0f}" if vtotal else "—"
    note_str  = f"— {vnote}" if vnote else "—"

    with st.container(key="det_panel_wrap"):
        dl_state_key = f"pdf_bytes_{vid}"
        vpdf         = cur_ver.get("pdf_path")
        note_suffix  = f" · {vnote}" if vnote else ""

        # ── Layout: [title+flow col] | [b1 Continuar] [b2 Nueva] ─
        t_col, b1, b2 = st.columns([3, 1.5, 1.5])

        with t_col:
            badge_html = _badge(status)
            st.markdown(
                f'<div style="font-size:0.92rem;font-weight:700;color:#1e293b;line-height:1.4;margin-bottom:8px;">'
                f'{quote_str} &nbsp;·&nbsp; {client_name} &nbsp;·&nbsp; {sys_label}'
                f' &nbsp;{badge_html}</div>',
                unsafe_allow_html=True,
            )

            # ── Status flow: pills look distinct from the action buttons ─────
            transitions = STATUS_TRANSITIONS.get(status, [])
            if transitions:
                labels = [lbl for _, lbl in transitions]
                choice = st.pills(
                    "Estado", labels,
                    key=f"det_flow_{pid}",
                    label_visibility="collapsed",
                )
                if choice is not None:
                    next_st = next(s for s, l in transitions if l == choice)
                    try:
                        update_proposal_status(pid, next_st)
                        st.session_state.pop(f"det_flow_{pid}", None)
                        if next_st == "won":
                            prospect_id = proposal.get("prospect_id")
                            if prospect_id:
                                from database.clients_db import promote_prospect
                                try:
                                    promote_prospect(prospect_id)
                                    st.info("🎉 Propuesta ganada — cliente movido de Prospectos a Clientes.")
                                except Exception as promo_err:
                                    st.warning(f"Propuesta ganada, pero no se pudo promover el prospecto: {promo_err}")
                            else:
                                st.info("🎉 Propuesta ganada.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.markdown(
                    '<div style="font-size:0.72rem;color:#94a3b8;padding:4px 0;">Estado final</div>',
                    unsafe_allow_html=True,
                )

        # b1 — Continuar (active when unlocked) — solid navy, primary action
        with b1:
            with st.container(key="det_continuar_wrap"):
                if st.button("Continuar", key=f"det_open_{vid}",
                             disabled=vlocked, use_container_width=True):
                    _open_version(pid, vid)

        # b2 — Nueva versión (active when locked) — navy outline, secondary action
        with b2:
            with st.container(key="det_newv_wrap"):
                if st.button("Nueva versión", key=f"det_newv_{vid}",
                             disabled=not vlocked, use_container_width=True):
                    try:
                        _new_version_from(pid, vid)
                    except Exception as e:
                        st.error(f"Error: {e}")

        # ── Mover a Proyecto (won proposals only) ────────────────────────────
        if status == "won":
            _render_promotion_block(proposal, vid)

        # ── Versions ──────────────────────────────────────────────────────────
        st.markdown(
            '<div style="border-top:1px solid #e2e8f0;margin:12px 0 8px;"></div>'
            '<div style="font-size:0.68rem;font-weight:700;color:#94a3b8;'
            'text-transform:uppercase;letter-spacing:0.06em;margin-bottom:6px;">Versiones</div>',
            unsafe_allow_html=True,
        )

        if not versions:
            st.caption("Sin versiones.")
        else:
            for v in reversed(versions):
                _render_version_row_compact(v, proposal)


def _render_promotion_block(proposal: dict, vid: str) -> None:
    """Won-proposal "Mover a Proyecto" affordance — either a link to the
    already-promoted project, or an inline form to create one."""
    import pandas as pd
    from config import EXPENSE_CATEGORIES
    from database.projects_db import (
        get_project_by_proposal, promote_to_project,
        derive_contract_terms, derive_budget_rows, payment_schedule_for_preset,
    )
    from database.proposals_db import get_version

    pid = proposal["id"]

    try:
        existing_project = get_project_by_proposal(pid)
    except Exception as e:
        st.error(f"Error verificando proyecto: {e}")
        return

    if existing_project:
        if st.button("Ver proyecto →", key=f"det_view_project_{pid}"):
            st.session_state["selected_project_id"] = existing_project["id"]
            st.switch_page("pages/04_project_detail.py")
        return

    open_key = f"det_promote_open_{pid}"
    if not st.session_state.get(open_key):
        if st.button("Mover a Proyecto", key=f"det_promote_btn_{pid}"):
            st.session_state[open_key] = True
            st.rerun()
        return

    with st.container(key="det_promote_wrap"):
        st.markdown(
            '<div style="font-size:0.82rem;font-weight:700;color:#166534;margin-bottom:8px;">'
            'Mover a Proyecto</div>',
            unsafe_allow_html=True,
        )

        try:
            version = get_version(vid)
        except Exception as e:
            st.error(f"Error cargando versión: {e}")
            return

        derived = derive_contract_terms(version)
        seeded_rows = derive_budget_rows(version)

        c1, c2 = st.columns(2)
        with c1:
            contract_usd = st.number_input(
                "Monto del contrato (USD, según cotización)",
                min_value=0.0, value=float(derived["contract_usd"]), step=10.0,
                key=f"promo_contract_{pid}",
                help="El total cotizado — ya incluye el IVA de cada renglón que corresponde "
                     "(equipos exentos, mano de obra/materiales/servicios al 13%, etc.). "
                     "El desglose por renglón se factura en la pestaña Facturación del proyecto.",
            )
        with c2:
            contract_iva_usd = st.number_input(
                "IVA incluido en el contrato (USD)",
                min_value=0.0, value=float(derived["contract_iva_usd"]), step=10.0,
                key=f"promo_iva_{pid}",
                help="Monto de IVA ya incluido en el total de arriba (tomado de los renglones "
                     "de la cotización con IVA — equipos suelen ser exentos, mano de obra/"
                     "materiales/servicios suelen llevar 13%). Se usa para calcular la utilidad "
                     "neta sin IVA en el Presupuesto del proyecto — no cambia el monto del "
                     "contrato ni el esquema de pagos.",
            )

        st.caption("Mapeo de presupuesto por rubro — editable antes de confirmar")
        budget_df = pd.DataFrame([
            {"Concepto": r["description"], "Rubro": r["category"], "Presupuesto USD": r["budgeted_usd"]}
            for r in seeded_rows
        ]) if seeded_rows else pd.DataFrame(columns=["Concepto", "Rubro", "Presupuesto USD"])

        edited_budget = st.data_editor(
            budget_df,
            column_config={
                "Rubro": st.column_config.SelectboxColumn(options=EXPENSE_CATEGORIES, required=True),
                "Presupuesto USD": st.column_config.NumberColumn(format="$%.2f"),
            },
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key=f"promo_budget_editor_{pid}",
        )

        budget_total = float(edited_budget["Presupuesto USD"].fillna(0).sum()) if not edited_budget.empty else 0.0
        st.caption(
            f"Presupuesto de costos (rubros, sin IVA por renglón): {budget_total:,.2f} USD  ·  "
            f"Monto del contrato (cotizado): {contract_usd:,.2f} USD — "
            "no son el mismo concepto: el presupuesto es costo estimado, el contrato es el precio "
            "cotizado al cliente."
        )

        preset = st.radio(
            "Esquema de pagos", ["70/30", "50/40/10", "Personalizado"],
            index=0, horizontal=True, key=f"promo_preset_{pid}",
        )

        total_with_iva = round(contract_usd, 2)  # already the full total — §1.5

        if preset == "Personalizado":
            custom_seed = payment_schedule_for_preset(total_with_iva, "70/30")
            custom_df = pd.DataFrame([
                {"Pago #": r["payment_number"], "Monto USD": r["amount_usd"]} for r in custom_seed
            ])
            edited_schedule = st.data_editor(
                custom_df,
                column_config={"Monto USD": st.column_config.NumberColumn(format="$%.2f")},
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                key=f"promo_schedule_editor_{pid}",
            )
            payment_schedule = [
                {"payment_number": int(r["Pago #"]), "amount_usd": float(r["Monto USD"])}
                for _, r in edited_schedule.iterrows()
                if r["Monto USD"] is not None
            ]
        else:
            payment_schedule = payment_schedule_for_preset(total_with_iva, preset)
            st.caption(
                " · ".join(
                    f"Pago {r['payment_number']}: \\${r['amount_usd']:,.2f}" for r in payment_schedule
                )
            )

        bcol1, bcol2 = st.columns([1, 1])
        with bcol1:
            if st.button("Confirmar", key=f"promo_confirm_{pid}", type="primary", use_container_width=True):
                budget_rows = [
                    {
                        "description": r["Concepto"],
                        "category": r["Rubro"],
                        "budgeted_usd": float(r["Presupuesto USD"] or 0),
                    }
                    for _, r in edited_budget.iterrows()
                    if r.get("Concepto")
                ]
                try:
                    project = promote_to_project(
                        pid, vid, contract_usd,
                        contract_iva_usd=contract_iva_usd,
                        budget_rows=budget_rows,
                        payment_schedule=payment_schedule,
                    )
                    st.session_state.pop(open_key, None)
                    st.success(f"Proyecto creado para {proposal.get('client_name')}.")
                    st.session_state["selected_project_id"] = project["id"]
                    st.switch_page("pages/04_project_detail.py")
                except Exception as e:
                    st.error(f"Error: {e}")
        with bcol2:
            if st.button("Cancelar", key=f"promo_cancel_{pid}", use_container_width=True):
                st.session_state.pop(open_key, None)
                st.rerun()


def _render_version_row_compact(v: dict, proposal: dict) -> None:
    from database.proposals_db import format_quote_number

    vid      = v["id"]
    vnum     = v["version_number"]
    vcreated = (v.get("created_at") or "")[:10]
    vlocked  = v.get("locked", False)
    vsent    = v.get("sent_to_client", False)
    vnote    = v.get("version_note") or ""
    vtotal   = v.get("total_usd")
    vpdf     = v.get("pdf_path")
    vquote   = format_quote_number(proposal.get("quote_number"), proposal.get("created_at", ""), vnum)

    vtotal_str   = f"${vtotal:,.0f}" if vtotal else "—"
    lock_badge   = _pill("Bloqueada", "#f1f5f9", "#64748b") if vlocked else _pill("Borrador", "#fef9c3", "#a16207")
    sent_badge   = " " + _pill("Enviada", "#dbeafe", "#1d4ed8") if vsent else ""
    note_html    = f'<div style="font-size:0.7rem;color:#94a3b8;margin-top:2px;">{vnote}</div>' if vnote else ""
    dl_state_key = f"pdf_bytes_{vid}"

    rc1, rc2, _gap, rc3 = st.columns([3, 1, 0.25, 0.9])
    with rc1:
        st.markdown(
            f'<div style="font-size:0.78rem;font-weight:600;color:#1e293b;padding:3px 0;">{vquote}</div>'
            f'<div style="padding:2px 0;">{lock_badge}{sent_badge}</div>'
            f'{note_html}',
            unsafe_allow_html=True,
        )
    with rc2:
        st.markdown(
            f'<div style="font-size:0.82rem;font-weight:600;color:#0d9488;text-align:right;padding:4px 0;">{vtotal_str}</div>'
            f'<div style="font-size:0.7rem;color:#94a3b8;text-align:right;">{vcreated}</div>',
            unsafe_allow_html=True,
        )
    with rc3:
        if vlocked:
            if vpdf:
                url = _signed_url(vpdf)
                if url:
                    st.markdown(
                        f'<a href="{url}" target="_blank" rel="noopener" class="vrow-pill-btn">PDF</a>',
                        unsafe_allow_html=True,
                    )
            elif dl_state_key in st.session_state:
                import base64 as _b64
                b64 = _b64.b64encode(st.session_state[dl_state_key]).decode()
                st.markdown(
                    f'<a href="data:application/pdf;base64,{b64}" download="{vquote}.pdf"'
                    f' class="vrow-pill-btn">PDF</a>',
                    unsafe_allow_html=True,
                )
            else:
                choice = st.pills("", ["Generar PDF"], key=f"v_gen_{vid}",
                                  label_visibility="collapsed")
                if choice is not None:
                    st.session_state.pop(f"v_gen_{vid}", None)
                    with st.spinner("Generando…"):
                        pdf = _generate_pdf_bytes(vid, proposal, vquote)
                    if pdf:
                        st.session_state[dl_state_key] = pdf
                    st.rerun()

    st.markdown('<div style="border-top:1px solid #f1f5f9;margin:4px 0;"></div>', unsafe_allow_html=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    from database.proposals_db import list_proposals

    st.markdown(_CSS, unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────────────────
    hcol, bcol = st.columns([5, 1])
    with hcol:
        st.markdown(
            f'<p style="color:{BRAND_NAVY};font-size:1.4rem;font-weight:700;margin:0 0 8px;">Cotizaciones</p>',
            unsafe_allow_html=True,
        )
    with bcol:
        if st.button("Nueva cotización", type="primary", key="p1_new",
                     use_container_width=True):
            _clear_wizard()
            st.switch_page("pages/02_new_proposal.py")

    # ── Search + filter ───────────────────────────────────────────────────────
    search_col, pill_col = st.columns([2, 3])
    with search_col:
        query = st.text_input(
            "Buscar",
            placeholder="🔍  Cliente, número de cotización…",
            label_visibility="collapsed",
            key="p1_search",
        )
    with pill_col:
        sel_filter = st.pills(
            "Filtro", FILTER_OPTIONS,
            default="Todas",
            key="p1_filter_pills",
            label_visibility="collapsed",
        ) or "Todas"

    filter_status = FILTER_MAP.get(sel_filter)

    # ── Load + filter ─────────────────────────────────────────────────────────
    try:
        proposals = list_proposals(status=filter_status)
    except Exception as e:
        st.error(f"Error cargando cotizaciones: {e}")
        return

    q = (query or "").strip().lower()
    if q:
        proposals = [
            p for p in proposals
            if q in (p.get("client_name") or "").lower()
            or q in str(p.get("quote_number") or "").lower()
        ]

    if not proposals:
        st.info("No hay cotizaciones. Crea una nueva con el botón de arriba.")
    else:
        st.caption(f"{len(proposals)} cotización(es)")
        st.write("")

        # ── Table ─────────────────────────────────────────────────────────────
        # Header spans 16/17 of the width (matching the content_col in _render_row)
        hdr_col, _ = st.columns([16, 1])
        with hdr_col:
            st.markdown(_HEADER_HTML, unsafe_allow_html=True)

        selected_pid = st.session_state.get("p1_selected_pid")

        for proposal in proposals:
            pid         = proposal["id"]
            is_selected = pid == selected_pid

            clicked = _render_row(proposal, is_selected)
            if clicked:
                st.session_state["p1_selected_pid"] = None if is_selected else pid
                st.rerun()

            if is_selected:
                _render_detail_panel(proposal)

    st.write("")
    st.write("")
    _render_test_pdf_panel()


def _render_test_pdf_panel() -> None:
    """Discreet dev tool: generate a sample PDF per system type without going through the wizard."""
    with st.expander("Generar PDF de prueba", expanded=False):
        from proposals.generator import generate_pdf, MARIA_JOSE_DATA, JORGE_RAMIREZ_DATA, HYBRID_DATA

        sample_data = {
            "Grid Zero": ("grid_zero", MARIA_JOSE_DATA, "muestra_grid_zero"),
            "Off-Grid":  ("off_grid",  JORGE_RAMIREZ_DATA, "muestra_off_grid"),
            "Híbrido":   ("hybrid",    HYBRID_DATA, "muestra_hibrido"),
        }
        sys_label = st.radio("Tipo de sistema", list(sample_data.keys()), horizontal=True, key="p1_test_pdf_type")
        system_type, data, filename_base = sample_data[sys_label]

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Generar — Español", key="p1_test_pdf_es"):
                pdf = generate_pdf(data, system_type, "es")
                st.download_button("⬇ Descargar ES", pdf, f"{filename_base}_es.pdf", "application/pdf", key="p1_test_pdf_dl_es")
        with col2:
            if st.button("Generar — English", key="p1_test_pdf_en"):
                pdf = generate_pdf(data, system_type, "en")
                st.download_button("⬇ Download EN", pdf, f"{filename_base}_en.pdf", "application/pdf", key="p1_test_pdf_dl_en")


main()
