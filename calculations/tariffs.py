"""
Tiered electricity bill calculator for Costa Rican ARESEP tariffs.
Handles: block tiers, IVA threshold (280 kWh), bomberos levy (1.75%). Phase 2.

Formula:
  energy_charge = sum of (kwh_in_tier × rate_crc) per tier block
  subtotal = energy_charge + access_charge
  bomberos = subtotal × bomberos_pct
  iva = subtotal × 0.13  (only if kwh > iva_threshold_kwh; applies to full subtotal)
  total = subtotal + bomberos + iva
"""


def _apply_tiers(kwh: float, tiers: list[dict]) -> float:
    """Apply block-rate tiers to kwh. Returns total energy charge in CRC."""
    tiers_sorted = sorted(tiers, key=lambda t: t["sort_order"])
    energy = 0.0
    remaining = kwh

    for tier in tiers_sorted:
        if remaining <= 0:
            break

        from_kwh = int(tier["from_kwh"])
        to_kwh = tier.get("to_kwh")
        rate = float(tier["rate_crc"])

        if to_kwh is None:
            # Unlimited top tier
            tier_kwh = remaining
        else:
            tier_width = int(to_kwh) - from_kwh + 1
            tier_kwh = min(remaining, tier_width)

        energy += tier_kwh * rate
        remaining -= tier_kwh

    return energy


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
        iva_crc: 13% on subtotal if kwh > threshold (0 otherwise).
        total_crc: Final bill amount.
    """
    energy = _apply_tiers(kwh, tiers)
    access = float(tariff_type.get("access_charge_crc", 0))
    subtotal = energy + access

    bomberos_pct = float(tariff_type.get("bomberos_pct", 0.0175))
    bomberos = subtotal * bomberos_pct

    iva_threshold = int(tariff_type.get("iva_threshold_kwh", 280))
    iva = subtotal * 0.13 if kwh > iva_threshold else 0.0

    total = subtotal + bomberos + iva

    return {
        "energy_charge_crc": round(energy),
        "access_charge_crc": round(access),
        "subtotal_crc": round(subtotal),
        "bomberos_crc": round(bomberos),
        "iva_crc": round(iva),
        "total_crc": round(total),
    }


def calculate_new_bill(new_kwh: float, tariff_type: dict, tiers: list[dict]) -> dict:
    """Same as calculate_bill but for post-solar net consumption."""
    return calculate_bill(new_kwh, tariff_type, tiers)
