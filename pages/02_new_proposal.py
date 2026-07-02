"""Proposal wizard entry point. Phase 2. Phase 1 test button included."""
import streamlit as st

st.set_page_config(page_title="Nueva cotización — Pauly&Co Solar", layout="wide")
st.title("Nueva cotización")

# ── Phase 1 PDF test ─────────────────────────────────────────────────────────
st.subheader("🧪 Phase 1 — Generador de PDF (prueba)")
st.caption("Genera un PDF con datos de María José Castro para validar el template.")

col1, col2 = st.columns(2)

with col1:
    if st.button("Generar PDF — Español", type="primary"):
        with st.spinner("Generando PDF…"):
            try:
                from proposals.generator import generate_pdf, MARIA_JOSE_DATA
                pdf_bytes = generate_pdf(MARIA_JOSE_DATA, "grid_zero", "es")
                st.success(f"PDF generado — {len(pdf_bytes):,} bytes")
                st.download_button(
                    label="⬇ Descargar PDF (ES)",
                    data=pdf_bytes,
                    file_name="cotizacion_maria_jose_es.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.error(f"Error: {e}")
                st.exception(e)

with col2:
    if st.button("Generar PDF — English", type="secondary"):
        with st.spinner("Generating PDF…"):
            try:
                from proposals.generator import generate_pdf, MARIA_JOSE_DATA
                pdf_bytes = generate_pdf(MARIA_JOSE_DATA, "grid_zero", "en")
                st.success(f"PDF generated — {len(pdf_bytes):,} bytes")
                st.download_button(
                    label="⬇ Download PDF (EN)",
                    data=pdf_bytes,
                    file_name="quotation_maria_jose_en.pdf",
                    mime="application/pdf",
                )
            except Exception as e:
                st.error(f"Error: {e}")
                st.exception(e)

st.divider()
st.info("El asistente de cotización completo estará disponible en Fase 2.")
