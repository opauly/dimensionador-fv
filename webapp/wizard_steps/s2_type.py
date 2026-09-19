"""Step 2 — Tipo e idioma. Port of wizard/common.py:step1_system_type()
(Streamlit's *display* step 2 — see webapp/wizard_steps/common.py's
docstring on the legacy name inversion this port drops).

This step's POST does not create the proposal row (§0.3 Q3 moved that to
Step 1's own POST) — it only patches `meta` (system_type + language) into
the row Step 1 already created, and additionally corrects the
`proposals.system_type` DB column (see
database.proposals_db.update_proposal_system_type()'s docstring for why
that's needed on top of the JSONB patch).
"""
from __future__ import annotations

from webapp.wizard_steps.common import (
    DEFAULT_LANGUAGE, DEFAULT_SYSTEM_TYPE, LANGUAGE_OPTIONS, SYSTEM_TYPE_OPTIONS,
)

_SYSTEM_TYPES = {key for key, _ in SYSTEM_TYPE_OPTIONS}
_LANGUAGES = {key for key, _ in LANGUAGE_OPTIONS}


def build_context(blob: dict) -> dict:
    meta = (blob or {}).get("meta") or {}
    return {
        "system_type": meta.get("system_type") or DEFAULT_SYSTEM_TYPE,
        "language": meta.get("language") or DEFAULT_LANGUAGE,
        "system_type_options": SYSTEM_TYPE_OPTIONS,
        "language_options": LANGUAGE_OPTIONS,
    }


def parse_form(form) -> dict:
    """`request.form` -> a validated {system_type, language} pair, falling
    back to the same defaults the Streamlit radios use if the posted value
    is missing/tampered."""
    system_type = form.get("system_type") or DEFAULT_SYSTEM_TYPE
    if system_type not in _SYSTEM_TYPES:
        system_type = DEFAULT_SYSTEM_TYPE
    language = form.get("language") or DEFAULT_LANGUAGE
    if language not in _LANGUAGES:
        language = DEFAULT_LANGUAGE
    return {"system_type": system_type, "language": language}
