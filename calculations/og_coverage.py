"""Off-Grid's shared "monthly coverage + battery-SoC simulation" helper.
Phase 20 Step 8 (PLAN_PHASE20_PROPOSALS_JINJA.md's Off-Grid Step 6 build
step) — moved **verbatim** out of `wizard/off_grid.py` (previously a
module-private `_og_monthly_coverage_and_sim()`), because the plan requires
this stay **one** implementation shared by three call sites that did not
previously share a module: the Flask wizard's Step 6 live preview
(`webapp/wizard_steps/og_s6_equipment.py`), a future Off-Grid Step 8's
summary KV, and `proposals/generator.py`'s PDF chart data. Putting it in
`wizard/off_grid.py` (a Streamlit-importing module) would have forced any of
those non-Streamlit callers to import Streamlit transitively — the same
reason `ai/daytime_fraction.py` and `webapp/figures.py` exist.

This is a *move*, not a rewrite: the body is unchanged (same fallback logic,
same monthly aggregation) so `main`'s Streamlit behaviour is identical —
`wizard/off_grid.py` now imports this function under its old private name
instead of defining it.
"""
from __future__ import annotations


def og_monthly_coverage_and_sim(
    array: dict, battery: dict, battery_bank: dict, consumption: dict, site: dict,
) -> tuple[dict, dict | None]:
    """
    Real day-by-day simulation (calculations/sizing_off_grid.py:
    simulate_battery_soc()) against the site's real PVGIS reference year —
    shared by the PDF's "Cobertura mensual" chart, Step 8's "Aprovechamiento
    solar" summary, and Step 6's live preview of the same chart (called with
    that step's currently-selected scenario/manual array and battery_bank,
    not the final persisted equipment). One implementation so all three stay
    numerically identical instead of drifting into separate approximations.

    Falls back to a coarse monthly-average approximation (no `recharge` key,
    no utilization sim) when the draft has no cached daily series — e.g. an
    older draft from before fetch_daily_series() existed.

    Returns (monthly_coverage_dict_for_pdf, sim_dict_or_None).
    """
    import calendar as _cal

    kw = array.get("array_kw", 0)
    daily = consumption.get("daily_kwh", 0)
    pvgis_daily_blob = site.get("pvgis_daily") or {}
    pvgis_daily = pvgis_daily_blob.get("daily_kwh_kwp", [])
    pvgis_daily_year = pvgis_daily_blob.get("year")
    monthly_coverage: dict = {}
    sim = None

    if pvgis_daily and pvgis_daily_year and len(pvgis_daily) >= 300:
        from calculations.sizing_off_grid import simulate_battery_soc

        daily_gen = [v * kw * 0.80 for v in pvgis_daily]
        capacity_kwh = battery_bank.get("total_kwh_installed", 0)
        dod_pct = battery.get("dod_pct", 80)
        sim = (
            simulate_battery_soc(daily_gen, daily, capacity_kwh, dod_pct, 100 - dod_pct)
            if capacity_kwh > 0 else None
        )
        if sim:
            days_in_month = [_cal.monthrange(pvgis_daily_year, m)[1] for m in range(1, 13)]
            gen_m, cons_m, rec_m, idx = [], [], [], 0
            for d in days_in_month:
                gen_m.append(round(sum(daily_gen[idx:idx + d]), 1))
                cons_m.append(round(daily * d, 1))
                rec_m.append(round(sum(sim["daily_charge_in_kwh"][idx:idx + d]), 1))
                idx += d
            monthly_coverage = {"generation": gen_m, "consumption": cons_m, "recharge": rec_m}

    if not monthly_coverage:
        pvgis_monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp", [])
        if pvgis_monthly and len(pvgis_monthly) == 12:
            from datetime import date as _dt
            days = [_cal.monthrange(_dt.today().year, m)[1] for m in range(1, 13)]
            monthly_coverage = {
                "generation": [round(v * kw * 0.80, 1) for v in pvgis_monthly],
                "consumption": [round(daily * d, 1) for d in days],
            }

    return monthly_coverage, sim
