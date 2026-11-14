"""Optional disconnect load center next to the Fronius ("centro de carga de desconexión").

A small 4-space load center placed at the output of the string inverter, so the Fronius can be cut off close to where it is.
Oscar's rule (2026-11-13): it is OPTIONAL per project, it does not replace the generation meter base, and it only exists where there
is a Fronius:
  * Grid Zero:            Fronius -> load center -> generation meter base (breaker 2P for the Fronius; a second 2P breaker feeds the Smart Meter)
  * AC-coupled hybrid:    Fronius -> load center -> critical-loads sub-panel (breaker 2P for the Fronius)

The choice is a tiny dict kept in the same two homes as the PV coupling: `blob["scratch"]["disconnect"]` for a quote being built,
`projects.tech_spec["disconnect"]` for a won project.

    {"enabled": bool}
"""
from __future__ import annotations

SCRATCH_KEY = "disconnect"
FORM_MARK = "disc_form"          # hidden field: an unchecked checkbox sends nothing, so the form carries a marker
LENGTH_KEY = "disc_m"            # Fronius -> load center, metres
LENGTH_LABEL = "Inversor → centro de carga de desconexión"
LENGTH_LABEL_AC = "Inversor FV → centro de carga de desconexión"
BREAKER_POLES = 2
SPACES = 4


def clean(saved: dict | None) -> dict:
    return {"enabled": bool((saved or {}).get("enabled"))}


def from_form(form) -> dict | None:
    """The disconnect field of the wiring form, or None when the form does not carry it (an older page posting only cable
    lengths must not reset the choice)."""
    if FORM_MARK not in form:
        return None
    return clean({"enabled": form.get("disc_enabled") in ("1", "on", "true")})


def from_blob(blob: dict) -> dict:
    return clean(((blob or {}).get("scratch") or {}).get(SCRATCH_KEY))


def resolve(saved: dict | None, can: bool) -> dict:
    """{'can': the design has a Fronius, 'enabled': chosen AND possible}."""
    return {"can": bool(can), "enabled": bool(can and clean(saved)["enabled"])}
