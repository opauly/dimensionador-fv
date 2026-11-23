"""End-to-end check of the three-phase Grid Zero wizard steps (Distribuidora, Consumo, Equipos, cableado) on a hand-made draft.

    python3 scripts/validate_three_phase_wizard.py

Needs the live catalog (Supabase), the eGauge reference plant (migrations 070/071 + scripts/load_egauge.py) and the fleet cache
(.cache/fleet_sim.pkl). Renders the real templates with Flask's test context; no AI calls.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import render_template  # noqa: E402
from werkzeug.datastructures import MultiDict  # noqa: E402

from webapp import create_app  # noqa: E402
from webapp.wizard_steps import gz_s4_utility as s4  # noqa: E402
from webapp.wizard_steps import gz_s5_consumption as s5  # noqa: E402
from webapp.wizard_steps import gz_s6_equipment as s6  # noqa: E402
from webapp.wizard_steps import gz_wiring  # noqa: E402

fails: list[str] = []


def check(name, got, want=True):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}" + ("" if ok else f", want {want!r}"))
    if not ok:
        fails.append(name)


BASE = {"meta": {"system_type": "grid_zero"}, "client": {},
        "site": {"lat": 9.93, "lon": -84.08, "city": "San José", "pvgis_data": {"monthly_kwh_kwp": [130] * 12}},
        "consumption": {"avg_kwh": 27150, "avg_bill_crc": 6_000_000}, "utility": {}}
THREE = {**BASE, "utility": {"service_phases": "3", "service_v_ll": 208, "profile_site_id": "mar-profundo-planta-actual"}}
LOADS = [
    {"Descripción": "TP · RACK DE COMPRESORES", "W": 165526, "Und": 1, "h/día": 14.0, "días/mes": 30, "Categoría": "Compresores / rack", "Tablero": "TP"},
    {"Descripción": "TR1 · EVAPORADORAS (CAMARA)", "W": 1200, "Und": 1, "h/día": 20.0, "días/mes": 30, "Categoría": "Refrigeración (evaporadores)", "Tablero": "TR1"},
]

app = create_app()
with app.test_request_context("/"):
    # Step 4: the service question
    ctx4 = s4.build_context(THREE)
    check("step 4 shows the three-phase service and the reference plant", (ctx4["service"]["phases"], [r["site_id"] for r in ctx4["reference_sites"]]),
          (3, ["mar-profundo-planta-actual"]))
    html4 = render_template("wizard/gz_s4_utility.html", vid="x", n=4, **ctx4)
    check("step 4 renders the service block", "Servicio eléctrico" in html4 and "Trifásico" in html4)

    # Step 5: loads table from the plans
    blob5 = {**THREE, "scratch": {"s5": {"selected_source": "loads", "loads_data": LOADS, "loads_from_tablero": True,
                                         "plano_boards": [{"board": "TP", "name": "TABLERO PRINCIPAL", "circuits_w": 165526, "reserved_w": 0, "printed_total_w": 165526, "counted_w": 165526}],
                                         "plano_notes": []}}}
    c5 = s5.build_context(blob5)
    check("step 5 is industrial with a check against the measured plant", (c5["industrial"], bool(c5["industrial_check"]["ref_avg_kw"])), (True, True))
    h5 = render_template("wizard/gz_s5_consumption.html", vid="x", n=5, **c5)
    check("step 5 renders plans upload, summary and category columns", all(t in h5 for t in ("Leer planos", "Resumen de la lectura", 'name="row-0-cat"', "multiple")))
    form = MultiDict({"row-0-desc": "a", "row-0-w": "1000", "row-0-und": "1", "row-0-hd": "10", "row-0-dm": "30", "row-0-cat": "Proceso / producción", "row-0-brd": "TR0"})
    upd = s5.update_loads_table(blob5, form)
    check("editing the table keeps category and board", (upd["loads_data"][0].get("Categoría"), upd["loads_data"][0].get("Tablero")), ("Proceso / producción", "TR0"))
    months = [m["kwh"] for m in s5.apply_loads(blob5)["applied_months"]]
    check("12 months come from the nominal month shaped by the measured pattern", abs(sum(months) / 12 - s5.build_context(blob5)["loads_total_kwh"]) < 1.0)
    c1 = s5.build_context({**BASE, "scratch": {"s5": {"selected_source": "loads"}}})
    h1 = render_template("wizard/gz_s5_consumption.html", vid="x", n=5, **c1)
    check("single-phase Step 5 is unchanged", (c1["industrial"], "Extraer cargas del tablero" in h1, "multiple" in h1), (False, True, False))

    # Step 6: recommended inverter, MPPT scenarios, save, wiring
    ctx = s6.build_context(THREE)
    inv, reco = ctx["selected_inverter"], ctx["reco"]
    check("Equipos recommends a generic three-phase inverter first", (inv.get("generic"), inv.get("phase"), reco["ok"]), (True, "three", True))
    check("its quantity comes from the recommendation", ctx["inverter_qty"], reco["inverter"]["qty"])
    blob6 = {**THREE, "scratch": {"s6": s6.calc_mppt(THREE)}}
    scen = blob6["scratch"]["s6"]["scenarios"]
    check("MPPT scenarios come out valid for the stand-in", any(s["within_limits"] for s in scen))
    html6 = render_template("wizard/_s6_equipos.html", vid="x", n=7, **s6.build_context(blob6))
    check("Equipos renders the recommended block and the minimum requirements", "Recomendado" in html6 and "Requisitos" in html6)
    saved = s6.save_step(blob6)
    check("Equipos saves the design", bool(saved) and saved["inverter"].get("generic"))
    w = gz_wiring.build_context({**blob6, "equipment": saved})
    per_inv = next(b for b in w["branches"] if b["label"].startswith("Inversor → centro"))
    check("AC feeder per inverter is three-phase + neutral at 208 V", (per_inv["hot"], per_inv["neutral"], per_inv["v_ref"], per_inv["phases"]), (3, 1, 208.0, 3))
    cs = s6.build_context({**BASE})
    check("single-phase Equipos is unchanged (no stand-in, no recommendation)", (cs["selected_inverter"].get("generic"), cs["reco"]), (None, None))

print()
print("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
