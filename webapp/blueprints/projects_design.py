from __future__ import annotations
"""The saved design a project reads for its engineering tabs (Técnico, Lista de materiales, Unifilar).

One loader so the three tabs can never read different versions or size different wiring:
the project's `tech_spec` picks the quote version (default: latest locked) and carries the cable
lengths and PV coupling; equipment and wiring are read from that version's draft blob.
"""


def pick_version(versions: list[dict], wanted: str | None) -> dict | None:
    if not versions:
        return None
    if wanted:
        hit = next((v for v in versions if v["id"] == wanted), None)
        if hit:
            return hit
    locked = [v for v in versions if v.get("locked")]
    return (locked or versions)[-1]


def load(project: dict) -> dict:
    """{'empty': str|None, 'spec', 'versions', 'chosen', 'blob', 'eq', 'wiring'} — `empty` says why
    there is nothing to show; `wiring` is `og_wiring.build_context` for Off-Grid / Hybrid designs."""
    from database.proposals_db import list_versions
    from webapp.wizard_steps import og_wiring
    from wizard import draft

    spec = project.get("tech_spec") or {}
    out = {"empty": None, "spec": spec, "versions": [], "chosen": None, "blob": {}, "eq": {}, "wiring": {"ready": False, "branches": []}}
    proposal_id = project.get("proposal_id")
    if not proposal_id:
        out["empty"] = "Este proyecto se creó sin cotización, así que no hay un diseño guardado del cual leer equipos y cableado."
        return out
    versions = list_versions(proposal_id)
    chosen = pick_version(versions, spec.get("version_id"))
    out.update(versions=versions, chosen=chosen)
    if chosen is None:
        out["empty"] = "La cotización de este proyecto no tiene versiones."
        return out
    blob = draft.load(chosen["id"])
    eq = blob.get("equipment") or {}
    out.update(blob=blob, eq=eq)
    if not eq.get("panel"):
        out["empty"] = "La versión elegida todavía no tiene equipos seleccionados."
        return out
    if project.get("system_type") in ("off_grid", "hybrid"):
        out["wiring"] = og_wiring.build_context(blob, spec.get("wiring_lengths") or {}, spec.get("coupling"))
    elif project.get("system_type") == "grid_zero":
        from webapp.wizard_steps import gz_wiring

        out["wiring"] = gz_wiring.build_context(blob, spec.get("wiring_lengths") or {}, spec.get("wiring_manual") or {})
    else:
        out["wiring"] = {"ready": False, "reason": "El cableado automático está disponible para sistemas Off-Grid, Híbridos y Grid Zero.",
                         "branches": []}
    return out
