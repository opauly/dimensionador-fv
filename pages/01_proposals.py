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


def _badge(status: str) -> str:
    label, bg, fg = STATUS_BADGE.get(status, ("—", "#f1f5f9", "#64748b"))
    return (
        f'<span style="display:inline-flex;align-items:center;height:20px;padding:0 9px;'
        f'border-radius:10px;font-size:0.7rem;font-weight:600;background:{bg};color:{fg};">'
        f'{label}</span>'
    )


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

    with st.container():
        st.markdown(
            '<div style="border:1.5px solid #bfdbfe;border-radius:8px;'
            'padding:14px 16px 12px;margin:4px 0 8px;background:white;">',
            unsafe_allow_html=True,
        )

        dl_state_key = f"pdf_bytes_{vid}"
        vpdf         = cur_ver.get("pdf_path")
        note_suffix  = f" · {vnote}" if vnote else ""

        # ── Layout: [title+flow col] | divider | [b1 Continuar] [b2 Nueva] ─
        t_col, _sep, b1, b2 = st.columns([3, 0.03, 1.5, 1.5])

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
                            st.info("🎉 Propuesta ganada.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.markdown(
                    '<div style="font-size:0.72rem;color:#94a3b8;padding:4px 0;">Estado final</div>',
                    unsafe_allow_html=True,
                )

        with _sep:
            st.markdown(
                '<div style="border-left:1px solid #cbd5e1;height:60px;margin:0 auto;width:1px;"></div>',
                unsafe_allow_html=True,
            )

        # b1 — Continuar (active when unlocked)
        with b1:
            if st.button("✏️ Continuar", key=f"det_open_{vid}",
                         disabled=vlocked, use_container_width=True):
                _open_version(pid, vid)

        # b2 — Nueva versión (active when locked)
        with b2:
            if st.button("📋 Nueva versión", key=f"det_newv_{vid}",
                         disabled=not vlocked, use_container_width=True):
                try:
                    _new_version_from(pid, vid)
                except Exception as e:
                    st.error(f"Error: {e}")

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

        st.markdown('</div>', unsafe_allow_html=True)


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
    lock_icon    = "🔒 Bloqueada" if vlocked else "✏️ Borrador"
    sent_str     = " · 📤 Enviada" if vsent else ""
    note_str     = f" · {vnote}" if vnote else ""
    dl_state_key = f"pdf_bytes_{vid}"

    rc1, rc2, _gap, rc3 = st.columns([3, 1, 0.25, 0.9])
    with rc1:
        st.markdown(
            f'<div style="font-size:0.78rem;font-weight:600;color:#1e293b;padding:3px 0;">{vquote}</div>'
            f'<div style="font-size:0.7rem;color:#94a3b8;">{lock_icon}{sent_str}{note_str}</div>',
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
                        f'<a href="{url}" target="_blank" rel="noopener" class="vrow-pill-btn">⬇ PDF</a>',
                        unsafe_allow_html=True,
                    )
            elif dl_state_key in st.session_state:
                import base64 as _b64
                b64 = _b64.b64encode(st.session_state[dl_state_key]).decode()
                st.markdown(
                    f'<a href="data:application/pdf;base64,{b64}" download="{vquote}.pdf"'
                    f' class="vrow-pill-btn">⬇ PDF</a>',
                    unsafe_allow_html=True,
                )
            else:
                choice = st.pills("", ["📄 Generar"], key=f"v_gen_{vid}",
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
        if st.button("➕ Nueva", type="primary", key="p1_new",
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
        return

    st.caption(f"{len(proposals)} cotización(es)")
    st.write("")

    # ── Table ─────────────────────────────────────────────────────────────────
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


main()
