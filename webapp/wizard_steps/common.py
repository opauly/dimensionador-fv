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


def parse_rows(form, prefix: str, fields: list[str]) -> list[dict]:
    """PLAN §1.5's `st.data_editor` replacement — the inverse of the
    `<prefix>-<i>-<field>` naming convention every editable-table fragment
    uses for its `<input>`/`<select>` names (e.g. `m-3-kwh`, `row-0-W`).

    Scans `form` for every `<prefix>-<i>-<field>` key, groups them by row
    index `i`, and returns `list[dict]` ordered by index — one dict per row
    actually present in the submission, so "+ Fila"/"✕" (which just add or
    drop indices between renders) round-trip for free.

    Blanks coerce to `None`, not `0` or `""` — callers decide their own
    "blank means what" rule (e.g. `_row_subtotal()`'s "qty is None => treat
    as 1") rather than this helper silently picking one.
    """
    marker = f"{prefix}-"
    indices: set[int] = set()
    for key in form.keys():
        if not key.startswith(marker):
            continue
        rest = key[len(marker):]
        idx_str, sep, field = rest.partition("-")
        if sep and idx_str.isdigit() and field in fields:
            indices.add(int(idx_str))

    rows = []
    for i in sorted(indices):
        row = {}
        for field in fields:
            value = form.get(f"{prefix}-{i}-{field}")
            if value is not None:
                value = value.strip()
            row[field] = value if value else None
        rows.append(row)
    return rows
