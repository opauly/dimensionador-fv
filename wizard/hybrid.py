from __future__ import annotations
"""Wizard steps 4-8 for Hybrid proposals. Extends Off-Grid. Phase 5."""
import streamlit as st

from wizard import off_grid

_AC_COUPLING_NOTE_ES = (
    "Este sistema es híbrido: mantiene conexión a la red eléctrica además del banco de "
    "baterías. El excedente solar no consumido en sitio ni almacenado en batería se "
    "acopla en corriente alterna (AC) hacia la red — sin crédito por excedentes "
    "(no hay medición neta)."
)
_AC_COUPLING_NOTE_EN = (
    "This system is hybrid: it keeps a grid connection in addition to the battery "
    "bank. Solar excess not consumed on-site or stored in the battery is AC-coupled "
    "to the grid — no export credit (no net metering)."
)


def step4_loads() -> dict | None:
    """Same as off_grid.step4_loads with a grid-connection-at-main-panel option."""
    st.markdown("### Paso 4 — Cargas eléctricas y perfil de consumo general")
    st.info("Sistema Híbrido: conserva conexión a la red eléctrica además del banco de baterías.")

    current = st.session_state.get("wizard_consumption", {})
    grid_connected = st.checkbox(
        "Conexión a la red en el panel principal",
        value=current.get("grid_connected", True),
        key="w4h_grid_connected",
        help="Desmarcar solo si, a pesar de ser híbrido, no habrá conexión activa a la red en este momento.",
    )
    st.session_state["_w4h_grid_connected"] = grid_connected

    result = off_grid.step4_loads()
    if result is not None:
        result["grid_connected"] = st.session_state.get("_w4h_grid_connected", True)
        st.session_state["wizard_consumption"] = result
    return result


def step5_demand() -> dict | None:
    return off_grid.step5_demand()


def step6_equipment() -> dict | None:
    return off_grid.step6_equipment()


def step7_costs() -> dict | None:
    return off_grid.step7_costs()


def step8_review(site=None, loads=None, equipment=None, costs=None, language: str = "es") -> None:
    """Includes the AC coupling note in the proposal text before generating the PDF."""
    note = _AC_COUPLING_NOTE_ES if language == "es" else _AC_COUPLING_NOTE_EN
    current_text = st.session_state.get("wizard_proposal_text", "")
    if note not in current_text:
        st.session_state["wizard_proposal_text"] = (current_text + "\n\n" + note).strip()

    off_grid.step8_review(site=site, loads=loads, equipment=equipment, costs=costs, language=language)
