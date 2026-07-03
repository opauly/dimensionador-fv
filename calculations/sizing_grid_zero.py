"""
Grid Zero system sizing: system kW, panel count, monthly generation table,
net consumption, and monthly savings. Phase 2.

Validation target (María José Castro):
    avg_kwh=1475, irradiance monthly avg≈127.2 kWh/kWp, panel_wp=620, 16 panels
    → system_kw=9.92, avg_generation≈1262 kWh/mo, avg_net≈521 kWh/mo

Note: monthly_irradiance_kwh_kwp values from PVGIS already include system losses
(14% derating passed to the API), so no additional loss factor is applied here.
"""
from __future__ import annotations

MONTHS_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]
MONTHS_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


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
    system_kw = round(panel_count * panel_wp / 1000, 3)

    # PVGIS E_m already has losses baked in (passed loss=14 to API)
    monthly_gen = [round(system_kw * irr, 2) for irr in monthly_irradiance_kwh_kwp]

    # Net consumption month by month: capped at 0 (Grid Zero = no export credit)
    monthly_net = [max(0.0, avg_kwh_month - gen) for gen in monthly_gen]

    avg_gen = round(sum(monthly_gen) / 12, 2)
    avg_net = round(sum(monthly_net) / 12, 2)

    return {
        "system_kw": round(system_kw, 2),
        "panel_count": panel_count,
        "monthly_generation": monthly_gen,
        "monthly_net_consumption": monthly_net,
        "avg_generation_kwh": avg_gen,
        "avg_net_consumption_kwh": avg_net,
    }


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
    from calculations.tariffs import calculate_bill

    rows = []
    for i, (kwh, gen) in enumerate(zip(monthly_kwh, monthly_generation)):
        net_kwh = max(0.0, kwh - gen)
        old_bill = calculate_bill(kwh, tariff_type, tiers)["total_crc"]
        new_bill = calculate_bill(net_kwh, tariff_type, tiers)["total_crc"]
        savings_crc = old_bill - new_bill
        savings_usd = round(savings_crc / exchange_rate, 2) if exchange_rate else 0.0

        rows.append({
            "month_es": MONTHS_ES[i],
            "month_en": MONTHS_EN[i],
            "kwh": kwh,
            "generation": round(gen, 2),
            "net_kwh": round(net_kwh, 2),
            "old_bill_crc": old_bill,
            "new_bill_crc": new_bill,
            "savings_crc": savings_crc,
            "savings_usd": savings_usd,
        })

    return rows


def compute_avg_billing(
    monthly_kwh: list[float],
    monthly_generation: list[float],
    tariff_type: dict,
    tiers: list[dict],
    exchange_rate: float,
) -> dict:
    """
    Returns the averaged billing row used in the PDF billing_avg section.
    """
    rows = monthly_savings_table(monthly_kwh, monthly_generation, tariff_type, tiers, exchange_rate)
    n = len(rows)

    avg_kwh = round(sum(r["kwh"] for r in rows) / n, 2)
    avg_gen = round(sum(r["generation"] for r in rows) / n, 2)
    avg_net = round(sum(r["net_kwh"] for r in rows) / n, 2)
    avg_old_bill = round(sum(r["old_bill_crc"] for r in rows) / n)
    avg_new_bill = round(sum(r["new_bill_crc"] for r in rows) / n)
    avg_savings_crc = avg_old_bill - avg_new_bill
    avg_savings_usd = round(avg_savings_crc / exchange_rate, 2) if exchange_rate else 0.0
    pct_savings = round(avg_savings_crc / avg_old_bill * 100, 2) if avg_old_bill else 0.0

    return {
        "consumption_kwh": avg_kwh,
        "bill_crc": avg_old_bill,
        "generation_kwh": avg_gen,
        "new_consumption_kwh": avg_net,
        "new_bill_crc": avg_new_bill,
        "savings_crc": avg_savings_crc,
        "savings_usd": avg_savings_usd,
        "pct_savings": pct_savings,
    }
