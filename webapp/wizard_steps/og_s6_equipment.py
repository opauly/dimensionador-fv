"""Off-Grid Step 6 — Equipos + reliability scenarios. Port of
wizard/off_grid.py:step6_equipment().

Per PLAN §1.3, `build_context(blob, vid=None)` is the one function every
route rendering any part of this step calls. `vid` is an optional, disclosed
extension of the plan's literal `build_context(blob)` signature (same
precedent as `gz_s8_review.build_context(blob, vid)`) — it is needed ONLY so
the lazy daily-PVGIS-series backfill (do-not-drop item 2's sibling note, see
`_resolve_pvgis_daily()`) can persist the fetched series back onto
`site.pvgis_daily` for a draft created before Step 3 started fetching it,
instead of silently re-fetching (a cheap Supabase cache read, not a PVGIS
network call — see calculations/pvgis.py:fetch_daily_series()) on every
single render forever. Every route below still funnels every render through
this one function.

KEY FINDING vs. the build plan's literal wording (reported back to the
orchestrator, not silently "fixed"): unlike Grid Zero's Step 6 (whose MPPT
scenarios need an expensive AI call and are therefore gated behind a
"Calcular configuración MPPT" button, cached in `scratch.s6.scenarios`),
Off-Grid's `generate_reliability_scenarios()` is a deterministic function of
already-persisted consumption/site data and the currently-selected
panel/charge-controller/battery — `wizard/off_grid.py:step6_equipment()`
(L997-1003) calls it on EVERY rerun, unconditionally, with no "Calcular"
button and no scenario caching. This port matches that: `_compute()` (and
therefore `build_context()`) recomputes `scenarios` fresh on every call,
and there is deliberately NO `POST …/paso/6/reliability/calcular` route —
every existing action (equipment select, scenario select, manual
select/validate) already re-renders the whole fragment from a fresh
`build_context()` call, which reproduces the scenario table "just appearing"
the same way it does in Streamlit. `hx-indicator`/`hx-disabled-elt` are
still applied to the equipment `<select>`s (the action most likely to make
this recompute run) per PLAN §1.4's "any action that calls PVGIS or the SoC
simulator" rule.

`scratch.s6og` shape (PLAN §1.1's example, filled in here):
    {"panel_id": ..., "inverter_id": ..., "battery_id": ..., "charge_controller_id": ...,
     "monitoring_id": ..., "equip_key": "<panel_id>_<cc_id>_<battery_id>",
     "selected_scenario": "2", "use_manual": false,
     "manual": {"series": 8, "parallel": 1, "battery_count": 2}}

Do-not-drop items carried from PLAN §1.10 (cited by number at each site
below): 2, 3, 16, 17, 18.
"""
from __future__ import annotations

from calculations.load_profile_off_grid import CATEGORY_LABELS_ES
from calculations.mppt import check_charge_controller_design_multi
from calculations.sizing_off_grid import (
    _HYBRID_RELIABILITY_SCENARIO_DEFS,
    check_split_phase,
    compute_ac_breaker_summary,
    generate_reliability_scenarios,
    simulate_battery_soc,
    size_battery_bank,
)
from config import BRAND_GREEN, BRAND_NAVY

DEFAULT_SCRATCH_KEY = "s6og"

# Cap on how many charge controllers we'll parallel before calling the array
# unbuildable — do-not-drop item 18, verbatim value from
# wizard/off_grid.py's own module-level `_MAX_CHARGE_CONTROLLERS = 4` (a
# distinct, deliberately-not-shared constant from
# calculations/sizing_off_grid.py's own private module-level default of the
# same name/value — the wizard step owns its own UI-facing cap).
_MAX_CHARGE_CONTROLLERS = 4

# Same 5-category colour map as wizard/off_grid.py's module-level
# `_CATEGORY_CHART_COLORS` (og_s4_loads.py / og_s5_demand.py don't export it,
# so it's kept here too rather than introducing a shared import for one
# small dict three modules already duplicate independently).
_CATEGORY_CHART_COLORS = {
    "fixed_cycling": BRAND_GREEN,
    "behavior_driven": BRAND_NAVY,
    "climate_driven": "#1d4ed8",
    "discretionary": "#b45309",
    "ignition_only": "#6b7280",
    "appliance": "#7c3aed",
}

# size_array()'s/every array-generation-figure default system_losses_pct —
# named here once since it's used verbatim in half a dozen places below,
# exactly as wizard/off_grid.py inlines `1 - 0.20` at each site.
_DERATING = 1 - 0.20


# ── scratch / catalog helpers ────────────────────────────────────────────


def _s6og(blob: dict) -> dict:
    return (blob.get("scratch") or {}).get(DEFAULT_SCRATCH_KEY) or {}


def _catalog() -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    from database.equipment_db import (
        list_batteries, list_charge_controllers, list_inverters, list_monitoring_devices, list_panels,
    )

    panels = list_panels()
    inverters = [i for i in list_inverters() if i.get("type") == "hybrid"]
    batteries = list_batteries()
    charge_controllers = list_charge_controllers()
    monitoring_devices = list_monitoring_devices()
    return panels, inverters, batteries, charge_controllers, monitoring_devices


def _find(items: list[dict], id_: str | None) -> dict | None:
    if not id_:
        return None
    return next((x for x in items if x.get("id") == id_), None)


