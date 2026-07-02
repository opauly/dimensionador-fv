"""
Off-Grid system sizing: battery bank, array, discharge %, split-phase check. Phase 5.

Validation target (Jorge Ramírez):
    8 × 620W, 2 × Pylontech US5000C, Victron MPPT 250/100, Victron MultiPlus 5000VA
    → 5.0 kW, 16 m², 6.38 kWh/day, 9.60 kWh @10h, 66.46% discharge, $10,320, $2.08/Wp
"""


def size_battery_bank(
    daily_kwh: float,
    autonomy_days: int,
    dod_pct: int,
    battery_voltage_v: float,
    battery_capacity_kwh: float,
) -> dict:
    """
    Returns: total_kwh_needed, battery_count, total_kwh_installed,
             discharge_pct, voltage_bank
    """
    raise NotImplementedError("Phase 5")


def size_array(
    daily_kwh: float,
    avg_peak_sun_hours: float,
    panel_wp: int,
    system_losses_pct: float = 0.20,
) -> dict:
    """
    Returns: array_kw, panel_count, area_m2
    """
    raise NotImplementedError("Phase 5")


def check_split_phase(inverter: dict, output_v_required: float) -> dict:
    """
    Returns: requires_split_phase (bool), autotransformer_needed (bool), warning_message (str)
    """
    raise NotImplementedError("Phase 5")
