"""
Tiered electricity bill calculator for Costa Rican ARESEP tariffs.
Handles: block tiers, IVA threshold (280 kWh), bomberos levy, alumbrado
publico, IOS. Phase 2.

Formula:
  energy_charge = sum of (kwh_in_tier × rate_crc) per tier block
  alumbrado = kwh × alumbrado_publico_rate_crc
  subtotal = energy_charge + access_charge + alumbrado + ios_monthly_crc
  bomberos = subtotal × bomberos_pct
  iva = subtotal × 0.13  (only if kwh > iva_threshold_kwh; applies to full subtotal)
  total = subtotal + bomberos + iva

Same Generación Distribuida charge handling as `calculations/tariff_calculator.py`
-- see that module's docstring for the full reasoning (DER never modeled,
COA/CVG flat-monthly and opt-in via `include_gd_charges`; IOS is NOT
GD-specific — a real non-solar CNFL customer still carries it, so it's a
flat monthly figure applied unconditionally, like alumbrado, not gated
behind include_gd_charges), and for the alumbrado_publico_rate_crc/
ios_monthly_crc default of 0 meaning "unverified for this area," not
"genuinely zero."

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


def calculate_bill(
    kwh: float,
    tariff_type: dict,
    tiers: list[dict],
    include_gd_charges: bool = False,
) -> dict:
    """
    Calculate monthly electricity bill.

    Args:
        kwh: Monthly consumption in kWh.
        tariff_type: Row from tariff_types table (access_charge_crc, bomberos_pct, iva_threshold_kwh).
        tiers: Rows from tariff_tiers table sorted by sort_order.
        include_gd_charges: adds COA + CVG (flat monthly, from
            `tariff_type["coa_monthly_crc"]`/`["cvg_monthly_crc"]`). See
            `calculations/tariff_calculator.py`'s docstring for when to set
            this True. DER is never modeled either way.

    Returns dict with:
        energy_charge_crc: Sum of tier charges.
        access_charge_crc: Fixed monthly charge.
        alumbrado_publico_crc: Public lighting charge.
        ios_crc: Impuesto Otros Servicios (flat monthly, always applied).
        subtotal_crc: energy + access + alumbrado + ios.
        bomberos_crc: bomberos_pct of subtotal.
        iva_crc: 13% on subtotal if kwh > threshold (0 otherwise).
        gd_charges_crc: COA + CVG if include_gd_charges, else 0.
        total_crc: Final bill amount.
    """
    energy = _apply_tiers(kwh, tiers)
    access = float(tariff_type.get("access_charge_crc", 0))
    alumbrado = kwh * float(tariff_type.get("alumbrado_publico_rate_crc", 0) or 0)
    ios = float(tariff_type.get("ios_monthly_crc", 0) or 0)
    subtotal = energy + access + alumbrado + ios

    bomberos_pct = float(tariff_type.get("bomberos_pct", 0.0175))
    bomberos = subtotal * bomberos_pct

    iva_threshold = int(tariff_type.get("iva_threshold_kwh", 280))
    iva = subtotal * 0.13 if kwh > iva_threshold else 0.0

    gd_charges = 0.0
    if include_gd_charges:
        coa = float(tariff_type.get("coa_monthly_crc", 0) or 0)
        cvg = float(tariff_type.get("cvg_monthly_crc", 0) or 0)
        gd_charges = coa + cvg

    total = subtotal + bomberos + iva + gd_charges

    return {
        "energy_charge_crc": round(energy),
        "access_charge_crc": round(access),
        "alumbrado_publico_crc": round(alumbrado),
        "ios_crc": round(ios),
        "subtotal_crc": round(subtotal),
        "bomberos_crc": round(bomberos),
        "iva_crc": round(iva),
        "gd_charges_crc": round(gd_charges),
        "total_crc": round(total),
    }


def calculate_new_bill(new_kwh: float, tariff_type: dict, tiers: list[dict]) -> dict:
    """Same as calculate_bill but for post-solar net consumption -- defaults
    `include_gd_charges` to True, since a customer with solar under net
    metering IS enrolled in Generación Distribuida (unlike calculate_bill's
    default, which assumes the WITHOUT-solar case unless told otherwise)."""
    return calculate_bill(new_kwh, tariff_type, tiers, include_gd_charges=True)
