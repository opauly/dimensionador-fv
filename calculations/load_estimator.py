"""
3-scenario load estimation from tablero data. Phase 5.

Scenarios (demand_factor, peak_hours):
    Conservative: 40% / 6h
    Optimal:      55% / 8h
    Maximum:      75% / 10h
"""


def estimate_from_tablero(total_kva: float, demand_factor: float = None) -> list[dict]:
    """
    Args:
        total_kva: Total installed capacity from tablero in kVA.
        demand_factor: Override; if None, returns all 3 scenarios.

    Returns list of scenario dicts with:
        name, demand_factor, peak_hours, daily_kwh, monthly_kwh,
        label (str for display)
    """
    raise NotImplementedError("Phase 5")
