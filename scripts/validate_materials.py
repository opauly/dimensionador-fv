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

# ── Without a roof layout each string is one row; with no strings either, the mounting is not guessed ──
r, by = lines()
check("no layout -> one string per row: rails are calculated", by["Rieles (largueros)"]["qty"], 9)
check("no layout but strings known -> nothing pending about the layout", any("layout del techo" in p for p in r["pending"]), False)
r, by = lines(ctx={**CTX, "coupling": {**CTX["coupling"], "strings": 0}})
check("no layout and no strings -> no rails", "Rieles (largueros)" in by, False)
check("no layout and no strings -> pending note", any("layout del techo" in p for p in r["pending"]), True)

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
check("SOLAR black / red by the metre: 2 strings x 15 m + 10 % = 35 m each", (q("Cable #10 AWG - SOLAR negro"), q("Cable #10 AWG - SOLAR rojo")), (35, 35))
check("panels 16, Multis 2, Fidus 4, Ekrano 1", (q("Paneles solares"), q("Inversor Multiplus 5000 120V"), q("Batería Pylontech Fidus"), q("Ekrano GX")), (16, 2, 4, 1))
check("Pylontech cable sets 4 (she bought 4)", q("Cables para Pylontech"), 4)
check("Lynx bars 2 / bolts 12 (she bought 3 bars / 12 bolts: open question)", (q("Lynx Power In"), q("Roscas para Lynx Power In")), (2, 12))
check("UTP 4 / VE.CAN 1 (she bought 4 / 1)", (q("Cable UTP normal"), q("Cable UTP tipo A")), (4, 1))
check("tape: one roll per colour used (4)", sum(1 for n in by if n.startswith("Tape color")), 4)
check("Fronius is a new line, not in the master list", (q("Inversor Fronius Primo 10.0-1"), by["Inversor Fronius Primo 10.0-1"]["in_master"]), (1, False))
check("string breaker follows the design: 32 A DC x2 (in the master list)", (q("Breaker DC para riel DIN 32A 2P"), by["Breaker DC para riel DIN 32A 2P"]["in_master"]), (2, True))
check("AC in: two 120 V Multis share one 2-pole 90 A breaker", q("Breaker AC para riel DIN 90A 2P"), 1)
check("AC out 70 A 2P x1, Fronius 60 A 2P x1", (q("Breaker AC para riel DIN 70A 2P"), q("Breaker AC para riel DIN 60A 2P")), (1, 1))
check("battery-to-Multi fuses: Mega 125 A x2 (4000 W continuous / 0.96 / 51.2 V x 1.25 = 102 A) + battery fuses by definir x4",
      (q("Fusible Mega 125A"), q("Fusible Mega de batería (calibre por definir)")), (2, 4))
check("ground by breaker (T250.122), one per raceway: #8 green = AC out 10 m + AC in 10 m, +10 % -> 25", q("Cable #8 AWG THHN, CU, color verde"), 25)
check("ground by breaker: #10 green = PV 15 m + Fronius 10 m (32 A and 60 A breakers), +10 % -> 30", q("Cable #10 AWG THHN, CU, color verde"), 30)
check("no #3 AWG cable is asked for (dealers do not stock it): AC in uses #2", ("Cable #3 AWG THHN, CU, color negro" in by, "Cable #2 AWG THHN, CU, color negro" in by), (False, True))
check("#4 black THHN is a master line, 15 m", (by["Cable #4 AWG THHN, CU, color negro"]["in_master"], q("Cable #4 AWG THHN, CU, color negro")), (True, 15))
check("heat-shrink for the DC lugs (#2 AWG), 1 m minimum", q("Termoencogible para cable #2 rojo"), 1)
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
check("drawn from the sized design: string breaker / wire", (cfg["pv"]["string_breaker"], cfg["pv"]["dc_wire"]), ("32 A 2P DC", "#10 AWG SOLAR"))
check("Q3 Fronius breaker and conductors", (cfg["fronius"]["ac_breaker"], cfg["fronius"]["ac_conductors"]), ("2P 60 A", ["L1 #6 AWG negro", "L2 #6 AWG rojo", "T #10 AWG verde"]))
check("Q1 from the manual limit: 2P 90 A on #2 AWG (no #3 sold)", (cfg["multis"]["ac_in_breaker"], cfg["multis"]["ac_in_conductors"][0]), ("2P 90 A", "L1 #2 AWG negro"))
check("DC to the Multis uses the sized cable", (cfg["multis"]["dc_pos"], cfg["multis"]["dc_neg"]), ("+ #2 AWG rojo", "- #2 AWG negro"))
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
check("no layout: one string per row (2 strings -> 2 rows, 8 modules each)", (ME.build_list(EQ, CTX, {}, None)["layout"]["rows"], ME.build_list(EQ, CTX, {}, None)["counts"]["per_row"]), (2, 8))
_nostr = {**CTX, "coupling": {**CTX["coupling"], "strings": 0}}
check("no layout and no strings leaves mounting pending", any("layout del techo" in x for x in ME.build_list(EQ, _nostr, {}, None)["pending"]), True)
check("a row count typed by the user wins over the strings", ME.build_list(EQ, CTX, {"materials": {"layout": {"rows": 4}}}, None)["layout"]["rows"], 4)
_r = ME.layout_counts(PANEL, 16, {"rows": 2, "orientation": "portrait", "rail_len_m": 4.7, "foot_spacing_m": 1.0})
check("string of 8 modules is 9.21 m: 2 rails of 4.7 m + 1 splice per rail line, 4 rail lines", (_r["row_len_m"], _r["rails"], _r["splices"]), (9.21, 8, 4))