def _resolve_equipment(blob: dict) -> dict:
    """Panel/inverter/battery/charge-controller/monitoring currently in
    play — scratch first (a live selection this session), else whatever was
    already persisted at a prior Siguiente click, else the catalog's first
    row of each type (matches Streamlit's `default_*_idx = ... or 0`)."""
    s6 = _s6og(blob)
    current = blob.get("equipment") or {}
    panels, inverters, batteries, charge_controllers, monitoring_devices = _catalog()

    panel_id = s6.get("panel_id") or current.get("panel_id") or (panels[0]["id"] if panels else None)
    inverter_id = s6.get("inverter_id") or current.get("inverter_id") or (inverters[0]["id"] if inverters else None)
    battery_id = s6.get("battery_id") or current.get("battery_id") or (batteries[0]["id"] if batteries else None)
    cc_id = s6.get("charge_controller_id") or current.get("charge_controller_id") or (
        charge_controllers[0]["id"] if charge_controllers else None
    )
    monitoring_id = s6.get("monitoring_id", current.get("monitoring_id"))

    return {
        "panels": panels, "inverters": inverters, "batteries": batteries,
        "charge_controllers": charge_controllers, "monitoring_devices": monitoring_devices,
        "panel": _find(panels, panel_id) or (panels[0] if panels else None),
        "inverter": _find(inverters, inverter_id) or (inverters[0] if inverters else None),
        "battery": _find(batteries, battery_id) or (batteries[0] if batteries else None),
        "cc": _find(charge_controllers, cc_id) or (charge_controllers[0] if charge_controllers else None),
        "monitoring": _find(monitoring_devices, monitoring_id),
    }


def select_equipment(blob: dict, form) -> dict:
    """`paso/6/equipo`'s core logic — verbatim port of the `w6og_equip_key`
    reset block (wizard/off_grid.py L973-982, do-not-drop item 17's sibling
    note / item 11's Off-Grid analogue). Keys on panel + charge controller +
    battery ONLY — confirmed by reading the exact source line
    (`equip_key = f"{panel['id']}_{cc['id']}_{battery['id']}"`); changing the
    INVERTER alone does NOT reset scenarios/manual/selection in the actual
    Streamlit source (flagged, not silently "corrected" — see this module's
    own docstring for why that's reported rather than fixed).

    Only `use_manual`/`selected_scenario` are cleared on a key change — the
    manual series/parallel/battery-count NUMBERS are left untouched, exactly
    matching Streamlit's own `st.session_state.pop("w6og_use_manual", None)`
    / `.pop("w6og_selected_scenario", None)` (its manual number_inputs are
    separate widget keys the reset never touches)."""
    s6 = _s6og(blob)
    panels, inverters, batteries, charge_controllers, _monitoring = _catalog()

    def _pick(field: str, items: list[dict]) -> str | None:
        posted = (form.get(field) or "").strip()
        return posted or s6.get(field) or (items[0]["id"] if items else None)

    panel_id = _pick("panel_id", panels)
    inverter_id = _pick("inverter_id", inverters)
    battery_id = _pick("battery_id", batteries)
    cc_id = _pick("charge_controller_id", charge_controllers)
    monitoring_id = (form.get("monitoring_id") or "").strip() or None

    equip_key = f"{panel_id}_{cc_id}_{battery_id}" if (panel_id and cc_id and battery_id) else None
    new_s6 = {
        **s6, "panel_id": panel_id, "inverter_id": inverter_id, "battery_id": battery_id,
        "charge_controller_id": cc_id, "monitoring_id": monitoring_id,
    }
    if s6.get("equip_key") != equip_key:
        new_s6["equip_key"] = equip_key
        new_s6.pop("selected_scenario", None)
        new_s6["use_manual"] = False
    return new_s6


# ── PVGIS daily-series lazy backfill (do-not-drop item 2) ────────────────


def _resolve_pvgis_daily(blob: dict, vid: str | None) -> tuple[list[float], dict]:
    """Verbatim port of wizard/off_grid.py:step6_equipment()'s lazy backfill
    (L930-946) for drafts created before Step 3 started fetching the daily
    PVGIS series. `fetch_daily_series()` is itself cached in Supabase by
    lat/lon (calculations/pvgis.py), so this only ever hits the PVGIS network
    API the first time any draft asks for this site's daily series — every
    later call (this draft or any other at the same site) is a cheap cache
    read. Persists the fetched series onto `site.pvgis_daily` via
    `wizard.draft.patch()` when `vid` is given, so this class of draft only
    needs the backfill once rather than on every single render forever
    (Flask has no Streamlit-session-state to silently carry it in memory
    between reruns the way the original does)."""
    site = blob.get("site") or {}
    pvgis_daily_blob = site.get("pvgis_daily") or {}
    series = pvgis_daily_blob.get("daily_kwh_kwp") or []
    if not series and site.get("lat") and site.get("lon"):
        try:
            from calculations.pvgis import fetch_daily_series

            pvgis_daily_blob = fetch_daily_series(site["lat"], site["lon"])
            series = pvgis_daily_blob.get("daily_kwh_kwp") or []
            if vid:
                from wizard import draft

                draft.patch(vid, "site", {"pvgis_daily": pvgis_daily_blob})
        except Exception:
            pass
    return series, pvgis_daily_blob


# ── manual-mode projection (do-not-drop item 2's manual-mode utilization) ─


def _og_scenario_projection(
    combo: dict,
    avg_peak_sun_hours: float,
    daily_kwh: float,
    autonomy_days: float,
    dod_pct: float,
    battery_voltage_v: float,
    battery_capacity_kwh: float,
    daily_kwh_kwp: list[float] | None = None,
    battery_count_override: int | None = None,
) -> dict:
    """Verbatim port of wizard/off_grid.py's own `_og_scenario_projection()`
    (L637-702). Runs `simulate_battery_soc()` against this specific manual
    array + the battery bank it sizes here, when a real daily PVGIS series is
    available, so manual mode's "Aprovechamiento solar" is the same
    real-simulation-driven number as the auto scenarios — never the flat
    single-day ratio (do-not-drop item 2's warning, applied here too)."""
    daily_generation = round(combo["system_kw"] * avg_peak_sun_hours * _DERATING, 2)
    if battery_count_override is not None:
        total_kwh_installed = round(battery_count_override * battery_capacity_kwh, 2)
        bank = {
            "battery_count": battery_count_override,
            "total_kwh_installed": total_kwh_installed,
            "discharge_pct": round(daily_generation / total_kwh_installed * 100, 2) if total_kwh_installed > 0 else 0.0,
        }
    else:
        bank = size_battery_bank(
            daily_kwh=daily_generation, autonomy_days=autonomy_days, dod_pct=dod_pct,
            battery_voltage_v=battery_voltage_v, battery_capacity_kwh=battery_capacity_kwh,
        )
    margin_kwh = round(max(0, daily_generation - daily_kwh), 2)

    utilization_pct = None
    if daily_kwh_kwp and len(daily_kwh_kwp) >= 300 and bank["total_kwh_installed"] > 0:
        daily_gen_series = [v * combo["system_kw"] * _DERATING for v in daily_kwh_kwp]
        sim = simulate_battery_soc(
            daily_gen_series, daily_kwh, bank["total_kwh_installed"], dod_pct, 100 - dod_pct,
        )
        utilization_pct = sim["utilization_pct"]

    return {
        "daily_generation": daily_generation,
        "battery_count": bank["battery_count"],
        "battery_kwh": bank["total_kwh_installed"],
        "covers": daily_generation >= daily_kwh,
        "margin_kwh": margin_kwh,
        "utilization_pct": utilization_pct,
    }


