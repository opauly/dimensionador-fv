"""
Monthly electricity bill estimator using ARESEP tariff structure.

Formula (Costa Rica residential T-RE):
  energy_charge  = sum of tiered kWh × rate_crc per tier
  fixed_charge   = access_charge_crc
  bomberos       = (energy_charge + fixed_charge) × bomberos_pct
  subtotal       = fixed_charge + energy_charge + bomberos
  iva            = subtotal × 0.13  if kwh >= iva_threshold_kwh, else 0
  total          = subtotal + iva
"""
from __future__ import annotations

_IVA_RATE = 0.13


def estimate_bill_crc(kwh: float, tariff_info: dict) -> float:
    """
    Estimate monthly electricity bill (₡) from consumption and tariff.

    Args:
        kwh: Monthly consumption in kWh.
        tariff_info: Dict with keys:
            access_charge_crc, bomberos_pct, iva_threshold_kwh,
            tiers: list of {from_kwh, to_kwh, rate_crc, is_fixed, sort_order}

    Returns:
        Estimated total bill in CRC, rounded to nearest colón.
    """
    if kwh <= 0:
        # Access charge + bomberos still apply even at 0 kWh
        fixed = float(tariff_info.get("access_charge_crc") or 0)
        bomberos = fixed * float(tariff_info.get("bomberos_pct") or 0)
        return round(fixed + bomberos)

    tiers = sorted(tariff_info.get("tiers") or [], key=lambda t: t.get("sort_order", 0))
    fixed_charge = float(tariff_info.get("access_charge_crc") or 0)
    bomberos_pct = float(tariff_info.get("bomberos_pct") or 0)
    iva_threshold = int(tariff_info.get("iva_threshold_kwh") or 9999)

    energy_charge = 0.0
    for tier in tiers:
        if tier.get("is_fixed"):
            energy_charge += float(tier["rate_crc"])
            continue
        from_k = int(tier.get("from_kwh") or 0)
        to_k = tier.get("to_kwh")  # None means unlimited
        if kwh <= from_k:
            continue
        tier_kwh = (min(kwh, to_k) - from_k) if to_k is not None else (kwh - from_k)
        energy_charge += tier_kwh * float(tier["rate_crc"])

    bomberos = (fixed_charge + energy_charge) * bomberos_pct
    subtotal = fixed_charge + energy_charge + bomberos
    iva = subtotal * _IVA_RATE if kwh >= iva_threshold else 0.0
    return round(subtotal + iva)


def estimate_blended_effective_rate_crc(monthly_kwh: float,
                                        tariff_infos: list[dict]) -> float | None:
    """Effective ₡/kWh averaged across several tariffs at the same consumption
    level — used by the VRM weekly report for a Costa Rica site with no known
    distributor, so a real number can be shown without asking which utility a
    customer is on.

    Averages the *result* (bill ÷ kWh) rather than merging tier structures: CR
    distributors don't share tier boundaries, so there's no principled way to
    combine the tiers themselves, but every one of them reduces to a single
    effective rate at a given consumption level, and those rates ARE
    comparable and can be averaged.
    """
    if monthly_kwh <= 0 or not tariff_infos:
        return None
    rates = [estimate_bill_crc(monthly_kwh, t) / monthly_kwh for t in tariff_infos]
    return sum(rates) / len(rates)


def fill_bill_amounts(history: list[dict], tariff_info: dict) -> list[dict]:
    """
    Return a copy of history with bill_crc estimated from tariff for every month.

    Replaces null/0 bill_crc values; preserves existing non-zero values
    (those come from the actual PDF bill).
    """
    result = []
    for h in history:
        existing = h.get("bill_crc")
        if existing and float(existing) > 0:
            result.append(dict(h))
        else:
            computed = estimate_bill_crc(float(h.get("kwh") or 0), tariff_info)
            result.append({**h, "bill_crc": computed})
    return result
