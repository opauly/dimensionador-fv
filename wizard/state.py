"""Auto-save and session state helpers for the proposal wizard. Phase 2."""
from __future__ import annotations
from datetime import datetime

import streamlit as st

# Default company info — replaced by app_settings in Phase 7
_DEFAULT_COMPANY = {
    "contact_name": "Ing. Oscar Pauly Calvo",
    "contact_title": "Gerente de Proyecto",
    "contact_title_en": "Project Manager",
    "license": "IE-30111",
    "phone": "+506 7104-8046",
    "email": "info@paulyco.com",
    "website": "www.paulyco.com",
}

_DEFAULT_BANK_LOCAL_ES = [
    "Banco: BAC San José (USD)",
    "Beneficiario: Pauly y Compañía Ingenieros y Arquitectos S.A.",
    "IBAN: CR94010200009461058148",
    "Cédula Jurídica: 3-101-798034",
    "Correo: facturas@paulyco.com",
]
_DEFAULT_BANK_INTL_ES = [
    "Formato: MT103",
    "Campo: 57",
    "Transferir a: Banco BAC San José",
    "Swift: BSNJCRSJ",
    "Dirección: Calle 0 Avenidas 3 y 5, San José Costa Rica, CA",
    "Nombre Completo del Beneficiario: Pauly y Compañía Ingenieros y Arquitectos",
    "IBAN del Beneficiario: CR94010200009461058148",
]
_DEFAULT_BANK_LOCAL_EN = [
    "Bank: BAC San José (USD)",
    "Beneficiary: Pauly y Compañía Ingenieros y Arquitectos S.A.",
    "IBAN: CR94010200009461058148",
    "Tax ID: 3-101-798034",
    "Email: facturas@paulyco.com",
]
_DEFAULT_BANK_INTL_EN = [
    "Format: MT103",
    "Field: 57",
    "Transfer to: Banco BAC San José",
    "Swift: BSNJCRSJ",
    "Address: Calle 0 Avenidas 3 y 5, San José Costa Rica, CA",
    "Full Beneficiary Name: Pauly y Compañía Ingenieros y Arquitectos",
    "Beneficiary IBAN: CR94010200009461058148",
]


def init_wizard(proposal_id: str, version_id: str) -> None:
    """Store proposal/version IDs in session state to track the active wizard."""
    st.session_state["wizard_proposal_id"] = proposal_id
    st.session_state["wizard_version_id"] = version_id
    if "wizard_step" not in st.session_state:
        st.session_state["wizard_step"] = 1
    if "save_status" not in st.session_state:
        st.session_state["save_status"] = "saved"


def autosave(proposal_id: str, version_id: str) -> None:
    """Serialize current wizard session state to Supabase."""
    from database.proposals_db import upsert_version

    st.session_state["save_status"] = "saving"

    step = st.session_state.get("wizard_step", 1)
    data = {
        "meta": {**st.session_state.get("wizard_meta", {}), "step_reached": step},
        "client": st.session_state.get("wizard_client", {}),
        "site": st.session_state.get("wizard_site", {}),
        "utility": st.session_state.get("wizard_utility", {}),
        "consumption": st.session_state.get("wizard_consumption", {}),
        "equipment": st.session_state.get("wizard_equipment", {}),
        "costs": st.session_state.get("wizard_costs", {}),
        "proposal_text": st.session_state.get("wizard_proposal_text", ""),
    }

    total_usd = st.session_state.get("wizard_costs", {}).get("total_usd")
    upsert_version(version_id, data, total_usd)

    st.session_state["save_status"] = "saved"
    st.session_state["last_saved"] = datetime.now()


def load_draft(version_id: str) -> None:
    """Restore wizard session state from a Supabase version row on app load."""
    from database.proposals_db import get_version

    row = get_version(version_id)
    if not row or not row.get("data"):
        return

    blob = row["data"]
    for key in ("meta", "client", "site", "utility", "consumption", "equipment", "costs"):
        if key in blob:
            st.session_state[f"wizard_{key}"] = blob[key]
    if "proposal_text" in blob:
        st.session_state["wizard_proposal_text"] = blob["proposal_text"]

    step = blob.get("meta", {}).get("step_reached", 1)
    st.session_state["wizard_step"] = step


def autosave_if_possible() -> None:
    """Autosave from any wizard step without needing the caller to hold IDs."""
    p_id = st.session_state.get("wizard_proposal_id")
    v_id = st.session_state.get("wizard_version_id")
    if p_id and v_id:
        try:
            autosave(p_id, v_id)
        except Exception:
            pass


def clear_wizard_state() -> None:
    """Remove all wizard_ keys from st.session_state (called after locking a version)."""
    keys_to_clear = [k for k in st.session_state if k.startswith("wizard_")]
    for k in keys_to_clear:
        del st.session_state[k]


def show_save_indicator() -> None:
    """Render the ● Guardado / Guardando… chip in the top-right of the wizard."""
    status = st.session_state.get("save_status", "saved")
    last = st.session_state.get("last_saved")
    if status == "saving":
        st.caption("⏳ Guardando…")
    elif last:
        st.caption(f"● Guardado {last.strftime('%H:%M')}")
    else:
        st.caption("● Guardado")


def get_company_info() -> dict:
    """Return company info from app_settings, falling back to defaults."""
    try:
        from database.supabase_client import get_client
        result = (
            get_client()
            .table("app_settings")
            .select("value")
            .eq("key", "company_info")
            .single()
            .execute()
        )
        if result.data and result.data.get("value"):
            stored = result.data["value"]
            if isinstance(stored, str):
                import json
                stored = json.loads(stored)
            # Only override defaults with non-empty stored values so partial
            # records in app_settings never blank out contact details.
            merged = dict(_DEFAULT_COMPANY)
            for k, v in stored.items():
                if v is not None and v != "":
                    merged[k] = v
            return merged
    except Exception:
        pass
    return _DEFAULT_COMPANY


def get_bank_info() -> dict:
    """Return bank lines from app_settings, falling back to defaults."""
    return {
        "bank_local_lines": _DEFAULT_BANK_LOCAL_ES,
        "bank_intl_lines": _DEFAULT_BANK_INTL_ES,
        "bank_local_lines_en": _DEFAULT_BANK_LOCAL_EN,
        "bank_intl_lines_en": _DEFAULT_BANK_INTL_EN,
    }