def _hybrid_savings_pct(
    hybrid_savings_enabled: bool, whole_home_avg_kwh_month: float, daily_kwh: float, utility: dict,
    avg_peak_sun_hours: float, system_kw: float, daily_generation_kwh: float | None = None,
) -> float | None:
    """Verbatim port of step6_equipment()'s local `_scenario_savings_pct()`
    closure (L917-928) — kept as a module-level function (not a closure)
    since this port has no single enclosing render call to close over.
    `daily_generation_kwh=None` recomputes a rough figure from
    `system_kw * avg_peak_sun_hours * derating` (used for auto-scenario
    cards/rows, matching the source's own `_scenario_savings_pct(s["system_kw"])`
    call with no second arg); the manual card passes its own precise
    `mp["daily_generation"]` instead (matching
    `_scenario_savings_pct(m["system_kw"], mp["daily_generation"])`)."""
    if not hybrid_savings_enabled:
        return None
    from calculations.sizing_off_grid import estimate_hybrid_savings_pct

    if daily_generation_kwh is None:
        daily_generation_kwh = system_kw * avg_peak_sun_hours * _DERATING
    result = estimate_hybrid_savings_pct(
        daily_generation_kwh=daily_generation_kwh, critical_daily_kwh=daily_kwh,
        whole_home_avg_kwh_month=whole_home_avg_kwh_month,
        daytime_fraction=0.45, tariff_info=utility,
    )
    return result["savings_pct"]


# ── the one shared "what's currently chosen" computation ──────────────────
# Both build_context() (for rendering) and save_step() (for what gets
# persisted at "Siguiente") need EXACTLY the same resolution of scenarios/
# chosen-config/battery_bank — factored into this one function so there is
# never a second implementation of "what is chosen right now" to drift
# against the first (PLAN §1.3's principle applied one level further down,
# same idea gz_s6_equipment.py's `_resolve_chosen()` embodies).


