"""
Standalone solar bill-savings calculator for the Apps Script PDF report generator.

Self-contained copy of the tariff logic used by the main tool
(calculations/tariff_calculator.py + the zero-export savings model in
wizard/grid_zero.py::_scenario_projection). No imports from this project —
safe to hand off to another codebase as a single file.

Usage (CLI):
    python solar_tariff_savings.py input.json

    input.json:
    {
      "daily_kwh_generated": 42.0,
      "daily_kwh_consumed": 49.2,
      "daytime_fraction": 0.45,
      "tariff_info": {
        "access_charge_crc": 1500,
        "bomberos_pct": 0.0175,
        "iva_threshold_kwh": 280,
        "tiers": [
          {"from_kwh": 0, "to_kwh": 200, "rate_crc": 85.5, "is_fixed": false, "sort_order": 1},
          {"from_kwh": 200, "to_kwh": null, "rate_crc": 105.2, "is_fixed": false, "sort_order": 2}
        ]
      }
    }

Usage (as a module):
    from solar_tariff_savings import calculate_solar_savings
    result = calculate_solar_savings(
        daily_kwh_generated=42.0,
        daily_kwh_consumed=49.2,
        tariff_info=tariff_info,
        daytime_fraction=0.45,
    )
"""
from __future__ import annotations

import json
import sys

DAYS_PER_MONTH = 30
_IVA_RATE = 0.13
_DEFAULT_DAYTIME_FRACTION = 0.45


def estimate_bill_crc(kwh: float, tariff_info: dict) -> float:
    """
    Estimate a monthly electricity bill (CRC) from consumption and tariff structure.

    Args:
        kwh: Monthly consumption in kWh.
        tariff_info: Dict with keys:
            access_charge_crc, bomberos_pct, iva_threshold_kwh,
            tiers: list of {from_kwh, to_kwh, rate_crc, is_fixed, sort_order}

    Returns:
        Estimated total bill in CRC, rounded to the nearest colón.
    """
    if kwh <= 0:
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


def calculate_solar_savings(
    daily_kwh_generated: float,
    daily_kwh_consumed: float,
    tariff_info: dict,
    daytime_fraction: float = _DEFAULT_DAYTIME_FRACTION,
) -> dict:
    """
    Estimate the monthly bill savings from solar generation, given overall
    daily kWh generated and consumed (zero-export / Grid Zero model — no
    energy is fed back to the grid; excess solar beyond daytime consumption
    is curtailed).

      avg_kwh       = daily_kwh_consumed  × 30   (monthly consumption before solar)
      gen            = daily_kwh_generated × 30   (monthly generation)
      daytime_kwh   = avg_kwh × daytime_fraction  (consumption during solar hours)
      self_consumed = min(gen, daytime_kwh)       (solar actually used on-site)
      curtailed     = max(0, gen − daytime_kwh)   (solar that can't be absorbed)
      grid_kwh      = avg_kwh − self_consumed     (still drawn from grid, always > 0)

    Args:
        daily_kwh_generated: Average daily solar generation, in kWh.
        daily_kwh_consumed: Average daily consumption, in kWh.
        tariff_info: Same shape as used by estimate_bill_crc().
        daytime_fraction: Fraction of daily consumption that occurs during
            solar hours (7am-5pm). Defaults to 0.45.

    Returns:
        Dict with monthly figures: avg_kwh, gen, grid_kwh, curtailed,
        coverage_pct, self_consumption_pct, old_bill_crc, new_bill_crc,
        monthly_savings_crc.
    """
    avg_kwh = daily_kwh_consumed * DAYS_PER_MONTH
    gen = daily_kwh_generated * DAYS_PER_MONTH

    daytime_kwh = avg_kwh * daytime_fraction
    self_consumed = min(gen, daytime_kwh)
    curtailed = max(0.0, gen - daytime_kwh)
    grid_kwh = max(0.0, avg_kwh - self_consumed)

    coverage_pct = round(self_consumed / avg_kwh * 100, 1) if avg_kwh > 0 else 0.0
    self_consumption_pct = round(self_consumed / gen * 100, 1) if gen > 0 else 0.0

    old_bill = estimate_bill_crc(avg_kwh, tariff_info)
    new_bill = estimate_bill_crc(grid_kwh, tariff_info)
    monthly_savings = max(0, round(old_bill - new_bill))

    return {
        "avg_kwh": round(avg_kwh),
        "gen": round(gen),
        "grid_kwh": round(grid_kwh),
        "curtailed": round(curtailed),
        "coverage_pct": coverage_pct,
        "self_consumption_pct": self_consumption_pct,
        "old_bill_crc": int(old_bill),
        "new_bill_crc": int(new_bill),
        "monthly_savings_crc": int(monthly_savings),
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python solar_tariff_savings.py <input.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as f:
        payload = json.load(f)

    result = calculate_solar_savings(
        daily_kwh_generated=float(payload["daily_kwh_generated"]),
        daily_kwh_consumed=float(payload["daily_kwh_consumed"]),
        tariff_info=payload["tariff_info"],
        daytime_fraction=float(payload.get("daytime_fraction", _DEFAULT_DAYTIME_FRACTION)),
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
