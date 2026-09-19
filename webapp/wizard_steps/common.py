"""Shared constants/helpers for every wizard step module. Port of the labels
and options `pages/02_new_proposal.py` and `wizard/common.py` hard-code.

Step numbering follows the *displayed* order — 1 Cliente, 2 Tipo e idioma,
3 Sitio, 4..8 — i.e. this port drops `pages/02_new_proposal.py`'s legacy
name inversion (display step 1 renders step2_client(), display step 2
renders step1_system_type()). Not a behaviour change, just saner names.
"""
from __future__ import annotations

# wizard/state.py's autosave() default and pages/02_new_proposal.py's radio
# default both fall back to "grid_zero" — used here as the placeholder
# proposals.system_type the DB's NOT NULL/CHECK constraint needs before
# Step 2 (Tipo e idioma) sets the real value (PLAN §1.2's Q3 revision: the
# row is created on Step 1, before system type is known).
DEFAULT_SYSTEM_TYPE = "grid_zero"
DEFAULT_LANGUAGE = "es"

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

SYSTEM_TYPE_OPTIONS = [
    ("grid_zero", "Grid Zero (sin exportación de excedentes)"),
    ("off_grid", "Off-Grid (sistema aislado)"),
    ("hybrid", "Híbrido (Grid Zero + respaldo)"),
]
LANGUAGE_OPTIONS = [("es", "Español"), ("en", "English")]


def step_labels(system_type: str) -> list[str]:
    """STEP_LABELS_GRID_ZERO / STEP_LABELS_OFF_GRID switch — Hybrid uses the
    Off-Grid labels too (Cargas/Demanda), matching wizard/hybrid.py L382-397's
    delegation to the Off-Grid step modules."""
    return STEP_LABELS_GRID_ZERO if system_type == "grid_zero" else STEP_LABELS_OFF_GRID


def to_float(value, default: float | None = None) -> float | None:
    """Best-effort str -> float for optional numeric form fields (manual
    lat/lon overrides), coercing blanks/garbage to `default` instead of
    raising — the html <input type=number> can still submit an empty string."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