def _compute(blob: dict, vid: str | None = None) -> dict:
    s6 = _s6og(blob)
    consumption = blob.get("consumption") or {}
    site = blob.get("site") or {}
    # Hybrid fix (Phase 20 Step 9): the real Streamlit source
    # (wizard/off_grid.py:step6_equipment() L907/L926, shared by Hybrid via
    # wizard/hybrid.py's step6_equipment() = off_grid.step6_equipment())
    # reads `consumption["utility"]` for the hybrid-savings tariff — Hybrid's
    # own Step 4 (hy_s4_loads.py) nests the distributor/tariff dict INSIDE
    # `consumption.utility`, never in the durable top-level `utility` section
    # (that section stays Grid-Zero-owned/empty for every Off-Grid/Hybrid
    # draft — see wizard/state.py:autosave()). Reading `blob["utility"]`
    # here would always see `{}` for a real Hybrid draft, silently disabling
    # every hybrid_savings_enabled branch below. Off-Grid drafts never set
    # consumption.utility either way, so this is a no-op there.
    utility = consumption.get("utility") or blob.get("utility") or {}
    profile = consumption.get("profile") or {}

    eq = _resolve_equipment(blob)
    panel, inverter, battery, cc, monitoring = eq["panel"], eq["inverter"], eq["battery"], eq["cc"], eq["monitoring"]

    if not (panel and inverter and battery and cc):
        return {**eq, "no_catalog": True}

    panel_area = round(float(panel.get("width_m") or 0) * float(panel.get("height_m") or 0), 2)
    split_phase = check_split_phase(inverter, consumption.get("voltage_v", 120))

    daily_kwh = consumption.get("daily_kwh", 0) or 0
    pvgis_monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp", [])
    avg_peak_sun_hours = (sum(pvgis_monthly) / 12 / 30.4) if pvgis_monthly else 4.5

    # ── Hybrid bill-reduction estimate (no-op for pure Off-Grid — do-not-
    # drop item 16's sibling: this must stay wired so a later Hybrid draft
    # (consumption.grid_connected=True, from wizard/hybrid.py's Step 4, not
    # built by og_s4_loads.py) gets it "for free" once Hybrid's own steps
    # land, without this step needing to change.
    hybrid_savings_enabled = bool(consumption.get("grid_connected")) and bool(utility)
    whole_home_avg_kwh_month = 0.0
    if hybrid_savings_enabled:
        main_panel = consumption.get("main_panel")
        if consumption.get("panel_scope") == "secondary" and main_panel:
            whole_home_avg_kwh_month = float(main_panel.get("avg_kwh_month") or 0)
        else:
            whole_home_avg_kwh_month = daily_kwh * 30.4
        hybrid_savings_enabled = whole_home_avg_kwh_month > 0

    if hybrid_savings_enabled:
        # Hybrid fix (Phase 20 Step 9): the real Streamlit source's own
        # `_render_utility_block()` (wizard/hybrid.py) embeds
        # `"tiers": get_tariff_tiers(...)` directly into the dict it stores
        # at `consumption["utility"]` — but this port's hy_s4_loads.py
        # deliberately follows gz_s4_utility.py's own convention instead
        # (never cache tiers in a persisted `utility` dict; fetch them fresh
        # wherever a bill actually needs computing — see
        # gz_s5_consumption.py's own `_tariff_info()`, reused verbatim here).
        # Without this, `estimate_bill_crc()` inside
        # `estimate_hybrid_savings_pct()` below silently sees an empty tiers
        # list and returns just the access charge as "the whole bill" —
        # confirmed empirically (₡1,745 instead of a real ~₡88,000 bill on a
        # 900 kWh/month test draft) before this fix.
        from webapp.wizard_steps.gz_s5_consumption import _tariff_info

        tariff_info = _tariff_info(utility)
        if tariff_info:
            utility = {**utility, **tariff_info}
        else:
            hybrid_savings_enabled = False

    pvgis_daily_series, pvgis_daily_blob = _resolve_pvgis_daily(blob, vid)
    if pvgis_daily_blob:
        # Harmless no-op re-merge when nothing was backfilled (same values);
        # makes sure this function's own `site` local reflects a freshly
        # fetched series immediately, without relying on a fragile identity
        # check against the original `site.get("pvgis_daily")`.
        site = {**site, "pvgis_daily": pvgis_daily_blob}

    if daily_kwh <= 0:
        return {
            **eq, "no_catalog": False, "no_daily_kwh": True, "panel_area": panel_area,
            "split_phase": split_phase,
        }

    autonomy_days = consumption.get("autonomy_days", 1)
    dod_pct = battery.get("dod_pct", 80)
    base_inverter_qty = 2 if split_phase["requires_split_phase"] else 1
    base_inverter_power_w = round(base_inverter_qty * float(inverter.get("kw") or 0) * 1000)

    profile_lines = profile.get("lines", [])
    total_connected_load_kw = sum(
        line.get("quantity", 1) * line.get("connected_power_kw", 0) for line in profile_lines
    )

    # ── Auto scenarios — recomputed fresh every call, no button/cache (see
    # module docstring's "KEY FINDING"). Do-not-drop item 16: hybrid tier
    # switch, wired but inert for pure Off-Grid.
    is_hybrid_grid = bool(consumption.get("grid_connected"))
    scenario_defs = _HYBRID_RELIABILITY_SCENARIO_DEFS if is_hybrid_grid else None
    scenarios = (
        generate_reliability_scenarios(
            panel, cc, battery, daily_kwh, pvgis_daily_series, autonomy_days,
            base_inverter_qty, float(inverter.get("kw") or 0), total_connected_load_kw,
            _MAX_CHARGE_CONTROLLERS, scenario_defs=scenario_defs,
        ) if pvgis_daily_series and len(pvgis_daily_series) >= 300 else []
    )

    using_manual = bool(s6.get("use_manual"))
    selected_scenario_label = s6.get("selected_scenario") or "2"
    valid_scenarios = [s for s in scenarios if s["within_limits"]]
    if not using_manual and valid_scenarios:
        valid_labels = [s["scenario"] for s in valid_scenarios]
        if selected_scenario_label not in valid_labels:
            selected_scenario_label = valid_labels[min(1, len(valid_labels) - 1)]

    # ── Manual design (do-not-drop item 2's manual-mode note) ─────────────
    default_scenario = next((s for s in scenarios if s["scenario"] == "2"), None)
    manual = s6.get("manual") or {}
    m_series = int(manual.get("series") or (default_scenario["panels_per_string"] if default_scenario else 1))
    m_strings = int(manual.get("parallel") or (default_scenario["strings"] if default_scenario else 1))
    m_battery_count = int(
        manual.get("battery_count") or (default_scenario["battery"]["battery_count"] if default_scenario else 1)
    )

    m = check_charge_controller_design_multi(panel, cc, m_series, m_strings, _MAX_CHARGE_CONTROLLERS)
    mp = None
    if m is not None:
        mp = _og_scenario_projection(
            m, avg_peak_sun_hours, daily_kwh, autonomy_days, dod_pct,
            battery["voltage_v"], battery["capacity_kwh"],
            daily_kwh_kwp=pvgis_daily_series, battery_count_override=m_battery_count,
        )

    # ── Resolve the active configuration (auto scenario or manual) ────────
    if using_manual:
        chosen = {**m, "scenario": "M"} if (m is not None and m["within_limits"]) else None
    else:
        chosen = next((s for s in scenarios if s["scenario"] == selected_scenario_label), None) or (
            scenarios[0] if scenarios else None
        )

    if chosen is None:
        panels_per_string = n_strings = cc_qty = actual_panel_count = 0
        display_array_kw = display_area_m2 = display_daily_generation = 0.0
        is_valid = False
        battery_bank = {"battery_count": 0, "total_kwh_installed": 0, "discharge_pct": 0}
        final_inverter_qty, final_inverter_power_w = base_inverter_qty, base_inverter_power_w
    else:
        panels_per_string = chosen["panels_per_string"]
        n_strings = chosen["strings"]
        cc_qty = chosen["charge_controller_qty"]
        actual_panel_count = chosen["total_panels"]
        display_array_kw = chosen["system_kw"]
        display_area_m2 = chosen["area_m2"]
        display_daily_generation = round(display_array_kw * avg_peak_sun_hours * _DERATING, 2)
        is_valid = chosen["within_limits"]
        if chosen["scenario"] == "M":
            # Manual mode's battery bank comes from the engineer's own
            # "Cantidad de baterías" input, not size_battery_bank() — verbatim
            # port of L1318-1336, INCLUDING the fact that this dict never
            # gets unmet_load_days/days_full_pct/min_soc_actual_pct populated
            # (only utilization_pct, when a daily series exists) — a real
            # asymmetry vs. the auto scenarios' battery dict, present in the
            # actual Streamlit source and preserved here rather than "fixed"
            # (see this module's docstring / the final report for why this
            # is flagged, not silently corrected).
            total_kwh_installed = round(m_battery_count * battery["capacity_kwh"], 2)
            battery_bank = {
                "battery_count": m_battery_count,
                "total_kwh_installed": total_kwh_installed,
                "discharge_pct": round(display_daily_generation / total_kwh_installed * 100, 2) if total_kwh_installed > 0 else 0.0,
            }
            if pvgis_daily_series and len(pvgis_daily_series) >= 300 and battery_bank["total_kwh_installed"] > 0:
                _m_gen = [v * display_array_kw * _DERATING for v in pvgis_daily_series]
                battery_bank["utilization_pct"] = simulate_battery_soc(
                    _m_gen, daily_kwh, battery_bank["total_kwh_installed"], dod_pct, 100 - dod_pct,
                )["utilization_pct"]
            final_inverter_qty, final_inverter_power_w = base_inverter_qty, base_inverter_power_w
        else:
            # Auto scenarios (1/2/3) already carry their own min-SoC-driven
            # battery bank (real-simulation-backed — do-not-drop item 2) and
            # headroom-checked inverter count from generate_reliability_scenarios().
            battery_bank = chosen["battery"]
            final_inverter_qty = chosen["inverter_qty"]
            final_inverter_power_w = chosen["inverter_power_w"]

    return {
        **eq, "no_catalog": False, "no_daily_kwh": False,
        "panel_area": panel_area, "split_phase": split_phase,
        "consumption": consumption, "site": site, "utility": utility, "profile": profile,
        "daily_kwh": daily_kwh, "autonomy_days": autonomy_days, "dod_pct": dod_pct,
        "avg_peak_sun_hours": avg_peak_sun_hours, "pvgis_daily_series": pvgis_daily_series,
        "total_connected_load_kw": total_connected_load_kw,
        "base_inverter_qty": base_inverter_qty, "base_inverter_power_w": base_inverter_power_w,
        "is_hybrid_grid": is_hybrid_grid,
        "hybrid_savings_enabled": hybrid_savings_enabled, "whole_home_avg_kwh_month": whole_home_avg_kwh_month,
        "scenarios": scenarios, "using_manual": using_manual,
        "selected_scenario_label": selected_scenario_label, "valid_scenarios": valid_scenarios,
        "m_series": m_series, "m_strings": m_strings, "m_battery_count": m_battery_count,
        "m": m, "mp": mp,
        "chosen": chosen, "is_valid": is_valid,
        "panels_per_string": panels_per_string, "n_strings": n_strings, "cc_qty": cc_qty,
        "actual_panel_count": actual_panel_count,
        "display_array_kw": display_array_kw, "display_area_m2": display_area_m2,
        "display_daily_generation": display_daily_generation,
        "battery_bank": battery_bank,
        "final_inverter_qty": final_inverter_qty, "final_inverter_power_w": final_inverter_power_w,
    }


