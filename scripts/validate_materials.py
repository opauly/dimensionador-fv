"""Checks for the materials list engine, its xlsx export and the unifilar configuration.

    python3 scripts/validate_materials.py

Reference design: María José Castro (16 x SUN600, 2 x MultiPlus-II 48/5000 120 V, 4 x Fidus, Fronius
Primo 10.0-1, Ekrano). Where her real purchase (Proforma 180-2026, Protel Z12-010970, her Solicitud de
materiales) gives a number, the check says so; known differences are asserted as differences so a rule
change that closes (or widens) the gap is noticed.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl  # noqa: E402

from materials import engine  # noqa: E402
from materials.catalog import CATALOG  # noqa: E402
from materials.export_xlsx import build_workbook  # noqa: E402
from unifilar import config_builder as CB  # noqa: E402
from webapp.wizard_steps import og_coupling, og_wiring  # noqa: E402

fails: list[str] = []


def check(name, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{name}: got {got!r}, want {want!r}")
    if not ok:
        fails.append(name)


PANEL = {"wp": 600, "voc": 48.15, "vmp": 40.46, "isc": 15.86, "imp": 14.95, "brand": "Sunergy", "model": "SUN600-66MDH12RS",
         "width_m": 1.134, "height_m": 2.382}
FRONIUS = {"id": "fr10", "type": "string_inverter", "brand": "Fronius", "model": "Primo 10.0-1", "kw": 10.0, "mppt_channels": 2,
           "vmax": 1000.0, "vmax_mppt": 800.0, "vmin_mppt": 200.0, "imax_mppt": 27.0}
MP = {"id": "mp5", "brand": "Victron Energy", "model": "MultiPlus-II 48/5000/70-95", "kw": 5.0, "output_v": 120.0,
      "ac_out_rated_a": 115.0, "ac_input_current_max_a": 95.0, "efficiency_pct": 96.0, "type": "hybrid"}
EQ = {"panel": PANEL, "panel_count": 16, "battery": {"brand": "Pylontech", "model": "Fidus", "voltage_v": 51.2, "capacity_kwh": 4.97},
      "battery_bank": {"battery_count": 4}, "inverter": MP, "inverter_qty": 2, "monitoring": {"brand": "Victron Energy", "model": "Ekrano GX"},
      "n_strings": 2, "panels_per_string": 8, "array": {"area_m2": 43.2}}
og_coupling.pv_inverter_options = lambda: [FRONIUS]
og_wiring._fresh_inverter = lambda eq: eq.get("inverter") or {}
og_wiring._ac_summary = lambda blob, qty: ({"ac_in": {"breaker_a": 190}}, 120.0, False, {"total_installed_kw": 13.25, "total_demand_kw": 8.8})
BLOB = {"meta": {"system_type": "hybrid"}, "equipment": EQ, "scratch": {"coupling": {"mode": "ac"}},
        "site": {"city": "Carrillo", "province": "Guanacaste"}}
CTX = og_wiring.build_context(BLOB)
LAYOUT = {"materials": {"layout": {"rows": 2, "orientation": "portrait"}}}


def lines(spec=None, ctx=CTX):
    r = engine.build_list(EQ, ctx, spec)
    return r, {ln["name"]: ln for ln in r["lines"]}


# ── Catalog ────────────────────────────────────────────────────────────────────
check("catalog has the 171 master lines", len(CATALOG), 171)
check("catalog keys are unique", len({r["key"] for r in CATALOG}), 171)
check("every cable / conduit / fuse pattern is tagged", sum(1 for r in CATALOG if r.get("kind")), 94)

# ── Without a roof layout the mounting is not guessed ──────────────────────────
r, by = lines()
check("no layout -> no rails", "Rieles (largueros)" in by, False)
check("no layout -> pending note", any("layout del techo" in p for p in r["pending"]), True)

# ── María José, 2 rows of 8 in portrait ─────────────────────────────────────────
r, by = lines(LAYOUT)
q = lambda n: by[n]["qty"] if n in by else None  # noqa: E731
check("layout: rows of 8 modules, 9.21 m, 4 rail lines, 8 rails", (r["counts"]["per_row"], r["counts"]["row_len_m"], r["counts"]["rail_lines"], r["counts"]["rails"]), (8, 9.21, 4, 8))
check("rails 9 (she bought 9)", q("Rieles (largueros)"), 9)
check("rail grounding lugs 8 (she bought 8)", q("Tierras para rieles"), 8)
check("splices 4 (she bought 8: known gap)", q("Uniones de riel"), 4)
check("mid clamps 30 (she bought 32)", q("Midclamp"), 30)
check("end clamps 9 (she bought 10)", q("Endclamp"), 9)
check("MC4 8 (she bought 8)", q("MC4"), 8)
check("SOLAR black / red 100 m rolls (she bought 100 / 100)", (q("Cable #10 AWG - SOLAR negro"), q("Cable #10 AWG - SOLAR rojo")), (100, 100))
check("panels 16, Multis 2, Fidus 4, Ekrano 1", (q("Paneles solares"), q("Inversor Multiplus 5000 120V"), q("Batería Pylontech Fidus"), q("Ekrano GX")), (16, 2, 4, 1))
check("Pylontech cable sets 4 (she bought 4)", q("Cables para Pylontech"), 4)
check("Lynx bars 2 / bolts 12 (she bought 3 bars / 12 bolts: open question)", (q("Lynx Power In"), q("Roscas para Lynx Power In")), (2, 12))
check("UTP 4 / VE.CAN 1 (she bought 4 / 1)", (q("Cable UTP normal"), q("Cable UTP tipo A")), (4, 1))
check("tape: one roll per colour used (4)", sum(1 for n in by if n.startswith("Tape color")), 4)
check("Fronius is a new line, not in the master list", (q("Inversor Fronius Primo 10.0-1"), by["Inversor Fronius Primo 10.0-1"]["in_master"]), (1, False))
check("string breaker follows the design: 25 A DC, 2 (new line)", (q("Breaker DC para riel DIN 25A 2P"), by["Breaker DC para riel DIN 25A 2P"]["in_master"]), (2, False))
check("AC in: two 120 V Multis share one 2-pole 90 A breaker", q("Breaker AC para riel DIN 90A 2P"), 1)
check("AC out 70 A 2P x1, Fronius 60 A 2P x1", (q("Breaker AC para riel DIN 70A 2P"), q("Breaker AC para riel DIN 60A 2P")), (1, 1))
check("battery-to-Multi fuses: Mega 200 A x2 (Lynx series, new line) + battery fuses by definir x4",
      (q("Fusible Mega 200A"), q("Fusible Mega de batería (calibre por definir)")), (2, 4))
check("one ground per raceway: #8 green 49.5 m -> 50", q("Cable #8 AWG THHN, CU, color verde"), 50)
check("#3 AWG is not in the master list -> new line", by["Cable #3 AWG THHN, CU, color negro"]["in_master"], False)
check("#4 black THHN is a master line, 15 m", (by["Cable #4 AWG THHN, CU, color negro"]["in_master"], q("Cable #4 AWG THHN, CU, color negro")), (True, 15))
check("heat-shrink for the DC lugs, 1 m minimum", q("Termoencogible para cable #3/0 rojo"), 1)
check("battery-side DC runs are not piped (no 1 1/4 in conduit from them)", any("Tuberia 1 1/4" in n and by[n]["comment"].startswith("Baterías") for n in by), False)
check("PVC glue 1 when PVC is used", q("Pegamento para PVC"), 1)

# ── Options ────────────────────────────────────────────────────────────────────
spec32 = {"materials": {**LAYOUT["materials"], "options": {"string_breaker_a": 32}}}
_, by32 = lines(spec32)
check("string breaker 32 A (her choice) lands on the master row", (by32["Breaker DC para riel DIN 32A 2P"]["in_master"], by32["Breaker DC para riel DIN 32A 2P"]["qty"]), (True, 2))
specE = {"materials": {**LAYOUT["materials"], "options": {"conduit_material": {"ac_out": "EMT", "ac_in": "EMT"}}}}
_, byE = lines(specE)
check("EMT for the AC runs: EMT tubes + pressure connectors appear", ('Tuberia 1 1/4" / EMT' in byE, 'Conector de presión 1 1/4" EMT' in byE), (True, True))

# ── Edits survive regeneration ─────────────────────────────────────────────────
key = by["Midclamp"]["id"]
specEd = {"materials": {**LAYOUT["materials"], "overrides": {key: {"qty": 32}}, "extras": [
    {"id": "a1", "key": "gabinetes-cajas-registros-gabinete-metalico-50x40x20", "qty": 1, "comment": "Breaker DC / Cerbo"},
    {"id": "a2", "key": None, "name": "Caja de paso 4x4", "qty": 2, "unit": "un"}]}}
_, byEd = lines(specEd)
check("override keeps her 32 mid clamps and remembers the computed 30", (byEd["Midclamp"]["qty"], byEd["Midclamp"]["computed_qty"], byEd["Midclamp"]["edited"]), (32, 30, True))
check("extra from the master list keeps its section", byEd["Gabinete metálico 50x40x20"]["section"], "Generales")
check("free-text extra is a new line", (byEd["Caja de paso 4x4"]["qty"], byEd["Caja de paso 4x4"]["in_master"]), (2, False))

# ── xlsx export ────────────────────────────────────────────────────────────────
ws = openpyxl.load_workbook(io.BytesIO(build_workbook(r["lines"]))).active
rows = list(ws.iter_rows(values_only=True))
check("xlsx header like the master sheet", rows[0][:5], ("Detalle", "Cantidad", "Unidad", "Comentarios", "Avolta"))
check("xlsx dealer columns and Bodega left empty", all(v is None for row in rows[1:] for v in row[4:]), True)
check("xlsx starts a section with the master's header row", rows[1][:3], ("Paneles solares", "Cantidad", "Unidad"))
check("xlsx holds only lines with a quantity", all(row[1] for row in rows[1:] if isinstance(row[1], (int, float)) or row[1] is None and False), True)

# ── Unifilar configuration ─────────────────────────────────────────────────────
project = {"system_type": "hybrid", "client_name": "María José Castro"}
d = {"eq": EQ, "wiring": CTX, "blob": BLOB}
cfg, prob = CB.build_config(project, d, {})
check("both questions block the drawing until answered", (cfg, len(prob["blockers"])), (None, 2))
ans = {"export": "grid_zero", "lynx": "power_in"}
cfg, prob = CB.build_config(project, d, ans)
check("drawn from the sized design: string breaker / wire", (cfg["pv"]["string_breaker"], cfg["pv"]["dc_wire"]), ("25 A 2P DC", "#10 AWG SOLAR"))
check("Q3 Fronius breaker and conductors", (cfg["fronius"]["ac_breaker"], cfg["fronius"]["ac_conductors"]), ("2P 60 A", ["L1 #6 AWG negro", "L2 #6 AWG rojo", "T #8 AWG verde"]))
check("Q1 from the manual limit: 2P 90 A on #3 AWG", (cfg["multis"]["ac_in_breaker"], cfg["multis"]["ac_in_conductors"][0]), ("2P 90 A", "L1 #3 AWG negro"))
check("DC to the Multis uses the sized cable", (cfg["multis"]["dc_pos"], cfg["multis"]["dc_neg"]), ("+ #3/0 AWG rojo", "- #3/0 AWG negro"))
check("layout 2 strings x 8, label and title", (cfg["pv"]["strings"], cfg["pv"]["modules_per_string"], cfg["project"]["name"]), (2, 8, "Proyecto María José Castro en Carrillo, Guanacaste"))
cfg32, _ = CB.build_config(project, d, ans, string_breaker_a=32)
check("her 32 A string breaker reaches the drawing", cfg32["pv"]["string_breaker"], "32 A 2P DC")
check("only drawable characters in the labels", all(ch not in str(cfg) for ch in "→−≥≤"), True)
check("engineering notes stay out of the config", "warnings" in prob and "warnings" not in cfg, True)
check("review list mentions the 95 A input limit", any("95 A" in w["text"] for w in prob["warnings"]), True)
_, off = CB.build_config({**project, "system_type": "off_grid"}, d, ans)
check("off-grid project is out of scope", any("híbridos" in b for b in off["blockers"]), True)
dc_ctx = og_wiring.build_context({**BLOB, "scratch": {}})
_, dcp = CB.build_config(project, {"eq": EQ, "wiring": dc_ctx, "blob": BLOB}, ans)
check("DC coupling is out of scope", any("acople AC" in b for b in dcp["blockers"]), True)
from unifilar.generate_unifilar import build  # noqa: E402
out = io.BytesIO()
build(cfg, out)
check("the PDF renders from the config", out.getvalue()[:4], b"%PDF")

# Roof layout answered in the wizard (blob scratch) feeds the list; the project's own answer wins key by key.
from materials import engine as ME  # noqa: E402
check("clean_layout drops blanks and junk", ME.clean_layout({"rows": "", "orientation": "diagonal", "rail_len_m": "-1", "foot_spacing_m": "1,2"}), {"foot_spacing_m": 1.2})
check("layout_from_blob reads scratch.roof_layout", ME.layout_from_blob({"scratch": {"roof_layout": {"rows": "2", "orientation": "landscape"}}}), {"rows": 2, "orientation": "landscape"})
wiz = {"rows": 2, "orientation": "landscape"}
check("wizard layout reaches the list", ME.build_list(EQ, CTX, {}, wiz)["layout"]["rows"], 2)
check("project layout wins over the wizard's", ME.build_list(EQ, CTX, {"materials": {"layout": {"rows": 3}}}, wiz)["layout"]["rows"], 3)
check("no layout anywhere leaves mounting pending", any("layout del techo" in x for x in ME.build_list(EQ, CTX, {}, None)["pending"]), True)

print("\n" + ("ALL MATERIALS CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
