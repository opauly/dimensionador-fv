"""Projects list and financial dashboard. Phase 6."""
from __future__ import annotations
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="Proyectos — Pauly&Co Solar", layout="wide")

from config import BRAND_NAVY, PROJECT_STATUSES, SYSTEM_TYPES, SYSTEM_TYPE_LABELS
from utils.formatting import fmt_usd

# ── Constants ─────────────────────────────────────────────────────────────────

STATUS_LABELS = {
    "active":    "Activo",
    "completed": "Completado",
    "paused":    "Pausado",
    "cancelled": "Cancelado",
}
STATUS_BADGE = {
    "active":    ("Activo",     "#dcfce7", "#16a34a"),
    "completed": ("Completado", "#dbeafe", "#1d4ed8"),
    "paused":    ("Pausado",    "#fef9c3", "#a16207"),
    "cancelled": ("Cancelado",  "#fee2e2", "#dc2626"),
}
FILTER_OPTIONS = ["Todos", "Activos", "Completados", "Pausados", "Cancelados"]
FILTER_MAP = {
    "Todos": None,
    "Activos": "active",
    "Completados": "completed",
    "Pausados": "paused",
    "Cancelados": "cancelled",
}

# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
<style>
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
[data-testid="stVerticalBlock"] > [data-testid="element-container"] {
    margin-bottom: 0 !important;
}
button[data-testid="baseButton-secondary"],
button[data-testid="baseButton-primary"] {
    min-height: 0 !important;
    height: 36px !important;
    padding: 0 10px !important;
    font-size: 0.8rem !important;
}
[data-testid="stHorizontalBlock"] {
    gap: 4px !important;
    align-items: center !important;
}
div[data-testid="stPills"] button[aria-selected="true"] {
    background-color: #0f172a !important;
    color: #ffffff !important;
    border-color: #0f172a !important;
}
.st-key-p3_new_wrap {
    border: 1.5px solid #bfdbfe;
    border-radius: 8px;
    padding: 14px 16px 12px;
    margin: 4px 0 8px;
    background: white;
}
</style>
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _pill(label: str, bg: str, fg: str) -> str:
    return (
        f'<span style="display:inline-flex;align-items:center;height:20px;padding:0 9px;'
        f'border-radius:10px;font-size:0.7rem;font-weight:600;background:{bg};color:{fg};">'
        f'{label}</span>'
    )


def _badge(status: str) -> str:
    label, bg, fg = STATUS_BADGE.get(status, ("—", "#f1f5f9", "#64748b"))
    return _pill(label, bg, fg)


_HEADER_HTML = """
<div style="display:grid;
  grid-template-columns:1.6fr 1fr 1fr 1fr 80px;
  gap:10px;align-items:center;padding:5px 8px;
  border-bottom:2px solid #e2e8f0;margin-bottom:2px;">
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Cliente</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Sistema</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Contrato</div>
  <div style="font-size:0.68rem;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.06em;">Estado</div>
  <div></div>
</div>"""


def _render_row(project: dict) -> bool:
    """Render one project row. Returns True if the '›' button was clicked."""
    pid         = project["id"]
    client_name = project.get("client_name") or "Sin nombre"
    sys_label   = SYSTEM_TYPE_LABELS.get(project.get("system_type", ""), "—")
    status      = project.get("status", "active")
    contract    = project.get("contract_usd")
    contract_str = fmt_usd(contract)
    badge_html  = _badge(status)

    row_html = f"""
<div style="background:white;display:grid;
  grid-template-columns:1.6fr 1fr 1fr 1fr 80px;
  gap:10px;align-items:center;padding:9px 8px;
  border-bottom:1px solid #f1f5f9;border-radius:4px;">
  <div style="font-size:0.82rem;font-weight:600;color:#1e293b;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{client_name}</div>
  <div style="font-size:0.78rem;color:#64748b;white-space:nowrap;">{sys_label}</div>
  <div style="font-size:0.82rem;font-weight:600;color:#1e293b;">{contract_str}</div>
  <div>{badge_html}</div>
</div>"""

    content_col, btn_col = st.columns([16, 1])
    with content_col:
        st.markdown(row_html, unsafe_allow_html=True)
    with btn_col:
        return st.button("›", key=f"p3_sel_{pid}", type="secondary", use_container_width=True)


# ── New project form ────────────────────────────────────────────────────────