# ── in-step actions ────────────────────────────────────────────────────


def select_scenario(blob: dict, label: str) -> dict:
    """`paso/6/escenario/<label>`'s core logic — only a currently-valid
    scenario's selector button renders at all; server-side no-op otherwise,
    mirroring Grid Zero's equivalent (do-not-drop item 10)."""
    c = _compute(blob)
    if c.get("no_catalog") or c.get("no_daily_kwh"):
        return _s6og(blob)
    valid_labels = {s["scenario"] for s in c["scenarios"] if s["within_limits"]}
    s6 = _s6og(blob)
    if label not in valid_labels:
        return s6
    return {**s6, "selected_scenario": label, "use_manual": False}


def validate_manual(blob: dict, form) -> dict:
    """`paso/6/manual/validar`'s core logic — the live, change-triggered
    recompute (PLAN §1.4 pattern 3) as series/strings/battery-count are
    edited. Off-Grid's Opción 2 has THREE live inputs (panels-in-series,
    strings-in-parallel, battery count) vs. Grid Zero's two — this is
    battery-BANK sizing, not just PV-string sizing (per the task's own
    framing)."""
    from webapp.wizard_steps.common import to_float

    s6 = _s6og(blob)
    series = int(to_float(form.get("m_series"), 1) or 1)
    strings = int(to_float(form.get("m_strings"), 1) or 1)
    battery_count = int(to_float(form.get("m_battery_count"), 1) or 1)
    series = max(1, min(50, series))
    strings = max(1, min(50, strings))
    battery_count = max(1, min(50, battery_count))
    return {**s6, "manual": {"series": series, "parallel": strings, "battery_count": battery_count}}


def select_manual(blob: dict) -> dict:
    """`paso/6/manual`'s core logic — do-not-drop item 14's Off-Grid
    analogue: a manual design can only be *selected* when currently
    `within_limits`, rejected server-side (not just via a disabled button)."""
    c = _compute(blob)
    s6 = _s6og(blob)
    if c.get("no_catalog") or c.get("no_daily_kwh") or c.get("m") is None:
        return s6
    if not c["m"].get("within_limits"):
        return s6
    return {**s6, "use_manual": True}


# ── Siguiente ─────────────────────────────────────────────────────────────


def save_step(blob: dict, vid: str | None = None) -> dict | None:
    """Verbatim port of step6_equipment()'s own return dict (wizard/off_grid.py
    L1848-1867). Returns None when neither a valid auto scenario nor a valid
    manual design currently exists — `webapp/blueprints/wizard.py` treats
    None as "reject the advance, re-render step 6 with an error", same
    contract as `gz_s6_equipment.save_step()`."""
    c = _compute(blob, vid)
    if c.get("no_catalog") or c.get("no_daily_kwh"):
        return None
    chosen = c["chosen"]
    if chosen is None or not c["is_valid"]:
        return None

    hybrid_savings = None
    if c["hybrid_savings_enabled"]:
        from calculations.sizing_off_grid import estimate_hybrid_savings_pct

        hybrid_savings = estimate_hybrid_savings_pct(
            daily_generation_kwh=c["display_daily_generation"], critical_daily_kwh=c["daily_kwh"],
            whole_home_avg_kwh_month=c["whole_home_avg_kwh_month"],
            daytime_fraction=0.45, tariff_info=c["utility"],
        )

    monitoring = c["monitoring"]
    return {
        "panel_id": c["panel"]["id"], "panel": c["panel"],
        "inverter_id": c["inverter"]["id"], "inverter": c["inverter"],
        "battery_id": c["battery"]["id"], "battery": c["battery"],
        "charge_controller_id": c["cc"]["id"], "charge_controller": c["cc"],
        "charge_controller_qty": c["cc_qty"],
        "inverter_qty": c["final_inverter_qty"],
        "monitoring_id": monitoring["id"] if monitoring else None, "monitoring": monitoring,
        "panels_per_string": c["panels_per_string"],
        "n_strings": c["n_strings"],
        "panel_count": c["actual_panel_count"],
        "array_scenario": chosen["scenario"],
        # Do-not-drop item 7 — the FULL scenario set, not just the chosen one.
        "array_scenarios": c["scenarios"],
        "array": {
            "array_kw": c["display_array_kw"], "panel_count": c["actual_panel_count"],
            "area_m2": c["display_area_m2"], "daily_generation_kwh": c["display_daily_generation"],
        },
        "battery_bank": c["battery_bank"],
        "split_phase": c["split_phase"],
        "hybrid_savings": hybrid_savings,
    }


