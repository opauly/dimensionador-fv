"""Proposal wizard — Phase 2: full Grid Zero 8-step wizard."""
from __future__ import annotations
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Nueva cotización — Pauly&Co Solar", layout="wide")

from config import BRAND_GREEN, BRAND_NAVY, WIZARD_STEPS_GRID_ZERO

STEP_LABELS_GRID_ZERO = [
    "Cliente",
    "Tipo e idioma",
    "Sitio e irradiancia",
    "Distribuidora",
    "Consumo",
    "Equipos",
    "Costos",
    "Revisión y PDF",
]

STEP_LABELS_OFF_GRID = [
    "Cliente",
    "Tipo e idioma",
    "Sitio e irradiancia",
    "Cargas",
    "Demanda",
    "Equipos",
    "Costos",
    "Revisión y PDF",
]


def _render_progress(current_step: int) -> None:
    """Render step breadcrumb at the top. Step 4/5 labels depend on system_type."""
    system_type = st.session_state.get("wizard_meta", {}).get("system_type", "grid_zero")
    step_labels = STEP_LABELS_GRID_ZERO if system_type == "grid_zero" else STEP_LABELS_OFF_GRID
    cols = st.columns(len(step_labels))
    for i, (col, label) in enumerate(zip(cols, step_labels), start=1):
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
    from wizard.state import autosave_if_possible
    autosave_if_possible()


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

    header_col, save_col = st.columns([6, 1])
    with header_col:
        if is_resuming:
            if st.button("← Cotizaciones", key="h_back_proposals"):
                st.switch_page("pages/01_proposals.py")
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
        from wizard.common import step2_client
        result = step2_client()
        if result is not None:
            try:
                if result.get("client_id"):
                    # Existing client selected via search — fill blank fields only,
                    # same behavior as before this change.
                    from database.clients_db import upsert_client
                    upsert_client(
                        name=result["name"],
                        empresa=result.get("empresa", ""),
                        phone=result.get("phone", ""),
                        email=result.get("email", ""),
                    )
                else:
                    # No existing match — this is a new prospect, not a client yet.
                    # Only becomes a client when a proposal for them is marked won
                    # (see promote_prospect() in pages/01_proposals.py).
                    from database.prospects_db import create_prospect
                    prospect = create_prospect(
                        name=result["name"],
                        empresa=result.get("empresa", ""),
                        phone=result.get("phone", ""),
                        email=result.get("email", ""),
                    )
                    result["prospect_id"] = prospect["id"]
                    st.session_state["wizard_client"] = result
            except Exception:
                pass
            st.session_state["wizard_step"] = 2
            st.rerun()

    elif current_step == 2:
        from wizard.common import step1_system_type
        result = step1_system_type()
        if result is not None:
            try:
                client = st.session_state.get("wizard_client", {})
                p_id = st.session_state.get("wizard_proposal_id")
                v_id = st.session_state.get("wizard_version_id")
                if not (p_id and v_id):
                    from database.proposals_db import create_proposal
                    prop = create_proposal(
                        client_name=client.get("name", "Sin nombre"),
                        system_type=result.get("system_type", "grid_zero"),
                        client_id=client.get("client_id"),
                        prospect_id=client.get("prospect_id"),
                    )
                    st.session_state["wizard_proposal_id"] = prop["proposal_id"]
                    st.session_state["wizard_version_id"] = prop["id"]
                st.session_state["wizard_step"] = 3
                _autosave_if_possible()
            except Exception as e:
                st.error(f"No se pudo crear la cotización: {e}")
            st.rerun()

    elif current_step == 3:
        from wizard.common import step3_site
        result = step3_site()
        if result is not None:
            st.session_state["wizard_step"] = 4
            _autosave_if_possible()
            st.rerun()

    elif current_step == 4:
        system_type = st.session_state.get("wizard_meta", {}).get("system_type", "grid_zero")
        if system_type == "grid_zero":
            from wizard.grid_zero import step4_utility as step4
        elif system_type == "off_grid":
            from wizard.off_grid import step4_loads as step4
        else:
            from wizard.hybrid import step4_loads as step4
        result = step4()
        if result is not None:
            st.session_state["wizard_step"] = 5
            _autosave_if_possible()
            st.rerun()

    elif current_step == 5:
        system_type = st.session_state.get("wizard_meta", {}).get("system_type", "grid_zero")
        if system_type == "grid_zero":
            from wizard.grid_zero import step5_consumption as step5
        elif system_type == "off_grid":
            from wizard.off_grid import step5_demand as step5
        else:
            from wizard.hybrid import step5_demand as step5
        result = step5()
        if result is not None:
            st.session_state["wizard_step"] = 6
            _autosave_if_possible()
            st.rerun()

    elif current_step == 6:
        system_type = st.session_state.get("wizard_meta", {}).get("system_type", "grid_zero")
        if system_type == "grid_zero":
            from wizard.grid_zero import step6_equipment as step6
        elif system_type == "off_grid":
            from wizard.off_grid import step6_equipment as step6
        else:
            from wizard.hybrid import step6_equipment as step6
        result = step6()
        if result is not None:
            st.session_state["wizard_step"] = 7
            _autosave_if_possible()
            st.rerun()

    elif current_step == 7:
        system_type = st.session_state.get("wizard_meta", {}).get("system_type", "grid_zero")
        if system_type == "grid_zero":
            from wizard.grid_zero import step7_costs as step7
        elif system_type == "off_grid":
            from wizard.off_grid import step7_costs as step7
        else:
            from wizard.hybrid import step7_costs as step7
        result = step7()
        if result is not None:
            st.session_state["wizard_step"] = 8
            _autosave_if_possible()
            st.rerun()

    elif current_step == 8:
        system_type = st.session_state.get("wizard_meta", {}).get("system_type", "grid_zero")
        if system_type == "grid_zero":
            from wizard.grid_zero import step8_review
            step8_review()
        elif system_type == "off_grid":
            from wizard.off_grid import step8_review
            step8_review(language=st.session_state.get("wizard_meta", {}).get("language", "es"))
        else:
            from wizard.hybrid import step8_review
            step8_review(language=st.session_state.get("wizard_meta", {}).get("language", "es"))

main()
