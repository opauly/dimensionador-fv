"""Step 8 — Instalación: the electrical-installation details (cable runs, PV coupling, AC protection layout, roof and mounting, conductors per
run) that used to live folded inside the Equipos step's "Detalle técnico". They get their own step so they are always in view while the
design is being decided.

The block itself is the `wizard/_wiring.html` fragment, the same one the project's Técnico tab reuses. Off-Grid / Hybrid read it from
`og_wiring`, Grid Zero from `gz_wiring`. Nothing here is mandatory: every answer has a default, so Siguiente is always open.
"""
from __future__ import annotations

from webapp.wizard_steps import gz_wiring, og_wiring


def roof_context(blob: dict, coupling: dict | None = None) -> dict | None:
    """The roof-layout question: the saved answer, the module count it applies to and the mounting counts it gives.
    None until a panel is chosen (nothing to lay out yet)."""
    from materials import engine

    blob = blob or {}
    eq = blob.get("equipment") or {}
    if (blob.get("meta") or {}).get("system_type") == "grid_zero":
        eq = engine.grid_zero_equipment(eq)
    panel, n_panels = eq.get("panel") or {}, int(eq.get("panel_count") or 0)
    if not (panel and n_panels):
        return None
    layout = engine.with_default_rows({**engine.DEFAULT_LAYOUT, **engine.layout_from_blob(blob)}, engine.string_count(eq, coupling))
    return {"layout": layout, "n_panels": n_panels, "counts": engine.layout_counts(panel, n_panels, layout),
            "has_dims": bool(panel.get("width_m") and panel.get("height_m"))}


def wiring_context(blob: dict) -> dict:
    """What `_wiring.html` needs, for any system type, plus the roof block."""
    grid_zero = ((blob or {}).get("meta") or {}).get("system_type") == "grid_zero"
    ctx = gz_wiring.build_context(blob) if grid_zero else og_wiring.build_context(blob)
    return {**ctx, "roof": roof_context(blob, ctx.get("coupling"))}


def build_context(blob: dict) -> dict:
    return {**wiring_context(blob), "can_continue": True}
