"""
Grid Zero system sizing: system kW, panel count, monthly generation table,
net consumption, and monthly savings. Phase 2.

Validation target (María José Castro):
    avg_kwh=1475, irradiance=..., panel_wp=620, scenario_B
    → system_kw=?, panels=?, generation=1262 kWh/mo, new_consumption=521, savings=₡106,192/mo
"""


def size_system(
    avg_kwh_month: float,
    monthly_irradiance_kwh_kwp: list[float],
    panel_wp: int,
    panel_count: int,
    system_losses_pct: float = 0.14,
) -> dict:
    """
    Returns:
        system_kw, panel_count, monthly_generation (list[12]),
        avg_generation_kwh, avg_net_consumption_kwh
    """
    raise NotImplementedError("Phase 2")


def monthly_savings_table(
    monthly_kwh: list[float],
    monthly_generation: list[float],
    tariff_type: dict,
    tiers: list[dict],
    exchange_rate: float,
) -> list[dict]:
    """
    Per-month comparison: old bill vs new bill vs savings (CRC and USD).
    Returns list of 12 dicts with month, kwh, generation, net_kwh,
    old_bill_crc, new_bill_crc, savings_crc, savings_usd.
    """
    raise NotImplementedError("Phase 2")
