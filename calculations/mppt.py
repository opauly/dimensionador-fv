from __future__ import annotations
"""
MPPT string design validator. Generates 3 scenarios (A/B/C) per inverter. Phase 2.
"""


def validate_string_design(
    panel: dict,
    inverter: dict,
    target_system_kw: float | None = None,
) -> list[dict]:
    """
    Generate 3 MPPT scenarios for the given panel + inverter combination.

    Each scenario tries a different number of panels per string and strings in parallel,
    keeping Voc within inverter Vmax and Vmp within MPPT window.

    Returns list of 3 dicts, each with:
        scenario: 'A' | 'B' | 'C'
        panels_per_string: int
        strings: int
        total_panels: int
        system_kw: float
        voc_total: float
        vmp_total: float
        isc_total: float
        within_limits: bool
        notes: str
    """
    raise NotImplementedError("Phase 2")
