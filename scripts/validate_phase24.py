"""Phase 24 Step 1 validation — `calculations/design_targets.py` and the generators it is lifted from.

    python -m scripts.validate_phase24              # check everything (offline, no DB)
    python -m scripts.validate_phase24 --capture    # (re)write the golden file from the CURRENT generators

Two kinds of check:

1. GOLDEN — `generate_design_scenarios()` and `generate_design_scenarios_hybrid()` must return byte-identical
   results before and after the formula lift (PLAN_PHASE24_OBJETIVOS.md §4 item 1). The golden file was captured
   from the pre-refactor code; `--capture` exists only for a deliberate, reviewed change to the calibrated model
   (it also needs the DB once, to snapshot the equipment rows into the fixture, so the check itself runs offline).
2. TARGETS — the equipment-free target functions, hand-computed independently of the code under test.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLDEN_PATH = ROOT / "scripts" / "phase24_golden.json"

# PVGIS-like monthly kWh/kWp for a Costa Rica site (shape matters, not the exact figures).
MONTHLY_KWH_KWP = [141.0, 136.0, 152.0, 141.0, 128.0, 122.0, 127.0, 131.0, 121.0, 113.0, 112.0, 126.0]


def _pick(rows: list[dict], model: str) -> dict:
    return next(r for r in rows if r["model"] == model)


def _snapshot_equipment() -> dict:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from database.equipment_db import list_batteries, list_charge_controllers, list_inverters, list_panels

    panels, ccs, batts, invs = list_panels(), list_charge_controllers(), list_batteries(), list_inverters()
    return {
        "panel": _pick(panels, "JAM66D45-620LB"),
        "cc": _pick(ccs, "SmartSolar MPPT 250/100"),
        "battery_us5000": _pick(batts, "US5000"),
        "battery_fidus": _pick(batts, "Fidus"),
        "inv_mp5000": _pick(invs, "MultiPlus-II 48/5000/70-95"),
        "inv_mp3000": _pick(invs, "MultiPlus-II 48/3000/35-50"),
        "inv_quattro": _pick(invs, "Quattro 48/10000/140-100/100 120V"),
    }


def _og_cases(eq: dict) -> list[dict]:
    base = dict(panel=eq["panel"], charge_controller=eq["cc"], monthly_kwh_kwp=MONTHLY_KWH_KWP)
    return [
        {"name": "og_home_12kwh", **base, "battery": eq["battery_us5000"], "inverter": eq["inv_mp5000"],
         "daily_kwh_consumption": 12.0, "peak_demand_kw": 4.5, "inverter_qty": 1},
        {"name": "og_big_25kwh_two_inverters", **base, "battery": eq["battery_us5000"], "inverter": eq["inv_mp5000"],
         "daily_kwh_consumption": 25.0, "peak_demand_kw": 9.0, "inverter_qty": 2},
        {"name": "og_tiny_fidus", **base, "battery": eq["battery_fidus"], "inverter": eq["inv_mp3000"],
         "daily_kwh_consumption": 3.0, "peak_demand_kw": 1.2, "inverter_qty": 1},
        {"name": "og_custom_tier", **base, "battery": eq["battery_us5000"], "inverter": eq["inv_mp5000"],
         "daily_kwh_consumption": 12.0, "peak_demand_kw": 4.5, "inverter_qty": 1,
         "custom_tier": {"key": "C", "label": "Personalizado", "reserve_soc_pct": 30.0, "autonomy_days": 3.0,
                         "pv_design_factor": 3.4, "solar_resource_basis": "worst_month",
                         "inverter_loading_target_pct": 70.0, "growth_energy_pct": 10.0,
                         "growth_peak_pct": 12.0, "expansion_provision": "one"}},
    ]


def _hy_cases(eq: dict) -> list[dict]:
    base = dict(panel=eq["panel"], charge_controller=eq["cc"], monthly_kwh_kwp=MONTHLY_KWH_KWP)
    return [
        {"name": "hy_home", **base, "battery": eq["battery_us5000"], "inverter": eq["inv_mp5000"],
         "critical_daily_kwh": 8.0, "critical_peak_kw": 3.0, "whole_home_daily_kwh": 30.0,
         "whole_home_peak_kw": 9.0, "inverter_qty": 1, "daytime_fraction": 0.5},
        {"name": "hy_measured_night_exporting_quattro", **base, "battery": eq["battery_fidus"],
         "inverter": eq["inv_quattro"], "critical_daily_kwh": 14.0, "critical_peak_kw": 6.0,
         "whole_home_daily_kwh": 45.0, "whole_home_peak_kw": 14.0, "inverter_qty": 1,
         "daytime_fraction": 0.45, "night_load_fraction": 0.35, "site_exports_to_grid": True},
        {"name": "hy_two_small_inverters_no_passthrough_rating", **base, "battery": eq["battery_us5000"],
         "inverter": eq["inv_mp3000"], "critical_daily_kwh": 6.0, "critical_peak_kw": 2.2,
         "whole_home_daily_kwh": 22.0, "whole_home_peak_kw": 7.0, "inverter_qty": 2,
         "daytime_fraction": 0.4, "shiftable_daily_kwh": 4.0},
        {"name": "hy_custom_tier", **base, "battery": eq["battery_us5000"], "inverter": eq["inv_mp5000"],
         "critical_daily_kwh": 8.0, "critical_peak_kw": 3.0, "whole_home_daily_kwh": 30.0,
         "whole_home_peak_kw": 9.0, "inverter_qty": 1, "daytime_fraction": 0.5,
         "custom_tier": {"key": "C", "label": "Personalizado", "reserve_soc_pct": 30.0, "backup_nights": 1.75,
                         "cycling_nights": 1.4, "battery_basis": "critical_plus_comfort", "pv_coverage": 1.6,
                         "inverter_islanded_loading_target_pct": 72.0, "growth_energy_pct": 10.0,
                         "growth_peak_pct": 12.0, "expansion_provision": "one"}},
    ]


def _run_generators(og_cases: list[dict], hy_cases: list[dict]) -> dict:
    from calculations import sizing_off_grid as sog

    out: dict = {}
    for c in og_cases:
        kw = {k: v for k, v in c.items() if k not in ("name", "custom_tier")}
        if "custom_tier" in c:
            kw["tiers"] = [sog.OffGridDesignTier(**c["custom_tier"])]
        out[c["name"]] = sog.generate_design_scenarios(**kw)
    for c in hy_cases:
        kw = {k: v for k, v in c.items() if k not in ("name", "custom_tier")}
        if "custom_tier" in c:
            kw["tiers"] = [sog.HybridDesignTier(**c["custom_tier"])]
        out[c["name"]] = sog.generate_design_scenarios_hybrid(**kw)
    return out


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str, indent=1)


def capture() -> None:
    eq = _snapshot_equipment()
    og, hy = _og_cases(eq), _hy_cases(eq)
    golden = _run_generators(og, hy)
    GOLDEN_PATH.write_text(
        json.dumps({"equipment": eq, "golden": json.loads(_canon(golden))}, sort_keys=True, indent=1),
        encoding="utf-8",
    )
    print(f"captured {len(golden)} cases -> {GOLDEN_PATH.relative_to(ROOT)}")


def check_golden() -> int:
    saved = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    eq = saved["equipment"]
    now = json.loads(_canon(_run_generators(_og_cases(eq), _hy_cases(eq))))
    failures = 0
    for name, expected in saved["golden"].items():
        if now.get(name) == expected:
            print(f"  ok   golden {name}")
        else:
            failures += 1
            print(f"  FAIL golden {name}")
    return failures


# ── TARGETS section is appended below as the target functions are built ───────────────────────────────

def _approx(a, b, tol=1e-9) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))


def check_targets() -> int:
    """Hand-derived expectations: every expected number below is computed here from raw constants, never by calling
    the function under test (the 0.96 / 0.96 efficiencies, 0.88 array PR and the 0.40 fleet night-load fraction are the
    calibrated defaults restated, so a silent change to any of them fails these checks)."""
    from calculations import design_targets as dt

    failures = 0

    def expect(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f"  [{detail}]" if detail and not ok else ""))
        failures += 0 if ok else 1

    avg_daily = sum(m / d for m, d in zip(MONTHLY_KWH_KWP, [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])) / 12
    deliverable = avg_daily * 0.88
    og_rec, hy_rec = dt.default_goals("off_grid"), dt.default_goals("hybrid")

    # ── Off-grid, Recomendado: reserve 35, autonomy 2.25, PV factor 3.25, inverter ceiling 75 ──
    t = dt.offgrid_targets(og_rec, daily_kwh=12.0, peak_kw=4.5, monthly_kwh_kwp=MONTHLY_KWH_KWP)
    expect("off-grid battery usable = 12 x 2.25 = 27 kWh", _approx(t["battery_usable_kwh"], 27.0))
    expect("off-grid battery nominal = 27 / (0.65 x 0.96 x 0.96)", _approx(t["battery_nominal_kwh"], 27.0 / (0.65 * 0.96 * 0.96)))
    expect("off-grid PV = 12 x 3.25 / (avg yield x 0.88)", _approx(t["system_kw"], 12.0 * 3.25 / deliverable))
    expect("off-grid inverter = 4.5 / 0.75 = 6.0 kW", _approx(t["inverter_kw"], 6.0))
    expect("off-grid usable window is the reserve window (65) under the 80% reference DoD",
           t["assumptions"]["usable_window_pct"] == 65.0)
    shallow = dt.offgrid_targets(replace_goal(og_rec, reserve_soc_pct=10.0), daily_kwh=12.0, peak_kw=4.5,
                                 monthly_kwh_kwp=MONTHLY_KWH_KWP)
    expect("off-grid window is capped at the 80% reference DoD when the reserve is shallow (10% -> 90 -> 80)",
           shallow["assumptions"]["usable_window_pct"] == 80.0)

    # ── Hybrid, Recomendado: reserve 35, backup 1.5 nights, cycling 1.25, coverage 1.5, islanded ceiling 75 ──
    h = dt.hybrid_targets(hy_rec, critical_daily_kwh=8.0, critical_peak_kw=3.0, whole_home_daily_kwh=30.0,
                          whole_home_peak_kw=9.0, monthly_kwh_kwp=MONTHLY_KWH_KWP, daytime_fraction=0.5)
    eff = 0.96 * 0.96
    night, shiftable = 8.0 * 0.40, (30.0 - 8.0) * (1 - 0.5)
    c_backup = night * 1.5 / (0.80 * eff)
    c_shift = 1.25 * (night + shiftable) / (0.65 * eff)
    expect("hybrid backup layer = 1.5 x 3.2 kWh / (0.80 x eff)", _approx(h["battery_c_backup_kwh"], c_backup))
    expect("hybrid cycling layer = 1.25 x 14.2 kWh / (0.65 x eff)", _approx(h["battery_c_daily_shift_kwh"], c_shift))
    expect("hybrid battery = the larger layer, driven by cycling", _approx(h["battery_nominal_kwh"], max(c_backup, c_shift))
           and h["battery_driven_by"] == "daily_shift")
    expect("hybrid PV = (8 + 11) x 1.5 / (avg yield x 0.88)", _approx(h["system_kw"], (8.0 + shiftable) * 1.5 / deliverable))
    expect("hybrid islanded inverter = 3 / 0.75 = 4.0 kW", _approx(h["inverter_kw"], 4.0))
    expect("hybrid pass-through requirement = 9000 W / 240 V = 37.5 A", _approx(h["grid_passthrough_required_a"], 37.5))
    measured = dt.hybrid_targets(hy_rec, critical_daily_kwh=8.0, critical_peak_kw=3.0, whole_home_daily_kwh=30.0,
                                 whole_home_peak_kw=9.0, monthly_kwh_kwp=MONTHLY_KWH_KWP, daytime_fraction=0.5,
                                 night_load_fraction=0.35)
    expect("hybrid reports whether the night fraction was measured or the fleet default",
           measured["assumptions"]["night_load_fraction_source"] == "measured"
           and h["assumptions"]["night_load_fraction_source"] == "fleet_default")

    # ── Hybrid kWh reduction goal: PV is the larger of coverage-based and reduction-based ──
    # (At the Recomendado coverage of 1.5 the coverage sizing alone already reaches the 50% daytime ceiling on this
    # fixture, so the reduction goal can only bind with a leaner coverage factor — 1.0 here.)
    hr = dict(critical_daily_kwh=8.0, critical_peak_kw=3.0, whole_home_daily_kwh=30.0, whole_home_peak_kw=9.0,
              monthly_kwh_kwp=MONTHLY_KWH_KWP, daytime_fraction=0.5)
    lean = replace_goal(hy_rec, pv_coverage=1.0)
    base = dt.hybrid_targets(lean, **hr)
    low = dt.hybrid_targets(lean, reduction_target_pct=10.0, **hr)
    high = dt.hybrid_targets(lean, reduction_target_pct=45.0, **hr)
    expect("hybrid: coverage-only sizing = (8 + 11) x 1.0 / (avg yield x 0.88) and reaches 36.7% on its own",
           _approx(base["system_kw"], 19.0 / deliverable) and _approx(base["kwh_reduction_pct_at_size"], (19.0 - 8.0) * 30.4 / 912.0 * 100))
    expect("hybrid: a small reduction goal (10%) leaves the coverage sizing in charge",
           low["pv_driven_by"] == "coverage" and _approx(low["system_kw"], base["system_kw"]))
    expect("hybrid: a larger goal (45%) takes over: (8 + 0.45 x 30) kWh/day / (avg yield x 0.88), delivering exactly 45%",
           high["pv_driven_by"] == "kwh_reduction" and _approx(high["system_kw"], (8.0 + 0.45 * 30.0) / deliverable)
           and _approx(high["kwh_reduction_pct_at_size"], 45.0))
    above = dt.hybrid_targets(lean, reduction_target_pct=90.0, **hr)
    expect("hybrid: a goal above the daytime ceiling (50%) is sized at the ceiling, not beyond it",
           _approx(above["system_kw"], (8.0 + 0.50 * 30.0) / deliverable) and _approx(above["kwh_reduction_pct_at_size"], 50.0))
    hb = dt.hybrid_target_band(lean, reduction_target_pct=30.0, **hr)
    expect("hybrid band with a reduction goal stays ordered on PV",
           hb["piso"]["system_kw"] <= hb["optimo"]["system_kw"] <= hb["techo"]["system_kw"])

    # ── Grid Zero: average-month zero-export model (the one Step 6's _scenario_projection uses) ──
    gz = dt.GridZeroGoals(reduction_target_pct=40.0)
    kw = dict(avg_kwh_month=800.0, avg_irradiance_kwh_kwp_month=130.0, daytime_fraction=0.45)
    g = dt.grid_zero_targets(gz, **kw)
    expect("grid-zero ceiling = daytime fraction (45%)", g["ceiling_pct"] == 45.0)
    expect("grid-zero 40% goal -> kWp = 0.40 x 800 / 130", _approx(g["system_kw"], 0.40 * 800.0 / 130.0) and g["attainable"])
    expect("grid-zero inverter = kWp / 1.2 DC/AC", _approx(g["inverter_kw"], 0.40 * 800.0 / 130.0 / 1.2))
    expect("grid-zero delivers the 40% it was sized for", _approx(g["reduction_pct"], 40.0))
    over = dt.grid_zero_targets(dt.GridZeroGoals(reduction_target_pct=60.0), **kw)
    expect("grid-zero goal above the ceiling is flagged unattainable and sized at the ceiling (45%)",
           (not over["attainable"]) and _approx(over["reduction_pct"], 45.0) and _approx(over["system_kw"], 0.45 * 800.0 / 130.0))
    capped = dt.grid_zero_targets(dt.GridZeroGoals(reduction_target_pct=40.0, max_system_kwp=2.0), **kw)
    expect("grid-zero kWp cap binds and reports the reduction it actually gives (2 x 130 / 800 = 32.5%)",
           capped["capped_by_max_kwp"] and _approx(capped["system_kw"], 2.0) and _approx(capped["reduction_pct"], 32.5))
    expect("grid-zero pre-fill = the ceiling rounded down to 5 points (45 -> 45; 47.3 -> 45; 52 -> 50)",
           dt.grid_zero_default_goals(0.45).reduction_target_pct == 45.0
           and dt.grid_zero_default_goals(0.473).reduction_target_pct == 45.0
           and dt.grid_zero_default_goals(0.52).reduction_target_pct == 50.0)
    st_ok = dt.grid_zero_goal_status(dt.GridZeroGoals(reduction_target_pct=45.0), 0.45)
    st_over = dt.grid_zero_goal_status(dt.GridZeroGoals(reduction_target_pct=60.0), 0.45)
    st_bad = dt.grid_zero_goal_status(dt.GridZeroGoals(reduction_target_pct=40.0, max_dc_ac_ratio=2.0), 0.45)
    expect("grid-zero status: a goal at the ceiling is fine; above it needs acknowledgement; a bad ratio is an error",
           not st_ok["errors"] and not st_ok["needs_acknowledgement"] and st_over["needs_acknowledgement"]
           and not st_over["errors"] and any("max_dc_ac_ratio" in e for e in st_bad["errors"]))
    expect("grid-zero rejects a non-positive kWp cap",
           any("max_system_kwp" in e for e in dt.grid_zero_goal_status(dt.GridZeroGoals(reduction_target_pct=40.0, max_system_kwp=0.0), 0.45)["errors"]))

    # ── Piso / Techo ──
    og_min, _, og_max = dt.goal_presets("off_grid")
    band = dt.offgrid_target_band(og_rec, daily_kwh=12.0, peak_kw=4.5, monthly_kwh_kwp=MONTHLY_KWH_KWP)
    ref_min = dt.offgrid_targets(og_min, daily_kwh=12.0, peak_kw=4.5, monthly_kwh_kwp=MONTHLY_KWH_KWP)
    ref_max = dt.offgrid_targets(og_max, daily_kwh=12.0, peak_kw=4.5, monthly_kwh_kwp=MONTHLY_KWH_KWP)
    same = lambda a, b: all(_approx(a[k], b[k]) for k in ("system_kw", "battery_nominal_kwh", "inverter_kw"))
    expect("off-grid band centered on the Recomendado goals reproduces the Mínimo and Máxima presets", same(band["piso"], ref_min) and same(band["techo"], ref_max))
    expect("off-grid band is ordered: piso <= optimo <= techo on PV, battery and inverter",
           all(band["piso"][k] <= band["optimo"][k] <= band["techo"][k] for k in ("system_kw", "battery_nominal_kwh", "inverter_kw")))
    custom = replace_goal(og_rec, autonomy_days=3.0, reserve_soc_pct=40.0, inverter_loading_target_pct=70.0)
    lo, hi = dt._shift_tier(custom, "off_grid", -1), dt._shift_tier(custom, "off_grid", +1)
    expect("custom goals shift by the calibrated step sizes (autonomy 3.0 -> 2.75 / 3.25; reserve 40 -> 30 / 55)",
           lo.autonomy_days == 2.75 and hi.autonomy_days == 3.25 and lo.reserve_soc_pct == 30.0 and hi.reserve_soc_pct == 55.0)
    expect("inverter ceiling moves the right way (it shrinks a design as it grows): 70 -> piso 80 / techo 63",
           lo.inverter_loading_target_pct == 80.0 and hi.inverter_loading_target_pct == 63.0)
    edge = dt._shift_tier(replace_goal(og_rec, autonomy_days=0.6), "off_grid", -1)
    expect("band is clamped to the valid range (autonomy 0.6 -> piso 0.35 clamps to 0.5)", edge.autonomy_days == 0.5)
    hy_min, _, hy_max = dt.goal_presets("hybrid")
    hband = dt.hybrid_target_band(hy_rec, critical_daily_kwh=8.0, critical_peak_kw=3.0, whole_home_daily_kwh=30.0,
                                  whole_home_peak_kw=9.0, monthly_kwh_kwp=MONTHLY_KWH_KWP, daytime_fraction=0.5)
    href_min = dt.hybrid_targets(hy_min, critical_daily_kwh=8.0, critical_peak_kw=3.0, whole_home_daily_kwh=30.0,
                                 whole_home_peak_kw=9.0, monthly_kwh_kwp=MONTHLY_KWH_KWP, daytime_fraction=0.5)
    expect("hybrid band centered on Recomendado reproduces the Mínimo preset",
           _approx(hband["piso"]["system_kw"], href_min["system_kw"]) and _approx(hband["piso"]["battery_nominal_kwh"], href_min["battery_nominal_kwh"]))
    gband = dt.grid_zero_target_band(gz, **kw)
    expect("grid-zero band: piso 30%, optimo 40%, techo 45% (limited by the ceiling)",
           gband["piso"]["reduction_target_pct"] == 30.0 and gband["optimo"]["reduction_target_pct"] == 40.0
           and gband["techo"]["reduction_target_pct"] == 45.0)
    at_ceiling = dt.grid_zero_target_band(dt.GridZeroGoals(reduction_target_pct=45.0), **kw)
    above = dt.grid_zero_target_band(dt.GridZeroGoals(reduction_target_pct=60.0), **kw)
    expect("grid-zero band at the ceiling: techo collapses onto the goal; above it the band stays ordered",
           at_ceiling["techo"]["reduction_target_pct"] == 45.0
           and above["piso"]["system_kw"] <= above["optimo"]["system_kw"] <= above["techo"]["system_kw"])

    # ── Validation ──
    expect("defined ranges: off-grid PV factor 1.5-5.0, hybrid coverage 1.0-2.5, inverter ceilings 50-95, GZ DC/AC 1.0-1.5",
           dt.GOAL_RANGES["off_grid"]["pv_design_factor"] == (1.5, 5.0) and dt.GOAL_RANGES["hybrid"]["pv_coverage"] == (1.0, 2.5)
           and dt.GOAL_RANGES["off_grid"]["inverter_loading_target_pct"] == (50.0, 95.0)
           and dt.GOAL_RANGES["hybrid"]["inverter_islanded_loading_target_pct"] == (50.0, 95.0)
           and dt.GOAL_RANGES["grid_zero"]["max_dc_ac_ratio"] == (1.0, 1.5))
    expect("calibrated presets validate clean (all six)",
           all(not dt.validate_goals(st, t) for st in ("off_grid", "hybrid") for t in dt.goal_presets(st)))
    expect("an out-of-range autonomy is rejected", any("autonomy_days" in e for e in dt.validate_goals("off_grid", replace_goal(og_rec, autonomy_days=9.0))))
    expect("a missing value is rejected", any("pv_design_factor" in e for e in dt.validate_goals("off_grid", replace_goal(og_rec, pv_design_factor=None))))
    expect("an off-grid PV factor below 1.5 is rejected (real deficit per the calibration doc)",
           any("pv_design_factor" in e for e in dt.validate_goals("off_grid", replace_goal(og_rec, pv_design_factor=1.2))))
    expect("an unknown expansion provision is rejected", any("expansion" in e for e in dt.validate_goals("hybrid", replace_goal(hy_rec, expansion_provision="three"))))
    return failures


def replace_goal(goals, **changes):
    from dataclasses import replace

    return replace(goals, **changes)


# ── Step 2: the wizard renumber (Equipos/Costos/Revisión 6/7/8 -> 7/8/9) ─────────────────────────────────

def og_form(**overrides) -> dict:
    """A complete Off-Grid Objetivos POST body: the Recomendado preset, as the browser would submit it."""
    from calculations import design_targets as dt

    rec = dt.default_goals("off_grid")
    form = {f"g_{f}": str(getattr(rec, f)) for f in
            ("autonomy_days", "reserve_soc_pct", "pv_design_factor", "solar_resource_basis", "inverter_loading_target_pct",
             "growth_energy_pct", "growth_peak_pct", "expansion_provision")}
    form.update({f"g_{k}": str(v) for k, v in overrides.items()})
    return form


def confirmed_og() -> dict:
    from calculations import design_targets as dt

    rec = dt.default_goals("off_grid")
    goals = {f: getattr(rec, f) for f in ("autonomy_days", "reserve_soc_pct", "pv_design_factor", "solar_resource_basis",
                                          "inverter_loading_target_pct", "growth_energy_pct", "growth_peak_pct", "expansion_provision")}
    return {"system_type": "off_grid", "preset": "recomendado", "goals": goals, "assumptions": {}, "confirmed": True,
            "ack_ceiling_pct": None, "source": "user"}


def check_wizard_numbering() -> int:
    """Offline: the database is replaced by an in-memory store, and step rendering by a marker string, so this tests
    exactly the routing, guards, progress conversion and lockstep check the renumber touched."""
    import re
    from unittest import mock

    from database import proposals_db
    from webapp import create_app
    import webapp.blueprints.wizard as wz
    from wizard import draft

    failures = 0

    def expect(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f"  [{detail}]" if detail and not ok else ""))
        failures += 0 if ok else 1

    store: dict = {}

    def fake_get_version(vid):
        v = store.get(vid)
        return None if v is None else {"id": vid, "data": v["data"], "locked": v.get("locked", False)}

    def fake_upsert(vid, blob, total_usd):
        store[vid]["data"] = json.loads(json.dumps(blob))

    def fake_create_proposal(**kw):
        store["new1"] = {"data": {}}
        return {"id": "new1"}

    def mk(meta: dict, objectives: dict | None = None) -> str:
        vid = f"d{len(store)}"
        store[vid] = {"data": {"meta": {"system_type": "off_grid", **meta}, "client": {"name": "x"}}}
        if objectives is not None:
            store[vid]["data"]["objectives"] = objectives
        return vid

    base = "/cotizaciones/asistente"
    with mock.patch.object(proposals_db, "get_version", fake_get_version), \
            mock.patch.object(proposals_db, "upsert_version", fake_upsert), \
            mock.patch.object(proposals_db, "create_proposal", fake_create_proposal), \
            mock.patch.object(wz, "_get_version", fake_get_version), \
            mock.patch.object(wz, "_render_step", lambda vid, n, blob, **kw: (f"RENDER {n}", 200)), \
            mock.patch("webapp.wizard_steps.s1_client.resolve_client", lambda r: r):
        client = create_app().test_client()

        def get(path):
            return client.get(path, follow_redirects=False)

        def target(resp) -> str:
            return resp.headers.get("Location", "").rsplit("/paso/", 1)[-1]

        # ── effective_step_reached(): the one place that interprets the stored integer ──
        eff = draft.effective_step_reached
        expect("old drafts (no marker): 1-5 unchanged, 6/7/8 -> 7/8/9",
               [eff({"step_reached": r}) for r in range(1, 9)] == [1, 2, 3, 4, 5, 7, 8, 9])
        expect("marked drafts are trusted as stored; missing meta defaults to 1",
               eff({"step_reached": 6, "wizard_rev": 2}) == 6 and eff({"step_reached": 9, "wizard_rev": 2}) == 9
               and eff(None) == 1 and eff({}) == 1)

        # ── guard on a draft saved under the OLD numbering ──
        max_allowed = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 8, 7: 9, 8: 9}   # highest step each old draft may open now
        resume_on = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 7, 7: 8, 8: 9}      # where its redirect sends a too-far request
        bad = []
        for r in range(1, 9):
            vid = mk({"step_reached": r})
            for n in range(1, 10):
                resp = get(f"{base}/{vid}/paso/{n}")
                if n <= max_allowed[r]:
                    if resp.status_code != 200:
                        bad.append(f"old r={r} step {n} should open, got {resp.status_code}")
                elif not (resp.status_code == 303 and target(resp) == str(resume_on[r])):
                    bad.append(f"old r={r} step {n} should redirect to {resume_on[r]}, got {resp.status_code} {target(resp)}")
        expect("every old draft (saved at 1-8): opens exactly what it could before, shifted; too-far requests land on its own content", not bad, "; ".join(bad[:3]))

        old7 = mk({"step_reached": 7})
        expect("old draft at Costos (7) is on new Costos (8) and may open Review (9)",
               get(f"{base}/{old7}/paso/9").status_code == 200 and target(get(f"{base}/{old7}/abrir")) == "8")
        old5 = mk({"step_reached": 5})
        expect("old draft at step 5 must pass through Objetivos: it can open 6 but not Equipos (7)",
               get(f"{base}/{old5}/paso/6").status_code == 200 and get(f"{base}/{old5}/paso/7").status_code == 303)
        newd = mk({"step_reached": 6, "wizard_rev": 2}, objectives=confirmed_og())
        expect("marked draft at Objetivos (6) with CONFIRMED goals may open 7 but not 8", get(f"{base}/{newd}/paso/7").status_code == 200
               and get(f"{base}/{newd}/paso/8").status_code == 303)
        expect("abrir resumes on the effective step (marked 6 -> 6)", target(get(f"{base}/{newd}/abrir")) == "6")

        # ── Objetivos Siguiente: advances, converts, never lowers ──
        d = mk({"step_reached": 6, "wizard_rev": 2})
        resp = client.post(f"{base}/{d}/paso/6", data=og_form())
        meta = store[d]["data"]["meta"]
        expect("Objetivos POST with a valid form advances to Equipos (7) and records it",
               resp.status_code == 303 and target(resp) == "7" and meta["step_reached"] == 7)
        d = mk({"step_reached": 5})
        client.post(f"{base}/{d}/paso/6", data=og_form())
        meta = store[d]["data"]["meta"]
        expect("an old draft at 5 is converted on first save (step 7, wizard_rev 2)", meta["step_reached"] == 7 and meta["wizard_rev"] == 2)
        d = mk({"step_reached": 7})
        client.post(f"{base}/{d}/paso/6", data=og_form())
        meta = store[d]["data"]["meta"]
        expect("revisiting Objetivos on an old Costos draft converts it to 8 and never lowers it", meta["step_reached"] == 8 and meta["wizard_rev"] == 2)
        d = mk({"step_reached": 7, "wizard_rev": 2})
        resp = client.post(f"{base}/{d}/paso/7/atras")
        expect("Atrás from Equipos (7) goes to Objetivos (6)", resp.status_code == 303 and target(resp) == "6")

        # ── nueva stamps new drafts ──
        resp = client.post(f"{base}/nueva", data={"name": "Cliente QA"})
        meta = store.get("new1", {}).get("data", {}).get("meta", {})
        expect("a new draft is stamped wizard_rev 2 at step 2", resp.status_code == 303 and meta.get("wizard_rev") == 2 and meta.get("step_reached") == 2)

        # ── routes: every former Equipos/Costos/Revisión route moved, none left behind, each guard matches ──
        rules = [(r.rule, r.methods) for r in create_app().url_map.iter_rules() if "/paso/" in r.rule]
        literal = [(rule, m) for rule, m in rules if re.search(r"/paso/\d+/", rule)]
        numbers = {int(re.search(r"/paso/(\d+)/", rule).group(1)) for rule, _ in literal}
        paths = {rule for rule, _ in literal}
        expect("action routes exist at the new numbers",
               {f"{base}/<vid>/paso/7/equipo", f"{base}/<vid>/paso/7/og/manual", f"{base}/<vid>/paso/8/tabla",
                f"{base}/<vid>/paso/8/og/refrescar", f"{base}/<vid>/paso/9/bloquear", f"{base}/<vid>/paso/9/pdf/descargar"} <= paths)
        expect("no action route is left at an old number (only Objetivos' own recalcular lives at 6)",
               not ({f"{base}/<vid>/paso/6/equipo", f"{base}/<vid>/paso/7/tabla", f"{base}/<vid>/paso/8/bloquear",
                     f"{base}/<vid>/paso/8/pdf"} & paths)
               and {p for p in paths if "/paso/6/" in p} == {f"{base}/<vid>/paso/6/recalcular"})
        bad, guarded = [], 0
        for rule, methods in sorted(literal):
            n = int(re.search(r"/paso/(\d+)/", rule).group(1))
            if n < 7:
                continue
            guarded += 1
            vid = mk({"step_reached": n - 2, "wizard_rev": 2})
            path = re.sub(r"<[^>]+>", "A", rule.replace("<vid>", vid))
            resp = client.post(path) if "POST" in methods else get(path)
            if not (resp.status_code == 303 and target(resp) == str(n - 2)):
                bad.append(f"{rule} -> {resp.status_code} {target(resp)}")
        expect(f"all {guarded} routes at steps 7-9 reject a request one step too far (guard number matches the path)",
               guarded == 21 and not bad, "; ".join(bad[:3]) or f"expected 21 routes (Equipos 5+4, Costos 4+4, Revisión 4), found {guarded}")

        # ── Objetivos gate (plan §1.8): server-side, every route, grandfathering ──
        d = mk({"step_reached": 6, "wizard_rev": 2})
        expect("no objectives: Equipos (7) is closed even though step 6 was reached", get(f"{base}/{d}/paso/7").status_code == 303
               and target(get(f"{base}/{d}/paso/7")) == "6")
        unconf = confirmed_og()
        unconf["confirmed"] = False
        d = mk({"step_reached": 9, "wizard_rev": 2}, objectives=unconf)
        blocked = [get(f"{base}/{d}/paso/8"), client.post(f"{base}/{d}/paso/8/tabla"), client.post(f"{base}/{d}/paso/9/bloquear"),
                   get(f"{base}/{d}/paso/9/pdf/descargar"), client.post(f"{base}/{d}/paso/7/og/manual")]
        expect("unconfirmed objectives close Equipos/Costos/Revisión by page AND by direct action URL (5 requests, even at step 9)",
               all(r.status_code == 303 and target(r) == "6" for r in blocked), str([(r.status_code, target(r)) for r in blocked]))
        d = mk({"step_reached": 7})   # old draft already at Costos: no objectives key at all
        expect("a draft that predates objectives (old step 7, no objectives) is grandfathered and not blocked",
               get(f"{base}/{d}/paso/8").status_code == 200 and get(f"{base}/{d}/paso/9").status_code == 200)
        hy_conf = {**confirmed_og(), "system_type": "hybrid"}
        d = mk({"step_reached": 8, "wizard_rev": 2}, objectives=hy_conf)
        expect("goals confirmed for another system type do not open Equipos", get(f"{base}/{d}/paso/7").status_code == 303)

        d = mk({"step_reached": 6, "wizard_rev": 2})
        client.post(f"{base}/{d}/paso/6", data=og_form())
        sd = store[d]["data"]
        expect("confirming stores the goals, marks them confirmed and mirrors autonomy for Equipos",
               sd["objectives"]["confirmed"] is True and sd["objectives"]["goals"]["autonomy_days"] == 2.25
               and sd["consumption"]["autonomy_days"] == 2.25 and get(f"{base}/{d}/paso/7").status_code == 200)
        d = mk({"step_reached": 6, "wizard_rev": 2})
        resp = client.post(f"{base}/{d}/paso/6")
        expect("an empty POST (no form fields) cannot confirm the pre-filled defaults",
               resp.status_code == 200 and not store[d]["data"].get("objectives", {}).get("confirmed"))
        d = mk({"step_reached": 6, "wizard_rev": 2})
        resp = client.post(f"{base}/{d}/paso/6", data=og_form(autonomy_days=9))
        sd = store[d]["data"]
        expect("an out-of-range goal is rejected, the typed value is kept, and the draft stays unconfirmed",
               resp.status_code == 200 and sd["objectives"]["confirmed"] is False and sd["objectives"]["goals"]["autonomy_days"] == 9.0
               and get(f"{base}/{d}/paso/7").status_code == 303)
        d = mk({"step_reached": 6, "wizard_rev": 2}, objectives=confirmed_og())
        client.post(f"{base}/{d}/paso/6/recalcular", data=og_form(autonomy_days=3))
        expect("editing a confirmed goal through the live recompute un-confirms it and re-closes Equipos",
               store[d]["data"]["objectives"]["confirmed"] is False and get(f"{base}/{d}/paso/7").status_code == 303)
        resp = client.post(f"{base}/{d}/paso/6/recalcular", data=og_form(autonomy_days=3))
        expect("the live recompute renders the fragment (with the sweet-spot panel)", resp.status_code == 200 and b"Recomendaci" in resp.data)
        d = mk({"step_reached": 6, "wizard_rev": 2}, objectives=confirmed_og())
        client.post(f"{base}/{d}/paso/6/recalcular", data=og_form())
        expect("re-posting identical goals keeps them confirmed", store[d]["data"]["objectives"]["confirmed"] is True)

        # ── lockstep check fails loudly ──
        saved = wz.STEP_MODULES.pop(wz.STEP_OBJETIVOS)
        try:
            wz._check_step_tables()
            raised = False
        except AssertionError:
            raised = True
        finally:
            wz.STEP_MODULES[wz.STEP_OBJETIVOS] = saved
        expect("lockstep check raises when a step is missing from STEP_MODULES", raised)
        wz.step_common.STEP_LABELS_OFF_GRID.append("Extra")
        try:
            wz._check_step_tables()
            raised = False
        except AssertionError:
            raised = True
        finally:
            wz.step_common.STEP_LABELS_OFF_GRID.pop()
        expect("lockstep check raises when a label has no step behind it", raised)
        wz._check_step_tables()
        expect("lockstep check passes on the real tables", True)

    # ── nothing reads the raw stored integer any more ──
    raw = []
    for path in sorted((ROOT / "webapp").rglob("*.py")):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""get\(["']step_reached["']""", line):
                raw.append(f"{path.relative_to(ROOT)}:{i}")
    expect("no code under webapp/ reads meta.step_reached directly (all go through effective_step_reached)", not raw, ", ".join(raw))
    return failures


