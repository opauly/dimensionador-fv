"""Goals-vs-design check at Equipos (Phase 24 Step 4, PLAN_PHASE24_OBJETIVOS.md §1.4). Thin glue: it takes the
sweet-spot band for the draft's effective goals (confirmed, or the defaults for a grandfathered draft) and the
chosen design's `facts`, and hands both to the pure `calculations/goals_check.py`. Purely informational — it never
blocks Equipos; the engineer reads it and keeps the selection or picks something else."""
from __future__ import annotations

from calculations import goals_check as gc
from webapp.wizard_steps import s6_objetivos


def build(blob: dict, facts: dict) -> dict | None:
    """`facts` per system type — Off-Grid/Hybrid: system_kw, battery_installed_kwh, battery_dod_pct, inverter_kw_total,
    passthrough_a_total (or None). Grid Zero: system_kw, inverter_kw, reduction_pct. None when there is nothing
    to compare against (invalid goals, or an earlier step's data missing)."""
    sp = s6_objetivos.sweet_spot(blob)
    if sp is None:
        return None
    system_type = sp["system_type"]
    if system_type == "off_grid":
        rows = gc.check_offgrid(sp["goal_obj"], sp["band"], facts, sp["inputs"])
    elif system_type == "hybrid":
        rows = gc.check_hybrid(sp["goal_obj"], sp["band"], facts, {**sp["inputs"], "daytime_fraction": s6_objetivos._hybrid_daytime()}, sp["assumptions"],
                               sp["goals"].get("reduction_target_pct"))
    else:
        rows = gc.check_grid_zero(sp["goal_obj"], sp["band"], facts, sp["ack"])
    return {
        "system_type": system_type,
        "rows": rows,
        "summary": gc.summarize(rows),
        "default_goals": sp["source"] == "default",
        # Equipos' automatic scenarios (1/2/3) still come from the legacy reliability simulation, which these
        # goals do not drive — say so rather than let a "no cumple" read as a bug.
        "legacy_model_note": system_type in ("off_grid", "hybrid"),
    }
