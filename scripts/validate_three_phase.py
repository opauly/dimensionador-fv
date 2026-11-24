"""Checks for the three-phase reverse sizing (calculations/three_phase.py).

    python3 scripts/validate_three_phase.py

Reference: Canadian Solar CS7N-620MS (620 Wp) on a 120/208 V three-phase service (the Mar Profundo plant), 200 kWp target.
Expected numbers were worked out by hand (see the comments next to each check).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calculations import coupling, industrial_profiles as ip, mppt, wiring as W  # noqa: E402
from calculations import tablero_industrial as TI  # noqa: E402
from calculations import three_phase as T  # noqa: E402

fails: list[str] = []


def check(name, got, want, tol=1e-3):
    ok = abs(got - want) <= tol if isinstance(want, float) else got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


PANEL = {"brand": "Canadian Solar", "model": "CS7N-620MS", "wp": 620, "voc": 50.2, "vmp": 42.4, "isc": 15.62, "imp": 14.62,
         "temp_coeff_pmax": -0.34, "width_m": 1.134, "height_m": 2.384}

# ── Pieces ─────────────────────────────────────────────────────────────────────
check("rated current 60 kW @ 208 V", round(T.ac_current_a(60, 208), 1), 166.5)      # 60000 / (1.732 x 208)
lim = T.string_limits(PANEL, v_ll=208)
check("Voc cold (10 C)", lim["voc_cold"], 52.23, 0.01)                              # 50.2 x (1 + 0.0027 x 15)
check("Vmp hot (70 C)", lim["vmp_hot"], 35.91, 0.01)                                # 42.4 x (1 - 0.0034 x 45)
check("min series (DC bus must clear 208 V peak + 10 %)", lim["ns_min"], 10)         # 323.6 V / 35.91 V -> 10
check("max series (1000 V)", lim["ns_max"], 19)                                      # 1000 / 52.23 -> 19

# ── Inverter selection (Fronius Symo commercial sizes) ─────────────────────────
check("208 V class tops out at 15 kW (the 17.5-24 kW Symo are 480 V only)", max(u["kw"] for u in T.ladder_for(208)), 15.0)
check("480 V class goes up to 24 kW", max(u["kw"] for u in T.ladder_for(480)), 24.0)
best = T.inverter_options(200)[0]
check("200 kWp at 208 V -> fewest units within 15 % of 166.7 kW AC: 12 x 15", (best["qty"], best["unit_kw"]), (12, 15.0))
capped = T.inverter_options(200, max_unit_kw=12)[0]
check("200 kWp, units capped at 12 kW -> 14 x 12", (capped["qty"], capped["unit_kw"]), (14, 12.0))
check("nothing above the cap is offered", max(o["unit_kw"] for o in T.inverter_options(200, max_unit_kw=12)), 12.0)
check("a custom ladder of plain kW sizes still works", T.inverter_options(200, ladder=(60.0,))[0]["qty"], 3)

# ── Full recommendation ────────────────────────────────────────────────────────
rec = T.recommend(PANEL, 200, v_ll=208)
check("recommendation ok", rec["ok"], True)
check("12 inverters of 15 kW", (rec["inverter"]["qty"], rec["inverter"]["kw"]), (12, 15.0))
check("commercial equivalent named", rec["inverter"]["reference_model"], "Fronius Symo 15.0-3 208")
check("14 modules in series", rec["array"]["panels_per_string"], 14)                  # fewest extra modules: 336 vs 323 needed
check("2 strings per inverter", rec["array"]["strings_per_inverter"], 2)               # the 15 kW unit has one 50 A input: 2 x 14.62 A
check("336 modules", rec["array"]["total_panels"], 336)
check("array kWp", rec["array"]["system_kw"], 208.32)
check("DC/AC ratio", rec["array"]["dc_ac_ratio"], 1.16, 0.01)                         # 208.32 / 180
check("1 MPPT input per inverter", rec["inverter"]["mppt_channels_required"], 1)
check("Imax per MPPT >= 2 x Imp", rec["inverter"]["imax_mppt_required_a"], 29.3, 0.01)  # 29.24 rounded up
check("DC max voltage class", rec["inverter"]["vmax_dc_required"], 1000.0)
check("AC current per inverter (datasheet 41.6 A)", rec["inverter"]["ac_current_a"], 41.6, 0.05)
check("breaker per inverter = 125 % -> next standard size (datasheet 60 A)", rec["ac"]["ocpd_each_a"], 60)
check("3 CTs for the meter", rec["ac"]["ct_count"], 3)
check("208 V with 12 units tells why there are so many", any("más grande de la gama" in w for w in rec["warnings"]), True)
rec480 = T.recommend(PANEL, 200, v_ll=480)
check("480 V -> 8 x 22.7 kW (7 x 24 kW would push DC/AC over 1.2)", (rec480["inverter"]["qty"], rec480["inverter"]["kw"]), (8, 22.7))
check("480 V: 3 strings fit the two inputs (33 A + 25 A)", (rec480["array"]["strings_per_inverter"], rec480["inverter"]["mppt_channels_required"]), (3, 2))
check("24 kW at 480 V draws 28.9 A (datasheet)", round(T.ac_current_a(24, 480), 1), 28.9)
check("10 kW (9,995 VA) at 208 V draws 27.7 A (datasheet)", round(T.ac_current_a(9.995, 208), 1), 27.7)
cap10 = T.strings_capacity(T.ladder_for(208)[0], PANEL)
check("Symo 10.0 at 208 V: one string per input (25 A and 16.5 A inputs)", cap10, 2)
check("Symo 15.0 at 208 V: 3 strings on its 50 A input", T.strings_capacity(T.ladder_for(208)[2], PANEL), 3)

# ── The stand-in inverter works in the existing MPPT checks ───────────────────
inv = T.virtual_inverter(rec)
check("stand-in is three-phase 208 V", (inv["phase"], inv["output_v"]), ("three", 208.0))
check("stand-in carries the real unit's DC window", (inv["vmax"], inv["vmin_mppt"], inv["vmax_mppt"], inv["mppt_channels"], inv["imax_mppt"]),
      (1000.0, 325.0, 850.0, 1, 50.0))
manual = mppt.check_design(PANEL, inv, rec["array"]["panels_per_string"], rec["array"]["strings_per_inverter"])
check("check_design accepts the recommended layout", manual["within_limits"], True)
check("check_design rejects a 4th string (over the 50 A input)", mppt.check_design(PANEL, inv, 14, 4)["within_limits"], False)
scen = mppt.validate_string_design(PANEL, inv, target_system_kw=rec["array"]["system_kw"] / rec["inverter"]["qty"])
check("existing scenarios still produce a design", bool(scen), True)

# ── Edge cases ─────────────────────────────────────────────────────────────────
low = T.recommend(PANEL, 50, v_ll=208, vdc_max=300)      # an input-voltage class too low for a 208 V service: no string length fits
check("no valid string length is refused, with a reason", (low["ok"], bool(low["reasons"])), (False, True))
check("zero target is refused", T.recommend(PANEL, 0)["ok"], False)
small = T.recommend(PANEL, 15, v_ll=208)
check("15 kWp -> 1 inverter", small["inverter"]["qty"], 1)
big_i = T.recommend(PANEL, 600, v_ll=208)
check("600 kWp warns about total AC current", any("corriente total" in w for w in big_i["warnings"]), True)

# ── Three-phase service plumbing ───────────────────────────────────────────────
check("AC current of a 60 kW three-phase inverter at 208 V", round(coupling.pv_inverter_ac_current_a({"kw": 60, "phase": "three", "output_v": 208}), 1), 166.5)
check("single-phase inverter keeps kW / 240 V", round(coupling.pv_inverter_ac_current_a({"kw": 10, "phase": "single"}), 2), 41.67)
one, three = W.vdrop_ac("4/0", 100, 30), W.vdrop_ac("4/0", 100, 30, phases=3)
check("three-phase drop = sqrt3 / 2 of the two-wire drop", round(three / one, 4), round(3 ** 0.5 / 2, 4))
br = W.size_branch("t", kind="ac", qty=3, current_a=166.5, factor=1.25, v_ref=208, length_m=20, hot=3, neutral=1, phases=3)
check("166.5 A three-phase feeder: gauge / breaker / phases recorded", (br["ugc"], br["ocpd_a"], br["hot"], br["phases"]), ("4/0", 225, 3, 3))
huge = W.size_branch("t", kind="ac", qty=1, current_a=499.5, factor=1.25, v_ref=208, length_m=20, hot=3, neutral=1, phases=3)
check("a feeder beyond the tables is flagged, not crashed", (huge["ok"], huge["ugc"]), (False, None))
check("no service saved -> single-phase", ip.service_of({"utility": {}})["phases"], 1)
check("three-phase service with its voltage", ip.service_of({"utility": {"service_phases": "3", "service_v_ll": 220}}), {"phases": 3, "v_ll": 220.0, "profile_site_id": None})
check("single-phase has no plant profile", ip.profile_id_for({"utility": {}}), None)
from webapp.wizard_steps import gz_s4_utility as S4  # noqa: E402
check("step 4 saves a three-phase service", S4._service_fields({"service_phases": "3", "service_v_ll": "208", "profile_site_id": "x"}),
      {"service_phases": "3", "service_v_ll": 208.0, "profile_site_id": "x"})
check("step 4 default stays single-phase", S4._service_fields({})["service_phases"], "1")

# ── Industrial plan reader (pure parts) ────────────────────────────────────────
check("rack of compressors", TI.categorize("RACK DE COMPRESORES"), "compresores")
check("maintenance outlet at the rack is an outlet, not a compressor", TI.categorize("TOMA DE MANTENIMIENTO (RACK EXTERIOR)"), "tomas")
check("telecom rack is backup", TI.categorize("RACK DE TELECOMUNICACIONES"), "respaldo")
check("defrost heater", TI.categorize("RESISTENCIA DESHIELO (TUNEL)"), "deshielo")
check("door heaters", TI.categorize("RESISTENCIAS DE PUERTA (CAMARA CEVICHE)"), "puertas")
check("condensing unit on an HVAC board is A/C", TI.categorize("UNIDAD CONDENSADORA UC-1 (OFICINAS)", "TABLERO CARGAS HVAC"), "hvac")
check("evaporators on a refrigeration board", TI.categorize("EVAPORADORAS Y CONTROLADORES (CAMARA)", "TABLERO DE EQUIPOS DE REFRIGERACION"), "refrigeracion")
check("sealer is process", TI.categorize("SELLADORA AL VACIO (PROCESOS INTERMEDIOS)"), "proceso")
boards = [
    {"board": "TP", "name": "TABLERO PRINCIPAL", "total_w": 1000, "reserved_w": 100, "circuits": [
        {"description": "TABLERO - TR1", "load_w": 300}, {"description": "RACK DE COMPRESORES", "load_w": 600}]},
    {"board": "TR1", "name": "TABLERO DE EQUIPOS DE REFRIGERACION", "total_w": 400, "reserved_w": 0, "circuits": [
        {"description": "EVAPORADORAS (CAMARA)", "load_w": 400}, {"description": "PREVISTA", "load_w": 0}]},
]
res = TI.build_loads(boards)
check("a line feeding a board that was read is not counted twice", sorted(r["Tablero"] for r in res["loads"]), ["TP", "TR1"])
check("rows keep the Step 5 shape and carry category + board", sorted(res["loads"][0].keys()), sorted(["Descripción", "W", "Und", "h/día", "días/mes", "Categoría", "Tablero"]))
check("circuits + reserved reconcile with the printed total -> no warning", [n for n in res["notes"] if "revisar" in n], [])
bad = TI.build_loads([{"board": "TX", "name": "X", "total_w": 1000, "circuits": [{"description": "EVAPORADORA", "load_w": 500}]}])
check("a board that does not add up is flagged", any("revisar" in n for n in bad["notes"]), True)

print()
print("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
