from __future__ import annotations
"""
Estimated savings for the weekly report — replaces the "Tariff data coming
soon" placeholder with a real number, without ever asking which electric
company a site is on.

Two paths, chosen automatically from `sites.country` (already a column on
both `monitoring.sites` and `vrm.sites`, default 'CR'):

- **country == 'CR'**: runs the real ARESEP tiered bill formula
  (`calculations/tariff_calculator.py`) — the same engine the Grid Zero
  proposal calculator uses — blended across every seeded Costa Rica
  distributor's T-RE tariff into one effective ₡/kWh
  (`estimate_blended_effective_rate_crc`). This covers `monitoring` (Pauly &
  Co's own fleet, currently 100% Costa Rica) and any `vrm` site the operator
  hasn't marked otherwise, with zero configuration.
- **country != 'CR'**: uses `sites.savings_rate` / `savings_currency` — a
  flat rate the operator typed in at CSV upload (migration 014, `vrm.sites`
  only). If unset, savings are not shown. Never fabricated.

In both paths, savings = avoided grid purchase only:
`(load − grid import) × rate`. Exported energy is deliberately NOT counted —
export compensation (net metering vs net billing vs none at all) is a policy
variable that differs by country and even by Costa Rican distributor;
modeling it without knowing the specific policy risks a confidently wrong
number, which is worse than the honest gap this leaves for exporting sites.

`rate` itself is energy charge ÷ kWh only — see
`calculations/tariff_calculator.py`'s own docstring for why bomberos,
alumbrado público, IVA, and Generación Distribuida charges are excluded
from that formula entirely, not just from this weekly-report path.
"""
import time

from calculations.tariff_calculator import (
    estimate_bill_crc,
    estimate_blended_effective_rate_crc,
)

_CR_BLEND_CACHE: dict = {"tariffs": None, "fetched_at": 0.0}
_CR_BLEND_TTL_S = 3600  # matches config.EXCHANGE_RATE_CACHE_TTL's order of magnitude

CURRENCY_SYMBOLS = {"CRC": "₡", "USD": "$", "EUR": "€"}
SUPPORTED_FLAT_CURRENCIES = ["CRC", "USD", "EUR"]


def _cr_tariff_infos() -> list[dict]:
    """Every seeded CR distributor's T-RE tariff, process-cached for an hour.

    Confirmed (2026-07) all 8 seeded distributors have complete T-RE tiers, so
    no partial-data filtering beyond the defensive `tiers` check below.
    """
    now = time.time()
    cached = _CR_BLEND_CACHE["tariffs"]
    if cached is not None and now - _CR_BLEND_CACHE["fetched_at"] < _CR_BLEND_TTL_S:
        return cached

    from database import tariffs_db
    infos = []
    for d in tariffs_db.list_distributors():
        info = tariffs_db.get_tariff_info(d["abbreviation"], "T-RE")
        if info and info.get("tiers"):
            infos.append(info)
    _CR_BLEND_CACHE["tariffs"] = infos
    _CR_BLEND_CACHE["fetched_at"] = now
    return infos


def format_money(amount: float, currency: str) -> str:
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    # Colones aren't practically subdivided; other currencies get cents.
    return f"{symbol}{amount:,.0f}" if currency == "CRC" else f"{symbol}{amount:,.2f}"


def compute_weekly_savings(totals: dict, site: dict, num_days: int) -> dict | None:
    """`{"amount": float, "currency": str, "basis": str}`, or None if there's
    no basis to compute one (no CR tariff data, or no flat rate configured for
    a non-CR site) — the caller keeps the existing placeholder in that case.
    """
    offset_kwh = max(0.0, float(totals.get("load", 0)) - float(totals.get("grid", 0)))
    if offset_kwh <= 0 or num_days <= 0:
        return None

    country = (site.get("country") or "CR").strip().upper()

    if country == "CR":
        tariff_infos = _cr_tariff_infos()
        if not tariff_infos:
            return None
        monthly_equiv_kwh = totals["load"] / num_days * 30
        rate = estimate_blended_effective_rate_crc(monthly_equiv_kwh, tariff_infos)
        if not rate:
            return None
        return {
            "amount": round(offset_kwh * rate),
            "currency": "CRC",
            "basisCount": len(tariff_infos),
        }

    rate = site.get("savings_rate")
    currency = site.get("savings_currency")
    if not rate or not currency:
        return None
    return {
        "amount": round(offset_kwh * float(rate), 2),
        "currency": currency,
        "basisCount": None,
    }