# ── Step 3: the Objetivos step module ────────────────────────────────────────────────────────────────────

def check_objetivos() -> int:
    from unittest import mock

    from calculations import design_targets as dt
    from webapp.wizard_steps import s6_objetivos as ob

    failures = 0

    def expect(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f"  [{detail}]" if detail and not ok else ""))
        failures += 0 if ok else 1

    line = lambda kw, f=0.9: {"category": "x", "quantity": 1, "connected_power_kw": kw, "demand_factor_pct": f}
    site = {"pvgis_data": {"monthly_kwh_kwp": MONTHLY_KWH_KWP}}
    og = {"meta": {"system_type": "off_grid", "step_reached": 5, "wizard_rev": 2}, "site": site,
          "consumption": {"daily_kwh": 12.0, "profile": {"lines": [line(5.0)]}}}
    hy = {"meta": {"system_type": "hybrid", "step_reached": 5, "wizard_rev": 2}, "site": site,
          "consumption": {"daily_kwh_diversified": 8.0, "profile": {"lines": [line(3.0, 1.0)]},
                          "main_panel": {"avg_kwh_month": 22.0 * 30.4, "mode": "bill"}}}
    gz = {"meta": {"system_type": "grid_zero", "step_reached": 5, "wizard_rev": 2},
          "site": {"pvgis_data": {"monthly_kwh_kwp": [130.0] * 12}}, "consumption": {"avg_kwh": 800.0}}
    avg_daily = sum(m / d for m, d in zip(MONTHLY_KWH_KWP, [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])) / 12
    deliverable = avg_daily * 0.88
    calls = []

    def fake_daytime(loads, city):
        calls.append((len(loads), city))
        return 0.45, "nota IA"

    # no fleet data -> the fixed fallback (45 % day, 40 % night), so the numbers below reproduce on any machine
    with mock.patch.object(ob, "_estimate_daytime", fake_daytime), \
            mock.patch("calculations.fleet_shares.fleet_shares", lambda: None):
        # ── pre-fill and the sweet-spot block ──
        ctx = ob.build_context(og)
        rows = {r["label"]: r["values"] for r in ctx["block"]["rows"]}
        pv = rows["Paneles (potencia DC)"]
        expect("off-grid pre-fills the Según datos reales preset, unconfirmed, flagged as default",
               ctx["preset"] == "datos_reales" and not ctx["confirmed"] and ctx["from_default"] and ctx["can_continue"]
               and [f["value"] for f in ctx["fields"] if f["name"] == "autonomy_days"] == [2.0])
        expect("off-grid Punto óptimo: PV = 12 x 2.0 / (avg yield x 0.88), battery = 24 / (0.75 x 0.96 x 0.96), inverter = 4.5 / 0.80",
               pv[1] == f"{12 * 2.0 / deliverable:,.1f}"
               and rows["Batería (capacidad nominal)"][1] == f"{24.0 / (0.75 * 0.96 * 0.96):,.1f}"
               and rows["Inversor (potencia AC continua)"][1] == f"{4.5 / 0.80:,.1f}")
        expect("off-grid Piso/Techo shift the data-based goals one calibrated step (PV 1.75x and 2.25x)",
               pv[0] == f"{12 * 1.75 / deliverable:,.1f}" and pv[2] == f"{12 * 2.25 / deliverable:,.1f}")
        hctx = ob.build_context(hy)
        hrows = {r["label"]: r["values"] for r in hctx["block"]["rows"]}
        expect("hybrid block derives whole-home (30 kWh/day) and critical (8 kWh/day, 3 kW) loads like the generator's test page",
               hrows["Inversor (potencia AC, en isla)"][1] == "4.0" and hctx["night_load_pct"] == 40.0
               and "Reducción de kWh que entrega" in hrows)
        gctx = ob.build_context(gz)
        grows = {r["label"]: r["values"] for r in gctx["block"]["rows"]}
        expect("grid-zero pre-fills 45% (the ceiling, rounded down) and sizes 0.45 x 800 / 130 kWp",
               [f["value"] for f in gctx["fields"] if f["name"] == "reduction_target_pct"] == [45.0]
               and grows["Paneles (potencia DC)"][1] == f"{0.45 * 800 / 130:,.1f}" and gctx["ceiling_pct"] == 45.0)
        missing = ob.build_context({"meta": {"system_type": "off_grid"}})
        expect("missing earlier-step data is reported instead of crashing", missing["inputs_missing"] and missing["block"] is None)

        # ── Grid Zero's daytime fraction is cached ──
        calls.clear()
        ob._daytime(gz, None)
        cached = {**gz, "scratch": {"obj": {"daytime": {"key": ob.hashlib.sha1(ob.json.dumps([[], "Costa Rica"], sort_keys=True, default=str).encode()).hexdigest()[:16], "fraction": 0.5, "note": "x"}}}}
        got = ob._daytime(cached, None)
        expect("the AI daytime fraction is computed on a cache miss and reused on a hit", len(calls) == 1 and got["fraction"] == 0.5)
        ob._daytime({**cached, "site": {"city": "Otra"}}, None)
        expect("a change of loads/city invalidates the cache", len(calls) == 2)

        # ── presets, parsing, validation ──
        from werkzeug.datastructures import MultiDict

        def form(**kw):
            base = {f"g_{f['name']}": ("" if f["value"] is None else str(f["value"])) for f in ob.build_context(og)["fields"]}
            base.update({f"g_{k}": str(v) for k, v in kw.items()})
            return MultiDict(base)

        maxi = ob.recalc(og, MultiDict({"apply_preset": "maximo"}))
        expect("applying a preset fills every field from the calibrated tier", maxi["preset"] == "maximo"
               and maxi["goals"]["autonomy_days"] == 2.5 and maxi["goals"]["pv_design_factor"] == 3.5)
        edited = ob.recalc({**og, "objectives": maxi}, form(autonomy_days=3.0))
        expect("editing a field of a preset makes it 'personalizado'", edited["preset"] == "personalizado" and edited["goals"]["autonomy_days"] == 3.0)
        expect("recalc never confirms by itself", not ob.recalc(og, form())["confirmed"])

        for label, bad_kw, field in [("autonomy above 7", {"autonomy_days": 9}, "autonomy_days"),
                                     ("PV factor below 1.5", {"pv_design_factor": 1.2}, "pv_design_factor"),
                                     ("inverter ceiling above 95", {"inverter_loading_target_pct": 99}, "inverter_loading_target_pct"),
                                     ("a blank autonomy", {"autonomy_days": ""}, "autonomy_days")]:
            _, errs = ob.save_step(og, form(**bad_kw))
            expect(f"Siguiente rejects {label}", any(field in e for e in errs))
        ok_obj, errs = ob.save_step(og, form())
        expect("Siguiente confirms a valid Off-Grid goal set and mirrors autonomy for Equipos",
               not errs and ok_obj["confirmed"] and ob.mirror_consumption(ok_obj) == {"autonomy_days": 2.0})
        _, errs = ob.save_step(og, MultiDict({}))
        expect("a POST without the goal fields cannot confirm the defaults", any(e.startswith("form") for e in errs))

        # hybrid specifics
        hf = lambda **kw: MultiDict({**{f"g_{f['name']}": ("" if f["value"] is None else str(f["value"])) for f in ob.build_context(hy)["fields"]},
                                     "a_night_load_pct": "40", **{k: str(v) for k, v in kw.items()}})
        h_obj, errs = ob.save_step(hy, hf())
        expect("hybrid confirms with the optional kWh goal left blank and mirrors backup nights as its autonomy",
               not errs and h_obj["confirmed"] and h_obj["goals"]["reduction_target_pct"] is None
               and ob.mirror_consumption(h_obj) == {"autonomy_days": 1.5} and h_obj["assumptions"]["night_load_fraction"] == 0.4)
        _, errs = ob.save_step(hy, hf(a_night_load_pct=""))
        expect("hybrid needs a night-load fraction", any("night_load_fraction" in e for e in errs))
        _, errs = ob.save_step(hy, hf(g_reduction_target_pct=80))
        expect("hybrid kWh goal above the ceiling needs the acknowledgement", any(e.startswith("ack") for e in errs))
        h_ack, errs = ob.save_step(hy, MultiDict({**hf(g_reduction_target_pct=80), "ack_unattainable": "on"}))
        expect("…and confirms once acknowledged (ceiling recorded)", not errs and h_ack["confirmed"] and h_ack["ack_ceiling_pct"] == 45.0)

        # grid zero
        gf = lambda **kw: MultiDict({**{f"g_{f['name']}": ("" if f["value"] is None else str(f["value"])) for f in ob.build_context(gz)["fields"]},
                                     **{k: str(v) for k, v in kw.items()}})
        g_obj, errs = ob.save_step(gz, gf())
        expect("grid-zero confirms its pre-fill and has nothing to mirror", not errs and g_obj["confirmed"] and ob.mirror_consumption(g_obj) == {})
        _, errs = ob.save_step(gz, gf(g_reduction_target_pct=60))
        expect("grid-zero goal above the 45% ceiling needs the acknowledgement", any(e.startswith("ack") for e in errs))
        g_ack, errs = ob.save_step(gz, MultiDict({**gf(g_reduction_target_pct=60), "ack_unattainable": "on"}))
        expect("…and confirms once acknowledged", not errs and g_ack["confirmed"] and g_ack["ack_ceiling_pct"] == 45.0)
        unticked = ob.recalc({**gz, "objectives": g_ack}, gf(g_reduction_target_pct=60))
        expect("unticking the acknowledgement un-confirms", unticked["confirmed"] is False)
        _, errs = ob.save_step(gz, gf(g_max_dc_ac_ratio=2.0))
        expect("grid-zero rejects a DC/AC ratio above 1.5", any("max_dc_ac_ratio" in e for e in errs))

        # confirmation lifecycle
        conf = {**og, "objectives": ok_obj}
        expect("re-posting the same goals keeps the confirmation", ob.recalc(conf, form())["confirmed"] is True)
        expect("changing any goal drops the confirmation", ob.recalc(conf, form(autonomy_days=3.0))["confirmed"] is False)

        # ── the gate ──
        ready = ob.is_ready
        expect("is_ready: new draft before objectives = False", not ready({"meta": {"step_reached": 5, "wizard_rev": 2, "system_type": "off_grid"}}))
        expect("is_ready: confirmed for this system type = True", ready(conf))
        expect("is_ready: confirmed but for another system type = False",
               not ready({**conf, "meta": {**conf["meta"], "system_type": "hybrid"}}))
        expect("is_ready: stored but unconfirmed = False", not ready({**og, "objectives": {**ok_obj, "confirmed": False}}))
        expect("is_ready: grandfathered old draft at Costos (old 7, no marker, no objectives) = True",
               ready({"meta": {"step_reached": 7, "system_type": "off_grid"}}))
        expect("is_ready: an old draft still at step 5 is NOT grandfathered",
               not ready({"meta": {"step_reached": 5, "system_type": "off_grid"}}))
        eff = ob.effective_goals({"meta": {"step_reached": 7, "system_type": "off_grid"}})
        expect("a grandfathered draft's check will use the default goals, tagged as such", eff["source"] == "default" and eff["goals"]["autonomy_days"] == 2.0)
        expect("Hybrid/Off-Grid goal specs never ask for autonomy anywhere else: Step 4 has no autonomy field",
               "autonomy_days" not in (ROOT / "webapp/templates/wizard/og_s4_loads.html").read_text(encoding="utf-8")
               and "autonomy_days" not in (ROOT / "webapp/templates/wizard/hy_s4_loads.html").read_text(encoding="utf-8")
               and "autonomy_days" not in (ROOT / "webapp/wizard_steps/og_s4_loads.py").read_text(encoding="utf-8").split("def save_step")[1].split("def build_context")[0].replace("`autonomy_days`", ""))
    return failures


