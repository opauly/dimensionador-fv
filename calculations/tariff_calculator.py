"""
Monthly electricity bill estimator using ARESEP tariff structure.

Formula:
  energy_charge = sum of tiered kWh × rate_crc per tier (T-RE: consumption
                  blocks; T-CO: a single flat rate — see below)
  fixed_charge  = access_charge_crc
  total         = fixed_charge + energy_charge

── Deliberately excludes bomberos, alumbrado público, IVA, and Generación
Distribuida charges (DER/COA/CVG/IOS) -- Oscar's explicit direction
(2026-09-02) ─────────────────────────────────────────────────────────────
Real CNFL invoices (validated against 6 bills across two customers, one with
a full itemized breakdown for three separate months) confirmed every one of
these is messier than a static tariff table can responsibly hold:

  Bomberos is bracket-dependent, not a flat percentage -- two real customers
    at different consumption levels implied 0.68% and 2.1-2.4% respectively,
    and even the SAME customer's rate moved between months.
  Alumbrado público (confirmed ¢3.02/kWh, apparently CNFL-wide) and IOS
    (Impuesto Otros Servicios, flat monthly) are real charges, but only
    verified for CNFL -- no data for any other distributor.
  COA/CVG (Generación Distribuida access charges) don't scale with kWh and
    are revised by periodic ARESEP resolution: two real bills for the exact
    same 410 kWh had COA of ¢9,085 and ¢14,020, a 54% swing with zero change
    in consumption. DER (Recursos Energéticos Distribuidos) was never
    modeled at all, even before this simplification.
  IVA (13%) itself isn't hard to compute, but it taxes a subtotal built from
    all of the above -- keeping it while stripping everything it was taxing
    would just misprice it differently, not more simply.

Rather than keep chasing partial, CNFL-only, sometimes-contradicted values
for all of this, the formula now estimates only the two components with
real month-to-month stability and (for CNFL, at least) real-invoice
confirmation: the tiered/flat energy rate and the fixed access charge. Every
caller showing this estimate to a client (Grid Zero/Hybrid proposals, the
solar-savings-table skill) must say so -- see their own docstrings/SKILL.md
for the exact disclaimer text to carry through to the client-facing
document. `database/tariffs_db.py`'s `alumbrado_publico_rate_crc`/
`ios_monthly_crc`/`coa_monthly_crc`/`cvg_monthly_crc`/`bomberos_pct`/
`iva_threshold_kwh` columns are left in place as reference data (some of it
real-invoice-confirmed for CNFL) for whenever this gets revisited, but
nothing in this module reads them anymore.

`demand_rate_crc`/`demand_threshold_kw` are the same story for a different
reason: they're ARESEP's real, official T-CO demand-charge structure (see
`aresep/tariff_parser.py`'s docstring), but real invoices show it's never
actually billed to Pauly & Co's typical <100kW single-phase commercial
client, so this module ignores them too. `access_charge_crc`/`tiers` for
T-CO, by contrast, ARE read here, and were deliberately hand-corrected away
from ARESEP's raw published values to match those same invoices -- don't
let a routine ARESEP sync silently overwrite them back (see
pages/05_admin.py's tariff-sync tool).
"""
from __future__ import annotations


def estimate_bill_crc(kwh: float, tariff_info: dict) -> float:
    """
    Estimate monthly electricity bill (₡) from consumption and tariff --
    energy charge (tiered or flat) plus the fixed access charge only. See
    this module's docstring for what's deliberately excluded and why.

    Args:
        kwh: Monthly consumption in kWh.
        tariff_info: Dict with keys:
            access_charge_crc,
            tiers: list of {from_kwh, to_kwh, rate_crc, is_fixed, sort_order}

    Returns:
        Estimated total bill in CRC, rounded to nearest colón.
    """
    fixed_charge = float(tariff_info.get("access_charge_crc") or 0)
    if kwh <= 0:
        return round(fixed_charge)

    tiers = sorted(tariff_info.get("tiers") or [], key=lambda t: t.get("sort_order", 0))
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

    return round(fixed_charge + energy_charge)


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