def _render_new_project_form() -> None:
    from database.clients_db import search_clients
    from database.projects_db import create_project_manual

    with st.container(key="p3_new_wrap"):
        st.markdown(
            '<div style="font-size:0.92rem;font-weight:700;color:#1e293b;margin-bottom:8px;">'
            'Nuevo proyecto (sin cotización)</div>',
            unsafe_allow_html=True,
        )

        query = st.text_input(
            "Cliente",
            placeholder="Buscar cliente existente o escribir nombre nuevo…",
            key="p3_new_client_query",
        )
        matches = search_clients(query) if query else []
        client_id = None
        client_name = query.strip()
        if matches:
            options = ["(usar texto libre — sin cliente registrado)"] + [
                f"{m['name']}" + (f" — {m['empresa']}" if m.get("empresa") else "") for m in matches
            ]
            choice = st.selectbox("Coincidencias encontradas", options, key="p3_new_client_choice")
            idx = options.index(choice) - 1
            if idx >= 0:
                client_id = matches[idx]["id"]
                client_name = matches[idx]["name"]

        c1, c2, c3 = st.columns(3)
        with c1:
            system_type = st.selectbox(
                "Tipo de sistema", SYSTEM_TYPES,
                format_func=lambda s: SYSTEM_TYPE_LABELS.get(s, s),
                key="p3_new_system_type",
            )
        with c2:
            contract_usd = st.number_input(
                "Contrato (USD, monto total)", min_value=0.0, step=10.0, key="p3_new_contract",
                help="El total del contrato, con IVA incluido si corresponde.",
            )
        with c3:
            contract_iva_usd = st.number_input(
                "IVA incluido (USD)", min_value=0.0, step=10.0, key="p3_new_iva",
                help="Monto de IVA ya incluido en el total de arriba, si aplica. Normalmente 0.",
            )

        notes = st.text_area("Notas", key="p3_new_notes")

        bcol1, bcol2 = st.columns([1, 1])
        with bcol1:
            if st.button("Crear proyecto", key="p3_new_confirm", type="primary", use_container_width=True):
                if not client_name:
                    st.error("Ingresa un nombre de cliente.")
                else:
                    try:
                        project = create_project_manual(
                            client_name=client_name,
                            system_type=system_type,
                            contract_usd=contract_usd,
                            contract_iva_usd=contract_iva_usd,
                            client_id=client_id,
                            notes=notes or None,
                        )
                        st.session_state.pop("p3_new_open", None)
                        st.session_state["selected_project_id"] = project["id"]
                        st.switch_page("pages/04_project_detail.py")
                    except Exception as e:
                        st.error(f"Error: {e}")
        with bcol2:
            if st.button("Cancelar", key="p3_new_cancel", use_container_width=True):
                st.session_state.pop("p3_new_open", None)
                st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    from database.projects_db import list_projects

    st.markdown(_CSS, unsafe_allow_html=True)

    hcol, bcol = st.columns([5, 1])
    with hcol:
        st.markdown(
            f'<p style="color:{BRAND_NAVY};font-size:1.4rem;font-weight:700;margin:0 0 8px;">Proyectos</p>',
            unsafe_allow_html=True,
        )
    with bcol:
        if st.button("+ Nuevo proyecto", type="primary", key="p3_new_toggle", use_container_width=True):
            st.session_state["p3_new_open"] = not st.session_state.get("p3_new_open", False)
            st.rerun()

    if st.session_state.get("p3_new_open"):
        _render_new_project_form()

    sel_filter = st.pills(
        "Filtro", FILTER_OPTIONS,
        default="Todos",
        key="p3_filter_pills",
        label_visibility="collapsed",
    ) or "Todos"

    filter_status = FILTER_MAP.get(sel_filter)

    try:
        projects = list_projects(status=filter_status)
    except Exception as e:
        st.error(f"Error cargando proyectos: {e}")
        return

    if not projects:
        st.info("No hay proyectos. Promueve una cotización ganada o crea uno nuevo con el botón de arriba.")
        return

    st.caption(f"{len(projects)} proyecto(s)")
    st.write("")

    hdr_col, _ = st.columns([16, 1])
    with hdr_col:
        st.markdown(_HEADER_HTML, unsafe_allow_html=True)

    for project in projects:
        clicked = _render_row(project)
        if clicked:
            st.session_state["selected_project_id"] = project["id"]
            st.switch_page("pages/04_project_detail.py")


main()
