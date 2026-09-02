"""
Tiered electricity bill calculator for Costa Rican ARESEP tariffs. Phase 2.

Formula:
  energy_charge = sum of (kwh_in_tier × rate_crc) per tier block
  total = energy_charge + access_charge

Deliberately excludes bomberos, alumbrado público, IVA, and Generación
Distribuida charges (COA/CVG/DER/IOS) — same reasoning as
`calculations/tariff_calculator.py`'s docstring: real CNFL invoices showed
every one of these is either bracket-dependent, revised by periodic ARESEP
resolution, or only verified for a single distributor, so this estimates
only the two components with real month-to-month stability. Any caller
showing this to a client must carry that disclaimer through — see
`calculations/tariff_calculator.py`'s docstring for the exact reasoning.

This is a second, independent implementation of the same formula (used by
the Grid Zero proposal wizard/sizing, where `calculations/tariff_calculator.py`
is used by the VRM weekly report and other tools) -- kept in sync by hand for
now. Its tier-boundary convention (`_apply_tiers`'s `to_kwh - from_kwh + 1`,
inclusive of both ends) differs from `tariff_calculator.py`'s (`from_kwh`
exclusive), a pre-existing discrepancy between the two that predates this
change and is out of scope here.
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
    Calculate monthly electricity bill -- energy charge (tiered) plus the
    fixed access charge only. See this module's docstring for what's
    deliberately excluded and why.

    Args:
        kwh: Monthly consumption in kWh.
        tariff_type: Row from tariff_types table (access_charge_crc).
        tiers: Rows from tariff_tiers table sorted by sort_order.

    Returns dict with:
        energy_charge_crc: Sum of tier charges.
        access_charge_crc: Fixed monthly charge.
        total_crc: Final bill amount (energy + access).
    """
    energy = _apply_tiers(kwh, tiers)
    access = float(tariff_type.get("access_charge_crc", 0))
    total = energy + access

    return {
        "energy_charge_crc": round(energy),
        "access_charge_crc": round(access),
        "total_crc": round(total),
    }


def calculate_new_bill(new_kwh: float, tariff_type: dict, tiers: list[dict]) -> dict:
    """Same as calculate_bill -- kept as a separate name for call sites that
    read more clearly labeling a post-solar net-consumption bill as such."""
    return calculate_bill(new_kwh, tariff_type, tiers)
