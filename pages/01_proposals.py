"""Proposals list and version history. Phase 3."""
from __future__ import annotations
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Cotizaciones — Pauly&Co Solar", layout="wide")

from config import BRAND_NAVY

STATUS_LABELS = {
    "draft":     "Borrador",
    "active":    "Enviada",
    "won":       "Ganada",
    "lost":      "Perdida",
    "cancelled": "Cancelada",
}

SYSTEM_TYPE_LABELS = {
    "grid_zero": "Grid Zero",
    "off_grid":  "Off-Grid",
    "hybrid":    "Híbrido",
}


def _clear_wizard() -> None:
    keys = [k for k in list(st.session_state.keys())
            if k.startswith("wizard_") or k.startswith("w")]
    for k in keys:
        del st.session_state[k]


def _open_version(proposal_id: str, version_id: str) -> None:
    """Load unlocked version into wizard state, then navigate to wizard."""
    _clear_wizard()
    from wizard.state import load_draft
    st.session_state["wizard_proposal_id"] = proposal_id
    st.session_state["wizard_version_id"] = version_id
    load_draft(version_id)
    st.switch_page("pages/02_new_proposal.py")


def _new_version_from(proposal_id: str, source_version_id: str) -> None:
    """Fork a new unlocked version from an existing locked version."""
    from database.proposals_db import get_version, create_version
    from wizard.state import load_draft

    full_v = get_version(source_version_id)
    data = full_v.get("data", {}) if full_v else {}
    new_v = create_version(proposal_id, data)

    _clear_wizard()
    st.session_state["wizard_proposal_id"] = proposal_id
    st.session_state["wizard_version_id"] = new_v["id"]
    load_draft(new_v["id"])
    st.session_state["wizard_step"] = 1
    st.switch_page("pages/02_new_proposal.py")


def _signed_url(pdf_path: str) -> str | None:
    """Return a 1-hour signed URL for a Supabase Storage path, or None."""
    try:
        from database.supabase_client import get_client
        resp = get_client().storage.from_("solar-tool").create_signed_url(pdf_path, 3600)
        return resp.get("signedURL") or resp.get("signedUrl")
    except Exception:
        return None


def _render_version_row(v: dict, proposal_id: str) -> None:
    """Render one version row with status badges and action buttons."""
    from database.proposals_db import mark_version_sent

    vid      = v["id"]
    vnum     = v["version_number"]
    vcreated = (v.get("created_at") or "")[:10]
    vlocked  = v.get("locked", False)
    vsent    = v.get("sent_to_client", False)
    vnote    = v.get("version_note") or ""
    vtotal   = v.get("total_usd")
    vpdf     = v.get("pdf_path")

    vtotal_str = f"${vtotal:,.0f}" if vtotal else "—"

    badges = []
    if vlocked:
        badges.append("🔒 Bloqueada")
    else:
        badges.append("✏️ Borrador")
    if vsent:
        badges.append("📤 Enviada")
    note_str = f" · _{vnote}_" if vnote else ""

    st.markdown(
        f"**v{vnum}** &nbsp;·&nbsp; {vcreated} &nbsp;·&nbsp; {vtotal_str}"
        f" &nbsp;·&nbsp; {' · '.join(badges)}{note_str}",
        unsafe_allow_html=True,
    )

    btn_cols = st.columns(5)

    with btn_cols[0]:
        if not vlocked:
            if st.button("✏️ Continuar", key=f"open_{vid}"):
                _open_version(proposal_id, vid)

    with btn_cols[1]:
        if vpdf:
            url = _signed_url(vpdf)
            if url:
                st.link_button("⬇ PDF", url, key=f"dl_{vid}")
            else:
                st.caption("PDF (sin URL)")

    with btn_cols[2]:
        if vlocked:
            if st.button("📋 Nueva versión", key=f"newv_{vid}"):
                try:
                    _new_version_from(proposal_id, vid)
                except Exception as e:
                    st.error(f"Error creando versión: {e}")

    with btn_cols[3]:
        if vlocked and not vsent:
            if st.button("📤 Marcar enviada", key=f"sent_{vid}"):
                try:
                    mark_version_sent(vid)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

    st.markdown("---")