# ── build_context ────────────────────────────────────────────────────────


def build_context(blob: dict, vid: str | None = None) -> dict:
    blob = blob or {}
    c = _compute(blob, vid)

    if c.get("no_catalog"):
        return {
            "no_catalog": True, "can_continue": False,
            "panels": c.get("panels") or [], "inverters": c.get("inverters") or [],
            "batteries": c.get("batteries") or [], "charge_controllers": c.get("charge_controllers") or [],
            "monitoring_devices": c.get("monitoring_devices") or [],
        }
    if c.get("no_daily_kwh"):
        return {
            "no_catalog": False, "no_daily_kwh": True, "can_continue": False,
            "panels": c["panels"], "inverters": c["inverters"], "batteries": c["batteries"],
            "charge_controllers": c["charge_controllers"], "monitoring_devices": c["monitoring_devices"],
            "selected_panel": c["panel"], "selected_inverter": c["inverter"], "selected_battery": c["battery"],
            "selected_cc": c["cc"], "selected_monitoring": c["monitoring"],
            "panel_area": c["panel_area"], "split_phase": c["split_phase"],
        }

    panel, inverter, battery, cc, monitoring = c["panel"], c["inverter"], c["battery"], c["cc"], c["monitoring"]
    consumption, site, profile = c["consumption"], c["site"], c["profile"]
    daily_kwh, autonomy_days, dod_pct = c["daily_kwh"], c["autonomy_days"], c["dod_pct"]
    avg_peak_sun_hours = c["avg_peak_sun_hours"]
    is_hybrid_grid = c["is_hybrid_grid"]
    hybrid_savings_enabled = c["hybrid_savings_enabled"]

    def _savings(system_kw: float, daily_generation_kwh: float | None = None) -> float | None:
        return _hybrid_savings_pct(
            hybrid_savings_enabled, c["whole_home_avg_kwh_month"], daily_kwh, c["utility"],
            avg_peak_sun_hours, system_kw, daily_generation_kwh,
        )

    # ── Scenario table + projection cards ─────────────────────────────────
    scenarios = c["scenarios"]
    using_manual = c["using_manual"]
    selected_scenario_label = c["selected_scenario_label"]
    scenario_rows = []
    scenario_cards = []
    for s in scenarios:
        bank = s["battery"]
        scenario_rows.append({
            "escenario": s["scenario"], "label": s["label"],
            "soc_objetivo": s["min_soc_target_pct"],
            "dias_recarga_completa": bank["days_full_pct"],
            "dias_sin_cubrir": bank["unmet_load_days"],
            "aprovechamiento_solar": bank["utilization_pct"],
            "panels_per_string": s["panels_per_string"], "strings": s["strings"],
            "controladores": s["charge_controller_qty"], "total_panels": s["total_panels"],
            "system_kw": s["system_kw"], "area_m2": s["area_m2"],
            "voc_total": s["voc_total"], "imp_total": s["imp_total"],
            "inverter_qty": s["inverter_qty"], "inverter_power_w": s["inverter_power_w"],
            "inverter_load_ratio_pct": s["inverter_load_ratio_pct"],
            "battery_count": bank["battery_count"], "battery_kwh": bank["total_kwh_installed"],
            "min_soc_actual_pct": bank["min_soc_actual_pct"],
            "reduccion_factura": _savings(s["system_kw"]) if hybrid_savings_enabled else None,
            "within_limits": s["within_limits"], "notes": s["notes"],
        })
        scenario_cards.append({
            "scenario": s["scenario"], "label": s["label"], "system_kw": s["system_kw"],
            "min_soc_target_pct": s["min_soc_target_pct"],
            "is_valid": s["within_limits"],
            "is_selected": (s["scenario"] == selected_scenario_label) and not using_manual,
            "bank": bank,
            "cc_qty": s["charge_controller_qty"], "growth_strings": s.get("growth_strings"),
            "inverter_growth_added": s.get("inverter_growth_added"),
            "inverter_headroom_tight": s.get("inverter_headroom_tight"),
            "inverter_load_ratio_pct": s["inverter_load_ratio_pct"],
            "total_panels": s["total_panels"], "panels_per_string": s["panels_per_string"], "strings": s["strings"],
            "inverter_qty": s["inverter_qty"], "inverter_power_w": s["inverter_power_w"],
            "savings_pct": _savings(s["system_kw"]) if hybrid_savings_enabled else None,
        })

    # ── Manual design (Opción 2) ──────────────────────────────────────────
    m, mp = c["m"], c["mp"]
    manual_ctx = None
    if m is not None:
        imp_limit_m = cc["imax_in"] * m["charge_controller_qty"]
        manual_ctx = {
            "series": c["m_series"], "strings": c["m_strings"], "battery_count": c["m_battery_count"],
            "design": m, "voc_ok": m["voc_total"] <= cc["vin_max"], "imp_ok": m["imp_total"] <= imp_limit_m,
            "imp_limit": imp_limit_m,
            "can_select": bool(m.get("within_limits")),
            "proj": mp,
            "savings_pct": _savings(m["system_kw"], mp["daily_generation"]) if (mp and hybrid_savings_enabled) else None,
        }

    # ── Chosen config ──────────────────────────────────────────────────────
    chosen = c["chosen"]
    is_valid = c["is_valid"]
    battery_bank = c["battery_bank"]
    panels_per_string, n_strings, cc_qty = c["panels_per_string"], c["n_strings"], c["cc_qty"]
    actual_panel_count = c["actual_panel_count"]
    display_array_kw, display_area_m2 = c["display_array_kw"], c["display_area_m2"]
    display_daily_generation = c["display_daily_generation"]
    final_inverter_qty, final_inverter_power_w = c["final_inverter_qty"], c["final_inverter_power_w"]

    split_phase = c["split_phase"]
    inverter_arrangement = (
        "Split-phase 120/240V (master/slave)" if split_phase["requires_split_phase"]
        else f"{consumption.get('voltage_v', 120):.0f}V"
    )
    panel_arrangement = f"{panels_per_string} en serie × {n_strings} en paralelo" if chosen else "—"

    chosen_ctx = None
    if chosen:
        voc_ok = chosen["voc_total"] <= cc["vin_max"]
        imp_limit = cc["imax_in"] * cc_qty
        imp_ok = chosen["imp_total"] <= imp_limit

        min_safe_soc_pct = round(100 - dod_pct, 1)
        # Do-not-drop item 2's core requirement: min_soc_actual_pct comes
        # from simulate_battery_soc() (via generate_reliability_scenarios()
        # for auto scenarios), NOT from discharge_pct — a flat single-day
        # ratio that no longer tracks the same number once the scenario
        # search validates against a real daily series. See _compute()'s
        # own comment for the one documented exception (manual mode, ported
        # verbatim from the actual Streamlit source, not introduced here).
        unmet_days = battery_bank.get("unmet_load_days", 0)
        design_min_soc_pct = battery_bank.get("min_soc_actual_pct", round(100 - battery_bank["discharge_pct"], 1))
        soc_ok = design_min_soc_pct >= min_safe_soc_pct and unmet_days == 0
        discharge_ok = battery_bank["discharge_pct"] <= 100

        from webapp.figures import fig_to_fragment, gz_margin_bars_fig, og_generation_vs_consumption_fig

        margin_items = [
            ("Voc del arreglo (vs. controlador)", (chosen["voc_total"] / cc["vin_max"] * 100) if cc["vin_max"] else 0),
            ("Corriente del arreglo (vs. controlador)", (chosen["imp_total"] / imp_limit * 100) if imp_limit else 0),
            ("Profundidad de descarga (vs. batería)", (battery_bank["discharge_pct"] / dod_pct * 100) if dod_pct else 0),
        ]
        margin_chart_html = fig_to_fragment(gz_margin_bars_fig(margin_items))

        gen_chart_html = None
        margin_kwh_gen = round(max(0, display_daily_generation - daily_kwh), 2)
        if display_daily_generation > 0:
            gen_chart_html = fig_to_fragment(
                og_generation_vs_consumption_fig(display_daily_generation, daily_kwh, margin_kwh_gen)
            )

        chosen_ctx = {
            "scenario_note": "manual" if chosen["scenario"] == "M" else f"Escenario {chosen['scenario']} · {chosen['label']}",
            "voc_ok": voc_ok, "imp_ok": imp_ok, "is_valid": is_valid,
            "voc_total": chosen["voc_total"], "imp_total": chosen["imp_total"], "imp_limit": imp_limit,
            "cc_qty": cc_qty, "cc_brand_model": f"{cc['brand']} {cc['model']}",
            "discharge_pct": battery_bank["discharge_pct"], "discharge_ok": discharge_ok,
            "min_safe_soc_pct": min_safe_soc_pct, "design_min_soc_pct": design_min_soc_pct,
            "unmet_days": unmet_days, "soc_ok": soc_ok,
            "notes": chosen.get("notes"),
            "margin_chart_html": margin_chart_html,
            "panel_arrangement": panel_arrangement, "inverter_arrangement": inverter_arrangement,
            "total_panels": actual_panel_count, "panels_per_string": panels_per_string, "strings": n_strings,
            "system_kw": display_array_kw, "area_m2": display_area_m2,
            "final_inverter_qty": final_inverter_qty, "battery_count": battery_bank["battery_count"],
            "display_daily_generation": display_daily_generation, "margin_kwh_gen": margin_kwh_gen,
            "covers": display_daily_generation >= daily_kwh,
            "battery_kwh": battery_bank["total_kwh_installed"],
            "gen_chart_html": gen_chart_html,
        }

    # ── Resumen eléctrico — carga y protecciones (do-not-drop item 18) ─────
    ac_ctx = None
    profile_lines = profile.get("lines") or []
    if profile_lines:
        from calculations.load_profile_off_grid import compute_demand_load

        demand = compute_demand_load(profile_lines)
        design_voltage_v = 240.0 if split_phase["requires_split_phase"] else float(consumption.get("voltage_v", 120))
        ac_summary = compute_ac_breaker_summary(
            demand["total_demand_kw"], design_voltage_v, inverter, final_inverter_qty,
            grid_connected=is_hybrid_grid,
        )
        available_power_kw = float(inverter.get("kw") or 0) * final_inverter_qty
        ac_ctx = {
            "demand": demand, "ac_summary": ac_summary, "available_power_kw": available_power_kw,
            "cat_table": [{
                "category_label": CATEGORY_LABELS_ES.get(cat["category"], cat["category"]),
                "installed_kw": cat["installed_kw"], "factor_applied": cat["factor_applied"],
                "demand_kw": cat["demand_kw"],
            } for cat in demand["categories"]],
        }

    # ── Dimensionamiento calculado ──────────────────────────────────────
    dim_ctx = {
        "scenario_note": (
            ("manual" if chosen["scenario"] == "M" else f"Escenario {chosen['scenario']} · {chosen['label']}")
            if chosen else None
        ),
        "total_panels": actual_panel_count, "panel_arrangement": panel_arrangement,
        "system_kw": display_array_kw, "area_m2": display_area_m2,
        "final_inverter_qty": final_inverter_qty, "inverter_arrangement": inverter_arrangement,
        "cc_qty": cc_qty or 1, "battery_count": battery_bank["battery_count"],
        "daily_generation": display_daily_generation, "battery_kwh": battery_bank["total_kwh_installed"],
    }

    # ── Estadísticas ────────────────────────────────────────────────────
    stats_ctx = None
    if display_daily_generation > 0:
        from calculations.og_coverage import og_monthly_coverage_and_sim
        from webapp.figures import (
            fig_to_fragment, monthly_coverage_fig, og_energy_flow_sankey_fig,
            og_seasonal_coverage_fig, og_solar_utilization_fig,
        )

        step6_coverage, step6_sim = og_monthly_coverage_and_sim(
            {"array_kw": display_array_kw}, battery, battery_bank, {"daily_kwh": daily_kwh}, site,
        )
        coverage_chart_html = None
        if step6_coverage:
            coverage_chart_html = fig_to_fragment(monthly_coverage_fig(
                step6_coverage.get("generation"), step6_coverage.get("consumption"),
                recharge_kwh=step6_coverage.get("recharge"), flag_shortfall=True,
            ))

        utilization_ctx = None
        if step6_sim:
            util_pct = step6_sim["utilization_pct"]
            used_kwh = round(step6_sim["total_generation_kwh"] - step6_sim["curtailed_kwh"])
            curtailed_kwh = round(step6_sim["curtailed_kwh"])
            utilization_ctx = {
                "util_pct": util_pct, "used_kwh": used_kwh, "curtailed_kwh": curtailed_kwh,
                "chart_html": fig_to_fragment(og_solar_utilization_fig(used_kwh, curtailed_kwh, util_pct, is_hybrid_grid)),
                "oversized": util_pct < 50 and not is_hybrid_grid,
            }

        seasonal_ctx = None
        pvgis_monthly = (site.get("pvgis_data") or {}).get("monthly_kwh_kwp", [])
        if pvgis_monthly and len(pvgis_monthly) == 12:
            import calendar

            from calculations.sizing_grid_zero import MONTHS_ES

            days_in_month = [calendar.monthrange(2026, mo)[1] for mo in range(1, 13)]
            monthly_gen_kwh_day = [
                round(m_kwhkwp * display_array_kw * _DERATING / d, 2)
                for m_kwhkwp, d in zip(pvgis_monthly, days_in_month)
            ]
            worst_idx = min(range(12), key=lambda i: monthly_gen_kwh_day[i])
            seasonal_ctx = {
                "chart_html": fig_to_fragment(
                    og_seasonal_coverage_fig(MONTHS_ES, monthly_gen_kwh_day, daily_kwh, worst_idx)
                ),
                "worst_month": MONTHS_ES[worst_idx],
                "worst_month_kwh_day": monthly_gen_kwh_day[worst_idx],
                "deficit": round(daily_kwh - monthly_gen_kwh_day[worst_idx], 2),
                "shortfall": monthly_gen_kwh_day[worst_idx] < daily_kwh,
            }

        flow_ctx = None
        if profile and daily_kwh > 0:
            raw_cat_kwh: dict[str, float] = {}
            for line in profile.get("lines", []):
                raw_cat_kwh[line["category"]] = raw_cat_kwh.get(line["category"], 0) + line["estimated_kwh_day"]
            raw_total = sum(raw_cat_kwh.values())
            if raw_total > 0:
                scale = daily_kwh / raw_total
                cat_kwh = {k: round(v * scale, 3) for k, v in raw_cat_kwh.items()}
                flow_ctx = {
                    "chart_html": fig_to_fragment(og_energy_flow_sankey_fig(
                        display_array_kw, avg_peak_sun_hours, display_daily_generation, daily_kwh,
                        cat_kwh, CATEGORY_LABELS_ES, _CATEGORY_CHART_COLORS,
                    )),
                }

        stats_ctx = {
            "coverage_chart_html": coverage_chart_html,
            "utilization": utilization_ctx,
            "seasonal": seasonal_ctx,
            "flow": flow_ctx,
            "is_hybrid_grid": is_hybrid_grid,
        }

    return {
        "no_catalog": False, "no_daily_kwh": False,
        "panels": c["panels"], "inverters": c["inverters"], "batteries": c["batteries"],
        "charge_controllers": c["charge_controllers"], "monitoring_devices": c["monitoring_devices"],
        "selected_panel": panel, "selected_inverter": inverter, "selected_battery": battery,
        "selected_cc": cc, "selected_monitoring": monitoring,
        "panel_area": c["panel_area"], "split_phase": split_phase,
        "is_hybrid_grid": is_hybrid_grid,
        "daily_kwh": daily_kwh, "autonomy_days": autonomy_days,
        "base_inverter_qty": c["base_inverter_qty"], "base_inverter_power_w": c["base_inverter_power_w"],
        "scenarios": scenarios, "scenario_rows": scenario_rows, "scenario_cards": scenario_cards,
        "valid_scenarios_count": len(c["valid_scenarios"]),
        "hybrid_savings_enabled": hybrid_savings_enabled,
        "using_manual": using_manual,
        "manual": manual_ctx,
        "chosen": chosen_ctx,
        "ac": ac_ctx,
        "dim": dim_ctx,
        "stats": stats_ctx,
        "max_charge_controllers": _MAX_CHARGE_CONTROLLERS,
        "no_pvgis_daily": not (c["pvgis_daily_series"] and len(c["pvgis_daily_series"]) >= 300),
        "no_scenarios_reachable": bool(
            c["pvgis_daily_series"] and len(c["pvgis_daily_series"]) >= 300 and not scenarios
        ),
        "can_continue": bool(chosen) and is_valid,
    }