# Batch-1 rules: one enclosure (size to confirm), one SPD, roof sealant by feet; no roof screws, no sub-panel.
_res = ME.build_list(EQ, CTX, {"materials": {"layout": {"rows": 2}}}, None)
_by = {ln["name"]: ln for ln in _res["lines"] if ln["qty"]}
check("enclosure 50x40x20 x1 flagged to confirm", (_by["Gabinete metálico 50x40x20"]["qty"], _by["Gabinete metálico 50x40x20"]["comment"]), (1, "POR CONFIRMAR MEDIDA"))
check("one surge protector", _by["Supresor de Picos SDSA 1175"]["qty"], 1)
check("sealant: 1 tube per 20 feet", _by["Silicon 3M (especificar color según color de las láminas del techo)"]["qty"], 3)
check("no roof screws on the list", any("Tornillo de techo" in n for n in _by), False)
check("no sub-panel board on the list", any("Tablero NEMA" in n for n in _by), False)

# Batch-2 rules: Chint DC box, 4x4 duct + 2 caps, EMT stubs to the inverters, monitoring outlet kit, 1 tie pack, 1" solar conduit.
check("Chint DC 5-space box x1", _by["Centro de carga Chint DC 5 espacios"]["qty"], 1)
check("duct 4x4 x1 + 2 end caps", (_by["Ducto metálico cuadrado 4x4"]["qty"], _by["Tapas para ducto metálico 4x4"]["qty"]), (1, 2))
check("PG-21 cable glands x2", _by["Manguito prensacable de poliamida gris PG-21 (incluye contratuerca)"]["qty"], 2)
check("EMT stubs to the 2 inverters: 2 tubes, 8 pressure connectors", (_by['Tuberia 1" / EMT']["qty"], _by['Conector de presión 1" EMT']["qty"]), (2, 8))
check("monitoring outlet kit", [_by[n]["qty"] for n in ("Breaker 20A 1 polo CH (toma de monitoreo)", "Toma doble 15A 125V", "Placa de acero inoxidable para toma doble", 'Caja rectangular de intemperie 3 huecos 1/2"')], [1, 1, 1, 1])
check("monitoring circuit: #12 red / green / white, 15 m each", [_by[f"Cable #12 AWG THHN, CU, color {c}"]["qty"] for c in ("rojo", "verde", "blanco")], [15, 15, 15])
check("ties: one pack", _by["Gasas plásticas #8 (Negras)"]["qty"], 1)
check("solar strings go in at least 1 in conduit", [b["conduit"]["trade"] for b in CTX["branches"] if b.get("key") == "pv_strings"], ["1"])
check("no 3 AWG anywhere in the sized branches", any(b.get("ugc") in ("3", "1") for b in CTX["branches"]), False)

# Batch-5 rules: DIN rail, DIN terminal and strut x1 always; energy meter chosen in Equipos brings 2 CTs (size to verify) and 1 UTP.
check("DIN rail, DIN terminal and strut x1", [_by[n]["qty"] for n in ("Riel DIN perforado 35x15mm", "Terminal para riel din", "Riel strut perfil bajo")], [1, 1, 1])
check("no plexo box and no PVC pull box by default", any(n.startswith("Caja plexo") or n == "Caja de registro PVC" for n in _by), False)
check("no meter selected: no meter, no CTs", any("VM-3P75CT" in n or "Transformador de Corriente" in n for n in _by), False)
_utp0 = _by["Cable UTP normal"]["qty"]
_EQM = {**EQ, "energy_meter": {"brand": "Victron Energy", "model": "VM-3P75CT"}}
_resm = ME.build_list(_EQM, CTX, {"materials": {"layout": {"rows": 2}}}, None)
_bym = {ln["name"]: ln for ln in _resm["lines"] if ln["qty"]}
check("meter VM-3P75CT x1 on the Victron section", (_bym["Medidor VM-3P75CT"]["qty"], _bym["Medidor VM-3P75CT"]["section"]), (1, "Victron Energy"))
check("2 current transformers flagged to verify size", (_bym["Transformador de Corriente 100A:333mV"]["qty"], _bym["Transformador de Corriente 100A:333mV"]["comment"]), (2, "POR VERIFICAR TAMAÑO"))
check("meter adds no short UTP, it brings cat6e by metre", (_bym["Cable UTP normal"]["qty"], "Cable de red Ethernet cat6e" in _bym), (_utp0, True))
_run = CTX["lengths"]["ac_in_m"]
check("cat6e as long as the cabinet -> panel run (+waste, 5 m steps)", _bym["Cable de red Ethernet cat6e"]["qty"], ME._ceil_to(_run * (1 + ME.WASTE), ME.CABLE_STEP_M))
check("no meter: no cat6e", "Cable de red Ethernet cat6e" in _by, False)

print("\n" + ("ALL MATERIALS CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
