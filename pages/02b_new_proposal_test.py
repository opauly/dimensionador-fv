"""
Proposal wizard — TEST variant of the static design-tier scenario model.

Reuses Steps 1-5 from wizard/common.py and wizard/off_grid.py/hybrid.py
completely unchanged (same functions, same session-state keys as the real
"Nueva cotización" page) — only Step 6 is swapped for the new static
generator (wizard/design_scenarios_test.py). Nothing here writes to
Supabase: no proposal is created, no client/prospect is upserted, no
autosave — this page is an ephemeral sandbox for comparing the new engine's
numbers against real site/load data, not a second production entry point.

Because Steps 1-5 are the SAME functions the real wizard uses, they read
and write the SAME wizard_client/wizard_meta/wizard_site/wizard_consumption/
wizard_step session-state keys — deliberately, so you can fill in a site
once and see both engines' Step 6 against it. The one thing to know: some
of those reused steps' own "Atrás" buttons write wizard_step directly, so
this page's step navigation is coupled to the real wizard's — don't expect
to have both pages mid-flight on different steps in the same browser tab.
Use "Reiniciar prueba" below to clear all wizard_* state and start fresh.
"""
from __future__ import annotations
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Nueva cotización (TEST) — Pauly&Co Solar", layout="wide")

STEP_LABELS = [
    "Cliente", "Tipo e idioma", "Sitio e irradiancia", "Cargas", "Demanda",
    "Equipos (TEST)", "Costos", "Revisión",
]


def _render_progress(current_step: int) -> None:
    cols = st.columns(len(STEP_LABELS))
    for i, (col, label) in enumerate(zip(cols, STEP_LABELS), start=1):
        with col:
            if i < current_step:
                st.markdown(f"<div style='text-align:center;color:#4BAE6A;font-size:0.78rem;'>{i}. {label}</div>", unsafe_allow_html=True)
            elif i == current_step:
                st.markdown(
                    f"<div style='text-align:center;color:#1E2D54;font-size:0.78rem;font-weight:700;"
                    f"border-bottom:2px solid #4BAE6A;padding-bottom:2px;'>{i}. {label}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"<div style='text-align:center;color:#adb5bd;font-size:0.78rem;'>{i}. {label}</div>", unsafe_allow_html=True)


def main():
    header_col, reset_col = st.columns([3.3, 2.2])
    with header_col:
        st.markdown(
            '<p style="color:#1E2D54;font-size:1.4rem;font-weight:700;margin:0;">Nueva cotización — TEST (modelo estático)</p>',
            unsafe_allow_html=True,
        )
        st.caption("Sandbox: no crea ni guarda cotizaciones. Ver docstring del archivo para el detalle del alcance.")
    with reset_col:
        if st.button("Reiniciar prueba", key="tds_reset"):
            for k in list(st.session_state.keys()):
                if k.startswith("wizard_") or k.startswith("test_wizard_") or k.startswith("tds_"):
                    del st.session_state[k]
            st.rerun()

    current_step = st.session_state.get("wizard_step", 1)
    if current_step > 8:
        current_step = 1
        st.session_state["wizard_step"] = 1

    _render_progress(min(current_step, 8))
    st.divider()

    if current_step == 1:
        from wizard.common import step2_client
        result = step2_client()
        if result is not None:
            st.session_state["wizard_step"] = 2
            st.rerun()

    elif current_step == 2:
        from wizard.common import step1_system_type
        result = step1_system_type()
        if result is not None:
            if result.get("system_type") not in ("off_grid", "hybrid"):
                st.warning(
                    "Este modelo estático solo aplica a Off-Grid e Híbrido. "
                    "Selecciona uno de esos dos tipos para probarlo."
                )
            else:
                st.session_state["wizard_step"] = 3
                st.rerun()

    elif current_step == 3:
        from wizard.common import step3_site
        result = step3_site()
        if result is not None:
            st.session_state["wizard_step"] = 4
            st.rerun()

    elif current_step == 4:
        system_type = st.session_state.get("wizard_meta", {}).get("system_type", "off_grid")
        if system_type == "off_grid":
            from wizard.off_grid import step4_loads as step4
        else:
            from wizard.hybrid import step4_loads as step4
        result = step4()
        if result is not None:
            st.session_state["wizard_step"] = 5
            st.rerun()

    elif current_step == 5:
        system_type = st.session_state.get("wizard_meta", {}).get("system_type", "off_grid")
        if system_type == "off_grid":
            from wizard.off_grid import step5_demand as step5
        else:
            from wizard.hybrid import step5_demand as step5
        result = step5()
        if result is not None:
            st.session_state["wizard_step"] = 6
            st.rerun()

    elif current_step == 6:
        from wizard.design_scenarios_test import step6_equipment_static
        result = step6_equipment_static()
        if result is not None:
            st.session_state["wizard_step"] = 7
            st.rerun()

    elif current_step == 7:
        system_type = st.session_state.get("wizard_meta", {}).get("system_type", "off_grid")
        if system_type == "off_grid":
            from wizard.off_grid import step7_costs
        else:
            from wizard.hybrid import step7_costs
        result = step7_costs()
        if result is not None:
            st.session_state["wizard_step"] = 8
            st.rerun()

    elif current_step == 8:
        system_type = st.session_state.get("wizard_meta", {}).get("system_type", "off_grid")
        if system_type == "off_grid":
            from wizard.off_grid import step8_review
        else:
            from wizard.hybrid import step8_review
        step8_review(language=st.session_state.get("wizard_meta", {}).get("language", "es"))


main()