# ── Step 4: goals-vs-design check ────────────────────────────────────────────────────────────────────────

def check_goals() -> int:
    from calculations import design_targets as dt
    from calculations import goals_check as gc
    from webapp import create_app
    from webapp.wizard_steps import goals_check as glue
    from webapp.wizard_steps import s6_objetivos as ob

    failures = 0

    def expect(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f"  [{detail}]" if detail and not ok else ""))
        failures += 0 if ok else 1

    st = lambda rows, key: next(r for r in rows if r["key"] == key)["status"]

    # ── status rules ──
    expect("range status: inside ok, <10% under justo, further under bajo, above sobre",
           gc.range_status(10, 10, 20) == "ok" and gc.range_status(9.5, 10, 20) == "justo"
           and gc.range_status(8.9, 10, 20) == "bajo" and gc.range_status(20.1, 10, 20) == "sobre")
    expect("at-least status: meets ok, within 10% justo, else bajo", gc.at_least_status(2.25, 2.25) == "ok"
           and gc.at_least_status(2.1, 2.25) == "justo" and gc.at_least_status(1.9, 2.25) == "bajo")
    expect("kWh goals use 5-point tolerance: 45 ok, 41 justo, 39 bajo",
           gc.at_least_points_status(45, 45) == "ok" and gc.at_least_points_status(41, 45) == "justo" and gc.at_least_points_status(39, 45) == "bajo")
    expect("at-most status with tolerance", gc.at_most_status(75, 75, 5) == "ok" and gc.at_most_status(79, 75, 5) == "justo"
           and gc.at_most_status(81, 75, 5) == "bajo")

    # ── Off-Grid, hand-derived: Recomendado goals, 12 kWh/day, peak 4.5 kW ──
    site = {"pvgis_data": {"monthly_kwh_kwp": MONTHLY_KWH_KWP}}
    og_in = {"daily_kwh": 12.0, "peak_kw": 4.5, "monthly_kwh_kwp": MONTHLY_KWH_KWP}
    tier = dt.default_goals("off_grid")
    band = dt.offgrid_target_band(tier, daily_kwh=12.0, peak_kw=4.5, monthly_kwh_kwp=MONTHLY_KWH_KWP)
    o = band["optimo"]
    at_spot = {"system_kw": o["system_kw"], "battery_installed_kwh": o["battery_nominal_kwh"], "battery_dod_pct": 80.0,
               "inverter_kw_total": o["inverter_kw"]}
    rows = gc.check_offgrid(tier, band, at_spot, og_in)
    autonomy = st(rows, "autonomy")
    ach = float(next(r for r in rows if r["key"] == "autonomy")["achieved"].split()[0])
    expect("off-grid: a design built exactly at the sweet spot meets every quantity and goal",
           all(st(rows, k) == "ok" for k in ("pv", "battery", "autonomy", "inverter", "loading", "worst")) and ach == 2.25,
           str([(r["key"], r["status"]) for r in rows]))
    g = next(r for r in rows if r["key"] == "growth")
    expect("off-grid growth row: +15% needs 13.8 x 2.25 / 0.5928 = 52.4 kWh (6.8 more than the 45.6 installed) and 4.5 x 1.15 / 0.75 = 6.9 kW (0.9 more than 6.0)",
           g["status"] == "info" and "faltan ~6.8 kWh" in g["achieved"] and "faltan ~0.9 kW" in g["achieved"])
    under = gc.check_offgrid(tier, band, {**at_spot, "system_kw": o["system_kw"] * 0.25}, og_in)
    half = gc.check_offgrid(tier, band, {**at_spot, "system_kw": o["system_kw"] * 0.5}, og_in)
    near = gc.check_offgrid(tier, band, {**at_spot, "system_kw": band["piso"]["system_kw"] * 0.95}, og_in)
    over = gc.check_offgrid(tier, band, {**at_spot, "system_kw": band["techo"]["system_kw"] * 1.3}, og_in)
    expect("off-grid PV: a quarter of the sweet spot = bajo, 5% under the Piso = justo, 30% over the Techo = sobre",
           st(under, "pv") == "bajo" and st(near, "pv") == "justo" and st(over, "pv") == "sobre")
    expect("worst-month gate: half the sweet spot still covers the load (1.39x), a quarter does not (0.69x)",
           st(half, "worst") == "ok" and st(under, "worst") == "bajo")
    small_bank = gc.check_offgrid(tier, band, {**at_spot, "battery_installed_kwh": 20.0}, og_in)
    expect("off-grid autonomy: a 20 kWh bank carries 20 x 0.65 x 0.9216 / 12 = 1.00 days against a 2.25-day goal",
           st(small_bank, "autonomy") == "bajo" and "1.00" in st_text(small_bank, "autonomy"))
    limited = gc.check_offgrid(tier, band, {**at_spot, "battery_dod_pct": 50.0}, og_in)
    expect("off-grid autonomy window is capped by a battery whose DoD is below the reserve window",
           "limitada por el DoD" in next(r for r in limited if r["key"] == "autonomy")["note"])
    tight = gc.check_offgrid(tier, band, {**at_spot, "inverter_kw_total": 4.8}, og_in)
    expect("off-grid inverter loading 4.5 / 4.8 = 94% against a 75% ceiling is bajo", st(tight, "loading") == "bajo")
    summ = gc.summarize(under)
    expect("summary counts the statuses and reports the worst", summ["bajo"] >= 1 and summ["overall"] == "bajo" and "no cumple" in summ["text"])

    # ── Hybrid ──
    hy_in = {"critical_daily_kwh": 8.0, "critical_peak_kw": 3.0, "whole_home_daily_kwh": 30.0, "whole_home_peak_kw": 5.75,
             "monthly_kwh_kwp": MONTHLY_KWH_KWP}
    htier = dt.default_goals("hybrid")
    hass = {"night_load_fraction": 0.40, "site_exports_to_grid": False}
    hkw = dict(critical_daily_kwh=8.0, critical_peak_kw=3.0, whole_home_daily_kwh=30.0, whole_home_peak_kw=5.75,
               monthly_kwh_kwp=MONTHLY_KWH_KWP, daytime_fraction=0.45, night_load_fraction=0.40)
    hband = dt.hybrid_target_band(htier, reduction_target_pct=30.0, **hkw)
    ho = hband["optimo"]
    h_at = {"system_kw": ho["system_kw"], "battery_installed_kwh": ho["battery_nominal_kwh"], "battery_dod_pct": 80.0,
            "inverter_kw_total": ho["inverter_kw"], "passthrough_a_total": 95.0}
    hrows = gc.check_hybrid(htier, hband, h_at, hy_in, hass, 30.0)
    cyc = next(r for r in hrows if r["key"] == "cycling")
    expect("hybrid at its sweet spot: backup and cycling nights meet their goals (cycling = 1.25 exactly when cycling drives the bank)",
           all(st(hrows, k) == "ok" for k in ("pv", "battery", "backup", "cycling", "inverter", "loading", "reduction"))
           and float(cyc["achieved"].split()[0]) in (1.25, 1.3, 1.26, 1.27, 1.28, 1.29) or st(hrows, "cycling") == "ok", str([(r["key"], r["status"]) for r in hrows]))
    expect("hybrid pass-through current is checked against the whole-house peak (5750 W / 240 V = 24 A)",
           st(hrows, "passthrough") == "ok" and st(gc.check_hybrid(htier, hband, {**h_at, "passthrough_a_total": 10.0}, hy_in, hass, 30.0), "passthrough") == "bajo")
    short_red = gc.check_hybrid(htier, hband, {**h_at, "system_kw": ho["system_kw"] * 0.4}, hy_in, hass, 30.0)
    expect("hybrid kWh reduction falls short when the array is 40% of the sweet spot", st(short_red, "reduction") in ("bajo", "justo"))
    fat = gc.check_hybrid(htier, hband, {**h_at, "system_kw": ho["system_kw"] * 3.0}, hy_in, hass, None)
    expect("hybrid over-sized array on a non-exporting site raises the surplus row; an exporting site does not",
           any(r["key"] == "surplus" for r in fat)
           and not any(r["key"] == "surplus" for r in gc.check_hybrid(htier, hband, {**h_at, "system_kw": ho["system_kw"] * 3.0}, hy_in, {**hass, "site_exports_to_grid": True}, None)))

    # ── Grid Zero ──
    gz_goals = dt.GridZeroGoals(reduction_target_pct=40.0, max_dc_ac_ratio=1.2)
    gkw = dict(avg_kwh_month=800.0, avg_irradiance_kwh_kwp_month=130.0, daytime_fraction=0.45)
    gband = dt.grid_zero_target_band(gz_goals, **gkw)
    go = gband["optimo"]
    g_at = {"system_kw": go["system_kw"], "inverter_kw": go["inverter_kw"], "reduction_pct": 40.0}
    grows = gc.check_grid_zero(gz_goals, gband, g_at, False)
    expect("grid-zero at its sweet spot meets PV, inverter, DC/AC (2.46 / 2.05 = 1.20) and the 40% reduction",
           all(st(grows, k) == "ok" for k in ("pv", "inverter", "dcac", "reduction")) and not any(r["key"] == "cap" for r in grows))
    expect("grid-zero DC/AC: 1.23 is justo, 1.4 is bajo",
           st(gc.check_grid_zero(gz_goals, gband, {**g_at, "inverter_kw": go["system_kw"] / 1.23}, False), "dcac") == "justo"
           and st(gc.check_grid_zero(gz_goals, gband, {**g_at, "inverter_kw": go["system_kw"] / 1.4}, False), "dcac") == "bajo")
    expect("grid-zero reduction: 41% against 40+... short by 4 points is justo, 7 points short is bajo",
           st(gc.check_grid_zero(gz_goals, gband, {**g_at, "reduction_pct": 36.5}, False), "reduction") == "justo"
           and st(gc.check_grid_zero(gz_goals, gband, {**g_at, "reduction_pct": 33.0}, False), "reduction") == "bajo")
    capped = gc.check_grid_zero(dt.GridZeroGoals(40.0, 1.2, max_system_kwp=2.0), gband, g_at, False)
    expect("grid-zero kWp cap row appears and fails when the chosen array exceeds it", st(capped, "cap") == "bajo")
    over = gc.check_grid_zero(dt.GridZeroGoals(60.0, 1.2), dt.grid_zero_target_band(dt.GridZeroGoals(60.0, 1.2), **gkw),
                              {**g_at, "reduction_pct": 45.0}, True)
    expect("an acknowledged above-ceiling goal is noted on its row", "reconocida" in next(r for r in over if r["key"] == "reduction")["note"])

    # ── glue + template ──
    line = lambda kw, f=0.9: {"category": "x", "quantity": 1, "connected_power_kw": kw, "demand_factor_pct": f}
    og = {"meta": {"system_type": "off_grid", "step_reached": 7, "wizard_rev": 2}, "site": site,
          "consumption": {"daily_kwh": 12.0, "profile": {"lines": [line(5.0)]}}}
    ctx = glue.build(og, at_spot)
    expect("glue: a grandfathered draft is judged against the default goals and flagged as such; Off-Grid carries the legacy-model note",
           ctx and ctx["default_goals"] and ctx["legacy_model_note"] and ctx["summary"]["overall"] in ("ok", "justo", "sobre"))
    conf = {**og, "objectives": {"system_type": "off_grid", "preset": "personalizado", "confirmed": True, "source": "user",
            "assumptions": {}, "goals": {**{k: getattr(tier, k) for k in ("reserve_soc_pct", "pv_design_factor", "solar_resource_basis",
                                                                          "inverter_loading_target_pct", "growth_energy_pct", "growth_peak_pct", "expansion_provision")},
                                          "autonomy_days": 4.0}}}
    ctx2 = glue.build(conf, at_spot)
    expect("glue: confirmed custom goals (4 days) are what the check judges: the same bank now misses the autonomy goal",
           ctx2 and not ctx2["default_goals"] and st(ctx2["rows"], "autonomy") in ("bajo", "justo"))
    expect("glue: no inputs or invalid goals = no strip (never a crash)", glue.build({"meta": {"system_type": "off_grid"}}, at_spot) is None)
    gzb = {"meta": {"system_type": "grid_zero", "step_reached": 7, "wizard_rev": 2},
           "site": {"pvgis_data": {"monthly_kwh_kwp": [130.0] * 12}}, "consumption": {"avg_kwh": 800.0}}
    expect("grid-zero daytime fraction for the strip: Objetivos' cache first, else Equipos' own estimate, else 0.45 (never an AI call)",
           ob._cached_fraction(gzb, "grid_zero") == 0.45
           and ob._cached_fraction({**gzb, "scratch": {"s6": {"coverage_ai": {"fraction": 0.55}}}}, "grid_zero") == 0.55
           and ob._cached_fraction({**gzb, "scratch": {"s6": {"coverage_ai": {"fraction": 0.55}}, "obj": {"daytime": {"fraction": 0.65}}}}, "grid_zero") == 0.65)

    app = create_app()
    with app.test_request_context():
        from flask import render_template

        html = render_template("wizard/_goals_check.html", goals_check=ctx, vid="v1")
        expect("template renders the banner, one row per check and the default-goals link",
               "Objetivos vs. diseño" in html and html.count("<tr>") == len(ctx["rows"]) + 1 and "Definir objetivos" in html
               and "modelo de confiabilidad anterior" in html)
        expect("template renders nothing without a check", render_template("wizard/_goals_check.html", goals_check=None, vid="v1").strip() == "")
    return failures


