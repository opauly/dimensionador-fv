"""
Tiered electricity bill calculator for Costa Rican ARESEP tariffs.
Handles: block tiers, IVA threshold (280 kWh), bomberos levy (1.75%). Phase 2.
"""


def calculate_bill(kwh: float, tariff_type: dict, tiers: list[dict]) -> dict:
    """
    Calculate monthly electricity bill.

    Args:
        kwh: Monthly consumption in kWh.
        tariff_type: Row from tariff_types table (access_charge_crc, bomberos_pct, iva_threshold_kwh).
        tiers: Rows from tariff_tiers table sorted by sort_order.

    Returns dict with:
        energy_charge_crc: Sum of tier charges.
        access_charge_crc: Fixed monthly charge.
        subtotal_crc: energy + access.
        bomberos_crc: 1.75% of subtotal.
        iva_crc: 13% on consumption above threshold (0 if below 280 kWh).
        total_crc: Final bill amount.
    """
    raise NotImplementedError("Phase 2")


def calculate_new_bill(new_kwh: float, tariff_type: dict, tiers: list[dict]) -> dict:
    """Same as calculate_bill but for post-solar net consumption."""
    raise NotImplementedError("Phase 2")