def main() -> None:
    from database.proposals_db import list_proposals, list_versions, update_proposal_status

    # ── Header ────────────────────────────────────────────────────────────────
    hcol, bcol = st.columns([5, 1])
    with hcol:
        st.markdown(
            f'<p style="color:{BRAND_NAVY};font-size:1.4rem;font-weight:700;margin:0;">Cotizaciones</p>',
            unsafe_allow_html=True,
        )
    with bcol:
        if st.button("➕ Nueva", type="primary", key="p1_new"):
            _clear_wizard()
            st.switch_page("pages/02_new_proposal.py")

    # ── Status filter ─────────────────────────────────────────────────────────
    filter_map = {
        "Todas": None,
        "Borrador": "draft",
        "Enviada": "active",
        "Ganada": "won",
        "Perdida": "lost",
    }
    sel_filter = st.radio(
        "Filtrar",
        list(filter_map.keys()),
        horizontal=True,
        label_visibility="collapsed",
        key="p1_filter",
    )
    filter_status = filter_map[sel_filter]

    # ── Load proposals ────────────────────────────────────────────────────────
    try:
        proposals = list_proposals(status=filter_status)
    except Exception as e:
        st.error(f"Error cargando cotizaciones: {e}")
        return

    if not proposals:
        st.info("No hay cotizaciones. Crea una nueva con el botón de arriba.")
        return

    st.caption(f"{len(proposals)} cotización(es)")
    st.divider()

    # ── Proposal rows ─────────────────────────────────────────────────────────
    for proposal in proposals:
        pid         = proposal["id"]
        client_name = proposal.get("client_name") or "Sin nombre"
        sys_label   = SYSTEM_TYPE_LABELS.get(proposal.get("system_type", ""), proposal.get("system_type", ""))
        status      = proposal.get("status", "draft")
        cur_vnum    = proposal.get("current_version_number", 1)
        updated     = (proposal.get("updated_at") or "")[:10] or "—"

        # Quick total from embedded version list
        versions_embedded = proposal.get("proposal_versions") or []
        cur_ver_embed = next(
            (v for v in versions_embedded if v.get("version_number") == cur_vnum),
            versions_embedded[-1] if versions_embedded else {},
        )
        total_usd = cur_ver_embed.get("total_usd")
        total_str = f"${total_usd:,.0f}" if total_usd else "—"

        status_label = STATUS_LABELS.get(status, status)
        expander_label = (
            f"{client_name} — {sys_label} | v{cur_vnum} | {total_str} | "
            f"{status_label} | {updated}"
        )

        with st.expander(expander_label, expanded=False):
            # ── Status control ────────────────────────────────────────────────
            sc, _ = st.columns([2, 4])
            with sc:
                all_statuses = list(STATUS_LABELS.keys())
                cur_idx = all_statuses.index(status) if status in all_statuses else 0
                new_status = st.selectbox(
                    "Estado",
                    all_statuses,
                    format_func=lambda s: STATUS_LABELS.get(s, s),
                    index=cur_idx,
                    key=f"status_{pid}",
                )
                if new_status != status:
                    try:
                        update_proposal_status(pid, new_status)
                        if new_status == "won":
                            st.info(
                                "🎉 Propuesta ganada. La función 'Mover a Proyecto' "
                                "estará disponible en Fase 6."
                            )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error actualizando estado: {e}")

            st.divider()

            # ── Version history ───────────────────────────────────────────────
            try:
                versions = list_versions(pid)
            except Exception as e:
                st.error(f"Error cargando versiones: {e}")
                continue

            if not versions:
                st.info("Sin versiones.")
                continue

            st.markdown("**Historial de versiones**")
            for v in reversed(versions):
                _render_version_row(v, pid)


main()