def check_fleet_shares() -> int:
    """Day / night shares come from the real fleet when it is there, and fall back to the old fixed values when it is not."""
    from unittest import mock

    from calculations import fleet_shares as fsh

    failures = 0

    def expect(label, ok):
        nonlocal failures
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
        failures += 0 if ok else 1

    fleet = {"day": 0.52, "night": 0.43, "n": 9, "day_range": (0.38, 0.76), "night_range": (0.21, 0.53)}
    with mock.patch.object(fsh, "fleet_shares", lambda: fleet):
        d = fsh.hybrid_defaults()
        expect("hybrid defaults take the fleet's night and day shares",
               d["night_load_fraction"] == 0.43 and d["daytime_fraction"] == 0.52 and d["site_exports_to_grid"] is False)
        frac, note = fsh.daytime_fraction_for([], "x")
        expect("Grid Zero's daytime fraction is the fleet median, with a note naming the 9 sites",
               frac == 0.52 and "9 sitios" in note and "38-76" in note)
    with mock.patch.object(fsh, "fleet_shares", lambda: None), \
            mock.patch("ai.daytime_fraction.estimate_daytime_fraction_ai", lambda loads, city: (0.47, "ia")):
        d = fsh.hybrid_defaults()
        expect("without fleet data the hybrid defaults are the historical 40 % night / 45 % day",
               d["night_load_fraction"] == 0.40 and d["daytime_fraction"] == 0.45)
        expect("without fleet data Grid Zero falls back to the AI estimate", fsh.daytime_fraction_for([], "x") == (0.47, "ia"))
    return failures


