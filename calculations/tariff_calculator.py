"""
Monthly electricity bill estimator using ARESEP tariff structure.

Formula (Costa Rica residential T-RE):
  energy_charge  = sum of tiered kWh × rate_crc per tier
  fixed_charge   = access_charge_crc
  alumbrado      = kwh × alumbrado_publico_rate_crc
  ios            = ios_monthly_crc (flat -- see below)
  bomberos       = (energy_charge + fixed_charge) × bomberos_pct
  subtotal       = fixed_charge + energy_charge + alumbrado + ios + bomberos
  iva            = subtotal × 0.13  if kwh >= iva_threshold_kwh, else 0
  total          = subtotal + iva
  [+ gd_charges, only if include_gd_charges=True -- see below]

── Extra CNFL bill charges, confirmed against real invoices ───────────────
Two real CNFL customers' full itemized bills (Rainforest Lab / Casa Garleo
S.A., NISE 28487956, three months Jan/Apr/Aug 2026; and a second, unrelated
commercial customer, NISE 27967117, Aug 2026 -- confirmed NOT running solar:
no DER/COA/CVG line items at all) surfaced charges this formula didn't have
fields for. They split into two groups:

ALWAYS applies, any customer (added to `alumbrado`/`ios_monthly_crc` above):
  Alumbrado Público -- flat ¢/kWh, printed directly on every CNFL invoice.
  IOS (Impuesto Otros Servicios) -- flat monthly, NOT a function of COA
    despite an earlier version of this formula deriving it as 13% of COA:
    that held within ¢3 across the three Rainforest Lab bills, but the
    second (non-solar) customer's real IOS of ¢1,460 falsified it outright
    (COA=0 there predicts IOS=0). No formula fit across the 4 real data
    points gathered so far, so it's modeled the same way as alumbrado: a
    flat monthly figure from the caller, `ios_monthly_crc`, defaulting to 0
    ("unverified for this row," not "genuinely zero" -- see
    database/migrations/036_ios_charge.sql).

Generación Distribuida-ONLY (a customer without solar isn't enrolled and
doesn't pay these -- opt-in via `include_gd_charges`, see below):
  DER (Recursos Energéticos Distribuidos) -- flat ¢3,220 in all three
    Rainforest Lab bills, regardless of kWh. Deliberately NEVER modeled
    here, at Oscar's explicit direction (2026-09-02) -- a deliberate
    simplification, not an oversight, in either direction.
  COA (Costo de Acceso Generación Distribuida) -- the big one, ¢9,085-
    ¢14,020 across the three real bills despite two of them billing the
    exact same 410 kWh (a 54% swing with zero change in consumption). An
    ARESEP pass-through revised by periodic resolution, not a function of
    kWh -- modeled as `coa_monthly_crc`, a flat monthly figure the caller
    supplies (see database/migrations/035_gd_access_charges.sql).
  CVG (Costo Variable Generación) -- present in one of the three real bills
    (¢8,480) and entirely absent from the other two. Modeled the same way,
    `cvg_monthly_crc` -- in practice set this to a long-run monthly AVERAGE
    across months it appears and months it doesn't, since there's no known
    trigger condition for which months it applies to.

`include_gd_charges` defaults to False, matching the two contexts where this
formula is used most:
  - The WITHOUT-solar counterfactual (`victron/savings.py`, and the "old
    bill" side of the Grid Zero/Hybrid wizards) is correct to exclude
    DER/COA/CVG -- a site without solar was never enrolled in Generación
    Distribuida. (Alumbrado and IOS still apply either way -- they're in
    the base formula above, not gated.)
  - Whenever a real bill is available for a site actually running solar
    (a maintenance report backed by actual invoices), prefer that real
    number outright over any estimate -- no formula, gd-charges-inclusive or
    not, beats an actual invoice.
Pass `include_gd_charges=True` specifically for the WITH-solar projection in
a Grid Zero/Hybrid PROPOSAL (a prospective client who doesn't have a real
post-solar bill yet to prefer instead) -- otherwise that projection promises
a lower post-solar bill, and therefore more savings, than the client will
actually see once COA/CVG start showing up on their real invoices.
"""
from __future__ import annotations

_IVA_RATE = 0.13


def estimate_bill_crc(kwh: float, tariff_info: dict, include_gd_charges: bool = False) -> float:
    """
    Estimate monthly electricity bill (₡) from consumption and tariff.

    Args:
        kwh: Monthly consumption in kWh.
        tariff_info: Dict with keys:
            access_charge_crc, bomberos_pct, iva_threshold_kwh,
            alumbrado_publico_rate_crc (₡/kWh, defaults to 0 -- see
            database/migrations/034_alumbrado_publico.sql; a 0 here means
            "not yet verified for this distributor/area," not "genuinely
            zero"),
            ios_monthly_crc (₡/month flat, always applied when set -- see
            database/migrations/036_ios_charge.sql; same "0 means
            unverified" convention),
            coa_monthly_crc, cvg_monthly_crc (₡/month flat, only read when
            include_gd_charges=True -- see database/migrations/
            035_gd_access_charges.sql),
            tiers: list of {from_kwh, to_kwh, rate_crc, is_fixed, sort_order}
        include_gd_charges: adds COA + CVG (flat monthly) on top of the base
            bill. See this module's docstring for when to set this True --
            DER is never modeled either way.

    Returns:
        Estimated total bill in CRC, rounded to nearest colón.
    """
    if kwh <= 0:
        # Access charge + IOS + bomberos still apply even at 0 kWh
        fixed = float(tariff_info.get("access_charge_crc") or 0)
        ios = float(tariff_info.get("ios_monthly_crc") or 0)
        bomberos = fixed * float(tariff_info.get("bomberos_pct") or 0)
        total = fixed + ios + bomberos
        if include_gd_charges:
            total += _gd_charges_crc(tariff_info)
        return round(total)

    tiers = sorted(tariff_info.get("tiers") or [], key=lambda t: t.get("sort_order", 0))
    fixed_charge = float(tariff_info.get("access_charge_crc") or 0)
    alumbrado_rate = float(tariff_info.get("alumbrado_publico_rate_crc") or 0)
    ios = float(tariff_info.get("ios_monthly_crc") or 0)
    bomberos_pct = float(tariff_info.get("bomberos_pct") or 0)
    # `or 9999` would silently discard a legitimate 0 (T-CO's real seeded
    # value, meaning "no exemption -- IVA always applies") since 0 is falsy;
    # `is None` distinguishes "explicitly 0" from "field absent."
    _iva_threshold_raw = tariff_info.get("iva_threshold_kwh")
    iva_threshold = 9999 if _iva_threshold_raw is None else int(_iva_threshold_raw)

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

    alumbrado = kwh * alumbrado_rate
    bomberos = (fixed_charge + energy_charge) * bomberos_pct
    subtotal = fixed_charge + energy_charge + alumbrado + ios + bomberos
    iva = subtotal * _IVA_RATE if kwh >= iva_threshold else 0.0
    total = subtotal + iva
    if include_gd_charges:
        total += _gd_charges_crc(tariff_info)
    return round(total)


def _gd_charges_crc(tariff_info: dict) -> float:
    """COA + CVG, both flat monthly. Never includes DER. IOS moved out of
    here (see this module's docstring) -- it applies unconditionally now,
    in the base formula above."""
    coa = float(tariff_info.get("coa_monthly_crc") or 0)
    cvg = float(tariff_info.get("cvg_monthly_crc") or 0)
    return coa + cvg


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
