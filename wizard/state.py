"""Auto-save and session state helpers for the proposal wizard. Phase 2."""
import streamlit as st
from datetime import datetime


def autosave(proposal_id: str, version_id: str) -> None:
    """Serialize current wizard session state to Supabase. Called on every field change."""
    raise NotImplementedError("Phase 2")


def load_draft(version_id: str) -> None:
    """Restore wizard session state from a Supabase version row on app load."""
    raise NotImplementedError("Phase 2")


def clear_wizard_state() -> None:
    """Remove all wizard_ keys from st.session_state (called after locking a version)."""
    keys_to_clear = [k for k in st.session_state if k.startswith("wizard_")]
    for k in keys_to_clear:
        del st.session_state[k]


def show_save_indicator() -> None:
    """Render the ● Guardado / Guardando… chip in the top-right of the wizard. Phase 2."""
    raise NotImplementedError("Phase 2")
