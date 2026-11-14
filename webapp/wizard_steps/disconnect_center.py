"""AC protection layout: breaker on the DIN rail in the gabinete, a load center ("centro de carga"), or no breaker.

Oscar's rules (2026-11-13):
  * Hybrid / off-grid, AC OUT of the Victron units, and AC IN (grid input to the Victron units): each place is one of
        "din"     breakers on the DIN rail inside the gabinete (what the list always had; the default),
        "center"  a load center that REPLACES those breakers: every inverter lands on its own breaker, the bus joins them and ONE feeder
                  leaves towards the sub-panel (AC OUT) or arrives from the grid (AC IN), sized for the sum,
        "none"    no breaker on the list (the client already has them).
    120 V Victron units go in PAIRS: two of them share one 2-pole breaker.
  * AC-coupled Fronius: its output goes to the AC OUT load center ("center") or straight to the critical-loads sub-panel ("subpanel").
  * Grid Zero keeps the breaker in the generation meter base; an extra small load center next to the Fronius is optional (`enabled`): one 2P
    breaker per Fronius + a 2P 20 A one that feeds the Smart Meter. It does not replace the base.

The choice is a small dict kept in the same two homes as the PV coupling: `blob["scratch"]["disconnect"]` for a quote being built,
`projects.tech_spec["disconnect"]` for a won project.

    {"enabled": bool,                       # Grid Zero extra load center
     "ac_out": "din"|"center"|"none", "ac_in": "din"|"center"|"none", "fronius_to": "subpanel"|"center"}
"""
from __future__ import annotations

SCRATCH_KEY = "disconnect"
FORM_MARK = "disc_form"          # hidden field: an unchecked checkbox sends nothing, so the form carries a marker
LENGTH_KEY = "disc_m"            # inverter -> AC OUT load center (or Fronius -> Grid Zero load center), metres
LENGTH_IN_KEY = "disc_in_m"      # AC IN load center -> inverter, metres
LENGTH_LABEL = "Inversor → centro de carga de desconexión"
LENGTH_LABEL_AC = "Inversor FV → centro de carga de desconexión"
MODES = ("din", "center", "none")
FRONIUS_TO = ("subpanel", "center")
BOX_SPACES = (2, 4, 8)            # NEMA 3R load centers in the catalog
METER_BREAKER_A = 20             # Smart Meter feed breaker: 2 poles, 20 A


def clean(saved: dict | None) -> dict:
    saved = saved or {}
    return {
        "enabled": bool(saved.get("enabled")),
        "ac_out": saved.get("ac_out") if saved.get("ac_out") in MODES else "din",
        "ac_in": saved.get("ac_in") if saved.get("ac_in") in MODES else "din",
        "fronius_to": saved.get("fronius_to") if saved.get("fronius_to") in FRONIUS_TO else "subpanel",
    }


def from_form(form) -> dict | None:
    """The protection fields of the wiring form, or None when the form does not carry them (an older page posting only cable lengths must
    not reset the choice)."""
    if FORM_MARK not in form:
        return None
    return clean({
        "enabled": form.get("disc_enabled") in ("1", "on", "true"),
        "ac_out": form.get("disc_ac_out"), "ac_in": form.get("disc_ac_in"), "fronius_to": form.get("disc_fronius"),
    })


def from_blob(blob: dict) -> dict:
    return clean(((blob or {}).get("scratch") or {}).get(SCRATCH_KEY))


def resolve(saved: dict | None, system_type: str | None, ac_coupled: bool = False, show_ac_in: bool = True) -> dict:
    """What applies to this design. `can_gz`: Grid Zero extra center; `can_ac`: Victron AC OUT / AC IN selectors; `can_fronius`: AC-coupled
    Fronius destination. `enabled` is the Grid Zero center; `ac_out` / `ac_in` / `fronius_to` are the effective modes."""
    cfg = clean(saved)
    grid_zero = system_type == "grid_zero"
    can_ac = system_type in ("off_grid", "hybrid")
    ac_out = cfg["ac_out"] if can_ac else "din"
    ac_in = cfg["ac_in"] if can_ac and show_ac_in else "din"
    fronius_to = "center" if (can_ac and ac_coupled and ac_out == "center" and cfg["fronius_to"] == "center") else "subpanel"
    return {
        "can": grid_zero, "can_gz": grid_zero, "can_ac": can_ac, "can_fronius": bool(can_ac and ac_coupled and ac_out == "center"),
        "can_ac_in": bool(can_ac and show_ac_in),
        "enabled": bool(grid_zero and cfg["enabled"]),
        "ac_out": ac_out, "ac_in": ac_in, "fronius_to": fronius_to,
        "out_center": ac_out == "center", "in_center": ac_in == "center",
    }


def box_spaces(breakers_2p: int) -> tuple[int, int]:
    """(spaces per box, boxes) for that many 2-pole breakers: the smallest catalog box that holds them, several of the largest beyond that."""
    need = 2 * max(1, int(breakers_2p))
    for s in BOX_SPACES:
        if need <= s:
            return s, 1
    top = BOX_SPACES[-1]
    return top, -(-need // top)