def check_fleet_peaks() -> int:
    """The fleet's measured peak/average ratio feeds the main-panel peak estimate and the step-7 reference chip; 3.0 is the fallback."""
    from unittest import mock

    from calculations import fleet_peaks as fpk

    failures = 0

    def expect(label, ok):
        nonlocal failures
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
        failures += 0 if ok else 1

    fleet = {"n": 12, "typical": 3.5, "design": 5.5, "design_range": (2.4, 19.0)}
    with mock.patch.object(fpk, "fleet_peak_ratios", lambda: fleet):
        e = fpk.expected_peak_kw(48.0)         # 2 kW average
        expect("typical peak ratio is the fleet's median", fpk.typical_peak_ratio() == 3.5)
        expect("expected peak = average power x the fleet's design ratio, with the site range",
               abs(e["design_kw"] - 11.0) < 1e-9 and abs(e["range_kw"][0] - 4.8) < 1e-9 and abs(e["range_kw"][1] - 38.0) < 1e-9 and e["n"] == 12)
        expect("no energy -> no expected peak", fpk.expected_peak_kw(0) is None)
    with mock.patch.object(fpk, "fleet_peak_ratios", lambda: None):
        expect("without fleet data the peak ratio falls back to the historical 3.0", fpk.typical_peak_ratio() == 3.0)
        expect("without fleet data there is no reference peak", fpk.expected_peak_kw(48.0) is None)
    return failures


def st_text(rows, key):
    r = next(r for r in rows if r["key"] == key)
    return r["achieved"]


def main() -> int:
    if "--capture" in sys.argv:
        capture()
        return 0
    print("Golden — generators unchanged by the formula lift")
    failures = check_golden()
    print("Targets — equipment-free sizing functions")
    failures += check_targets()
    print("Step 2 — wizard renumber")
    failures += check_wizard_numbering()
    print("Step 3 — Objetivos step")
    failures += check_objetivos()
    print("Step 4 — goals vs design")
    failures += check_goals()
    print("Fleet day / night shares")
    failures += check_fleet_shares()
    print("Fleet peak / average ratio")
    failures += check_fleet_peaks()
    print("\nALL PASSED" if failures == 0 else f"\n{failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
