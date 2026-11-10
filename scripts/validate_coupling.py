"""Checks for the AC-coupled hybrid mode (calculations/coupling.py + the AC branches of
webapp/wizard_steps/og_wiring.py + the system rows of calculations/bom.py).

    python3 scripts/validate_coupling.py

Uses the María José Castro hybrid design as the reference: 16 x SUN600 on a Fronius Primo 10.0-1
(2 MPPT), two MultiPlus-II 48/5000 120 V, four Pylontech Fidus, Ekrano GX. Numbers that the
as-built diagram and quotes also show are noted next to each check.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calculations import bom as B  # noqa: E402
from calculations import coupling as C  # noqa: E402
from webapp.wizard_steps import og_coupling, og_wiring  # noqa: E402

fails: list[str] = []


def check(name, got, want, tol=1e-3):
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


PANEL = {"wp": 600, "voc": 48.15, "vmp": 40.46, "isc": 15.86, "imp": 14.95, "brand": "Sunergy", "model": "SUN600"}
FRONIUS = {"id": "fr10", "type": "string_inverter", "brand": "Fronius", "model": "Primo 10.0-1", "kw": 10.0, "mppt_channels": 2,
           "vmax": 1000.0, "vmax_mppt": 800.0, "vmin_mppt": 200.0, "imax_mppt": 27.0}
MP = {"id": "mp5", "brand": "Victron Energy", "model": "MultiPlus-II 48/5000/70-95", "kw": 5.0, "output_v": 120.0,
      "ac_out_rated_a": 115.0, "ac_input_current_max_a": 95.0, "efficiency_pct": 96.0, "type": "hybrid"}
BAT = {"brand": "Pylontech", "model": "Fidus", "voltage_v": 51.2}

# ── String checks ──────────────────────────────────────────────────────────────
check("default layout 16 panels on 2 MPPT", C.default_layout(16, 2), (2, 8))
check("default layout 15 panels on 2 MPPT rounds up", C.default_layout(15, 2), (2, 8))
chk = C.check_strings(PANEL, FRONIUS, 2, 8, hybrid_kw_total=10.0)
check("Voc string 8 x 48.15 (diagram: 385 V)", chk["voc_string"], 385.2, 0.1)
check("Vmp string 8 x 40.46 (diagram: 324 V)", chk["vmp_string"], 323.7, 0.1)
check("array kWp", chk["array_kw"], 9.6)
check("DC/AC ratio 9.6 / 10", chk["dc_ac_ratio"], 0.96)
check("María José layout is valid", chk["ok"], True)
bad = C.check_strings(PANEL, FRONIUS, 2, 17, hybrid_kw_total=10.0)
check("17 modules: Voc 819 V over the 800 V window", bad["ok"], False)
check("PV inverter bigger than the Multis is flagged", C.check_strings(PANEL, {**FRONIUS, "kw": 12.0}, 2, 8, hybrid_kw_total=10.0)["ok"], False)
check("suggest: smallest Fronius with kW >= 95 % of 9.6 kWp",
      C.suggest_pv_inverter([{**FRONIUS, "kw": 8.2, "id": "a"}, FRONIUS, {**FRONIUS, "kw": 6.0, "id": "b"}], 9.6)["id"], "fr10")
check("Fronius AC current Primo 10.0-1 @240 V: datasheet 41.6 A (not 10 kW / 240 V = 41.67)", round(C.pv_inverter_ac_current_a(FRONIUS), 2), 41.6)

# ── Wiring: AC-coupled branches ────────────────────────────────────────────────
EQ = {"panel": PANEL, "panel_count": 16, "battery": BAT, "battery_bank": {"battery_count": 4}, "inverter": MP,
      "inverter_qty": 2, "monitoring": {"brand": "Victron Energy", "model": "Ekrano GX"},
      "charge_controller": {"brand": "Victron", "model": "SmartSolar", "imax_out": 70}, "charge_controller_qty": 2,
      "panels_per_string": 4, "n_strings": 4}
og_coupling.pv_inverter_options = lambda: [FRONIUS]       # no database in the check
og_wiring._fresh_inverter = lambda eq: eq.get("inverter") or {}
og_wiring._ac_summary = lambda blob, qty: None            # AC out/in need loads; covered by validate_wiring
BLOB = {"meta": {"system_type": "hybrid"}, "equipment": EQ, "scratch": {"coupling": {"mode": "ac"}}}

ctx = og_wiring.build_context(BLOB)
by = {b["label"]: b for b in ctx["branches"]}
check("AC mode: no charge-controller branches", any("controlador" in k.lower() for k in by), False)
pv, ac = by["Paneles → inversor FV (strings)"], by["Inversor FV → sub-panel de cargas críticas"]
check("one PV run per string", pv["qty"], 2)
check("string current is one string's Isc", pv["current_a"], 15.86)
check("string breaker: 15.86 x 1.5625 = 24.8 A -> 32 A (no 25 A exists)", pv["ocpd_a"], 32)
check("PV cable floor: #10 although ampacity allows #12", pv["ugc"], "10")
check("PV run: 2 conductors + ground", [(r["role"], r["count"]) for r in pv["conductors"]], [("UGC", 2), ("EGC", 1)])
check("PV ground by the 32 A string breaker (T250.122 -> 10 AWG)", pv["egc"], "10")
check("Fronius AC: 41.7 A x 1.25 = 52 A -> 60 A 2-pole breaker (diagram: 2P 60 A)", ac["ocpd_a"], 60)
check("Fronius AC conductor: L1 + L2 + ground, no neutral", [(r["role"], r["count"]) for r in ac["conductors"]], [("UGC", 2), ("EGC", 1)])
check("Fronius AC gauge from 52 A design", ac["ugc"], "6")
check("DC mode still gives controller branches", any("controlador" in b["label"].lower()
      for b in og_wiring.build_context({**BLOB, "scratch": {}})["branches"]), True)
check("off-grid design can be AC-coupled too (no charge controllers)", og_wiring.build_context({**BLOB, "meta": {"system_type": "off_grid"}})["coupling"]["ac"], True)
check("a grid-zero draft never gets the coupling choice", og_wiring.build_context({**BLOB, "meta": {"system_type": "grid_zero"}})["can_couple"], False)
check("lengths keep a hidden value", og_wiring.lengths_from_form({"pv_cc_m": "20"}, {"cc_bat_m": 4.0})["cc_bat_m"], 4.0)

# ── BOM system rows ────────────────────────────────────────────────────────────
rows = {r["item"]: r for r in B.system_rows(EQ, ctx["coupling"], ctx)}
check("Lynx bars: 4 batteries + 2 inverters = 6 inputs -> 2 bars", rows["Victron Lynx Power In"]["qty"], 2)
check("Lynx bolts: 2 per input (user: 'bolts are two per input')", rows["Pernos / roscas para Lynx Power In"]["qty"], 12)
check("UTP: VE.Bus 1 + MP-GX 1 + Fronius-GX 1 + router 1 (quote: 4 x UTP 3 m)", rows["Cable UTP con RJ-45 (3 m)"]["qty"], 4)
check("VE.CAN cable x1 (quote: 1)", rows["Cable VE.CAN / CAN-bus de batería"]["qty"], 1)
dc_rows = {r["item"]: r for r in B.system_rows(EQ, {"ac": False}, {})}
check("DC-coupled adds the controllers as Lynx inputs: 8 inputs -> 2 bars", dc_rows["Victron Lynx Power In"]["qty"], 2)
check("DC-coupled UTP has no Fronius link", dc_rows["Cable UTP con RJ-45 (3 m)"]["qty"], 3)
eq_rows = {r["category"] for r in B.equipment_rows(EQ, ctx["coupling"])}
check("equipment rows: PV inverter in, controller out", ("Inversor FV (acople AC)" in eq_rows, "Controlador de carga" in eq_rows), (True, False))

print("\n" + ("ALL COUPLING CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
