"""Proposal wizard — Phase 2: full Grid Zero 8-step wizard."""
from __future__ import annotations
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Nueva cotización — Pauly&Co Solar", layout="wide")

from config import BRAND_GREEN, BRAND_NAVY, WIZARD_STEPS_GRID_ZERO

STEP_LABELS = [
    "Tipo y idioma",
    "Cliente",
    "Sitio e irradiancia",
    "Distribuidora",
    "Consumo",
    "Equipos",
    "Costos",
    "Revisión y PDF",
]


def _render_progress(current_step: int) -> None:
    """Render step breadcrumb at the top."""
    cols = st.columns(len(STEP_LABELS))
    for i, (col, label) in enumerate(zip(cols, STEP_LABELS), start=1):
        with col:
            if i < current_step:
                st.markdown(
                    f"<div style='text-align:center;color:#4BAE6A;font-size:0.78rem;'>✓ {i}. {label}</div>",
                    unsafe_allow_html=True,
                )
            elif i == current_step:
                st.markdown(
                    f"<div style='text-align:center;color:#1E2D54;font-size:0.78rem;font-weight:700;"
                    f"border-bottom:2px solid #4BAE6A;padding-bottom:2px;'>{i}. {label}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"<div style='text-align:center;color:#adb5bd;font-size:0.78rem;'>{i}. {label}</div>",
                    unsafe_allow_html=True,
                )


def _init_or_resume_wizard() -> tuple[str | None, str | None]:
    """
    Ensure there's an active proposal+version in session.
    - If wizard_proposal_id exists in session → resume that draft.
    - If URL param 'proposal_id' + 'version_id' → load that draft.
    - Otherwise → create a new proposal when the user reaches Step 2.
    Returns (proposal_id, version_id) or (None, None).
    """
    p_id = st.session_state.get("wizard_proposal_id")
    v_id = st.session_state.get("wizard_version_id")
    return p_id, v_id


def _ensure_proposal_created() -> tuple[str, str]:
    """Create a proposal row in DB once the client name is known (called at Step 2 completion)."""
    p_id = st.session_state.get("wizard_proposal_id")
    v_id = st.session_state.get("wizard_version_id")
    if p_id and v_id:
        return p_id, v_id

    client = st.session_state.get("wizard_client", {})
    meta = st.session_state.get("wizard_meta", {})
    client_name = client.get("name", "Sin nombre")
    system_type = meta.get("system_type", "grid_zero")

    try:
        from database.proposals_db import create_proposal
        result = create_proposal(client_name, system_type)
        p_id = result["proposal_id"]
        v_id = result["id"]
        st.session_state["wizard_proposal_id"] = p_id
        st.session_state["wizard_version_id"] = v_id
    except Exception as e:
        st.error(f"No se pudo crear la cotización en la base de datos: {e}")
        raise

    return p_id, v_id


def _autosave_if_possible() -> None:
    p_id = st.session_state.get("wizard_proposal_id")
    v_id = st.session_state.get("wizard_version_id")
    if p_id and v_id:
        try:
            from wizard.state import autosave
            autosave(p_id, v_id)
        except Exception:
            pass


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    # Header
    is_resuming = bool(st.session_state.get("wizard_proposal_id"))
    client_name = st.session_state.get("wizard_client", {}).get("name", "")
    if is_resuming and client_name:
        title = f"Cotización — {client_name}"
    elif is_resuming:
        title = "Editar cotización"
    else:
        title = "Nueva cotización"

    header_col, save_col = st.columns([5, 1])
    with header_col:
        back_col, title_col = st.columns([1, 6])
        with back_col:
            if is_resuming:
                if st.button("← Cotizaciones", key="h_back_proposals"):
                    st.switch_page("pages/01_proposals.py")
        with title_col:
            st.markdown(
                f'<p style="color:#1E2D54;font-size:1.4rem;font-weight:700;margin:0;">{title}</p>',
                unsafe_allow_html=True,
            )
    with save_col:
        from wizard.state import show_save_indicator
        show_save_indicator()

    current_step = st.session_state.get("wizard_step", 1)

    # Progress bar
    _render_progress(current_step)
    st.divider()

    # Route to the correct step
    if current_step == 1:
        from wizard.common import step1_system_type
        result = step1_system_type()
        if result is not None:
            st.session_state["wizard_step"] = 2
            st.rerun()

    elif current_step == 2:
        from wizard.common import step2_client
        result = step2_client()
        if result is not None:
            # Save client to DB (create or update)
            try:
                from database.clients_db import upsert_client
                upsert_client(
                    name=result["name"],
                    phone=result.get("phone", ""),
                    email=result.get("email", ""),
                )
            except Exception:
                pass
            # Create proposal row now that we have client name
            try:
                p_id, v_id = _ensure_proposal_created()
                _autosave_if_possible()
            except Exception:
                pass
            st.session_state["wizard_step"] = 3
            st.rerun()

    elif current_step == 3:
        from wizard.common import step3_site
        result = step3_site()
        if result is not None:
            _autosave_if_possible()
            st.session_state["wizard_step"] = 4
            st.rerun()

    elif current_step == 4:
        from wizard.grid_zero import step4_utility
        result = step4_utility()
        if result is not None:
            _autosave_if_possible()
            st.session_state["wizard_step"] = 5
            st.rerun()

    elif current_step == 5:
        from wizard.grid_zero import step5_consumption
        result = step5_consumption()
        if result is not None:
            _autosave_if_possible()
            st.session_state["wizard_step"] = 6
            st.rerun()

    elif current_step == 6:
        from wizard.grid_zero import step6_equipment
        result = step6_equipment()
        if result is not None:
            _autosave_if_possible()
            st.session_state["wizard_step"] = 7
            st.rerun()

    elif current_step == 7:
        from wizard.grid_zero import step7_costs
        result = step7_costs()
        if result is not None:
            _autosave_if_possible()
            st.session_state["wizard_step"] = 8
            st.rerun()

    elif current_step == 8:
        from wizard.grid_zero import step8_review
        step8_review()

    # Phase 1 test buttons (collapsed)
    with st.expander("🧪 Prueba Fase 1 — PDF con datos de muestra", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Generar PDF prueba — Español", key="p1_es"):
                from proposals.generator import generate_pdf, MARIA_JOSE_DATA
                pdf = generate_pdf(MARIA_JOSE_DATA, "grid_zero", "es")
                st.download_button("⬇ Descargar ES", pdf, "muestra_es.pdf", "application/pdf", key="p1_dl_es")
        with col2:
            if st.button("Generar PDF prueba — English", key="p1_en"):
                from proposals.generator import generate_pdf, MARIA_JOSE_DATA
                pdf = generate_pdf(MARIA_JOSE_DATA, "grid_zero", "en")
                st.download_button("⬇ Download EN", pdf, "sample_en.pdf", "application/pdf", key="p1_dl_en")


main()
