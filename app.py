import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Pauly&Co Solar Tool",
    page_icon="☀️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { background-color: #1E2D54; }
    [data-testid="stSidebar"] .st-emotion-cache-1cypcdb,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] a { color: #ffffff !important; }
    [data-testid="stSidebarNav"] a span { color: #ffffff !important; }
    .page-header { color: #1E2D54; font-size: 1.8rem; font-weight: 700; margin-bottom: 0; }
    .page-sub   { color: #6c757d; font-size: 0.9rem; margin-top: 0; }
    .card-green { border-left: 4px solid #4BAE6A; background: #f8f9fa;
                  border-radius: 6px; padding: 1rem 1.2rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("##Pauly&Co")
    st.markdown("**Solar Design Tool**")
    st.divider()
    _db_ok = False
    try:
        from database.supabase_client import ping
        _db_ok = ping()
    except Exception:
        pass
    if _db_ok:
        st.success("● Supabase conectado", icon=None)
    else:
        st.warning("⚠ Supabase no conectado")

st.markdown('<p class="page-header">Panel de Control</p>', unsafe_allow_html=True)
st.markdown('<p class="page-sub">Herramienta de diseño solar — Pauly&Co</p>', unsafe_allow_html=True)
st.divider()

_drafts_count = "—"
_sent_count = "—"
try:
    from database.proposals_db import list_proposals as _lp
    _drafts_count = len(_lp(status="draft"))
    _sent_count = len(_lp(status="active"))
except Exception:
    pass

col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(
        f'<div class="card-green"><b>Borradores abiertos</b><br>'
        f'<span style="font-size:1.4rem">{_drafts_count}</span></div>',
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        f'<div class="card-green"><b>En espera de respuesta</b><br>'
        f'<span style="font-size:1.4rem">{_sent_count}</span></div>',
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        '<div class="card-green"><b>Proyectos activos</b><br>'
        '<span style="font-size:1.4rem">—</span></div>',
        unsafe_allow_html=True,
    )

st.divider()

if st.button("➕ Nueva cotización", type="primary"):
    st.switch_page("pages/02_new_proposal.py")

st.divider()
st.markdown("#### Estado del proyecto")
phases = [
    ("Fase 0 — Fundación",        "✅ Completa"),
    ("Fase 1 — Motor PDF",        "✅ Completa"),
    ("Fase 2 — Asistente Grid Zero", "✅ Completa"),
    ("Fase 3 — Gestión de cotizaciones", "✅ Completa"),
    ("Fase 4 — Funciones AI",     "🔲 Pendiente"),
    ("Fase 5 — Off-Grid + Híbrido", "🔲 Pendiente"),
    ("Fase 6 — Módulo Proyectos", "🔲 Pendiente"),
    ("Fase 7 — Admin + Pulido",   "🔲 Pendiente"),
    ("Fase 8 — QA + Entrega",     "🔲 Pendiente"),
]
for name, status in phases:
    st.markdown(f"{status} {name}")
