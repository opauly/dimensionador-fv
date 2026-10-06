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
    the function under test (the 0.95 / 0.96 efficiencies, 0.88 array PR and the 0.40 fleet night-load fraction are the
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
    expect("off-grid battery nominal = 27 / (0.65 x 0.95 x 0.96)", _approx(t["battery_nominal_kwh"], 27.0 / (0.65 * 0.95 * 0.96)))
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
    eff = 0.95 * 0.96
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
    expect("grid-zero pre-fill = 90% of ceiling floored to 5 points (45 -> 40.5 -> 40)",
           dt.grid_zero_default_goals(0.45).reduction_target_pct == 40.0)

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

    # ── Validation ──
    expect("calibrated presets validate clean (all six)",
           all(not dt.validate_goals(st, t) for st in ("off_grid", "hybrid") for t in dt.goal_presets(st)))
    expect("an out-of-range autonomy is rejected", any("autonomy_days" in e for e in dt.validate_goals("off_grid", replace_goal(og_rec, autonomy_days=9.0))))
    expect("a missing value is rejected", any("pv_design_factor" in e for e in dt.validate_goals("off_grid", replace_goal(og_rec, pv_design_factor=None))))
    expect("an unknown expansion provision is rejected", any("expansion" in e for e in dt.validate_goals("hybrid", replace_goal(hy_rec, expansion_provision="three"))))
    return failures


def replace_goal(goals, **changes):
    from dataclasses import replace

    return replace(goals, **changes)


# ── Step 2: the wizard renumber (Equipos/Costos/Revisión 6/7/8 -> 7/8/9) ─────────────────────────────────

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

    def mk(meta: dict) -> str:
        vid = f"d{len(store)}"
        store[vid] = {"data": {"meta": {"system_type": "off_grid", **meta}, "client": {"name": "x"}}}
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
        newd = mk({"step_reached": 6, "wizard_rev": 2})
        expect("marked draft at Objetivos (6) may open 7 but not 8", get(f"{base}/{newd}/paso/7").status_code == 200
               and get(f"{base}/{newd}/paso/8").status_code == 303)
        expect("abrir resumes on the effective step (marked 6 -> 6)", target(get(f"{base}/{newd}/abrir")) == "6")

        # ── placeholder Objetivos: advances, converts, never lowers ──
        d = mk({"step_reached": 6, "wizard_rev": 2})
        resp = client.post(f"{base}/{d}/paso/6")
        meta = store[d]["data"]["meta"]
        expect("Objetivos placeholder POST advances to Equipos (7) and records it",
               resp.status_code == 303 and target(resp) == "7" and meta["step_reached"] == 7)
        d = mk({"step_reached": 5})
        client.post(f"{base}/{d}/paso/6")
        meta = store[d]["data"]["meta"]
        expect("an old draft at 5 is converted on first save (step 7, wizard_rev 2)", meta["step_reached"] == 7 and meta["wizard_rev"] == 2)
        d = mk({"step_reached": 7})
        client.post(f"{base}/{d}/paso/6")
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
        expect("no action route is left at an old number (6, or 7/8 for the old Costos/Revisión paths)",
               not ({f"{base}/<vid>/paso/6/equipo", f"{base}/<vid>/paso/7/tabla", f"{base}/<vid>/paso/8/bloquear",
                     f"{base}/<vid>/paso/8/pdf"} & paths) and 6 not in numbers)
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
    print("\nALL PASSED" if failures == 0 else f"\n{failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
